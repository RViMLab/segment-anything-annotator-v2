"""Exercise image-display controls on the real Qt window without loading SAM."""

import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Load the application before Qt DLLs for PyTorch compatibility on Windows.
from annotator import MainWindow
import cv2
import numpy as np
from PIL import Image
from qtpy import QtGui, QtWidgets

from review import ReviewConfig, validate_review_config


def pixmap_pixels(pixmap):
    image = pixmap.toImage()
    return np.array([
        [image.pixelColor(x, y).getRgb()[:3] for x in range(image.width())]
        for y in range(image.height())
    ], dtype=np.uint8)


class ImageDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.images = self.root / "images"
        self.annotations = self.root / "annotations"
        self.output = self.root / "output"
        for directory in (self.images, self.annotations, self.output):
            directory.mkdir()
        # Three RGB pixels require row padding in a QImage.
        self.pixels = np.array([
            [[0, 10, 255], [20, 40, 60], [100, 120, 140]],
            [[255, 255, 255], [0, 0, 0], [3, 77, 199]],
        ], dtype=np.uint8)
        self.next_pixels = np.array(255 - self.pixels, dtype=np.uint8)
        Image.fromarray(self.pixels).save(self.images / "frame-1.png")
        Image.fromarray(self.next_pixels).save(self.images / "frame-2.png")
        self.annotation = {
            "imageWidth": 3, "imageHeight": 2,
            "shapes": [{"label": "tool", "shape_type": "polygon", "group_id": 7,
                        "flags": {}, "points": [[0, 0], [2, 0], [2, 1]]}],
        }
        for name in ("frame-1", "frame-2"):
            (self.annotations / f"{name}.json").write_text(json.dumps(self.annotation))
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.current_output_dir = str(self.annotations)
        self.window.img_list = [str(path) for path in sorted(self.images.glob("*.png"))]
        self.window.img_len = len(self.window.img_list)
        self.window.current_img_index = 0
        self.window.current_img = self.window.img_list[0]
        self.window.loadImg()
        self.window.setClean()

    def tearDown(self):
        self.window._bc_timer.stop()
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temporary.cleanup()

    def assertPreview(self, pixels):
        np.testing.assert_array_equal(pixmap_pixels(self.window.canvas.pixmap), pixels)

    def test_toggle_inverts_rgb_and_restores_without_touching_annotations_or_sam(self):
        self.assertFalse(self.window.button_invert_colours.isChecked())
        self.assertPreview(self.pixels)
        shape = self.window.canvas.shapes[0]
        original_points = list(shape.points)
        backups = len(self.window.canvas.shapesBackups)
        encoded_data = self.window.current_img_data
        self.window.predictor = Mock()
        self.window.image_encoded_flag = True
        for _ in range(3):
            self.window.button_invert_colours.click()
            self.assertPreview(255 - self.pixels)
            self.window.button_invert_colours.click()
            self.assertPreview(self.pixels)
        self.assertIs(self.window.canvas.shapes[0], shape)
        self.assertEqual(shape.points, original_points)
        self.assertEqual(len(self.window.canvas.shapesBackups), backups)
        self.assertFalse(self.window.actions.save.isEnabled())
        self.assertEqual(self.window.current_img_data, encoded_data)
        self.assertTrue(self.window.image_encoded_flag)
        self.assertEqual(self.window.predictor.mock_calls, [])
        np.testing.assert_array_equal(pixmap_pixels(self.window._raw_pixmap), self.pixels)

    def test_brightness_contrast_and_reset_keep_inversion_state(self):
        self.window.brightness_slider.setValue(15)
        self.window.contrast_slider.setValue(140)
        self.window.button_invert_colours.click()
        adjusted = cv2.convertScaleAbs(self.pixels, alpha=1.4, beta=15)
        self.assertPreview(255 - adjusted)
        self.window.button_invert_colours.click()
        self.assertPreview(adjusted)
        self.window.button_invert_colours.click()
        self.window.resetBrightnessContrast()
        self.window._bc_timer.stop()
        self.window.applyBrightnessContrast()
        self.assertTrue(self.window.button_invert_colours.isChecked())
        self.assertPreview(255 - self.pixels)

    def test_normal_navigation_keeps_inversion(self):
        self.window.button_invert_colours.click()
        self.window.clickButtonNext()
        self.assertPreview(255 - self.next_pixels)
        self.window.clickButtonLast()
        self.assertPreview(255 - self.pixels)

    def test_review_navigation_keeps_inversion_and_save_keeps_source_image(self):
        report = validate_review_config(ReviewConfig(
            "tester", "researcher", self.images, self.annotations, self.output,
        ))
        self.assertTrue(report.is_valid)
        self.window.configureReviewSession(report)
        source_images = {path: path.read_bytes() for path in self.images.glob("*.png")}
        source_annotations = {path: path.read_bytes() for path in self.annotations.glob("*.json")}
        self.window.button_invert_colours.click()
        self.assertTrue(self.window.saveFile())
        saved = json.loads((self.output / "frame-1.json").read_bytes())
        np.testing.assert_array_equal(
            pixmap_pixels(QtGui.QPixmap.fromImage(QtGui.QImage.fromData(
                base64.b64decode(saved["imageData"]),
            ))), self.pixels,
        )
        self.assertEqual(saved["shapes"][0]["points"], self.annotation["shapes"][0]["points"])
        self.assertEqual(saved["shapes"][0]["label"], "tool")
        self.assertEqual(saved["shapes"][0]["group_id"], 7)
        self.window.navigateReviewTarget(1)
        self.assertPreview(255 - self.next_pixels)
        self.window.navigateReviewTarget(-1)
        self.assertPreview(255 - self.pixels)
        for path, contents in {**source_images, **source_annotations}.items():
            self.assertEqual(path.read_bytes(), contents)

    def test_toggle_before_loading_and_layout_after_resize(self):
        self.window._raw_pixmap = None
        self.window.button_invert_colours.click()
        self.window.loadImg()
        self.assertPreview(255 - self.pixels)
        for width in (1000, 1600, 1920):
            self.window._updateResponsiveLayout(width, 1600)
            button = self.window.button_invert_colours.geometry()
            reset = self.window.button_bc_reset.geometry()
            self.assertEqual(button.left(), reset.left())
            self.assertEqual(button.width(), reset.width())
            self.assertGreater(button.top(), reset.bottom())
            self.assertLess(button.right(), self.window.shape_dock.x())


if __name__ == "__main__":
    unittest.main()
