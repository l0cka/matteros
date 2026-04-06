"""Tests for Jira and Slack intake handlers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from matteros.automation.intake import handle_jira_intake, handle_slack_intake
from matteros.automation.state import AutomationState
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore


@pytest.fixture
def env(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    ms = MatterStore(db)
    state = AutomationState(db)
    return ms, state


def _jira_issue(key: str, summary: str, description: str, reporter: dict | None = None):
    if reporter is None:
        reporter = {"displayName": "Jane Doe", "emailAddress": "jane@example.com"}
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "description": description,
            "reporter": reporter,
        },
    }


def _slack_message(text: str, ts: str, *, bot_id: str | None = None, subtype: str | None = None, thread_ts: str | None = None, user_profile: dict | None = None):
    msg: dict = {"text": text, "ts": ts}
    if bot_id is not None:
        msg["bot_id"] = bot_id
    if subtype is not None:
        msg["subtype"] = subtype
    if thread_ts is not None:
        msg["thread_ts"] = thread_ts
    if user_profile is not None:
        msg["user_profile"] = user_profile
    return msg


# ── TestJiraIntake ──────────────────────────────────────────────────


class TestJiraIntake:
    def test_creates_matter_from_jira_issue(self, env):
        ms, state = env
        connector = MagicMock()
        connector.read.return_value = [_jira_issue("LEG-1", "Review NDA", "Please review")]

        actions = handle_jira_intake(
            ms=ms, state=state, jira_connector=connector,
            project_key="LEG", default_privileged=True,
        )

        matters = ms.list_matters(source_ref="LEG-1")
        assert len(matters) == 1
        m = matters[0]
        assert m["title"] == "Review NDA"
        assert m["source"] == "jira"
        assert m["source_ref"] == "LEG-1"
        assert m["privileged"] == 1
        assert len(actions) == 1

    def test_skips_existing_matter(self, env):
        ms, state = env
        ms.create_matter(title="Existing", type="request", source="jira", source_ref="LEG-2")

        connector = MagicMock()
        connector.read.return_value = [_jira_issue("LEG-2", "Duplicate", "dup")]

        actions = handle_jira_intake(
            ms=ms, state=state, jira_connector=connector, project_key="LEG",
        )

        assert len(actions) == 0
        assert len(ms.list_matters(source_ref="LEG-2")) == 1

    def test_creates_contact_from_reporter(self, env):
        ms, state = env
        connector = MagicMock()
        connector.read.return_value = [_jira_issue("LEG-3", "Contact test", "desc")]

        handle_jira_intake(
            ms=ms, state=state, jira_connector=connector, project_key="LEG",
        )

        matters = ms.list_matters(source_ref="LEG-3")
        contacts = ms.list_matter_contacts(matters[0]["id"])
        assert len(contacts) == 1
        assert contacts[0]["email"] == "jane@example.com"
        assert contacts[0]["role"] == "requestor"

    def test_stores_description_as_activity(self, env):
        ms, state = env
        connector = MagicMock()
        connector.read.return_value = [_jira_issue("LEG-4", "Activity test", "Important details")]

        handle_jira_intake(
            ms=ms, state=state, jira_connector=connector, project_key="LEG",
        )

        matters = ms.list_matters(source_ref="LEG-4")
        activities = ms.list_activities(matters[0]["id"])
        assert len(activities) == 1
        assert activities[0]["type"] == "comment"
        assert activities[0]["visibility"] == "internal"
        assert activities[0]["content"]["text"] == "Important details"
        assert activities[0]["content"]["source"] == "jira"

    def test_updates_last_poll_timestamp(self, env):
        ms, state = env
        connector = MagicMock()
        connector.read.return_value = [_jira_issue("LEG-5", "Poll test", "desc")]

        handle_jira_intake(
            ms=ms, state=state, jira_connector=connector, project_key="LEG",
        )

        assert state.get("jira_intake:last_poll") is not None


# ── TestSlackIntake ─────────────────────────────────────────────────


class TestSlackIntake:
    def test_creates_matter_from_slack_message(self, env):
        ms, state = env
        connector = MagicMock()
        connector.read.return_value = [_slack_message("Need contract review", "1712345678.000100")]

        actions = handle_slack_intake(
            ms=ms, state=state, slack_connector=connector, channel="C123",
        )

        matters = ms.list_matters(source_ref="C123:1712345678.000100")
        assert len(matters) == 1
        m = matters[0]
        assert m["title"] == "Need contract review"
        assert m["source"] == "slack"
        assert m["source_ref"] == "C123:1712345678.000100"
        assert len(actions) == 1

    def test_skips_bot_messages(self, env):
        ms, state = env
        connector = MagicMock()
        connector.read.return_value = [_slack_message("Bot msg", "1712345678.000200", bot_id="B123")]

        actions = handle_slack_intake(
            ms=ms, state=state, slack_connector=connector, channel="C123",
        )

        assert len(actions) == 0

    def test_skips_thread_replies(self, env):
        ms, state = env
        connector = MagicMock()
        connector.read.return_value = [
            _slack_message("Thread reply", "1712345678.000300", thread_ts="1712345678.000100"),
        ]

        actions = handle_slack_intake(
            ms=ms, state=state, slack_connector=connector, channel="C123",
        )

        assert len(actions) == 0

    def test_dedup_by_source_ref(self, env):
        ms, state = env
        ms.create_matter(title="Existing", type="request", source="slack", source_ref="C123:1712345678.000400")

        connector = MagicMock()
        connector.read.return_value = [_slack_message("Duplicate", "1712345678.000400")]

        actions = handle_slack_intake(
            ms=ms, state=state, slack_connector=connector, channel="C123",
        )

        assert len(actions) == 0

    def test_truncates_long_titles(self, env):
        ms, state = env
        long_text = "A" * 200
        connector = MagicMock()
        connector.read.return_value = [_slack_message(long_text, "1712345678.000500")]

        handle_slack_intake(
            ms=ms, state=state, slack_connector=connector, channel="C123",
        )

        matters = ms.list_matters(source_ref="C123:1712345678.000500")
        assert len(matters[0]["title"]) <= 120

    def test_updates_last_poll_timestamp(self, env):
        ms, state = env
        connector = MagicMock()
        connector.read.return_value = [_slack_message("Poll test", "1712345678.000600")]

        handle_slack_intake(
            ms=ms, state=state, slack_connector=connector, channel="C123",
        )

        assert state.get("slack_intake:last_poll") == "1712345678.000600"

    def test_advances_cursor_to_latest_seen_message_timestamp(self, env):
        ms, state = env
        connector = MagicMock()
        connector.read.return_value = [
            _slack_message("Need contract review", "1712345678.000100"),
            _slack_message("Bot msg", "1712345678.000900", bot_id="B123"),
        ]

        handle_slack_intake(
            ms=ms, state=state, slack_connector=connector, channel="C123",
        )

        assert state.get("slack_intake:last_poll") == "1712345678.000900"
