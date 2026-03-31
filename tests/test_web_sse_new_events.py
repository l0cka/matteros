"""Test that audit API includes draft.created events for SSE consumption."""

from __future__ import annotations

import json
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from matteros.core.store import SQLiteStore
from matteros.team.users import UserManager, hash_password
from matteros.web.app import create_app
from matteros.web.auth import SESSION_COOKIE_NAME, create_session


def _init_home(home: Path) -> str:
    """Set up home dir with a dev user and a draft.created event. Returns session cookie value."""
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    user_id = manager.create_user(username="dev", role="dev", password_hash=hash_password("p"))
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO audit_events (run_id, timestamp, event_type, actor, step_id, data_json, prev_hash, event_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "2024-01-01T00:00:00Z", "draft.created", "system", None, json.dumps({"draft_id": "d-1"}), None, "hash1"),
        )
        conn.commit()
    return create_session(store, user_id)


def test_audit_api_includes_draft_created_event(tmp_path):
    import asyncio

    home = tmp_path / "matteros"
    session_id = _init_home(home)
    app = create_app(home=home)

    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/audit",
                cookies={SESSION_COOKIE_NAME: session_id},
            )
            return resp.json()

    events = asyncio.run(_test())
    event_types = [e.get("event_type") for e in events]
    assert "draft.created" in event_types
