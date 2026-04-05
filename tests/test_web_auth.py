"""Tests for web authentication (session-based) and draft action responses."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from matteros.core.store import SQLiteStore
from matteros.drafts.manager import DraftManager
from matteros.team.users import UserManager, hash_password
from matteros.web.app import create_app


def _make_authed_client(home: Path) -> TestClient:
    """Create app with a gc user and return a logged-in client."""
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(username="gc", role="gc", password_hash=hash_password("pass"))
    app = create_app(home=home)
    client = TestClient(app)
    client.post("/login", data={"username": "gc", "password": "pass"})
    return client


def test_web_rejects_missing_auth(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    # Need at least one user so it's not solo mode
    store = SQLiteStore(home / "matteros.db")
    UserManager(store).create_user(username="u", role="gc", password_hash=hash_password("p"))
    app = create_app(home=home)
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_web_login_sets_session_cookie(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    UserManager(store).create_user(username="u", role="gc", password_hash=hash_password("p"))
    app = create_app(home=home)
    client = TestClient(app)

    response = client.post(
        "/login", data={"username": "u", "password": "p"}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert "matteros_session" in response.cookies

    # Can access dashboard with session
    dash = client.get("/")
    assert dash.status_code == 200


def test_draft_approve_endpoint_requires_approve_own_permission(tmp_path: Path) -> None:
    # The web layer guards /drafts/{id}/approve with approve_own/approve_others.
    # The new role model (legal/gc) does not include these legacy permission names,
    # so approvals via web require the web layer to be updated to use new permission
    # names (future task). Until then, authenticated users without approve_own get 403.
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    client = _make_authed_client(home)

    store = SQLiteStore(home / "matteros.db")
    manager = DraftManager(store)
    draft_id = manager.create_draft(
        run_id="run-1",
        entry={
            "matter_id": "MAT-123",
            "duration_minutes": 30,
            "narrative": "Draft entry",
            "confidence": 0.9,
        },
    )

    response = client.post(f"/drafts/{draft_id}/approve")
    # gc role has manage_matters but not legacy approve_own permission name
    assert response.status_code == 403
