"""Patient-space DICOM geometry, identity and GUI regressions on nonclinical data."""

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from annotator import MainWindow, get_parser, main
import numpy as np
from PIL import Image
from qtpy import QtCore, QtWidgets
from shape import Shape
from utils.dicom_volume import DicomVolume, discover_dicom_series
from utils.medical_volume import VolumeError

try:
    import nibabel as nib
    import pydicom
    from scripts.create_dicom_test_data import write_series
except ImportError:
    nib = pydicom = None


@unittest.skipIf(pydicom is None, "Install requirements-dicom.txt for DICOM tests")
class DicomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "dicom"
        self.uid, self.files = write_series(self.folder, slices=4, shape=(18, 24))
        self.output = self.root / "output"
        self.output.mkdir()
        self.sources = []
        self.window = MainWindow(global_w=1600, global_h=1000)
        self.window.setOutputDirectory(str(self.output))
        self.patches = [patch("annotator.QMessageBox.warning"), patch("annotator.QMessageBox.information"),
                        patch("annotator.QMessageBox.question", return_value=QtWidgets.QMessageBox.Yes),
                        patch.object(self.window, "_runVideoTask", side_effect=lambda text, work: work())]
        self.warning, self.info, self.question, self.runner = [p.start() for p in self.patches]

    def tearDown(self):
        self.window.setClean()
        self.window.close()
        for source in self.sources:
            source.close()
        for p in self.patches:
            p.stop()
        self.app.removeEventFilter(self.window)
        self.window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def source(self, folder=None):
        source = DicomVolume(discover_dicom_series(folder or self.folder)[0])
        self.sources.append(source)
        return source

    def edit(self, index, change):
        ds = pydicom.dcmread(self.files[index])
        change(ds)
        ds.save_as(self.files[index], enforce_file_format=True)

    def test_spatial_order_non_square_voxels_modality_scaling_and_ras_affine(self):
        before = [path.read_bytes() for path in self.files]
        source = self.source()
        self.assertEqual(source.shape, (24, 18, 4))
        for k in range(4):
            self.assertEqual(source.slice(k)[5, 5], (600 + 10 * k) * 2 - 1000)
            x, y = 5, 6
            lps = np.array([10, 20, 30]) + x * .7 * np.array([.8, .6, 0]) + y * 1.3 * np.array([-.6, .8, 0]) + k * np.array([0, 0, 2.5])
            ras = np.array([-lps[0], -lps[1], lps[2]])
            np.testing.assert_allclose((source.image.affine @ [x, y, k, 1])[:3], ras, atol=1e-5)
        expected = [str(pydicom.dcmread(path, stop_before_pixels=True).SOPInstanceUID) for path in self.files]
        self.assertEqual(source.export_metadata()["dicom"]["ordered_sop_instance_uids"], expected)
        self.assertEqual(source.metadata(2)["dicom"]["sop_instance_uid"], expected[2])
        self.assertEqual([path.read_bytes() for path in self.files], before)

    def test_extensionless_files_and_multiple_series_discovery(self):
        self.files[0].rename(self.folder / "no_extension")
        write_series(self.folder / "mr", modality="MR", slices=3, shape=(18, 24))
        (self.folder / "notes.txt").write_text("not dicom")
        series = discover_dicom_series(self.folder)
        self.assertEqual({s.modality for s in series}, {"CT", "MR"})
        self.assertEqual(sorted(len(s.files) for s in series), [3, 4])

    def test_mono1_display_is_inverted_without_inverting_voxel_intensities(self):
        other = self.root / "mr"
        write_series(other, modality="MR", slices=3, shape=(18, 24), photometric="MONOCHROME1")
        source = self.source(other)
        source.use_render(source.render())
        voxels = source.slice(0)
        expected = 255 - np.rint(np.clip((voxels - source.low) / (source.high - source.low), 0, 1) * 255).astype(np.uint8)
        np.testing.assert_array_equal(np.asarray(Image.open(source.paths[0])), expected.T)
        self.assertEqual(source.slice(0)[5, 5], 600)

    def test_constant_gantry_tilt_uses_exact_sform_instead_of_resampling(self):
        other = self.root / "tilt"
        write_series(other, slices=4, shape=(18, 24), step=(.3, -.2, 2.5))
        source = self.source(other)
        np.testing.assert_allclose(source.image.affine[:3, 2], [-.3, .2, 2.5], atol=1e-6)
        self.assertEqual(int(source.image.header["qform_code"]), 0)
        self.assertEqual(int(source.image.header["sform_code"]), 1)

    def test_duplicate_mixed_irregular_and_unsupported_stacks_are_rejected(self):
        variants = (
            lambda ds: setattr(ds, "ImagePositionPatient", [10, 20, 30]),
            lambda ds: setattr(ds, "ImagePositionPatient", [10, 20, 40]),
            lambda ds: setattr(ds, "ImageOrientationPatient", [1, 0, 0, 0, 1, 0]),
            lambda ds: setattr(ds, "PixelSpacing", [2, 2]),
            lambda ds: setattr(ds, "NumberOfFrames", 2),
            lambda ds: setattr(ds, "ImageType", ["ORIGINAL", "PRIMARY", "MOSAIC"]),
            lambda ds: setattr(ds, "RescaleSlope", 0),
            lambda ds: setattr(ds, "SamplesPerPixel", 3),
            lambda ds: ds.__delitem__("FrameOfReferenceUID"),
        )
        original = self.files[1].read_bytes()
        for change in variants:
            with self.subTest(change=change):
                self.files[1].write_bytes(original)
                self.edit(1, change)
                with self.assertRaises(VolumeError):
                    self.source()
        self.files[1].write_bytes(original)
        shutil.copyfile(self.files[0], self.folder / "duplicate.dcm")
        with self.assertRaisesRegex(VolumeError, "duplicate SOP"):
            self.source()

    def test_compressed_transfer_and_corrupt_pixel_payload_are_not_silently_loaded(self):
        from pydicom.encaps import encapsulate
        from pydicom.uid import JPEG2000Lossless
        original = self.files[0].read_bytes()
        def compressed(ds):
            ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
            ds.PixelData = encapsulate([b"not a jpeg2000 stream"])
            ds["PixelData"].is_undefined_length = True
        self.edit(0, compressed)
        with self.assertRaisesRegex(VolumeError, "uncompressed"):
            self.source()
        self.files[0].write_bytes(original)
        self.edit(0, lambda ds: setattr(ds, "PixelData", b"\0\0"))
        with self.assertRaisesRegex(VolumeError, "decode"):
            self.source()

    def test_folder_changes_invalidate_source_but_normal_outputs_do_not(self):
        source = self.source()
        (self.folder / "output.json").write_text("{}")
        source.check_source()
        self.files[1].write_bytes(self.files[1].read_bytes() + b"changed")
        with self.assertRaisesRegex(VolumeError, "changed"):
            source.check_source()

    def test_series_chooser_cancel_uid_selection_save_resume_and_mask_export(self):
        write_series(self.folder / "mr", modality="MR", slices=3, shape=(18, 24))
        current = self.window.current_img
        with patch("annotator.QtWidgets.QInputDialog.getItem", return_value=("", False)):
            self.assertFalse(self.window.openDicomDirectory(str(self.folder)))
        self.assertEqual(self.window.current_img, current)
        self.assertTrue(self.window.openDicomDirectory(str(self.folder), self.uid))
        shape = Shape(label="target", group_id=0, shape_type="polygon")
        shape.points = [QtCore.QPointF(3, 3), QtCore.QPointF(8, 3), QtCore.QPointF(8, 8)]
        shape.close()
        self.window.loadShapes([shape])
        self.window.setDirty()
        self.window.clickButtonNext()
        self.window.clickButtonLast()
        self.assertEqual(len(self.window.canvas.shapes), 1)
        source = self.window.volume
        folder = self.output / source.folder_name
        bundle = source.export(folder, self.output)
        result = nib.load(bundle / "segmentation.nii.gz")
        np.testing.assert_allclose(result.affine, source.image.affine)
        self.assertEqual(int(result.dataobj[5, 4, 0]), 1)
        sidecar = (bundle / "segmentation.json").read_text()
        self.assertNotIn("SYNTHETIC_NO_PATIENT", sidecar)
        self.assertNotIn("SYNTHETIC^EXAMPLE", sidecar)
        self.assertEqual(json.loads(sidecar)["source"]["source_format"], "DICOM-series")
        self.assertTrue(self.window.openDicomDirectory(str(self.folder), self.uid))
        self.assertEqual(len(self.window.canvas.shapes), 1)

    def test_failed_save_invalid_scan_and_missing_uid_preserve_current_volume(self):
        self.window.openDicomDirectory(str(self.folder))
        volume = self.window.volume
        self.window.setDirty()
        with patch.object(self.window, "saveFile", return_value=False):
            self.assertFalse(self.window.openDicomDirectory(str(self.folder)))
        self.assertIs(self.window.volume, volume)
        self.assertFalse(self.window.openDicomDirectory(str(self.folder), "1.2.3.999"))
        self.assertIs(self.window.volume, volume)
        broken = self.root / "broken"
        broken.mkdir()
        (broken / "bad.dcm").write_bytes(b"invalid")
        self.assertFalse(self.window.openDicomDirectory(str(broken)))
        self.assertIs(self.window.volume, volume)

    def test_missing_dependency_and_cli_mode_guards(self):
        import builtins
        original = builtins.__import__
        def no_dicom(name, *args, **kwargs):
            if name == "pydicom":
                raise ImportError("missing")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=no_dicom):
            with self.assertRaisesRegex(VolumeError, "requirements-dicom"):
                discover_dicom_series(self.folder)
        self.assertEqual(get_parser().parse_args(["--dicom-directory", "scan"]).dicom_directory, "scan")
        for args in (["--dicom-series", "1.2.3"], ["--dicom-directory", "scan", "--review"],
                     ["--dicom-directory", "scan", "--volume", "scan.nii"]):
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                main(args)

    def test_per_slice_rescale_and_modality_lut_are_applied_before_display(self):
        self.edit(1, lambda ds: setattr(ds, "RescaleSlope", 3))
        source = self.source()
        self.assertEqual(source.slice(1)[5, 5], 610 * 3 - 1000)
        source.close()
        self.sources.remove(source)
        from pydicom.dataset import Dataset
        def lut(ds):
            del ds.RescaleSlope
            del ds.RescaleIntercept
            table = Dataset()
            table.ModalityLUTType = "HU"
            table.LUTDescriptor = [1024, 0, 16]
            table.LUTData = (np.arange(1024, dtype=np.uint16) + 10).astype("<u2").tobytes()
            ds.ModalityLUTSequence = [table]
        for index in range(4):
            self.edit(index, lut)
        self.assertEqual(self.source().slice(2)[5, 5], 620 + 10)

    def test_implicit_vr_and_mr_without_rescale(self):
        from pydicom.uid import ImplicitVRLittleEndian
        self.edit(0, lambda ds: setattr(ds.file_meta, "TransferSyntaxUID", ImplicitVRLittleEndian))
        self.assertEqual(self.source().slice(0)[5, 5], 200)
        other = self.root / "mr"
        _, paths = write_series(other, modality="MR", slices=3, shape=(18, 24))
        for path in paths:
            ds = pydicom.dcmread(path)
            del ds.RescaleSlope
            del ds.RescaleIntercept
            ds.save_as(path, enforce_file_format=True)
        self.assertEqual(self.source(other).slice(0)[5, 5], 600)

    def test_series_chooser_accepts_selected_series_and_renamed_sources_resume(self):
        mr_uid, _ = write_series(self.folder / "mr", modality="MR", slices=3, shape=(18, 24))
        chosen = next(s for s in discover_dicom_series(self.folder) if s.uid == mr_uid)
        with patch("annotator.QtWidgets.QInputDialog.getItem", return_value=(chosen.label, True)):
            self.assertTrue(self.window.openDicomDirectory(str(self.folder)))
        self.assertEqual(self.window.volume.shape[2], 3)
        source = self.source(self.folder / "mr")
        identity = source.folder_name
        source.close()
        self.sources.remove(source)
        next((self.folder / "mr").glob("*.dcm")).rename(self.folder / "mr" / "renamed")
        self.assertEqual(self.source(self.folder / "mr").folder_name, identity)

    def test_stcn_adapter_propagates_and_exports_dicom_geometry_and_ids(self):
        from utils.video_tracking import DirectionalSliceTracker
        from tests.test_volume_propagation import SliceBackend
        self.window.openDicomDirectory(str(self.folder))
        shape = Shape(label="target", group_id=0, shape_type="polygon")
        shape.points = [QtCore.QPointF(3, 3), QtCore.QPointF(8, 3), QtCore.QPointF(8, 8)]
        shape.close()
        self.window.addLabel(shape)
        self.window.canvas.loadShapes([shape])
        self.window.labelList.selectItem(self.window.labelList.findItemByShape(shape))
        self.window.video_panel.backend.setCurrentIndex(1)
        backend = SliceBackend()
        with patch.object(self.window, "_makeVideoTracker", return_value=DirectionalSliceTracker(backend, 4)):
            self.assertTrue(self.window.trackVideoSelection())
        self.window.clickButtonNext()
        self.assertTrue(self.window.propagateVideoFrame())
        self.assertTrue(self.window.saveFile())
        document = json.loads(Path(self.window.current_output_filename).read_text())
        self.assertEqual(document["medical_volume"]["dicom"]["series_instance_uid"], self.uid)
        self.assertEqual(document["volume_tracking"]["source"], "stcn_propagated_slice")
        bundle = self.window.volume.export(self.output / self.window.volume.folder_name, self.output)
        result = nib.load(bundle / "segmentation.nii.gz")
        np.testing.assert_allclose(result.affine, self.window.volume.image.affine)
        self.assertTrue(np.any(np.asarray(result.dataobj)[:, :, 1] == 1))

    def test_big_endian_pixels_and_patient_metadata_are_handled_without_copying_headers(self):
        from pydicom.uid import ExplicitVRBigEndian
        ds = pydicom.dcmread(self.files[0])
        pixels = ds.pixel_array.copy()
        ds.file_meta.TransferSyntaxUID = ExplicitVRBigEndian
        ds.PixelData = pixels.astype(">i2").tobytes()
        ds.PatientName = "DO_NOT_COPY_DEMOGRAPHICS"
        ds.add_new((0x0011, 0x1010), "LO", "DO_NOT_COPY_PRIVATE")
        pydicom.dcmwrite(self.files[0], ds, little_endian=False, implicit_vr=False, enforce_file_format=True)
        source = self.source()
        self.assertEqual(source.slice(0)[5, 5], 200)
        metadata = json.dumps(source.export_metadata())
        self.assertNotIn("DO_NOT_COPY", metadata)
        self.assertEqual(bytes(source.image.header["descrip"]).rstrip(b"\0"), b"")

    def test_slice_sop_mismatch_blocks_resume_and_export(self):
        self.window.openDicomDirectory(str(self.folder))
        self.assertTrue(self.window._saveFile(self.window.current_output_filename))
        path = Path(self.window.current_output_filename)
        document = json.loads(path.read_text())
        document["medical_volume"]["dicom"]["sop_instance_uid"] = "1.2.3.999"
        path.write_text(json.dumps(document))
        current = self.window.volume
        self.assertFalse(self.window.openDicomDirectory(str(self.folder)))
        self.assertIs(self.window.volume, current)
        with self.assertRaisesRegex(VolumeError, "slice identities"):
            current.export(path.parent, self.output)


if __name__ == "__main__":
    unittest.main()
