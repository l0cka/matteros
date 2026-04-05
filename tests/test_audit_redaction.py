"""Tests for privilege-aware audit redaction."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
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
