import csv
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image

from review import (
    ReviewConfig,
    ReviewSessionStatus,
    ReviewStatus,
    ReviewStorage,
    SourceProvenance,
    compare_annotations,
    export_session_csv,
    validate_review_config,
    with_item_status,
)


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.images = self.root / "images"
        self.annotations = self.root / "annotations"
        self.output = self.root / "reviewed"
        for directory in (self.images, self.annotations, self.output):
            directory.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_pair(self, key):
        image_path = self.images / f"{key}.png"
        Image.new("RGB", (32, 24), "black").save(image_path)
        annotation_path = self.annotations / f"{key}.json"
        annotation_path.write_text(
            json.dumps(
                {
                    "imageWidth": 32,
                    "imageHeight": 24,
                    "shapes": [
                        {
                            "label": "object",
                            "shape_type": "polygon",
                            "points": [[1, 1], [8, 1], [8, 8]],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_complete_review_audit_trail(self):
        self.write_pair("frame-001")
        Image.new("RGB", (32, 24), "black").save(
            self.images / "frame-002.png"
        )
        config = ReviewConfig(
            reviewer_id="reviewer-1",
            reviewer_role="researcher",
            image_directory=self.images,
            annotation_directory=self.annotations,
            output_directory=self.output,
        )

        report = validate_review_config(config)
        self.assertTrue(report.is_valid)
        self.assertEqual(len(report.images), 2)
        self.assertEqual(len(report.pairs), 1)

        storage = ReviewStorage.for_config(config)
        session, items, resumed = storage.open_or_create_session(
            config, report.pairs
        )
        self.assertFalse(resumed)

        item = with_item_status(items[0], ReviewStatus.IN_PROGRESS)
        item.reviewed_annotation_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            item.original_annotation_path,
            item.reviewed_annotation_path,
        )
        comparison = compare_annotations(
            item.original_annotation_path,
            item.reviewed_annotation_path,
        )
        item = replace(
            item,
            source_provenance=SourceProvenance.MANUAL_KEYFRAME.value,
            active_review_seconds=4.25,
            original_json_sha256=comparison.original_json_sha256,
            reviewed_json_sha256=comparison.reviewed_json_sha256,
            annotation_changed=comparison.annotation_changed,
            geometry_changed=comparison.geometry_changed,
            raster_mask_changed=comparison.raster_mask_changed,
        )
        item = storage.save_item(
            with_item_status(item, ReviewStatus.NO_CHANGE)
        )
        self.assertFalse(item.annotation_changed)

        session = storage.set_session_status(
            session.session_id, ReviewSessionStatus.COMPLETED
        )
        csv_path = export_session_csv(storage, session)
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_status"], "completed")
        self.assertEqual(rows[0]["status"], "no_change")
        self.assertEqual(rows[0]["source_provenance"], "manual_keyframe")
        self.assertEqual(rows[0]["annotation_changed"], "0")
        self.assertEqual(rows[0]["active_review_seconds"], "4.250")

        next_session, _, resumed = storage.open_or_create_session(
            config, report.pairs
        )
        self.assertFalse(resumed)
        self.assertNotEqual(next_session.session_id, session.session_id)


if __name__ == "__main__":
    unittest.main()
