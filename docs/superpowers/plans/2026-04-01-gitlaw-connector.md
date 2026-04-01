# gitlaw Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only MatterOS connector that reads documents, audit logs, and reviews from a gitlaw-managed git repository.

**Architecture:** Single connector file (`gitlaw.py`) reads documents via pathlib/YAML and audit/review data from git notes via subprocess. All filesystem reads are validated against the repo root. Activity normalization converts gitlaw events into MatterOS format with duration hints from git commit timestamps.

**Tech Stack:** Python 3, pathlib, subprocess, json, PyYAML (existing dep)

**Spec:** `docs/superpowers/specs/2026-04-01-gitlaw-connector-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `matteros/connectors/gitlaw.py` | Connector class with 4 read operations, path safety, git notes reading |
| Modify | `matteros/connectors/__init__.py` | Register GitlawConnector when env var set |
| Modify | `matteros/connectors/base.py` | Add gitlaw manifest to `default_manifests()` |
| Create | `tests/test_gitlaw_connector.py` | All connector tests |
| Create | `tests/fixtures/gitlaw/` | Test fixture directory structure |

---

### Task 1: Path Safety Helper and Test Fixtures

**Files:**
- Create: `matteros/connectors/gitlaw.py` (initial scaffolding)
- Create: `tests/test_gitlaw_connector.py`
- Create: `tests/fixtures/gitlaw/`

- [ ] **Step 1: Create test fixture directory structure**

Create the following files:

`tests/fixtures/gitlaw/sample-contract/document.yaml`:
```yaml
title: Service Agreement
type: contract
status: review
parties:
  - name: Acme Corp
    role: client
  - name: Legal Co
    role: provider
created: "2026-03-15"
sections:
  - id: recitals
    file: sections/recitals.md
  - id: definitions
    file: sections/definitions.md
```

`tests/fixtures/gitlaw/sample-contract/.gitlaw`:
```yaml
signatures: []
audit_log_ref: refs/notes/gitlaw-audit
workflow_state:
  current_reviewers:
    - alice
  approvals: []
```

`tests/fixtures/gitlaw/sample-contract/sections/recitals.md`:
```markdown
# Recitals

WHEREAS Acme Corp requires legal services...
```

`tests/fixtures/gitlaw/sample-contract/sections/definitions.md`:
```markdown
# Definitions

"Agreement" means this Service Agreement.
```

`tests/fixtures/gitlaw/draft-policy/document.yaml`:
```yaml
title: Data Retention Policy
type: policy
status: draft
parties: []
created: "2026-03-20"
sections:
  - id: scope
    file: sections/scope.md
```

`tests/fixtures/gitlaw/draft-policy/.gitlaw`:
```yaml
signatures: []
audit_log_ref: refs/notes/gitlaw-audit
workflow_state:
  current_reviewers: []
  approvals: []
```

`tests/fixtures/gitlaw/draft-policy/sections/scope.md`:
```markdown
# Scope

This policy applies to all data retention activities.
```

- [ ] **Step 2: Write failing tests for path safety**

Create `tests/test_gitlaw_connector.py`:

```python
"""Tests for gitlaw connector."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from matteros.connectors.base import ConnectorError


def test_validate_path_accepts_valid_path(tmp_path: Path) -> None:
    from matteros.connectors.gitlaw import _validate_path

    root = tmp_path / "repo"
    root.mkdir()
    child = root / "doc" / "file.yaml"
    child.parent.mkdir(parents=True)
    child.touch()

    result = _validate_path(child, root)
    assert result == child.resolve()


def test_validate_path_rejects_escape(tmp_path: Path) -> None:
    from matteros.connectors.gitlaw import _validate_path

    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.touch()

    with pytest.raises(ConnectorError, match="path escapes repo root"):
        _validate_path(outside, root)


def test_validate_path_rejects_symlink(tmp_path: Path) -> None:
    from matteros.connectors.gitlaw import _validate_path

    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "secret.txt"
    target.write_text("secret")
    link = root / "sneaky"
    link.symlink_to(target)

    with pytest.raises(ConnectorError, match="symlinked paths not allowed"):
        _validate_path(link, root)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "validate_path" 2>&1 | head -20`

Expected: FAIL — `_validate_path` not defined

- [ ] **Step 4: Create initial `gitlaw.py` with path safety and manifest**

Create `matteros/connectors/gitlaw.py`:

```python
"""Read-only connector for gitlaw-managed git repositories."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

from matteros.connectors.base import Connector, ConnectorError
from matteros.core.types import ConnectorManifest, PermissionMode


def _validate_path(path: Path, root: Path) -> Path:
    """Resolve path and verify it's contained within root."""
    resolved = path.resolve()
    root_resolved = root.resolve()
    if not str(resolved).startswith(str(root_resolved) + "/") and resolved != root_resolved:
        raise ConnectorError(f"path escapes repo root: {path}")
    if path.is_symlink():
        raise ConnectorError(f"symlinked paths not allowed: {path}")
    return resolved


class GitlawConnector(Connector):
    manifest = ConnectorManifest(
        connector_id="gitlaw",
        description="Read documents, reviews, and audit events from a gitlaw repository",
        default_mode=PermissionMode.READ,
        operations={
            "documents": PermissionMode.READ,
            "document_detail": PermissionMode.READ,
            "audit_log": PermissionMode.READ,
            "reviews": PermissionMode.READ,
        },
    )

    def __init__(self, repo_dir: Path | None = None) -> None:
        self.repo_dir = (
            repo_dir
            or Path(os.environ.get("MATTEROS_GITLAW_REPO_DIR", ""))
        )

    def read(self, operation: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
        raise NotImplementedError(f"gitlaw read not yet implemented: {operation}")

    def write(self, operation: str, params: dict[str, Any], payload: Any, context: dict[str, Any]) -> Any:
        raise ConnectorError("gitlaw connector is read-only")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "validate_path" 2>&1 | tail -10`

Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/connectors/gitlaw.py tests/test_gitlaw_connector.py tests/fixtures/gitlaw/
git commit -m "feat(gitlaw): add connector scaffold with path safety and test fixtures"
```

---

### Task 2: Document Discovery and `documents` Operation

**Files:**
- Modify: `matteros/connectors/gitlaw.py`
- Modify: `tests/test_gitlaw_connector.py`

- [ ] **Step 1: Write failing tests for document discovery**

Add to `tests/test_gitlaw_connector.py`:

```python
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "gitlaw"


def test_read_documents_lists_all(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    docs = connector.read("documents", {}, {})

    assert len(docs) == 2
    keys = {d["key"] for d in docs}
    assert keys == {"sample-contract", "draft-policy"}


def test_read_documents_filter_by_status(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    docs = connector.read("documents", {"status": "draft"}, {})

    assert len(docs) == 1
    assert docs[0]["key"] == "draft-policy"


def test_read_documents_filter_by_type(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    docs = connector.read("documents", {"type": "contract"}, {})

    assert len(docs) == 1
    assert docs[0]["title"] == "Service Agreement"


def test_read_documents_includes_workflow_state(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    docs = connector.read("documents", {}, {})

    contract = next(d for d in docs if d["key"] == "sample-contract")
    assert contract["workflow_state"]["current_reviewers"] == ["alice"]


def test_read_documents_rejects_symlinked_dir(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)

    # Create a symlinked document directory pointing outside repo
    outside = tmp_path / "outside_doc"
    outside.mkdir()
    (outside / "document.yaml").write_text("title: Evil\ntype: contract\nstatus: draft\nparties: []\ncreated: '2026-01-01'\nsections: []\n")
    (repo / "evil-link").symlink_to(outside)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    docs = connector.read("documents", {}, {})

    # The symlinked dir should be silently skipped, not included
    keys = {d["key"] for d in docs}
    assert "evil-link" not in keys
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "read_documents" 2>&1 | head -20`

Expected: FAIL — `read` raises `NotImplementedError`

- [ ] **Step 3: Implement document discovery**

In `matteros/connectors/gitlaw.py`, add a `_discover_documents` method and wire it into `read`:

```python
def _discover_documents(self) -> list[dict[str, Any]]:
    """Scan repo root for directories containing document.yaml."""
    repo_root = self.repo_dir.resolve()
    documents = []
    for child in self.repo_dir.iterdir():
        if not child.is_dir():
            continue
        # Skip symlinked directories
        if child.is_symlink():
            continue
        doc_yaml = child / "document.yaml"
        if not doc_yaml.exists():
            continue
        try:
            _validate_path(child, self.repo_dir)
            _validate_path(doc_yaml, self.repo_dir)
        except ConnectorError:
            continue

        meta = yaml.safe_load(doc_yaml.read_text(encoding="utf-8"))

        tracking_file = child / ".gitlaw"
        workflow_state = {"current_reviewers": [], "approvals": []}
        if tracking_file.exists():
            try:
                _validate_path(tracking_file, self.repo_dir)
                tracking = yaml.safe_load(tracking_file.read_text(encoding="utf-8"))
                workflow_state = tracking.get("workflow_state", workflow_state)
            except ConnectorError:
                pass

        documents.append({
            "key": child.name,
            "title": meta.get("title", ""),
            "type": meta.get("type", ""),
            "status": meta.get("status", ""),
            "parties": meta.get("parties", []),
            "created": meta.get("created", ""),
            "sections": meta.get("sections", []),
            "workflow_state": workflow_state,
        })
    return documents
```

Update `read` method:

```python
def read(self, operation: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
    if operation == "documents":
        return self._read_documents(params)
    raise ConnectorError(f"unsupported gitlaw read operation: {operation}")

def _read_documents(self, params: dict[str, Any]) -> list[dict[str, Any]]:
    docs = self._discover_documents()
    status_filter = params.get("status")
    if status_filter:
        docs = [d for d in docs if d["status"] == status_filter]
    type_filter = params.get("type")
    if type_filter:
        docs = [d for d in docs if d["type"] == type_filter]
    return docs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "read_documents" 2>&1 | tail -15`

Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/connectors/gitlaw.py tests/test_gitlaw_connector.py
git commit -m "feat(gitlaw): implement documents operation with path-safe discovery"
```

---

### Task 3: `document_detail` Operation

**Files:**
- Modify: `matteros/connectors/gitlaw.py`
- Modify: `tests/test_gitlaw_connector.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_gitlaw_connector.py`:

```python
def test_read_document_detail(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    detail = connector.read("document_detail", {"document": "sample-contract"}, {})

    assert detail["key"] == "sample-contract"
    assert detail["title"] == "Service Agreement"
    assert "recitals" in detail["section_contents"]
    assert "WHEREAS" in detail["section_contents"]["recitals"]
    assert "definitions" in detail["section_contents"]


def test_read_document_detail_unknown_doc(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)

    with pytest.raises(ConnectorError, match="document not found"):
        connector.read("document_detail", {"document": "nonexistent"}, {})


def test_read_document_detail_rejects_traversal_section(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    doc_dir = repo / "evil-doc"
    doc_dir.mkdir(parents=True)
    sections_dir = doc_dir / "sections"
    sections_dir.mkdir()
    (sections_dir / "ok.md").write_text("safe content")

    # Write document.yaml with a path-traversal section reference
    (doc_dir / "document.yaml").write_text(
        "title: Evil\ntype: contract\nstatus: draft\nparties: []\n"
        "created: '2026-01-01'\nsections:\n- id: escape\n  file: ../../etc/passwd\n"
    )
    (doc_dir / ".gitlaw").write_text(
        "signatures: []\naudit_log_ref: refs/notes/gitlaw-audit\n"
        "workflow_state:\n  current_reviewers: []\n  approvals: []\n"
    )

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)

    with pytest.raises(ConnectorError, match="path escapes repo root"):
        connector.read("document_detail", {"document": "evil-doc"}, {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "document_detail" 2>&1 | head -15`

Expected: FAIL

- [ ] **Step 3: Implement `document_detail`**

Add to `GitlawConnector` in `gitlaw.py`:

```python
def _read_document_detail(self, params: dict[str, Any]) -> dict[str, Any]:
    doc_key = params.get("document")
    if not doc_key:
        raise ConnectorError("document_detail requires a 'document' param")

    doc_dir = self.repo_dir / doc_key
    if not doc_dir.exists() or not doc_dir.is_dir():
        raise ConnectorError(f"document not found: {doc_key}")
    _validate_path(doc_dir, self.repo_dir)

    doc_yaml = doc_dir / "document.yaml"
    if not doc_yaml.exists():
        raise ConnectorError(f"document not found: {doc_key}")
    _validate_path(doc_yaml, self.repo_dir)

    meta = yaml.safe_load(doc_yaml.read_text(encoding="utf-8"))

    tracking_file = doc_dir / ".gitlaw"
    workflow_state = {"current_reviewers": [], "approvals": []}
    if tracking_file.exists():
        _validate_path(tracking_file, self.repo_dir)
        tracking = yaml.safe_load(tracking_file.read_text(encoding="utf-8"))
        workflow_state = tracking.get("workflow_state", workflow_state)

    section_contents: dict[str, str] = {}
    for section_ref in meta.get("sections", []):
        section_file = doc_dir / section_ref["file"]
        _validate_path(section_file, self.repo_dir)
        section_contents[section_ref["id"]] = section_file.read_text(encoding="utf-8")

    return {
        "key": doc_key,
        "title": meta.get("title", ""),
        "type": meta.get("type", ""),
        "status": meta.get("status", ""),
        "parties": meta.get("parties", []),
        "created": meta.get("created", ""),
        "sections": meta.get("sections", []),
        "workflow_state": workflow_state,
        "section_contents": section_contents,
    }
```

Update `read` method to dispatch `document_detail`:

```python
def read(self, operation: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
    if operation == "documents":
        return self._read_documents(params)
    if operation == "document_detail":
        return self._read_document_detail(params)
    raise ConnectorError(f"unsupported gitlaw read operation: {operation}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "document_detail" 2>&1 | tail -10`

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/connectors/gitlaw.py tests/test_gitlaw_connector.py
git commit -m "feat(gitlaw): implement document_detail operation with section reading"
```

---

### Task 4: Git Notes Reading and `audit_log` Operation

**Files:**
- Modify: `matteros/connectors/gitlaw.py`
- Modify: `tests/test_gitlaw_connector.py`

- [ ] **Step 1: Write failing tests for git notes and audit_log**

Add to `tests/test_gitlaw_connector.py`:

```python
import json
import subprocess


def _init_git_repo(repo_dir: Path) -> None:
    """Initialize a git repo and make an initial commit."""
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, capture_output=True, check=True)


def _write_audit_notes(repo_dir: Path, entries: list[dict]) -> None:
    """Write audit entries as a git note on HEAD."""
    data = json.dumps(entries)
    subprocess.run(
        ["git", "notes", "--ref=refs/notes/gitlaw-audit", "add", "-f", "-m", data, "HEAD"],
        cwd=repo_dir, capture_output=True, check=True,
    )


def test_read_audit_log_returns_normalized_entries(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)
    _init_git_repo(repo)

    entries = [
        {
            "id": "abc123",
            "prev": None,
            "timestamp": "2026-03-20T14:30:00Z",
            "actor": "alice",
            "event": "section_modified",
            "document": "sample-contract",
            "commit": "deadbeef",
            "details": {"section": "definitions"},
        },
    ]
    _write_audit_notes(repo, entries)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    activities = connector.read("audit_log", {}, {})

    assert len(activities) == 1
    act = activities[0]
    assert act["timestamp"] == "2026-03-20T14:30:00Z"
    assert act["actor"] == "alice"
    assert act["activity_type"] == "document_edit"
    assert act["matter_id"] == "sample-contract"
    assert act["description"] == "section_modified"
    assert "deadbeef" in act["evidence_refs"]


def test_read_audit_log_filters_by_document(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)
    _init_git_repo(repo)

    entries = [
        {"id": "a1", "prev": None, "timestamp": "2026-03-20T10:00:00Z", "actor": "alice", "event": "section_modified", "document": "sample-contract", "commit": "c1", "details": {}},
        {"id": "a2", "prev": "a1", "timestamp": "2026-03-20T11:00:00Z", "actor": "bob", "event": "document_created", "document": "draft-policy", "commit": "c2", "details": {}},
    ]
    _write_audit_notes(repo, entries)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    activities = connector.read("audit_log", {"document": "sample-contract"}, {})

    assert len(activities) == 1
    assert activities[0]["matter_id"] == "sample-contract"


def test_read_audit_log_empty_when_no_notes(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)
    _init_git_repo(repo)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    activities = connector.read("audit_log", {}, {})

    assert activities == []


def test_read_audit_log_rejects_detached_head(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)
    _init_git_repo(repo)

    # Detach HEAD
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", "checkout", head], cwd=repo, capture_output=True, check=True)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)

    with pytest.raises(ConnectorError, match="detached HEAD"):
        connector.read("audit_log", {}, {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "audit_log" 2>&1 | head -20`

Expected: FAIL

- [ ] **Step 3: Implement git notes reading and audit_log normalization**

Add to `GitlawConnector` in `gitlaw.py`:

```python
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
```

Add these methods to the class:

```python
def _validate_repo_state(self) -> None:
    """Verify the repo is not in detached HEAD state."""
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=self.repo_dir,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ConnectorError("gitlaw repo is in detached HEAD state — audit/review data may be stale")

def _read_git_notes(self, notes_ref: str) -> str | None:
    """Read git notes from a ref. Returns None if no notes exist."""
    self._validate_repo_state()
    result = subprocess.run(
        ["git", "notes", f"--ref={notes_ref}", "show", "HEAD"],
        cwd=self.repo_dir,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        if "no note found" in result.stderr:
            return None
        raise ConnectorError(f"git notes read failed: {result.stderr.strip()}")
    return result.stdout

def _read_audit_log(self, params: dict[str, Any]) -> list[dict[str, Any]]:
    raw = self._read_git_notes(AUDIT_NOTES_REF)
    if not raw:
        return []

    entries = json.loads(raw)
    activities = []
    for entry in entries:
        gitlaw_event = entry.get("event", "")
        activity = {
            "timestamp": entry.get("timestamp", ""),
            "actor": entry.get("actor", ""),
            "activity_type": EVENT_TYPE_MAP.get(gitlaw_event, gitlaw_event),
            "matter_id": entry.get("document", ""),
            "description": gitlaw_event,
            "metadata": entry.get("details", {}),
            "evidence_refs": [entry["commit"]] if entry.get("commit") else [],
            "duration_hint_minutes": None,
        }
        activities.append(activity)

    # Apply filters
    doc_filter = params.get("document")
    if doc_filter:
        activities = [a for a in activities if a["matter_id"] == doc_filter]

    start = params.get("start")
    if start:
        activities = [a for a in activities if a["timestamp"] >= start]

    end = params.get("end")
    if end:
        activities = [a for a in activities if a["timestamp"] <= end]

    return activities
```

Update `read` method:

```python
def read(self, operation: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
    if operation == "documents":
        return self._read_documents(params)
    if operation == "document_detail":
        return self._read_document_detail(params)
    if operation == "audit_log":
        return self._read_audit_log(params)
    raise ConnectorError(f"unsupported gitlaw read operation: {operation}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "audit_log" 2>&1 | tail -15`

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/connectors/gitlaw.py tests/test_gitlaw_connector.py
git commit -m "feat(gitlaw): implement audit_log operation with git notes and activity normalization"
```

---

### Task 5: Duration Hints from Git Log

**Files:**
- Modify: `matteros/connectors/gitlaw.py`
- Modify: `tests/test_gitlaw_connector.py`

- [ ] **Step 1: Write failing test for duration hints**

Add to `tests/test_gitlaw_connector.py`:

```python
def test_audit_log_includes_duration_hints(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)
    _init_git_repo(repo)

    # Make a second commit 25 minutes later on the sample-contract dir
    (repo / "sample-contract" / "sections" / "recitals.md").write_text("# Updated recitals")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "edit recitals", "--date=2026-03-20T14:25:00+00:00"],
        cwd=repo, capture_output=True, check=True,
        env={**os.environ, "GIT_COMMITTER_DATE": "2026-03-20T14:25:00+00:00"},
    )

    # Make a third commit 30 minutes after that
    (repo / "sample-contract" / "sections" / "definitions.md").write_text("# Updated defs")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "edit defs", "--date=2026-03-20T14:55:00+00:00"],
        cwd=repo, capture_output=True, check=True,
        env={**os.environ, "GIT_COMMITTER_DATE": "2026-03-20T14:55:00+00:00"},
    )

    entries = [
        {"id": "a1", "prev": None, "timestamp": "2026-03-20T14:25:00Z", "actor": "Test", "event": "section_modified", "document": "sample-contract", "commit": "c1", "details": {}},
        {"id": "a2", "prev": "a1", "timestamp": "2026-03-20T14:55:00Z", "actor": "Test", "event": "section_modified", "document": "sample-contract", "commit": "c2", "details": {}},
    ]
    _write_audit_notes(repo, entries)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    activities = connector.read("audit_log", {}, {})

    # Second activity should have a duration hint of 30 minutes
    assert activities[1]["duration_hint_minutes"] == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py::test_audit_log_includes_duration_hints -v 2>&1 | tail -10`

Expected: FAIL — `duration_hint_minutes` is None

- [ ] **Step 3: Implement duration hint calculation**

Add to `GitlawConnector`:

```python
def _get_commit_timestamps(self, document: str) -> list[tuple[str, str, str]]:
    """Get (commit_hash, iso_timestamp, author) tuples from git log for a document dir."""
    doc_dir = self.repo_dir / document
    if not doc_dir.exists():
        return []
    result = subprocess.run(
        ["git", "log", "--format=%H %aI %an", "--", document],
        cwd=self.repo_dir,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return []
    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(" ", 2)
        if len(parts) == 3:
            entries.append((parts[0], parts[1], parts[2]))
    return entries

def _compute_duration_hints(self, activities: list[dict[str, Any]]) -> None:
    """Compute duration_hint_minutes for each activity from git commit gaps."""
    # Collect all documents referenced
    documents = {a["matter_id"] for a in activities if a["matter_id"]}

    # Build per-document, per-author timeline from git log
    # Key: (document, author) -> sorted list of ISO timestamps
    timelines: dict[tuple[str, str], list[str]] = {}
    for doc in documents:
        commits = self._get_commit_timestamps(doc)
        for _, ts, author in commits:
            key = (doc, author)
            if key not in timelines:
                timelines[key] = []
            timelines[key].append(ts)

    # Sort each timeline
    for key in timelines:
        timelines[key].sort()

    # For each activity, find the gap to the previous commit by same author on same doc
    from datetime import datetime, timezone
    for activity in activities:
        doc = activity["matter_id"]
        actor = activity["actor"]
        ts_str = activity["timestamp"]
        key = (doc, actor)
        timeline = timelines.get(key, [])
        if len(timeline) < 2:
            continue

        # Find the closest previous timestamp
        try:
            activity_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        prev_dt = None
        for t in timeline:
            try:
                t_dt = datetime.fromisoformat(t)
            except ValueError:
                continue
            if t_dt < activity_dt:
                prev_dt = t_dt
            else:
                break

        if prev_dt:
            gap_minutes = int((activity_dt - prev_dt).total_seconds() / 60)
            if 0 < gap_minutes <= 60:
                activity["duration_hint_minutes"] = gap_minutes
```

Update `_read_audit_log` to call duration hints after normalization but before filtering:

```python
def _read_audit_log(self, params: dict[str, Any]) -> list[dict[str, Any]]:
    raw = self._read_git_notes(AUDIT_NOTES_REF)
    if not raw:
        return []

    entries = json.loads(raw)
    activities = []
    for entry in entries:
        gitlaw_event = entry.get("event", "")
        activity = {
            "timestamp": entry.get("timestamp", ""),
            "actor": entry.get("actor", ""),
            "activity_type": EVENT_TYPE_MAP.get(gitlaw_event, gitlaw_event),
            "matter_id": entry.get("document", ""),
            "description": gitlaw_event,
            "metadata": entry.get("details", {}),
            "evidence_refs": [entry["commit"]] if entry.get("commit") else [],
            "duration_hint_minutes": None,
        }
        activities.append(activity)

    self._compute_duration_hints(activities)

    # Apply filters
    doc_filter = params.get("document")
    if doc_filter:
        activities = [a for a in activities if a["matter_id"] == doc_filter]
    start = params.get("start")
    if start:
        activities = [a for a in activities if a["timestamp"] >= start]
    end = params.get("end")
    if end:
        activities = [a for a in activities if a["timestamp"] <= end]

    return activities
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "audit_log" 2>&1 | tail -15`

Expected: 5 PASS (4 previous + 1 new)

- [ ] **Step 5: Commit**

```bash
git add matteros/connectors/gitlaw.py tests/test_gitlaw_connector.py
git commit -m "feat(gitlaw): add duration hints from git commit timestamps"
```

---

### Task 6: `reviews` Operation

**Files:**
- Modify: `matteros/connectors/gitlaw.py`
- Modify: `tests/test_gitlaw_connector.py`

- [ ] **Step 1: Write failing tests for reviews**

Add to `tests/test_gitlaw_connector.py`:

```python
def _write_review_notes(repo_dir: Path, data: dict) -> None:
    """Write review data as a git note on HEAD."""
    raw = json.dumps(data)
    subprocess.run(
        ["git", "notes", "--ref=refs/notes/gitlaw-reviews", "add", "-f", "-m", raw, "HEAD"],
        cwd=repo_dir, capture_output=True, check=True,
    )


def test_read_reviews_returns_merged_data(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)
    _init_git_repo(repo)

    review_data = {
        "requests": [
            ["sample-contract", {
                "document": "sample-contract",
                "reviewers": ["alice", "bob"],
                "requester": "charlie",
                "commit": "abc123",
                "timestamp": "2026-03-20T10:00:00Z",
                "status": "pending",
            }],
        ],
        "reviews": [
            ["sample-contract", [
                {
                    "document": "sample-contract",
                    "reviewer": "alice",
                    "decision": "approved",
                    "comment": "Looks good",
                    "commit": "def456",
                    "timestamp": "2026-03-20T15:00:00Z",
                },
            ]],
        ],
    }
    _write_review_notes(repo, review_data)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    reviews = connector.read("reviews", {}, {})

    assert len(reviews) == 1
    r = reviews[0]
    assert r["document"] == "sample-contract"
    assert r["reviewers"] == ["alice", "bob"]
    assert r["status"] == "pending"
    assert len(r["decisions"]) == 1
    assert r["decisions"][0]["reviewer"] == "alice"
    assert r["decisions"][0]["decision"] == "approved"


def test_read_reviews_filter_by_status(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)
    _init_git_repo(repo)

    review_data = {
        "requests": [
            ["doc-a", {"document": "doc-a", "reviewers": ["alice"], "requester": "bob", "commit": "c1", "timestamp": "2026-03-20T10:00:00Z", "status": "pending"}],
            ["doc-b", {"document": "doc-b", "reviewers": ["alice"], "requester": "bob", "commit": "c2", "timestamp": "2026-03-20T11:00:00Z", "status": "completed"}],
        ],
        "reviews": [],
    }
    _write_review_notes(repo, review_data)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)

    pending = connector.read("reviews", {"status": "pending"}, {})
    assert len(pending) == 1
    assert pending[0]["document"] == "doc-a"


def test_read_reviews_empty_when_no_notes(tmp_path: Path) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)
    _init_git_repo(repo)

    from matteros.connectors.gitlaw import GitlawConnector
    connector = GitlawConnector(repo_dir=repo)
    reviews = connector.read("reviews", {}, {})

    assert reviews == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "read_reviews" 2>&1 | head -15`

Expected: FAIL

- [ ] **Step 3: Implement `_read_reviews`**

Add to `GitlawConnector`:

```python
def _read_reviews(self, params: dict[str, Any]) -> list[dict[str, Any]]:
    raw = self._read_git_notes(REVIEW_NOTES_REF)
    if not raw:
        return []

    data = json.loads(raw)
    requests_list = data.get("requests", [])
    reviews_map = dict(data.get("reviews", []))

    results = []
    for doc_key, request in requests_list:
        decisions = reviews_map.get(doc_key, [])
        results.append({
            "document": request.get("document", doc_key),
            "reviewers": request.get("reviewers", []),
            "requester": request.get("requester", ""),
            "commit": request.get("commit", ""),
            "timestamp": request.get("timestamp", ""),
            "status": request.get("status", ""),
            "decisions": decisions,
        })

    status_filter = params.get("status")
    if status_filter:
        results = [r for r in results if r["status"] == status_filter]

    return results
```

Update `read` method:

```python
def read(self, operation: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
    if operation == "documents":
        return self._read_documents(params)
    if operation == "document_detail":
        return self._read_document_detail(params)
    if operation == "audit_log":
        return self._read_audit_log(params)
    if operation == "reviews":
        return self._read_reviews(params)
    raise ConnectorError(f"unsupported gitlaw read operation: {operation}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "read_reviews" 2>&1 | tail -10`

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/connectors/gitlaw.py tests/test_gitlaw_connector.py
git commit -m "feat(gitlaw): implement reviews operation with git notes"
```

---

### Task 7: Register Connector and Add Manifest

**Files:**
- Modify: `matteros/connectors/__init__.py`
- Modify: `matteros/connectors/base.py`
- Modify: `tests/test_gitlaw_connector.py`

- [ ] **Step 1: Write failing test for registration**

Add to `tests/test_gitlaw_connector.py`:

```python
def test_connector_registered_when_env_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo)

    monkeypatch.setenv("MATTEROS_GITLAW_REPO_DIR", str(repo))

    from matteros.connectors import create_default_registry
    registry = create_default_registry()
    manifests = registry.manifests()

    assert "gitlaw" in manifests
    assert manifests["gitlaw"].operations == {
        "documents": PermissionMode.READ,
        "document_detail": PermissionMode.READ,
        "audit_log": PermissionMode.READ,
        "reviews": PermissionMode.READ,
    }


def test_connector_not_registered_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MATTEROS_GITLAW_REPO_DIR", raising=False)

    from matteros.connectors import create_default_registry
    registry = create_default_registry()
    manifests = registry.manifests()

    assert "gitlaw" not in manifests
```

Add import at top of test file:

```python
from matteros.core.types import PermissionMode
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "registered" 2>&1 | head -15`

Expected: FAIL — gitlaw not in registry

- [ ] **Step 3: Register in `__init__.py`**

Add to `matteros/connectors/__init__.py`, after the Toggl block and before the iCal registration:

```python
if os.environ.get("MATTEROS_GITLAW_REPO_DIR"):
    from matteros.connectors.gitlaw import GitlawConnector
    registry.register(GitlawConnector(repo_dir=Path(os.environ["MATTEROS_GITLAW_REPO_DIR"])))
```

- [ ] **Step 4: Add manifest to `default_manifests()` in `base.py`**

Add to the `default_manifests()` function in `matteros/connectors/base.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gitlaw_connector.py -v -k "registered" 2>&1 | tail -10`

Expected: 2 PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ 2>&1 | tail -5`

Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add matteros/connectors/__init__.py matteros/connectors/base.py tests/test_gitlaw_connector.py
git commit -m "feat(gitlaw): register connector in default registry when env var set"
```
