"""Tests for stale matter detection automation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from matteros.automation.stale import detect_stale_matters
from matteros.automation.state import AutomationState
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore


@pytest.fixture
def env(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    ms = MatterStore(db)
    state = AutomationState(db)
    return {"db": db, "ms": ms, "state": state}


def _backdate_matter(db: SQLiteStore, matter_id: str, days: int) -> None:
    with db.connection() as conn:
        old_date = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        conn.execute(
            "UPDATE matters SET updated_at = ? WHERE id = ?", (old_date, matter_id)
        )
        conn.commit()


class TestStaleMatterDetection:
    def test_detects_stale_matter(self, env):
        ms, state, db = env["ms"], env["state"], env["db"]
        mid = ms.create_matter(title="Old NDA", type="contract")
        _backdate_matter(db, mid, 10)

        actions = detect_stale_matters(
            ms=ms, state=state, thresholds={"default": 7},
        )

        assert len(actions) == 1
        activities = ms.list_activities(mid)
        assert len(activities) == 1
        assert activities[0]["type"] == "nudge"
        assert "10 days" in activities[0]["content"]["text"]

    def test_respects_type_thresholds(self, env):
        ms, state, db = env["ms"], env["state"], env["db"]
        mid = ms.create_matter(title="Contract", type="contract")
        _backdate_matter(db, mid, 10)

        actions = detect_stale_matters(
            ms=ms, state=state, thresholds={"contract": 14, "default": 7},
        )

        # 10 days inactive < 14-day threshold for contracts
        assert len(actions) == 0

    def test_skips_resolved_matters(self, env):
        ms, state, db = env["ms"], env["state"], env["db"]
        mid = ms.create_matter(title="Done NDA", type="contract")
        ms.update_matter(mid, status="resolved")
        _backdate_matter(db, mid, 30)

        actions = detect_stale_matters(
            ms=ms, state=state, thresholds={"default": 7},
        )

        assert len(actions) == 0

    def test_nudge_counts_as_activity(self, env):
        ms, state, db = env["ms"], env["state"], env["db"]
        mid = ms.create_matter(title="Old NDA", type="contract")
        _backdate_matter(db, mid, 10)

        actions1 = detect_stale_matters(
            ms=ms, state=state, thresholds={"default": 7},
        )
        actions2 = detect_stale_matters(
            ms=ms, state=state, thresholds={"default": 7},
        )

        assert len(actions1) == 1
        assert len(actions2) == 0

    def test_sends_slack_alert(self, env):
        ms, state, db = env["ms"], env["state"], env["db"]
        mid = ms.create_matter(title="Old NDA", type="contract")
        _backdate_matter(db, mid, 10)

        slack = MagicMock()
        detect_stale_matters(
            ms=ms, state=state, thresholds={"default": 7},
            slack_connector=slack, slack_channel="#legal-alerts",
        )

        slack.write.assert_called_once()
