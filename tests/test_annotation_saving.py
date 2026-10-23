"""Exercise the real save/decision/navigation methods without loading SAM."""

import json
import os
from pathlib import Path
import stat
import tempfile
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Import the application before Qt loads DLLs (required by PyTorch on Windows).
from annotator import MainWindow
from PIL import Image
from qtpy import QtCore, QtWidgets
from review import ReviewConfig, ReviewPair, ReviewStatus, ReviewStorage
from utils.annotation_io import atomic_write_annotation


class AnnotationSavingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("images", "original", "reviewed"):
            (self.root / directory).mkdir()
        self.original = self.root / "original/frame.json"
        self.output = self.root / "reviewed/frame.json"
        self.image = self.root / "images/frame.png"
        Image.new("RGB", (32, 24)).save(self.image)
        self.original_data = {
            "imageWidth": 32, "imageHeight": 24,
            "shapes": [{"label": "tool", "shape_type": "polygon",
                        "points": [[1, 1], [8, 1], [8, 8]],
                        "flags": {}, "group_id": None}],
        }
        self.original.write_text(json.dumps(self.original_data), encoding="utf-8")
        config = ReviewConfig("reviewer", "researcher", self.image.parent,
                              self.original.parent, self.output.parent)
        pair = ReviewPair("frame", self.image, self.original, 32, 24)
        storage = ReviewStorage.for_config(config)
        session, items, _ = storage.open_or_create_session(config, [pair])
        panel = Mock()
        panel.elapsed_seconds.return_value = 1.0
        panel.notes_edit.toPlainText.return_value = ""
        panel.problem_combo.currentText.return_value = ""
        panel.provenance_combo.currentData.return_value = "unknown"
        self.window = SimpleNamespace(
            review_config=config, review_storage=storage, review_session=session,
            review_items=items, current_review_item=items[0],
            review_item_by_key={"frame": items[0]},
            review_item_by_image={os.path.normcase(str(self.image)): items[0]},
            review_pair_by_image={os.path.normcase(str(self.image)): pair},
            review_panel=panel, review_target_image_indexes=[0],
            current_output_filename=str(self.output), current_img=str(self.image),
            current_img_index=0, img_list=[str(self.image), str(self.image)], img_len=2,
            current_img_data=self.image.read_bytes(), raw_h=24, raw_w=32,
            actions=SimpleNamespace(save=QtWidgets.QAction(None),
                                    createMode=QtWidgets.QAction(None)),
            labelList=[], canvas=Mock(), img_progress_bar=Mock(), img_name=Mock(),
            category_list=[], brightness_slider=Mock(), contrast_slider=Mock(),
            button_invert_colours=QtWidgets.QPushButton(),
            tr=lambda value: value, exportReviewCsv=Mock(), _activateReviewItem=Mock(),
        )
        self.window.brightness_slider.value.return_value = 0
        self.window.contrast_slider.value.return_value = 100
        for name in ("saveFile", "_saveFile", "saveLabels", "setClean", "_showSaveError",
                     "recordReviewDecision", "_persistCurrentReviewState",
                     "_replaceReviewItem", "_reviewProgress", "navigateImage",
                     "navigateReviewTarget", "loadImg", "loadAnno", "closeEvent"):
            setattr(self.window, name, MethodType(getattr(MainWindow, name), self.window))
        self.window.addLabel = lambda shape: self.window.labelList.append(
            SimpleNamespace(shape=lambda: shape)
        )
        self.window.loadImg()
        self.window.setClean()
        self.dialogs = patch("annotator.QMessageBox")
        self.messages = self.dialogs.start()
        self.messages.question.return_value = self.messages.Yes

    def tearDown(self):
        self.dialogs.stop()
        for path in self.root.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IREAD | stat.S_IWRITE)
        self.temporary.cleanup()

    def edit_polygon(self):
        self.window.labelList[0].shape().points[0] = QtCore.QPointF(4, 4)
        self.window.actions.save.setEnabled(True)

    def test_ok_copy_is_writable_even_when_original_is_readonly(self):
        self.original.chmod(stat.S_IREAD)
        self.assertTrue(self.window.recordReviewDecision(ReviewStatus.NO_CHANGE))
        self.assertEqual(self.output.read_bytes(), self.original.read_bytes())
        self.assertTrue(self.output.stat().st_mode & stat.S_IWRITE)
        self.edit_polygon()
        self.assertTrue(self.window.saveFile())
        self.assertEqual(json.loads(self.output.read_bytes())["shapes"][0]["points"][0], [4, 4])
        self.assertFalse(self.original.stat().st_mode & stat.S_IWRITE)

    def test_save_repairs_legacy_readonly_review_output(self):
        self.output.write_bytes(self.original.read_bytes())
        self.output.chmod(stat.S_IREAD)
        self.edit_polygon()
        self.assertTrue(self.window.saveFile())
        self.assertTrue(self.output.stat().st_mode & stat.S_IWRITE)
        self.assertEqual(json.loads(self.original.read_bytes()), self.original_data)

    def test_decisions_and_reload_preserve_corrections(self):
        for status in (ReviewStatus.NO_CHANGE, ReviewStatus.MINOR_CORRECTION):
            with self.subTest(status=status):
                self.edit_polygon()
                self.assertTrue(self.window.recordReviewDecision(status))
                self.window.navigateImage(1)
                self.window.navigateImage(-1)
                self.assertEqual(self.window.labelList[0].shape().points[0], QtCore.QPointF(4, 4))
                self.assertTrue(self.window.recordReviewDecision(ReviewStatus.NO_CHANGE))
                self.window.loadImg()
                self.assertEqual(self.window.labelList[0].shape().points[0], QtCore.QPointF(4, 4))
                self.assertTrue(self.window.current_review_item.geometry_changed)

    def test_save_failure_keeps_edits_and_blocks_decision_navigation_and_close(self):
        self.output.write_bytes(self.original.read_bytes())
        self.edit_polygon()
        with patch("utils.annotation_io.os.replace", side_effect=PermissionError("locked")):
            self.assertFalse(self.window.saveFile())
            self.assertTrue(self.window.actions.save.isEnabled())
            self.assertFalse(self.window.recordReviewDecision(ReviewStatus.MINOR_CORRECTION))
            self.assertFalse(self.window.recordReviewDecision(ReviewStatus.NO_CHANGE))
            self.window.navigateImage(1)
            self.window.navigateReviewTarget(1)
            event = Mock()
            self.window.closeEvent(event)
            event.ignore.assert_called_once()
            event.accept.assert_not_called()
        self.assertEqual(self.window.current_img_index, 0)
        self.assertEqual(self.output.read_bytes(), self.original.read_bytes())
        self.assertEqual(self.window.current_review_item.status, ReviewStatus.UNREVIEWED)
        self.messages.critical.assert_called()

    def test_failed_replacement_preserves_old_file_and_removes_temp_file(self):
        self.output.write_bytes(b"previous annotation")
        self.output.chmod(stat.S_IREAD)
        with patch("utils.annotation_io.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                atomic_write_annotation(self.output, b"new", repair_readonly=True)
        self.assertEqual(self.output.read_bytes(), b"previous annotation")
        self.assertFalse(self.output.stat().st_mode & stat.S_IWRITE)
        self.assertEqual(list(self.output.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
