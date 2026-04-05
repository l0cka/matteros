"""AutomationState — key-value persistence for poll cursors and alert dedup."""
from __future__ import annotations
from datetime import UTC, datetime
from matteros.core.store import SQLiteStore

class AutomationState:
    def __init__(self, db: SQLiteStore) -> None:
        self._db = db

    def get(self, key: str) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT value FROM automation_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO automation_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
                """,
                (key, value, now, value, now),
            )
            conn.commit()

    def has(self, key: str) -> bool:
        return self.get(key) is not None
