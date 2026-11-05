"""Confirm default output and retain work when choosing a folder after drawing."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import annotator
from annotator import MainWindow
from PIL import Image
from qtpy import QtCore, QtGui, QtWidgets
from shape import Shape


class SaveDestinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        families = QtGui.QFontDatabase().families()
        if not families:
            font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
            if font_path.is_file():
                font_id = QtGui.QFontDatabase.addApplicationFont(str(font_path))
                families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if families:
            cls.application.setFont(QtGui.QFont(families[0], 9))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.image = self.root / "frame.png"
        Image.new("RGB", (32, 24)).save(self.image)
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.default = self.root / "default"
        self.window.current_output_dir = str(self.default)  # Isolate default writes.
        self.window.current_img = str(self.image)
        self.window.current_img_index = 0
        self.window.img_list = [str(self.image), str(self.image)]
        self.window.img_len = 2
        self.window.loadImg()
        shape = Shape(label="tool", shape_type="polygon", flags={"keep": True}, group_id=3)
        shape.points = [QtCore.QPointF(1, 1), QtCore.QPointF(8, 1), QtCore.QPointF(8, 8)]
        shape.other_data = {"description": "keep", "custom": {"source": "test"}}
        shape.close()
        self.window.addLabel(shape)
        self.window.canvas.loadShapes([shape])
        self.window.setDirty()

    def tearDown(self):
        self.application.removeEventFilter(self.window)
        self.window._bc_timer.stop()
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temporary.cleanup()

    def answer(self, text):
        def execute(dialog):
            self.assertIsInstance(dialog, QtWidgets.QMessageBox)
            self.assertEqual(dialog.text(), "No output folder selected. Save to the app's output folder?")
            for button in dialog.buttons():
                if button.text().replace("&", "") == text:
                    button.click()
                    return 0
            dialog.reject()
            self.fail(f"Missing dialog button {text}")
        # Native QMessageBox.exec_ crashes even in a standalone program on
        # this Windows offscreen Qt plugin. Use real buttons/roles and replace
        # only its modal loop; manual GUI testing covers native presentation.
        replacement = patch.object(QtWidgets.QMessageBox, "exec_", execute)
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_confirm_default_once_and_recreate_deleted_folder(self):
        self.answer("Use default")
        self.assertTrue(self.window.saveFile())
        destination = self.default / "frame.json"
        self.assertEqual(json.loads(destination.read_text())["shapes"][0]["label"], "tool")
        destination.unlink()
        self.default.rmdir()
        self.window.setDirty()
        with patch.object(self.window, "confirmSaveDestination") as confirm:
            self.assertTrue(self.window.saveFile())
            confirm.assert_not_called()
        self.assertTrue(destination.exists())

    def test_choose_directory_from_confirmation_preserves_unsaved_shapes(self):
        chosen = self.root / "chosen"
        shape = self.window.canvas.shapes[0]
        self.answer("Choose folder…")
        with patch("annotator.QFileDialog.getExistingDirectory", return_value=str(chosen)):
            self.assertTrue(self.window.saveFile())
        self.assertIs(self.window.canvas.shapes[0], shape)
        saved = json.loads((chosen / "frame.json").read_text())
        self.assertEqual(saved["shapes"][0]["custom"], {"source": "test"})
        self.assertFalse((self.default / "frame.json").exists())

    def test_selecting_save_directory_after_drawing_does_not_reload(self):
        chosen = self.root / "chosen"
        with patch("annotator.QFileDialog.getExistingDirectory", return_value=str(chosen)), \
                patch.object(self.window, "loadImg") as load:
            self.window.clickSaveChoose()
            load.assert_not_called()
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertTrue(self.window.actions.save.isEnabled())
        self.assertTrue(self.window.saveFile())
        self.assertTrue((chosen / "frame.json").exists())

    def test_cancelling_keeps_edits_and_blocks_navigation_and_close(self):
        self.answer("Cancel")
        self.assertFalse(self.window.saveFile())
        self.assertTrue(self.window.actions.save.isEnabled())
        self.answer("Cancel")
        self.window.clickButtonNext()
        self.assertEqual(self.window.current_img_index, 0)
        self.answer("Cancel")
        event = Mock()
        self.window.closeEvent(event)
        event.ignore.assert_called_once()
        event.accept.assert_not_called()
        self.assertFalse(self.default.exists())

    def test_cancel_folder_selection_does_not_confirm_destination(self):
        self.answer("Choose folder…")
        with patch("annotator.QFileDialog.getExistingDirectory", return_value=""):
            self.assertFalse(self.window.saveFile())
        self.assertFalse(self.window._save_destination_confirmed)
        self.assertTrue(self.window.actions.save.isEnabled())

    def test_review_destination_needs_no_confirmation(self):
        self.window.review_config = object()
        with patch.object(self.window, "confirmSaveDestination") as confirm:
            self.assertTrue(self.window.saveFile())
            confirm.assert_not_called()
        self.window.review_config = None

    def test_default_is_application_local_when_launched_from_other_directory(self):
        previous = os.getcwd()
        other = None
        try:
            os.chdir(self.root)
            other = MainWindow(global_w=1000, global_h=1600)
            self.assertEqual(Path(other.current_output_dir), Path(annotator.__file__).resolve().parent / "output")
            self.assertFalse((self.root / "output").exists())
        finally:
            os.chdir(previous)
            if other is not None:
                self.application.removeEventFilter(other)
                other.actions.save.setEnabled(False)
                other.close()
                other.deleteLater()
