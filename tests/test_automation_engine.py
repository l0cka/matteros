"""Tests for AutomationEngine scheduler."""
from __future__ import annotations
from pathlib import Path
import pytest
from matteros.core.store import SQLiteStore
from matteros.automation.engine import AutomationEngine

@pytest.fixture
def engine(tmp_path: Path) -> AutomationEngine:
    db = SQLiteStore(tmp_path / "test.db")
    return AutomationEngine(db=db, config={
        "jira_intake": {"enabled": False},
        "slack_intake": {"enabled": False},
        "deadline_alerts": {"enabled": False},
        "stale_detection": {"enabled": False},
    })

def test_engine_creates_without_error(engine):
    assert engine is not None

def test_engine_run_once_with_nothing_enabled(engine):
    actions = engine.run_once()
    assert actions == []

def test_engine_run_once_with_deadlines_enabled(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    engine = AutomationEngine(db=db, config={
        "jira_intake": {"enabled": False},
        "slack_intake": {"enabled": False},
        "deadline_alerts": {
            "enabled": True, "check_interval_minutes": 60,
            "alert_windows_days": [7], "slack_channel": None,
        },
        "stale_detection": {"enabled": False},
    })
    actions = engine.run_once()
    assert isinstance(actions, list)

def test_engine_run_once_with_stale_enabled(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    engine = AutomationEngine(db=db, config={
        "jira_intake": {"enabled": False},
        "slack_intake": {"enabled": False},
        "deadline_alerts": {"enabled": False},
        "stale_detection": {
            "enabled": True, "check_interval_minutes": 120,
            "thresholds": {"default": 14}, "slack_channel": None,
        },
    })
    actions = engine.run_once()
    assert isinstance(actions, list)
