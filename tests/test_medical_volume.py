"""Native-grid NIfTI round trips and isolation from existing editor modes."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from annotator import MainWindow, get_parser, main
import numpy as np
from PIL import Image
from qtpy import QtCore, QtWidgets
from shape import Shape
from utils.geometry_operations import exact_mask_polygons
from utils.medical_volume import NiftiVolume, VolumeError

try:
    import nibabel as nib
except ImportError:
    nib = None


@unittest.skipIf(nib is None, "Install requirements-volume.txt for NIfTI tests")
class VolumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.data = np.arange(24 * 18 * 4, dtype=np.int16).reshape(24, 18, 4)
        self.affine = np.array([[-0.7, .1, 0, 20], [0, 1.3, .2, -10], [0, 0, 3.2, 5], [0, 0, 0, 1]])
        self.source = self.write_volume(self.root / "scan.nii.gz")
        self.sources = []
        self.window = MainWindow(global_w=1600, global_h=1000)
        self.window.setOutputDirectory(str(self.output))
        self.patches = [patch("annotator.QMessageBox.warning"), patch("annotator.QMessageBox.information"),
                        patch("annotator.QMessageBox.question", return_value=QtWidgets.QMessageBox.Yes),
                        patch.object(self.window, "_runVideoTask", side_effect=lambda message, work: work())]
        self.warning, self.information, self.question, self.runner = [p.start() for p in self.patches]

    def tearDown(self):
        self.window.setClean()
        self.window.close()
        for source in self.sources:
            source.close()
        for item in self.patches:
            item.stop()
        self.app.removeEventFilter(self.window)
        self.window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def write_volume(self, path, data=None, nifti2=False):
        source = (nib.Nifti2Image if nifti2 else nib.Nifti1Image)(self.data if data is None else data, self.affine)
        source.set_qform(self.affine, code=2)
        source.set_sform(self.affine, code=4)
        source.header.set_xyzt_units("mm", "sec")
        nib.save(source, path)
        return path

    def read_source(self, path=None):
        source = NiftiVolume(path or self.source)
        self.sources.append(source)
        return source

    def record(self, source, index=0, group=0, points=None):
        return {"medical_volume": source.metadata(index), "imageWidth": 24, "imageHeight": 18,
                "shapes": [{"label": "target", "group_id": group, "shape_type": "polygon",
                            "points": points or [[2, 2], [8, 2], [8, 8], [2, 8]], "flags": {}}]}

    def save_record(self, source, index=0, record=None):
        folder = self.output / source.folder_name
        folder.mkdir(exist_ok=True)
        path = folder / f"slice_{index:05}.json"
        path.write_text(json.dumps(record or self.record(source, index)), encoding="utf-8")
        return folder

    def test_native_transpose_consistent_window_scaling_and_source_bytes_unchanged(self):
        before = self.source.read_bytes()
        source = self.read_source()
        source.use_render(source.render())
        shown = np.asarray(Image.open(source.paths[2]))
        expected = np.rint((self.data[:, :, 2].T - source.low) / (source.high - source.low) * 255).astype(np.uint8)
        np.testing.assert_array_equal(shown, expected)
        source.use_render(source.render(100, 200))
        np.testing.assert_array_equal(source.slice(2), self.data[:, :, 2])
        self.assertEqual(before, self.source.read_bytes())

    def test_export_preserves_native_affine_qform_sform_units_and_zero_class(self):
        for nifti2 in (False, True):
            with self.subTest(nifti2=nifti2):
                path = self.write_volume(self.root / f"source{nifti2}.nii", nifti2=nifti2)
                source = self.read_source(path)
                folder = self.save_record(source)
                bundle = source.export(folder, self.root)
                result = nib.load(bundle / "segmentation.nii.gz")
                original = nib.load(path)
                self.assertIs(type(result), type(original))
                self.assertEqual(result.shape, self.data.shape)
                np.testing.assert_allclose(result.affine, original.affine)
                np.testing.assert_allclose(result.get_qform(), original.get_qform())
                np.testing.assert_allclose(result.get_sform(), original.get_sform())
                self.assertEqual((int(result.header["qform_code"]), int(result.header["sform_code"])), (2, 4))
                self.assertEqual(result.header.get_xyzt_units(), original.header.get_xyzt_units())
                self.assertEqual(result.get_data_dtype(), np.dtype("uint32"))
                self.assertEqual(int(result.dataobj[3, 3, 0]), 1)
                self.assertEqual(int(result.dataobj[3, 3, 1]), 0)
                sidecar = json.loads((bundle / "segmentation.json").read_text())
                self.assertEqual(sidecar["classes"][0]["group_id"], 0)
                self.assertEqual(sidecar["unannotated_slices"], [1, 2, 3])

    def test_holes_single_pixels_hidden_parts_and_overlap_order_survive_export(self):
        source = self.read_source()
        mask = np.zeros((18, 24), np.uint8)
        mask[2:15, 2:18] = 1
        mask[6:10, 6:10] = 0
        mask[-1, -1] = 1
        document = self.record(source)
        document["shapes"] = [dict(label="target", group_id=0, shape_type="polygon", points=p, flags={})
                              for p in exact_mask_polygons(mask)]
        folder = self.save_record(source, record=document)
        result = nib.load(source.export(folder, self.root) / "segmentation.nii.gz")
        np.testing.assert_array_equal(np.asarray(result.dataobj)[:, :, 0].T, mask)
        document["shapes"].append(dict(label="other", group_id=4, shape_type="polygon",
                                      points=[[3, 3], [5, 3], [5, 5], [3, 5]], flags={}))
        self.save_record(source, record=document)
        result = nib.load(source.export(folder, self.root) / "segmentation.nii.gz")
        self.assertEqual(int(result.dataobj[4, 4, 0]), 5)

    def test_malformed_or_wrong_source_annotations_never_publish_partial_export(self):
        source = self.read_source()
        for change in ("identity", "negative_group", "nonpolygon", "nonfinite"):
            with self.subTest(change=change):
                doc = self.record(source)
                if change == "identity":
                    doc["medical_volume"]["slice_index"] = 3
                elif change == "negative_group":
                    doc["shapes"][0]["group_id"] = -1
                elif change == "nonpolygon":
                    doc["shapes"][0]["shape_type"] = "circle"
                else:
                    doc["shapes"][0]["points"][0][0] = float("nan")
                folder = self.save_record(source, record=doc)
                before = set(self.root.iterdir())
                with self.assertRaises(VolumeError):
                    source.export(folder, self.root)
                self.assertEqual(set(self.root.iterdir()), before)

    def test_same_named_different_inputs_have_separate_output_names(self):
        other = self.root / "other"
        other.mkdir()
        second = self.write_volume(other / "scan.nii.gz", data=self.data + 1)
        self.assertNotEqual(self.read_source().folder_name, self.read_source(second).folder_name)

    def test_source_scaling_is_displayed_but_does_not_scale_exported_labels(self):
        path = self.root / "scaled.nii.gz"
        image = nib.Nifti1Image(self.data, self.affine)
        image.header.set_slope_inter(2, -100)
        nib.save(image, path)
        source = self.read_source(path)
        np.testing.assert_array_equal(source.slice(1), self.data[:, :, 1] * 2 - 100)
        bundle = source.export(self.save_record(source), self.root)
        result = nib.load(bundle / "segmentation.nii.gz")
        self.assertEqual(int(result.dataobj[3, 3, 0]), 1)

    def test_changed_source_and_failed_write_do_not_publish_export(self):
        source = self.read_source()
        folder = self.save_record(source)
        before = set(self.root.iterdir())
        with patch.object(source.nib, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                source.export(folder, self.root)
        self.assertEqual(set(self.root.iterdir()), before)
        self.source.write_bytes(self.source.read_bytes() + b"changed")
        with self.assertRaisesRegex(VolumeError, "changed"):
            source.export(folder, self.root)

    def test_apply_window_keeps_completed_edit_undo_available(self):
        self.window.openVolume(str(self.source))
        shape = Shape(label="target", group_id=0, shape_type="polygon")
        shape.points = [QtCore.QPointF(2, 2), QtCore.QPointF(8, 2), QtCore.QPointF(8, 8)]
        self.window.loadShapes([shape])
        self.window.canvas.shapes[0].points[0] = QtCore.QPointF(3, 3)
        self.window.canvas.storeShapes()
        self.window.setDirty()
        self.assertTrue(self.window.applyVolumeWindow())
        self.assertTrue(self.window.canvas.isShapeRestorable)
        self.window.undoShapeEdit()
        self.assertEqual(self.window.canvas.shapes[0].points[0], QtCore.QPointF(2, 2))

    def test_volume_leaves_cleanly_for_images_and_video_and_blocks_review(self):
        self.window.openVolume(str(self.source))
        cache = self.window.volume.cache.name
        images = self.root / "images"
        images.mkdir()
        Image.new("RGB", (40, 32)).save(images / "frame.png")
        with patch("annotator.QFileDialog.getExistingDirectory", return_value=str(images)):
            self.window.clickFileChoose()
        self.assertIsNone(self.window.volume)
        self.assertFalse(Path(cache).exists())
        self.assertEqual(Path(self.window.current_img), images / "frame.png")
        self.window.openVolume(str(self.source))
        self.assertTrue(self.window.openVideoDirectory(str(images)))
        self.assertIsNone(self.window.volume)
        self.assertTrue(self.window.video_mode)
        self.window.review_config = object()
        self.assertFalse(self.window.openVolume(str(self.source)))
        self.window.review_config = None

    def test_rejects_4d_and_corrupt_files_without_replacing_open_dataset(self):
        self.assertTrue(self.window.openVolume(str(self.source)))
        volume, image = self.window.volume, self.window.current_img
        bad4d = self.write_volume(self.root / "four.nii", data=np.zeros((4, 4, 4, 2), np.int16))
        corrupt = self.root / "corrupt.nii.gz"
        corrupt.write_bytes(b"not a nifti")
        for path in (bad4d, corrupt):
            self.assertFalse(self.window.openVolume(str(path)))
            self.assertIs(self.window.volume, volume)
            self.assertEqual(self.window.current_img, image)

    def test_gui_save_navigation_window_resume_and_class_id_roundtrip(self):
        self.assertTrue(self.window.openVolume(str(self.source)))
        shape = Shape(label="target", group_id=0, shape_type="polygon")
        shape.points = [QtCore.QPointF(2, 2), QtCore.QPointF(8, 2), QtCore.QPointF(8, 8)]
        shape.close()
        self.window.loadShapes([shape])
        self.window.setDirty()
        self.window.clickButtonNext()
        self.assertEqual(self.window.current_img_index, 1)
        folder = self.output / self.window.volume.folder_name
        doc = json.loads((folder / "slice_00000.json").read_text())
        self.assertEqual(doc["shapes"][0]["group_id"], 0)
        self.assertEqual(doc["medical_volume"]["slice_index"], 0)
        self.window.clickButtonLast()
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.window.volume_width.setValue(200)
        self.assertTrue(self.window.applyVolumeWindow())
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertTrue(self.window.openVolume(str(self.source)))
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertFalse(self.window.video_mode)
        self.assertFalse(self.window.actions.propagateVideo.isEnabled())

    def test_failed_save_blocks_switch_and_window_change(self):
        self.window.openVolume(str(self.source))
        volume = self.window.volume
        self.window.setDirty()
        with patch.object(self.window, "saveFile", return_value=False):
            self.assertFalse(self.window.openVolume(str(self.source)))
            self.assertFalse(self.window.applyVolumeWindow())
        self.assertIs(self.window.volume, volume)
        self.assertTrue(self.window.actions.save.isEnabled())

    def test_sam_accept_and_export_button_handle_small_regions_and_missing_slices(self):
        self.window.openVolume(str(self.source))
        mask = np.zeros((18, 24), dtype=np.uint8)
        mask[3:10, 3:12] = 1
        mask[-1, -1] = 1
        self.window._buildSamProposals(np.stack([mask] * 3), [.9, .8, .7])
        with patch.object(self.window.labelDialog, "popUp", return_value=("target", {}, 0, "")):
            self.window.addSamMask()
        self.question.return_value = QtWidgets.QMessageBox.Cancel
        self.assertFalse(self.window.exportVolumeMask())
        self.assertFalse(list(self.output.glob("*_segmentation_*")))
        self.question.return_value = QtWidgets.QMessageBox.Yes
        with patch("annotator.QFileDialog.getExistingDirectory", return_value=str(self.output)):
            self.assertTrue(self.window.exportVolumeMask())
        bundles = list(self.output.glob("*_segmentation_*"))
        self.assertEqual(len(bundles), 1)
        result = nib.load(bundles[0] / "segmentation.nii.gz")
        np.testing.assert_array_equal(np.asarray(result.dataobj)[:, :, 0].T, mask)

    def test_missing_dependency_is_actionable_and_cli_rejects_mixed_modes(self):
        import builtins
        original = builtins.__import__
        def no_nib(name, *args, **kwargs):
            if name == "nibabel":
                raise ImportError("missing")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=no_nib):
            with self.assertRaisesRegex(VolumeError, "requirements-volume"):
                NiftiVolume(self.source)
        self.assertEqual(get_parser().parse_args(["--volume", str(self.source)]).volume, str(self.source))
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            main(["--volume", str(self.source), "--review"])


if __name__ == "__main__":
    unittest.main()
