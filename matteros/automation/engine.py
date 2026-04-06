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
    def __init__(self, *, db: SQLiteStore, config: dict[str, Any]) -> None:
        self._db = db
        self._config = config
        self._ms = MatterStore(db)
        self._state = AutomationState(db)

    def run_once(self) -> list[str]:
        """Run all enabled handlers once. Returns combined action descriptions."""
        actions: list[str] = []

        jira_cfg = self._config.get("jira_intake", {})
        if jira_cfg.get("enabled"):
            try:
                from matteros.connectors.jira import JiraConnector
                connector = JiraConnector()
                actions.extend(handle_jira_intake(
                    ms=self._ms, state=self._state, jira_connector=connector,
                    project_key=jira_cfg.get("project_key", "LEG"),
                    default_privileged=jira_cfg.get("default_privileged", False),
                ))
            except Exception:
                logger.warning("jira intake failed", exc_info=True)

        slack_cfg = self._config.get("slack_intake", {})
        if slack_cfg.get("enabled"):
            try:
                from matteros.connectors.slack import SlackConnector
                connector = SlackConnector()
                actions.extend(handle_slack_intake(
                    ms=self._ms, state=self._state, slack_connector=connector,
                    channel=slack_cfg.get("channel", ""),
                    default_privileged=slack_cfg.get("default_privileged", False),
                ))
            except Exception:
                logger.warning("slack intake failed", exc_info=True)

        dl_cfg = self._config.get("deadline_alerts", {})
        if dl_cfg.get("enabled"):
            try:
                slack_connector = self._get_slack_connector()
                actions.extend(check_deadlines(
                    ms=self._ms, state=self._state,
                    alert_windows_days=dl_cfg.get("alert_windows_days", [30, 14, 7, 1]),
                    slack_connector=slack_connector,
                    slack_channel=dl_cfg.get("slack_channel"),
                ))
            except Exception:
                logger.warning("deadline check failed", exc_info=True)

        stale_cfg = self._config.get("stale_detection", {})
        if stale_cfg.get("enabled"):
            try:
                slack_connector = self._get_slack_connector()
                actions.extend(detect_stale_matters(
                    ms=self._ms, state=self._state,
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
