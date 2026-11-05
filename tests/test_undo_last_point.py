"""Undo unfinished manual polygon vertices without affecting saved shapes."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow
from PIL import Image
from qtpy import QtCore, QtGui, QtTest, QtWidgets


class UndoLastPointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for name in ("frame-1", "frame-2"):
            Image.new("RGB", (100, 80)).save(self.root / f"{name}.png")
        self.document = {"imageWidth": 100, "imageHeight": 80, "provenance": "keep",
                         "shapes": [{"label": "existing", "shape_type": "polygon",
                                     "group_id": 2, "flags": {}, "description": "keep",
                                     "points": [[1, 1], [8, 1], [8, 8]]}]}
        (self.root / "frame-1.json").write_text(json.dumps(self.document))
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.current_output_dir = str(self.root)
        self.window.img_list = [str(path) for path in sorted(self.root.glob("*.png"))]
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

    def click_image(self, x, y):
        canvas = self.window.canvas
        position = (QtCore.QPointF(x, y) + canvas.offsetToCenter()) * canvas.scale
        move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, position,
                                QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
        self.application.sendEvent(canvas, move)
        QtTest.QTest.mouseClick(canvas, QtCore.Qt.LeftButton, pos=position.toPoint())

    def begin_polygon(self):
        self.window.toggleDrawMode(False, createMode="polygon")
        for point in ((20, 20), (50, 20), (50, 50)):
            self.click_image(*point)
        self.assertEqual(len(self.window.canvas.current.points), 3)
        self.assertTrue(self.window.actions.undoLastPoint.isEnabled())

    def test_toolbar_and_u_remove_vertices_until_empty(self):
        self.assertFalse(self.window.actions.undoLastPoint.isEnabled())
        self.begin_polygon()
        self.window.actions.undoLastPoint.trigger()
        self.assertEqual(len(self.window.canvas.current.points), 2)
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_U)
        self.assertEqual(len(self.window.canvas.current.points), 1)
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_U)
        self.assertIsNone(self.window.canvas.current)
        self.assertFalse(self.window.actions.undoLastPoint.isEnabled())
        self.assertFalse(self.window.actions.save.isEnabled())
        destination = self.root / "saved.json"
        self.assertTrue(self.window._saveFile(str(destination)))
        self.assertEqual(json.loads(destination.read_text())["shapes"], self.document["shapes"])

    def test_cancel_and_mode_switch_disable_point_undo(self):
        self.begin_polygon()
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_Escape)
        self.assertFalse(self.window.actions.undoLastPoint.isEnabled())
        self.begin_polygon()
        self.window.toggleDrawMode(False, createMode="point")
        self.assertFalse(self.window.actions.undoLastPoint.isEnabled())
        self.assertIsNone(self.window.canvas.current)

    def test_finishing_polygon_disables_point_undo_and_preserves_shape_undo(self):
        self.begin_polygon()
        with patch.object(self.window.labelDialog, "popUp", return_value=("new", {}, 3, "new description")):
            QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_Return)
        self.assertIsNone(self.window.canvas.current)
        self.assertFalse(self.window.actions.undoLastPoint.isEnabled())
        self.assertEqual(len(self.window.canvas.shapes), 2)
        self.assertTrue(self.window.actions.undo.isEnabled())
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_U, QtCore.Qt.ControlModifier)
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertEqual(self.window.canvas.shapes[0].other_data["description"], "keep")

    def test_navigation_clears_unfinished_polygon_and_undo_state(self):
        self.begin_polygon()
        self.window.clickButtonNext()
        self.assertIsNone(self.window.canvas.current)
        self.assertFalse(self.window.actions.undoLastPoint.isEnabled())
        self.assertEqual(self.window.canvas.shapes, [])

    def test_sam_box_and_circle_prompt_signals_do_not_enable_point_undo(self):
        for mode in ("point", "rectangle", "circle"):
            self.window.toggleDrawMode(False, createMode=mode)
            self.click_image(30, 30)
            self.assertFalse(self.window.actions.undoLastPoint.isEnabled(), mode)
