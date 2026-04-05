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
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS matters (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            type TEXT,
            status TEXT NOT NULL,
            privileged INTEGER DEFAULT 0,
            assignee_id TEXT,
            priority TEXT,
            source TEXT,
            source_ref TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            due_date TEXT,
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS activities (
            id TEXT PRIMARY KEY,
            matter_id TEXT NOT NULL,
            actor_id TEXT,
            type TEXT,
            visibility TEXT,
            content_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(matter_id) REFERENCES matters(id)
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            department TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS matter_contacts (
            matter_id TEXT NOT NULL,
            contact_id TEXT NOT NULL,
            role TEXT,
            PRIMARY KEY (matter_id, contact_id),
            FOREIGN KEY(matter_id) REFERENCES matters(id),
            FOREIGN KEY(contact_id) REFERENCES contacts(id)
        );

        CREATE TABLE IF NOT EXISTS deadlines (
            id TEXT PRIMARY KEY,
            matter_id TEXT NOT NULL,
            label TEXT,
            due_date TEXT,
            type TEXT,
            alert_before TEXT,
            recurring TEXT,
            status TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(matter_id) REFERENCES matters(id)
        );

        CREATE TABLE IF NOT EXISTS matter_relationships (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            type TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(source_id, target_id, type),
            FOREIGN KEY(source_id) REFERENCES matters(id),
            FOREIGN KEY(target_id) REFERENCES matters(id)
        );
        """
    )

    for old_role, new_role in ROLE_MIGRATION.items():
        conn.execute(
            "UPDATE users SET role = ? WHERE role = ?",
            (new_role, old_role),
        )
