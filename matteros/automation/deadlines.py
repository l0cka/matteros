"""Deadline checker — flags missed and approaching deadlines."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from matteros.automation.notify import build_alert_message, send_slack_alert
from matteros.automation.state import AutomationState
from matteros.matters.store import MatterStore


def check_deadlines(
    *,
    ms: MatterStore,
    state: AutomationState,
    alert_windows_days: list[int],
    slack_connector: Any | None = None,
    slack_channel: str | None = None,
) -> list[str]:
    """Check all pending deadlines for missed or approaching alerts.

    Returns a list of human-readable action descriptions.
    """
    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%dT00:00:00")
    actions: list[str] = []

    deadlines = ms.list_all_pending_deadlines()

    for dl in deadlines:
        dl_id = dl["id"]
        label = dl["label"]
        due = dl["due_date"]
        matter_id = dl["matter_id"]
        matter_title = dl["matter_title"]
        privileged = bool(dl["matter_privileged"])

        if due < today:
            # Overdue
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
                    matter_title=matter_title,
                    privileged=privileged,
                    text=text,
                )
                send_slack_alert(
                    slack_connector=slack_connector,
                    channel=slack_channel,
                    message=msg,
                )

            state.set(dedup_key, now.isoformat())
            actions.append(f"Marked deadline {dl_id} as missed: {label}")
        else:
            # Approaching — check alert windows
            due_dt = datetime.fromisoformat(due).replace(tzinfo=UTC)
            days_until = (due_dt - now).days

            for window in sorted(alert_windows_days, reverse=True):
                if days_until <= window:
                    dedup_key = f"deadline_alert:{dl_id}:{window}"
                    if state.has(dedup_key):
                        break

                    text = f"Deadline approaching: {label} — due in {days_until} days"
                    ms.add_activity(
                        matter_id=matter_id,
                        type="deadline_update",
                        content={"text": text},
                    )

                    if slack_connector and slack_channel:
                        msg = build_alert_message(
                            matter_id=matter_id,
                            matter_title=matter_title,
                            privileged=privileged,
                            text=text,
                        )
                        send_slack_alert(
                            slack_connector=slack_connector,
                            channel=slack_channel,
                            message=msg,
                        )

                    state.set(dedup_key, now.isoformat())
                    actions.append(
                        f"Alert for deadline {dl_id}: {label} due in {days_until} days"
                    )
                    break

    return actions
