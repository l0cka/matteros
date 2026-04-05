"""Tests for v005 matters migration."""

from __future__ import annotations

import sqlite3

import pytest


def _make_db() -> sqlite3.Connection:
    """Create an in-memory SQLite DB with the users table pre-populated."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            role TEXT,
            password_hash TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
        "VALUES ('u1', 'devuser', 'dev', 'hash1', '2025-01-01', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
        "VALUES ('u2', 'soluser', 'solicitor', 'hash2', '2025-01-01', '2025-01-01')"
    )
    conn.commit()
    return conn


def test_version_and_description():
    from matteros.core.migrations.v005_matters import VERSION, DESCRIPTION

    assert VERSION == 5
    assert isinstance(DESCRIPTION, str)
    assert len(DESCRIPTION) > 0


def test_creates_matters_table():
    from matteros.core.migrations.v005_matters import upgrade

    conn = _make_db()
    upgrade(conn)
    conn.commit()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(matters)").fetchall()}
    expected = {
        "id", "title", "type", "status", "privileged", "assignee_id",
        "priority", "source", "source_ref", "metadata_json",
        "created_at", "updated_at", "due_date", "resolved_at",
    }
    assert expected <= cols


def test_creates_activities_table():
    from matteros.core.migrations.v005_matters import upgrade

    conn = _make_db()
    upgrade(conn)
    conn.commit()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(activities)").fetchall()}
    expected = {
        "id", "matter_id", "actor_id", "type", "visibility",
        "content_json", "created_at",
    }
    assert expected <= cols


def test_creates_contacts_table():
    from matteros.core.migrations.v005_matters import upgrade

    conn = _make_db()
    upgrade(conn)
    conn.commit()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    expected = {"id", "name", "email", "department", "created_at"}
    assert expected <= cols

    # email should be unique — inserting duplicate should fail
    conn.execute(
        "INSERT INTO contacts (id, name, email, created_at) VALUES ('c1', 'A', 'a@b.com', '2025-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contacts (id, name, email, created_at) VALUES ('c2', 'B', 'a@b.com', '2025-01-01')"
        )


def test_creates_matter_contacts_table():
    from matteros.core.migrations.v005_matters import upgrade

    conn = _make_db()
    upgrade(conn)
    conn.commit()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_contacts)").fetchall()}
    expected = {"matter_id", "contact_id", "role"}
    assert expected <= cols

    # Composite PK — inserting duplicate pair should fail
    conn.execute(
        "INSERT INTO matters (id, title, status, created_at, updated_at) "
        "VALUES ('m1', 'Test', 'open', '2025-01-01', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO contacts (id, name, email, created_at) VALUES ('c1', 'A', 'a@b.com', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO matter_contacts (matter_id, contact_id, role) VALUES ('m1', 'c1', 'client')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO matter_contacts (matter_id, contact_id, role) VALUES ('m1', 'c1', 'client')"
        )


def test_creates_deadlines_table():
    from matteros.core.migrations.v005_matters import upgrade

    conn = _make_db()
    upgrade(conn)
    conn.commit()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(deadlines)").fetchall()}
    expected = {
        "id", "matter_id", "label", "due_date", "type",
        "alert_before", "recurring", "status", "created_at",
    }
    assert expected <= cols


def test_creates_matter_relationships_table():
    from matteros.core.migrations.v005_matters import upgrade

    conn = _make_db()
    upgrade(conn)
    conn.commit()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_relationships)").fetchall()}
    expected = {"id", "source_id", "target_id", "type", "created_at"}
    assert expected <= cols

    # UNIQUE constraint on source_id + target_id + type
    conn.execute(
        "INSERT INTO matters (id, title, status, created_at, updated_at) "
        "VALUES ('m1', 'A', 'open', '2025-01-01', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO matters (id, title, status, created_at, updated_at) "
        "VALUES ('m2', 'B', 'open', '2025-01-01', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO matter_relationships (id, source_id, target_id, type, created_at) "
        "VALUES ('r1', 'm1', 'm2', 'related', '2025-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO matter_relationships (id, source_id, target_id, type, created_at) "
            "VALUES ('r2', 'm1', 'm2', 'related', '2025-01-01')"
        )


def test_role_migration():
    from matteros.core.migrations.v005_matters import upgrade, ROLE_MIGRATION

    # Verify the mapping
    assert ROLE_MIGRATION == {
        "dev": "legal",
        "partner_gc": "gc",
        "sr_solicitor": "legal",
        "solicitor": "legal",
        "paralegal": "legal",
    }

    conn = _make_db()
    # Add extra users with other old roles
    conn.execute(
        "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
        "VALUES ('u3', 'pgcuser', 'partner_gc', 'hash3', '2025-01-01', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
        "VALUES ('u4', 'sruser', 'sr_solicitor', 'hash4', '2025-01-01', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
        "VALUES ('u5', 'parauser', 'paralegal', 'hash5', '2025-01-01', '2025-01-01')"
    )
    conn.commit()

    upgrade(conn)
    conn.commit()

    roles = {
        r["username"]: r["role"]
        for r in conn.execute("SELECT username, role FROM users").fetchall()
    }
    assert roles["devuser"] == "legal"
    assert roles["soluser"] == "legal"
    assert roles["pgcuser"] == "gc"
    assert roles["sruser"] == "legal"
    assert roles["parauser"] == "legal"
