"""Visibility controls and keyboard behavior on the real Qt window."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow
from PIL import Image
from qtpy import QtCore, QtGui, QtTest, QtWidgets
from review import ReviewConfig, validate_review_config
from shape import Shape


class PolygonVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.images, self.annotations, self.output = [
            self.root / name for name in ("images", "annotations", "output")
        ]
        for directory in (self.images, self.annotations, self.output):
            directory.mkdir()
        self.data = {"imageWidth": 32, "imageHeight": 24, "shapes": [
            {"label": label, "group_id": group, "shape_type": "polygon", "flags": {},
             "points": [[2, 2], [15, 2], [15, 15]]}
            for label, group in (("forceps", 3), ("tip", 3), ("3", 4), ("other", 13))
        ]}
        for name in ("frame-1", "frame-2"):
            Image.new("RGB", (32, 24)).save(self.images / f"{name}.png")
            (self.annotations / f"{name}.json").write_text(json.dumps(self.data))
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.current_output_dir = str(self.annotations)
        self.window.img_list = [str(path) for path in sorted(self.images.glob("*.png"))]
        self.window.img_len = 2
        self.window.current_img_index = 0
        self.window.current_img = self.window.img_list[0]
        self.window.loadImg()
        self.window.setClean()
        self.window.show()
        self.window.activateWindow()
        self.window.canvas.setFocus()
        self.application.processEvents()

    def tearDown(self):
        self.application.removeEventFilter(self.window)
        self.window._bc_timer.stop()
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temporary.cleanup()

    def visibility(self):
        return [item.checkState() == QtCore.Qt.Checked for item in self.window.labelList]

    def test_h_then_digit_isolates_object_id_and_keeps_checkboxes_in_sync(self):
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_H)
        self.assertEqual(self.visibility(), [False] * 4)
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_3)
        self.assertEqual(self.visibility(), [True, True, False, False])
        for item in self.window.labelList:
            self.assertEqual(self.window.canvas.isVisible(item.shape()),
                             item.checkState() == QtCore.Qt.Checked)
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_3)
        self.assertEqual(self.visibility(), [False] * 4)
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_H)
        self.assertEqual(self.visibility(), [True] * 4)
        self.assertFalse(self.window.actions.save.isEnabled())

    def test_mixed_visibility_unmapped_zero_and_string_ids(self):
        items = list(self.window.labelList)
        items[1].setCheckState(QtCore.Qt.Unchecked)
        self.window.toggleObjectPolygons(3)
        self.assertEqual(self.visibility(), [False, False, True, True])
        items[0].shape().group_id = "0"
        self.window.toggleObjectPolygons(0)
        self.assertEqual(self.visibility(), [True, False, True, True])
        before = self.visibility()
        self.window.toggleObjectPolygons(9)
        self.assertEqual(self.visibility(), before)

    def test_proposal_selection_uses_alt_digits_without_conflict(self):
        proposals = [[Shape(label=f"proposal-{i}")] for i in range(4)]
        self.window.sam_mask_proposal = proposals
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_3)
        self.assertEqual(self.window.sam_mask, [])
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_3, QtCore.Qt.AltModifier)
        QtTest.QTest.qWait(150)  # QPushButton keyboard activation uses animateClick.
        self.assertIs(self.window.sam_mask, proposals[2])
        self.assertEqual(self.visibility(), [False, False, True, True])

    def test_numeric_text_entry_is_not_consumed_or_toggled(self):
        controls = [QtWidgets.QLineEdit(self.window), QtWidgets.QPlainTextEdit(self.window),
                    QtWidgets.QTextEdit(self.window), QtWidgets.QSpinBox(self.window),
                    QtWidgets.QComboBox(self.window)]
        controls[-1].setEditable(True)
        for widget in controls:
            widget.show()
            widget.setFocus()
            self.application.processEvents()
            if isinstance(widget, QtWidgets.QAbstractSpinBox):
                widget.selectAll()
            QtTest.QTest.keyClicks(widget, "3")
            self.assertEqual(self.visibility(), [True] * 4)
            if isinstance(widget, QtWidgets.QLineEdit):
                self.assertEqual(widget.text(), "3")
            elif isinstance(widget, QtWidgets.QAbstractSpinBox):
                self.assertEqual(widget.value(), 3)
            elif isinstance(widget, QtWidgets.QComboBox):
                self.assertEqual(widget.currentText(), "3")
            else:
                self.assertEqual(widget.toPlainText(), "3")
            widget.hide()
            widget.deleteLater()

    def test_modal_dialog_and_auto_repeat_do_not_toggle(self):
        dialog = QtWidgets.QDialog(self.window)
        entry = QtWidgets.QLineEdit(dialog)
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        dialog.show()
        entry.setFocus()
        self.application.processEvents()
        QtTest.QTest.keyClicks(entry, "3")
        self.assertEqual(entry.text(), "3")
        self.assertEqual(self.visibility(), [True] * 4)
        dialog.close()
        self.window.activateWindow()
        self.window.canvas.setFocus()
        self.application.processEvents()
        repeat = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_3,
                                QtCore.Qt.NoModifier, "3", True)
        self.application.sendEvent(self.window.canvas, repeat)
        self.assertEqual(self.visibility(), [True] * 4)

    def test_show_labels_affects_text_only_and_preserves_saved_data(self):
        shapes = self.window.canvas.shapes
        painter = Mock()
        shapes[0].selected = True
        shapes[0].paint(painter, show_label=False)
        painter.drawText.assert_not_called()
        painter.drawPath.assert_called()
        shapes[0].paint(painter, show_label=True)
        painter.drawText.assert_called_once()
        original_points = [list(shape.points) for shape in shapes]
        self.window.showLabels.trigger()
        self.assertFalse(self.window.canvas.show_labels)
        self.assertEqual(self.visibility(), [True] * 4)
        self.assertEqual([list(shape.points) for shape in shapes], original_points)
        self.assertFalse(self.window.actions.save.isEnabled())
        with patch.object(shapes[0], "paint", wraps=shapes[0].paint) as painted:
            self.window.canvas.grab()
            self.assertFalse(painted.call_args.kwargs["show_label"])
        destination = self.output / "saved.json"
        self.assertTrue(self.window._saveFile(str(destination)))
        saved = json.loads(destination.read_text())
        self.assertEqual(saved["shapes"], self.data["shapes"])
        self.assertNotIn("show_labels", saved)
        self.window.showLabels.trigger()
        self.assertTrue(self.window.canvas.show_labels)

    def test_navigation_resets_polygon_visibility_but_keeps_label_preference(self):
        self.window.showLabels.trigger()
        self.window.togglePolygons(False)
        self.window.clickButtonNext()
        self.assertFalse(self.window.canvas.show_labels)
        self.assertEqual(self.visibility(), [True] * 4)

    def test_review_notes_and_object_shortcuts(self):
        report = validate_review_config(ReviewConfig(
            "tester", "researcher", self.images, self.annotations, self.output,
        ))
        self.window.configureReviewSession(report)
        notes = self.window.review_panel.notes_edit
        notes.setFocus()
        self.application.processEvents()
        QtTest.QTest.keyClicks(notes, "3")
        self.assertEqual(notes.toPlainText(), "3")
        self.assertEqual(self.visibility(), [True] * 4)
        self.window.canvas.setFocus()
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_3)
        self.assertEqual(self.visibility(), [False, False, True, True])

    def test_sam_acceptance_still_prompts_with_labels_hidden(self):
        for hidden in (False, True):
            if self.window.canvas.show_labels == hidden:
                self.window.showLabels.trigger()
            proposal = self.window.canvas.shapes[0].copy()
            self.window.sam_mask = [proposal]
            with patch.object(self.window.labelDialog, "popUp", return_value=(
                "accepted", {}, 8, "",
            )) as dialog, patch.object(self.window, "show_proposals"):
                self.window.addSamMask()
            dialog.assert_called_once()
            self.assertEqual(proposal.label, "accepted")
            self.assertEqual(proposal.group_id, 8)


if __name__ == "__main__":
    unittest.main()
