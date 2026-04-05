"""Tests for MatterStore CRUD operations."""
from __future__ import annotations

import sqlite3

import pytest

from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore


@pytest.fixture
def store(tmp_path):
    """Create a real SQLiteStore (auto-runs migrations including v005)."""
    db = SQLiteStore(tmp_path / "test.db")
    return MatterStore(db)


# ── TestCreateMatter ─────────────────────────────────────────────────


class TestCreateMatter:
    def test_create_returns_id(self, store):
        mid = store.create_matter(title="Test", type="litigation")
        assert isinstance(mid, str)
        assert len(mid) == 12

    def test_create_with_all_fields(self, store):
        mid = store.create_matter(
            title="Full",
            type="contract",
            priority="high",
            privileged=False,
            source="email",
            source_ref="ref-123",
            metadata={"key": "value"},
            due_date="2026-12-31",
            assignee_id=None,
        )
        matter = store.get_matter(mid)
        assert matter["title"] == "Full"
        assert matter["type"] == "contract"
        assert matter["priority"] == "high"
        assert matter["privileged"] == 0
        assert matter["source"] == "email"
        assert matter["source_ref"] == "ref-123"
        assert matter["metadata_json"] == '{"key": "value"}'
        assert matter["metadata"] == {"key": "value"}
        assert matter["due_date"] == "2026-12-31"

    def test_create_defaults_privileged_true(self, store):
        mid = store.create_matter(title="Priv", type="litigation")
        matter = store.get_matter(mid)
        assert matter["privileged"] == 1

    def test_create_defaults_status_new(self, store):
        mid = store.create_matter(title="New", type="litigation")
        matter = store.get_matter(mid)
        assert matter["status"] == "new"


# ── TestGetMatter ────────────────────────────────────────────────────


class TestGetMatter:
    def test_get_returns_none_for_missing(self, store):
        assert store.get_matter("nonexistent") is None

    def test_get_returns_dict(self, store):
        mid = store.create_matter(title="Get Me", type="litigation")
        matter = store.get_matter(mid)
        assert isinstance(matter, dict)
        assert matter["id"] == mid
        assert matter["title"] == "Get Me"


# ── TestUpdateMatter ─────────────────────────────────────────────────


class TestUpdateMatter:
    def test_update_status(self, store):
        mid = store.create_matter(title="Up", type="litigation")
        store.update_matter(mid, status="active")
        assert store.get_matter(mid)["status"] == "active"

    def test_update_assignee(self, store):
        mid = store.create_matter(title="Assign", type="litigation")
        # assignee_id can be set to None or a user id; None is valid
        store.update_matter(mid, assignee_id=None)
        assert store.get_matter(mid)["assignee_id"] is None

    def test_update_privilege_downgrade(self, store):
        mid = store.create_matter(title="Downgrade", type="litigation")
        assert store.get_matter(mid)["privileged"] == 1
        store.update_matter(mid, privileged=False)
        assert store.get_matter(mid)["privileged"] == 0

    def test_update_nonexistent_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.update_matter("nonexistent", status="active")


# ── TestListMatters ──────────────────────────────────────────────────


class TestListMatters:
    def test_list_empty(self, store):
        assert store.list_matters() == []

    def test_list_returns_all(self, store):
        store.create_matter(title="A", type="litigation")
        store.create_matter(title="B", type="contract")
        results = store.list_matters()
        assert len(results) == 2

    def test_list_filter_by_status(self, store):
        mid = store.create_matter(title="Active", type="litigation")
        store.update_matter(mid, status="active")
        store.create_matter(title="New", type="litigation")
        results = store.list_matters(status="active")
        assert len(results) == 1
        assert results[0]["title"] == "Active"

    def test_list_filter_by_type(self, store):
        store.create_matter(title="Lit", type="litigation")
        store.create_matter(title="Con", type="contract")
        results = store.list_matters(type="contract")
        assert len(results) == 1
        assert results[0]["title"] == "Con"

    def test_list_filter_by_assignee(self, store):
        store.create_matter(title="Unassigned", type="litigation")
        results = store.list_matters(assignee_id="nobody")
        assert len(results) == 0


# ── TestActivities ───────────────────────────────────────────────────


class TestActivities:
    def test_add_activity(self, store):
        mid = store.create_matter(title="Act", type="litigation")
        aid = store.add_activity(matter_id=mid, type="note", content={"text": "hello"})
        assert isinstance(aid, int)

    def test_list_activities(self, store):
        mid = store.create_matter(title="Act", type="litigation")
        store.add_activity(matter_id=mid, type="note", content={"text": "first"})
        store.add_activity(matter_id=mid, type="comment", content={"text": "second"})
        activities = store.list_activities(mid)
        assert len(activities) == 2
        assert activities[0]["type"] == "note"
        assert activities[0]["content"] == {"text": "first"}
        assert activities[1]["type"] == "comment"

    def test_privileged_matter_forces_internal_visibility(self, store):
        mid = store.create_matter(title="Priv", type="litigation", privileged=True)
        aid = store.add_activity(
            matter_id=mid, type="note", visibility="public"
        )
        activities = store.list_activities(mid)
        assert activities[0]["visibility"] == "internal"


# ── TestContacts ─────────────────────────────────────────────────────


class TestContacts:
    def test_create_contact(self, store):
        cid = store.create_contact(name="Alice", email="alice@example.com")
        assert isinstance(cid, str)
        assert len(cid) > 0

    def test_link_contact_to_matter(self, store):
        mid = store.create_matter(title="Link", type="litigation")
        cid = store.create_contact(name="Bob", email="bob@example.com")
        store.link_contact(matter_id=mid, contact_id=cid)
        contacts = store.list_matter_contacts(mid)
        assert len(contacts) == 1
        assert contacts[0]["name"] == "Bob"
        assert contacts[0]["role"] == "requestor"

    def test_duplicate_email_raises(self, store):
        store.create_contact(name="A", email="dup@example.com")
        with pytest.raises(sqlite3.IntegrityError):
            store.create_contact(name="B", email="dup@example.com")


# ── TestDeadlines ────────────────────────────────────────────────────


class TestDeadlines:
    def test_create_deadline(self, store):
        mid = store.create_matter(title="DL", type="litigation")
        did = store.create_deadline(
            matter_id=mid, label="Filing", due_date="2026-06-01"
        )
        assert isinstance(did, int)

    def test_list_deadlines(self, store):
        mid = store.create_matter(title="DL", type="litigation")
        store.create_deadline(matter_id=mid, label="B", due_date="2026-07-01")
        store.create_deadline(matter_id=mid, label="A", due_date="2026-06-01")
        deadlines = store.list_deadlines(mid)
        assert len(deadlines) == 2
        # ordered by due_date ASC
        assert deadlines[0]["label"] == "A"
        assert deadlines[1]["label"] == "B"

    def test_complete_deadline(self, store):
        mid = store.create_matter(title="DL", type="litigation")
        did = store.create_deadline(
            matter_id=mid, label="Filing", due_date="2026-06-01"
        )
        store.complete_deadline(did)
        deadlines = store.list_deadlines(mid)
        assert deadlines[0]["status"] == "completed"

    def test_list_upcoming_deadlines(self, store):
        m1 = store.create_matter(title="M1", type="litigation")
        m2 = store.create_matter(title="M2", type="contract")
        store.create_deadline(matter_id=m1, label="Soon", due_date="2026-05-01")
        store.create_deadline(matter_id=m2, label="Later", due_date="2026-12-01")
        store.create_deadline(matter_id=m1, label="Done", due_date="2026-04-01")
        # complete one to exclude it
        deadlines_all = store.list_deadlines(m1)
        done_id = [d for d in deadlines_all if d["label"] == "Done"][0]["id"]
        store.complete_deadline(done_id)

        upcoming = store.list_upcoming_deadlines(before="2026-06-01")
        assert len(upcoming) == 1
        assert upcoming[0]["label"] == "Soon"
        assert upcoming[0]["matter_title"] == "M1"
        assert upcoming[0]["matter_type"] == "litigation"


# ── TestRelationships ────────────────────────────────────────────────


class TestRelationships:
    def test_add_relationship(self, store):
        m1 = store.create_matter(title="Source", type="litigation")
        m2 = store.create_matter(title="Target", type="contract")
        rid = store.add_relationship(source_id=m1, target_id=m2, type="related")
        assert isinstance(rid, int)

    def test_list_relationships(self, store):
        m1 = store.create_matter(title="A", type="litigation")
        m2 = store.create_matter(title="B", type="contract")
        m3 = store.create_matter(title="C", type="litigation")
        store.add_relationship(source_id=m1, target_id=m2, type="related")
        store.add_relationship(source_id=m3, target_id=m1, type="parent")
        # m1 is source in first, target in second
        rels = store.list_relationships(m1)
        assert len(rels) == 2
