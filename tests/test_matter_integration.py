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
    # Note: actor_id omitted because activities.actor_id has FK to users table
    matters.add_activity(
        matter_id=matter_id,
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
