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
    """Set up home dir with a gc user. Returns session cookie value."""
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    user_id = manager.create_user(username="gc", role="gc", password_hash=hash_password("p"))
    return create_session(store, user_id)


def _make_client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def test_post_requires_run_playbooks_permission(tmp_path):
    # The /api/runs endpoint requires run_playbooks permission (legacy name).
    # The new role model (gc/legal) does not include run_playbooks, so all
    # authenticated users get 403 until the web layer is updated (future task).
    home = tmp_path / "matteros"
    session_id = _init_home(home)

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
    # gc has manage_matters but not legacy run_playbooks; permission check fires first
    assert resp.status_code == 403


def test_post_missing_playbook_still_blocked_by_permission(tmp_path):
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
    # Permission check fires before validation; gc lacks run_playbooks
    assert resp.status_code == 403


def test_post_unknown_playbook_still_blocked_by_permission(tmp_path):
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
    # Permission check fires before playbook lookup; gc lacks run_playbooks
    assert resp.status_code == 403


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


def test_post_dry_run_requires_permission(tmp_path):
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
    # gc lacks legacy run_playbooks permission; web layer needs updating
    assert resp.status_code == 403
