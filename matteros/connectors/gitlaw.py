from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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

    def read(self, operation: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
        raise ConnectorError(f"unsupported gitlaw read operation: {operation}")

    def write(self, operation: str, params: dict[str, Any], payload: Any, context: dict[str, Any]) -> Any:
        raise ConnectorError("gitlaw connector is read-only")
