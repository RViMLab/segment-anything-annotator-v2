"""Native SAM masks keep excluded pixels through ordinary polygon JSON."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow
import numpy as np
from PIL import Image, ImageDraw
from qtpy import QtCore, QtTest, QtWidgets
from shape import Shape
from utils.geometry_operations import mask_topology


class SamHoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        Image.new("RGB", (80, 60)).save(self.root / "frame.png")
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.setOutputDirectory(str(self.root))
        self.window.current_img = str(self.root / "frame.png")
        self.window.loadImg()
        self.window.keep_clicked_regions.setChecked(False)
        self.mask = np.zeros((60, 80), dtype=np.uint8)
        self.mask[5:50, 5:70] = 1
        self.mask[15:35, 25:45] = 0
        self.mask[53:55, 73:75] = 1  # Keep a small disconnected component too.
        self.warnings = patch("annotator.QMessageBox.warning")
        self.warning = self.warnings.start()
        self.questions = patch("annotator.QMessageBox.question", return_value=QtWidgets.QMessageBox.Yes)
        self.question = self.questions.start()

    def tearDown(self):
        self.warnings.stop()
        self.questions.stop()
        self.app.removeEventFilter(self.window)
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def union(self, shapes):
        mask = np.zeros_like(self.mask)
        for shape in shapes:
            mask |= self.window._shapeMask(shape)
        return mask

    def prepare(self, mode):
        w = self.window
        w.predictor = Mock()
        masks = np.stack([self.mask] * 3)
        w.predictor.predict.return_value = (masks, np.array([0.5, 0.9, 0.7]), None)
        if mode in ("box", "circle"):
            prompt = Shape(shape_type="rectangle" if mode == "box" else "circle")
            prompt.points = [QtCore.QPointF(5, 5), QtCore.QPointF(70, 50)]
            if mode == "box":
                w.canvas.currentBox = prompt
                w.clickManualSegBBox()
            else:
                w.canvas.currentCircle = prompt
                w.clickManualSegCircle()
        else:
            positive = Shape(shape_type="point")
            positive.points = [QtCore.QPointF(10, 10)]
            negative = Shape(shape_type="point")
            negative.points = [QtCore.QPointF(30, 25)]
            w.canvas.currentPos = positive
            w.canvas.currentNeg = negative
            w.clickManualSegBox()

    def test_box_circle_and_positive_negative_point_paths_preserve_all_proposals(self):
        for mode in ("box", "circle", "point"):
            with self.subTest(mode=mode):
                self.prepare(mode)
                self.assertEqual(len(self.window.sam_mask_proposal), 3)
                for index in range(3):
                    self.window.selectSamProposal(index)
                    self.assertTrue(self.window._prepareSelectedSamMask())
                    np.testing.assert_array_equal(self.union(self.window.sam_mask), self.mask)
                self.assertEqual(mask_topology(self.union(self.window.sam_mask))[1], 1)
        np.testing.assert_array_equal(self.window.predictor.predict.call_args.kwargs["point_labels"], [1, 0])

    def test_accept_save_reload_compatible_mask_and_undo(self):
        self.prepare("point")
        with patch.object(self.window.labelDialog, "popUp", return_value=("forceps", {"verified": True}, 3, "keep")):
            self.window.addSamMask()
        self.question.assert_called_once()
        self.assertIn("filled polygon parts", self.question.call_args.args[2])
        shapes = self.window.canvas.shapes
        self.assertGreater(len(shapes), 1)
        np.testing.assert_array_equal(self.union(shapes), self.mask)
        for shape in shapes:
            self.assertEqual((shape.label, shape.group_id), ("forceps", 3))
            self.assertEqual(shape.flags, {"verified": True})
            self.assertEqual(shape.other_data["description"], "keep")
        self.assertTrue(self.window._saveFile(str(self.root / "frame.json")))
        self.window.undoShapeEdit()
        self.assertEqual(self.window.canvas.shapes, [])
        self.window.loadImg()
        np.testing.assert_array_equal(self.union(self.window.canvas.shapes), self.mask)
        # Independent PIL consumers fill each saved polygon normally: no hole convention.
        mask = Image.new("L", (80, 60))
        draw = ImageDraw.Draw(mask)
        for shape in self.window.canvas.shapes:
            draw.polygon([(p.x(), p.y()) for p in shape.points], fill=1)
        np.testing.assert_array_equal(np.array(mask), self.mask)

    def test_cancel_hole_confirmation_keeps_proposals_and_existing_annotations(self):
        self.prepare("box")
        before = self.window._sam_masks.copy()
        self.question.return_value = QtWidgets.QMessageBox.Cancel
        with patch.object(self.window.labelDialog, "popUp") as label:
            self.window.addSamMask()
        label.assert_not_called()
        np.testing.assert_array_equal(self.window._sam_masks, before)
        self.assertEqual(self.window.canvas.shapes, [])
        self.assertFalse(self.window.actions.save.isEnabled())

    def test_cancel_free_form_label_after_hole_confirmation_keeps_proposals(self):
        self.prepare("point")
        before = self.window._sam_masks.copy()
        with patch.object(self.window.labelDialog, "popUp", return_value=(None, None, None, None)):
            self.window.addSamMask()
        np.testing.assert_array_equal(self.window._sam_masks, before)
        self.assertEqual(self.window.canvas.shapes, [])
        self.assertFalse(self.window.actions.save.isEnabled())

    def test_unrepresentable_proposal_remains_previewable_and_only_accept_explains_failure(self):
        thin = np.zeros_like(self.mask)
        thin[10:40, 5] = 1
        self.window._buildSamProposals(np.stack([self.mask, thin, self.mask]), [0.6, 0.99, 0.7])
        self.assertTrue(self.window.button_proposal_list[1].isEnabled())
        self.assertEqual(self.window._selected_sam_index, 1)
        self.warning.assert_not_called()
        self.window.addSamMask()
        self.warning.assert_called_once()
        self.window.selectSamProposal(0)
        self.assertTrue(self.window._prepareSelectedSamMask())
        np.testing.assert_array_equal(self.union(self.window.sam_mask), self.mask)

    def test_all_unrepresentable_or_empty_proposals_explain_failure_without_modifying_data(self):
        thin = np.zeros_like(self.mask)
        thin[10:40, 5] = 1
        self.window._buildSamProposals(np.stack([thin, thin * 0, thin]), [0.9, 0.8, 0.7])
        self.warning.assert_not_called()
        self.assertEqual([button.isEnabled() for button in self.window.button_proposal_list], [True, False, True])
        self.window.addSamMask()
        self.warning.assert_called_once()
        self.assertIn("Adjust the prompts", self.warning.call_args.args[2])
        self.assertFalse(self.window.actions.save.isEnabled())
        self.assertEqual(self.window.canvas.shapes, [])

    def test_predictions_are_raster_previews_without_running_polygon_conversion(self):
        self.window.keep_clicked_regions.setChecked(True)
        with patch("annotator.exact_mask_polygons", side_effect=AssertionError("must wait for Accept")) as convert:
            self.prepare("point")
            self.prepare("point")
            self.window.selectSamProposal(0)
            convert.assert_not_called()
        self.warning.assert_not_called()
        image = self.window._sam_overlay.toImage()
        self.assertEqual(image.pixelColor(10, 10).alpha(), 100)
        self.assertEqual(image.pixelColor(30, 25).alpha(), 0)

    def test_keep_clicked_regions_filters_only_unprompted_components_and_can_be_toggled(self):
        self.window.keep_clicked_regions.setChecked(True)
        self.prepare("point")
        expected = self.mask.copy()
        expected[53:55, 73:75] = 0
        np.testing.assert_array_equal(self.window._sam_masks[0], expected)
        calls = self.window.predictor.predict.call_count
        self.window.keep_clicked_regions.setChecked(False)
        np.testing.assert_array_equal(self.window._sam_masks[0], self.mask)
        self.assertEqual(self.window.predictor.predict.call_count, calls)
        self.window.keep_clicked_regions.setChecked(True)
        # A second positive point explicitly requests the disconnected island.
        self.window._buildSamProposals(np.stack([self.mask] * 3), [0.5, 0.9, 0.7],
                                       positive_points=[[10, 10], [73, 53]])
        np.testing.assert_array_equal(self.window._sam_masks[0], self.mask)
        # Box predictions do not use this point-only filter.
        self.prepare("box")
        np.testing.assert_array_equal(self.window._sam_masks[0], self.mask)

    def test_empty_filtered_previews_do_not_interrupt_clicks_or_create_annotations(self):
        self.window.keep_clicked_regions.setChecked(True)
        with patch("annotator.exact_mask_polygons") as convert:
            for _ in range(3):
                self.window._buildSamProposals(np.stack([self.mask] * 3), [0.5, 0.9, 0.7],
                                               positive_points=[[0, 0]])
            self.window.addSamMask()
            convert.assert_not_called()
        self.warning.assert_not_called()
        self.assertEqual(self.window.canvas.shapes, [])
        self.window.keep_clicked_regions.setChecked(False)
        self.assertTrue(all(button.isEnabled() for button in self.window.button_proposal_list))

    def test_unloaded_sam_toolbar_prompts_warn_without_changing_unfinished_polygon(self):
        self.window.toggleDrawMode(False, createMode="polygon")
        unfinished = Shape(shape_type="polygon")
        unfinished.points = [QtCore.QPointF(1, 1), QtCore.QPointF(10, 1)]
        self.window.canvas.current = unfinished
        for action in [self.window.actions.createPointMode, self.window.actions.createRectangleMode,
                       self.window.actions.createCircleMode]:
            action.trigger()
            self.assertIs(self.window.canvas.current, unfinished)
            self.assertEqual(self.window.canvas.createMode, "polygon")
        self.assertEqual(self.warning.call_count, 3)
        self.assertIn("Load SAM", self.warning.call_args.args[2])

    def test_unloaded_sam_keyboard_shortcuts_warn_and_manual_tools_remain_usable(self):
        self.window.show()
        self.window.activateWindow()
        self.window.canvas.setFocus()
        self.app.processEvents()
        for key in (QtCore.Qt.Key_P, QtCore.Qt.Key_B, QtCore.Qt.Key_C):
            QtTest.QTest.keyClick(self.window.canvas, key)
        self.assertEqual(self.warning.call_count, 3)
        self.warning.reset_mock()
        for mode in ("polygon", "construction_rectangle", "construction_circle"):
            self.window.toggleDrawMode(False, createMode=mode)
            self.assertEqual(self.window.canvas.createMode, mode)
        self.warning.assert_not_called()
        self.window.predictor = Mock()
        for mode in ("point", "rectangle", "circle"):
            self.window.toggleDrawMode(False, createMode=mode)
            self.assertEqual(self.window.canvas.createMode, mode)
        self.warning.assert_not_called()

    def test_reject_navigation_and_mode_changes_clear_raw_preview_state(self):
        self.prepare("point")
        self.assertIsNotNone(self.window._sam_overlay)
        self.window.cleanPrompt()
        self.assertIsNone(self.window._sam_overlay)
        self.assertIsNone(self.window._sam_masks)
        self.prepare("point")
        self.window.toggleDrawMode(False, createMode="polygon")
        self.assertIsNone(self.window._sam_overlay)
        self.assertIsNone(self.window._sam_masks)
        self.prepare("box")
        self.window.loadImg()
        self.assertIsNone(self.window._sam_overlay)
        self.assertIsNone(self.window._sam_masks)

    def test_selecting_all_polygon_parts_moves_ring_and_hole_together_with_undo(self):
        self.prepare("box")
        self.assertTrue(self.window._prepareSelectedSamMask())
        self.window.loadShapes(self.window.sam_mask)
        for item in self.window.labelList:
            self.window.labelList.selectItem(item)
        canvas = self.window.canvas
        self.assertEqual(len(canvas.selectedShapes), len(canvas.shapes))
        start = QtCore.QPointF(10, 10)
        canvas.selectShapePoint(start, False)
        self.assertEqual(len(canvas.selectedShapes), len(canvas.shapes))
        canvas.prevPoint = start
        self.assertTrue(canvas.boundedMoveShapes(canvas.selectedShapes, start + QtCore.QPointF(2, 1)))
        expected = np.zeros_like(self.mask)
        expected[1:, 2:] = self.mask[:-1, :-2]
        np.testing.assert_array_equal(self.union(canvas.shapes), expected)
        canvas.storeShapes()
        self.window.undoShapeEdit()
        np.testing.assert_array_equal(self.union(canvas.shapes), self.mask)


if __name__ == "__main__":
    unittest.main()
