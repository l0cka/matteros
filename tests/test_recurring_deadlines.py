"""Tests for recurring deadline auto-generation."""
from __future__ import annotations
from pathlib import Path
import pytest
from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore

@pytest.fixture
def ms(tmp_path: Path) -> MatterStore:
    db = SQLiteStore(tmp_path / "test.db")
    return MatterStore(db)

def test_complete_recurring_creates_next(ms):
    matter_id = ms.create_matter(title="Annual Filing", type="compliance")
    dl_id = ms.create_deadline(
        matter_id=matter_id, label="Annual report",
        due_date="2026-03-31", recurring="P1Y",
    )
    ms.complete_deadline(dl_id)
    deadlines = ms.list_deadlines(matter_id)
    assert len(deadlines) == 2
    completed = [d for d in deadlines if d["status"] == "completed"]
    pending = [d for d in deadlines if d["status"] == "pending"]
    assert len(completed) == 1
    assert len(pending) == 1
    assert pending[0]["due_date"][:10] == "2027-03-31"
    assert pending[0]["recurring"] == "P1Y"

def test_complete_non_recurring_does_not_create_next(ms):
    matter_id = ms.create_matter(title="One-off", type="compliance")
    dl_id = ms.create_deadline(
        matter_id=matter_id, label="One-time filing", due_date="2026-06-30",
    )
    ms.complete_deadline(dl_id)
    deadlines = ms.list_deadlines(matter_id)
    assert len(deadlines) == 1
    assert deadlines[0]["status"] == "completed"

def test_recurring_quarterly(ms):
    matter_id = ms.create_matter(title="Quarterly", type="compliance")
    dl_id = ms.create_deadline(
        matter_id=matter_id, label="Q1 Filing",
        due_date="2026-03-31", recurring="P3M",
    )
    ms.complete_deadline(dl_id)
    deadlines = ms.list_deadlines(matter_id)
    pending = [d for d in deadlines if d["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["due_date"][:10] == "2026-06-30"
