"""JSON round trips through the real annotation/review window, without SAM."""

import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from annotator import MainWindow, get_parser
from PIL import Image
from qtpy import QtCore, QtWidgets
from review import ReviewConfig, validate_review_config
from shape import Shape


class AnnotationRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.images, self.annotations, self.output = [
            self.root / name for name in ("images", "annotations", "reviewed")
        ]
        for directory in (self.images, self.annotations, self.output):
            directory.mkdir()
        for name in ("frame-1", "frame-2"):
            Image.new("RGB", (32, 24), "black").save(self.images / f"{name}.png")
        self.path = self.annotations / "frame-1.json"
        self.data = {
            "version": "5.2.0", "flags": {"verified": True},
            "imagePath": "../images/frame-1.png", "imageData": None,
            "imageWidth": 32, "imageHeight": 24,
            "provenance": {"source": "synthetic", "notes": ["α", "retained"]},
            "shapes": [{
                "label": "0", "group_id": 17, "shape_type": "polygon",
                "points": [[1, 1], [8.125, 1], [1, 1], [8, 8], [1, 1]],
                "flags": {"occluded": True}, "description": "keep α description",
                "custom": {"confidence": 0.73, "tags": ["manual"]},
            }],
        }
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.category_list = ["tool", "other"]
        self.window.current_output_dir = str(self.annotations)
        self.window.img_list = [str(path) for path in sorted(self.images.glob("*.png"))]
        self.window.img_len = 2
        self.window.current_img_index = 0
        self.window.current_img = self.window.img_list[0]
        self.load_fixture()

    def load_fixture(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        self.window.loadImg()
        self.window.setClean()

    def save(self, destination=None):
        destination = destination or self.output / "saved.json"
        self.assertTrue(self.window._saveFile(str(destination)))
        return json.loads(destination.read_text(encoding="utf-8"))

    def tearDown(self):
        self.window._bc_timer.stop()
        self.window.actions.save.setEnabled(False)
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temporary.cleanup()

    def test_unchanged_document_roundtrip_is_equal(self):
        original = self.path.read_bytes()
        saved = self.save()
        self.assertEqual(saved, self.data)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIs(type(saved["shapes"][0]["points"][0][0]), int)

    def test_numeric_like_labels_stay_literal_by_default(self):
        for label in ("0", "01", "-1", "1.0", "tool"):
            self.data["shapes"][0]["label"] = label
            self.load_fixture()
            self.assertEqual(self.window.canvas.shapes[0].label, label)
            self.assertEqual(self.save()["shapes"][0]["label"], label)

    def test_legacy_indices_require_explicit_option(self):
        self.assertFalse(get_parser().parse_args([]).legacy_label_indices)
        self.assertTrue(get_parser().parse_args(["--legacy-label-indices"]).legacy_label_indices)
        self.window.legacy_label_indices = True
        for label, expected in (("0", "tool"), ("1", "other"), ("-1", "-1"), ("99", "99")):
            self.data["shapes"][0]["label"] = label
            self.load_fixture()
            self.assertEqual(self.window.canvas.shapes[0].label, expected)
            self.assertEqual(self.save()["shapes"][0]["label"], expected)
            self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), self.data)

    def test_vertex_label_flags_and_group_edits_preserve_other_fields(self):
        shape = self.window.canvas.shapes[0]
        shape.points[1] = QtCore.QPointF(9.25, 2.5)
        shape.label = "updated"
        shape.flags["occluded"] = False
        shape.group_id = 23
        expected = deepcopy(self.data)
        expected["shapes"][0].update(label="updated", group_id=23, flags={"occluded": False})
        expected["shapes"][0]["points"][1] = [9.25, 2.5]
        self.assertEqual(self.save(), expected)

    def test_new_deleted_and_duplicated_shapes_keep_correct_metadata(self):
        original = self.window.canvas.shapes[0]
        duplicate = original.copy()
        duplicate.label = "duplicate"
        self.window.addLabel(duplicate)
        new = Shape(label="new", shape_type="polygon", flags={}, group_id=None)
        new.points = [QtCore.QPointF(2, 2), QtCore.QPointF(3, 2), QtCore.QPointF(3, 3)]
        new.close()
        self.window.addLabel(new)
        self.window.remLabels([original])
        saved = self.save()
        self.assertEqual(len(saved["shapes"]), 2)
        self.assertEqual(saved["shapes"][0]["description"], "keep α description")
        self.assertEqual(saved["shapes"][0]["custom"], self.data["shapes"][0]["custom"])
        self.assertNotIn("custom", saved["shapes"][1])
        self.assertEqual(saved["shapes"][1]["label"], "new")

    def test_label_dialog_edits_preserve_description_and_custom_metadata(self):
        item = next(iter(self.window.labelList))
        with patch.object(self.window.labelDialog, "popUp", return_value=(
            "edited", {"new_flag": True}, 9,
        )):
            self.window.editLabel(item)
        expected = deepcopy(self.data)
        expected["shapes"][0].update(label="edited", flags={"new_flag": True}, group_id=9)
        self.assertEqual(self.save(), expected)

    def test_label_dialog_displays_and_saves_deliberate_description_edit(self):
        item = next(iter(self.window.labelList))
        with patch.object(self.window.labelDialog, "popUp", return_value=(
            "0", {"occluded": True}, 17, "updated description",
        )) as dialog:
            self.window.editLabel(item)
        self.assertEqual(dialog.call_args.kwargs["description"], "keep α description")
        expected = deepcopy(self.data)
        expected["shapes"][0]["description"] = "updated description"
        self.assertEqual(self.save(), expected)

    def test_undo_restores_coordinates_and_metadata(self):
        self.window.canvas.shapes[0].points[1] = QtCore.QPointF(10, 3)
        self.window.canvas.storeShapes()
        self.window.undoShapeEdit()
        self.assertEqual(self.save(), self.data)

    def test_reordering_shapes_preserves_each_shapes_own_metadata(self):
        self.data["shapes"].append(dict(
            deepcopy(self.data["shapes"][0]), label="second", description="second metadata",
        ))
        self.load_fixture()
        shapes = list(reversed(self.window.canvas.shapes))
        self.window.labelList.clear()
        self.window.loadShapes(shapes)
        expected = deepcopy(self.data)
        expected["shapes"].reverse()
        self.assertEqual(self.save(), expected)

    def test_metadata_does_not_leak_to_unannotated_image(self):
        self.window.clickButtonNext()
        saved = self.save()
        self.assertNotIn("provenance", saved)
        self.assertEqual(saved["flags"], {})
        self.assertEqual(saved["version"], "1.0.0")
        self.assertEqual(saved["shapes"], [])
        self.assertEqual(saved["imagePath"], self.window.img_list[1])
        self.assertEqual(base64.b64decode(saved["imageData"]), self.window.current_img_data)
        self.window.clickButtonLast()
        self.assertEqual(self.save(), self.data)

    def test_next_annotated_image_uses_its_own_metadata(self):
        second = deepcopy(self.data)
        second["provenance"] = {"source": "second"}
        second["imagePath"] = "../images/frame-2.png"
        (self.annotations / "frame-2.json").write_text(json.dumps(second), encoding="utf-8")
        self.window.clickButtonNext()
        self.assertEqual(self.save(), second)

    def test_missing_optional_shape_fields_are_not_invented(self):
        self.data["shapes"] = [{"label": "0", "points": [[1, 1], [3, 1], [3, 3]]}]
        self.load_fixture()
        self.assertEqual(self.save(), self.data)

    def test_empty_shape_records_and_shape_order_are_retained(self):
        empty = {"label": "empty", "points": [], "description": "retain record"}
        self.data["shapes"].insert(0, empty)
        self.load_fixture()
        self.assertEqual(self.save(), self.data)

    def test_all_supported_shape_types_and_repeated_points_roundtrip(self):
        self.data["shapes"] = [
            dict(self.data["shapes"][0], shape_type=kind, points=points)
            for kind, points in (
                ("polygon", [[1, 1], [8, 1], [1, 1], [8, 8], [1, 1]]),
                ("rectangle", [[1, 1], [8, 8]]), ("circle", [[4, 4], [8, 4]]),
                ("point", [[1, 1]]), ("line", [[1, 1], [8, 8]]),
                ("linestrip", [[1, 1], [8, 1], [1, 1], [8, 8]]),
            )
        ]
        self.load_fixture()
        self.assertEqual(self.save(), self.data)

    def test_review_save_navigation_and_restart_preserve_metadata(self):
        originals = self.path.read_bytes()
        report = validate_review_config(ReviewConfig(
            "tester", "researcher", self.images, self.annotations, self.output,
        ))
        self.assertTrue(report.is_valid)
        self.window.configureReviewSession(report)
        shape = self.window.canvas.shapes[0]
        shape.points[1] = QtCore.QPointF(9, 2)
        expected = deepcopy(self.data)
        expected["shapes"][0]["points"][1] = [9, 2]
        self.assertTrue(self.window.saveFile())
        self.window.navigateImage(1)
        self.window.navigateImage(-1)
        self.assertEqual(self.save(), expected)
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.window = MainWindow(global_w=1000, global_h=1600)
        self.window.configureReviewSession(report)
        self.window.current_img_index = 0
        self.window.current_img = str(self.images / "frame-1.png")
        self.window.loadImg()
        self.assertEqual(self.save(), expected)
        self.assertEqual(self.path.read_bytes(), originals)

    def test_interactive_closing_still_uses_drawing_gesture(self):
        shape = Shape(label="drawn", shape_type="polygon")
        first = QtCore.QPointF(1, 1)
        for point in (first, QtCore.QPointF(8, 1), QtCore.QPointF(8, 8), first):
            shape.addPoint(point)
        self.assertTrue(shape.isClosed())
        self.assertEqual(len(shape.points), 3)


if __name__ == "__main__":
    unittest.main()
