import json
import tempfile
import unittest
from pathlib import Path

from review import compare_annotations


class ReviewComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_annotation(self, name, points, **shape_changes):
        shape = {
            "label": "object",
            "shape_type": "polygon",
            "points": points,
        }
        shape.update(shape_changes)
        data = {
            "imageWidth": 32,
            "imageHeight": 24,
            "shapes": [shape],
        }
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_identical_files_have_no_changes(self):
        original = self.write_annotation("original.json", [[1, 1], [8, 1], [8, 8]])
        reviewed = self.root / "reviewed.json"
        reviewed.write_bytes(original.read_bytes())

        result = compare_annotations(original, reviewed)

        self.assertFalse(result.annotation_changed)
        self.assertFalse(result.geometry_changed)
        self.assertFalse(result.raster_mask_changed)
        self.assertEqual(result.original_json_sha256, result.reviewed_json_sha256)

    def test_formatting_and_polygon_start_point_do_not_change_geometry(self):
        original = self.write_annotation("original.json", [[1, 1], [8, 1], [8, 8]])
        reviewed = self.write_annotation("reviewed.json", [[8, 1], [8, 8], [1, 1]])
        reviewed.write_text(
            json.dumps(json.loads(reviewed.read_text()), indent=2),
            encoding="utf-8",
        )

        result = compare_annotations(original, reviewed)

        self.assertTrue(result.annotation_changed)
        self.assertFalse(result.geometry_changed)
        self.assertFalse(result.raster_mask_changed)

    def test_moved_polygon_changes_geometry_and_mask(self):
        original = self.write_annotation("original.json", [[1, 1], [8, 1], [8, 8]])
        reviewed = self.write_annotation("reviewed.json", [[2, 1], [9, 1], [9, 8]])

        result = compare_annotations(original, reviewed)

        self.assertTrue(result.annotation_changed)
        self.assertTrue(result.geometry_changed)
        self.assertTrue(result.raster_mask_changed)

    def test_missing_reviewed_file_records_only_original_hash(self):
        original = self.write_annotation("original.json", [[1, 1], [8, 1], [8, 8]])

        result = compare_annotations(original, None)

        self.assertIsNotNone(result.original_json_sha256)
        self.assertIsNone(result.reviewed_json_sha256)
        self.assertIsNone(result.annotation_changed)
        self.assertIsNone(result.geometry_changed)
        self.assertIsNone(result.raster_mask_changed)


if __name__ == "__main__":
    unittest.main()
