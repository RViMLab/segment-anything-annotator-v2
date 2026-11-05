"""Validate geometry changes before committing editable polygons."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow
import numpy as np
from PIL import Image
from qtpy import QtCore, QtWidgets
from shape import Shape
from utils.geometry_operations import (
    GeometrySafetyError, describe_change, exact_mask_polygons, polygon_mask,
)


class MaskSafetyTests(unittest.TestCase):
    def test_holes_are_rejected_instead_of_filled(self):
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[2:25, 2:25] = 1
        mask[8:16, 8:16] = 0
        with self.assertRaisesRegex(GeometrySafetyError, "holes"):
            exact_mask_polygons(mask)

    def test_disconnected_regions_roundtrip_without_area_filtering(self):
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[2:12, 2:12] = 1
        mask[20:22, 20:22] = 1
        polygons = exact_mask_polygons(mask)
        self.assertEqual(len(polygons), 2)
        reproduced = np.zeros_like(mask)
        for polygon in polygons:
            reproduced |= polygon_mask(polygon, mask.shape)
        np.testing.assert_array_equal(mask, reproduced)

    def test_thin_region_is_blocked_instead_of_dropped(self):
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[2:12, 2] = 1
        with self.assertRaises(GeometrySafetyError):
            exact_mask_polygons(mask)

    def test_empty_mask_is_supported_and_diagnostics_count_changes(self):
        before = np.zeros((16, 16), dtype=np.uint8)
        before[2:6, 2:6] = 1
        after = np.zeros_like(before)
        self.assertEqual(exact_mask_polygons(after), [])
        report = describe_change(before, after)
        self.assertEqual((report.added, report.removed), (0, 16))
        self.assertEqual((report.before_regions, report.after_regions), (1, 0))


class GeometryOperationGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        Image.new("RGB", (40, 40)).save(self.root / "frame.png")
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.current_output_dir = str(self.root)
        self.window.current_img = str(self.root / "frame.png")
        self.window.current_img_index = 0
        self.window.loadImg()
        self.window.setClean()
        self.questions = patch("annotator.QMessageBox.question", return_value=QtWidgets.QMessageBox.Yes)
        self.question = self.questions.start()
        self.warnings = patch("annotator.QMessageBox.warning")
        self.warning = self.warnings.start()

    def tearDown(self):
        self.questions.stop()
        self.warnings.stop()
        self.application.removeEventFilter(self.window)
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.application.processEvents()
        self.temporary.cleanup()

    def polygon(self, points, label="tool", group_id=3):
        shape = Shape(label=label, shape_type="polygon", flags={"verified": True}, group_id=group_id)
        shape.other_data = {"description": "keep", "provenance": {"source": "manual"}}
        shape.points = [QtCore.QPointF(x, y) for x, y in points]
        shape.close()
        self.window.addLabel(shape)
        self.window.canvas.loadShapes([item.shape() for item in self.window.labelList])
        self.window.setClean()
        return shape

    def rectangle(self, x1, y1, x2, y2, **kwargs):
        return self.polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)], **kwargs)

    def test_hole_subtraction_preserves_original_shapes(self):
        target = self.rectangle(2, 2, 30, 30)
        source = self.rectangle(10, 10, 20, 20)
        before = list(self.window.canvas.shapes)
        self.assertFalse(self.window._perform_subtract(source, target))
        self.assertEqual(self.window.canvas.shapes, before)
        self.assertFalse(self.window.actions.save.isEnabled())
        self.warning.assert_called_once()
        self.assertIn("Holes: 0 → 1", self.warning.call_args.args[2])

    def test_subtraction_split_keeps_pixels_metadata_and_undo(self):
        target = self.rectangle(2, 2, 30, 30)
        source = self.rectangle(14, 0, 18, 35)
        intended = self.window._shapeMask(target) & (1 - self.window._shapeMask(source))
        self.assertTrue(self.window._perform_subtract(source, target))
        replacements = [s for s in self.window.canvas.shapes if s is not source]
        self.assertEqual(len(replacements), 2)
        actual = np.zeros_like(intended)
        for shape in replacements:
            actual |= self.window._shapeMask(shape)
            self.assertEqual(shape.other_data, target.other_data)
            self.assertEqual(shape.flags, target.flags)
        np.testing.assert_array_equal(actual, intended)
        self.assertTrue(self.window._saveFile(str(self.root / "result.json")))
        saved = json.loads((self.root / "result.json").read_text())
        self.assertEqual(saved["shapes"][0]["provenance"], {"source": "manual"})
        self.window.undoShapeEdit()
        self.assertEqual(len(self.window.canvas.shapes), 2)
        self.assertEqual(self.window.canvas.shapes[0].points, target.points)

    def test_empty_subtraction_requires_confirmation(self):
        target = self.rectangle(8, 8, 12, 12)
        source = self.rectangle(2, 2, 30, 30)
        self.assertTrue(self.window._perform_subtract(source, target))
        self.assertEqual(self.window.canvas.shapes, [source])
        self.question.assert_called_once()
        self.assertEqual(self.window.last_geometry_operation_report.after_regions, 0)

    def test_cancelled_merge_does_not_modify_shapes(self):
        source = self.rectangle(2, 2, 15, 15)
        target = self.rectangle(10, 10, 25, 25)
        self.question.return_value = QtWidgets.QMessageBox.Cancel
        self.assertFalse(self.window._perform_merge(source, target))
        self.assertEqual(self.window.canvas.shapes, [source, target])
        self.assertFalse(self.window.actions.save.isEnabled())

    def test_merge_preserves_disconnected_regions_and_metadata(self):
        source = self.rectangle(2, 2, 10, 10)
        target = self.rectangle(25, 25, 26, 26)
        intended = self.window._shapeMask(source) | self.window._shapeMask(target)
        self.assertTrue(self.window._perform_merge(source, target))
        actual = np.zeros_like(intended)
        self.assertEqual(len(self.window.canvas.shapes), 2)
        for shape in self.window.canvas.shapes:
            actual |= self.window._shapeMask(shape)
            self.assertEqual(shape.other_data, source.other_data)
        np.testing.assert_array_equal(actual, intended)

    def test_merge_conflicting_identity_or_metadata_is_blocked(self):
        source = self.rectangle(2, 2, 15, 15)
        target = self.rectangle(10, 10, 25, 25, group_id=4)
        self.assertFalse(self.window._perform_merge(source, target))
        self.assertEqual(self.window.canvas.shapes, [source, target])
        target.group_id = 3
        target.other_data["description"] = "different"
        self.assertFalse(self.window._perform_merge(source, target))

    def test_merge_across_intervening_overlap_is_blocked(self):
        source = self.rectangle(2, 2, 15, 15)
        middle = self.rectangle(5, 5, 20, 20, label="another", group_id=8)
        target = self.rectangle(10, 10, 25, 25)
        self.assertFalse(self.window._perform_merge(source, target))
        self.assertEqual(self.window.canvas.shapes, [source, middle, target])

    def test_reduce_points_preserves_metadata_and_undo(self):
        shape = self.polygon([(2, 2), (3, 2), (4, 2), (20, 2), (20, 20), (2, 20)])
        original = deepcopy(shape.points)
        self.window.labelList.selectItem(self.window.labelList.findItemByShape(shape))
        self.assertTrue(self.window.reducePoint())
        reduced = self.window.canvas.shapes[0]
        self.assertLess(len(reduced.points), len(original))
        self.assertEqual(reduced.flags, shape.flags)
        self.assertEqual(reduced.other_data, shape.other_data)
        self.window.undoShapeEdit()
        self.assertEqual(self.window.canvas.shapes[0].points, original)

    def test_invalid_reduction_does_not_delete_a_polygon(self):
        shape = self.polygon([(2, 2), (3, 2), (3, 3)])
        self.window.labelList.selectItem(self.window.labelList.findItemByShape(shape))
        self.assertFalse(self.window.reducePoint())
        self.assertEqual(self.window.canvas.shapes, [shape])
        self.assertFalse(self.window.actions.save.isEnabled())
