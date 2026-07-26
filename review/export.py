"""Duplicate-safe CSV export for persisted review sessions."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path


CSV_COLUMNS = (
    "session_id",
    "session_status",
    "reviewer_id",
    "reviewer_role",
    "relative_key",
    "ordinal",
    "image_path",
    "original_annotation_path",
    "reviewed_annotation_path",
    "status",
    "active_review_seconds",
    "reviewer_notes",
    "problem_status",
    "source_provenance",
    "original_json_sha256",
    "reviewed_json_sha256",
    "annotation_changed",
    "geometry_changed",
    "raster_mask_changed",
    "started_at",
    "completed_at",
    "created_at",
    "updated_at",
    "is_active",
)


def _optional_bool(value):
    if value is None:
        return ""
    return "1" if value else "0"


def default_csv_path(session) -> Path:
    return session.output_directory / f"review_session_{session.session_id}.csv"


def export_session_csv(storage, session, destination=None) -> Path:
    """Atomically rewrite one row per persisted item in a review session."""
    destination = Path(destination or default_csv_path(session)).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    items = storage.list_items(session.session_id, active_only=False)

    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8-sig",
            newline="",
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for item in items:
                writer.writerow(
                    {
                        "session_id": session.session_id,
                        "session_status": session.status.value,
                        "reviewer_id": session.reviewer_id,
                        "reviewer_role": session.reviewer_role,
                        "relative_key": item.relative_key,
                        "ordinal": item.ordinal,
                        "image_path": str(item.image_path),
                        "original_annotation_path": str(
                            item.original_annotation_path
                        ),
                        "reviewed_annotation_path": str(
                            item.reviewed_annotation_path
                        ),
                        "status": item.status.value,
                        "active_review_seconds": format(
                            item.active_review_seconds, ".3f"
                        ),
                        "reviewer_notes": item.reviewer_notes,
                        "problem_status": item.problem_status,
                        "source_provenance": item.source_provenance,
                        "original_json_sha256": item.original_json_sha256 or "",
                        "reviewed_json_sha256": item.reviewed_json_sha256 or "",
                        "annotation_changed": _optional_bool(
                            item.annotation_changed
                        ),
                        "geometry_changed": _optional_bool(
                            item.geometry_changed
                        ),
                        "raster_mask_changed": _optional_bool(
                            item.raster_mask_changed
                        ),
                        "started_at": item.started_at or "",
                        "completed_at": item.completed_at or "",
                        "created_at": item.created_at,
                        "updated_at": item.updated_at,
                        "is_active": "1" if item.is_active else "0",
                    }
                )
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    return destination
