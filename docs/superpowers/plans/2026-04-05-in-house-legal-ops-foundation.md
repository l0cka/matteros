# Legal Ops Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational data layer for the MatterOS legal ops redesign — schema, privilege-aware audit, authorization, and CRUD operations for matters, activities, contacts, and deadlines.

**Architecture:** New SQLite tables via the existing migration runner. A `MatterStore` class provides CRUD. The audit logger gains a privilege-aware redaction path. Authorization moves from global role strings to per-matter evaluation. Old playbook tables are retained but deprecated.

**Tech Stack:** Python 3.12+, SQLite, Pydantic, pytest

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `matteros/core/migrations/v005_matters.py` | Migration: matters, activities, contacts, deadlines, relationships tables + role migration |
| Create | `matteros/matters/store.py` | MatterStore: CRUD for matters, activities, contacts, deadlines, relationships |
| Create | `matteros/matters/__init__.py` | Package init |
| Create | `matteros/matters/auth.py` | Per-matter authorization: can_access, visible_fields, privilege checks |
| Modify | `matteros/core/audit.py` | Add privilege-aware redaction to AuditLogger.append() |
| Modify | `matteros/core/store.py` | Add matter_id column to audit_events (nullable, for backwards compat) |
| Modify | `matteros/team/users.py` | New roles (legal, gc), updated ROLE_PERMISSIONS, keep old roles for migration |
| Create | `tests/test_migration_v005.py` | Tests for v005 migration |
| Create | `tests/test_matter_store.py` | Tests for MatterStore CRUD |
| Create | `tests/test_matter_auth.py` | Tests for per-matter authorization |
| Create | `tests/test_audit_redaction.py` | Tests for privilege-aware audit redaction |

---

### Task 1: Database Migration — Matter Tables

**Files:**
- Create: `matteros/core/migrations/v005_matters.py`
- Create: `tests/test_migration_v005.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_v005.py`:

```python
"""Tests for v005 migration: matter tables and role migration."""
from __future__ import annotations

import sqlite3
import pytest
from matteros.core.migrations.v005_matters import VERSION, DESCRIPTION, upgrade


@pytest.fixture
def conn():
    """In-memory DB with prerequisite tables."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    c.execute(
        "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
        "VALUES ('u1', 'alice', 'dev', 'hash', '2026-01-01', '2026-01-01')"
    )
    c.execute(
        "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
        "VALUES ('u2', 'bob', 'solicitor', 'hash', '2026-01-01', '2026-01-01')"
    )
    c.commit()
    return c


def test_version_and_description():
    assert VERSION == 5
    assert isinstance(DESCRIPTION, str)
    assert len(DESCRIPTION) > 0


def test_creates_matters_table(conn):
    upgrade(conn)
    conn.execute(
        "INSERT INTO matters (id, title, type, status, privileged, created_at, updated_at) "
        "VALUES ('m1', 'Test', 'request', 'new', 1, '2026-01-01', '2026-01-01')"
    )
    row = conn.execute("SELECT * FROM matters WHERE id = 'm1'").fetchone()
    assert row["title"] == "Test"
    assert row["privileged"] == 1
    assert row["status"] == "new"


def test_creates_activities_table(conn):
    upgrade(conn)
    conn.execute(
        "INSERT INTO matters (id, title, type, status, privileged, created_at, updated_at) "
        "VALUES ('m1', 'Test', 'request', 'new', 1, '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO activities (matter_id, actor_id, type, visibility, created_at) "
        "VALUES ('m1', 'u1', 'comment', 'internal', '2026-01-01')"
    )
    row = conn.execute("SELECT * FROM activities WHERE matter_id = 'm1'").fetchone()
    assert row["type"] == "comment"
    assert row["visibility"] == "internal"


def test_creates_contacts_table(conn):
    upgrade(conn)
    conn.execute(
        "INSERT INTO contacts (id, name, email, created_at) "
        "VALUES ('c1', 'Jane', 'jane@corp.com', '2026-01-01')"
    )
    row = conn.execute("SELECT * FROM contacts WHERE id = 'c1'").fetchone()
    assert row["email"] == "jane@corp.com"


def test_creates_matter_contacts_table(conn):
    upgrade(conn)
    conn.execute(
        "INSERT INTO matters (id, title, type, status, privileged, created_at, updated_at) "
        "VALUES ('m1', 'Test', 'request', 'new', 0, '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO contacts (id, name, email, created_at) "
        "VALUES ('c1', 'Jane', 'jane@corp.com', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO matter_contacts (matter_id, contact_id, role) "
        "VALUES ('m1', 'c1', 'requestor')"
    )
    row = conn.execute("SELECT * FROM matter_contacts WHERE matter_id = 'm1'").fetchone()
    assert row["contact_id"] == "c1"
    assert row["role"] == "requestor"


def test_creates_deadlines_table(conn):
    upgrade(conn)
    conn.execute(
        "INSERT INTO matters (id, title, type, status, privileged, created_at, updated_at) "
        "VALUES ('m1', 'Test', 'compliance', 'new', 1, '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO deadlines (matter_id, label, due_date, type, status, created_at) "
        "VALUES ('m1', 'Filing', '2026-06-01', 'hard', 'pending', '2026-01-01')"
    )
    row = conn.execute("SELECT * FROM deadlines WHERE matter_id = 'm1'").fetchone()
    assert row["label"] == "Filing"
    assert row["type"] == "hard"


def test_creates_matter_relationships_table(conn):
    upgrade(conn)
    conn.execute(
        "INSERT INTO matters (id, title, type, status, privileged, created_at, updated_at) "
        "VALUES ('m1', 'Original', 'contract', 'resolved', 0, '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO matters (id, title, type, status, privileged, created_at, updated_at) "
        "VALUES ('m2', 'Renewal', 'contract', 'new', 0, '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO matter_relationships (source_id, target_id, type, created_at) "
        "VALUES ('m2', 'm1', 'renewal_of', '2026-01-01')"
    )
    row = conn.execute("SELECT * FROM matter_relationships WHERE source_id = 'm2'").fetchone()
    assert row["type"] == "renewal_of"


def test_unique_constraint_on_relationships(conn):
    upgrade(conn)
    conn.execute(
        "INSERT INTO matters (id, title, type, status, privileged, created_at, updated_at) "
        "VALUES ('m1', 'A', 'contract', 'new', 0, '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO matters (id, title, type, status, privileged, created_at, updated_at) "
        "VALUES ('m2', 'B', 'contract', 'new', 0, '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO matter_relationships (source_id, target_id, type, created_at) "
        "VALUES ('m1', 'm2', 'blocks', '2026-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO matter_relationships (source_id, target_id, type, created_at) "
            "VALUES ('m1', 'm2', 'blocks', '2026-01-01')"
        )


def test_role_migration(conn):
    upgrade(conn)
    alice = conn.execute("SELECT role FROM users WHERE id = 'u1'").fetchone()
    assert alice["role"] == "legal"
    bob = conn.execute("SELECT role FROM users WHERE id = 'u2'").fetchone()
    assert bob["role"] == "legal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration_v005.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'matteros.core.migrations.v005_matters'`

- [ ] **Step 3: Write the migration**

Create `matteros/core/migrations/v005_matters.py`:

```python
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
    conn.executescript(
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
        );

        CREATE TABLE IF NOT EXISTS activities (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            matter_id       TEXT NOT NULL REFERENCES matters(id),
            actor_id        TEXT REFERENCES users(id),
            type            TEXT NOT NULL,
            visibility      TEXT NOT NULL DEFAULT 'internal',
            content_json    TEXT,
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            email           TEXT NOT NULL UNIQUE,
            department      TEXT,
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS matter_contacts (
            matter_id       TEXT NOT NULL REFERENCES matters(id),
            contact_id      TEXT NOT NULL REFERENCES contacts(id),
            role            TEXT DEFAULT 'requestor',
            PRIMARY KEY (matter_id, contact_id)
        );

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
        );

        CREATE TABLE IF NOT EXISTS matter_relationships (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id       TEXT NOT NULL REFERENCES matters(id),
            target_id       TEXT NOT NULL REFERENCES matters(id),
            type            TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            UNIQUE (source_id, target_id, type)
        );
        """
    )

    for old_role, new_role in ROLE_MIGRATION.items():
        conn.execute(
            "UPDATE users SET role = ? WHERE role = ?",
            (new_role, old_role),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_migration_v005.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/core/migrations/v005_matters.py tests/test_migration_v005.py
git commit -m "feat: add v005 migration for matter management tables"
```

---

### Task 2: Update Roles and Permissions

**Files:**
- Modify: `matteros/team/users.py`
- Create: `tests/test_matter_roles.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_matter_roles.py`:

```python
"""Tests for updated roles and permissions."""
from __future__ import annotations

from matteros.team.users import VALID_ROLES, ROLE_PERMISSIONS


def test_valid_roles_include_legal_and_gc():
    assert "legal" in VALID_ROLES
    assert "gc" in VALID_ROLES


def test_legal_role_permissions():
    perms = ROLE_PERMISSIONS["legal"]
    assert "manage_matters" in perms
    assert "view_matters" in perms
    assert "view_audit" in perms
    assert "manage_deadlines" in perms
    assert "manage_contacts" in perms


def test_gc_role_permissions():
    perms = ROLE_PERMISSIONS["gc"]
    assert "manage_matters" in perms
    assert "view_matters" in perms
    assert "manage_users" in perms
    assert "view_audit" in perms
    assert "view_dashboard" in perms
    assert "manage_deadlines" in perms
    assert "manage_contacts" in perms


def test_gc_has_all_legal_permissions():
    legal = ROLE_PERMISSIONS["legal"]
    gc = ROLE_PERMISSIONS["gc"]
    assert legal.issubset(gc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_matter_roles.py -v`
Expected: FAIL — `"legal" not in VALID_ROLES`

- [ ] **Step 3: Update roles and permissions**

Modify `matteros/team/users.py` — replace `VALID_ROLES` and `ROLE_PERMISSIONS`:

```python
VALID_ROLES = {"legal", "gc"}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "legal": {
        "manage_matters", "view_matters", "view_audit",
        "manage_deadlines", "manage_contacts",
    },
    "gc": {
        "manage_matters", "view_matters", "view_audit",
        "manage_deadlines", "manage_contacts",
        "manage_users", "view_dashboard",
    },
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_matter_roles.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/team/users.py tests/test_matter_roles.py
git commit -m "feat: replace old roles with legal/gc for legal ops model"
```

---

### Task 3: MatterStore — Core CRUD

**Files:**
- Create: `matteros/matters/__init__.py`
- Create: `matteros/matters/store.py`
- Create: `tests/test_matter_store.py`

- [ ] **Step 1: Write the failing tests**

Create `matteros/matters/__init__.py` (empty file).

Create `tests/test_matter_store.py`:

```python
"""Tests for MatterStore CRUD operations."""
from __future__ import annotations

import pytest
from pathlib import Path
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore


@pytest.fixture
def store(tmp_path: Path) -> MatterStore:
    db = SQLiteStore(tmp_path / "test.db")
    return MatterStore(db)


class TestCreateMatter:
    def test_create_returns_id(self, store: MatterStore):
        matter_id = store.create_matter(
            title="NDA Review",
            type="contract",
        )
        assert isinstance(matter_id, str)
        assert len(matter_id) > 0

    def test_create_with_all_fields(self, store: MatterStore):
        matter_id = store.create_matter(
            title="Vendor Agreement",
            type="contract",
            priority="high",
            privileged=False,
            source="jira",
            source_ref="LEG-123",
            metadata={"counterparty": "Acme Corp", "value": 50000},
            due_date="2026-06-01",
        )
        matter = store.get_matter(matter_id)
        assert matter["title"] == "Vendor Agreement"
        assert matter["type"] == "contract"
        assert matter["priority"] == "high"
        assert matter["privileged"] == 0
        assert matter["source"] == "jira"
        assert matter["source_ref"] == "LEG-123"
        assert matter["due_date"] == "2026-06-01"

    def test_create_defaults_privileged_true(self, store: MatterStore):
        matter_id = store.create_matter(title="Sensitive", type="request")
        matter = store.get_matter(matter_id)
        assert matter["privileged"] == 1

    def test_create_defaults_status_new(self, store: MatterStore):
        matter_id = store.create_matter(title="Test", type="request")
        matter = store.get_matter(matter_id)
        assert matter["status"] == "new"


class TestGetMatter:
    def test_get_returns_none_for_missing(self, store: MatterStore):
        assert store.get_matter("nonexistent") is None

    def test_get_returns_dict(self, store: MatterStore):
        matter_id = store.create_matter(title="Test", type="request")
        matter = store.get_matter(matter_id)
        assert isinstance(matter, dict)
        assert matter["id"] == matter_id


class TestUpdateMatter:
    def test_update_status(self, store: MatterStore):
        matter_id = store.create_matter(title="Test", type="request")
        store.update_matter(matter_id, status="in_progress")
        matter = store.get_matter(matter_id)
        assert matter["status"] == "in_progress"

    def test_update_assignee(self, store: MatterStore):
        matter_id = store.create_matter(title="Test", type="request")
        store.update_matter(matter_id, assignee_id="user-1")
        matter = store.get_matter(matter_id)
        assert matter["assignee_id"] == "user-1"

    def test_update_privilege_downgrade(self, store: MatterStore):
        matter_id = store.create_matter(title="Test", type="request", privileged=True)
        store.update_matter(matter_id, privileged=False)
        matter = store.get_matter(matter_id)
        assert matter["privileged"] == 0

    def test_update_nonexistent_raises(self, store: MatterStore):
        with pytest.raises(ValueError, match="not found"):
            store.update_matter("nonexistent", status="resolved")


class TestListMatters:
    def test_list_empty(self, store: MatterStore):
        assert store.list_matters() == []

    def test_list_returns_all(self, store: MatterStore):
        store.create_matter(title="A", type="request")
        store.create_matter(title="B", type="contract")
        assert len(store.list_matters()) == 2

    def test_list_filter_by_status(self, store: MatterStore):
        m1 = store.create_matter(title="A", type="request")
        store.create_matter(title="B", type="request")
        store.update_matter(m1, status="resolved")
        results = store.list_matters(status="new")
        assert len(results) == 1
        assert results[0]["title"] == "B"

    def test_list_filter_by_type(self, store: MatterStore):
        store.create_matter(title="A", type="request")
        store.create_matter(title="B", type="contract")
        results = store.list_matters(type="contract")
        assert len(results) == 1
        assert results[0]["title"] == "B"

    def test_list_filter_by_assignee(self, store: MatterStore):
        m1 = store.create_matter(title="A", type="request")
        store.create_matter(title="B", type="request")
        store.update_matter(m1, assignee_id="user-1")
        results = store.list_matters(assignee_id="user-1")
        assert len(results) == 1
        assert results[0]["title"] == "A"


class TestActivities:
    def test_add_activity(self, store: MatterStore):
        matter_id = store.create_matter(title="Test", type="request")
        activity_id = store.add_activity(
            matter_id=matter_id,
            actor_id="user-1",
            type="comment",
            content={"text": "Reviewing now"},
        )
        assert isinstance(activity_id, int)

    def test_list_activities(self, store: MatterStore):
        matter_id = store.create_matter(title="Test", type="request")
        store.add_activity(matter_id=matter_id, actor_id="u1", type="comment", content={"text": "A"})
        store.add_activity(matter_id=matter_id, actor_id="u1", type="comment", content={"text": "B"})
        activities = store.list_activities(matter_id)
        assert len(activities) == 2

    def test_privileged_matter_forces_internal_visibility(self, store: MatterStore):
        matter_id = store.create_matter(title="Secret", type="request", privileged=True)
        store.add_activity(
            matter_id=matter_id,
            actor_id="u1",
            type="comment",
            content={"text": "test"},
            visibility="external",
        )
        activities = store.list_activities(matter_id)
        assert activities[0]["visibility"] == "internal"


class TestContacts:
    def test_create_contact(self, store: MatterStore):
        contact_id = store.create_contact(name="Jane", email="jane@corp.com")
        assert isinstance(contact_id, str)

    def test_link_contact_to_matter(self, store: MatterStore):
        matter_id = store.create_matter(title="Test", type="request", privileged=False)
        contact_id = store.create_contact(name="Jane", email="jane@corp.com")
        store.link_contact(matter_id=matter_id, contact_id=contact_id, role="requestor")
        contacts = store.list_matter_contacts(matter_id)
        assert len(contacts) == 1
        assert contacts[0]["name"] == "Jane"

    def test_duplicate_email_raises(self, store: MatterStore):
        store.create_contact(name="Jane", email="jane@corp.com")
        with pytest.raises(Exception):
            store.create_contact(name="Jane 2", email="jane@corp.com")


class TestDeadlines:
    def test_create_deadline(self, store: MatterStore):
        matter_id = store.create_matter(title="Filing", type="compliance")
        deadline_id = store.create_deadline(
            matter_id=matter_id,
            label="Annual filing",
            due_date="2026-12-31",
            type="hard",
            alert_before="P30D",
            recurring="P1Y",
        )
        assert isinstance(deadline_id, int)

    def test_list_deadlines(self, store: MatterStore):
        matter_id = store.create_matter(title="Filing", type="compliance")
        store.create_deadline(matter_id=matter_id, label="Q1", due_date="2026-03-31")
        store.create_deadline(matter_id=matter_id, label="Q2", due_date="2026-06-30")
        deadlines = store.list_deadlines(matter_id)
        assert len(deadlines) == 2

    def test_complete_deadline(self, store: MatterStore):
        matter_id = store.create_matter(title="Filing", type="compliance")
        deadline_id = store.create_deadline(matter_id=matter_id, label="Q1", due_date="2026-03-31")
        store.complete_deadline(deadline_id)
        deadlines = store.list_deadlines(matter_id)
        assert deadlines[0]["status"] == "completed"

    def test_list_upcoming_deadlines(self, store: MatterStore):
        m1 = store.create_matter(title="A", type="compliance")
        m2 = store.create_matter(title="B", type="compliance")
        store.create_deadline(matter_id=m1, label="Soon", due_date="2026-04-10")
        store.create_deadline(matter_id=m2, label="Later", due_date="2026-12-31")
        upcoming = store.list_upcoming_deadlines(before="2026-05-01")
        assert len(upcoming) == 1
        assert upcoming[0]["label"] == "Soon"


class TestRelationships:
    def test_add_relationship(self, store: MatterStore):
        m1 = store.create_matter(title="Original", type="contract")
        m2 = store.create_matter(title="Renewal", type="contract")
        rel_id = store.add_relationship(source_id=m2, target_id=m1, type="renewal_of")
        assert isinstance(rel_id, int)

    def test_list_relationships(self, store: MatterStore):
        m1 = store.create_matter(title="Original", type="contract")
        m2 = store.create_matter(title="Renewal", type="contract")
        store.add_relationship(source_id=m2, target_id=m1, type="renewal_of")
        rels = store.list_relationships(m2)
        assert len(rels) == 1
        assert rels[0]["target_id"] == m1
        assert rels[0]["type"] == "renewal_of"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_matter_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'matteros.matters'`

- [ ] **Step 3: Write MatterStore implementation**

Create `matteros/matters/__init__.py` (empty file).

Create `matteros/matters/store.py`:

```python
"""MatterStore — CRUD for matters, activities, contacts, deadlines, relationships."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from matteros.core.store import SQLiteStore


class MatterStore:
    def __init__(self, db: SQLiteStore) -> None:
        self._db = db

    # ---------- Matters ----------

    def create_matter(
        self,
        *,
        title: str,
        type: str,
        priority: str = "medium",
        privileged: bool = True,
        source: str | None = None,
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        due_date: str | None = None,
        assignee_id: str | None = None,
    ) -> str:
        matter_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO matters (id, title, type, status, assignee_id, priority,
                    privileged, source, source_ref, metadata_json, created_at, updated_at, due_date)
                VALUES (?, ?, ?, 'new', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    matter_id, title, type, assignee_id, priority,
                    int(privileged), source, source_ref,
                    json.dumps(metadata) if metadata else None,
                    now, now, due_date,
                ),
            )
            conn.commit()
        return matter_id

    def get_matter(self, matter_id: str) -> dict[str, Any] | None:
        with self._db.connection() as conn:
            row = conn.execute("SELECT * FROM matters WHERE id = ?", (matter_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            if result.get("metadata_json"):
                result["metadata"] = json.loads(result["metadata_json"])
            return result

    def update_matter(self, matter_id: str, **fields: Any) -> None:
        allowed = {"title", "type", "status", "assignee_id", "priority", "privileged",
                    "due_date", "metadata", "resolved_at"}
        updates = {}
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"cannot update field: {key}")
            if key == "metadata":
                updates["metadata_json"] = json.dumps(value) if value else None
            elif key == "privileged":
                updates["privileged"] = int(value)
            else:
                updates[key] = value

        if not updates:
            return

        updates["updated_at"] = datetime.now(UTC).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [matter_id]

        with self._db.connection() as conn:
            cursor = conn.execute(
                f"UPDATE matters SET {set_clause} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError(f"matter not found: {matter_id}")
            conn.commit()

    def list_matters(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        assignee_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if type:
            conditions.append("type = ?")
            params.append(type)
        if assignee_id:
            conditions.append("assignee_id = ?")
            params.append(assignee_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        with self._db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM matters {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- Activities ----------

    def add_activity(
        self,
        *,
        matter_id: str,
        actor_id: str | None = None,
        type: str,
        content: dict[str, Any] | None = None,
        visibility: str = "internal",
    ) -> int:
        matter = self.get_matter(matter_id)
        if matter and matter["privileged"]:
            visibility = "internal"

        now = datetime.now(UTC).isoformat()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO activities (matter_id, actor_id, type, visibility, content_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    matter_id, actor_id, type, visibility,
                    json.dumps(content) if content else None,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_activities(self, matter_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM activities WHERE matter_id = ? ORDER BY created_at ASC",
                (matter_id,),
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if d.get("content_json"):
                    d["content"] = json.loads(d["content_json"])
                results.append(d)
            return results

    # ---------- Contacts ----------

    def create_contact(
        self,
        *,
        name: str,
        email: str,
        department: str | None = None,
    ) -> str:
        contact_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO contacts (id, name, email, department, created_at) VALUES (?, ?, ?, ?, ?)",
                (contact_id, name, email, department, now),
            )
            conn.commit()
        return contact_id

    def link_contact(
        self,
        *,
        matter_id: str,
        contact_id: str,
        role: str = "requestor",
    ) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO matter_contacts (matter_id, contact_id, role) VALUES (?, ?, ?)",
                (matter_id, contact_id, role),
            )
            conn.commit()

    def list_matter_contacts(self, matter_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.*, mc.role
                FROM contacts c
                JOIN matter_contacts mc ON mc.contact_id = c.id
                WHERE mc.matter_id = ?
                """,
                (matter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- Deadlines ----------

    def create_deadline(
        self,
        *,
        matter_id: str,
        label: str,
        due_date: str,
        type: str = "hard",
        alert_before: str | None = None,
        recurring: str | None = None,
    ) -> int:
        now = datetime.now(UTC).isoformat()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO deadlines (matter_id, label, due_date, type, alert_before, recurring, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (matter_id, label, due_date, type, alert_before, recurring, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_deadlines(self, matter_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM deadlines WHERE matter_id = ? ORDER BY due_date ASC",
                (matter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def complete_deadline(self, deadline_id: int) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE deadlines SET status = 'completed' WHERE id = ?",
                (deadline_id,),
            )
            conn.commit()

    def list_upcoming_deadlines(self, *, before: str, status: str = "pending") -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT d.*, m.title as matter_title, m.type as matter_type
                FROM deadlines d
                JOIN matters m ON m.id = d.matter_id
                WHERE d.status = ? AND d.due_date <= ?
                ORDER BY d.due_date ASC
                """,
                (status, before),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- Relationships ----------

    def add_relationship(
        self,
        *,
        source_id: str,
        target_id: str,
        type: str,
    ) -> int:
        now = datetime.now(UTC).isoformat()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO matter_relationships (source_id, target_id, type, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (source_id, target_id, type, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_relationships(self, matter_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM matter_relationships
                WHERE source_id = ? OR target_id = ?
                ORDER BY created_at ASC
                """,
                (matter_id, matter_id),
            ).fetchall()
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_matter_store.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/matters/__init__.py matteros/matters/store.py tests/test_matter_store.py
git commit -m "feat: add MatterStore with CRUD for matters, activities, contacts, deadlines"
```

---

### Task 4: Privilege-Aware Audit Logger

**Files:**
- Modify: `matteros/core/audit.py`
- Create: `tests/test_audit_redaction.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audit_redaction.py`:

```python
"""Tests for privilege-aware audit redaction."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from matteros.core.store import SQLiteStore
from matteros.core.audit import AuditLogger


@pytest.fixture
def audit(tmp_path: Path) -> AuditLogger:
    store = SQLiteStore(tmp_path / "test.db")
    return AuditLogger(store, tmp_path / "audit.jsonl")


def test_non_privileged_logs_full_data(audit: AuditLogger):
    event = audit.append(
        run_id="r1",
        event_type="matter.updated",
        actor="user-1",
        step_id=None,
        data={"matter_id": "m1", "old_status": "new", "new_status": "in_progress",
              "comment": "Starting review of NDA with Acme Corp"},
        privileged=False,
    )
    assert "comment" in event["data"]
    assert event["data"]["comment"] == "Starting review of NDA with Acme Corp"


def test_privileged_redacts_sensitive_fields(audit: AuditLogger):
    event = audit.append(
        run_id="r1",
        event_type="matter.updated",
        actor="user-1",
        step_id=None,
        data={"matter_id": "m1", "old_status": "new", "new_status": "in_progress",
              "comment": "Privileged discussion about litigation strategy"},
        privileged=True,
    )
    assert "comment" not in event["data"]
    assert event["data"]["matter_id"] == "m1"
    assert event["data"]["event_type"] == "matter.updated"


def test_privileged_keeps_safe_metadata(audit: AuditLogger):
    event = audit.append(
        run_id="r1",
        event_type="matter.status_changed",
        actor="user-1",
        step_id=None,
        data={"matter_id": "m1", "old_status": "new", "new_status": "in_progress",
              "old_assignee": None, "new_assignee": "user-2"},
        privileged=True,
    )
    assert event["data"]["matter_id"] == "m1"
    assert event["data"]["old_status"] == "new"
    assert event["data"]["new_status"] == "in_progress"


def test_privileged_access_event(audit: AuditLogger):
    event = audit.append(
        run_id="r1",
        event_type="privileged_access",
        actor="user-1",
        step_id=None,
        data={"matter_id": "m1", "action": "viewed"},
        privileged=True,
    )
    assert event["data"]["matter_id"] == "m1"
    assert event["data"]["action"] == "viewed"


def test_privileged_redaction_in_jsonl(audit: AuditLogger, tmp_path: Path):
    audit.append(
        run_id="r1",
        event_type="matter.updated",
        actor="user-1",
        step_id=None,
        data={"matter_id": "m1", "comment": "Secret stuff"},
        privileged=True,
    )
    jsonl_content = (tmp_path / "audit.jsonl").read_text()
    assert "Secret stuff" not in jsonl_content
    assert "m1" in jsonl_content


def test_backwards_compat_no_privileged_flag(audit: AuditLogger):
    """Existing callers that don't pass privileged= should still work."""
    event = audit.append(
        run_id="r1",
        event_type="run.started",
        actor="system",
        step_id=None,
        data={"playbook": "test", "dry_run": True},
    )
    assert event["data"]["playbook"] == "test"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_audit_redaction.py -v`
Expected: FAIL — `TypeError: append() got an unexpected keyword argument 'privileged'`

- [ ] **Step 3: Update AuditLogger with redaction**

Modify `matteros/core/audit.py` — update the `append` method signature and add redaction logic:

Add these constants after the imports:

```python
# Fields that are safe to log even for privileged matters.
_SAFE_FIELDS = {
    "matter_id", "event_type", "action",
    "old_status", "new_status",
    "old_assignee", "new_assignee",
    "deadline_id", "due_date",
    "accessor_id",
}
```

Update the `append` method signature to add `privileged: bool = False` parameter. Add redaction logic before serializing:

```python
def append(
    self,
    *,
    run_id: str,
    event_type: str,
    actor: str,
    step_id: str | None,
    data: dict[str, Any],
    privileged: bool = False,
) -> dict[str, Any]:
    if privileged:
        data = self._redact(data, event_type)

    timestamp = datetime.now(UTC).isoformat()
    # ... rest of method unchanged ...
```

Add the `_redact` method:

```python
def _redact(self, data: dict[str, Any], event_type: str) -> dict[str, Any]:
    """Strip sensitive fields from data, keeping only safe metadata."""
    redacted = {"event_type": event_type}
    for key, value in data.items():
        if key in _SAFE_FIELDS:
            redacted[key] = value
    return redacted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_audit_redaction.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Run existing audit tests to verify no regression**

Run: `pytest tests/test_audit_verify.py tests/test_audit_verify_core.py -v`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/core/audit.py tests/test_audit_redaction.py
git commit -m "feat: add privilege-aware redaction to audit logger"
```

---

### Task 5: Per-Matter Authorization

**Files:**
- Create: `matteros/matters/auth.py`
- Create: `tests/test_matter_auth.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_matter_auth.py`:

```python
"""Tests for per-matter authorization."""
from __future__ import annotations

import pytest
from matteros.matters.auth import can_access_matter, visible_matter_fields


def _make_matter(*, privileged: bool = False, **overrides) -> dict:
    base = {
        "id": "m1",
        "title": "Test Matter",
        "type": "request",
        "status": "new",
        "priority": "medium",
        "privileged": int(privileged),
        "assignee_id": None,
        "due_date": "2026-06-01",
        "metadata_json": None,
    }
    base.update(overrides)
    return base


def _make_user(role: str = "legal") -> dict:
    return {"id": "u1", "role": role}


class TestCanAccessMatter:
    def test_legal_can_access_any_matter(self):
        matter = _make_matter(privileged=True)
        user = _make_user("legal")
        assert can_access_matter(user=user, matter=matter) is True

    def test_gc_can_access_any_matter(self):
        matter = _make_matter(privileged=True)
        user = _make_user("gc")
        assert can_access_matter(user=user, matter=matter) is True

    def test_legal_can_access_non_privileged(self):
        matter = _make_matter(privileged=False)
        user = _make_user("legal")
        assert can_access_matter(user=user, matter=matter) is True


class TestContactAccess:
    def test_contact_can_see_linked_non_privileged(self):
        matter = _make_matter(privileged=False)
        assert can_access_matter(
            contact_id="c1",
            matter=matter,
            linked_contact_ids=["c1"],
        ) is True

    def test_contact_cannot_see_privileged(self):
        matter = _make_matter(privileged=True)
        assert can_access_matter(
            contact_id="c1",
            matter=matter,
            linked_contact_ids=["c1"],
        ) is False

    def test_contact_cannot_see_unlinked(self):
        matter = _make_matter(privileged=False)
        assert can_access_matter(
            contact_id="c1",
            matter=matter,
            linked_contact_ids=["c2"],
        ) is False

    def test_contact_cannot_see_unlinked_empty(self):
        matter = _make_matter(privileged=False)
        assert can_access_matter(
            contact_id="c1",
            matter=matter,
            linked_contact_ids=[],
        ) is False


class TestVisibleFields:
    def test_legal_sees_all_fields(self):
        matter = _make_matter()
        user = _make_user("legal")
        result = visible_matter_fields(user=user, matter=matter)
        assert result == matter

    def test_contact_sees_only_safe_fields(self):
        matter = _make_matter(privileged=False)
        result = visible_matter_fields(contact_id="c1", matter=matter)
        assert set(result.keys()) == {"id", "title", "status", "due_date", "priority"}
        assert "metadata_json" not in result
        assert "assignee_id" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_matter_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'matteros.matters.auth'`

- [ ] **Step 3: Write authorization module**

Create `matteros/matters/auth.py`:

```python
"""Per-matter authorization for the legal ops model."""
from __future__ import annotations

from typing import Any

# Fields visible to contacts (business stakeholders) via Jira sync or future API.
_CONTACT_VISIBLE_FIELDS = {"id", "title", "status", "due_date", "priority"}


def can_access_matter(
    *,
    user: dict[str, Any] | None = None,
    contact_id: str | None = None,
    matter: dict[str, Any],
    linked_contact_ids: list[str] | None = None,
) -> bool:
    """Check whether a user or contact can access a matter.

    Legal/GC users can access all matters.
    Contacts can only access non-privileged matters they are linked to.
    """
    if user is not None:
        role = user.get("role", "")
        if role in ("legal", "gc"):
            return True
        return False

    if contact_id is not None:
        if matter.get("privileged", 1):
            return False
        if linked_contact_ids is None:
            return False
        return contact_id in linked_contact_ids

    return False


def visible_matter_fields(
    *,
    user: dict[str, Any] | None = None,
    contact_id: str | None = None,
    matter: dict[str, Any],
) -> dict[str, Any]:
    """Return the matter dict filtered to only the fields the caller can see.

    Legal/GC users see all fields.
    Contacts see only title, status, due_date, priority.
    """
    if user is not None:
        role = user.get("role", "")
        if role in ("legal", "gc"):
            return matter

    return {k: v for k, v in matter.items() if k in _CONTACT_VISIBLE_FIELDS}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_matter_auth.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/matters/auth.py tests/test_matter_auth.py
git commit -m "feat: add per-matter authorization with privilege and contact scoping"
```

---

### Task 6: Integration Test — Full Stack

**Files:**
- Create: `tests/test_matter_integration.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_matter_integration.py`:

```python
"""Integration test: create matter, add activity, check privilege, verify audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from matteros.core.store import SQLiteStore
from matteros.core.audit import AuditLogger
from matteros.matters.store import MatterStore
from matteros.matters.auth import can_access_matter, visible_matter_fields


@pytest.fixture
def env(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    audit = AuditLogger(db, tmp_path / "audit.jsonl")
    matters = MatterStore(db)
    return {"db": db, "audit": audit, "matters": matters, "tmp": tmp_path}


def test_full_privileged_matter_lifecycle(env):
    matters = env["matters"]
    audit = env["audit"]

    # Create privileged matter
    matter_id = matters.create_matter(
        title="Litigation Hold - Project Alpha",
        type="compliance",
        privileged=True,
        priority="urgent",
    )

    # Add activity with sensitive content
    matters.add_activity(
        matter_id=matter_id,
        actor_id="user-1",
        type="comment",
        content={"text": "Board approved litigation strategy"},
        visibility="external",  # Should be forced to internal
    )

    # Verify activity forced to internal
    activities = matters.list_activities(matter_id)
    assert activities[0]["visibility"] == "internal"

    # Audit the access — privileged redaction
    event = audit.append(
        run_id=matter_id,
        event_type="matter.updated",
        actor="user-1",
        step_id=None,
        data={"matter_id": matter_id, "comment": "Board approved litigation strategy"},
        privileged=True,
    )
    assert "comment" not in event["data"]

    # Verify JSONL doesn't contain sensitive content
    jsonl = (env["tmp"] / "audit.jsonl").read_text()
    assert "Board approved litigation strategy" not in jsonl

    # Contact cannot see privileged matter
    matter = matters.get_matter(matter_id)
    assert can_access_matter(contact_id="c1", matter=matter, linked_contact_ids=["c1"]) is False

    # Legal user can see everything
    user = {"id": "u1", "role": "legal"}
    assert can_access_matter(user=user, matter=matter) is True
    fields = visible_matter_fields(user=user, matter=matter)
    assert "assignee_id" in fields


def test_full_non_privileged_request_lifecycle(env):
    matters = env["matters"]
    audit = env["audit"]

    # Create non-privileged request from Jira
    matter_id = matters.create_matter(
        title="Review marketing materials",
        type="request",
        privileged=False,
        source="jira",
        source_ref="LEG-456",
    )

    # Add contact
    contact_id = matters.create_contact(name="Marketing Lead", email="mkt@corp.com", department="Marketing")
    matters.link_contact(matter_id=matter_id, contact_id=contact_id, role="requestor")

    # Add deadline
    matters.create_deadline(matter_id=matter_id, label="Review due", due_date="2026-04-15", type="hard")

    # Contact can see this matter
    matter = matters.get_matter(matter_id)
    assert can_access_matter(
        contact_id=contact_id, matter=matter, linked_contact_ids=[contact_id]
    ) is True

    # Contact sees limited fields
    fields = visible_matter_fields(contact_id=contact_id, matter=matter)
    assert "title" in fields
    assert "status" in fields
    assert "metadata_json" not in fields

    # Audit logs full data for non-privileged
    event = audit.append(
        run_id=matter_id,
        event_type="matter.created",
        actor="system",
        step_id=None,
        data={"matter_id": matter_id, "source": "jira", "source_ref": "LEG-456"},
        privileged=False,
    )
    assert event["data"]["source_ref"] == "LEG-456"
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_matter_integration.py -v`
Expected: All 2 tests PASS

- [ ] **Step 3: Run full test suite to check for regressions**

Run: `pytest tests/ -v --ignore=tests/cassettes`
Expected: All tests PASS (some existing tests may need the new roles — note any failures)

- [ ] **Step 4: Commit**

```bash
git add tests/test_matter_integration.py
git commit -m "test: add integration tests for matter lifecycle with privilege and auth"
```

---

## Summary

After completing all 6 tasks, the foundation is in place:

- **v005 migration** creates all matter tables
- **Roles** simplified to `legal`/`gc`
- **MatterStore** provides full CRUD for matters, activities, contacts, deadlines, relationships
- **AuditLogger** redacts privileged content at write time
- **Authorization** evaluates access per-matter with contact scoping
- **Integration tests** verify the full stack works together

**Next plan (layers 5-7):** Web UI views, automation engine, and Jira sync — to be planned after this foundation lands and is reviewed.
