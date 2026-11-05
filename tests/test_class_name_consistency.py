"""Read-only dataset name checks, example counts, and cache invalidation."""

import json
from pathlib import Path
import tempfile
from threading import Event
import unittest

from utils.class_name_consistency import ClassNameChecker, image_examples


def shape(name, group=3):
    return {"label": name, "group_id": group, "points": [[1, 1], [8, 1], [8, 8]]}


class ClassNameCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.checker = ClassNameChecker()

    def tearDown(self):
        self.temporary.cleanup()

    def annotation(self, name, records):
        path = self.root / name
        path.write_text(json.dumps({"shapes": records, "imageData": "large-ignored-payload"}))
        return path

    def test_one_peer_has_one_filename_without_other_image_suffix(self):
        path = self.annotation("first.json", [shape("cat"), shape("cat")])
        original = path.read_bytes()
        report = self.checker.check([shape("dog")], [("first.png", path)])
        self.assertEqual(len(report.conflicts), 1)
        self.assertIn('in image first.png.', report.message())
        self.assertNotIn("other image", report.message())
        self.assertEqual(path.read_bytes(), original)
        self.assertNotIn("imageData", str(self.checker.cache))

    def test_three_examples_plus_exact_remaining_distinct_image_count(self):
        peers = [(f"frame-{index}.png", self.annotation(f"frame-{index}.json", [shape("cat")] * 3))
                 for index in range(6)]
        report = self.checker.check([shape("dog")], peers)
        self.assertIn("frame-0.png, frame-1.png, frame-2.png and 3 other images", report.message())
        self.assertNotIn("frame-3.png", report.message())

    def test_same_image_conflict_needs_no_peer(self):
        report = self.checker.check([shape("cat"), shape("dog", "03")], [])
        self.assertIn('different names in this image: "cat", "dog"', report.message())

    def test_consistent_names_and_different_ids_do_not_warn(self):
        path = self.annotation("first.json", [shape("dog", 4), shape("cat", 3)])
        self.assertFalse(self.checker.check([shape("cat", 3)], [("first.png", path)]).conflicts)

    def test_cache_refreshes_when_saved_names_change(self):
        path = self.annotation("first.json", [shape("cat")])
        self.assertTrue(self.checker.check([shape("dog")], [("first.png", path)]).conflicts)
        path.write_text(json.dumps({"shapes": [shape("dog")], "note": "size change"}))
        self.assertFalse(self.checker.check([shape("dog")], [("first.png", path)]).conflicts)

    def test_reviewed_file_preferred_and_original_used_when_no_reviewed_file(self):
        original = self.annotation("original.json", [shape("cat")])
        reviewed = self.annotation("reviewed.json", [shape("dog")])
        peers = [("first.png", (reviewed, original))]
        self.assertFalse(self.checker.check([shape("dog")], peers).conflicts)
        reviewed.unlink()
        self.assertTrue(self.checker.check([shape("dog")], peers).conflicts)

    def test_bad_saved_file_is_reported_and_unannotated_frame_is_skipped(self):
        path = self.root / "bad.json"
        path.write_text("bad JSON")
        report = self.checker.check([shape("cat")], [("bad.png", path), ("new.png", self.root / "missing.json")])
        self.assertEqual(len(report.unreadable), 1)
        self.assertIn("Could not check 1 saved annotation", report.message())

    def test_cancelled_scan_does_not_claim_consistency(self):
        cancelled = Event()
        cancelled.set()
        path = self.annotation("first.json", [shape("cat")])
        self.assertTrue(self.checker.check([shape("dog")], [("first.png", path)], cancelled).cancelled)

    def test_example_wording_handles_zero_one_two_three_and_four(self):
        self.assertEqual(image_examples(["one"]), "one")
        self.assertEqual(image_examples(["one", "one"]), "one")
        self.assertNotIn("other", image_examples(["one", "two", "three"]))
        self.assertIn("1 other image", image_examples(["one", "two", "three", "four"]))
