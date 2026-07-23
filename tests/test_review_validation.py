import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from review import ReviewConfig, validate_review_config


class ReviewValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.images = self.root / "images"
        self.annotations = self.root / "annotations"
        self.output = self.root / "reviewed"
        self.images.mkdir()
        self.annotations.mkdir()
        self.output.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def config(self, output=None):
        return ReviewConfig(
            reviewer_id="reviewer-1",
            reviewer_role="researcher",
            image_directory=self.images,
            annotation_directory=self.annotations,
            output_directory=output or self.output,
        )

    def write_image(self, relative_path, size=(32, 24)):
        path = self.images / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size).save(path)
        return path

    def write_annotation(self, relative_path, size=(32, 24)):
        path = self.annotations / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "imageWidth": size[0],
            "imageHeight": size[1],
            "shapes": [
                {
                    "label": "object",
                    "shape_type": "polygon",
                    "points": [[1, 1], [10, 1], [10, 10]],
                }
            ],
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_valid_nested_pair(self):
        self.write_image("case-1/frame-001.png")
        self.write_annotation("case-1/frame-001.json")

        report = validate_review_config(self.config())

        self.assertTrue(report.is_valid)
        self.assertEqual(len(report.pairs), 1)
        self.assertEqual(report.pairs[0].relative_key, "case-1/frame-001")
        self.assertEqual(report.pairs[0].image_width, 32)
        self.assertEqual(report.pairs[0].image_height, 24)

    def test_missing_and_orphan_annotations_are_warnings(self):
        self.write_image("matched.png")
        self.write_annotation("matched.json")
        self.write_image("missing.png")
        self.write_annotation("orphan.json")

        report = validate_review_config(self.config())
        codes = {issue.code for issue in report.warnings}

        self.assertTrue(report.is_valid)
        self.assertIn("annotation_missing", codes)
        self.assertIn("orphan_annotation", codes)

    def test_duplicate_image_keys_are_errors(self):
        self.write_image("duplicate.png")
        self.write_image("duplicate.jpg")
        self.write_annotation("duplicate.json")

        report = validate_review_config(self.config())

        self.assertFalse(report.is_valid)
        self.assertIn(
            "duplicate_image_key",
            {issue.code for issue in report.errors},
        )

    def test_invalid_json_blocks_session(self):
        self.write_image("broken.png")
        (self.annotations / "broken.json").write_text(
            "{not valid JSON",
            encoding="utf-8",
        )

        report = validate_review_config(self.config())

        self.assertFalse(report.is_valid)
        self.assertIn("invalid_json", {issue.code for issue in report.errors})

    def test_output_inside_original_annotations_is_rejected(self):
        self.write_image("frame.png")
        self.write_annotation("frame.json")
        nested_output = self.annotations / "reviewed"
        nested_output.mkdir()

        report = validate_review_config(self.config(output=nested_output))

        self.assertFalse(report.is_valid)
        self.assertIn(
            "output_inside_annotations",
            {issue.code for issue in report.errors},
        )


if __name__ == "__main__":
    unittest.main()
