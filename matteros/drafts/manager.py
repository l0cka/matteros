"""Proactive draft management — auto-triggers runs and queues drafts for review."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from matteros.core.store import SQLiteStore


class DraftManager:
    """Manages the lifecycle of proactive time entry drafts.

    Drafts are created by the daemon when enough new activity is detected,
    and queued for user review via TUI or CLI.
    """

    def __init__(self, store: SQLiteStore, event_bus: Any | None = None) -> None:
        self.store = store
        self._event_bus = event_bus

    def create_draft(
        self,
        *,
        run_id: str,
        entry: dict[str, Any],
        pattern_ids: list[str] | None = None,
    ) -> str:
        draft_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO drafts (id, run_id, status, created_at, updated_at, entry_json, pattern_ids_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    run_id,
                    "pending",
                    now,
                    now,
                    json.dumps(entry, sort_keys=True),
                    json.dumps(pattern_ids or []),
                ),
            )
            conn.commit()

        if self._event_bus is not None:
            try:
                from matteros.core.events import EventType, RunEvent

                self._event_bus.emit(RunEvent(
                    event_type=EventType.DRAFT_CREATED,
                    run_id=run_id,
                    actor="system",
                    data={"draft_id": draft_id},
                ))
            except Exception:
                pass  # event emission is advisory

        return draft_id

    def list_drafts(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self.store.connection() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM drafts WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM drafts ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_draft(row) for row in rows]

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            return self._row_to_draft(row) if row else None

    def approve_draft(self, draft_id: str) -> None:
        self._update_status(draft_id, "approved")

    def reject_draft(self, draft_id: str) -> None:
        self._update_status(draft_id, "rejected")

    def expire_draft(self, draft_id: str) -> None:
        self._update_status(draft_id, "expired")

    def update_entry(self, draft_id: str, entry: dict[str, Any]) -> None:
        """Update the entry_json for a draft (used when editing before approval)."""
        now = datetime.now(UTC).isoformat()
        with self.store.connection() as conn:
            conn.execute(
                "UPDATE drafts SET entry_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(entry, sort_keys=True), now, draft_id),
            )
            conn.commit()

    def expire_stale_drafts(self, max_age_hours: int = 72) -> int:
        """Mark pending drafts older than max_age_hours as expired. Returns count."""
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
        now = datetime.now(UTC).isoformat()
        with self.store.connection() as conn:
            cursor = conn.execute(
                "UPDATE drafts SET status = 'expired', updated_at = ? WHERE status = 'pending' AND created_at < ?",
                (now, cutoff),
            )
            conn.commit()
            return cursor.rowcount

    def pending_count(self) -> int:
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM drafts WHERE status = 'pending'"
            ).fetchone()
            return row[0] if row else 0

    def _update_status(self, draft_id: str, status: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self.store.connection() as conn:
            conn.execute(
                "UPDATE drafts SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, draft_id),
            )
            conn.commit()

    def _row_to_draft(self, row: Any) -> dict[str, Any]:
        result = {
            "id": row["id"],
            "run_id": row["run_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "entry": json.loads(row["entry_json"]) if row["entry_json"] else {},
            "pattern_ids": json.loads(row["pattern_ids_json"]) if row["pattern_ids_json"] else [],
        }
        # user_id column added in v003 migration
        try:
            result["user_id"] = row["user_id"]
        except (IndexError, KeyError):
            result["user_id"] = "solo"
        return result
