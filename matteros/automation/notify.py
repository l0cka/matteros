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
        slack_connector.write("post_summary", {"channel": channel}, message, {})
        return True
    except Exception:
        logger.warning("failed to send Slack alert to %s", channel, exc_info=True)
        return False
