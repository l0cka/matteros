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
            contact_id="c1", matter=matter, linked_contact_ids=["c1"],
        ) is True

    def test_contact_cannot_see_privileged(self):
        matter = _make_matter(privileged=True)
        assert can_access_matter(
            contact_id="c1", matter=matter, linked_contact_ids=["c1"],
        ) is False

    def test_contact_cannot_see_unlinked(self):
        matter = _make_matter(privileged=False)
        assert can_access_matter(
            contact_id="c1", matter=matter, linked_contact_ids=["c2"],
        ) is False

    def test_contact_cannot_see_unlinked_empty(self):
        matter = _make_matter(privileged=False)
        assert can_access_matter(
            contact_id="c1", matter=matter, linked_contact_ids=[],
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
