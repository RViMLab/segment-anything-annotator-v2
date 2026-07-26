import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from review import (
    ReviewConfig,
    ReviewPair,
    ReviewSessionStatus,
    ReviewStatus,
    ReviewStorage,
    with_item_status,
)


class ReviewStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.images = self.root / "images"
        self.annotations = self.root / "annotations"
        self.output = self.root / "reviewed"
        self.images.mkdir()
        self.annotations.mkdir()
        self.output.mkdir()
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

    def test_creates_versioned_database_and_items(self):
        storage = ReviewStorage.for_config(self.config)

        session, items, resumed = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1"), self.pair("frame-2")],
        )

        self.assertFalse(resumed)
        self.assertEqual(session.status, ReviewSessionStatus.ACTIVE)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].status, ReviewStatus.UNREVIEWED)
        self.assertEqual(
            items[0].reviewed_annotation_path,
            self.output / "frame-1.json",
        )
        with sqlite3.connect(storage.database_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 1)

    def test_reopening_same_configuration_resumes_without_duplicates(self):
        storage = ReviewStorage.for_config(self.config)
        first_session, _, _ = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1"), self.pair("frame-2")],
        )

        second_session, items, resumed = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1"), self.pair("frame-2")],
        )

        self.assertTrue(resumed)
        self.assertEqual(second_session.session_id, first_session.session_id)
        self.assertEqual(len(items), 2)
        self.assertEqual(
            len(storage.list_items(first_session.session_id, active_only=False)),
            2,
        )

    def test_item_progress_persists_across_storage_instances(self):
        storage = ReviewStorage.for_config(self.config)
        session, items, _ = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1")],
        )
        item = with_item_status(items[0], ReviewStatus.IN_PROGRESS)
        item = replace(
            item,
            active_review_seconds=12.5,
            reviewer_notes="Needs a second look",
        )
        storage.save_item(item)

        reopened = ReviewStorage.for_config(self.config)
        saved_item = reopened.list_items(session.session_id)[0]

        self.assertEqual(saved_item.status, ReviewStatus.IN_PROGRESS)
        self.assertEqual(saved_item.active_review_seconds, 12.5)
        self.assertEqual(saved_item.reviewer_notes, "Needs a second look")
        self.assertIsNotNone(saved_item.started_at)
        self.assertEqual(
            reopened.get_resume_item(session.session_id).relative_key,
            "frame-1",
        )

    def test_dataset_changes_keep_history_without_active_duplicates(self):
        storage = ReviewStorage.for_config(self.config)
        session, items, _ = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1"), self.pair("frame-2")],
        )
        completed = with_item_status(
            items[1],
            ReviewStatus.NO_CHANGE,
        )
        storage.save_item(completed)

        _, active_items, resumed = storage.open_or_create_session(
            self.config,
            [self.pair("frame-2"), self.pair("frame-3")],
        )
        all_items = storage.list_items(
            session.session_id,
            active_only=False,
        )

        self.assertTrue(resumed)
        self.assertEqual(
            [item.relative_key for item in active_items],
            ["frame-2", "frame-3"],
        )
        self.assertEqual(len(all_items), 3)
        frame_1 = next(
            item for item in all_items if item.relative_key == "frame-1"
        )
        frame_2 = next(
            item for item in all_items if item.relative_key == "frame-2"
        )
        self.assertFalse(frame_1.is_active)
        self.assertEqual(frame_2.status, ReviewStatus.NO_CHANGE)

    def test_completed_session_is_not_resumed(self):
        storage = ReviewStorage.for_config(self.config)
        first_session, _, _ = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1")],
        )
        storage.set_session_status(
            first_session.session_id,
            ReviewSessionStatus.COMPLETED,
        )

        next_session, _, resumed = storage.open_or_create_session(
            self.config,
            [self.pair("frame-1")],
        )

        self.assertFalse(resumed)
        self.assertNotEqual(next_session.session_id, first_session.session_id)


if __name__ == "__main__":
    unittest.main()
