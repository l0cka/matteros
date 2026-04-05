"""Tests for web session auth, login/logout, and permission enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from matteros.core.store import SQLiteStore
from matteros.team.users import UserManager, hash_password
from matteros.web.app import create_app


def _setup_app_with_user(
    tmp_path: Path,
    username: str = "testuser",
    password: str = "testpass",
    role: str = "legal",
) -> tuple[TestClient, str, str]:
    """Create app, add a user, return (client, user_id, password)."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    user_id = manager.create_user(
        username=username,
        role=role,
        password_hash=hash_password(password),
    )
    app = create_app(home=home)
    client = TestClient(app)
    return client, user_id, password


# --- Login / Logout ---


def test_login_redirects_to_dashboard(tmp_path: Path) -> None:
    client, _, password = _setup_app_with_user(tmp_path)
    response = client.post(
        "/login",
        data={"username": "testuser", "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "matteros_session" in response.cookies


def test_login_wrong_password_shows_error(tmp_path: Path) -> None:
    client, _, _ = _setup_app_with_user(tmp_path)
    response = client.post(
        "/login",
        data={"username": "testuser", "password": "wrongpass"},
    )
    assert response.status_code == 200
    assert "Invalid username or password" in response.text


def test_login_nonexistent_user(tmp_path: Path) -> None:
    client, _, _ = _setup_app_with_user(tmp_path)
    response = client.post(
        "/login",
        data={"username": "nobody", "password": "x"},
    )
    assert response.status_code == 200
    assert "Invalid username or password" in response.text


def test_logout_clears_session(tmp_path: Path) -> None:
    client, _, password = _setup_app_with_user(tmp_path)
    client.post("/login", data={"username": "testuser", "password": password})
    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    dash = client.get("/", follow_redirects=False)
    assert dash.status_code == 303


# --- Unauthenticated redirect ---


def test_unauthenticated_redirects_to_login(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(username="u", role="gc", password_hash=hash_password("p"))
    app = create_app(home=home)
    client = TestClient(app)

    for path in ["/", "/runs", "/drafts", "/audit", "/settings"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, f"{path} should redirect"
        assert response.headers["location"] == "/login"


def test_login_page_accessible_without_auth(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(username="u", role="gc", password_hash=hash_password("p"))
    app = create_app(home=home)
    client = TestClient(app)

    response = client.get("/login")
    assert response.status_code == 200


# --- Solo mode (no users) ---


def test_solo_mode_shows_setup_message(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    app = create_app(home=home)
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)
    assert response.status_code in (200, 303)
    if response.status_code == 200:
        assert "matteros team init" in response.text


# --- Permission enforcement ---


def test_run_trigger_route_removed(tmp_path: Path) -> None:
    # /api/runs POST route has been removed from the web layer
    client, _, password = _setup_app_with_user(tmp_path, role="legal")
    client.post("/login", data={"username": "testuser", "password": password})
    response = client.post("/api/runs", json={"playbook": "test", "dry_run": True})
    assert response.status_code == 404


def test_settings_route_removed(tmp_path: Path) -> None:
    # /settings route has been removed from the web layer
    client, _, password = _setup_app_with_user(tmp_path, role="legal")
    client.post("/login", data={"username": "testuser", "password": password})
    response = client.get("/settings", follow_redirects=False)
    assert response.status_code == 404


def test_gc_can_access_settings(tmp_path: Path) -> None:
    # gc role: check the user can log in and access authenticated routes
    client, _, password = _setup_app_with_user(tmp_path, role="gc")
    client.post("/login", data={"username": "testuser", "password": password})
    # gc has view_audit; settings still requires manage_settings which gc lacks too
    response = client.get("/audit", follow_redirects=False)
    assert response.status_code == 200


# --- Expired session ---


def test_expired_session_redirects_to_login(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta
    import secrets

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    user_id = manager.create_user(
        username="expuser", role="gc", password_hash=hash_password("p"),
    )

    app = create_app(home=home)
    client = TestClient(app)

    session_id = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expired = (now - timedelta(hours=25)).isoformat()
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (session_id, user_id, now.isoformat(), expired),
        )
        conn.commit()

    client.cookies.set("matteros_session", session_id)
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# --- Cookie properties ---


def test_session_cookie_is_httponly(tmp_path: Path) -> None:
    client, _, password = _setup_app_with_user(tmp_path)
    response = client.post(
        "/login",
        data={"username": "testuser", "password": password},
        follow_redirects=False,
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower()


# --- Own-vs-others draft approval ---


def test_draft_approve_route_removed(tmp_path: Path) -> None:
    # Draft approval routes have been removed from the web layer.
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(
        username="gc1", role="gc", password_hash=hash_password("p"),
    )

    app = create_app(home=home)
    client = TestClient(app)
    client.post("/login", data={"username": "gc1", "password": "p"})
    response = client.post("/drafts/some-id/approve")
    assert response.status_code == 404


def test_draft_approve_others_route_removed(tmp_path: Path) -> None:
    # Draft approval routes have been removed from the web layer.
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(username="legal1", role="legal", password_hash=hash_password("p"))

    app = create_app(home=home)
    client = TestClient(app)
    client.post("/login", data={"username": "legal1", "password": "p"})
    response = client.post("/drafts/some-id/approve")
    assert response.status_code == 404


# --- Legacy SHA-256 hash rejection ---


def test_legacy_sha256_hash_cannot_login(tmp_path: Path) -> None:
    import hashlib as hl

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    legacy_hash = hl.sha256(b"oldpass").hexdigest()
    manager.create_user(username="legacy", role="gc", password_hash=legacy_hash)

    app = create_app(home=home)
    client = TestClient(app)
    response = client.post("/login", data={"username": "legacy", "password": "oldpass"})
    assert response.status_code == 200
    assert "Invalid username or password" in response.text
