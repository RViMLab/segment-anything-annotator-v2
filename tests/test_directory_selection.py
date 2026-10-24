"""Folder selection order and failed image loads through the real GUI methods."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow
from PIL import Image
from qtpy import QtCore, QtWidgets
from shape import Shape


class DirectorySelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.images, self.output = self.root / "images", self.root / "saved"
        self.images.mkdir()
        self.output.mkdir()
        self.image = self.images / "frame.png"
        Image.new("RGB", (32, 24)).save(self.image)
        self.window = MainWindow(global_w=1000, global_h=1600)

    def choose_images(self):
        with patch("annotator.QFileDialog.getExistingDirectory", return_value=str(self.images)):
            self.window.clickFileChoose()

    def choose_output(self):
        with patch("annotator.QFileDialog.getExistingDirectory", return_value=str(self.output)):
            self.window.clickSaveChoose()

    def tearDown(self):
        self.application.removeEventFilter(self.window)
        self.window._bc_timer.stop()
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temporary.cleanup()

    def test_output_first_waits_for_image_then_saves_to_selected_directory(self):
        with patch.object(self.window, "loadImg", wraps=self.window.loadImg) as load:
            self.choose_output()
            load.assert_not_called()
        self.assertEqual(self.window.current_output_dir, str(self.output))
        self.assertEqual(self.window.current_img, "")
        self.choose_images()
        self.assertEqual(self.window.current_img, str(self.image))
        self.assertEqual(self.window.current_output_filename, str(self.output / "frame.json"))
        shape = Shape(label="tool", shape_type="polygon", flags={}, group_id=3)
        shape.points = [QtCore.QPointF(1, 1), QtCore.QPointF(8, 1), QtCore.QPointF(8, 8)]
        shape.close()
        self.window.addLabel(shape)
        self.assertTrue(self.window.saveFile())
        saved = json.loads((self.output / "frame.json").read_text())
        self.assertEqual(saved["shapes"][0]["label"], "tool")

    def test_images_first_then_output_still_works(self):
        self.choose_images()
        self.choose_output()
        self.assertEqual(self.window.current_img, str(self.image))
        self.assertEqual(self.window.current_output_filename, str(self.output / "frame.json"))
        self.assertEqual(self.window.canvas.pixmap.size(), QtCore.QSize(32, 24))

    def test_cancelled_directory_dialogs_leave_state_unchanged(self):
        for loaded in (False, True):
            if loaded:
                self.choose_output()
                self.choose_images()
            before = (self.window.current_img, self.window.current_output_dir,
                      self.window.current_output_filename)
            with patch("annotator.QFileDialog.getExistingDirectory", return_value=""), \
                    patch.object(self.window, "loadImg") as load:
                self.window.clickSaveChoose()
                self.window.clickFileChoose()
                load.assert_not_called()
            self.assertEqual((self.window.current_img, self.window.current_output_dir,
                              self.window.current_output_filename), before)

    def test_empty_image_load_does_not_call_decoder(self):
        with patch("annotator.cv2.imread") as decode:
            self.assertFalse(self.window.loadImg())
            decode.assert_not_called()

    def test_unreadable_image_reports_error_and_preserves_displayed_state(self):
        self.choose_output()
        self.choose_images()
        self.window._annotation_data = {"provenance": "retained"}
        pixmap = self.window.canvas.pixmap
        self.window.current_img = str(self.images / "missing.png")
        self.window.current_img_index = 1
        with patch("annotator.cv2.imread", return_value=None), \
                patch("annotator.QMessageBox.critical") as error:
            self.assertFalse(self.window.loadImg())
            error.assert_called_once()
        self.assertEqual(self.window.current_img, str(self.image))
        self.assertEqual(self.window.current_img_index, 0)
        self.assertIs(self.window.canvas.pixmap, pixmap)
        self.assertEqual(self.window._annotation_data, {"provenance": "retained"})


if __name__ == "__main__":
    unittest.main()
