from __future__ import annotations

import sqlite3

VERSION = 4
DESCRIPTION = "Add sessions table and migrate legacy roles"

ROLE_MIGRATION = {
    "admin": "dev",
    "attorney": "solicitor",
    "reviewer": "sr_solicitor",
}


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    for old_role, new_role in ROLE_MIGRATION.items():
        conn.execute(
            "UPDATE users SET role = ? WHERE role = ?",
            (new_role, old_role),
        )
