"""Session-based web authentication and permission enforcement."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from fastapi import HTTPException, Request

from matteros.core.store import SQLiteStore
from matteros.team.users import ROLE_PERMISSIONS, UserManager, verify_password


SESSION_COOKIE_NAME = "matteros_session"
SESSION_DURATION_HOURS = 24


def create_session(store: SQLiteStore, user_id: str) -> str:
    """Create a new session row and return the session ID."""
    session_id = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires = now + timedelta(hours=SESSION_DURATION_HOURS)
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (session_id, user_id, now.isoformat(), expires.isoformat()),
        )
        conn.commit()
    return session_id


def delete_session(store: SQLiteStore, session_id: str) -> None:
    """Delete a session row."""
    with store.connection() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()


def resolve_session_user(store: SQLiteStore, session_id: str) -> dict[str, Any] | None:
    """Look up a session and return the user dict if valid and not expired."""
    with store.connection() as conn:
        row = conn.execute(
            "SELECT s.user_id, s.expires_at FROM sessions s WHERE s.id = ?",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if datetime.now(UTC) > expires_at:
        delete_session(store, session_id)
        return None
    manager = UserManager(store)
    return manager.get_user(row["user_id"])


def get_user_permissions(role: str) -> set[str]:
    """Return the set of allowed actions for a role."""
    return ROLE_PERMISSIONS.get(role, set())


def has_users(store: SQLiteStore) -> bool:
    """Check whether any users exist in the database."""
    with store.connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return row[0] > 0


def handle_login(store: SQLiteStore, username: str, password: str) -> str | None:
    """Validate credentials and return user_id on success, None on failure."""
    manager = UserManager(store)
    user = manager.get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user["id"]


def require_permission(action: str) -> Callable:
    """Return a FastAPI dependency that checks the current user's permission."""

    def _check(request: Request) -> None:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=403, detail="Not authenticated")
        permissions = get_user_permissions(user["role"])
        if action not in permissions:
            raise HTTPException(status_code=403, detail="Permission denied")

    return _check
