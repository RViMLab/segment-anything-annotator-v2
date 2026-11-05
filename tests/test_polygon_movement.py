"""Fractional polygon dragging at image boundaries, including save and undo."""

import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow
from PIL import Image
from qtpy import QtCore, QtWidgets


class PolygonMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.image = self.root / "frame.png"
        Image.new("RGB", (100, 80)).save(self.image)
        self.data = {"imageWidth": 100, "imageHeight": 80, "shapes": [
            {"label": "tool", "group_id": 3, "flags": {"verified": True},
             "description": "retain", "shape_type": "polygon", "custom": ["metadata"],
             "points": [[20.25, 20.5], [30.75, 20.5], [25.5, 30.25]]},
            {"label": "tip", "group_id": 3, "flags": {}, "shape_type": "polygon",
             "points": [[40.25, 40.5], [50.75, 40.5], [45.5, 50.25]]},
        ]}
        (self.root / "frame.json").write_text(json.dumps(self.data))
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.current_output_dir = str(self.root)
        self.window.current_img = str(self.image)
        self.window.current_img_index = 0
        self.window.loadImg()
        self.window.setClean()

    def tearDown(self):
        self.application.removeEventFilter(self.window)
        self.window._bc_timer.stop()
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temporary.cleanup()

    def coordinates(self):
        return [[(point.x(), point.y()) for point in shape.points]
                for shape in self.window.canvas.shapes]

    def move(self, destination, multiple=False):
        canvas = self.window.canvas
        canvas.selectedShapes = list(canvas.shapes if multiple else canvas.shapes[:1])
        canvas.prevPoint = QtCore.QPointF(25.5, 25.5)
        canvas.calculateOffsets(canvas.prevPoint)
        return canvas.boundedMoveShapes(canvas.selectedShapes, QtCore.QPointF(*destination))

    def assert_translation_and_bounds(self, before, count):
        after = self.coordinates()
        dx, dy = after[0][0][0] - before[0][0][0], after[0][0][1] - before[0][0][1]
        for index, points in enumerate(after):
            for vertex, (x, y) in enumerate(points):
                self.assertGreaterEqual(x, 0.0)
                self.assertGreaterEqual(y, 0.0)
                self.assertLessEqual(x, 100.0)
                self.assertLessEqual(y, 80.0)
                expected_dx, expected_dy = (dx, dy) if index < count else (0.0, 0.0)
                self.assertAlmostEqual(x - before[index][vertex][0], expected_dx)
                self.assertAlmostEqual(y - before[index][vertex][1], expected_dy)

    def test_each_border_and_corner_preserve_fractional_geometry(self):
        for destination in ((0.25, 25.5), (25.5, 0.25), (98.75, 25.5),
                            (25.5, 78.75), (0.25, 0.25), (98.75, 78.75)):
            with self.subTest(destination=destination):
                self.window.loadImg()
                before = self.coordinates()
                self.assertTrue(self.move(destination))
                self.assert_translation_and_bounds(before, 1)

    def test_multiple_selected_polygons_keep_relative_geometry(self):
        for destination in ((0.25, 0.25), (98.75, 78.75)):
            with self.subTest(destination=destination):
                self.window.loadImg()
                before = self.coordinates()
                self.assertTrue(self.move(destination, multiple=True))
                self.assert_translation_and_bounds(before, 2)

    def test_outside_cursor_does_not_move_shapes(self):
        before = self.coordinates()
        self.assertFalse(self.move((-1.25, 10.5)))
        self.assertEqual(self.coordinates(), before)

    def test_boundary_move_saves_reloads_and_undo_preserves_metadata(self):
        before = self.coordinates()
        self.assertTrue(self.move((25.5, 0.25)))
        moved = self.coordinates()
        self.window.canvas.storeShapes()
        self.window.undoShapeEdit()
        self.assertEqual(self.coordinates(), before)
        self.assertTrue(self.move((25.5, 0.25)))
        self.assertEqual(self.coordinates(), moved)
        self.assertTrue(self.window.saveFile())
        saved = json.loads((self.root / "frame.json").read_text())
        for key in ("label", "group_id", "flags", "description", "custom"):
            self.assertEqual(saved["shapes"][0][key], self.data["shapes"][0][key])
        self.window.loadImg()
        self.assertEqual(self.coordinates(), moved)


if __name__ == "__main__":
    unittest.main()
