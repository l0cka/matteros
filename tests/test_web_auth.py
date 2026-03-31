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
    """Create app with a dev user and return a logged-in client."""
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(username="dev", role="dev", password_hash=hash_password("pass"))
    app = create_app(home=home)
    client = TestClient(app)
    client.post("/login", data={"username": "dev", "password": "pass"})
    return client


def test_web_rejects_missing_auth(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    # Need at least one user so it's not solo mode
    store = SQLiteStore(home / "matteros.db")
    UserManager(store).create_user(username="u", role="dev", password_hash=hash_password("p"))
    app = create_app(home=home)
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_web_login_sets_session_cookie(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    UserManager(store).create_user(username="u", role="dev", password_hash=hash_password("p"))
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


def test_draft_approve_endpoint_returns_204(tmp_path: Path) -> None:
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
    assert response.status_code == 204
    assert response.text == ""

    updated = manager.get_draft(draft_id)
    assert updated is not None
    assert updated["status"] == "approved"
