"""Row drops must never hide annotations in child rows or delete drag sources."""

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
from qtpy import QtCore, QtGui, QtTest, QtWidgets
from shape import Shape
from utils.annotation_document import shape_to_annotation


class PolygonDropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        Image.new("RGB", (40, 40)).save(self.root / "frame.png")
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.current_output_dir = str(self.root)
        self.window.current_img = str(self.root / "frame.png")
        self.window.current_img_index = 0
        self.window.loadImg()
        self.view = self.window.labelList
        self.view.resize(300, 400)
        self.view.show()
        self.questions = patch("annotator.QMessageBox.question", return_value=QtWidgets.QMessageBox.Yes)
        self.question = self.questions.start()
        self.warnings = patch("annotator.QMessageBox.warning")
        self.warning = self.warnings.start()

    def tearDown(self):
        self.questions.stop()
        self.warnings.stop()
        self.app.removeEventFilter(self.window)
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def rectangle(self, x1=2, y1=2, x2=18, y2=18, group_id=3):
        shape = Shape(label="tool", shape_type="polygon", flags={"verified": True}, group_id=group_id)
        shape.other_data = {"description": "keep", "source": {"manual": True}}
        shape.points = [QtCore.QPointF(x, y) for x, y in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]]
        shape.close()
        self.window.addLabel(shape)
        self.window.canvas.loadShapes([item.shape() for item in self.view])
        self.window.setClean()
        self.view.doItemsLayout()
        self.app.processEvents()
        return shape

    def center(self, row):
        return self.view.visualRect(self.view.model().index(row, 0)).center()

    def assertFlat(self, count):
        self.assertEqual(len(self.view), count)
        self.assertEqual(len(self.window.canvas.shapes), count)
        for item in self.view:
            self.assertEqual(item.rowCount(), 0)
            self.assertFalse(item.isDropEnabled())

    def test_model_refuses_child_drop_even_if_view_is_bypassed(self):
        self.rectangle()
        self.rectangle(10, 10, 26, 26)
        model = self.view.model()
        mime = model.mimeData([model.index(0, 0)])
        parent = model.index(1, 0)
        self.assertFalse(model.canDropMimeData(mime, QtCore.Qt.MoveAction, -1, -1, parent))
        self.assertFalse(model.dropMimeData(mime, QtCore.Qt.MoveAction, -1, -1, parent))
        self.assertFlat(2)

    def test_no_preserves_entries_visibility_dirty_state_and_undo_history(self):
        self.rectangle()
        self.rectangle(10, 10, 26, 26)
        before = list(self.view)
        before[0].setCheckState(QtCore.Qt.Unchecked)
        self.window.setClean()
        backups = len(self.window.canvas.shapesBackups)
        self.question.return_value = QtWidgets.QMessageBox.No
        self.view.dropItems([before[0]], self.center(1))
        self.assertEqual(list(self.view), before)
        self.assertEqual(before[0].checkState(), QtCore.Qt.Unchecked)
        self.assertEqual(len(self.window.canvas.shapesBackups), backups)
        self.assertFalse(self.window.actions.save.isEnabled())
        self.assertIn("Do you want to merge the 2 annotations?", self.question.call_args.args[2])
        self.assertEqual(self.question.call_args.args[-1], QtWidgets.QMessageBox.No)
        self.assertFlat(2)

    def test_yes_merges_exact_union_saves_and_undo_restores_both(self):
        source = self.rectangle()
        target = self.rectangle(10, 10, 26, 26)
        expected = self.window._shapeMask(source) | self.window._shapeMask(target)
        self.view.dropItems([self.view[0]], self.center(1))
        self.assertFlat(1)
        merged = self.view[0].shape()
        np.testing.assert_array_equal(self.window._shapeMask(merged), expected)
        self.assertEqual(merged.other_data, source.other_data)
        self.assertEqual(merged.flags, source.flags)
        self.question.assert_called_once()
        self.assertTrue(self.window._saveFile(str(self.root / "frame.json")))
        saved = json.loads((self.root / "frame.json").read_text())
        self.assertEqual(len(saved["shapes"]), 1)
        self.window.undoShapeEdit()
        self.assertFlat(2)
        self.assertEqual(self.view[0].shape().points, source.points)
        self.assertEqual(self.view[1].shape().points, target.points)
        self.window.loadImg()
        self.assertFlat(1)
        np.testing.assert_array_equal(self.window._shapeMask(self.view[0].shape()), expected)
        self.assertEqual(shape_to_annotation(self.view[0].shape()), shape_to_annotation(merged))

    def test_reject_different_class_no_overlap_missing_id_and_metadata_conflict(self):
        for variant, message in [("class", "different classes"), ("overlap", "no overlapping"),
                                 ("missing", "numeric"), ("metadata", "metadata")]:
            with self.subTest(variant=variant):
                self.view.clear()
                self.window.canvas.loadShapes([])
                source = self.rectangle()
                target = self.rectangle(10, 10, 26, 26)
                if variant == "class":
                    target.group_id = 4
                elif variant == "missing":
                    target.group_id = None
                elif variant == "overlap":
                    target.points = [point + QtCore.QPointF(20, 20) for point in target.points]
                else:
                    target.other_data["description"] = "different"
                before = list(self.view)
                self.question.reset_mock()
                self.warning.reset_mock()
                self.view.dropItems([before[0]], self.center(1))
                self.question.assert_not_called()
                self.warning.assert_called_once()
                self.assertIn(message, self.warning.call_args.args[2])
                self.assertEqual(list(self.view), before)
                self.assertFalse(self.window.actions.save.isEnabled())
                self.assertFlat(2)

    def test_numeric_group_id_representations_match_including_zero(self):
        self.rectangle(group_id=0)
        self.rectangle(10, 10, 26, 26, group_id="00")
        self.view.dropItems([self.view[0]], self.center(1))
        self.assertFlat(1)
        self.assertEqual(self.view[0].shape().group_id, 0)

    def test_between_rows_reorders_and_is_undoable_without_merging(self):
        first = self.rectangle()
        second = self.rectangle(10, 10, 26, 26)
        third = self.rectangle(30, 30, 35, 35, group_id=4)
        self.view.selectItem(self.view[0])
        item = self.view[0]
        item.setCheckState(QtCore.Qt.Unchecked)
        dropped = QtTest.QSignalSpy(self.view.itemDropped)
        rectangle = self.view.visualRect(self.view.model().index(2, 0))
        self.assertTrue(self.view.dropItems([item], rectangle.bottomLeft()))
        self.assertEqual(len(dropped), 1)
        self.assertEqual(self.window.canvas.shapes, [second, third, first])
        self.assertIs(self.view[2], item)
        self.assertEqual(item.checkState(), QtCore.Qt.Unchecked)
        self.assertEqual(self.view.selectedItems(), [item])
        self.question.assert_not_called()
        self.assertFlat(3)
        self.assertTrue(self.window._saveFile(str(self.root / "frame.json")))
        self.window.undoShapeEdit()
        self.assertEqual([s.points for s in self.window.canvas.shapes], [first.points, second.points, third.points])
        self.assertFlat(3)
        self.window.loadImg()
        self.assertEqual([s.points for s in self.window.canvas.shapes], [second.points, third.points, first.points])
        self.assertFlat(3)

    def test_multi_selection_reorder_keeps_relative_order_and_center_drop_rejects(self):
        shapes = [self.rectangle(group_id=i) for i in range(4)]
        items = list(self.view)
        self.view.dropItems(items[:2], self.center(3))
        self.assertEqual(list(self.view), items)
        self.warning.assert_called_once()
        self.assertTrue(self.view.reorderItems(items[:2], 4))
        self.assertEqual(self.window.canvas.shapes, shapes[2:] + shapes[:2])
        self.assertFlat(4)

    def test_self_drop_and_outside_drop_are_noops(self):
        self.rectangle()
        before = list(self.view)
        self.assertFalse(self.view.dropItems(before, self.center(0)))
        self.assertFalse(self.view.dropItems(before, QtCore.QPoint(-1, -1)))
        self.assertEqual(list(self.view), before)
        self.question.assert_not_called()
        self.warning.assert_not_called()

    def test_owned_drag_does_not_delete_sources_after_native_move_result(self):
        self.rectangle()
        self.rectangle(10, 10, 26, 26)
        self.view.selectItem(self.view[0])
        before = list(self.view)
        self.question.return_value = QtWidgets.QMessageBox.No

        def simulate_drop(*args):
            self.view.dropItems(self.view._dragged_items, self.center(1))
            return QtCore.Qt.MoveAction

        with patch("utils.polygon_label_list.QtGui.QDrag.exec_", side_effect=simulate_drop):
            self.view.startDrag(QtCore.Qt.MoveAction)
        self.assertEqual(list(self.view), before)
        self.assertIsNone(self.view._drag_token)
        self.assertFlat(2)

    def test_drop_events_route_center_to_confirmation_and_edge_to_reorder(self):
        self.rectangle()
        self.rectangle(10, 10, 26, 26)
        before = list(self.view)
        self.question.return_value = QtWidgets.QMessageBox.No
        view = self.view

        class LocalDropEvent(QtGui.QDropEvent):
            def source(self):
                return view

        self.view._dragged_items = [before[0]]
        self.view._drag_token = "test-token"
        mime = QtCore.QMimeData()
        mime.setData(view.MIME_TYPE, b"test-token")

        def event_at(position):
            return LocalDropEvent(QtCore.QPointF(position), QtCore.Qt.MoveAction,
                                  mime, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)

        center_event = event_at(self.center(1))
        self.view.dropEvent(center_event)
        self.assertFalse(center_event.isAccepted())
        self.assertEqual(list(self.view), before)
        self.question.assert_called_once()
        bottom = self.view.visualRect(self.view.model().index(1, 0)).bottomLeft()
        edge_event = event_at(bottom)
        self.view.dropEvent(edge_event)
        self.assertTrue(edge_event.isAccepted())
        self.assertEqual(list(self.view), before[::-1])
        self.assertFlat(2)

    def test_external_drop_is_ignored(self):
        self.rectangle()
        self.rectangle(10, 10, 26, 26)
        model = self.view.model()
        mime = model.mimeData([model.index(0, 0)])
        event = QtGui.QDropEvent(QtCore.QPointF(self.center(1)), QtCore.Qt.MoveAction,
                                mime, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
        self.view.dropEvent(event)
        self.assertFalse(event.isAccepted())
        self.question.assert_not_called()
        self.assertFlat(2)

    def test_intervening_overlap_blocks_drop_merge(self):
        self.rectangle()
        self.rectangle(5, 5, 22, 22, group_id=4)
        self.rectangle(10, 10, 26, 26)
        before = list(self.view)
        self.view.dropItems([before[0]], self.center(2))
        self.question.assert_not_called()
        self.assertIn("draw order", self.warning.call_args.args[2])
        self.assertEqual(list(self.view), before)
        self.assertFlat(3)


if __name__ == "__main__":
    unittest.main()
