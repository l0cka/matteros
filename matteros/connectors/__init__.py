from __future__ import annotations

import os
from pathlib import Path

from matteros.connectors.base import ConnectorRegistry
from matteros.connectors.csv_export import CsvExportConnector
from matteros.connectors.filesystem import FilesystemConnector
from matteros.connectors.github_connector import GitHubConnector
from matteros.connectors.ical import ICalConnector
from matteros.connectors.jira import JiraConnector
from matteros.connectors.ms_graph_auth import MicrosoftGraphTokenManager
from matteros.connectors.ms_graph_calendar import MicrosoftGraphCalendarConnector
from matteros.connectors.ms_graph_mail import MicrosoftGraphMailConnector
from matteros.connectors.plugin import register_plugins
from matteros.connectors.slack import SlackConnector


def create_default_registry(
    *,
    auth_cache_path: Path | None = None,
    plugin_dir: Path | None = None,
) -> ConnectorRegistry:
    registry = ConnectorRegistry()
    resolved_auth_cache = (
        auth_cache_path.expanduser()
        if auth_cache_path is not None
        else Path(".matteros/auth/ms_graph_token.json").expanduser()
    )
    token_manager = MicrosoftGraphTokenManager(
        cache_path=resolved_auth_cache
    )
    registry.register(MicrosoftGraphMailConnector(token_manager=token_manager))
    registry.register(MicrosoftGraphCalendarConnector(token_manager=token_manager))
    registry.register(FilesystemConnector())
    registry.register(CsvExportConnector())

    # Optional connectors - register only when auth tokens are available.
    if os.environ.get("MATTEROS_SLACK_TOKEN"):
        registry.register(SlackConnector())
    if os.environ.get("MATTEROS_JIRA_TOKEN") and os.environ.get("MATTEROS_JIRA_URL"):
        registry.register(JiraConnector())
    if os.environ.get("MATTEROS_GITHUB_TOKEN"):
        registry.register(GitHubConnector())

    if os.environ.get("MATTEROS_GOOGLE_TOKEN") or os.environ.get("MATTEROS_GOOGLE_CLIENT_ID"):
        from matteros.connectors.google_auth import GoogleTokenManager
        from matteros.connectors.google_calendar import GoogleCalendarConnector
        google_token_mgr = GoogleTokenManager(
            cache_path=(auth_cache_path.parent / "google_token.json") if auth_cache_path else None
        )
        registry.register(GoogleCalendarConnector(token_manager=google_token_mgr))

    if os.environ.get("MATTEROS_TOGGL_TOKEN"):
        from matteros.connectors.toggl import TogglConnector
        registry.register(TogglConnector())

    if os.environ.get("MATTEROS_GITLAW_REPO_DIR"):
        from matteros.connectors.gitlaw import GitlawConnector
        registry.register(GitlawConnector(repo_dir=Path(os.environ["MATTEROS_GITLAW_REPO_DIR"])))

    # iCal is always available (local file parsing, no auth needed).
    registry.register(ICalConnector())

    resolved_plugin_dir = (
        plugin_dir.expanduser()
        if plugin_dir is not None
        else resolved_auth_cache.parent.parent / "plugins"
    )
    register_plugins(registry, plugin_dir=resolved_plugin_dir)

    return registry
