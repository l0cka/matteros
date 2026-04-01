from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

from matteros.connectors.base import Connector, ConnectorError
from matteros.core.types import ConnectorManifest, PermissionMode

AUDIT_NOTES_REF = "refs/notes/gitlaw-audit"
REVIEW_NOTES_REF = "refs/notes/gitlaw-reviews"

EVENT_TYPE_MAP: dict[str, str] = {
    "document_created": "document_create",
    "section_modified": "document_edit",
    "review_requested": "review_request",
    "review_decision": "review_action",
    "status_transition": "status_change",
    "signature_added": "signature",
    "document_exported": "export",
    "document_accessed": "access",
}


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
        if operation == "document_detail":
            return self._read_document_detail(params)
        if operation == "audit_log":
            return self._read_audit_log(params)
        if operation == "reviews":
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

    # ------------------------------------------------------------------
    # document_detail operation
    # ------------------------------------------------------------------

    def _read_document_detail(self, params: dict[str, Any]) -> dict[str, Any]:
        document_key = params.get("document", "")
        if not document_key:
            raise ConnectorError("document parameter is required")

        doc_dir = self.repo_dir / document_key
        if doc_dir.is_symlink() or not doc_dir.is_dir():
            raise ConnectorError(f"document not found: {document_key}")

        _validate_path(doc_dir, self.repo_dir)

        doc_yaml = doc_dir / "document.yaml"
        if not doc_yaml.exists():
            raise ConnectorError(f"document not found: {document_key}")

        doc = self._parse_document(doc_dir)

        section_contents: dict[str, str] = {}
        for section in doc["sections"]:
            sec_id = section.get("id", "")
            sec_file = section.get("file", "")
            if not sec_file:
                continue
            sec_path = doc_dir / sec_file
            _validate_path(sec_path, self.repo_dir)
            if sec_path.exists():
                section_contents[sec_id] = sec_path.read_text(encoding="utf-8")

        doc["section_contents"] = section_contents
        return doc

    # ------------------------------------------------------------------
    # audit_log operation
    # ------------------------------------------------------------------

    def _validate_repo_state(self) -> None:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ConnectorError(
                "gitlaw repo is in detached HEAD state — audit/review data may be stale"
            )

    def _read_git_notes(self, notes_ref: str) -> str | None:
        self._validate_repo_state()
        result = subprocess.run(
            ["git", "notes", f"--ref={notes_ref}", "show", "HEAD"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
        if "no note found" in result.stderr:
            return None
        raise ConnectorError(f"failed to read git notes: {result.stderr}")

    def _read_audit_log(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        raw = self._read_git_notes(AUDIT_NOTES_REF)
        if raw is None:
            return []

        entries = json.loads(raw)
        activities: list[dict[str, Any]] = []
        for entry in entries:
            event = entry.get("event", "")
            activities.append({
                "timestamp": entry["timestamp"],
                "actor": entry["actor"],
                "activity_type": EVENT_TYPE_MAP.get(event, event),
                "matter_id": entry["document"],
                "description": event,
                "metadata": entry.get("details", {}),
                "evidence_refs": [entry["commit"]] if entry.get("commit") else [],
                "duration_hint_minutes": None,
            })

        # Apply filters
        doc_filter = params.get("document")
        start_filter = params.get("start")
        end_filter = params.get("end")

        if doc_filter:
            activities = [a for a in activities if a["matter_id"] == doc_filter]
        if start_filter:
            activities = [a for a in activities if a["timestamp"] >= start_filter]
        if end_filter:
            activities = [a for a in activities if a["timestamp"] <= end_filter]

        return activities
