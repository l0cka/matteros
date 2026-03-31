"""Tests for POST /api/runs endpoint."""

from __future__ import annotations

import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from matteros.core.store import SQLiteStore
from matteros.team.users import UserManager, hash_password
from matteros.web.app import create_app
from matteros.web.auth import SESSION_COOKIE_NAME, create_session


def _init_home(home: Path) -> str:
    """Set up home dir with a dev user. Returns session cookie value."""
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    user_id = manager.create_user(username="dev", role="dev", password_hash=hash_password("p"))
    return create_session(store, user_id)


def _make_client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def test_post_returns_run_id(tmp_path):
    home = tmp_path / "matteros"
    session_id = _init_home(home)

    # Create a playbook
    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    (pb_dir / "test_playbook.yml").write_text(
        "metadata:\n  name: test_playbook\n  description: test\n  version: '1.0'\n"
        "connectors: []\ninputs: {}\nsteps:\n- id: noop\n  type: collect\n  config: {}\n"
    )

    app = create_app(home=home)

    async def _test():
        async with _make_client(app) as client:
            resp = await client.post(
                "/api/runs",
                json={"playbook": "test_playbook", "inputs": {}, "dry_run": True},
                cookies={SESSION_COOKIE_NAME: session_id},
            )
            return resp

    resp = asyncio.run(_test())
    assert resp.status_code == 201
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "started"


def test_post_validates_missing_playbook(tmp_path):
    home = tmp_path / "matteros"
    session_id = _init_home(home)
    app = create_app(home=home)

    async def _test():
        async with _make_client(app) as client:
            resp = await client.post(
                "/api/runs",
                json={"inputs": {}},
                cookies={SESSION_COOKIE_NAME: session_id},
            )
            return resp

    resp = asyncio.run(_test())
    assert resp.status_code == 422


def test_post_rejects_unknown_playbook(tmp_path):
    home = tmp_path / "matteros"
    session_id = _init_home(home)
    app = create_app(home=home)

    async def _test():
        async with _make_client(app) as client:
            resp = await client.post(
                "/api/runs",
                json={"playbook": "nonexistent_playbook"},
                cookies={SESSION_COOKIE_NAME: session_id},
            )
            return resp

    resp = asyncio.run(_test())
    assert resp.status_code == 404


def test_post_requires_auth(tmp_path):
    home = tmp_path / "matteros"
    _init_home(home)
    app = create_app(home=home)

    async def _test():
        async with _make_client(app) as client:
            resp = await client.post(
                "/api/runs",
                json={"playbook": "test"},
            )
            return resp

    resp = asyncio.run(_test())
    # Unauthenticated requests get redirected to login
    assert resp.status_code == 303


def test_post_dry_run_defaults_true(tmp_path):
    home = tmp_path / "matteros"
    session_id = _init_home(home)

    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    (pb_dir / "test_pb.yml").write_text(
        "metadata:\n  name: test_pb\n  description: test\n  version: '1.0'\n"
        "connectors: []\ninputs: {}\nsteps:\n- id: noop\n  type: collect\n  config: {}\n"
    )

    app = create_app(home=home)

    async def _test():
        async with _make_client(app) as client:
            resp = await client.post(
                "/api/runs",
                json={"playbook": "test_pb"},
                cookies={SESSION_COOKIE_NAME: session_id},
            )
            return resp

    resp = asyncio.run(_test())
    # Should succeed (dry_run defaults to True)
    assert resp.status_code == 201
