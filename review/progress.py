"""Derived review progress counts and remaining-time estimates."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .models import ReviewStatus


COMPLETED_STATUSES = {
    ReviewStatus.NO_CHANGE,
    ReviewStatus.MINOR_CORRECTION,
    ReviewStatus.MAJOR_CORRECTION,
    ReviewStatus.UNABLE_TO_REVIEW,
}


@dataclass(frozen=True)
class ReviewProgress:
    total: int
    reviewed: int
    in_progress: int
    unreviewed: int
    remaining: int
    percentage: float
    estimated_remaining_seconds: float | None


def calculate_review_progress(items, minimum_estimate_samples=5):
    active_items = [item for item in items if item.is_active]
    reviewed_items = [
        item for item in active_items if item.status in COMPLETED_STATUSES
    ]
    in_progress = sum(
        item.status == ReviewStatus.IN_PROGRESS for item in active_items
    )
    unreviewed = sum(
        item.status == ReviewStatus.UNREVIEWED for item in active_items
    )
    remaining = in_progress + unreviewed
    estimate = None
    if remaining == 0:
        estimate = 0.0
    elif len(reviewed_items) >= minimum_estimate_samples:
        estimate = statistics.median(
            item.active_review_seconds for item in reviewed_items
        ) * remaining
    total = len(active_items)
    reviewed = len(reviewed_items)
    return ReviewProgress(
        total=total,
        reviewed=reviewed,
        in_progress=in_progress,
        unreviewed=unreviewed,
        remaining=remaining,
        percentage=(100.0 * reviewed / total) if total else 0.0,
        estimated_remaining_seconds=estimate,
    )


def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    if seconds < 3600:
        minutes = max(1, round(seconds / 60)) if seconds else 0
        return f"{minutes} min"
    if seconds < 86400:
        hours = seconds // 3600
        minutes = round((seconds % 3600) / 60)
        if minutes == 60:
            hours += 1
            minutes = 0
        return f"{hours} h" + (f" {minutes} min" if minutes else "")
    days = seconds // 86400
    hours = round((seconds % 86400) / 3600)
    if hours == 24:
        days += 1
        hours = 0
    return f"{days} d" + (f" {hours} h" if hours else "")


def progress_text(progress):
    estimate = (
        "insufficient data"
        if progress.estimated_remaining_seconds is None
        else f"approximately {format_duration(progress.estimated_remaining_seconds)}"
    )
    return (
        f"Reviewed: {progress.reviewed} / {progress.total} "
        f"({progress.percentage:.1f}%)\n"
        f"Remaining: {progress.remaining}\n"
        f"Opened but undecided: {progress.in_progress}\n"
        f"Not yet opened: {progress.unreviewed}\n"
        f"Estimated remaining review time: {estimate}"
    )


def finish_confirmation_text(progress):
    counts = (
        f"Reviewed: {progress.reviewed} / {progress.total}\n"
        f"Opened but undecided: {progress.in_progress}\n"
        f"Not yet opened: {progress.unreviewed}\n"
        f"Remaining: {progress.remaining}"
    )
    if progress.remaining:
        return (
            f"{counts}\n\n"
            "Some targets do not have a completed review decision.\n\n"
            "Completing this session will prevent it from being resumed "
            "automatically next time. The unfinished target statuses will "
            "remain unchanged.\n\n"
            "Mark this review session as complete?"
        )
    return (
        f"{counts}\n\nAll targets have a completed review decision.\n\n"
        "Mark this review session as complete?"
    )
