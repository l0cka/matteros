"""Intake handlers for Jira and Slack — poll external sources and create matters."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from matteros.automation.state import AutomationState
from matteros.matters.store import MatterStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_contact(ms: MatterStore, matter_id: str, reporter: dict[str, Any]) -> None:
    """Create a contact by email (catching unique constraint violations) and link to matter."""
    email = reporter.get("emailAddress", "")
    name = reporter.get("displayName", email)
    if not email:
        return
    try:
        contact_id = ms.create_contact(name=name, email=email)
    except Exception:
        contact_id = ms.get_contact_by_email(email)
        if not contact_id:
            return
    try:
        ms.link_contact(matter_id=matter_id, contact_id=contact_id, role="requestor")
    except Exception:
        pass  # Already linked


def handle_jira_intake(
    *,
    ms: MatterStore,
    state: AutomationState,
    jira_connector: Any,
    project_key: str,
    default_privileged: bool = False,
) -> list[str]:
    """Poll Jira for new issues and create matters."""
    last_poll = state.get("jira_intake:last_poll")

    jql = f"project = {project_key} ORDER BY updated DESC"
    if last_poll:
        jql = f"project = {project_key} AND updated >= '{last_poll}' ORDER BY updated DESC"

    issues = jira_connector.read("issues", {"jql": jql, "max_results": 50}, {})

    actions: list[str] = []
    for issue in issues:
        key = issue["key"]

        # Dedup
        if ms.list_matters(source_ref=key):
            continue

        fields = issue["fields"]
        matter_id = ms.create_matter(
            title=fields["summary"],
            type="request",
            source="jira",
            source_ref=key,
            privileged=default_privileged,
        )

        # Contact from reporter
        reporter = fields.get("reporter")
        if reporter:
            _ensure_contact(ms, matter_id, reporter)

        # Store description as first activity
        description = fields.get("description", "")
        if description:
            ms.add_activity(
                matter_id=matter_id,
                type="comment",
                visibility="internal",
                content={"text": description, "source": "jira"},
            )

        actions.append(f"Created matter from Jira issue {key}: {fields['summary']}")

    state.set("jira_intake:last_poll", _now_iso())
    return actions


def handle_slack_intake(
    *,
    ms: MatterStore,
    state: AutomationState,
    slack_connector: Any,
    channel: str,
    default_privileged: bool = False,
) -> list[str]:
    """Poll Slack channel for new messages and create matters."""
    last_poll = state.get("slack_intake:last_poll")

    messages = slack_connector.read(
        "messages",
        {"channel": channel, "oldest": last_poll},
        {},
    )

    actions: list[str] = []
    for msg in messages:
        # Skip bot messages
        if msg.get("bot_id") or msg.get("subtype"):
            continue

        ts = msg["ts"]

        # Skip thread replies (thread_ts present but != ts)
        thread_ts = msg.get("thread_ts")
        if thread_ts is not None and thread_ts != ts:
            continue

        source_ref = f"{channel}:{ts}"

        # Dedup
        if ms.list_matters(source_ref=source_ref):
            continue

        text = msg.get("text", "")
        first_line = text.split("\n", 1)[0]
        title = first_line[:120]

        matter_id = ms.create_matter(
            title=title,
            type="request",
            source="slack",
            source_ref=source_ref,
            privileged=default_privileged,
        )

        # Store full text as activity
        ms.add_activity(
            matter_id=matter_id,
            type="comment",
            visibility="internal",
            content={"text": text, "source": "slack"},
        )

        # Link contact from user_profile if email available
        user_profile = msg.get("user_profile")
        if user_profile and user_profile.get("email"):
            _ensure_contact(ms, matter_id, {
                "displayName": user_profile.get("display_name", user_profile["email"]),
                "emailAddress": user_profile["email"],
            })

        actions.append(f"Created matter from Slack message: {title}")

    state.set("slack_intake:last_poll", _now_iso())
    return actions
