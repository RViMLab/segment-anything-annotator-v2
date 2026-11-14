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
from qtpy import QtCore, QtWidgets
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
                for index, parts in enumerate(self.window.sam_mask_proposal):
                    np.testing.assert_array_equal(self.union(parts), self.mask)
                    self.window.selectSamProposal(index)
                    self.assertIs(self.window.sam_mask, parts)
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
        before = self.window.sam_mask_proposal[:]
        self.question.return_value = QtWidgets.QMessageBox.Cancel
        with patch.object(self.window.labelDialog, "popUp") as label:
            self.window.addSamMask()
        label.assert_not_called()
        self.assertEqual(self.window.sam_mask_proposal, before)
        self.assertEqual(self.window.canvas.shapes, [])
        self.assertFalse(self.window.actions.save.isEnabled())

    def test_cancel_free_form_label_after_hole_confirmation_keeps_proposals(self):
        self.prepare("point")
        before = self.window.sam_mask_proposal[:]
        with patch.object(self.window.labelDialog, "popUp", return_value=(None, None, None, None)):
            self.window.addSamMask()
        self.assertEqual(self.window.sam_mask_proposal, before)
        self.assertEqual(self.window.canvas.shapes, [])
        self.assertFalse(self.window.actions.save.isEnabled())

    def test_unrepresentable_proposal_is_disabled_without_poisoning_valid_selection(self):
        thin = np.zeros_like(self.mask)
        thin[10:40, 5] = 1
        self.window._buildSamProposals(np.stack([self.mask, thin, self.mask]), [0.6, 0.99, 0.7])
        self.assertFalse(self.window.button_proposal_list[1].isEnabled())
        self.assertIn("unavailable", self.window.button_proposal_list[1].toolTip())
        self.assertIs(self.window.sam_mask, self.window.sam_mask_proposal[2])
        self.window.selectSamProposal(1)
        self.assertIs(self.window.sam_mask, self.window.sam_mask_proposal[2])
        self.warning.assert_not_called()

    def test_all_unrepresentable_or_empty_proposals_explain_failure_without_modifying_data(self):
        thin = np.zeros_like(self.mask)
        thin[10:40, 5] = 1
        self.window._buildSamProposals(np.stack([thin, thin * 0, thin]), [0.9, 0.8, 0.7])
        self.warning.assert_called_once()
        self.assertIn("No SAM proposal", self.warning.call_args.args[2])
        self.assertTrue(all(not button.isEnabled() for button in self.window.button_proposal_list))
        self.window.addSamMask()
        self.assertFalse(self.window.actions.save.isEnabled())
        self.assertEqual(self.window.canvas.shapes, [])


if __name__ == "__main__":
    unittest.main()
