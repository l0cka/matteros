# Automation Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polling-based automation engine that creates matters from Jira/Slack, monitors deadlines, and detects stale matters — running inside the existing daemon.

**Architecture:** Four handler functions (jira intake, slack intake, deadline checker, stale detector) called by an `AutomationEngine` on configurable intervals. Handlers are pure functions taking `(MatterStore, AutomationState, config)` and returning a list of action descriptions. A shared `notify_slack` helper sends privilege-safe alerts. State is persisted in an `automation_state` key-value table.

**Tech Stack:** Python 3.12+, SQLite, httpx (Jira/Slack APIs), Pydantic (config), pytest

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `matteros/core/migrations/v006_automation_state.py` | Migration: automation_state table |
| Create | `matteros/automation/__init__.py` | Package init |
| Create | `matteros/automation/state.py` | AutomationState: get/set key-value pairs |
| Create | `matteros/automation/notify.py` | Privilege-safe Slack notification helper |
| Create | `matteros/automation/intake.py` | Jira and Slack intake handlers |
| Create | `matteros/automation/deadlines.py` | Deadline checker handler |
| Create | `matteros/automation/stale.py` | Stale matter detection handler |
| Create | `matteros/automation/engine.py` | AutomationEngine: schedules and dispatches handlers |
| Modify | `matteros/core/config.py` | Add AutomationsConfig Pydantic model |
| Modify | `matteros/matters/store.py` | Add recurring deadline logic to complete_deadline |
| Create | `tests/test_automation_state.py` | Tests for AutomationState |
| Create | `tests/test_automation_notify.py` | Tests for Slack notification helper |
| Create | `tests/test_automation_intake.py` | Tests for Jira and Slack intake handlers |
| Create | `tests/test_automation_deadlines.py` | Tests for deadline checker |
| Create | `tests/test_automation_stale.py` | Tests for stale matter detection |
| Create | `tests/test_automation_engine.py` | Tests for the engine scheduler |

---

### Task 1: Migration and AutomationState

**Files:**
- Create: `matteros/core/migrations/v006_automation_state.py`
- Create: `matteros/automation/__init__.py`
- Create: `matteros/automation/state.py`
- Create: `tests/test_automation_state.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_automation_state.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_automation_state.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the v006 migration**

Create `matteros/core/migrations/v006_automation_state.py`:

```python
"""v006: Add automation_state table for poll cursors and alert dedup."""
from __future__ import annotations

import sqlite3

VERSION = 6
DESCRIPTION = "Add automation_state key-value table"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_state (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
```

- [ ] **Step 4: Write AutomationState**

Create `matteros/automation/__init__.py` (empty file).

Create `matteros/automation/state.py`:

```python
"""AutomationState — key-value persistence for poll cursors and alert dedup."""
from __future__ import annotations

from datetime import UTC, datetime

from matteros.core.store import SQLiteStore


class AutomationState:
    def __init__(self, db: SQLiteStore) -> None:
        self._db = db

    def get(self, key: str) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT value FROM automation_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO automation_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
                """,
                (key, value, now, value, now),
            )
            conn.commit()

    def has(self, key: str) -> bool:
        return self.get(key) is not None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_automation_state.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/core/migrations/v006_automation_state.py matteros/automation/__init__.py matteros/automation/state.py tests/test_automation_state.py
git commit -m "feat: add automation_state table and key-value store"
```

---

### Task 2: Slack Notification Helper

**Files:**
- Create: `matteros/automation/notify.py`
- Create: `tests/test_automation_notify.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_automation_notify.py`:

```python
"""Tests for privilege-safe Slack notification helper."""
from __future__ import annotations

from matteros.automation.notify import build_alert_message


def test_non_privileged_includes_title():
    msg = build_alert_message(
        matter_id="m1",
        matter_title="NDA Review",
        privileged=False,
        text="Deadline approaching: Filing — due in 7 days",
    )
    assert "NDA Review" in msg
    assert "Deadline approaching" in msg


def test_privileged_redacts_title():
    msg = build_alert_message(
        matter_id="m1",
        matter_title="Secret Litigation",
        privileged=True,
        text="Deadline approaching: Filing — due in 7 days",
    )
    assert "Secret Litigation" not in msg
    assert "matter #m1" in msg.lower() or "Matter #m1" in msg


def test_privileged_redacts_detail_text():
    msg = build_alert_message(
        matter_id="m1",
        matter_title="Secret",
        privileged=True,
        text="No activity for 14 days",
    )
    assert "Secret" not in msg
    assert "no activity" in msg.lower()
    assert "m1" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_automation_notify.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the notify module**

Create `matteros/automation/notify.py`:

```python
"""Privilege-safe Slack notification helper."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_alert_message(
    *,
    matter_id: str,
    matter_title: str,
    privileged: bool,
    text: str,
) -> str:
    """Build a Slack-safe alert message, redacting privileged matter details."""
    if privileged:
        return f"Matter #{matter_id}: {text}"
    return f"{matter_title} ({matter_id}): {text}"


def send_slack_alert(
    *,
    slack_connector: Any,
    channel: str,
    message: str,
) -> bool:
    """Send a message to a Slack channel. Returns True on success, False on failure."""
    try:
        slack_connector.write(
            "post_summary",
            {"channel": channel},
            message,
            {},
        )
        return True
    except Exception:
        logger.warning("failed to send Slack alert to %s", channel, exc_info=True)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_automation_notify.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/automation/notify.py tests/test_automation_notify.py
git commit -m "feat: add privilege-safe Slack notification helper"
```

---

### Task 3: Jira Intake Handler

**Files:**
- Create: `matteros/automation/intake.py`
- Create: `tests/test_automation_intake.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_automation_intake.py`:

```python
"""Tests for Jira and Slack intake handlers."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore
from matteros.automation.state import AutomationState
from matteros.automation.intake import handle_jira_intake, handle_slack_intake


@pytest.fixture
def env(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    ms = MatterStore(db)
    state = AutomationState(db)
    return {"db": db, "ms": ms, "state": state}


def _mock_jira_connector(issues: list[dict[str, Any]]) -> MagicMock:
    connector = MagicMock()
    connector.read.return_value = issues
    return connector


class TestJiraIntake:
    def test_creates_matter_from_jira_issue(self, env):
        connector = _mock_jira_connector([
            {
                "key": "LEG-1",
                "fields": {
                    "summary": "Review vendor contract",
                    "description": "Please review the attached contract",
                    "reporter": {"displayName": "Jane", "emailAddress": "jane@corp.com"},
                },
            }
        ])

        actions = handle_jira_intake(
            ms=env["ms"],
            state=env["state"],
            jira_connector=connector,
            project_key="LEG",
            default_privileged=False,
        )

        assert len(actions) == 1
        matters = env["ms"].list_matters()
        assert len(matters) == 1
        assert matters[0]["title"] == "Review vendor contract"
        assert matters[0]["source"] == "jira"
        assert matters[0]["source_ref"] == "LEG-1"
        assert matters[0]["privileged"] == 0

    def test_skips_existing_matter(self, env):
        env["ms"].create_matter(
            title="Already tracked",
            type="request",
            source="jira",
            source_ref="LEG-1",
        )

        connector = _mock_jira_connector([
            {
                "key": "LEG-1",
                "fields": {
                    "summary": "Review vendor contract",
                    "description": "desc",
                    "reporter": {"displayName": "Jane", "emailAddress": "jane@corp.com"},
                },
            }
        ])

        actions = handle_jira_intake(
            ms=env["ms"],
            state=env["state"],
            jira_connector=connector,
            project_key="LEG",
            default_privileged=False,
        )

        assert len(actions) == 0
        assert len(env["ms"].list_matters()) == 1

    def test_creates_contact_from_reporter(self, env):
        connector = _mock_jira_connector([
            {
                "key": "LEG-2",
                "fields": {
                    "summary": "Question about policy",
                    "description": "Quick question",
                    "reporter": {"displayName": "Bob", "emailAddress": "bob@corp.com"},
                },
            }
        ])

        handle_jira_intake(
            ms=env["ms"],
            state=env["state"],
            jira_connector=connector,
            project_key="LEG",
            default_privileged=False,
        )

        matters = env["ms"].list_matters()
        contacts = env["ms"].list_matter_contacts(matters[0]["id"])
        assert len(contacts) == 1
        assert contacts[0]["email"] == "bob@corp.com"

    def test_stores_description_as_activity(self, env):
        connector = _mock_jira_connector([
            {
                "key": "LEG-3",
                "fields": {
                    "summary": "NDA review",
                    "description": "Please review this NDA",
                    "reporter": {"displayName": "Jane", "emailAddress": "jane@corp.com"},
                },
            }
        ])

        handle_jira_intake(
            ms=env["ms"],
            state=env["state"],
            jira_connector=connector,
            project_key="LEG",
            default_privileged=False,
        )

        matters = env["ms"].list_matters()
        activities = env["ms"].list_activities(matters[0]["id"])
        assert len(activities) == 1
        assert activities[0]["content"]["text"] == "Please review this NDA"
        assert activities[0]["visibility"] == "internal"

    def test_updates_last_poll_timestamp(self, env):
        connector = _mock_jira_connector([])

        handle_jira_intake(
            ms=env["ms"],
            state=env["state"],
            jira_connector=connector,
            project_key="LEG",
            default_privileged=False,
        )

        assert env["state"].get("jira_intake:last_poll") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_automation_intake.py::TestJiraIntake -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the intake module**

Create `matteros/automation/intake.py`:

```python
"""Jira and Slack intake handlers — poll external sources, create matters."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from matteros.automation.state import AutomationState
from matteros.matters.store import MatterStore

logger = logging.getLogger(__name__)


def handle_jira_intake(
    *,
    ms: MatterStore,
    state: AutomationState,
    jira_connector: Any,
    project_key: str,
    default_privileged: bool = False,
) -> list[str]:
    """Poll Jira for new issues and create matters. Returns list of action descriptions."""
    actions: list[str] = []

    last_poll = state.get("jira_intake:last_poll")
    jql = f"project = {project_key} ORDER BY updated DESC"
    if last_poll:
        jql = f"project = {project_key} AND updated >= '{last_poll[:19].replace('T', ' ')}' ORDER BY updated DESC"

    try:
        issues = jira_connector.read("issues", {"jql": jql, "max_results": 50}, {})
    except Exception:
        logger.warning("jira intake poll failed", exc_info=True)
        return actions

    for issue in issues:
        key = issue.get("key", "")
        if not key:
            continue

        # Dedup by source_ref
        existing = ms.list_matters(source_ref=key)
        if existing:
            continue

        fields = issue.get("fields", {})
        title = fields.get("summary", key)
        description = fields.get("description", "")
        reporter = fields.get("reporter", {})

        matter_id = ms.create_matter(
            title=title,
            type="request",
            source="jira",
            source_ref=key,
            privileged=default_privileged,
        )

        # Create/link contact from reporter
        if reporter and reporter.get("emailAddress"):
            _ensure_contact(ms, matter_id, reporter)

        # Store description as first activity
        if description:
            ms.add_activity(
                matter_id=matter_id,
                type="comment",
                content={"text": description, "source": "jira"},
                visibility="internal",
            )

        actions.append(f"created matter {matter_id} from {key}")

    state.set("jira_intake:last_poll", datetime.now(UTC).isoformat())
    return actions


def handle_slack_intake(
    *,
    ms: MatterStore,
    state: AutomationState,
    slack_connector: Any,
    channel: str,
    default_privileged: bool = False,
) -> list[str]:
    """Poll Slack channel for new messages and create matters. Returns list of action descriptions."""
    actions: list[str] = []

    last_poll = state.get("slack_intake:last_poll")
    params: dict[str, Any] = {"channel": channel}
    if last_poll:
        params["oldest"] = last_poll

    try:
        messages = slack_connector.read("messages", params, {})
    except Exception:
        logger.warning("slack intake poll failed", exc_info=True)
        return actions

    for msg in messages:
        # Skip bot messages, thread replies
        if msg.get("bot_id") or msg.get("subtype") or msg.get("thread_ts") != msg.get("ts", ""):
            # thread_ts != ts means it's a reply, not a top-level message
            # But if thread_ts is absent, it's a top-level message
            if msg.get("bot_id") or msg.get("subtype"):
                continue
            if msg.get("thread_ts") and msg.get("thread_ts") != msg.get("ts"):
                continue

        ts = msg.get("ts", "")
        if not ts:
            continue

        source_ref = f"{channel}:{ts}"

        # Dedup by source_ref
        existing = ms.list_matters(source_ref=source_ref)
        if existing:
            continue

        text = msg.get("text", "")
        title = text.split("\n")[0][:120] if text else f"Slack message {ts}"

        matter_id = ms.create_matter(
            title=title,
            type="request",
            source="slack",
            source_ref=source_ref,
            privileged=default_privileged,
        )

        # Store full message as activity
        if text:
            ms.add_activity(
                matter_id=matter_id,
                type="comment",
                content={"text": text, "source": "slack"},
                visibility="internal",
            )

        # Link contact from Slack user profile if available
        user_name = msg.get("user_profile", {}).get("real_name") or msg.get("user", "")
        user_email = msg.get("user_profile", {}).get("email")
        if user_email:
            _ensure_contact(ms, matter_id, {"displayName": user_name, "emailAddress": user_email})

        actions.append(f"created matter {matter_id} from slack:{ts}")

    state.set("slack_intake:last_poll", datetime.now(UTC).isoformat())
    return actions


def _ensure_contact(ms: MatterStore, matter_id: str, reporter: dict[str, Any]) -> None:
    """Create or find a contact by email, then link to matter."""
    email = reporter.get("emailAddress", "")
    name = reporter.get("displayName", email)
    if not email:
        return

    # Try to find existing contact by listing matter contacts won't work here;
    # we need to check if contact with this email exists globally
    try:
        contact_id = ms.create_contact(name=name, email=email)
    except Exception:
        # Email unique constraint — contact already exists, find it
        contact_id = ms.get_contact_by_email(email)
        if not contact_id:
            return

    try:
        ms.link_contact(matter_id=matter_id, contact_id=contact_id, role="requestor")
    except Exception:
        # Already linked
        pass
```

- [ ] **Step 4: Add missing methods to MatterStore**

Add `list_matters` support for `source_ref` filter and `get_contact_by_email` to `matteros/matters/store.py`:

In `list_matters`, add `source_ref: str | None = None` parameter:

```python
def list_matters(
    self,
    *,
    status: str | None = None,
    type: str | None = None,
    assignee_id: str | None = None,
    source_ref: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
```

Add the filter clause:

```python
        if source_ref is not None:
            clauses.append("source_ref = ?")
            params.append(source_ref)
```

Add `get_contact_by_email` method:

```python
    def get_contact_by_email(self, email: str) -> str | None:
        """Return contact ID for a given email, or None."""
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT id FROM contacts WHERE email = ?", (email,)
            ).fetchone()
            return row["id"] if row else None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_automation_intake.py::TestJiraIntake -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/automation/intake.py matteros/matters/store.py tests/test_automation_intake.py
git commit -m "feat: add Jira intake handler with dedup and contact linking"
```

---

### Task 4: Slack Intake Handler Tests

**Files:**
- Modify: `tests/test_automation_intake.py`

- [ ] **Step 1: Add Slack intake tests**

Add to `tests/test_automation_intake.py`:

```python
def _mock_slack_connector(messages: list[dict[str, Any]]) -> MagicMock:
    connector = MagicMock()
    connector.read.return_value = messages
    return connector


class TestSlackIntake:
    def test_creates_matter_from_slack_message(self, env):
        connector = _mock_slack_connector([
            {
                "ts": "1712345678.000100",
                "text": "Can legal review this vendor agreement?",
                "user": "U12345",
            }
        ])

        actions = handle_slack_intake(
            ms=env["ms"],
            state=env["state"],
            slack_connector=connector,
            channel="C_LEGAL",
            default_privileged=False,
        )

        assert len(actions) == 1
        matters = env["ms"].list_matters()
        assert len(matters) == 1
        assert matters[0]["title"] == "Can legal review this vendor agreement?"
        assert matters[0]["source"] == "slack"
        assert matters[0]["source_ref"] == "C_LEGAL:1712345678.000100"

    def test_skips_bot_messages(self, env):
        connector = _mock_slack_connector([
            {
                "ts": "1712345678.000200",
                "text": "Bot notification",
                "bot_id": "B12345",
            }
        ])

        actions = handle_slack_intake(
            ms=env["ms"],
            state=env["state"],
            slack_connector=connector,
            channel="C_LEGAL",
            default_privileged=False,
        )

        assert len(actions) == 0
        assert len(env["ms"].list_matters()) == 0

    def test_skips_thread_replies(self, env):
        connector = _mock_slack_connector([
            {
                "ts": "1712345678.000300",
                "thread_ts": "1712345678.000100",
                "text": "Reply in thread",
                "user": "U12345",
            }
        ])

        actions = handle_slack_intake(
            ms=env["ms"],
            state=env["state"],
            slack_connector=connector,
            channel="C_LEGAL",
            default_privileged=False,
        )

        assert len(actions) == 0

    def test_dedup_by_source_ref(self, env):
        env["ms"].create_matter(
            title="Existing",
            type="request",
            source="slack",
            source_ref="C_LEGAL:1712345678.000100",
        )

        connector = _mock_slack_connector([
            {
                "ts": "1712345678.000100",
                "text": "Can legal review this?",
                "user": "U12345",
            }
        ])

        actions = handle_slack_intake(
            ms=env["ms"],
            state=env["state"],
            slack_connector=connector,
            channel="C_LEGAL",
            default_privileged=False,
        )

        assert len(actions) == 0
        assert len(env["ms"].list_matters()) == 1

    def test_truncates_long_titles(self, env):
        long_text = "A" * 200 + "\nSecond line"
        connector = _mock_slack_connector([
            {
                "ts": "1712345678.000400",
                "text": long_text,
                "user": "U12345",
            }
        ])

        handle_slack_intake(
            ms=env["ms"],
            state=env["state"],
            slack_connector=connector,
            channel="C_LEGAL",
            default_privileged=False,
        )

        matters = env["ms"].list_matters()
        assert len(matters[0]["title"]) <= 120

    def test_updates_last_poll_timestamp(self, env):
        connector = _mock_slack_connector([])

        handle_slack_intake(
            ms=env["ms"],
            state=env["state"],
            slack_connector=connector,
            channel="C_LEGAL",
            default_privileged=False,
        )

        assert env["state"].get("slack_intake:last_poll") is not None
```

- [ ] **Step 2: Run all intake tests**

Run: `pytest tests/test_automation_intake.py -v`
Expected: All 11 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_automation_intake.py
git commit -m "test: add Slack intake handler tests"
```

---

### Task 5: Deadline Checker

**Files:**
- Create: `matteros/automation/deadlines.py`
- Create: `tests/test_automation_deadlines.py`
- Modify: `matteros/matters/store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_automation_deadlines.py`:

```python
"""Tests for deadline checker automation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore
from matteros.automation.state import AutomationState
from matteros.automation.deadlines import check_deadlines


@pytest.fixture
def env(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    ms = MatterStore(db)
    state = AutomationState(db)
    return {"db": db, "ms": ms, "state": state}


def _days_from_now(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")


class TestDeadlineChecker:
    def test_marks_overdue_deadline_as_missed(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Filing", type="compliance")
        ms.create_deadline(matter_id=matter_id, label="Q1 Filing", due_date="2020-01-01")

        actions = check_deadlines(
            ms=ms,
            state=env["state"],
            alert_windows_days=[30, 14, 7, 1],
            slack_connector=None,
            slack_channel=None,
        )

        deadlines = ms.list_deadlines(matter_id)
        assert deadlines[0]["status"] == "missed"
        assert len(actions) >= 1

    def test_adds_activity_for_missed_deadline(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Filing", type="compliance")
        ms.create_deadline(matter_id=matter_id, label="Q1 Filing", due_date="2020-01-01")

        check_deadlines(
            ms=ms,
            state=env["state"],
            alert_windows_days=[30, 14, 7, 1],
            slack_connector=None,
            slack_channel=None,
        )

        activities = ms.list_activities(matter_id)
        assert any("missed" in (a.get("content", {}) or {}).get("text", "").lower() for a in activities)

    def test_alerts_for_approaching_deadline(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Contract Renewal", type="contract")
        ms.create_deadline(
            matter_id=matter_id,
            label="Renewal Date",
            due_date=_days_from_now(5),
        )

        actions = check_deadlines(
            ms=ms,
            state=env["state"],
            alert_windows_days=[30, 14, 7, 1],
            slack_connector=None,
            slack_channel=None,
        )

        assert len(actions) >= 1
        activities = ms.list_activities(matter_id)
        assert any("approaching" in (a.get("content", {}) or {}).get("text", "").lower() for a in activities)

    def test_dedup_prevents_repeat_alerts(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Filing", type="compliance")
        dl_id = ms.create_deadline(
            matter_id=matter_id,
            label="Annual",
            due_date=_days_from_now(5),
        )

        # First run — should alert
        actions1 = check_deadlines(
            ms=ms, state=env["state"], alert_windows_days=[7],
            slack_connector=None, slack_channel=None,
        )

        # Second run — should not re-alert
        actions2 = check_deadlines(
            ms=ms, state=env["state"], alert_windows_days=[7],
            slack_connector=None, slack_channel=None,
        )

        assert len(actions1) >= 1
        assert len(actions2) == 0

    def test_skips_completed_deadlines(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Done", type="compliance")
        dl_id = ms.create_deadline(matter_id=matter_id, label="Past", due_date="2020-01-01")
        ms.complete_deadline(dl_id)

        actions = check_deadlines(
            ms=ms, state=env["state"], alert_windows_days=[7],
            slack_connector=None, slack_channel=None,
        )

        assert len(actions) == 0

    def test_sends_slack_alert(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Filing", type="compliance", privileged=False)
        ms.create_deadline(matter_id=matter_id, label="Q1", due_date="2020-01-01")

        mock_slack = MagicMock()
        mock_slack.write.return_value = {"ok": True}

        check_deadlines(
            ms=ms, state=env["state"], alert_windows_days=[7],
            slack_connector=mock_slack, slack_channel="legal-alerts",
        )

        mock_slack.write.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_automation_deadlines.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Add mark_deadline_missed to MatterStore**

Add to `matteros/matters/store.py`:

```python
    def mark_deadline_missed(self, deadline_id: int) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE deadlines SET status = 'missed' WHERE id = ?",
                (deadline_id,),
            )
            conn.commit()

    def list_all_pending_deadlines(self) -> list[dict[str, Any]]:
        """Return all pending deadlines with matter info."""
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT d.*, m.title AS matter_title, m.type AS matter_type,
                       m.privileged AS matter_privileged
                FROM deadlines d
                JOIN matters m ON m.id = d.matter_id
                WHERE d.status = 'pending'
                ORDER BY d.due_date ASC
                """,
            ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Write the deadline checker**

Create `matteros/automation/deadlines.py`:

```python
"""Deadline checker — monitors deadlines, marks overdue, sends alerts."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from matteros.automation.notify import build_alert_message, send_slack_alert
from matteros.automation.state import AutomationState
from matteros.matters.store import MatterStore

logger = logging.getLogger(__name__)


def check_deadlines(
    *,
    ms: MatterStore,
    state: AutomationState,
    alert_windows_days: list[int],
    slack_connector: Any | None,
    slack_channel: str | None,
) -> list[str]:
    """Check all pending deadlines for overdue/approaching status. Returns action descriptions."""
    actions: list[str] = []
    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%dT00:00:00")

    deadlines = ms.list_all_pending_deadlines()

    for dl in deadlines:
        dl_id = dl["id"]
        due = dl["due_date"]
        matter_id = dl["matter_id"]
        label = dl["label"]
        privileged = bool(dl.get("matter_privileged", 1))

        # Overdue check
        if due < today:
            dedup_key = f"deadline_alert:{dl_id}:missed"
            if state.has(dedup_key):
                continue

            ms.mark_deadline_missed(dl_id)
            text = f"Deadline missed: {label}"
            ms.add_activity(
                matter_id=matter_id,
                type="deadline_update",
                content={"text": text},
            )

            if slack_connector and slack_channel:
                msg = build_alert_message(
                    matter_id=matter_id,
                    matter_title=dl.get("matter_title", ""),
                    privileged=privileged,
                    text=text,
                )
                send_slack_alert(
                    slack_connector=slack_connector,
                    channel=slack_channel,
                    message=msg,
                )

            state.set(dedup_key, now.isoformat())
            actions.append(f"deadline {dl_id} missed for matter {matter_id}")
            continue

        # Approaching check — find the largest matching window
        days_until = (datetime.fromisoformat(due) - now).days
        for window in sorted(alert_windows_days, reverse=True):
            if days_until <= window:
                dedup_key = f"deadline_alert:{dl_id}:{window}"
                if state.has(dedup_key):
                    continue

                text = f"Deadline approaching: {label} — due in {days_until} days"
                ms.add_activity(
                    matter_id=matter_id,
                    type="deadline_update",
                    content={"text": text},
                )

                if slack_connector and slack_channel:
                    msg = build_alert_message(
                        matter_id=matter_id,
                        matter_title=dl.get("matter_title", ""),
                        privileged=privileged,
                        text=text,
                    )
                    send_slack_alert(
                        slack_connector=slack_connector,
                        channel=slack_channel,
                        message=msg,
                    )

                state.set(dedup_key, now.isoformat())
                actions.append(f"deadline {dl_id} approaching ({window}d window) for matter {matter_id}")
                break  # Only alert for the largest matching window

    return actions
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_automation_deadlines.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/automation/deadlines.py matteros/matters/store.py tests/test_automation_deadlines.py
git commit -m "feat: add deadline checker with overdue detection and Slack alerts"
```

---

### Task 6: Stale Matter Detection

**Files:**
- Create: `matteros/automation/stale.py`
- Create: `tests/test_automation_stale.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_automation_stale.py`:

```python
"""Tests for stale matter detection."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore
from matteros.automation.state import AutomationState
from matteros.automation.stale import detect_stale_matters


@pytest.fixture
def env(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    ms = MatterStore(db)
    state = AutomationState(db)
    return {"db": db, "ms": ms, "state": state}


THRESHOLDS = {"request": 7, "contract": 14, "compliance": 30, "default": 14}


class TestStaleDetection:
    def test_detects_stale_matter(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Old Request", type="request")
        ms.update_matter(matter_id, status="in_progress")

        # Backdate the matter's updated_at to make it stale
        with env["db"].connection() as conn:
            old_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
            conn.execute("UPDATE matters SET updated_at = ? WHERE id = ?", (old_date, matter_id))
            conn.commit()

        actions = detect_stale_matters(
            ms=ms,
            state=env["state"],
            thresholds=THRESHOLDS,
            slack_connector=None,
            slack_channel=None,
        )

        assert len(actions) == 1
        activities = ms.list_activities(matter_id)
        assert any(a["type"] == "nudge" for a in activities)

    def test_respects_type_thresholds(self, env):
        ms = env["ms"]
        # Contract with 10 days no activity — under 14-day threshold
        matter_id = ms.create_matter(title="Contract", type="contract")
        ms.update_matter(matter_id, status="in_progress")

        with env["db"].connection() as conn:
            old_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
            conn.execute("UPDATE matters SET updated_at = ? WHERE id = ?", (old_date, matter_id))
            conn.commit()

        actions = detect_stale_matters(
            ms=ms, state=env["state"], thresholds=THRESHOLDS,
            slack_connector=None, slack_channel=None,
        )

        assert len(actions) == 0  # Not stale yet for contracts

    def test_skips_resolved_matters(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Done", type="request")
        ms.update_matter(matter_id, status="resolved")

        with env["db"].connection() as conn:
            old_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            conn.execute("UPDATE matters SET updated_at = ? WHERE id = ?", (old_date, matter_id))
            conn.commit()

        actions = detect_stale_matters(
            ms=ms, state=env["state"], thresholds=THRESHOLDS,
            slack_connector=None, slack_channel=None,
        )

        assert len(actions) == 0

    def test_nudge_counts_as_activity(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Stale", type="request")
        ms.update_matter(matter_id, status="new")

        with env["db"].connection() as conn:
            old_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
            conn.execute("UPDATE matters SET updated_at = ? WHERE id = ?", (old_date, matter_id))
            conn.commit()

        # First run — should nudge
        actions1 = detect_stale_matters(
            ms=ms, state=env["state"], thresholds=THRESHOLDS,
            slack_connector=None, slack_channel=None,
        )

        # Second run — nudge itself is recent activity, should not re-nudge
        actions2 = detect_stale_matters(
            ms=ms, state=env["state"], thresholds=THRESHOLDS,
            slack_connector=None, slack_channel=None,
        )

        assert len(actions1) == 1
        assert len(actions2) == 0

    def test_sends_slack_alert(self, env):
        ms = env["ms"]
        matter_id = ms.create_matter(title="Stale", type="request", privileged=False)
        ms.update_matter(matter_id, status="in_progress")

        with env["db"].connection() as conn:
            old_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
            conn.execute("UPDATE matters SET updated_at = ? WHERE id = ?", (old_date, matter_id))
            conn.commit()

        mock_slack = MagicMock()
        mock_slack.write.return_value = {"ok": True}

        detect_stale_matters(
            ms=ms, state=env["state"], thresholds=THRESHOLDS,
            slack_connector=mock_slack, slack_channel="legal-alerts",
        )

        mock_slack.write.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_automation_stale.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the stale detection module**

Create `matteros/automation/stale.py`:

```python
"""Stale matter detection — nudge matters with no recent activity."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from matteros.automation.notify import build_alert_message, send_slack_alert
from matteros.automation.state import AutomationState
from matteros.matters.store import MatterStore

logger = logging.getLogger(__name__)


def detect_stale_matters(
    *,
    ms: MatterStore,
    state: AutomationState,
    thresholds: dict[str, int],
    slack_connector: Any | None,
    slack_channel: str | None,
) -> list[str]:
    """Find matters with no recent activity and create nudge activities. Returns action descriptions."""
    actions: list[str] = []
    now = datetime.now(UTC)

    # Get all active matters
    active_matters: list[dict[str, Any]] = []
    for status in ("new", "in_progress"):
        active_matters.extend(ms.list_matters(status=status))

    for matter in active_matters:
        matter_id = matter["id"]
        matter_type = matter.get("type", "default")
        threshold_days = thresholds.get(matter_type, thresholds.get("default", 14))
        cutoff = (now - timedelta(days=threshold_days)).isoformat()
        privileged = bool(matter.get("privileged", 1))

        # Check most recent activity
        activities = ms.list_activities(matter_id)
        if activities:
            last_activity_date = activities[-1]["created_at"]
            if last_activity_date > cutoff:
                continue
            days_inactive = (now - datetime.fromisoformat(last_activity_date)).days
        else:
            # No activities — use matter's updated_at
            last_date = matter.get("updated_at", matter.get("created_at", ""))
            if last_date > cutoff:
                continue
            days_inactive = (now - datetime.fromisoformat(last_date)).days

        # Create nudge activity
        text = f"No activity for {days_inactive} days"
        ms.add_activity(
            matter_id=matter_id,
            type="nudge",
            content={"text": text},
        )

        if slack_connector and slack_channel:
            msg = build_alert_message(
                matter_id=matter_id,
                matter_title=matter.get("title", ""),
                privileged=privileged,
                text=text,
            )
            send_slack_alert(
                slack_connector=slack_connector,
                channel=slack_channel,
                message=msg,
            )

        actions.append(f"nudged matter {matter_id}: {text}")

    return actions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_automation_stale.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/automation/stale.py tests/test_automation_stale.py
git commit -m "feat: add stale matter detection with nudge activities and Slack alerts"
```

---

### Task 7: AutomationEngine

**Files:**
- Create: `matteros/automation/engine.py`
- Create: `tests/test_automation_engine.py`
- Modify: `matteros/core/config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_automation_engine.py`:

```python
"""Tests for AutomationEngine scheduler."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_engine_creates_without_error(engine: AutomationEngine):
    assert engine is not None


def test_engine_run_once_with_nothing_enabled(engine: AutomationEngine):
    actions = engine.run_once()
    assert actions == []


def test_engine_run_once_with_deadlines_enabled(tmp_path: Path):
    db = SQLiteStore(tmp_path / "test.db")
    engine = AutomationEngine(db=db, config={
        "jira_intake": {"enabled": False},
        "slack_intake": {"enabled": False},
        "deadline_alerts": {
            "enabled": True,
            "check_interval_minutes": 60,
            "alert_windows_days": [7],
            "slack_channel": None,
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
            "enabled": True,
            "check_interval_minutes": 120,
            "thresholds": {"default": 14},
            "slack_channel": None,
        },
    })

    actions = engine.run_once()
    assert isinstance(actions, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_automation_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Add AutomationsConfig to config.py**

Add to `matteros/core/config.py`, before `MatterOSConfig`:

```python
class AutomationsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
```

Add the field to `MatterOSConfig`:

```python
    automations: AutomationsConfig = Field(default_factory=AutomationsConfig)
```

- [ ] **Step 4: Write AutomationEngine**

Create `matteros/automation/engine.py`:

```python
"""AutomationEngine — schedules and dispatches automation handlers."""
from __future__ import annotations

import logging
from typing import Any

from matteros.automation.deadlines import check_deadlines
from matteros.automation.intake import handle_jira_intake, handle_slack_intake
from matteros.automation.stale import detect_stale_matters
from matteros.automation.state import AutomationState
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore

logger = logging.getLogger(__name__)


class AutomationEngine:
    """Manages automation handlers on configurable schedules."""

    def __init__(self, *, db: SQLiteStore, config: dict[str, Any]) -> None:
        self._db = db
        self._config = config
        self._ms = MatterStore(db)
        self._state = AutomationState(db)

    def run_once(self) -> list[str]:
        """Run all enabled handlers once. Returns combined action descriptions."""
        actions: list[str] = []

        # Jira intake
        jira_cfg = self._config.get("jira_intake", {})
        if jira_cfg.get("enabled"):
            try:
                from matteros.connectors.jira import JiraConnector
                connector = JiraConnector()
                actions.extend(handle_jira_intake(
                    ms=self._ms,
                    state=self._state,
                    jira_connector=connector,
                    project_key=jira_cfg.get("project_key", "LEG"),
                    default_privileged=jira_cfg.get("default_privileged", False),
                ))
            except Exception:
                logger.warning("jira intake failed", exc_info=True)

        # Slack intake
        slack_cfg = self._config.get("slack_intake", {})
        if slack_cfg.get("enabled"):
            try:
                from matteros.connectors.slack import SlackConnector
                connector = SlackConnector()
                actions.extend(handle_slack_intake(
                    ms=self._ms,
                    state=self._state,
                    slack_connector=connector,
                    channel=slack_cfg.get("channel", ""),
                    default_privileged=slack_cfg.get("default_privileged", False),
                ))
            except Exception:
                logger.warning("slack intake failed", exc_info=True)

        # Deadline alerts
        dl_cfg = self._config.get("deadline_alerts", {})
        if dl_cfg.get("enabled"):
            try:
                slack_connector = self._get_slack_connector()
                actions.extend(check_deadlines(
                    ms=self._ms,
                    state=self._state,
                    alert_windows_days=dl_cfg.get("alert_windows_days", [30, 14, 7, 1]),
                    slack_connector=slack_connector,
                    slack_channel=dl_cfg.get("slack_channel"),
                ))
            except Exception:
                logger.warning("deadline check failed", exc_info=True)

        # Stale detection
        stale_cfg = self._config.get("stale_detection", {})
        if stale_cfg.get("enabled"):
            try:
                slack_connector = self._get_slack_connector()
                actions.extend(detect_stale_matters(
                    ms=self._ms,
                    state=self._state,
                    thresholds=stale_cfg.get("thresholds", {"default": 14}),
                    slack_connector=slack_connector,
                    slack_channel=stale_cfg.get("slack_channel"),
                ))
            except Exception:
                logger.warning("stale detection failed", exc_info=True)

        if actions:
            logger.info("automation engine completed: %d actions", len(actions))
        return actions

    def _get_slack_connector(self) -> Any | None:
        try:
            from matteros.connectors.slack import SlackConnector
            return SlackConnector()
        except Exception:
            return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_automation_engine.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ --ignore=tests/cassettes -q`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add matteros/automation/engine.py matteros/core/config.py tests/test_automation_engine.py
git commit -m "feat: add AutomationEngine with configurable handler dispatch"
```

---

### Task 8: Recurring Deadlines

**Files:**
- Modify: `matteros/matters/store.py`
- Create: `tests/test_recurring_deadlines.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_recurring_deadlines.py`:

```python
"""Tests for recurring deadline auto-generation."""
from __future__ import annotations

from pathlib import Path

import pytest
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore


@pytest.fixture
def ms(tmp_path: Path) -> MatterStore:
    db = SQLiteStore(tmp_path / "test.db")
    return MatterStore(db)


def test_complete_recurring_creates_next(ms: MatterStore):
    matter_id = ms.create_matter(title="Annual Filing", type="compliance")
    dl_id = ms.create_deadline(
        matter_id=matter_id,
        label="Annual report",
        due_date="2026-03-31",
        recurring="P1Y",
    )

    ms.complete_deadline(dl_id)

    deadlines = ms.list_deadlines(matter_id)
    assert len(deadlines) == 2
    completed = [d for d in deadlines if d["status"] == "completed"]
    pending = [d for d in deadlines if d["status"] == "pending"]
    assert len(completed) == 1
    assert len(pending) == 1
    assert pending[0]["due_date"][:10] == "2027-03-31"
    assert pending[0]["label"] == "Annual report"
    assert pending[0]["recurring"] == "P1Y"


def test_complete_non_recurring_does_not_create_next(ms: MatterStore):
    matter_id = ms.create_matter(title="One-off", type="compliance")
    dl_id = ms.create_deadline(
        matter_id=matter_id,
        label="One-time filing",
        due_date="2026-06-30",
    )

    ms.complete_deadline(dl_id)

    deadlines = ms.list_deadlines(matter_id)
    assert len(deadlines) == 1
    assert deadlines[0]["status"] == "completed"


def test_recurring_quarterly(ms: MatterStore):
    matter_id = ms.create_matter(title="Quarterly", type="compliance")
    dl_id = ms.create_deadline(
        matter_id=matter_id,
        label="Q1 Filing",
        due_date="2026-03-31",
        recurring="P3M",
    )

    ms.complete_deadline(dl_id)

    deadlines = ms.list_deadlines(matter_id)
    pending = [d for d in deadlines if d["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["due_date"][:10] == "2026-06-30"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_recurring_deadlines.py -v`
Expected: FAIL — `complete_deadline` doesn't create next occurrence

- [ ] **Step 3: Update complete_deadline with recurring logic**

Modify `matteros/matters/store.py` — replace the `complete_deadline` method:

```python
    def complete_deadline(self, deadline_id: int) -> None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM deadlines WHERE id = ?", (deadline_id,)
            ).fetchone()
            if not row:
                return

            conn.execute(
                "UPDATE deadlines SET status = 'completed' WHERE id = ?",
                (deadline_id,),
            )

            # Auto-generate next occurrence for recurring deadlines
            recurring = row["recurring"]
            if recurring:
                next_due = self._advance_date(row["due_date"], recurring)
                if next_due:
                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        """
                        INSERT INTO deadlines (matter_id, label, due_date, type, alert_before, recurring, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        (row["matter_id"], row["label"], next_due, row["type"],
                         row["alert_before"], recurring, now),
                    )

            conn.commit()

    @staticmethod
    def _advance_date(due_date: str, duration: str) -> str | None:
        """Advance a date by an ISO 8601 duration (P1Y, P3M, P1M, P7D, etc.)."""
        from datetime import date as date_type
        d = date_type.fromisoformat(due_date[:10])

        if duration.startswith("P") and duration.endswith("Y"):
            years = int(duration[1:-1])
            return d.replace(year=d.year + years).isoformat()
        if duration.startswith("P") and duration.endswith("M"):
            months = int(duration[1:-1])
            new_month = d.month + months
            new_year = d.year + (new_month - 1) // 12
            new_month = ((new_month - 1) % 12) + 1
            # Handle month-end edge cases (e.g., Jan 31 + 1M = Feb 28)
            import calendar
            max_day = calendar.monthrange(new_year, new_month)[1]
            new_day = min(d.day, max_day)
            return date_type(new_year, new_month, new_day).isoformat()
        if duration.startswith("P") and duration.endswith("D"):
            from datetime import timedelta as td
            days = int(duration[1:-1])
            return (d + td(days=days)).isoformat()

        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_recurring_deadlines.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run existing deadline tests for regression**

Run: `pytest tests/test_matter_store.py tests/test_automation_deadlines.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/matters/store.py tests/test_recurring_deadlines.py
git commit -m "feat: add recurring deadline auto-generation on completion"
```

---

## Summary

After completing all 8 tasks:

- **AutomationState** — key-value persistence for poll cursors and alert dedup
- **Slack notifications** — privilege-safe alert helper
- **Jira intake** — poll for issues, create matters with contacts and activities
- **Slack intake** — poll channel messages, create matters with dedup
- **Deadline checker** — overdue detection, approaching alerts, Slack notifications
- **Stale detection** — configurable per-type thresholds, nudge activities
- **AutomationEngine** — schedules all handlers, configurable via config.yml
- **Recurring deadlines** — auto-generate next occurrence on completion
