"""Stale matter detection — nudges matters with no recent activity."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from matteros.automation.notify import build_alert_message, send_slack_alert
from matteros.automation.state import AutomationState
from matteros.matters.store import MatterStore


def detect_stale_matters(
    *,
    ms: MatterStore,
    state: AutomationState,
    thresholds: dict[str, int],
    slack_connector: Any | None = None,
    slack_channel: str | None = None,
) -> list[str]:
    """Detect matters with no recent activity and add nudge activities.

    Returns a list of human-readable action descriptions.
    """
    now = datetime.now(UTC)
    actions: list[str] = []

    # Gather active matters (new + in_progress)
    matters = ms.list_matters(status="new") + ms.list_matters(status="in_progress")

    for matter in matters:
        matter_id = matter["id"]
        matter_type = matter["type"]
        threshold_days = thresholds.get(matter_type, thresholds.get("default", 7))

        cutoff = (now - timedelta(days=threshold_days)).isoformat()

        # Determine last activity date
        activities = ms.list_activities(matter_id)
        if activities:
            last_date = activities[-1]["created_at"]
        else:
            last_date = matter["updated_at"]

        if last_date > cutoff:
            continue  # Not stale yet

        # Calculate days inactive
        last_dt = datetime.fromisoformat(last_date)
        days_inactive = (now - last_dt).days

        text = f"No activity for {days_inactive} days"
        ms.add_activity(
            matter_id=matter_id,
            type="nudge",
            content={"text": text},
        )

        if slack_connector and slack_channel:
            msg = build_alert_message(
                matter_id=matter_id,
                matter_title=matter["title"],
                privileged=bool(matter["privileged"]),
                text=text,
            )
            send_slack_alert(
                slack_connector=slack_connector,
                channel=slack_channel,
                message=msg,
            )

        actions.append(f"Nudged matter {matter_id}: {text}")

    return actions
