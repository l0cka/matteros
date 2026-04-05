"""User management for team mode.

Roles:
- legal: lawyer, full matter management with audit access
- gc: general counsel, full access including user management and dashboard
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from matteros.core.store import SQLiteStore


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a random 16-byte salt.

    Returns 'salt_hex$scrypt_hex'.
    """
    salt = os.urandom(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"{salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored 'salt_hex$scrypt_hex' hash.

    Returns False for legacy unsalted SHA-256 hashes (no '$' separator).
    """
    if "$" not in stored_hash:
        return False
    salt_hex, hash_hex = stored_hash.split("$", 1)
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    derived = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return derived.hex() == hash_hex


VALID_ROLES = {"legal", "gc"}

# Permission matrix: role -> set of allowed actions
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "legal": {
        "manage_matters", "view_matters", "view_audit",
        "manage_deadlines", "manage_contacts",
    },
    "gc": {
        "manage_matters", "view_matters", "view_audit",
        "manage_deadlines", "manage_contacts",
        "manage_users", "view_dashboard",
    },
}


class UserManager:
    """Manages user accounts for team mode."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def create_user(
        self,
        *,
        username: str,
        role: str,
        password_hash: str,
    ) -> str:
        if role not in VALID_ROLES:
            raise ValueError(f"invalid role: {role}; must be one of {VALID_ROLES}")

        user_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, role, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, role, password_hash, now, now),
            )
            conn.commit()
        return user_id

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT id, username, role, created_at, updated_at FROM users ORDER BY created_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_role(self, user_id: str, role: str) -> None:
        if role not in VALID_ROLES:
            raise ValueError(f"invalid role: {role}; must be one of {VALID_ROLES}")
        now = datetime.now(UTC).isoformat()
        with self.store.connection() as conn:
            conn.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                (role, now, user_id),
            )
            conn.commit()

    def delete_user(self, user_id: str) -> None:
        with self.store.connection() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()

    def check_permission(self, user_id: str, action: str) -> bool:
        user = self.get_user(user_id)
        if not user:
            return False
        role = user["role"]
        allowed = ROLE_PERMISSIONS.get(role, set())
        return action in allowed
