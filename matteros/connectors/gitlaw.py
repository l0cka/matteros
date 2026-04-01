from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from matteros.connectors.base import Connector, ConnectorError
from matteros.core.types import ConnectorManifest, PermissionMode


def _validate_path(path: Path, root: Path) -> None:
    """Verify that *path* is contained within *root* and is not a symlink.

    Raises ConnectorError for symlinks or paths that resolve outside root.
    """
    if path.is_symlink():
        raise ConnectorError(f"symlinks are not allowed: {path}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ConnectorError(f"path escapes repository root: {path}")


class GitlawConnector(Connector):
    manifest = ConnectorManifest(
        connector_id="gitlaw",
        description="Read legal documents from a gitlaw-managed git repository",
        default_mode=PermissionMode.READ,
        operations={
            "documents": PermissionMode.READ,
            "document_detail": PermissionMode.READ,
            "audit_log": PermissionMode.READ,
            "reviews": PermissionMode.READ,
        },
    )

    def __init__(self, repo_dir: Path | None = None) -> None:
        if repo_dir is not None:
            self.repo_dir = Path(repo_dir)
        else:
            env_val = os.environ.get("MATTEROS_GITLAW_REPO_DIR", "")
            if not env_val:
                raise ConnectorError(
                    "gitlaw repo directory not configured. "
                    "Pass repo_dir or set MATTEROS_GITLAW_REPO_DIR."
                )
            self.repo_dir = Path(env_val)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def read(self, operation: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
        if operation == "documents":
            return self._read_documents(params)
        if operation in ("document_detail", "audit_log", "reviews"):
            raise ConnectorError(f"gitlaw operation not yet implemented: {operation}")
        raise ConnectorError(f"unsupported gitlaw read operation: {operation}")

    def write(self, operation: str, params: dict[str, Any], payload: Any, context: dict[str, Any]) -> Any:
        raise ConnectorError("gitlaw connector is read-only")

    # ------------------------------------------------------------------
    # documents operation
    # ------------------------------------------------------------------

    def _discover_documents(self) -> list[Path]:
        """Return non-symlink subdirectories of repo_dir that contain document.yaml."""
        docs: list[Path] = []
        for entry in sorted(self.repo_dir.iterdir()):
            if entry.is_symlink():
                continue
            if not entry.is_dir():
                continue
            if (entry / "document.yaml").exists():
                docs.append(entry)
        return docs

    def _parse_document(self, doc_dir: Path) -> dict[str, Any]:
        """Parse document.yaml and .gitlaw for a document directory."""
        doc_yaml = doc_dir / "document.yaml"
        _validate_path(doc_yaml, self.repo_dir)
        meta = yaml.safe_load(doc_yaml.read_text(encoding="utf-8")) or {}

        gitlaw_file = doc_dir / ".gitlaw"
        workflow_state: dict[str, Any] = {"current_reviewers": [], "approvals": []}
        if gitlaw_file.exists():
            _validate_path(gitlaw_file, self.repo_dir)
            tracking = yaml.safe_load(gitlaw_file.read_text(encoding="utf-8")) or {}
            workflow_state = tracking.get("workflow_state", workflow_state)

        return {
            "key": doc_dir.name,
            "title": meta.get("title", ""),
            "type": meta.get("type", ""),
            "status": meta.get("status", ""),
            "parties": meta.get("parties", []),
            "created": meta.get("created", ""),
            "sections": meta.get("sections", []),
            "workflow_state": workflow_state,
        }

    def _read_documents(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        status_filter = params.get("status")
        type_filter = params.get("type")

        results: list[dict[str, Any]] = []
        for doc_dir in self._discover_documents():
            doc = self._parse_document(doc_dir)
            if status_filter and doc["status"] != status_filter:
                continue
            if type_filter and doc["type"] != type_filter:
                continue
            results.append(doc)
        return results
