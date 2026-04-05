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


def _upgraded_db() -> sqlite3.Connection:
    """Return a db with the v005 migration already applied."""
    from matteros.core.migrations.v005_matters import upgrade

    conn = _make_db()
    upgrade(conn)
    conn.commit()
    return conn


def _insert_matter(conn, **overrides):
    """Insert a matter with sensible defaults, allowing overrides."""
    defaults = {
        "id": "m1",
        "title": "Test",
        "type": "litigation",
        "status": "new",
        "created_at": "2025-01-01",
        "updated_at": "2025-01-01",
    }
    defaults.update(overrides)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    conn.execute(
        f"INSERT INTO matters ({cols}) VALUES ({placeholders})",
        list(defaults.values()),
    )


# ---------- Module-level ----------


def test_version_and_description():
    from matteros.core.migrations.v005_matters import VERSION, DESCRIPTION

    assert VERSION == 5
    assert isinstance(DESCRIPTION, str)
    assert len(DESCRIPTION) > 0


# ---------- matters table ----------


def test_creates_matters_table():
    conn = _upgraded_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matters)").fetchall()}
    expected = {
        "id", "title", "type", "status", "privileged", "assignee_id",
        "priority", "source", "source_ref", "metadata_json",
        "created_at", "updated_at", "due_date", "resolved_at",
    }
    assert expected <= cols


def test_matter_type_not_null():
    """Inserting a matter without type must fail (NOT NULL)."""
    conn = _upgraded_db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO matters (id, title, created_at, updated_at) "
            "VALUES ('m1', 'No Type', '2025-01-01', '2025-01-01')"
        )


def test_matter_default_status_is_new():
    """Default status should be 'new' when not specified."""
    conn = _upgraded_db()
    conn.execute(
        "INSERT INTO matters (id, title, type, created_at, updated_at) "
        "VALUES ('m1', 'Test', 'litigation', '2025-01-01', '2025-01-01')"
    )
    row = conn.execute("SELECT status FROM matters WHERE id = 'm1'").fetchone()
    assert row["status"] == "new"


def test_matter_default_privileged_is_1():
    """Default privileged should be 1 (privilege-first)."""
    conn = _upgraded_db()
    conn.execute(
        "INSERT INTO matters (id, title, type, created_at, updated_at) "
        "VALUES ('m1', 'Test', 'litigation', '2025-01-01', '2025-01-01')"
    )
    row = conn.execute("SELECT privileged FROM matters WHERE id = 'm1'").fetchone()
    assert row["privileged"] == 1


def test_matter_default_priority_is_medium():
    """Default priority should be 'medium'."""
    conn = _upgraded_db()
    conn.execute(
        "INSERT INTO matters (id, title, type, created_at, updated_at) "
        "VALUES ('m1', 'Test', 'litigation', '2025-01-01', '2025-01-01')"
    )
    row = conn.execute("SELECT priority FROM matters WHERE id = 'm1'").fetchone()
    assert row["priority"] == "medium"


def test_matter_assignee_id_fk_to_users():
    """assignee_id must reference users(id) — invalid FK should fail."""
    conn = _upgraded_db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO matters (id, title, type, assignee_id, created_at, updated_at) "
            "VALUES ('m1', 'Test', 'litigation', 'nonexistent_user', '2025-01-01', '2025-01-01')"
        )


# ---------- activities table ----------


def test_creates_activities_table():
    conn = _upgraded_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(activities)").fetchall()}
    expected = {
        "id", "matter_id", "actor_id", "type", "visibility",
        "content_json", "created_at",
    }
    assert expected <= cols


def test_activities_id_is_integer_autoincrement():
    """activities.id must be INTEGER PRIMARY KEY AUTOINCREMENT."""
    conn = _upgraded_db()
    _insert_matter(conn)
    conn.execute(
        "INSERT INTO activities (matter_id, type, created_at) "
        "VALUES ('m1', 'note', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO activities (matter_id, type, created_at) "
        "VALUES ('m1', 'comment', '2025-01-02')"
    )
    rows = conn.execute("SELECT id FROM activities ORDER BY id").fetchall()
    assert rows[0]["id"] == 1
    assert rows[1]["id"] == 2


def test_activities_type_not_null():
    """activities.type must be NOT NULL."""
    conn = _upgraded_db()
    _insert_matter(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO activities (matter_id, created_at) "
            "VALUES ('m1', '2025-01-01')"
        )


def test_activities_default_visibility_is_internal():
    """Default visibility on activities should be 'internal'."""
    conn = _upgraded_db()
    _insert_matter(conn)
    conn.execute(
        "INSERT INTO activities (matter_id, type, created_at) "
        "VALUES ('m1', 'note', '2025-01-01')"
    )
    row = conn.execute("SELECT visibility FROM activities WHERE matter_id = 'm1'").fetchone()
    assert row["visibility"] == "internal"


def test_activities_actor_id_fk_to_users():
    """actor_id must reference users(id) — invalid FK should fail."""
    conn = _upgraded_db()
    _insert_matter(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO activities (matter_id, actor_id, type, created_at) "
            "VALUES ('m1', 'nonexistent_user', 'note', '2025-01-01')"
        )


# ---------- contacts table ----------


def test_creates_contacts_table():
    conn = _upgraded_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    expected = {"id", "name", "email", "department", "created_at"}
    assert expected <= cols


def test_contacts_email_not_null():
    """contacts.email must be NOT NULL."""
    conn = _upgraded_db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contacts (id, name, created_at) "
            "VALUES ('c1', 'No Email', '2025-01-01')"
        )


def test_contacts_email_unique():
    """contacts.email must be UNIQUE — duplicate should fail."""
    conn = _upgraded_db()
    conn.execute(
        "INSERT INTO contacts (id, name, email, created_at) VALUES ('c1', 'A', 'a@b.com', '2025-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contacts (id, name, email, created_at) VALUES ('c2', 'B', 'a@b.com', '2025-01-01')"
        )


# ---------- matter_contacts table ----------


def test_creates_matter_contacts_table():
    conn = _upgraded_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_contacts)").fetchall()}
    expected = {"matter_id", "contact_id", "role"}
    assert expected <= cols


def test_matter_contacts_composite_pk():
    """Composite PK — inserting duplicate pair should fail."""
    conn = _upgraded_db()
    _insert_matter(conn)
    conn.execute(
        "INSERT INTO contacts (id, name, email, created_at) VALUES ('c1', 'A', 'a@b.com', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO matter_contacts (matter_id, contact_id) VALUES ('m1', 'c1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO matter_contacts (matter_id, contact_id) VALUES ('m1', 'c1')"
        )


def test_matter_contacts_default_role_is_requestor():
    """Default role should be 'requestor'."""
    conn = _upgraded_db()
    _insert_matter(conn)
    conn.execute(
        "INSERT INTO contacts (id, name, email, created_at) VALUES ('c1', 'A', 'a@b.com', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO matter_contacts (matter_id, contact_id) VALUES ('m1', 'c1')"
    )
    row = conn.execute("SELECT role FROM matter_contacts WHERE matter_id = 'm1'").fetchone()
    assert row["role"] == "requestor"


# ---------- deadlines table ----------


def test_creates_deadlines_table():
    conn = _upgraded_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(deadlines)").fetchall()}
    expected = {
        "id", "matter_id", "label", "due_date", "type",
        "alert_before", "recurring", "status", "created_at",
    }
    assert expected <= cols


def test_deadlines_id_is_integer_autoincrement():
    """deadlines.id must be INTEGER PRIMARY KEY AUTOINCREMENT."""
    conn = _upgraded_db()
    _insert_matter(conn)
    conn.execute(
        "INSERT INTO deadlines (matter_id, label, due_date, created_at) "
        "VALUES ('m1', 'Filing', '2025-06-01', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO deadlines (matter_id, label, due_date, created_at) "
        "VALUES ('m1', 'Hearing', '2025-07-01', '2025-01-02')"
    )
    rows = conn.execute("SELECT id FROM deadlines ORDER BY id").fetchall()
    assert rows[0]["id"] == 1
    assert rows[1]["id"] == 2


def test_deadlines_label_not_null():
    """deadlines.label must be NOT NULL."""
    conn = _upgraded_db()
    _insert_matter(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO deadlines (matter_id, due_date, created_at) "
            "VALUES ('m1', '2025-06-01', '2025-01-01')"
        )


def test_deadlines_due_date_not_null():
    """deadlines.due_date must be NOT NULL."""
    conn = _upgraded_db()
    _insert_matter(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO deadlines (matter_id, label, created_at) "
            "VALUES ('m1', 'Filing', '2025-01-01')"
        )


def test_deadlines_default_type_is_hard():
    """Default deadline type should be 'hard'."""
    conn = _upgraded_db()
    _insert_matter(conn)
    conn.execute(
        "INSERT INTO deadlines (matter_id, label, due_date, created_at) "
        "VALUES ('m1', 'Filing', '2025-06-01', '2025-01-01')"
    )
    row = conn.execute("SELECT type FROM deadlines WHERE matter_id = 'm1'").fetchone()
    assert row["type"] == "hard"


def test_deadlines_default_status_is_pending():
    """Default deadline status should be 'pending'."""
    conn = _upgraded_db()
    _insert_matter(conn)
    conn.execute(
        "INSERT INTO deadlines (matter_id, label, due_date, created_at) "
        "VALUES ('m1', 'Filing', '2025-06-01', '2025-01-01')"
    )
    row = conn.execute("SELECT status FROM deadlines WHERE matter_id = 'm1'").fetchone()
    assert row["status"] == "pending"


# ---------- matter_relationships table ----------


def test_creates_matter_relationships_table():
    conn = _upgraded_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_relationships)").fetchall()}
    expected = {"id", "source_id", "target_id", "type", "created_at"}
    assert expected <= cols


def test_matter_relationships_id_is_integer_autoincrement():
    """matter_relationships.id must be INTEGER PRIMARY KEY AUTOINCREMENT."""
    conn = _upgraded_db()
    _insert_matter(conn, id="m1")
    _insert_matter(conn, id="m2", title="Other")
    conn.execute(
        "INSERT INTO matter_relationships (source_id, target_id, type, created_at) "
        "VALUES ('m1', 'm2', 'related', '2025-01-01')"
    )
    row = conn.execute("SELECT id FROM matter_relationships").fetchone()
    assert row["id"] == 1


def test_matter_relationships_type_not_null():
    """matter_relationships.type must be NOT NULL."""
    conn = _upgraded_db()
    _insert_matter(conn, id="m1")
    _insert_matter(conn, id="m2", title="Other")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO matter_relationships (source_id, target_id, created_at) "
            "VALUES ('m1', 'm2', '2025-01-01')"
        )


def test_matter_relationships_unique_constraint():
    """UNIQUE constraint on (source_id, target_id, type)."""
    conn = _upgraded_db()
    _insert_matter(conn, id="m1")
    _insert_matter(conn, id="m2", title="Other")
    conn.execute(
        "INSERT INTO matter_relationships (source_id, target_id, type, created_at) "
        "VALUES ('m1', 'm2', 'related', '2025-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO matter_relationships (source_id, target_id, type, created_at) "
            "VALUES ('m1', 'm2', 'related', '2025-01-02')"
        )


# ---------- role migration ----------


def test_role_migration():
    from matteros.core.migrations.v005_matters import upgrade, ROLE_MIGRATION

    assert ROLE_MIGRATION == {
        "dev": "legal",
        "partner_gc": "gc",
        "sr_solicitor": "legal",
        "solicitor": "legal",
        "paralegal": "legal",
    }

    conn = _make_db()
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
