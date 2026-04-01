from __future__ import annotations

from pathlib import Path

import pytest

from matteros.connectors.base import ConnectorError
from matteros.connectors.gitlaw import _validate_path

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
