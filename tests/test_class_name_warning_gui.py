"""Warning actions, autosave gates, and reviewed-file precedence on a real window."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow
from PIL import Image
from qtpy import QtCore, QtWidgets
from review import ReviewConfig, validate_review_config
from utils.class_name_consistency import ConsistencyReport


class ClassNameWarningGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.images, self.annotations = self.root / "images", self.root / "annotations"
        self.images.mkdir()
        self.annotations.mkdir()
        self.document = {"imageWidth": 100, "imageHeight": 80, "shapes": [
            {"label": "cat", "group_id": 3, "shape_type": "polygon", "flags": {},
             "points": [[10, 10], [50, 10], [50, 50]], "description": "keep"},
        ]}
        for name in ("first", "second", "third"):
            Image.new("RGB", (100, 80)).save(self.images / f"{name}.png")
            if name != "third":
                (self.annotations / f"{name}.json").write_text(json.dumps(self.document))
        self.window = MainWindow(global_w=1000, global_h=1600)
        with patch("annotator.QFileDialog.getExistingDirectory", return_value=str(self.annotations)):
            self.window.clickSaveChoose()
        self.window.img_list = [str(self.images / f"{name}.png") for name in ("first", "second", "third")]
        self.window.img_len = 3
        self.window.current_img_index = 1
        self.window.current_img = self.window.img_list[1]
        self.window.loadImg()
        self.window.canvas.shapes[0].label = "dog"
        self.window.setDirty()
        self.messages = []
        self.choice = "Review names"

        def execute(dialog):
            # The offscreen Windows plugin cannot run native QMessageBox.exec_.
            # Exercise its real buttons/roles, replacing only the modal loop.
            self.assertEqual(dialog.windowTitle(), "Class name mismatch")
            self.messages.append(dialog.text())
            for button in dialog.buttons():
                if button.text().replace("&", "") == self.choice:
                    button.click()
                    return 0
            self.fail("Missing warning button")

        self.modal = patch.object(QtWidgets.QMessageBox, "exec_", execute)
        self.modal.start()

    def tearDown(self):
        self.window.actions.save.setEnabled(False)
        self.application.removeEventFilter(self.window)
        self.window.close()
        self.modal.stop()
        self.window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.application.processEvents()
        self.temporary.cleanup()

    def test_review_names_blocks_save_next_previous_jump_and_close(self):
        path = self.annotations / "second.json"
        original = path.read_bytes()
        self.assertFalse(self.window.saveFile())
        self.window.clickButtonNext()
        self.window.clickButtonLast()
        with patch("annotator.QMessageBox.question", return_value=QtWidgets.QMessageBox.Yes), \
                patch("annotator.QtWidgets.QInputDialog.getItem") as jump:
            self.window.clickButtonJump()
            jump.assert_not_called()
        event = Mock()
        self.window.closeEvent(event)
        event.ignore.assert_called_once()
        self.assertEqual(self.window.current_img_index, 1)
        self.assertTrue(self.window.actions.save.isEnabled())
        self.assertEqual(self.window.canvas.shapes[0].label, "dog")
        self.assertEqual(path.read_bytes(), original)
        self.assertIn('in image first.png.', self.messages[0])
        self.assertNotIn("other image", self.messages[0])

    def test_save_anyway_preserves_names_and_does_not_repeat_on_next(self):
        self.choice = "Save anyway"
        self.assertTrue(self.window.saveFile())
        self.assertEqual(len(self.messages), 1)
        saved = json.loads((self.annotations / "second.json").read_text())
        self.assertEqual(saved["shapes"][0]["label"], "dog")
        self.assertEqual(json.loads((self.annotations / "first.json").read_text())["shapes"][0]["label"], "cat")
        self.window.clickButtonNext()
        self.assertEqual(self.window.current_img_index, 2)
        self.assertEqual(len(self.messages), 1)

    def test_same_image_different_names_are_detected(self):
        duplicate = self.window.canvas.shapes[0].copy()
        duplicate.label = "cat"
        self.window.addLabel(duplicate)
        self.assertFalse(self.window.saveFile())
        self.assertIn('different names in this image: "cat", "dog"', self.messages[0])

    def test_changed_peer_name_requires_new_acknowledgement(self):
        self.choice = "Save anyway"
        self.assertTrue(self.window.saveFile())
        changed = json.loads(json.dumps(self.document))
        changed["shapes"][0]["label"] = "parrot"
        (self.annotations / "first.json").write_text(json.dumps(changed))
        self.choice = "Review names"
        self.assertFalse(self.window.saveFile())
        self.assertEqual(len(self.messages), 2)
        self.assertIn('"parrot"', self.messages[-1])

    def test_cancelled_background_check_blocks_save_without_changing_data(self):
        with patch.object(self.window, "_waitForClassNameCheck", return_value=None):
            self.assertFalse(self.window.saveFile())
        self.assertTrue(self.window.actions.save.isEnabled())
        self.assertEqual(self.messages, [])
        self.assertEqual(json.loads((self.annotations / "second.json").read_text()), self.document)

    def test_save_as_uses_the_same_warning(self):
        destination = self.annotations / "copy.json"
        with patch("annotator.QFileDialog.getSaveFileName", return_value=(str(destination), "")):
            self.assertFalse(self.window.saveFileAs())
            self.assertFalse(destination.exists())
            self.choice = "Save anyway"
            self.assertTrue(self.window.saveFileAs())
        self.assertEqual(json.loads(destination.read_text())["shapes"][0]["label"], "dog")

    def test_save_as_adds_json_suffix_when_not_typed(self):
        self.choice = "Save anyway"
        with patch("annotator.QFileDialog.getSaveFileName", return_value=(str(self.annotations / "copy"), "")):
            self.assertTrue(self.window.saveFileAs())
        self.assertTrue((self.annotations / "copy.json").is_file())

    def test_actual_worker_progress_cancellation_preserves_edits(self):
        received = []
        checker = Mock()

        def wait_for_cancel(records, peers, cancelled):
            received.append(cancelled)
            cancelled.wait(2)
            return ConsistencyReport(cancelled=cancelled.is_set())

        checker.check.side_effect = wait_for_cancel
        self.window._class_name_checker = checker

        def cancel_progress():
            progress = self.window.findChild(QtWidgets.QProgressDialog)
            self.assertIsNotNone(progress)
            progress.canceled.emit()

        QtCore.QTimer.singleShot(25, cancel_progress)
        self.assertFalse(self.window.saveFile())
        self.assertTrue(received[0].is_set())
        self.assertTrue(self.window.actions.save.isEnabled())
        self.assertEqual(self.messages, [])

    def test_review_uses_reviewed_names_before_original_names(self):
        reviewed = self.root / "reviewed"
        reviewed.mkdir()
        changed = json.loads(json.dumps(self.document))
        changed["shapes"][0]["label"] = "dog"
        (reviewed / "first.json").write_text(json.dumps(changed))
        report = validate_review_config(ReviewConfig("tester", "researcher", self.images,
                                                     self.annotations, reviewed))
        self.window.setClean()
        self.window.configureReviewSession(report)
        self.window.current_img_index = 1
        self.window.current_img = self.window.img_list[1]
        self.window.loadImg()
        self.window._activateReviewItem()
        self.window.canvas.shapes[0].label = "dog"
        self.window.setDirty()
        self.assertTrue(self.window.saveFile())
        self.assertEqual(self.messages, [])
        self.assertEqual(json.loads((self.annotations / "second.json").read_text()), self.document)

    def test_clean_navigation_still_checks_imported_inconsistency(self):
        self.window.setClean()
        self.window.clickButtonLast()
        self.assertEqual(self.window.current_img_index, 1)
        self.assertEqual(len(self.messages), 1)
