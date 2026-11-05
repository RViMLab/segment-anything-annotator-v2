"""Dataset-local numeric class IDs, overlap rules, and audit persistence."""

import csv
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest

from review import ReviewConfig, ReviewPair, ReviewStorage, compare_annotations, export_session_csv
from review.comparison import CLASS_MASK_POLICY


def rectangle(group_id, x1=2, y1=2, x2=12, y2=12, label="Object"):
    return {"group_id": group_id, "label": label, "shape_type": "polygon",
            "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]}


class ClassMaskTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def compare(self, original, reviewed):
        paths = [self.root / "original.json", self.root / "reviewed.json"]
        for path, shapes in zip(paths, (original, reviewed)):
            path.write_text(json.dumps({"imageWidth": 32, "imageHeight": 24, "shapes": shapes}))
        contents = [path.read_bytes() for path in paths]
        result = compare_annotations(*paths)
        self.assertEqual([path.read_bytes() for path in paths], contents)
        self.assertEqual(result.class_mask_policy, CLASS_MASK_POLICY)
        return result

    def test_swapped_numeric_ids_change_classes_without_changing_silhouette(self):
        original = [rectangle(3), rectangle(4, 18, 2, 28, 12)]
        reviewed = [dict(original[0], group_id=4), dict(original[1], group_id=3)]
        result = self.compare(original, reviewed)
        self.assertFalse(result.geometry_changed)
        self.assertFalse(result.raster_mask_changed)
        self.assertTrue(result.class_mask_changed)

    def test_names_are_display_text_and_do_not_define_computer_classes(self):
        result = self.compare([rectangle(3, label="cat")], [rectangle(3, label="pizza")])
        self.assertTrue(result.annotation_changed)
        self.assertFalse(result.class_mask_changed)

    def test_hidden_class_region_removal_is_detected(self):
        result = self.compare([rectangle(3), rectangle(4)], [rectangle(4)])
        self.assertFalse(result.raster_mask_changed)
        self.assertTrue(result.class_mask_changed)

    def test_overlap_order_changes_visible_classes(self):
        original = [rectangle(3), rectangle(4, 8, 8, 20, 20)]
        result = self.compare(original, list(reversed(original)))
        self.assertFalse(result.geometry_changed)
        self.assertFalse(result.raster_mask_changed)
        self.assertTrue(result.class_mask_changed)

    def test_reordering_same_class_or_disconnected_classes_is_equivalent(self):
        for groups in ((3, 3), (3, 4)):
            original = [rectangle(groups[0]), rectangle(groups[1], 18, 2, 28, 12)]
            self.assertFalse(self.compare(original, list(reversed(original))).class_mask_changed)

    def test_zero_is_a_class_not_background(self):
        result = self.compare([rectangle(0)], [])
        self.assertTrue(result.class_mask_changed)
        self.assertIsNone(result.class_mask_error)

    def test_numeric_encodings_have_same_meaning_without_rewriting_json(self):
        for first, second in ((3, "03"), (0, "0"), (3, 3.0), (-1, "-1")):
            self.assertFalse(self.compare([rectangle(first)], [rectangle(second)]).class_mask_changed)

    def test_missing_or_invalid_ids_report_unavailable_instead_of_no_change(self):
        for group_id in (None, True, 3.5, "forceps"):
            result = self.compare([rectangle(group_id)], [rectangle(group_id)])
            self.assertIsNone(result.class_mask_changed)
            self.assertTrue(result.class_mask_error)
            self.assertFalse(result.raster_mask_changed)

    def test_arbitrary_numeric_ids_need_no_global_ontology(self):
        result = self.compare([rectangle(123456)], [rectangle(123456)])
        self.assertFalse(result.class_mask_changed)
        self.assertIsNone(result.class_mask_error)

    def test_inner_polygon_is_independently_filled_not_an_implicit_hole(self):
        result = self.compare([rectangle(3), rectangle(3, 4, 4, 8, 8)], [rectangle(3)])
        self.assertFalse(result.class_mask_changed)

    def test_empty_unassigned_records_do_not_make_comparison_unavailable(self):
        empty = {"label": "empty", "points": [], "shape_type": "polygon"}
        self.assertFalse(self.compare([rectangle(3), empty], [rectangle(3)]).class_mask_changed)

    def test_v1_database_migration_preserves_history_and_exports_new_fields(self):
        config = ReviewConfig("tester", "researcher", self.root, self.root, self.root / "output")
        storage = ReviewStorage.for_config(config)
        session, items, _ = storage.open_or_create_session(config, [ReviewPair(
            "frame", self.root / "frame.png", self.root / "frame.json", 32, 24,
        )])
        saved = storage.save_item(replace(items[0], reviewer_notes="retain history",
                                         original_json_sha256="old-original", raster_mask_changed=False))
        # Reconstruct the prior schema in this disposable fixture, not user data.
        with closing(sqlite3.connect(storage.database_path)) as connection:
            for column in ("class_mask_changed", "class_mask_error", "class_mask_policy"):
                connection.execute(f"ALTER TABLE review_items DROP COLUMN {column}")
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
        migrated = ReviewStorage.for_config(config)
        old = migrated.list_items(session.session_id)[0]
        self.assertEqual(old.item_id, saved.item_id)
        self.assertEqual(old.reviewer_notes, "retain history")
        self.assertEqual(old.original_json_sha256, "old-original")
        self.assertIsNone(old.class_mask_changed)
        self.assertIsNone(old.class_mask_policy)
        migrated.save_item(replace(old, class_mask_changed=True, class_mask_policy=CLASS_MASK_POLICY))
        with export_session_csv(migrated, session).open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raster_mask_changed"], "0")
        self.assertEqual(rows[0]["class_mask_changed"], "1")
        self.assertEqual(rows[0]["class_mask_policy"], CLASS_MASK_POLICY)
        self.assertEqual(rows[0]["reviewer_notes"], "retain history")
        with closing(sqlite3.connect(migrated.database_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
