from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from matteros.connectors.base import ConnectorError
from matteros.connectors.gitlaw import GitlawConnector, _validate_path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "gitlaw"


# ---------------------------------------------------------------------------
# Task 1: _validate_path tests
# ---------------------------------------------------------------------------


def test_validate_path_accepts_valid_path(tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "file.txt"
    target.parent.mkdir(parents=True)
    target.write_text("hello")
    # Should not raise
    _validate_path(target, tmp_path)


def test_validate_path_rejects_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("nope")
    with pytest.raises(ConnectorError, match="escapes repository root"):
        _validate_path(outside, tmp_path)


def test_validate_path_rejects_symlink(tmp_path: Path) -> None:
    real_file = tmp_path / "real.txt"
    real_file.write_text("real")
    link = tmp_path / "link.txt"
    link.symlink_to(real_file)
    with pytest.raises(ConnectorError, match="symlinks are not allowed"):
        _validate_path(link, tmp_path)


# ---------------------------------------------------------------------------
# Task 2: documents operation tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES_DIR, tmp_path / "repo")
    return tmp_path / "repo"


def make_connector(repo: Path) -> GitlawConnector:
    return GitlawConnector(repo_dir=repo)


def test_read_documents_lists_all(repo: Path) -> None:
    connector = make_connector(repo)
    docs = connector.read("documents", {}, {})
    assert len(docs) == 2
    keys = {d["key"] for d in docs}
    assert keys == {"sample-contract", "draft-policy"}


def test_read_documents_filter_by_status(repo: Path) -> None:
    connector = make_connector(repo)
    docs = connector.read("documents", {"status": "draft"}, {})
    assert len(docs) == 1
    assert docs[0]["key"] == "draft-policy"


def test_read_documents_filter_by_type(repo: Path) -> None:
    connector = make_connector(repo)
    docs = connector.read("documents", {"type": "contract"}, {})
    assert len(docs) == 1
    assert docs[0]["key"] == "sample-contract"


def test_read_documents_includes_workflow_state(repo: Path) -> None:
    connector = make_connector(repo)
    docs = connector.read("documents", {}, {})
    contract = next(d for d in docs if d["key"] == "sample-contract")
    assert contract["workflow_state"]["current_reviewers"] == ["alice"]
    assert contract["workflow_state"]["approvals"] == []


def test_read_documents_rejects_symlinked_dir(repo: Path, tmp_path: Path) -> None:
    # Create a real doc directory outside the repo
    real_doc = tmp_path / "real-doc"
    real_doc.mkdir()
    (real_doc / "document.yaml").write_text(
        "title: External\ntype: contract\nstatus: active\nparties: []\ncreated: '2026-01-01'\nsections: []\n"
    )

    # Symlink it into the repo
    link = repo / "symlinked-doc"
    link.symlink_to(real_doc)

    connector = make_connector(repo)
    docs = connector.read("documents", {}, {})
    keys = {d["key"] for d in docs}
    assert "symlinked-doc" not in keys
    assert len(docs) == 2


# ---------------------------------------------------------------------------
# Task 3: document_detail operation tests
# ---------------------------------------------------------------------------


def test_read_document_detail(repo: Path) -> None:
    connector = make_connector(repo)
    detail = connector.read("document_detail", {"document": "sample-contract"}, {})
    assert detail["title"] == "Service Agreement"
    assert "recitals" in detail["section_contents"]
    assert "definitions" in detail["section_contents"]
    assert "WHEREAS" in detail["section_contents"]["recitals"]
    assert "Agreement" in detail["section_contents"]["definitions"]


def test_read_document_detail_unknown_doc(repo: Path) -> None:
    connector = make_connector(repo)
    with pytest.raises(ConnectorError, match="document not found: nonexistent"):
        connector.read("document_detail", {"document": "nonexistent"}, {})


def test_read_document_detail_rejects_traversal_section(repo: Path) -> None:
    # Create a document that references a section file with path traversal
    evil_doc_dir = repo / "evil-doc"
    evil_doc_dir.mkdir()
    (evil_doc_dir / "sections").mkdir()

    evil_meta = {
        "title": "Evil Doc",
        "type": "contract",
        "status": "draft",
        "parties": [],
        "created": "2026-01-01",
        "sections": [
            {"id": "passwd", "file": "../../etc/passwd"},
        ],
    }
    (evil_doc_dir / "document.yaml").write_text(yaml.dump(evil_meta))
    (evil_doc_dir / ".gitlaw").write_text(
        "signatures: []\naudit_log_ref: refs/notes/gitlaw-audit\nworkflow_state:\n  current_reviewers: []\n  approvals: []\n"
    )

    connector = make_connector(repo)
    with pytest.raises(ConnectorError, match="escapes repository root"):
        connector.read("document_detail", {"document": "evil-doc"}, {})


# ---------------------------------------------------------------------------
# Helpers for git-based tests (Tasks 4 & 5)
# ---------------------------------------------------------------------------


def _init_git_repo(repo_dir):
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, capture_output=True, check=True)


def _write_audit_notes(repo_dir, entries):
    data = json.dumps(entries)
    subprocess.run(
        ["git", "notes", "--ref=refs/notes/gitlaw-audit", "add", "-f", "-m", data, "HEAD"],
        cwd=repo_dir, capture_output=True, check=True,
    )


# ---------------------------------------------------------------------------
# Task 4: audit_log operation tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a fixture-based repo that is also a real git repo."""
    repo_dir = tmp_path / "repo"
    shutil.copytree(FIXTURES_DIR, repo_dir)
    _init_git_repo(repo_dir)
    return repo_dir


def test_read_audit_log_returns_normalized_entries(git_repo: Path) -> None:
    entries = [
        {
            "timestamp": "2026-03-01T10:00:00+00:00",
            "actor": "alice",
            "event": "document_created",
            "document": "sample-contract",
            "commit": "abc123",
            "details": {"note": "initial draft"},
        }
    ]
    _write_audit_notes(git_repo, entries)

    connector = make_connector(git_repo)
    result = connector.read("audit_log", {}, {})

    assert len(result) == 1
    activity = result[0]
    assert activity["activity_type"] == "document_create"
    assert activity["actor"] == "alice"
    assert activity["matter_id"] == "sample-contract"
    assert activity["description"] == "document_created"
    assert activity["evidence_refs"] == ["abc123"]
    assert activity["metadata"] == {"note": "initial draft"}


def test_read_audit_log_filters_by_document(git_repo: Path) -> None:
    entries = [
        {
            "timestamp": "2026-03-01T10:00:00+00:00",
            "actor": "alice",
            "event": "document_created",
            "document": "sample-contract",
            "commit": "abc123",
            "details": {},
        },
        {
            "timestamp": "2026-03-01T11:00:00+00:00",
            "actor": "bob",
            "event": "section_modified",
            "document": "draft-policy",
            "commit": "def456",
            "details": {},
        },
    ]
    _write_audit_notes(git_repo, entries)

    connector = make_connector(git_repo)
    result = connector.read("audit_log", {"document": "sample-contract"}, {})

    assert len(result) == 1
    assert result[0]["matter_id"] == "sample-contract"


def test_read_audit_log_empty_when_no_notes(git_repo: Path) -> None:
    connector = make_connector(git_repo)
    result = connector.read("audit_log", {}, {})
    assert result == []


def test_read_audit_log_rejects_detached_head(git_repo: Path) -> None:
    # Get current commit SHA and detach HEAD
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "checkout", sha],
        cwd=git_repo, capture_output=True, check=True,
    )

    connector = make_connector(git_repo)
    with pytest.raises(ConnectorError, match="detached HEAD"):
        connector.read("audit_log", {}, {})
