"""Help remains searchable without changing the active annotation session."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow
from PIL import Image
from qtpy import QtCore, QtGui, QtTest, QtWidgets
from shape import Shape
from utils.annotation_document import shape_to_annotation


class HelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        for index in range(2):
            Image.new("RGB", (40, 32)).save(root / f"frame{index}.png")
        self.window = MainWindow(global_w=1600, global_h=1000)
        self.window.setOutputDirectory(str(root))
        self.window.img_list = [str(root / f"frame{i}.png") for i in range(2)]
        self.window.img_len = 2
        self.window.current_img = self.window.img_list[0]
        self.window.loadImg()
        shape = Shape(label="cat", group_id=3, shape_type="polygon")
        shape.points = [QtCore.QPointF(2, 2), QtCore.QPointF(20, 2), QtCore.QPointF(20, 20)]
        shape.close()
        self.window.loadShapes([shape])
        self.window.setClean()
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()

    def tearDown(self):
        self.app.removeEventFilter(self.window)
        self.window._bc_timer.stop()
        self.window.setClean()
        if self.window._help_dialog is not None:
            self.window._help_dialog.close()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def snapshot(self):
        return ([shape_to_annotation(s) for s in self.window.canvas.shapes],
                self.window.actions.save.isEnabled(), self.window.current_img_index,
                self.window.canvas.createMode, self.window.canvas.editing(),
                [item.checkState() for item in self.window.labelList],
                self.window.video_tracker, self.window.predictor)

    def test_f1_opens_nonmodal_help_without_touching_annotations(self):
        before = self.snapshot()
        self.window.canvas.setFocus()
        QtTest.QTest.keyClick(self.window.canvas, QtCore.Qt.Key_F1)
        self.app.processEvents()
        dialog = self.window._help_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.isModal())
        self.assertIsNone(self.app.activeModalWidget())
        self.assertEqual(self.snapshot(), before)

    def test_toolbar_button_reopens_one_help_window(self):
        button = self.window.toolbar.widgetForAction(self.window.actions.help)
        QtTest.QTest.mouseClick(button, QtCore.Qt.LeftButton)
        self.app.processEvents()
        dialog = self.window._help_dialog
        self.assertTrue(dialog.isVisible())
        dialog.close()
        self.window.actions.help.trigger()
        self.assertIs(self.window._help_dialog, dialog)
        self.assertTrue(dialog.isVisible())

    def test_search_filters_topics_and_explains_no_results(self):
        self.window.showHelp()
        dialog = self.window._help_dialog
        dialog.search.setText("donut")
        self.assertIn("Ctrl-select", dialog.results.toPlainText())
        self.assertNotIn("Why is the app using CPU", dialog.results.toPlainText())
        dialog.search.setText("no-such-help-topic")
        self.assertIn("No matching topics", dialog.results.toPlainText())
        dialog.search.clear()
        self.assertIn("Why is the app using CPU", dialog.results.toPlainText())

    def test_help_uses_actual_action_bindings_on_reopen(self):
        self.window.actions.createRectangleMode.setShortcut("Ctrl+Shift+B")
        self.window.showHelp()
        text = self.window._help_dialog.results.toPlainText()
        self.assertIn("Ctrl+Shift+B", text)
        self.assertIn("PgDown", text)
        self.assertIn("0–9", text)
        self.assertIn("Review mode shortcuts", text)

    def test_search_and_browsing_do_not_trigger_editor_or_application_shortcuts(self):
        before = self.snapshot()
        review_callback = Mock()
        review_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("K"), self.window)
        review_shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        review_shortcut.activated.connect(review_callback)
        save = Mock()
        undo = Mock()
        self.window.actions.save.setEnabled(True)
        self.window.actions.undo.setEnabled(True)
        self.window.actions.save.triggered.connect(save)
        self.window.actions.undo.triggered.connect(undo)
        before = self.snapshot()
        self.window.showHelp()
        dialog = self.window._help_dialog
        dialog.activateWindow()
        dialog.search.setFocus()
        self.app.processEvents()
        text = "n b a s u 0 1 2 3 k m l o"
        QtTest.QTest.keyClicks(dialog.search, text)
        self.assertEqual(dialog.search.text(), text)
        for widget in (dialog.search, dialog.results):
            widget.setFocus()
            for key in (QtCore.Qt.Key_PageDown, QtCore.Qt.Key_PageUp,
                        QtCore.Qt.Key_Space, QtCore.Qt.Key_K):
                QtTest.QTest.keyClick(widget, key)
            QtTest.QTest.keyClick(widget, QtCore.Qt.Key_U, QtCore.Qt.ControlModifier)
            QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Right, QtCore.Qt.AltModifier)
        self.app.processEvents()
        review_callback.assert_not_called()
        save.assert_not_called()
        undo.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_shortcut_captions_and_tooltips_match_bindings(self):
        for name in ("promptSeg", "createMode", "editMode", "save"):
            action = getattr(self.window.actions, name)
            primary = action.shortcuts()[0].toString()
            self.assertIn(f"({primary})", action.iconText())
            self.assertIn(primary, action.toolTip())


if __name__ == "__main__":
    unittest.main()
