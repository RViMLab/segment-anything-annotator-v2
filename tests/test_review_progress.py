import unittest
from types import SimpleNamespace

from review import (
    ReviewStatus,
    calculate_review_progress,
    finish_confirmation_text,
    progress_text,
)


def item(status, seconds=0, active=True):
    return SimpleNamespace(
        status=status,
        active_review_seconds=seconds,
        is_active=active,
    )


class ReviewProgressTests(unittest.TestCase):
    def test_mixed_status_counts(self):
        items = [
            item(ReviewStatus.NO_CHANGE, 10),
            item(ReviewStatus.MINOR_CORRECTION, 20),
            item(ReviewStatus.MAJOR_CORRECTION, 30),
            item(ReviewStatus.UNABLE_TO_REVIEW, 40),
            item(ReviewStatus.IN_PROGRESS, 1000),
            item(ReviewStatus.UNREVIEWED),
            item(ReviewStatus.NO_CHANGE, 5, active=False),
        ]
        progress = calculate_review_progress(items)
        self.assertEqual(progress.total, 6)
        self.assertEqual(progress.reviewed, 4)
        self.assertEqual(progress.in_progress, 1)
        self.assertEqual(progress.unreviewed, 1)
        self.assertEqual(progress.remaining, 2)
        self.assertAlmostEqual(progress.percentage, 66.666, places=2)
        self.assertIsNone(progress.estimated_remaining_seconds)

    def test_median_estimate_resists_outlier(self):
        completed = [10, 11, 12, 13, 1000]
        items = [item(ReviewStatus.NO_CHANGE, value) for value in completed]
        items.extend(
            [item(ReviewStatus.IN_PROGRESS), item(ReviewStatus.UNREVIEWED)]
        )
        progress = calculate_review_progress(items)
        self.assertEqual(progress.estimated_remaining_seconds, 24)

    def test_zero_remaining_is_safe(self):
        progress = calculate_review_progress(
            [item(ReviewStatus.NO_CHANGE, 10)]
        )
        self.assertEqual(progress.estimated_remaining_seconds, 0)
        self.assertIn("approximately 0 min", progress_text(progress))

    def test_partial_finish_warning_preserves_statuses(self):
        progress = calculate_review_progress(
            [item(ReviewStatus.NO_CHANGE), item(ReviewStatus.IN_PROGRESS)]
        )
        message = finish_confirmation_text(progress)
        self.assertIn("Opened but undecided: 1", message)
        self.assertIn("statuses will remain unchanged", message)
        self.assertIn("prevent it from being resumed", message)

    def test_complete_finish_message_is_simpler(self):
        progress = calculate_review_progress(
            [item(ReviewStatus.NO_CHANGE)]
        )
        message = finish_confirmation_text(progress)
        self.assertIn("All targets", message)
        self.assertNotIn("Some targets", message)


if __name__ == "__main__":
    unittest.main()
