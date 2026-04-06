"""Tests for AutomationState key-value store."""
from __future__ import annotations
from pathlib import Path
import pytest
from matteros.core.store import SQLiteStore
from matteros.automation.state import AutomationState

@pytest.fixture
def state(tmp_path: Path) -> AutomationState:
    db = SQLiteStore(tmp_path / "test.db")
    return AutomationState(db)

def test_get_returns_none_for_missing(state: AutomationState):
    assert state.get("nonexistent") is None

def test_set_and_get(state: AutomationState):
    state.set("jira_intake:last_poll", "2026-04-05T12:00:00Z")
    assert state.get("jira_intake:last_poll") == "2026-04-05T12:00:00Z"

def test_set_overwrites(state: AutomationState):
    state.set("key", "v1")
    state.set("key", "v2")
    assert state.get("key") == "v2"

def test_has_key(state: AutomationState):
    assert state.has("key") is False
    state.set("key", "val")
    assert state.has("key") is True
