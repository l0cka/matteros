"""v006: Add automation_state table for poll cursors and alert dedup."""
from __future__ import annotations
import sqlite3

VERSION = 6
DESCRIPTION = "Add automation_state key-value table"

def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_state (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
