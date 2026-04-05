"""Tests for team/multi-user features."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from matteros.core.store import SQLiteStore
from matteros.team.reports import TeamReports
from matteros.team.users import UserManager, hash_password, verify_password


def test_create_and_get_user(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)

    user_id = manager.create_user(
        username="testuser",
        role="legal",
        password_hash="fakehash",
    )
    user = manager.get_user(user_id)
    assert user is not None
    assert user["username"] == "testuser"
    assert user["role"] == "legal"


def test_get_user_by_username(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)

    manager.create_user(username="alice", role="gc", password_hash="h1")
    user = manager.get_user_by_username("alice")
    assert user is not None
    assert user["role"] == "gc"


def test_list_users(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)

    manager.create_user(username="u1", role="gc", password_hash="h1")
    manager.create_user(username="u2", role="legal", password_hash="h2")
    manager.create_user(username="u3", role="legal", password_hash="h3")

    users = manager.list_users()
    assert len(users) == 3


def test_update_role(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)

    uid = manager.create_user(username="bob", role="legal", password_hash="h")
    manager.update_role(uid, "gc")

    user = manager.get_user(uid)
    assert user["role"] == "gc"


def test_invalid_role_raises(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)

    with pytest.raises(ValueError, match="invalid role"):
        manager.create_user(username="x", role="superadmin", password_hash="h")


def test_valid_roles_rejects_old_names(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    for old_role in ("dev", "partner_gc", "sr_solicitor", "solicitor", "paralegal"):
        with pytest.raises(ValueError, match="invalid role"):
            manager.create_user(username=f"u_{old_role}", role=old_role, password_hash="h")


def test_valid_roles_accepts_new_names(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    for role in ("legal", "gc"):
        uid = manager.create_user(username=f"u_{role}", role=role, password_hash="h")
        assert manager.get_user(uid)["role"] == role


def test_permission_gc_has_manage_users(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    uid = manager.create_user(username="gc1", role="gc", password_hash="h")
    for action in (
        "manage_matters", "view_matters", "view_audit",
        "manage_deadlines", "manage_contacts",
        "manage_users", "view_dashboard",
    ):
        assert manager.check_permission(uid, action) is True


def test_permission_legal_cannot_manage_users(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    uid = manager.create_user(username="legal1", role="legal", password_hash="h")
    assert manager.check_permission(uid, "manage_matters") is True
    assert manager.check_permission(uid, "view_matters") is True
    assert manager.check_permission(uid, "view_audit") is True
    assert manager.check_permission(uid, "manage_deadlines") is True
    assert manager.check_permission(uid, "manage_contacts") is True
    assert manager.check_permission(uid, "manage_users") is False
    assert manager.check_permission(uid, "view_dashboard") is False


def test_hash_password_produces_salt_scrypt_format() -> None:
    h = hash_password("mysecret")
    parts = h.split("$")
    assert len(parts) == 2
    salt_hex, hash_hex = parts
    assert len(bytes.fromhex(salt_hex)) == 16
    assert len(hash_hex) > 0


def test_verify_password_correct() -> None:
    h = hash_password("testpass")
    assert verify_password("testpass", h) is True


def test_verify_password_wrong() -> None:
    h = hash_password("testpass")
    assert verify_password("wrongpass", h) is False


def test_verify_password_rejects_legacy_sha256() -> None:
    import hashlib
    legacy_hash = hashlib.sha256(b"oldpass").hexdigest()
    assert verify_password("oldpass", legacy_hash) is False


def test_approval_queue_depth(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    reports = TeamReports(store)
    queue = reports.approval_queue_depth()
    assert isinstance(queue, dict)


def test_weekly_summary(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    reports = TeamReports(store)
    weekly = reports.weekly_summary()
    assert isinstance(weekly, list)


def test_hours_by_matter_filters_by_user_id(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    reports = TeamReports(store)

    run_id = store.create_run(
        playbook_name="test",
        started_at=datetime.now(UTC).isoformat(),
        dry_run=False,
        approve_mode=True,
        input_payload={},
    )
    now = datetime.now(UTC).isoformat()

    store.insert_approval(
        run_id=run_id,
        step_id="approve_entries",
        item_index=0,
        decision="approve",
        reason=None,
        reviewer="alice",
        created_at=now,
        resolved_at=now,
        entry_payload={"matter_id": "MAT-A", "duration_minutes": 30},
    )
    store.insert_approval(
        run_id=run_id,
        step_id="approve_entries",
        item_index=1,
        decision="approve",
        reason=None,
        reviewer="bob",
        created_at=now,
        resolved_at=now,
        entry_payload={"matter_id": "MAT-B", "duration_minutes": 60},
    )

    all_rows = reports.hours_by_matter()
    alice_rows = reports.hours_by_matter(user_id="alice")

    assert {row["matter_id"] for row in all_rows} == {"MAT-A", "MAT-B"}
    assert len(alice_rows) == 1
    assert alice_rows[0]["matter_id"] == "MAT-A"
    assert alice_rows[0]["total_minutes"] == 30
