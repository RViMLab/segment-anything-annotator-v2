import csv
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from review import (
    ReviewConfig,
    ReviewPair,
    ReviewStatus,
    ReviewStorage,
    SourceProvenance,
    export_session_csv,
    derive_frame_idx,
    with_item_status,
)


class ReviewExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.images = self.root / "images"
        self.annotations = self.root / "annotations"
        self.output = self.root / "reviewed"
        for directory in (self.images, self.annotations, self.output):
            directory.mkdir()
        self.config = ReviewConfig(
            reviewer_id="reviewer-1",
            reviewer_role="researcher",
            image_directory=self.images,
            annotation_directory=self.annotations,
            output_directory=self.output,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def pair(self, key):
        return ReviewPair(
            relative_key=key,
            image_path=self.images / f"{key}.png",
            annotation_path=self.annotations / f"{key}.json",
            image_width=32,
            image_height=24,
        )

    def read_rows(self, path):
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_repeated_export_rewrites_rows_without_duplicates(self):
        storage = ReviewStorage.for_config(self.config)
        session, items, _ = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1")],
        )
        item = with_item_status(items[0], ReviewStatus.MINOR_CORRECTION)
        storage.save_item(
            replace(
                item,
                reviewer_notes="Moved edge, then checked mask",
                source_provenance=(
                    SourceProvenance.REVIEWED_PROPAGATED_FRAME.value
                ),
                annotation_changed=True,
                geometry_changed=True,
                raster_mask_changed=True,
            )
        )

        first_path = export_session_csv(storage, session)
        second_path = export_session_csv(storage, session)
        rows = self.read_rows(second_path)

        self.assertEqual(first_path, second_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relative_key"], "frame-1")
        self.assertEqual(rows[0]["source_provenance"], "reviewed_propagated_frame")
        self.assertEqual(rows[0]["geometry_changed"], "1")
        self.assertEqual(rows[0]["reviewer_notes"], "Moved edge, then checked mask")

    def test_export_retains_inactive_history_once(self):
        storage = ReviewStorage.for_config(self.config)
        session, _, _ = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1"), self.pair("frame-2")],
        )
        session, _, _ = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1")],
        )

        rows = self.read_rows(export_session_csv(storage, session))

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["relative_key"] for row in rows},
            {"frame-1", "frame-2"},
        )
        inactive = next(row for row in rows if row["relative_key"] == "frame-2")
        self.assertEqual(inactive["is_active"], "0")

    def test_strict_frame_index_parser(self):
        self.assertEqual(derive_frame_idx("frame_024550"), 24550)
        self.assertEqual(derive_frame_idx("frame_024550.json"), 24550)
        self.assertEqual(derive_frame_idx("frame_024550.png"), 24550)
        self.assertEqual(derive_frame_idx("case/frame_024550"), 24550)
        for value in (
            "024550",
            "my_frame_024550",
            "frame_024550_extra",
            "frame_24.5",
            "frame_.png",
        ):
            self.assertIsNone(derive_frame_idx(value))


if __name__ == "__main__":
    unittest.main()
