"""Tests for the deadline checker automation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from matteros.automation.deadlines import check_deadlines
from matteros.automation.state import AutomationState
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore


@pytest.fixture
def env(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    ms = MatterStore(db)
    state = AutomationState(db)
    return {"db": db, "ms": ms, "state": state}


def _past_date(days: int = 2) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")


def _future_date(days: int = 5) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")


class TestDeadlineChecker:
    def test_marks_overdue_deadline_as_missed(self, env):
        ms, state = env["ms"], env["state"]
        mid = ms.create_matter(title="NDA Review", type="contract")
        dl_id = ms.create_deadline(matter_id=mid, label="Filing", due_date=_past_date())

        check_deadlines(ms=ms, state=state, alert_windows_days=[7])

        deadlines = ms.list_deadlines(mid)
        assert deadlines[0]["status"] == "missed"

    def test_adds_activity_for_missed_deadline(self, env):
        ms, state = env["ms"], env["state"]
        mid = ms.create_matter(title="NDA Review", type="contract")
        ms.create_deadline(matter_id=mid, label="Filing", due_date=_past_date())

        check_deadlines(ms=ms, state=state, alert_windows_days=[7])

        activities = ms.list_activities(mid)
        assert len(activities) == 1
        assert "missed" in activities[0]["content"]["text"].lower()

    def test_alerts_for_approaching_deadline(self, env):
        ms, state = env["ms"], env["state"]
        mid = ms.create_matter(title="NDA Review", type="contract")
        ms.create_deadline(matter_id=mid, label="Filing", due_date=_future_date(5))

        actions = check_deadlines(ms=ms, state=state, alert_windows_days=[7])

        assert len(actions) == 1
        activities = ms.list_activities(mid)
        assert len(activities) == 1
        assert "approaching" in activities[0]["content"]["text"].lower()

    def test_dedup_prevents_repeat_alerts(self, env):
        ms, state = env["ms"], env["state"]
        mid = ms.create_matter(title="NDA Review", type="contract")
        ms.create_deadline(matter_id=mid, label="Filing", due_date=_past_date())

        actions1 = check_deadlines(ms=ms, state=state, alert_windows_days=[7])
        actions2 = check_deadlines(ms=ms, state=state, alert_windows_days=[7])

        assert len(actions1) == 1
        assert len(actions2) == 0

    def test_skips_completed_deadlines(self, env):
        ms, state = env["ms"], env["state"]
        mid = ms.create_matter(title="NDA Review", type="contract")
        dl_id = ms.create_deadline(matter_id=mid, label="Filing", due_date=_past_date())
        ms.complete_deadline(dl_id)

        actions = check_deadlines(ms=ms, state=state, alert_windows_days=[7])

        assert len(actions) == 0

    def test_sends_slack_alert(self, env):
        ms, state = env["ms"], env["state"]
        mid = ms.create_matter(title="NDA Review", type="contract")
        ms.create_deadline(matter_id=mid, label="Filing", due_date=_past_date())

        slack = MagicMock()
        check_deadlines(
            ms=ms, state=state, alert_windows_days=[7],
            slack_connector=slack, slack_channel="#legal-alerts",
        )

        slack.write.assert_called_once()
