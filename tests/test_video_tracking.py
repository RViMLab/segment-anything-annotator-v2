"""Unified frame navigation, tracking commits, optional setup, and review safety."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from threading import get_ident
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow, get_parser, main
import numpy as np
from PIL import Image
from qtpy import QtCore, QtTest, QtWidgets
from review import ReviewConfig, ReviewStatus, validate_review_config
from shape import Shape
import torch
from utils.geometry_operations import exact_mask_polygons, polygon_mask
from utils.video_panel import TrackingProgressDialog
from utils.video_window import VideoWindowMixin
from utils.annotation_document import shape_to_annotation
from utils.video_tracking import StcnTracker, VideoTrackingError, discover_sequences


class DummyTracker:
    def start(self, image, masks, index):
        self.masks = [mask.copy() for mask in masks]
        self.reference_index = index

    def predict(self, image, index):
        if index <= self.reference_index:
            raise VideoTrackingError("Choose a frame after the tracking reference.")
        return [np.roll(mask, 1, axis=1) for mask in self.masks]


class VideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.images, self.output = self.root / "images", self.root / "output"
        for clip in ("clip_a", "clip_b"):
            (self.images / clip).mkdir(parents=True)
            for index in range(3):
                Image.new("RGB", (40, 32)).save(self.images / clip / f"{index:05}.png")
        self.output.mkdir()
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.setOutputDirectory(str(self.output))
        self.backend = DummyTracker()
        self.patches = [
            patch.object(self.window, "_makeVideoTracker", return_value=self.backend),
            patch.object(self.window, "_runVideoTask", side_effect=lambda message, operation: operation()),
            patch("annotator.QMessageBox.warning"),
            patch("annotator.QMessageBox.question", return_value=QtWidgets.QMessageBox.Yes),
            patch("annotator.QMessageBox.information"),
        ]
        self.factory, self.runner, self.warning, self.question, self.information = [p.start() for p in self.patches]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.app.removeEventFilter(self.window)
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def open(self):
        self.assertTrue(self.window.openVideoDirectory(self.images))
        self.window.video_panel.backend.setCurrentIndex(1)

    def polygon(self, x=3, group=3):
        shape = Shape(label="cat", group_id=group, shape_type="polygon", flags={"verified": True})
        shape.points = [QtCore.QPointF(x, 3), QtCore.QPointF(x + 8, 3),
                        QtCore.QPointF(x + 8, 14), QtCore.QPointF(x, 14)]
        shape.other_data = {"description": "keep", "custom": {"source": "test"}}
        shape.close()
        self.window.addLabel(shape)
        self.window.canvas.loadShapes([item.shape() for item in self.window.labelList])
        self.window.setClean()
        self.window.labelList.selectItem(self.window.labelList.findItemByShape(shape))
        return shape

    def test_discovery_handles_parent_single_sequence_case_and_duplicate_stems(self):
        clips = discover_sequences(self.images)
        self.assertEqual([clip.name for clip in clips], ["clip_a", "clip_b"])
        self.assertEqual(len(discover_sequences(self.images / "clip_a")[0].frames), 3)
        Image.new("RGB", (40, 32)).save(self.images / "clip_a/00000.jpg")
        with self.assertRaisesRegex(VideoTrackingError, "same JSON"):
            discover_sequences(self.images)

    def test_missing_stcn_is_actionable_and_does_not_import_optional_network(self):
        with patch("utils.video_tracking.importlib.import_module") as importer:
            with self.assertRaisesRegex(VideoTrackingError, "optional"):
                StcnTracker(self.root)
            importer.assert_not_called()

    def test_outputs_are_sequence_scoped_and_save_folder_can_be_selected_before_frames(self):
        self.open()
        self.polygon()
        self.assertTrue(self.window.saveFile())
        self.assertTrue((self.output / "clip_a/00000.json").is_file())
        self.window.video_panel.sequence.setCurrentIndex(1)
        self.polygon()
        self.assertTrue(self.window.saveFile())
        self.assertTrue((self.output / "clip_b/00000.json").is_file())
        peers = self.window._classNameCandidates(self.window.current_output_filename)
        self.assertIn("clip_a/00000.png", [name for name, _ in peers])

    def test_backend_selection_is_explicit_without_quality_default(self):
        self.window.openVideoDirectory(self.images)
        self.polygon()
        self.assertIsNone(self.window.video_panel.backend.currentData())
        self.assertFalse(self.window.trackVideoSelection())
        self.factory.assert_not_called()
        self.assertIn("explicitly", self.warning.call_args.args[2])

    def test_same_class_objects_have_distinct_track_ids_and_group_id_stays_class(self):
        self.open()
        first, second = self.polygon(), self.polygon(20)
        self.question.return_value = QtWidgets.QMessageBox.No
        self.assertTrue(self.window.trackVideoSelection())
        self.assertEqual(len(self.window.video_objects), 2)
        self.assertNotEqual(first.other_data["video_object_id"], second.other_data["video_object_id"])
        self.assertEqual((first.group_id, second.group_id), (3, 3))
        self.window.clickButtonNext()
        self.assertTrue(self.window.propagateVideoFrame())
        self.assertEqual(len(self.window.canvas.shapes), 2)
        for shape in self.window.canvas.shapes:
            self.assertEqual(shape.group_id, 3)
            self.assertEqual(shape.flags, {"verified": True})
            self.assertEqual(shape.other_data["description"], "keep")
        self.assertTrue(self.window.saveFile())
        self.window.loadImg()
        self.assertEqual(len({s.other_data["video_object_id"] for s in self.window.canvas.shapes}), 2)
        data = json.loads((self.output / "clip_a/00001.json").read_text())
        self.assertEqual(data["video_annotation"]["source"], "stcn_propagated_frame")

    def test_selected_parts_can_form_one_track_without_new_class_id(self):
        self.open()
        shapes = [self.polygon(), self.polygon(20)]
        self.question.return_value = QtWidgets.QMessageBox.Yes
        self.assertTrue(self.window.trackVideoSelection())
        self.assertEqual(len(self.window.video_objects), 1)
        self.assertEqual(shapes[0].other_data["video_object_id"], shapes[1].other_data["video_object_id"])
        self.assertEqual(len(self.backend.masks), 1)

    def test_failed_start_does_not_change_metadata_or_dirty_state(self):
        self.open()
        shape = self.polygon()
        before = shape_to_annotation(shape)
        self.factory.side_effect = RuntimeError("missing checkpoint")
        self.assertFalse(self.window.trackVideoSelection())
        self.assertEqual(shape_to_annotation(shape), before)
        self.assertFalse(self.window.actions.save.isEnabled())
        self.assertIsNone(self.window.video_tracker)

    def test_propagation_preserves_untracked_shapes_order_and_supports_undo(self):
        self.open()
        self.polygon()
        self.window.trackVideoSelection()
        self.window.clickButtonNext()
        untracked = self.polygon(20, group=4)
        self.assertTrue(self.window.propagateVideoFrame())
        self.assertIs(self.window.canvas.shapes[0], untracked)
        self.assertEqual(len(self.window.canvas.shapes), 2)
        self.window.undoShapeEdit()
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertEqual(self.window.canvas.shapes[0].points, untracked.points)

    def test_cancelled_replacement_never_calls_prediction(self):
        self.open()
        self.polygon()
        self.window.trackVideoSelection()
        self.window.clickButtonNext()
        shape = self.polygon(20, group=4)
        before = shape_to_annotation(shape)
        self.question.return_value = QtWidgets.QMessageBox.Cancel
        with patch.object(self.backend, "predict") as predict:
            self.assertFalse(self.window.propagateVideoFrame())
            predict.assert_not_called()
        self.assertEqual(shape_to_annotation(shape), before)

    def test_unrepresentable_prediction_preserves_current_annotations(self):
        self.open()
        self.polygon()
        self.window.trackVideoSelection()
        self.window.clickButtonNext()
        shape = self.polygon(20, group=4)
        mask = np.zeros((32, 40), np.uint8)
        mask[3:20, 2] = 1
        with patch.object(self.backend, "predict", return_value=[mask]):
            self.assertFalse(self.window.propagateVideoFrame())
        self.assertEqual(self.window.canvas.shapes, [shape])
        self.assertFalse(self.window.actions.save.isEnabled())

    def test_correction_updates_reference_and_metadata_without_changing_class(self):
        self.open()
        self.polygon()
        self.window.trackVideoSelection()
        self.window.clickButtonNext()
        self.window.propagateVideoFrame()
        shape = self.window.canvas.shapes[0]
        shape.points[0] += QtCore.QPointF(1, 0)
        shape.other_data["description"] = "corrected"
        self.assertTrue(self.window.useVideoCorrection())
        self.assertEqual(self.backend.reference_index, 1)
        self.assertEqual(self.window.video_objects[0]["template"].other_data["description"], "corrected")
        self.window.clickButtonNext()
        self.window.propagateVideoFrame()
        self.assertEqual(self.window.canvas.shapes[0].other_data["description"], "corrected")

    def test_switch_sequence_stops_tracking_and_saves_unsaved_frame(self):
        self.open()
        self.polygon()
        self.window.trackVideoSelection()
        self.window.video_panel.sequence.setCurrentIndex(1)
        self.assertIsNone(self.window.video_tracker)
        self.assertFalse(self.window.actions.propagateVideo.isEnabled())
        self.assertTrue((self.output / "clip_a/00000.json").exists())
        self.assertEqual(Path(self.window.current_img).parent.name, "clip_b")

    def test_failed_save_blocks_sequence_switch(self):
        self.open()
        self.polygon()
        self.window.setDirty()
        with patch.object(self.window, "saveFile", return_value=False):
            self.window.video_panel.sequence.setCurrentIndex(1)
        self.assertEqual(self.window.video_sequence_index, 0)
        self.assertEqual(self.window.video_panel.sequence.currentIndex(), 0)

    def test_page_navigation_and_j_are_universal_and_n_b_keep_drawing_roles(self):
        self.open()
        self.window.show()
        self.window.activateWindow()
        self.window.canvas.setFocus()
        self.app.processEvents()
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_PageDown)
        self.assertEqual(self.window.current_img_index, 1)
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_PageUp)
        self.assertEqual(self.window.current_img_index, 0)
        with patch("annotator.QtWidgets.QInputDialog.getItem", return_value=("2 - 00002.png", True)) as chooser:
            QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_J)
            chooser.assert_called_once()
        self.assertEqual(self.window.current_img_index, 2)
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_N)
        self.assertEqual(self.window.canvas.createMode, "polygon")
        self.window.predictor = Mock()
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_B)
        self.assertEqual(self.window.canvas.createMode, "rectangle")
        self.assertEqual(self.window.current_img_index, 2)

    def test_review_pairs_nested_outputs_and_retains_stcn_provenance_without_tracking(self):
        self.open()
        self.polygon()
        self.window.trackVideoSelection()
        self.window.saveFile()
        self.window.clickButtonNext()
        self.window.propagateVideoFrame()
        self.window.saveFile()
        source = self.output / "clip_a/00001.json"
        before = source.read_bytes()
        (self.root / "reviewed").mkdir()
        report = validate_review_config(ReviewConfig("reviewer", "tester", self.images, self.output, self.root / "reviewed"))
        self.assertTrue(report.is_valid)
        pair = next(pair for pair in report.pairs if pair.relative_key == "clip_a/00001")
        self.assertEqual(pair.source_provenance, "stcn_propagated_frame")
        self.window.configureReviewSession(report)
        self.assertFalse(self.window.actions.videoDirectory.isEnabled())
        self.assertFalse(self.window.actions.propagateVideo.isEnabled())
        self.assertFalse(self.window.video_mode)
        self.window.current_img_index = self.window.img_list.index(str(pair.image_path))
        self.window.current_img = str(pair.image_path)
        self.window.loadImg()
        self.window._activateReviewItem()
        self.assertEqual(self.window.current_review_item.source_provenance, "stcn_propagated_frame")
        self.assertTrue(self.window.recordReviewDecision(ReviewStatus.NO_CHANGE))
        self.assertEqual(source.read_bytes(), before)
        self.assertTrue((self.root / "reviewed/clip_a/00001.json").exists())

    def test_video_cli_and_legacy_size_option(self):
        args = get_parser().parse_args(["--video", "--max_size_STCN", "320"])
        self.assertTrue(args.video)
        self.assertEqual(args.max_size_stcn, 320)
        with patch("annotator.QApplication") as application, patch("sys.stderr"), self.assertRaises(SystemExit):
            main(["--video", "--review"])
        application.assert_not_called()

    def test_hole_parts_seed_one_mask_and_propagation_undo_restores_frame_provenance(self):
        self.open()
        mask = np.zeros((32, 40), np.uint8)
        mask[2:29, 2:35] = 1
        mask[9:21, 12:25] = 0
        for points in exact_mask_polygons(mask):
            shape = self.polygon()
            shape.points = [QtCore.QPointF(x, y) for x, y in points]
        self.assertTrue(self.window.trackVideoSelection())
        np.testing.assert_array_equal(self.backend.masks[0], mask)
        self.window.clickButtonNext()
        self.assertTrue(self.window.propagateVideoFrame())
        result = np.zeros_like(mask)
        identities = set()
        for shape in self.window.canvas.shapes:
            result |= self.window._shapeMask(shape)
            identities.add(shape.other_data["video_object_id"])
        np.testing.assert_array_equal(result, np.roll(mask, 1, axis=1))
        self.assertEqual(len(identities), 1)
        self.window.undoShapeEdit()
        self.assertEqual(self.window.canvas.shapes, [])
        self.assertIsNone(self.window.video_tracker)
        self.assertIsNone(self.window._video_frame_metadata)
        self.assertTrue(self.window.saveFile())
        data = json.loads((self.output / "clip_a/00001.json").read_text())
        self.assertEqual(data["video_annotation"]["source"], "manual_keyframe")

    def test_invalid_identity_metadata_is_not_rewritten(self):
        self.open()
        shape = self.polygon()
        shape.other_data["video_object_id"] = ["external", "value"]
        before = shape_to_annotation(shape)
        self.assertFalse(self.window.trackVideoSelection())
        self.assertEqual(shape_to_annotation(shape), before)

    def test_corrupt_or_empty_new_directory_preserves_current_tracking_and_paths(self):
        self.open()
        self.polygon()
        self.assertTrue(self.window.trackVideoSelection())
        image, output = self.window.current_img, self.window.current_output_filename
        empty = self.root / "empty"
        empty.mkdir()
        with patch("annotator.QFileDialog.getExistingDirectory", return_value=str(empty)):
            self.window.clickFileChoose()
        self.assertTrue(self.window.video_mode)
        self.assertIs(self.window.video_tracker, self.backend)
        (empty / "00000.png").write_bytes(b"not an image")
        self.assertFalse(self.window.openVideoDirectory(empty))
        self.assertEqual((self.window.current_img, self.window.current_output_filename), (image, output))
        (self.images / "clip_b/00000.png").write_bytes(b"corrupt")
        self.window.video_panel.sequence.setCurrentIndex(1)
        self.assertEqual(self.window.video_sequence_index, 0)
        self.assertIs(self.window.video_tracker, self.backend)

    def test_unknown_frame_metadata_is_preserved_and_tracking_will_not_overwrite_it(self):
        self.open()
        self.polygon()
        self.window._video_frame_metadata = "external value"
        self.assertFalse(self.window.trackVideoSelection())
        self.factory.assert_not_called()
        self.assertTrue(self.window.saveFile())
        data = json.loads((self.output / "clip_a/00000.json").read_text())
        self.assertEqual(data["video_annotation"], "external value")
        self.window._video_frame_metadata = {"external": {"keep": True}}
        self.assertTrue(self.window.trackVideoSelection())
        self.assertEqual(self.window._video_frame_metadata["external"], {"keep": True})

    def test_duplicate_allocates_new_object_identity_and_undo_keeps_it_independent(self):
        self.open()
        shape = self.polygon()
        self.assertTrue(self.window.trackVideoSelection())
        original = shape.other_data["video_object_id"]
        self.window.duplicateSelectedShape()
        duplicate = self.window.canvas.shapes[-1]
        identity = duplicate.other_data["video_object_id"]
        self.assertNotEqual(identity, original)
        self.assertEqual(duplicate.group_id, shape.group_id)
        duplicate.moveBy(QtCore.QPointF(1, 0))
        self.window.canvas.storeShapes()
        self.window.undoShapeEdit()
        self.assertEqual(self.window.canvas.shapes[-1].other_data["video_object_id"], identity)

    def test_real_worker_executes_off_ui_thread_and_progress_cannot_be_dismissed(self):
        ui = get_ident()
        thread = VideoWindowMixin._runVideoTask(self.window, "Test worker", get_ident)
        self.assertNotEqual(thread, ui)
        with self.assertRaisesRegex(ValueError, "worker failed"):
            VideoWindowMixin._runVideoTask(self.window, "Test failure", lambda: (_ for _ in ()).throw(ValueError("worker failed")))
        progress = TrackingProgressDialog("Test", None, 0, 0, self.window)
        progress.show()
        self.app.processEvents()
        QtTest.QTest.keyClick(progress, QtCore.Qt.Key_Escape)
        self.assertTrue(progress.isVisible())
        progress.close()
        self.assertTrue(progress.isVisible())
        progress.allow_close = True
        progress.close()
        progress.deleteLater()


class TrackerTransactionTests(unittest.TestCase):
    """Exercise real device-independent memory commits without model weights."""

    def tracker(self):
        tracker = StcnTracker.__new__(StcnTracker)
        tracker.torch = torch
        tracker.device = "cpu"
        tracker.reference_index, tracker.last_index = 0, 1
        tracker._pending = None
        tracker.bank = SimpleNamespace(temp_k=torch.tensor([7]), temp_v=torch.tensor([9]))
        tracker._image = Mock(return_value=(torch.zeros(1, 3, 8, 8), (0, 0, 0, 0), (8, 8), (8, 8)))
        tracker.unpad = lambda mask, padding: mask
        tracker.model = Mock()
        key = torch.ones(1, 4, 2, 2)
        tracker.model.encode_key.return_value = (key, key, key, key, key)
        tracker.model.segment_with_query.return_value = torch.ones(1, 1, 8, 8)
        tracker.model.encode_value.return_value = torch.ones(1, 4, 1, 2, 2)
        return tracker

    def test_prediction_does_not_update_memory_until_ui_accepts_geometry(self):
        tracker = self.tracker()
        key, value = tracker.bank.temp_k, tracker.bank.temp_v
        mask = tracker.predict("frame.png", 2)[0]
        self.assertEqual(int(mask.sum()), 64)
        self.assertIs(tracker.bank.temp_k, key)
        self.assertIs(tracker.bank.temp_v, value)
        self.assertEqual(tracker.last_index, 1)
        tracker.discard_prediction()
        self.assertIsNone(tracker._pending)
        tracker.predict("frame.png", 2)
        tracker.commit_prediction()
        self.assertEqual(tracker.last_index, 2)
        self.assertIsNot(tracker.bank.temp_k, key)

    def test_jumps_use_reference_memory_and_failure_restores_previous_temporary_state(self):
        tracker = self.tracker()
        key, value = tracker.bank.temp_k, tracker.bank.temp_v

        def inspect(bank, *args):
            self.assertIsNone(bank.temp_k)
            self.assertIsNone(bank.temp_v)
            raise ValueError("inference failed")

        tracker.model.segment_with_query.side_effect = inspect
        with self.assertRaisesRegex(ValueError, "inference failed"):
            tracker.predict("frame.png", 5)
        self.assertIs(tracker.bank.temp_k, key)
        self.assertIs(tracker.bank.temp_v, value)
        self.assertEqual(tracker.last_index, 1)
        with self.assertRaisesRegex(VideoTrackingError, "after"):
            tracker.predict("frame.png", 0)

    def test_corrections_preserve_initial_reference_bound_memory_and_remove_future_references(self):
        tracker = StcnTracker.__new__(StcnTracker)
        key, value = torch.ones(1, 4, 1, 2, 2), torch.ones(1, 4, 1, 2, 2)
        tracker._encode_reference = Mock(return_value=(key, value))

        class Bank:
            def __init__(self, k, top_k):
                self.num_objects = k
                self.keys = []

            def add_memory(self, key, value):
                self.keys.append(key)

        tracker.bank_type = Bank
        masks = [np.ones((8, 8), np.uint8)]
        tracker.start("frame.png", masks, 0)
        for index in range(1, 8):
            tracker.correct("frame.png", masks, index)
        self.assertEqual(tracker.reference_indices, [0, 4, 5, 6, 7])
        self.assertEqual(len(tracker.bank.keys), 5)
        tracker.correct("frame.png", masks, 3)
        self.assertEqual(tracker.reference_indices, [0, 3])
        self.assertEqual(tracker.reference_index, 3)
        before = tracker.bank
        tracker._encode_reference.side_effect = ValueError("bad reference")
        with self.assertRaisesRegex(ValueError, "bad reference"):
            tracker.correct("frame.png", masks, 4)
        self.assertIs(tracker.bank, before)


if __name__ == "__main__":
    unittest.main()
