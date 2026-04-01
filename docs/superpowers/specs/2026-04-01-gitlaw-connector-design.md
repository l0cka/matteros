# gitlaw Connector Design

**Date:** 2026-04-01
**Scope:** Read-only MatterOS connector for gitlaw repositories. Write operations tracked as GitHub issues for future implementation.

## Summary

A single-file MatterOS connector that reads documents, audit logs, and reviews from a gitlaw-managed git repository. Documents are read via `pathlib` + `PyYAML`. Audit logs and reviews are read from git notes via `subprocess`. Audit events are normalized into MatterOS's activity format with duration hints derived from git commit timestamps.

## gitlaw Data Layout

gitlaw stores data in two places within a git repo:

**Document directories** (regular files):
```
some-contract/
  document.yaml    # YAML: title, type, status, parties, sections list
  .gitlaw          # YAML: signatures, audit_log_ref, workflow_state
  sections/
    recitals.md
    definitions.md
    ...
```

**Git notes** (git's notes mechanism, not regular files):
- `refs/notes/gitlaw-audit` — JSON array of `AuditEntry` objects (hash-chained via SHA-256)
- `refs/notes/gitlaw-reviews` — JSON with `requests` (document → ReviewRequest) and `reviews` (document → ReviewRecord[]) maps

Documents are discovered by scanning the repo root for directories containing `document.yaml`. No recursive scan — documents are top-level directories.

## Connector Manifest

```python
ConnectorManifest(
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
```

**Registration:** In `create_default_registry()` when `MATTEROS_GITLAW_REPO_DIR` is set. Same conditional pattern as Toggl, Slack, etc.

## Operations

### `documents` (read)

List all documents with metadata.

**Params:**
- `status` (optional): filter by document status (`draft`, `review`, `approved`, `finalised`, `archived`)
- `type` (optional): filter by document type (`contract`, `policy`, `brief`)
- `mock_file` (optional): path to JSON fixture

**Returns:** List of dicts:
```python
{
    "key": "some-contract",          # directory name
    "title": "Service Agreement",
    "type": "contract",
    "status": "review",
    "parties": [{"name": "Acme", "role": "client"}, ...],
    "created": "2026-03-15",
    "sections": [{"id": "recitals", "file": "sections/recitals.md"}, ...],
    "workflow_state": {
        "current_reviewers": ["alice"],
        "approvals": [],
    },
}
```

**Implementation:** Scan repo root for directories with `document.yaml`. Parse YAML. Parse `.gitlaw` for tracking/workflow state. Apply optional filters.

### `document_detail` (read)

Single document with full section content.

**Params:**
- `document` (required): directory name (key)
- `mock_file` (optional): path to JSON fixture

**Returns:** Same as `documents` item, plus:
```python
{
    ...,
    "section_contents": {
        "recitals": "# Recitals\n\nWHEREAS ...",
        "definitions": "# Definitions\n\n...",
    },
}
```

**Implementation:** Read `document.yaml`, `.gitlaw`, then read each `sections/*.md` file referenced in the sections list. Path traversal check: resolved section path must start with the document directory.

### `audit_log` (read)

gitlaw audit entries normalized into MatterOS activity format.

**Params:**
- `start` (optional): ISO datetime, filter events after this time
- `end` (optional): ISO datetime, filter events before this time
- `document` (optional): filter to a specific document key
- `mock_file` (optional): path to JSON fixture

**Returns:** List of normalized activity dicts:
```python
{
    "timestamp": "2026-03-20T14:30:00Z",
    "actor": "alice",
    "activity_type": "document_edit",      # normalized from gitlaw event type
    "matter_id": "some-contract",          # gitlaw document key
    "description": "section_modified",     # original gitlaw event type
    "metadata": {"section": "definitions"},# gitlaw details
    "evidence_refs": ["abc123"],           # git commit SHA
    "duration_hint_minutes": 25,           # estimated from commit gaps
}
```

**Event type mapping:**

| gitlaw event | MatterOS `activity_type` |
|---|---|
| `document_created` | `document_create` |
| `section_modified` | `document_edit` |
| `review_requested` | `review_request` |
| `review_decision` | `review_action` |
| `status_transition` | `status_change` |
| `signature_added` | `signature` |
| `document_exported` | `export` |
| `document_accessed` | `access` |

**Duration hint calculation:** Run `git log --format='%H %aI %an' -- <doc_dir>` to get commit timestamps per author per document. For each audit event, find the gap to the previous commit by the same author on the same document. Cap at 60 minutes (longer gaps assumed to be breaks). If no previous commit found, no duration hint.

**Implementation:** Read git notes from `refs/notes/gitlaw-audit` via `subprocess.run(["git", "notes", "--ref=refs/notes/gitlaw-audit", "show", "HEAD"], cwd=repo_dir)`. Parse JSON. Normalize each entry. Optionally run git log for duration hints. Apply time/document filters.

### `reviews` (read)

Pending and completed review requests with decisions.

**Params:**
- `status` (optional): `pending` or `completed`
- `mock_file` (optional): path to JSON fixture

**Returns:** List of dicts:
```python
{
    "document": "some-contract",
    "reviewers": ["alice", "bob"],
    "requester": "charlie",
    "commit": "abc123",
    "timestamp": "2026-03-20T10:00:00Z",
    "status": "pending",
    "decisions": [
        {
            "reviewer": "alice",
            "decision": "approved",
            "comment": "Looks good",
            "commit": "def456",
            "timestamp": "2026-03-20T15:00:00Z",
        },
    ],
}
```

**Implementation:** Read git notes from `refs/notes/gitlaw-reviews` via subprocess. Parse JSON. Merge requests with their review records. Apply status filter.

## Git Notes Reading

Both `audit_log` and `reviews` read from git notes via subprocess:

```python
result = subprocess.run(
    ["git", "notes", f"--ref={notes_ref}", "show", "HEAD"],
    cwd=repo_dir,
    capture_output=True,
    text=True,
    timeout=10,
)
```

If the command fails with "no note found" (exit code 1, stderr contains "no note found"), return empty data — not an error. This handles repos with no audit history.

## Mock Support

All operations accept a `mock_file` param pointing to a JSON fixture file, following the same pattern as Slack, Toggl, and other connectors. This enables testing without a real gitlaw repo.

## Configuration

Single env var: `MATTEROS_GITLAW_REPO_DIR` — absolute path to a gitlaw-managed git repository.

## File Structure

| Action | File |
|---|---|
| Create | `matteros/connectors/gitlaw.py` |
| Modify | `matteros/connectors/__init__.py` (register in `create_default_registry`) |
| Modify | `matteros/connectors/base.py` (add manifest to `default_manifests`) |
| Create | `tests/test_gitlaw_connector.py` |
| Create | `tests/fixtures/gitlaw/` (mock fixtures) |

## No New Dependencies

Uses `pathlib`, `subprocess`, `json` (stdlib) plus `PyYAML` (already a MatterOS dependency).

## Future: Write Operations

Write operations (review decisions, status transitions, new audit entries) are tracked as GitHub issues on the MatterOS repo for future implementation. The connector manifest will expand to include write operations when implemented. The read-only foundation (document discovery, git notes parsing, activity normalization) will be reused.
