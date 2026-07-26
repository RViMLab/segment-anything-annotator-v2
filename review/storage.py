from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple

from .models import (
    ReviewConfig,
    ReviewItemRecord,
    ReviewPair,
    ReviewSessionRecord,
    ReviewSessionStatus,
    ReviewStatus,
)


SCHEMA_VERSION = 1
DEFAULT_DATABASE_FILENAME = "review_session.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _optional_bool(value):
    if value is None:
        return None
    return bool(value)


class ReviewStorage:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def for_config(cls, config: ReviewConfig) -> "ReviewStorage":
        config = config.normalized()
        return cls(config.output_directory / DEFAULT_DATABASE_FILENAME)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    "Review database schema is newer than this application "
                    f"supports ({version} > {SCHEMA_VERSION})."
                )
            if version == 0:
                connection.executescript(
                    """
                    CREATE TABLE review_sessions (
                        session_id TEXT PRIMARY KEY,
                        reviewer_id TEXT NOT NULL,
                        reviewer_role TEXT NOT NULL DEFAULT '',
                        image_directory TEXT NOT NULL,
                        annotation_directory TEXT NOT NULL,
                        output_directory TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'active',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX idx_review_sessions_lookup
                    ON review_sessions (
                        reviewer_id,
                        image_directory,
                        annotation_directory,
                        output_directory,
                        status
                    );

                    CREATE TABLE review_items (
                        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        relative_key TEXT NOT NULL,
                        image_path TEXT NOT NULL,
                        original_annotation_path TEXT NOT NULL,
                        reviewed_annotation_path TEXT NOT NULL,
                        image_width INTEGER,
                        image_height INTEGER,
                        status TEXT NOT NULL DEFAULT 'unreviewed',
                        active_review_seconds REAL NOT NULL DEFAULT 0,
                        reviewer_notes TEXT NOT NULL DEFAULT '',
                        problem_status TEXT NOT NULL DEFAULT '',
                        source_provenance TEXT NOT NULL DEFAULT 'unknown',
                        original_json_sha256 TEXT,
                        reviewed_json_sha256 TEXT,
                        annotation_changed INTEGER,
                        geometry_changed INTEGER,
                        raster_mask_changed INTEGER,
                        started_at TEXT,
                        completed_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        UNIQUE (session_id, relative_key),
                        FOREIGN KEY (session_id)
                            REFERENCES review_sessions(session_id)
                            ON DELETE CASCADE
                    );

                    CREATE INDEX idx_review_items_progress
                    ON review_items (session_id, is_active, status, ordinal);
                    """
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def open_or_create_session(
        self,
        config: ReviewConfig,
        pairs: Iterable[ReviewPair],
    ) -> Tuple[ReviewSessionRecord, List[ReviewItemRecord], bool]:
        config = config.normalized()
        pairs = list(pairs)
        timestamp = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT *
                FROM review_sessions
                WHERE reviewer_id = ?
                  AND image_directory = ?
                  AND annotation_directory = ?
                  AND output_directory = ?
                  AND status = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    config.reviewer_id,
                    str(config.image_directory),
                    str(config.annotation_directory),
                    str(config.output_directory),
                    ReviewSessionStatus.ACTIVE.value,
                ),
            ).fetchone()
            resumed = row is not None
            if row is None:
                session_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO review_sessions (
                        session_id,
                        reviewer_id,
                        reviewer_role,
                        image_directory,
                        annotation_directory,
                        output_directory,
                        status,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        config.reviewer_id,
                        config.reviewer_role,
                        str(config.image_directory),
                        str(config.annotation_directory),
                        str(config.output_directory),
                        ReviewSessionStatus.ACTIVE.value,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                session_id = row["session_id"]
                connection.execute(
                    """
                    UPDATE review_sessions
                    SET reviewer_role = ?, updated_at = ?
                    WHERE session_id = ?
                    """,
                    (config.reviewer_role, timestamp, session_id),
                )

            connection.execute(
                """
                UPDATE review_items
                SET is_active = 0, updated_at = ?
                WHERE session_id = ?
                """,
                (timestamp, session_id),
            )
            for ordinal, pair in enumerate(pairs):
                relative_annotation = pair.annotation_path.relative_to(
                    config.annotation_directory
                )
                reviewed_annotation = (
                    config.output_directory / relative_annotation
                )
                connection.execute(
                    """
                    INSERT INTO review_items (
                        session_id,
                        ordinal,
                        relative_key,
                        image_path,
                        original_annotation_path,
                        reviewed_annotation_path,
                        image_width,
                        image_height,
                        created_at,
                        updated_at,
                        is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(session_id, relative_key) DO UPDATE SET
                        ordinal = excluded.ordinal,
                        image_path = excluded.image_path,
                        original_annotation_path =
                            excluded.original_annotation_path,
                        reviewed_annotation_path =
                            excluded.reviewed_annotation_path,
                        image_width = excluded.image_width,
                        image_height = excluded.image_height,
                        updated_at = excluded.updated_at,
                        is_active = 1
                    """,
                    (
                        session_id,
                        ordinal,
                        pair.relative_key,
                        str(pair.image_path),
                        str(pair.annotation_path),
                        str(reviewed_annotation),
                        pair.image_width,
                        pair.image_height,
                        timestamp,
                        timestamp,
                    ),
                )
            connection.execute(
                """
                UPDATE review_sessions
                SET updated_at = ?
                WHERE session_id = ?
                """,
                (timestamp, session_id),
            )
            session_row = connection.execute(
                "SELECT * FROM review_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            item_rows = connection.execute(
                """
                SELECT *
                FROM review_items
                WHERE session_id = ? AND is_active = 1
                ORDER BY ordinal
                """,
                (session_id,),
            ).fetchall()
        return (
            self._session_from_row(session_row),
            [self._item_from_row(item_row) for item_row in item_rows],
            resumed,
        )

    def list_items(
        self,
        session_id: str,
        active_only: bool = True,
    ) -> List[ReviewItemRecord]:
        query = "SELECT * FROM review_items WHERE session_id = ?"
        parameters = [session_id]
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY ordinal"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._item_from_row(row) for row in rows]

    def get_resume_item(
        self,
        session_id: str,
    ) -> Optional[ReviewItemRecord]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM review_items
                WHERE session_id = ?
                  AND is_active = 1
                  AND status IN (?, ?)
                ORDER BY
                    CASE status WHEN ? THEN 0 ELSE 1 END,
                    ordinal
                LIMIT 1
                """,
                (
                    session_id,
                    ReviewStatus.IN_PROGRESS.value,
                    ReviewStatus.UNREVIEWED.value,
                    ReviewStatus.IN_PROGRESS.value,
                ),
            ).fetchone()
        return self._item_from_row(row) if row is not None else None

    def save_item(self, item: ReviewItemRecord) -> ReviewItemRecord:
        timestamp = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE review_items
                SET status = ?,
                    active_review_seconds = ?,
                    reviewer_notes = ?,
                    problem_status = ?,
                    source_provenance = ?,
                    original_json_sha256 = ?,
                    reviewed_json_sha256 = ?,
                    annotation_changed = ?,
                    geometry_changed = ?,
                    raster_mask_changed = ?,
                    started_at = ?,
                    completed_at = ?,
                    updated_at = ?
                WHERE item_id = ? AND session_id = ?
                """,
                (
                    item.status.value,
                    item.active_review_seconds,
                    item.reviewer_notes,
                    item.problem_status,
                    item.source_provenance,
                    item.original_json_sha256,
                    item.reviewed_json_sha256,
                    item.annotation_changed,
                    item.geometry_changed,
                    item.raster_mask_changed,
                    item.started_at,
                    item.completed_at,
                    timestamp,
                    item.item_id,
                    item.session_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(
                    f"Review item {item.item_id} was not found in session "
                    f"{item.session_id}."
                )
            row = connection.execute(
                "SELECT * FROM review_items WHERE item_id = ?",
                (item.item_id,),
            ).fetchone()
        return self._item_from_row(row)

    def set_session_status(
        self,
        session_id: str,
        status: ReviewSessionStatus,
    ) -> ReviewSessionRecord:
        timestamp = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE review_sessions
                SET status = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (status.value, timestamp, session_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Review session {session_id} was not found.")
            row = connection.execute(
                "SELECT * FROM review_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._session_from_row(row)

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> ReviewSessionRecord:
        return ReviewSessionRecord(
            session_id=row["session_id"],
            reviewer_id=row["reviewer_id"],
            reviewer_role=row["reviewer_role"],
            image_directory=Path(row["image_directory"]),
            annotation_directory=Path(row["annotation_directory"]),
            output_directory=Path(row["output_directory"]),
            status=ReviewSessionStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> ReviewItemRecord:
        return ReviewItemRecord(
            item_id=row["item_id"],
            session_id=row["session_id"],
            ordinal=row["ordinal"],
            relative_key=row["relative_key"],
            image_path=Path(row["image_path"]),
            original_annotation_path=Path(
                row["original_annotation_path"]
            ),
            reviewed_annotation_path=Path(row["reviewed_annotation_path"]),
            image_width=row["image_width"],
            image_height=row["image_height"],
            status=ReviewStatus(row["status"]),
            active_review_seconds=row["active_review_seconds"],
            reviewer_notes=row["reviewer_notes"],
            problem_status=row["problem_status"],
            source_provenance=row["source_provenance"],
            original_json_sha256=row["original_json_sha256"],
            reviewed_json_sha256=row["reviewed_json_sha256"],
            annotation_changed=_optional_bool(row["annotation_changed"]),
            geometry_changed=_optional_bool(row["geometry_changed"]),
            raster_mask_changed=_optional_bool(row["raster_mask_changed"]),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_active=bool(row["is_active"]),
        )


def with_item_status(
    item: ReviewItemRecord,
    status: ReviewStatus,
) -> ReviewItemRecord:
    timestamp = utc_now()
    started_at = item.started_at
    completed_at = item.completed_at
    if status == ReviewStatus.IN_PROGRESS and started_at is None:
        started_at = timestamp
    if status in {
        ReviewStatus.NO_CHANGE,
        ReviewStatus.MINOR_CORRECTION,
        ReviewStatus.MAJOR_CORRECTION,
        ReviewStatus.UNABLE_TO_REVIEW,
    }:
        completed_at = timestamp
    return replace(
        item,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
    )
