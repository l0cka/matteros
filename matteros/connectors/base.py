from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from matteros.core.types import ConnectorManifest, PermissionMode


class ConnectorError(Exception):
    """Raised for connector failures."""


class Connector(ABC):
    manifest: ConnectorManifest

    @abstractmethod
    def read(self, operation: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    def write(self, operation: str, params: dict[str, Any], payload: Any, context: dict[str, Any]) -> Any:
        raise NotImplementedError


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.manifest.connector_id] = connector

    def get(self, connector_id: str) -> Connector:
        connector = self._connectors.get(connector_id)
        if connector is None:
            raise ConnectorError(f"unknown connector: {connector_id}")
        return connector

    def manifests(self) -> dict[str, ConnectorManifest]:
        return {cid: connector.manifest for cid, connector in self._connectors.items()}

    def list(self) -> list[ConnectorManifest]:
        return list(self.manifests().values())


def default_manifests() -> dict[str, ConnectorManifest]:
    return {
        "ms_graph_mail": ConnectorManifest(
            connector_id="ms_graph_mail",
            description="Read sent messages from Microsoft Graph",
            default_mode=PermissionMode.READ,
            operations={"sent_emails": PermissionMode.READ},
        ),
        "ms_graph_calendar": ConnectorManifest(
            connector_id="ms_graph_calendar",
            description="Read calendar events from Microsoft Graph",
            default_mode=PermissionMode.READ,
            operations={"events": PermissionMode.READ},
        ),
        "filesystem": ConnectorManifest(
            connector_id="filesystem",
            description="Read file metadata from local workspace",
            default_mode=PermissionMode.READ,
            operations={"activity_metadata": PermissionMode.READ},
        ),
        "csv_export": ConnectorManifest(
            connector_id="csv_export",
            description="Write approved entries to local CSV",
            default_mode=PermissionMode.WRITE,
            operations={"export_time_entries": PermissionMode.WRITE},
        ),
        "slack": ConnectorManifest(
            connector_id="slack",
            description="Read and post messages via Slack Web API",
            default_mode=PermissionMode.READ,
            operations={
                "messages": PermissionMode.READ,
                "post_summary": PermissionMode.WRITE,
            },
        ),
        "jira": ConnectorManifest(
            connector_id="jira",
            description="Read worklogs/issues and log time via Jira REST API",
            default_mode=PermissionMode.READ,
            operations={
                "worklogs": PermissionMode.READ,
                "issues": PermissionMode.READ,
                "log_time": PermissionMode.WRITE,
            },
        ),
        "github": ConnectorManifest(
            connector_id="github",
            description="Read commits and pull requests from GitHub API",
            default_mode=PermissionMode.READ,
            operations={
                "commits": PermissionMode.READ,
                "prs": PermissionMode.READ,
            },
        ),
        "ical": ConnectorManifest(
            connector_id="ical",
            description="Read events from local iCal (.ics) files",
            default_mode=PermissionMode.READ,
            operations={"events": PermissionMode.READ},
        ),
        "gitlaw": ConnectorManifest(
            connector_id="gitlaw",
            description="Read documents, reviews, and audit events from a gitlaw repository",
            default_mode=PermissionMode.READ,
            operations={
                "documents": PermissionMode.READ,
                "document_detail": PermissionMode.READ,
                "audit_log": PermissionMode.READ,
                "reviews": PermissionMode.READ,
            },
        ),
    }


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
