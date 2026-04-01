from __future__ import annotations

import shutil
from pathlib import Path

import pytest

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
