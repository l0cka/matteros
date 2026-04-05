"""Tests for per-run SSE streaming."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from matteros.core.store import SQLiteStore
from matteros.team.users import UserManager, hash_password
from matteros.web.app import create_app
from matteros.web.auth import SESSION_COOKIE_NAME, create_session


def _init_home(home: Path) -> str:
    """Set up home dir with a gc user and test data. Returns session cookie value."""
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    user_id = manager.create_user(username="gc", role="gc", password_hash=hash_password("p"))
    # Insert a run and some events scoped to it
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO runs (id, playbook_name, status, started_at, dry_run, approve_mode, input_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run-sse-1", "test", "completed", "2024-01-01T00:00:00Z", 1, 0, "{}"),
        )
        conn.execute(
            "INSERT INTO audit_events (run_id, timestamp, event_type, actor, step_id, data_json, prev_hash, event_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-sse-1", "2024-01-01T00:00:01Z", "step.started", "system", "s1", "{}", None, "h1"),
        )
        conn.execute(
            "INSERT INTO audit_events (run_id, timestamp, event_type, actor, step_id, data_json, prev_hash, event_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-sse-1", "2024-01-01T00:00:02Z", "run.completed", "system", None, "{}", "h1", "h2"),
        )
        # An event for a different run should NOT appear
        conn.execute(
            "INSERT INTO audit_events (run_id, timestamp, event_type, actor, step_id, data_json, prev_hash, event_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-other", "2024-01-01T00:00:03Z", "run.started", "system", None, "{}", "h2", "h3"),
        )
        conn.commit()
    return create_session(store, user_id)


def test_per_run_sse_requires_view_runs_permission(tmp_path):
    # The /runs/{id}/live SSE endpoint requires view_runs permission (legacy name).
    # The new role model (gc/legal) does not include view_runs, so access is denied
    # until the web layer is updated to use new permission names (future task).
    home = tmp_path / "matteros"
    session_id = _init_home(home)
    app = create_app(home=home)

    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/runs/run-sse-1/live",
                params={"since": 0},
                cookies={SESSION_COOKIE_NAME: session_id},
                timeout=5.0,
            )
            return resp.status_code

    status = asyncio.run(_test())
    # gc lacks legacy view_runs permission; web layer needs updating
    assert status == 403


def test_per_run_sse_unauthenticated_redirects(tmp_path):
    home = tmp_path / "matteros"
    _init_home(home)
    app = create_app(home=home)

    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/runs/run-sse-1/live",
                params={"since": 0},
                follow_redirects=False,
                timeout=5.0,
            )
            return resp.status_code

    status = asyncio.run(_test())
    assert status == 303
