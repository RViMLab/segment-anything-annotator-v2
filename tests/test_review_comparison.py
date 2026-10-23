import json
import itertools
import math
import random
import tempfile
import tracemalloc
import unittest
from pathlib import Path

from review import compare_annotations
from review.comparison import _canonical_polygon


def legacy_canonical_polygon(points):
    """Original implementation retained only as a small-input test oracle."""
    points = tuple((round(float(x), 8), round(float(y), 8)) for x, y in points)
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if not points:
        return points
    reverse = tuple(reversed(points))
    return min(
        sequence[index:] + sequence[:index]
        for sequence in (points, reverse)
        for index in range(len(sequence))
    )


class PolygonCanonicalizationTests(unittest.TestCase):
    def test_matches_legacy_on_exhaustive_small_sequences(self):
        # Includes repeated minima, repeated closure, and periodic sequences.
        alphabet = ((0, 0), (0, 1), (1, 0))
        for size in range(8):
            for points in itertools.product(alphabet, repeat=size):
                self.assertEqual(_canonical_polygon(points), legacy_canonical_polygon(points), points)

    def test_matches_legacy_on_seeded_random_sequences(self):
        generator = random.Random(30)
        for _ in range(200):
            points = [(generator.uniform(-20, 20), generator.uniform(-20, 20))
                      for _ in range(generator.randrange(1, 100))]
            if generator.choice((True, False)):
                points.append(points[0])
            self.assertEqual(_canonical_polygon(points), legacy_canonical_polygon(points))

    def test_coordinate_rounding_matches_legacy(self):
        points = [(1.000000001, 2), (1.000000002, 2), (-0.0, -3.123456789), (1, 2)]
        self.assertEqual(_canonical_polygon(points), legacy_canonical_polygon(points))

    def test_large_periodic_and_identical_sequences(self):
        for points in ([(1, 1)] * 3000, [(0, 0), (1, 1), (0, 0)] * 1000):
            expected = _canonical_polygon(points)
            # Preserve the legacy removal of exactly one closing vertex.
            open_points = points[:-1] if points[0] == points[-1] else points
            rotated = open_points[517:] + open_points[:517]
            rotated.append(rotated[0])
            self.assertEqual(expected, _canonical_polygon(rotated))
            reversed_closed = list(reversed(open_points))
            reversed_closed.append(reversed_closed[0])
            self.assertEqual(expected, _canonical_polygon(reversed_closed))

    def test_high_vertex_polygon_has_bounded_memory(self):
        points = [(math.cos(index * math.tau / 3000), math.sin(index * math.tau / 3000))
                  for index in range(3000)]
        tracemalloc.start()
        try:
            result = _canonical_polygon(points)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(result), 3000)
        # Generous headroom for Python/platform differences; the old algorithm
        # used over 100 MiB at this contour size.
        self.assertLess(peak, 8 * 1024 * 1024)


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

    def test_high_vertex_review_detects_edit_without_mutating_files(self):
        points = [[16 + 10 * math.cos(index * math.tau / 2660),
                   12 + 10 * math.sin(index * math.tau / 2660)] for index in range(2660)]
        original = self.write_annotation("original.json", points)
        reordered = list(reversed(points[900:] + points[:900]))
        reviewed = self.write_annotation("reviewed.json", reordered)
        original_bytes, reviewed_bytes = original.read_bytes(), reviewed.read_bytes()
        comparison = compare_annotations(original, reviewed)
        self.assertFalse(comparison.geometry_changed)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(reviewed.read_bytes(), reviewed_bytes)
        reordered[0] = [reordered[0][0] + 0.25, reordered[0][1]]
        reviewed = self.write_annotation("reviewed.json", reordered)
        self.assertTrue(compare_annotations(original, reviewed).geometry_changed)


if __name__ == "__main__":
    unittest.main()
