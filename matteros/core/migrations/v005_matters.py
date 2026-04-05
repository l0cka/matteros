"""v005: Add matter management tables and migrate roles to legal/gc."""
from __future__ import annotations

import sqlite3

VERSION = 5
DESCRIPTION = "Add matters, activities, contacts, deadlines, matter_relationships tables and migrate roles"

ROLE_MIGRATION = {
    "dev": "legal",
    "partner_gc": "gc",
    "sr_solicitor": "legal",
    "solicitor": "legal",
    "paralegal": "legal",
}


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matters (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            type            TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'new',
            assignee_id     TEXT REFERENCES users(id),
            priority        TEXT DEFAULT 'medium',
            privileged      INTEGER NOT NULL DEFAULT 1,
            source          TEXT,
            source_ref      TEXT,
            metadata_json   TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            due_date        TEXT,
            resolved_at     TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activities (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            matter_id       TEXT NOT NULL REFERENCES matters(id),
            actor_id        TEXT REFERENCES users(id),
            type            TEXT NOT NULL,
            visibility      TEXT NOT NULL DEFAULT 'internal',
            content_json    TEXT,
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            email           TEXT NOT NULL UNIQUE,
            department      TEXT,
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matter_contacts (
            matter_id       TEXT NOT NULL REFERENCES matters(id),
            contact_id      TEXT NOT NULL REFERENCES contacts(id),
            role            TEXT DEFAULT 'requestor',
            PRIMARY KEY (matter_id, contact_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS deadlines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            matter_id       TEXT NOT NULL REFERENCES matters(id),
            label           TEXT NOT NULL,
            due_date        TEXT NOT NULL,
            type            TEXT NOT NULL DEFAULT 'hard',
            alert_before    TEXT,
            recurring       TEXT,
            status          TEXT NOT NULL DEFAULT 'pending',
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matter_relationships (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id       TEXT NOT NULL REFERENCES matters(id),
            target_id       TEXT NOT NULL REFERENCES matters(id),
            type            TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            UNIQUE (source_id, target_id, type)
        )
        """
    )

    for old_role, new_role in ROLE_MIGRATION.items():
        conn.execute(
            "UPDATE users SET role = ? WHERE role = ?",
            (new_role, old_role),
        )
