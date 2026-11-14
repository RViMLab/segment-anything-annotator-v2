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
import cv2
import numpy as np
from PIL import Image, ImageDraw
from qtpy import QtCore, QtWidgets
from shape import Shape
from review.comparison import _mask, compare_class_masks
from utils.annotation_document import shape_to_annotation
from utils.geometry_operations import (
    GeometrySafetyError, describe_change, exact_mask_polygons, polygon_mask,
)


class MaskSafetyTests(unittest.TestCase):
    def test_holes_are_decomposed_without_filling_them(self):
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[2:25, 2:25] = 1
        mask[8:16, 8:16] = 0
        self.assert_exact_parts(mask)

    def assert_exact_parts(self, mask):
        polygons = exact_mask_polygons(mask)
        cv_mask = np.zeros_like(mask)
        pil_mask = Image.new("L", (mask.shape[1], mask.shape[0]))
        draw = ImageDraw.Draw(pil_mask)
        for polygon in polygons:
            part = polygon_mask(polygon, mask.shape)
            self.assertEqual(describe_change(part, part).after_holes, 0)
            cv_mask |= part
            draw.polygon([tuple(point) for point in polygon], fill=1)
        np.testing.assert_array_equal(mask, cv_mask)
        np.testing.assert_array_equal(mask, np.array(pil_mask))
        return polygons

    def test_circular_hole_nested_island_multiple_holes_and_disconnected_region(self):
        mask = np.zeros((120, 160), dtype=np.uint8)
        cv2.circle(mask, (60, 60), 48, 1, -1)
        cv2.circle(mask, (60, 60), 18, 0, -1)
        mask[57:63, 57:63] = 1
        mask[35:43, 40:45] = 0
        mask[20:27, 135:142] = 1
        self.assert_exact_parts(mask)

    def test_border_touching_object_tiny_hole_and_small_disconnected_region(self):
        mask = np.ones((35, 50), dtype=np.uint8)
        mask[4, 4] = 0
        mask[12:20, 23:32] = 0
        mask[:, 40:] = 0
        mask[30:32, 46:48] = 1
        self.assert_exact_parts(mask)

    def test_sloped_outline_and_multiple_hole_sizes(self):
        for radius in (1, 3, 10, 22):
            with self.subTest(radius=radius):
                mask = np.zeros((120, 160), dtype=np.uint8)
                cv2.fillPoly(mask, [np.array([[3, 3], [140, 23], [110, 112], [12, 90]])], 1)
                cv2.circle(mask, (70, 60), radius, 0, -1)
                self.assert_exact_parts(mask)

    def test_overly_complex_hole_decomposition_is_bounded_and_rejected_safely(self):
        mask = np.ones((100, 100), dtype=np.uint8)
        mask[2:98:3, 2:98:3] = 0
        with self.assertRaises(GeometrySafetyError):
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
        self.question.return_value = QtWidgets.QMessageBox.Cancel
        self.assertFalse(self.window._perform_subtract(source, target))
        self.assertEqual(self.window.canvas.shapes, before)
        self.assertFalse(self.window.actions.save.isEnabled())
        self.warning.assert_not_called()
        self.assertIn("Holes: 0 → 1", self.question.call_args.args[2])
        self.assertIn("cutter remains", self.question.call_args.args[2])

    def test_hole_subtraction_preserves_mask_metadata_save_reload_and_undo(self):
        target = self.rectangle(2, 2, 35, 35)
        source = self.rectangle(10, 10, 20, 20, group_id=4)
        expected = self.window._shapeMask(target) & (1 - self.window._shapeMask(source))
        self.assertTrue(self.window._perform_subtract(source, target))
        parts = [shape for shape in self.window.canvas.shapes if shape is not source]
        actual = np.zeros_like(expected)
        for part in parts:
            actual |= self.window._shapeMask(part)
            self.assertEqual(part.group_id, target.group_id)
            self.assertEqual(part.flags, target.flags)
            self.assertEqual(part.other_data, target.other_data)
        np.testing.assert_array_equal(actual, expected)
        part_document = {"shapes": [shape_to_annotation(part) for part in parts]}
        np.testing.assert_array_equal(np.asarray(_mask(part_document, 40, 40)).astype(np.uint8), expected)
        self.assertTrue(compare_class_masks({"shapes": [shape_to_annotation(target)]}, part_document, 40, 40))
        # Subtract does not delete its cutter: it still fills those pixels in
        # the all-class union until the user deliberately removes that entry.
        with_cutter = {"shapes": [shape_to_annotation(part) for part in self.window.canvas.shapes]}
        np.testing.assert_array_equal(np.asarray(_mask(with_cutter, 40, 40)).astype(np.uint8),
                                      self.window._shapeMask(target))
        self.assertTrue(self.window._saveFile(str(self.root / "frame.json")))
        self.window.undoShapeEdit()
        self.assertEqual([s.points for s in self.window.canvas.shapes], [target.points, source.points])
        self.window.loadImg()
        restored = np.zeros_like(expected)
        for shape in self.window.canvas.shapes:
            if shape.group_id == 3:
                restored |= self.window._shapeMask(shape)
        np.testing.assert_array_equal(restored, expected)

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

    def test_merge_of_ring_parts_preserves_hole_and_explains_parts(self):
        mask = np.zeros((40, 40), dtype=np.uint8)
        mask[2:35, 2:35] = 1
        mask[10:20, 10:20] = 0
        shapes = [self.polygon(points) for points in exact_mask_polygons(mask)]
        self.assertEqual(len(shapes), 2)
        self.assertTrue(self.window._perform_merge(*shapes))
        actual = np.zeros_like(mask)
        for shape in self.window.canvas.shapes:
            actual |= self.window._shapeMask(shape)
            self.assertEqual(shape.group_id, 3)
        np.testing.assert_array_equal(actual, mask)
        self.assertIn("Holes will be preserved", self.question.call_args.args[2])
        self.window.undoShapeEdit()
        self.assertEqual([shape.points for shape in self.window.canvas.shapes], [shape.points for shape in shapes])

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
