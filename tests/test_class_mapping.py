"""Dataset mappings fill names only for annotations the user confirms."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow
from PIL import Image
from qtpy import QtCore, QtWidgets
from shape import Shape
from utils.annotation_document import shape_to_annotation
from utils.class_mapping import load_mapping, mapping_from_rows, save_mapping
from utils.class_mapping_dialog import ClassMappingDialog, MappedLabelDialog


class MappingFileTests(unittest.TestCase):
    def test_roundtrip_zero_large_ids_and_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "classes.json"
            expected = {0: "background", 3: "forceps", 125: "rétine"}
            save_mapping(path, expected)
            self.assertEqual(load_mapping(path), expected)

    def test_invalid_definitions_rejected(self):
        for rows in [[], [(True, "dog")], [(-1, "dog")], [(1.0, "dog")],
                     [("x", "dog")], [(1, " ")], [(1, None)], [(3, "cat"), ("03", "dog")]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                mapping_from_rows(rows)

    def test_duplicate_ids_are_not_silently_overwritten_when_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "classes.json"
            path.write_text(json.dumps({"version": 1, "classes": [
                {"group_id": 3, "label": "cat"}, {"group_id": 3, "label": "dog"}]}))
            with self.assertRaisesRegex(ValueError, "more than once"):
                load_mapping(path)

    def test_bad_file_format_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "classes.json"
            for data in [{}, [], {"version": 2, "classes": []}, {"version": True, "classes": []},
                         {"version": 1, "classes": ["cat"]}]:
                path.write_text(json.dumps(data))
                with self.subTest(data=data), self.assertRaises(ValueError):
                    load_mapping(path)

    def test_failed_save_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "classes.json"
            save_mapping(path, {3: "cat"})
            before = path.read_bytes()
            with patch("utils.annotation_io.os.replace", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    save_mapping(path, {3: "dog"})
            self.assertEqual(path.read_bytes(), before)


class MappingGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        Image.new("RGB", (100, 80)).save(self.root / "frame.png")
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.setOutputDirectory(str(self.root))
        self.window.current_img = str(self.root / "frame.png")
        self.window.loadImg()
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.deleteLater()
        self.app.removeEventFilter(self.window)
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def enable_mapping(self, mapping=None):
        mapping = mapping or {0: "background", 3: "forceps", 125: "retina"}

        def apply(dialog):
            dialog.setRows(mapping)
            dialog.enabled.setChecked(True)
            dialog.apply()
            return dialog.result()

        with patch.object(ClassMappingDialog, "exec_", apply):
            self.window.configureClassMapping()
        self.assertTrue(self.window.class_mapping_enabled)
        return self.window.labelDialog

    def shape(self, label="old name", group=3):
        shape = Shape(label=label, shape_type="polygon", flags={"verified": True}, group_id=group)
        shape.points = [QtCore.QPointF(5, 5), QtCore.QPointF(20, 5), QtCore.QPointF(20, 20)]
        shape.other_data = {"description": "keep description", "provenance": {"source": "manual"}}
        shape.close()
        return shape

    def test_enabling_and_cancelling_setup_never_relabels_existing_shapes(self):
        shape = self.shape()
        self.window.loadShapes([shape])
        self.window.setClean()
        before = shape_to_annotation(shape)
        self.enable_mapping()
        self.assertEqual(shape_to_annotation(shape), before)
        self.assertFalse(self.window.actions.save.isEnabled())
        with patch.object(ClassMappingDialog, "exec_", return_value=QtWidgets.QDialog.Rejected):
            self.window.configureClassMapping()
        self.assertEqual(self.window.class_mapping[3], "forceps")
        self.assertEqual(shape_to_annotation(shape), before)

    def test_id_entry_fills_name_and_unknown_id_disables_ok(self):
        dialog = self.enable_mapping()
        self.assertTrue(dialog.edit.isReadOnly())
        for group, label in [(0, "background"), (3, "forceps"), (125, "retina")]:
            dialog.edit_group_id.setText(str(group))
            self.assertEqual(dialog.edit.text(), label)
            self.assertTrue(dialog.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).isEnabled())
        for invalid in ["", "4", "-1"]:
            dialog.edit_group_id.setText(invalid)
            self.assertEqual(dialog.edit.text(), "")
            self.assertFalse(dialog.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).isEnabled())
            dialog.validate()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.Accepted)

    def test_selecting_mapping_row_sets_id_and_name(self):
        dialog = self.enable_mapping()
        dialog.labelList.setCurrentRow(1)
        self.assertEqual(dialog.edit_group_id.text(), "3")
        self.assertEqual(dialog.edit.text(), "forceps")
        dialog.addLabelHistory("unmapped history")
        self.assertEqual(dialog.labelList.count(), 3)

    def test_edit_confirm_maps_name_but_preserves_points_flags_and_metadata(self):
        shape = self.shape()
        self.window.loadShapes([shape])
        points = list(shape.points)
        dialog = self.enable_mapping()
        with patch.object(dialog, "exec_", return_value=QtWidgets.QDialog.Accepted):
            self.window.editLabel(self.window.labelList[0])
        self.assertEqual((shape.label, shape.group_id), ("forceps", 3))
        self.assertEqual(shape.points, points)
        self.assertEqual(shape.flags, {"verified": True})
        self.assertEqual(shape.other_data, {"description": "keep description", "provenance": {"source": "manual"}})
        self.assertTrue(self.window._saveFile(str(self.root / "frame.json")))
        self.window.loadImg()
        self.assertEqual(shape_to_annotation(self.window.canvas.shapes[0]), shape_to_annotation(shape))

    def test_cancelled_or_unknown_id_edit_leaves_original_unchanged(self):
        shape = self.shape(group=9)
        self.window.loadShapes([shape])
        before = shape_to_annotation(shape)
        dialog = self.enable_mapping()
        for result in [QtWidgets.QDialog.Accepted, QtWidgets.QDialog.Rejected]:
            with patch.object(dialog, "exec_", return_value=result):
                self.window.editLabel(self.window.labelList[0])
            self.assertEqual(shape_to_annotation(shape), before)

    def test_manual_polygon_uses_mapping_even_if_name_suggestion_selected(self):
        dialog = self.enable_mapping()
        shape = self.shape(label="", group=None)
        self.window.canvas.loadShapes([shape])
        # A selected historical name must not bypass the mapped ID dialog.
        with patch.object(self.window.uniqLabelList, "selectedItems", return_value=[
                type("Suggestion", (), {"data": lambda self, role: "old name"})()]):
            def choose():
                dialog.edit_group_id.setText("0")
                dialog.editDescription.setPlainText("new description")
                return QtWidgets.QDialog.Accepted
            with patch.object(dialog, "exec_", side_effect=choose):
                self.window.newShape()
        self.assertEqual((shape.label, shape.group_id), ("background", 0))
        self.assertEqual(shape.other_data["description"], "new description")

    def test_sam_cancel_keeps_proposals_and_confirm_maps_all_components(self):
        dialog = self.enable_mapping()
        shapes = [self.shape(), self.shape()]
        self.window.sam_mask = shapes[:]
        proposals = [shapes[:]]
        self.window.sam_mask_proposal = proposals[:]
        with patch.object(dialog, "exec_", return_value=QtWidgets.QDialog.Rejected):
            self.window.addSamMask()
        self.assertEqual(self.window.sam_mask, shapes)
        self.assertEqual(self.window.sam_mask_proposal, proposals)
        self.assertEqual(len(self.window.labelList), 0)

        def choose():
            dialog.edit_group_id.setText("3")
            dialog.editDescription.setPlainText("SAM description")
            return QtWidgets.QDialog.Accepted

        with patch.object(dialog, "exec_", side_effect=choose):
            self.window.addSamMask()
        self.assertEqual(len(self.window.labelList), 2)
        self.assertEqual(self.window.sam_mask, [])
        self.assertEqual(self.window.sam_mask_proposal, [])
        for shape in self.window.canvas.shapes:
            self.assertEqual((shape.label, shape.group_id), ("forceps", 3))
            self.assertEqual(shape.other_data["description"], "SAM description")

    def test_disabling_restores_free_form_dialog_and_retains_setup(self):
        self.enable_mapping()

        def disable(dialog):
            dialog.enabled.setChecked(False)
            dialog.apply()
            return dialog.result()

        with patch.object(ClassMappingDialog, "exec_", disable):
            self.window.configureClassMapping()
        self.assertFalse(self.window.class_mapping_enabled)
        self.assertEqual(self.window.class_mapping[3], "forceps")
        self.assertFalse(self.window.labelDialog.edit.isReadOnly())
        with patch.object(self.window.labelDialog, "exec_", return_value=QtWidgets.QDialog.Accepted):
            result = self.window.labelDialog.popUp(text="arbitrary", group_id=4, move=False)
        self.assertEqual((result[0], result[2]), ("arbitrary", 4))

    def test_setup_invalid_rows_do_not_apply_and_disabling_is_always_possible(self):
        dialog = ClassMappingDialog(self.window, {}, False)
        self.dialogs.append(dialog)
        dialog.enabled.setChecked(True)
        dialog.addRow(3, "cat")
        dialog.addRow(3, "dog")
        dialog.apply()
        self.assertNotEqual(dialog.result(), QtWidgets.QDialog.Accepted)
        self.assertIn("more than once", dialog.error.text())
        dialog.enabled.setChecked(False)
        dialog.apply()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)

    def test_loading_bad_file_keeps_draft_and_successful_load_needs_apply(self):
        dialog = ClassMappingDialog(self.window, {3: "cat"}, True)
        self.dialogs.append(dialog)
        path = self.root / "mapping.json"
        path.write_text("not json")
        with patch("utils.class_mapping_dialog.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(path), "")):
            dialog.loadFile()
            self.assertEqual(dialog.readRows(), {3: "cat"})
            save_mapping(path, {0: "background", 4: "dog"})
            dialog.loadFile()
        self.assertEqual(dialog.readRows(), {0: "background", 4: "dog"})
        self.assertNotEqual(dialog.result(), QtWidgets.QDialog.Accepted)
        self.assertEqual(self.window.class_mapping, {})

    def test_category_file_stays_compatible_and_does_not_disable_mapping(self):
        self.enable_mapping()
        path = self.root / "names.txt"
        path.write_text("cat\ndog\n")
        with patch("annotator.QFileDialog.getOpenFileName", return_value=(str(path), "")):
            self.window.clickCategoryChoose()
        self.assertEqual(self.window.category_list, ["cat", "dog"])
        self.assertTrue(self.window.class_mapping_enabled)
        self.assertEqual(self.window.labelDialog.mapping[3], "forceps")

    def test_save_setup_file_does_not_apply_or_modify_current_mapping(self):
        dialog = ClassMappingDialog(self.window, {3: "cat"}, True)
        self.dialogs.append(dialog)
        dialog.setRows({0: "background", 4: "dog"})
        path = self.root / "mapping"
        with patch("utils.class_mapping_dialog.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(path), "")):
            dialog.saveFile()
        self.assertEqual(load_mapping(path.with_suffix(".json")), {0: "background", 4: "dog"})
        self.assertEqual(self.window.class_mapping, {})
        self.assertNotEqual(dialog.result(), QtWidgets.QDialog.Accepted)

    def test_flags_survive_changing_selected_class(self):
        dialog = self.enable_mapping()

        def choose():
            dialog.edit_group_id.setText("125")
            self.assertEqual(dialog.getFlags(), {"verified": True})
            dialog.flagsLayout.itemAt(0).widget().setChecked(False)
            dialog.edit_group_id.setText("3")
            self.assertEqual(dialog.getFlags(), {"verified": False})
            return QtWidgets.QDialog.Accepted

        with patch.object(dialog, "exec_", side_effect=choose):
            result = dialog.popUp(text="old", group_id=0, flags={"verified": True})
        self.assertEqual(result[:3], ("forceps", {"verified": False}, 3))

    def test_imported_integral_float_id_can_be_confirmed_without_touching_until_accept(self):
        dialog = self.enable_mapping()
        with patch.object(dialog, "exec_", return_value=QtWidgets.QDialog.Accepted):
            result = dialog.popUp(text="old", group_id=3.0)
        self.assertEqual((result[0], result[2]), ("forceps", 3))


if __name__ == "__main__":
    unittest.main()
