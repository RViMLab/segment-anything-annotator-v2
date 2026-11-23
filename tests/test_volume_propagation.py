"""Experimental slice tracking must preserve native geometry and video behaviour."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from annotator import MainWindow
import numpy as np
from qtpy import QtCore, QtWidgets
from shape import Shape
from utils.annotation_document import shape_to_annotation
from utils.video_tracking import DirectionalSliceTracker, VideoTrackingError

try:
    import nibabel as nib
except ImportError:
    nib = None


class SliceBackend:
    reference_index = None

    def __init__(self):
        self.reference_indices = []
        self.commits = self.discards = self.predictions = 0

    def start(self, image, masks, index):
        self.masks = [mask.copy() for mask in masks]
        self.reference_index, self.reference_indices = index, [index]

    def correct(self, image, masks, index):
        self.masks = [mask.copy() for mask in masks]
        self.reference_index = index
        self.reference_indices = [i for i in self.reference_indices if i < index] + [index]

    def predict(self, image, index):
        self.predictions += 1
        return [np.roll(mask, 1, axis=1) for mask in self.masks]

    def commit_prediction(self):
        self.commits += 1

    def discard_prediction(self):
        self.discards += 1


class DirectionTests(unittest.TestCase):
    def test_reverse_indices_references_corrections_and_wrong_direction(self):
        backend = SliceBackend()
        tracker = DirectionalSliceTracker(backend, 6, -1)
        tracker.start("slice4", [np.ones((4, 4), np.uint8)], 4)
        self.assertEqual(backend.reference_index, 1)
        self.assertEqual(tracker.reference_index, 4)
        self.assertEqual(tracker.reference_indices, [4])
        tracker.predict("slice3", 3)
        tracker.correct("slice3", [np.ones((4, 4), np.uint8)], 3)
        self.assertEqual(tracker.reference_indices, [4, 3])
        tracker.commit_prediction()
        tracker.discard_prediction()
        self.assertEqual((backend.commits, backend.discards), (1, 1))
        with self.assertRaises(VideoTrackingError):
            tracker.predict("slice4", 4)
        self.assertEqual(backend.predictions, 1)
        with self.assertRaises(VideoTrackingError):
            tracker.predict("outside", -1)


@unittest.skipIf(nib is None, "Install requirements-volume.txt for NIfTI tests")
class SlicePropagationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "volume.nii.gz"
        self.affine = np.array([[-.7, .1, 0, 20], [0, 1.2, .2, 10], [0, 0, 2.5, -4], [0, 0, 0, 1]])
        nib.save(nib.Nifti1Image(np.arange(40 * 32 * 6, dtype=np.int16).reshape(40, 32, 6), self.affine), self.path)
        self.output = self.root / "output"
        self.output.mkdir()
        self.window = MainWindow(global_w=1600, global_h=1000)
        self.window.setOutputDirectory(str(self.output))
        self.backends = []
        self.patches = [patch("annotator.QMessageBox.warning"), patch("annotator.QMessageBox.information"),
                        patch("annotator.QMessageBox.question", return_value=QtWidgets.QMessageBox.Yes),
                        patch.object(self.window, "_runVideoTask", side_effect=lambda text, work: work()),
                        patch.object(self.window, "_makeVideoTracker", side_effect=self.factory)]
        self.warning, self.info, self.question, self.runner, self.make = [p.start() for p in self.patches]
        self.assertTrue(self.window.openVolume(str(self.path)))
        self.window.video_panel.backend.setCurrentIndex(1)

    def factory(self):
        backend = SliceBackend()
        self.backends.append(backend)
        return DirectionalSliceTracker(backend, self.window.img_len, self.window.video_panel.direction.currentData())

    def tearDown(self):
        self.window.setClean()
        self.window.close()
        for p in self.patches:
            p.stop()
        self.app.removeEventFilter(self.window)
        self.window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def go(self, index):
        while self.window.current_img_index < index:
            self.window.clickButtonNext()
        while self.window.current_img_index > index:
            self.window.clickButtonLast()

    def polygon(self, group=0, x=3, label="target"):
        shape = Shape(label=label, group_id=group, shape_type="polygon")
        shape.points = [QtCore.QPointF(x, 3), QtCore.QPointF(x + 8, 3),
                        QtCore.QPointF(x + 8, 15), QtCore.QPointF(x, 15)]
        shape.close()
        shape.other_data["description"] = "retain"
        self.window.addLabel(shape)
        self.window.canvas.loadShapes([item.shape() for item in self.window.labelList])
        self.window.labelList.selectItem(self.window.labelList.findItemByShape(shape))
        return shape

    def start(self, direction=1):
        self.go(2)
        self.window.video_panel.direction.setCurrentIndex(0 if direction == 1 else 1)
        self.polygon()
        self.assertTrue(self.window.trackVideoSelection())
        return self.window.video_tracker

    def test_forward_and_reverse_propagation_corrections_save_and_export_provenance(self):
        for direction in (1, -1):
            with self.subTest(direction=direction):
                self.window.stopVideoTracking()
                self.go(2)
                if not self.window.canvas.shapes:
                    self.polygon()
                for item in self.window.labelList:
                    self.window.labelList.selectItem(item)
                self.window.video_panel.direction.setCurrentIndex(0 if direction == 1 else 1)
                self.assertTrue(self.window.trackVideoSelection())
                identity = self.window.video_objects[0]["id"]
                target = 2 + direction
                self.go(target)
                self.assertTrue(self.window.propagateVideoFrame())
                self.assertEqual(self.backends[-1].commits, 1)
                for shape in self.window.canvas.shapes:
                    self.assertEqual((shape.group_id, shape.other_data["video_object_id"]), (0, identity))
                    self.assertEqual(shape.other_data["description"], "retain")
                self.assertTrue(self.window.saveFile())
                document = json.loads(Path(self.window.current_output_filename).read_text())
                self.assertNotIn("video_annotation", document)
                provenance = document["volume_tracking"]
                self.assertEqual(provenance["source"], "stcn_propagated_slice")
                self.assertEqual(provenance["direction"], direction)
                self.assertEqual(provenance["reference_slice_indices"], [2])
                self.assertTrue(provenance["experimental"])
                self.assertTrue(self.window.useVideoCorrection())
                self.go(target + direction)
                self.assertTrue(self.window.propagateVideoFrame())
                self.assertEqual(self.window._video_frame_metadata["reference_slice_indices"], [2, target])
                self.assertTrue(self.window.saveFile())
                folder = self.output / self.window.volume.folder_name
                bundle = self.window.volume.export(folder, self.root)
                mask = nib.load(bundle / "segmentation.nii.gz")
                np.testing.assert_allclose(mask.affine, self.affine)
                sidecar = json.loads((bundle / "segmentation.json").read_text())
                self.assertEqual(sidecar["slice_tracking_provenance"][str(target)]["direction"], direction)

    def test_wrong_direction_and_failed_predictions_leave_annotations_and_memory(self):
        tracker = self.start(-1)
        self.go(3)
        before = [shape_to_annotation(s) for s in self.window.canvas.shapes]
        self.assertFalse(self.window.propagateVideoFrame())
        self.assertEqual(tracker.backend.predictions, 0)
        self.assertEqual([shape_to_annotation(s) for s in self.window.canvas.shapes], before)
        self.go(1)
        with patch.object(tracker.backend, "predict", return_value=[np.ones((2, 2), np.uint8)]):
            self.assertFalse(self.window.propagateVideoFrame())
        self.assertEqual(tracker.backend.commits, 0)
        self.assertGreaterEqual(tracker.backend.discards, 1)

    def test_window_success_resets_tracking_failure_preserves_it_and_undo_stops(self):
        tracker = self.start()
        self.assertFalse(self.window.video_panel.direction.isEnabled())
        with patch.object(self.window.volume, "render", side_effect=ValueError("failed window")):
            self.assertFalse(self.window.applyVolumeWindow())
        self.assertIs(self.window.video_tracker, tracker)
        self.window.volume_width.setValue(100)
        self.assertTrue(self.window.applyVolumeWindow())
        self.assertIsNone(self.window.video_tracker)
        self.assertTrue(self.window.video_panel.direction.isEnabled())
        for item in self.window.labelList:
            self.window.labelList.selectItem(item)
        self.assertTrue(self.window.trackVideoSelection())
        self.go(3)
        self.window.propagateVideoFrame()
        self.window.undoShapeEdit()
        self.assertIsNone(self.window.video_tracker)
        self.assertEqual(self.window.canvas.shapes, [])

    def test_changed_source_or_programmatic_direction_cannot_reuse_memory(self):
        tracker = self.start()
        self.go(3)
        self.window.video_panel.direction.setCurrentIndex(1)
        self.assertFalse(self.window.propagateVideoFrame())
        self.assertIsNone(self.window.video_tracker)
        self.assertEqual(tracker.backend.predictions, 0)
        self.go(2)
        self.window.video_panel.direction.setCurrentIndex(0)
        for item in self.window.labelList:
            self.window.labelList.selectItem(item)
        self.assertTrue(self.window.trackVideoSelection())
        self.path.write_bytes(self.path.read_bytes() + b"changed")
        self.assertFalse(self.window.propagateVideoFrame())
        self.assertIsNone(self.window.video_tracker)

    def test_cancelled_replacement_and_empty_prediction_preserve_unrelated_objects(self):
        tracker = self.start()
        self.go(3)
        other = self.polygon(group=4, x=23, label="other")
        self.window.setClean()
        self.question.return_value = QtWidgets.QMessageBox.Cancel
        self.assertFalse(self.window.propagateVideoFrame())
        self.assertEqual(tracker.backend.predictions, 0)
        self.question.return_value = QtWidgets.QMessageBox.Yes
        with patch.object(tracker.backend, "predict", return_value=[np.zeros((32, 40), np.uint8)]):
            self.assertTrue(self.window.propagateVideoFrame())
        self.assertEqual(self.window.canvas.shapes, [other])
        self.assertEqual(tracker.backend.commits, 1)
        self.assertFalse(self.window.useVideoCorrection())

    def test_explicit_backend_unknown_metadata_and_reopening_starts_without_memory(self):
        self.polygon()
        self.window.video_panel.backend.setCurrentIndex(0)
        self.assertFalse(self.window.trackVideoSelection())
        self.make.assert_not_called()
        self.window.video_panel.backend.setCurrentIndex(1)
        self.window._video_frame_metadata = "external reserved value"
        self.assertFalse(self.window.trackVideoSelection())
        self.window._video_frame_metadata = None
        self.assertTrue(self.window.trackVideoSelection())
        self.window.saveFile()
        self.assertTrue(self.window.openVolume(str(self.path)))
        self.assertIsNone(self.window.video_tracker)
        self.assertFalse(self.window.actions.propagateVideo.isEnabled())
        self.assertEqual(self.window._video_frame_metadata["source"], "manual_keyframe")
        self.assertEqual(self.window.video_panel.backend.currentData(), None)

    def test_empty_prediction_undo_restores_provenance_even_with_identical_geometry(self):
        tracker = self.start()
        self.go(3)
        self.assertIsNone(self.window._video_frame_metadata)
        with patch.object(tracker.backend, "predict", return_value=[np.zeros((32, 40), np.uint8)]):
            self.assertTrue(self.window.propagateVideoFrame())
        self.assertEqual(self.window.canvas.shapes, [])
        self.assertEqual(self.window._video_frame_metadata["source"], "stcn_propagated_slice")
        self.window.undoShapeEdit()
        self.assertIsNone(self.window._video_frame_metadata)
        self.assertIsNone(self.window.video_tracker)

    def test_multiple_classes_track_together_and_failed_save_keeps_memory_on_mode_change(self):
        self.go(2)
        self.polygon()
        self.polygon(group=4, x=23, label="other")
        for item in self.window.labelList:
            self.window.labelList.selectItem(item)
        self.assertTrue(self.window.trackVideoSelection())
        self.assertEqual(len(self.window.video_objects), 2)
        tracker = self.window.video_tracker
        self.window.setDirty()
        with patch.object(self.window, "saveFile", return_value=False):
            self.assertFalse(self.window.openVolume(str(self.path)))
        self.assertIs(self.window.video_tracker, tracker)
        self.go(3)
        self.assertTrue(self.window.propagateVideoFrame())
        self.assertEqual({s.group_id for s in self.window.canvas.shapes}, {0, 4})

    def test_source_change_during_prediction_discards_output_and_model_memory(self):
        tracker = self.start()
        self.go(3)
        def changed(image, index):
            self.path.write_bytes(self.path.read_bytes() + b"changed")
            return [np.ones((32, 40), np.uint8)]
        with patch.object(tracker.backend, "predict", side_effect=changed):
            self.assertFalse(self.window.propagateVideoFrame())
        self.assertEqual(self.window.canvas.shapes, [])
        self.assertIsNone(self.window.video_tracker)
        self.assertEqual(tracker.backend.commits, 0)
        self.assertEqual(tracker.backend.discards, 1)


if __name__ == "__main__":
    unittest.main()
