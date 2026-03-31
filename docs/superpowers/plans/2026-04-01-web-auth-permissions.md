# Web Auth & Permission Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace MatterOS web's single shared token with per-user login and role-based permission enforcement.

**Architecture:** Session-aware FastAPI middleware resolves the current user from an httponly cookie backed by a SQLite `sessions` table. A `require_permission(action)` FastAPI dependency checks the user's role against a permission matrix with 5 legal-team roles and 10 named actions. Password hashing moves from unsalted SHA-256 to salted scrypt.

**Tech Stack:** Python 3, FastAPI, Jinja2, HTMX, SQLite, hashlib.scrypt (stdlib)

**Spec:** `docs/superpowers/specs/2026-04-01-web-auth-permissions-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `matteros/team/users.py` | New roles, permission matrix, password hashing helpers |
| Create | `matteros/core/migrations/v004_sessions.py` | Sessions table + role migration |
| Create | `matteros/web/auth.py` | Session middleware, login/logout handlers, `require_permission` dependency |
| Modify | `matteros/web/app.py` | Wire auth module, remove old token auth, add permission deps to routes |
| Create | `matteros/web/templates/login.html` | Login form template |
| Modify | `matteros/web/templates/base.html` | User display, logout link, conditional nav |
| Modify | `matteros/cli.py` | New role names, scrypt hashing in team commands |
| Modify | `tests/test_team.py` | Update for new roles and permission matrix |
| Create | `tests/test_web_auth_sessions.py` | Session auth, login/logout, permission enforcement, security test cases |

---

### Task 1: Update Roles and Permission Matrix in `users.py`

**Files:**
- Modify: `matteros/team/users.py`
- Test: `tests/test_team.py`

- [ ] **Step 1: Write failing tests for new roles and permissions**

Add to `tests/test_team.py` — replace the old role tests with new ones:

```python
# At the top, update imports (already correct)
# Replace the VALID_ROLES-related tests:

def test_valid_roles_rejects_old_names(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    for old_role in ("admin", "attorney", "reviewer"):
        with pytest.raises(ValueError, match="invalid role"):
            manager.create_user(username=f"u_{old_role}", role=old_role, password_hash="h")


def test_valid_roles_accepts_new_names(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    for role in ("dev", "partner_gc", "sr_solicitor", "solicitor", "paralegal"):
        uid = manager.create_user(username=f"u_{role}", role=role, password_hash="h")
        assert manager.get_user(uid)["role"] == role


def test_permission_dev_has_all(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    uid = manager.create_user(username="dev1", role="dev", password_hash="h")
    for action in (
        "manage_users", "manage_settings", "run_playbooks", "create_drafts",
        "approve_own", "approve_others", "view_runs", "view_audit", "view_reports", "view_drafts",
    ):
        assert manager.check_permission(uid, action) is True


def test_permission_solicitor_cannot_approve_others(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    uid = manager.create_user(username="sol1", role="solicitor", password_hash="h")
    assert manager.check_permission(uid, "run_playbooks") is True
    assert manager.check_permission(uid, "approve_own") is True
    assert manager.check_permission(uid, "approve_others") is False
    assert manager.check_permission(uid, "view_reports") is False


def test_permission_paralegal_limited(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    uid = manager.create_user(username="para1", role="paralegal", password_hash="h")
    assert manager.check_permission(uid, "create_drafts") is True
    assert manager.check_permission(uid, "view_runs") is True
    assert manager.check_permission(uid, "view_drafts") is True
    assert manager.check_permission(uid, "run_playbooks") is False
    assert manager.check_permission(uid, "approve_own") is False
    assert manager.check_permission(uid, "approve_others") is False
    assert manager.check_permission(uid, "view_audit") is False
    assert manager.check_permission(uid, "view_reports") is False


def test_permission_sr_solicitor_can_approve_others(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    uid = manager.create_user(username="sr1", role="sr_solicitor", password_hash="h")
    assert manager.check_permission(uid, "approve_others") is True
    assert manager.check_permission(uid, "view_reports") is True
    assert manager.check_permission(uid, "manage_users") is False


def test_permission_partner_gc_can_manage_settings(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    uid = manager.create_user(username="gc1", role="partner_gc", password_hash="h")
    assert manager.check_permission(uid, "manage_settings") is True
    assert manager.check_permission(uid, "approve_others") is True
    assert manager.check_permission(uid, "manage_users") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_team.py -v -k "new_names or rejects_old or permission_dev or permission_solicitor or permission_paralegal or permission_sr_solicitor or permission_partner" 2>&1 | head -60`

Expected: FAIL — old roles are still in `VALID_ROLES`, old permission matrix

- [ ] **Step 3: Update `users.py` with new roles and permission matrix**

In `matteros/team/users.py`, replace `VALID_ROLES` and `check_permission`:

```python
VALID_ROLES = {"dev", "partner_gc", "sr_solicitor", "solicitor", "paralegal"}

# Permission matrix: role -> set of allowed actions
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "dev": {
        "manage_users", "manage_settings", "run_playbooks", "create_drafts",
        "approve_own", "approve_others", "view_runs", "view_audit", "view_reports", "view_drafts",
    },
    "partner_gc": {
        "manage_settings", "run_playbooks", "create_drafts",
        "approve_own", "approve_others", "view_runs", "view_audit", "view_reports", "view_drafts",
    },
    "sr_solicitor": {
        "run_playbooks", "create_drafts", "approve_own", "approve_others",
        "view_runs", "view_audit", "view_reports", "view_drafts",
    },
    "solicitor": {
        "run_playbooks", "create_drafts", "approve_own",
        "view_runs", "view_audit", "view_drafts",
    },
    "paralegal": {
        "create_drafts", "view_runs", "view_drafts",
    },
}
```

Replace the `check_permission` method:

```python
def check_permission(self, user_id: str, action: str) -> bool:
    user = self.get_user(user_id)
    if not user:
        return False
    role = user["role"]
    allowed = ROLE_PERMISSIONS.get(role, set())
    return action in allowed
```

- [ ] **Step 4: Remove old tests, run all team tests**

Remove these old test functions from `tests/test_team.py`:
- `test_create_and_get_user` — replace role in the call from `"attorney"` to `"solicitor"`
- `test_get_user_by_username` — replace role from `"admin"` to `"dev"`
- `test_list_users` — replace roles from `"admin"/"attorney"/"reviewer"` to `"dev"/"solicitor"/"paralegal"`
- `test_update_role` — replace `"attorney"` to `"solicitor"`, `"reviewer"` to `"sr_solicitor"`
- `test_invalid_role_raises` — keep as-is (still tests an invalid role)
- `test_check_permission_admin` — DELETE (replaced by new tests)
- `test_check_permission_attorney` — DELETE (replaced by new tests)
- `test_check_permission_reviewer` — DELETE (replaced by new tests)

Run: `python -m pytest tests/test_team.py -v 2>&1 | tail -30`

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/team/users.py tests/test_team.py
git commit -m "feat(team): update roles to legal hierarchy with 5-role permission matrix

Replace admin/attorney/reviewer with dev/partner_gc/sr_solicitor/solicitor/paralegal.
Permission matrix uses named actions checked via ROLE_PERMISSIONS dict."
```

---

### Task 2: Password Hashing Helpers

**Files:**
- Modify: `matteros/team/users.py`
- Test: `tests/test_team.py`

- [ ] **Step 1: Write failing tests for scrypt hashing**

Add to `tests/test_team.py`:

```python
from matteros.team.users import hash_password, verify_password


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_team.py -v -k "hash_password or verify_password" 2>&1 | head -20`

Expected: ImportError — `hash_password` and `verify_password` not defined

- [ ] **Step 3: Implement `hash_password` and `verify_password` in `users.py`**

Add to `matteros/team/users.py` (after imports, before `VALID_ROLES`):

```python
import hashlib
import os


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_team.py -v -k "hash_password or verify_password" 2>&1 | tail -15`

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/team/users.py tests/test_team.py
git commit -m "feat(team): add scrypt password hashing with salt

hash_password() and verify_password() using hashlib.scrypt with
random 16-byte salt. Stored as salt_hex\$scrypt_hex. Legacy SHA-256
hashes (no \$ separator) are rejected by verify_password()."
```

---

### Task 3: Database Migration `v004_sessions.py`

**Files:**
- Create: `matteros/core/migrations/v004_sessions.py`
- Test: `tests/test_migrations.py`

- [ ] **Step 1: Write failing test for migration v004**

Add to `tests/test_migrations.py` (follow existing pattern — check the file first for the existing test structure):

```python
def test_v004_creates_sessions_table_and_migrates_roles(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "test.db")

    # Insert a user with old 'admin' role to test migration
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
            "VALUES ('u1', 'oldadmin', 'admin', 'fakehash', '2025-01-01', '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
            "VALUES ('u2', 'oldatty', 'attorney', 'fakehash', '2025-01-01', '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO users (id, username, role, password_hash, created_at, updated_at) "
            "VALUES ('u3', 'oldrev', 'reviewer', 'fakehash', '2025-01-01', '2025-01-01')"
        )
        conn.commit()

        # Apply v004
        from matteros.core.migrations.v004_sessions import upgrade
        upgrade(conn)
        conn.commit()

        # Sessions table exists
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "sessions" in tables

        # Roles migrated
        roles = {
            r["username"]: r["role"]
            for r in conn.execute("SELECT username, role FROM users").fetchall()
        }
        assert roles["oldadmin"] == "dev"
        assert roles["oldatty"] == "solicitor"
        assert roles["oldrev"] == "sr_solicitor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_migrations.py -v -k "v004" 2>&1 | head -20`

Expected: FAIL — module not found

- [ ] **Step 3: Create `v004_sessions.py`**

Create `matteros/core/migrations/v004_sessions.py`:

```python
from __future__ import annotations

import sqlite3

VERSION = 4
DESCRIPTION = "Add sessions table and migrate legacy roles"

ROLE_MIGRATION = {
    "admin": "dev",
    "attorney": "solicitor",
    "reviewer": "sr_solicitor",
}


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    for old_role, new_role in ROLE_MIGRATION.items():
        conn.execute(
            "UPDATE users SET role = ? WHERE role = ?",
            (new_role, old_role),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_migrations.py -v -k "v004" 2>&1 | tail -10`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/core/migrations/v004_sessions.py tests/test_migrations.py
git commit -m "feat(migrations): add v004 sessions table and role migration

Creates sessions table for per-user web auth. Migrates legacy roles:
admin->dev, attorney->solicitor, reviewer->sr_solicitor."
```

---

### Task 4: Web Auth Module (`web/auth.py`)

**Files:**
- Create: `matteros/web/auth.py`
- Create: `tests/test_web_auth_sessions.py`

- [ ] **Step 1: Write failing tests for session creation and verification**

Create `tests/test_web_auth_sessions.py`:

```python
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
    role: str = "solicitor",
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
    # Login first
    client.post("/login", data={"username": "testuser", "password": password})
    # Logout
    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    # Session cookie cleared — next request should redirect to login
    dash = client.get("/", follow_redirects=False)
    assert dash.status_code == 303


# --- Unauthenticated redirect ---


def test_unauthenticated_redirects_to_login(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    # Create at least one user so it's not solo mode
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(username="u", role="dev", password_hash=hash_password("p"))
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
    manager.create_user(username="u", role="dev", password_hash=hash_password("p"))
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
    # Should show setup message, not crash
    assert response.status_code in (200, 303)
    if response.status_code == 200:
        assert "matteros team init" in response.text


# --- Permission enforcement ---


def test_paralegal_cannot_trigger_run(tmp_path: Path) -> None:
    client, _, password = _setup_app_with_user(tmp_path, role="paralegal")
    client.post("/login", data={"username": "testuser", "password": password})
    response = client.post("/api/runs", json={"playbook": "test", "dry_run": True})
    assert response.status_code == 403


def test_paralegal_cannot_view_audit(tmp_path: Path) -> None:
    client, _, password = _setup_app_with_user(tmp_path, role="paralegal")
    client.post("/login", data={"username": "testuser", "password": password})
    response = client.get("/audit", follow_redirects=False)
    assert response.status_code == 403


def test_solicitor_can_view_runs(tmp_path: Path) -> None:
    client, _, password = _setup_app_with_user(tmp_path)
    client.post("/login", data={"username": "testuser", "password": password})
    response = client.get("/runs")
    assert response.status_code == 200


def test_dev_can_access_settings(tmp_path: Path) -> None:
    client, _, password = _setup_app_with_user(tmp_path, role="dev")
    client.post("/login", data={"username": "testuser", "password": password})
    response = client.get("/settings")
    assert response.status_code == 200


def test_solicitor_cannot_access_settings(tmp_path: Path) -> None:
    client, _, password = _setup_app_with_user(tmp_path)
    client.post("/login", data={"username": "testuser", "password": password})
    response = client.get("/settings", follow_redirects=False)
    assert response.status_code == 403


# --- Expired session ---


def test_expired_session_redirects_to_login(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    user_id = manager.create_user(
        username="expuser", role="dev", password_hash=hash_password("p"),
    )

    app = create_app(home=home)
    client = TestClient(app)

    # Manually insert an expired session
    import secrets
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


def test_solicitor_can_approve_own_draft(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    user_id = manager.create_user(
        username="sol", role="solicitor", password_hash=hash_password("p"),
    )
    # Create a draft owned by this user
    from matteros.drafts.manager import DraftManager
    dm = DraftManager(store)
    with store.connection() as conn:
        conn.execute("UPDATE drafts SET user_id = ? WHERE 1=0", (user_id,))  # no-op, just ensure column
    draft_id = dm.create_draft(run_id="r1", entry={"matter_id": "M1", "duration_minutes": 10, "narrative": "x", "confidence": 0.8})
    # Set the draft's user_id to this solicitor
    with store.connection() as conn:
        conn.execute("UPDATE drafts SET user_id = ? WHERE id = ?", (user_id, draft_id))
        conn.commit()

    app = create_app(home=home)
    client = TestClient(app)
    client.post("/login", data={"username": "sol", "password": "p"})
    response = client.post(f"/drafts/{draft_id}/approve")
    assert response.status_code == 204


def test_solicitor_cannot_approve_others_draft(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(username="sol", role="solicitor", password_hash=hash_password("p"))
    other_id = manager.create_user(username="other", role="solicitor", password_hash=hash_password("p2"))
    from matteros.drafts.manager import DraftManager
    dm = DraftManager(store)
    draft_id = dm.create_draft(run_id="r1", entry={"matter_id": "M1", "duration_minutes": 10, "narrative": "x", "confidence": 0.8})
    with store.connection() as conn:
        conn.execute("UPDATE drafts SET user_id = ? WHERE id = ?", (other_id, draft_id))
        conn.commit()

    app = create_app(home=home)
    client = TestClient(app)
    client.post("/login", data={"username": "sol", "password": "p"})
    response = client.post(f"/drafts/{draft_id}/approve")
    assert response.status_code == 403


def test_sr_solicitor_can_approve_others_draft(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(username="sr", role="sr_solicitor", password_hash=hash_password("p"))
    other_id = manager.create_user(username="other", role="solicitor", password_hash=hash_password("p2"))
    from matteros.drafts.manager import DraftManager
    dm = DraftManager(store)
    draft_id = dm.create_draft(run_id="r1", entry={"matter_id": "M1", "duration_minutes": 10, "narrative": "x", "confidence": 0.8})
    with store.connection() as conn:
        conn.execute("UPDATE drafts SET user_id = ? WHERE id = ?", (other_id, draft_id))
        conn.commit()

    app = create_app(home=home)
    client = TestClient(app)
    client.post("/login", data={"username": "sr", "password": "p"})
    response = client.post(f"/drafts/{draft_id}/approve")
    assert response.status_code == 204


# --- Legacy SHA-256 hash rejection ---


def test_legacy_sha256_hash_cannot_login(tmp_path: Path) -> None:
    import hashlib as hl

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    legacy_hash = hl.sha256(b"oldpass").hexdigest()
    manager.create_user(username="legacy", role="dev", password_hash=legacy_hash)

    app = create_app(home=home)
    client = TestClient(app)
    response = client.post("/login", data={"username": "legacy", "password": "oldpass"})
    assert response.status_code == 200
    assert "Invalid username or password" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_auth_sessions.py -v 2>&1 | head -30`

Expected: FAIL — `web/auth.py` doesn't exist yet, old auth middleware still in place

- [ ] **Step 3: Create `matteros/web/auth.py`**

```python
"""Session-based web authentication and permission enforcement."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from fastapi import HTTPException, Request, Response
from fastapi.responses import RedirectResponse

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
```

- [ ] **Step 4: Run tests to verify the auth module imports**

Run: `python -c "from matteros.web.auth import create_session, handle_login, require_permission; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add matteros/web/auth.py tests/test_web_auth_sessions.py
git commit -m "feat(web): add session auth module with login/logout and permission checks

New matteros/web/auth.py with session CRUD, password verification,
and require_permission() FastAPI dependency. Tests cover login,
logout, redirects, permission denial, expired sessions, legacy hash
rejection, and cookie properties."
```

---

### Task 5: Wire Auth into `app.py`

**Files:**
- Modify: `matteros/web/app.py`
- Create: `matteros/web/templates/login.html`

- [ ] **Step 1: Create `login.html` template**

Create `matteros/web/templates/login.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MatterOS - Login</title>
    <style>
        :root {
            --bg: #0f172a; --surface: #1e293b; --border: #334155;
            --text: #e2e8f0; --muted: #94a3b8; --accent: #3b82f6;
            --red: #ef4444;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'SF Mono', 'Cascadia Code', monospace; background: var(--bg); color: var(--text); display: flex; align-items: center; justify-content: center; min-height: 100vh; }
        .login-box { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 2rem; width: 340px; }
        .login-box h1 { font-size: 1.2rem; color: var(--accent); margin-bottom: 1.5rem; text-align: center; }
        .field { margin-bottom: 1rem; }
        .field label { display: block; font-size: 0.8rem; color: var(--muted); margin-bottom: 0.3rem; }
        .field input { width: 100%; background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 0.5rem 0.7rem; border-radius: 4px; font-family: inherit; font-size: 0.85rem; }
        .btn-login { width: 100%; padding: 0.5rem; background: var(--accent); color: white; border: none; border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 0.85rem; margin-top: 0.5rem; }
        .btn-login:hover { opacity: 0.9; }
        .error { color: var(--red); font-size: 0.8rem; margin-bottom: 1rem; text-align: center; }
        .setup-msg { text-align: center; font-size: 0.85rem; color: var(--muted); line-height: 1.6; }
        .setup-msg code { background: var(--bg); padding: 2px 6px; border-radius: 3px; font-size: 0.8rem; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>MatterOS</h1>
        {% if setup_required %}
        <div class="setup-msg">
            No users configured.<br>
            Run <code>matteros team init</code> to create the first user.
        </div>
        {% else %}
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST" action="/login">
            <div class="field">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" autocomplete="username" required>
            </div>
            <div class="field">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" autocomplete="current-password" required>
            </div>
            <button type="submit" class="btn-login">Sign in</button>
        </form>
        {% endif %}
    </div>
</body>
</html>
```

- [ ] **Step 2: Rewrite `app.py` to use session auth**

Replace the auth-related code in `matteros/web/app.py`. The key changes:

1. Remove the old `_token`, `AUTH_COOKIE_NAME`, `AUTH_QUERY_PARAM` variables and the `_auth_middleware` function.
2. Remove the `AUTH_COOKIE_NAME` and `AUTH_QUERY_PARAM` exports (tests will change in the next task).
3. Add imports from `matteros.web.auth`.
4. Add new session middleware.
5. Add login/logout routes.
6. Add `Depends(require_permission(...))` to protected routes.

Replace the entire auth section (lines ~27-84 of current `app.py`) with:

```python
from fastapi import Depends
from starlette.responses import RedirectResponse

from matteros.web.auth import (
    SESSION_COOKIE_NAME,
    create_session,
    delete_session,
    get_user_permissions,
    handle_login,
    has_users,
    require_permission,
    resolve_session_user,
)
```

Remove `_token`, `app.state.web_token`, `app.state.auth_query_param`, `app.state.auth_cookie_name`, `_extract_bearer_token`, `_is_authorized`.

Replace `_auth_middleware` with:

```python
@app.middleware("http")
async def _session_middleware(request: Request, call_next):
    # Allow login page and static assets without auth
    if request.url.path in ("/login",):
        response = await call_next(request)
        return response

    store = _store()

    # Solo mode: no users exist
    if not has_users(store):
        if request.url.path == "/":
            return templates.TemplateResponse("login.html", {
                "request": request,
                "setup_required": True,
                "error": None,
            })
        return RedirectResponse("/", status_code=303)

    # Check session cookie
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    user = resolve_session_user(store, session_id) if session_id else None

    if not user:
        return RedirectResponse("/login", status_code=303)

    request.state.user = user
    request.state.permissions = get_user_permissions(user["role"])
    response = await call_next(request)
    return response
```

Add login/logout routes after the middleware:

```python
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    store = _store()
    return templates.TemplateResponse("login.html", {
        "request": request,
        "setup_required": not has_users(store),
        "error": None,
    })

@app.post("/login")
async def login_submit(request: Request) -> Response:
    store = _store()
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))

    user_id = handle_login(store, username, password)
    if not user_id:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "setup_required": False,
            "error": "Invalid username or password",
        })

    session_id = create_session(store, user_id)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="strict",
    )
    return response

@app.post("/logout")
async def logout(request: Request) -> Response:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        store = _store()
        delete_session(store, session_id)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
```

Add `Depends(require_permission(...))` to protected routes:

```python
# Dashboard — any authenticated user (no extra permission needed, middleware handles it)
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    ...

# Runs
@app.get("/runs", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_runs"))])
async def runs_page(request: Request) -> HTMLResponse:
    ...

@app.get("/runs/new", response_class=HTMLResponse, dependencies=[Depends(require_permission("run_playbooks"))])
async def run_trigger_page(request: Request) -> HTMLResponse:
    ...

@app.get("/runs/{run_id}", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_runs"))])
async def run_detail(request: Request, run_id: str) -> HTMLResponse:
    ...

@app.get("/runs/{run_id}/live", dependencies=[Depends(require_permission("view_runs"))])
async def run_live_stream(run_id: str, since: int = Query(0, ge=0)) -> StreamingResponse:
    ...

# Approvals
@app.get("/approvals", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_runs"))])
async def approvals_page(request: Request) -> HTMLResponse:
    ...

# Drafts
@app.get("/drafts", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_drafts"))])
async def drafts_page(request: Request) -> HTMLResponse:
    ...

@app.post("/drafts/{draft_id}/approve")
async def approve_draft(request: Request, draft_id: str) -> Response:
    # Check own-vs-others: if the draft's user_id matches the current user, require approve_own; otherwise approve_others
    store = _store()
    manager = DraftManager(store)
    draft = manager.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    user = request.state.user
    permissions = request.state.permissions
    draft_owner = draft.get("user_id", "solo")
    if draft_owner == user["id"]:
        if "approve_own" not in permissions:
            raise HTTPException(status_code=403, detail="Permission denied")
    else:
        if "approve_others" not in permissions:
            raise HTTPException(status_code=403, detail="Permission denied")
    manager.approve_draft(draft_id)
    return Response(status_code=204)

@app.post("/drafts/{draft_id}/reject")
async def reject_draft(request: Request, draft_id: str) -> Response:
    store = _store()
    manager = DraftManager(store)
    draft = manager.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    user = request.state.user
    permissions = request.state.permissions
    draft_owner = draft.get("user_id", "solo")
    if draft_owner == user["id"]:
        if "approve_own" not in permissions:
            raise HTTPException(status_code=403, detail="Permission denied")
    else:
        if "approve_others" not in permissions:
            raise HTTPException(status_code=403, detail="Permission denied")
    manager.reject_draft(draft_id)
    return Response(status_code=204)

# Audit
@app.get("/audit", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_audit"))])
async def audit_page(request: Request) -> HTMLResponse:
    ...

# Settings
@app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_permission("manage_settings"))])
async def settings_page(request: Request) -> HTMLResponse:
    ...

# SSE stream
@app.get("/events/stream", dependencies=[Depends(require_permission("view_runs"))])
async def event_stream(since: int = Query(0, ge=0)) -> StreamingResponse:
    ...

# API endpoints
@app.get("/api/runs", dependencies=[Depends(require_permission("view_runs"))])
async def api_runs(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    ...

@app.get("/api/audit", dependencies=[Depends(require_permission("view_audit"))])
async def api_audit(...) -> list[dict]:
    ...

@app.post("/api/runs", dependencies=[Depends(require_permission("run_playbooks"))])
async def api_trigger_run(...) -> JSONResponse:
    ...
```

- [ ] **Step 3: Run the new auth tests**

Run: `python -m pytest tests/test_web_auth_sessions.py -v 2>&1 | tail -40`

Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add matteros/web/app.py matteros/web/templates/login.html
git commit -m "feat(web): replace shared token auth with per-user session login

Session middleware resolves user from cookie. Login/logout via HTML form.
require_permission() enforced on all routes. Solo mode shows setup message.
Old bootstrap URL / single token auth removed."
```

---

### Task 6: Update Templates for Per-User Nav

**Files:**
- Modify: `matteros/web/templates/base.html`

- [ ] **Step 1: Update `base.html` with user display, logout, and conditional nav**

Replace the `<nav>` section in `matteros/web/templates/base.html`:

```html
<nav>
    <h1>MatterOS</h1>
    <div style="font-size:0.75rem; color:var(--muted); margin-bottom:1rem; padding:0 0.75rem;">
        {{ request.state.user.username }} <span style="opacity:0.5">({{ request.state.user.role }})</span>
    </div>
    <a href="/" {% if request.url.path == "/" %}class="active"{% endif %}>Dashboard</a>
    {% if "view_runs" in request.state.permissions %}
    <a href="/runs" {% if "/runs" in request.url.path %}class="active"{% endif %}>Runs</a>
    <a href="/approvals" {% if "/approvals" in request.url.path %}class="active"{% endif %}>Approvals</a>
    {% endif %}
    {% if "view_drafts" in request.state.permissions %}
    <a href="/drafts" {% if "/drafts" in request.url.path %}class="active"{% endif %}>Drafts</a>
    {% endif %}
    {% if "view_audit" in request.state.permissions %}
    <a href="/audit" {% if "/audit" in request.url.path %}class="active"{% endif %}>Audit Log</a>
    {% endif %}
    {% if "manage_settings" in request.state.permissions %}
    <a href="/settings" {% if "/settings" in request.url.path %}class="active"{% endif %}>Settings</a>
    {% endif %}
    <form method="POST" action="/logout" style="margin-top:auto; padding-top:1rem;">
        <button type="submit" style="background:none; border:none; color:var(--muted); cursor:pointer; font-family:inherit; font-size:0.85rem; padding:0.5rem 0.75rem;">Logout</button>
    </form>
</nav>
```

Also update the `<nav>` CSS to use flexbox for the logout at the bottom:

```css
nav { width: 220px; background: var(--surface); border-right: 1px solid var(--border); padding: 1rem; position: fixed; height: 100vh; display: flex; flex-direction: column; }
```

- [ ] **Step 2: Verify by running the existing web auth tests**

Run: `python -m pytest tests/test_web_auth_sessions.py -v 2>&1 | tail -30`

Expected: All PASS (templates render correctly with `request.state.user` and `request.state.permissions`)

- [ ] **Step 3: Commit**

```bash
git add matteros/web/templates/base.html
git commit -m "feat(web): add user display, conditional nav, and logout to base template

Nav shows username/role, hides links based on permissions, and adds
logout button at bottom. Server-side enforcement is the real gate."
```

---

### Task 7: Update CLI Commands for New Roles and Scrypt

**Files:**
- Modify: `matteros/cli.py`

- [ ] **Step 1: Write failing test for CLI team init with new roles**

Add to `tests/test_team.py`:

```python
def test_cli_team_init_uses_scrypt(tmp_path: Path) -> None:
    """Verify that team init creates a user with scrypt hash format."""
    store = SQLiteStore(tmp_path / "test.db")
    manager = UserManager(store)
    pw_hash = hash_password("testpw")
    uid = manager.create_user(username="cliuser", role="dev", password_hash=pw_hash)
    user = manager.get_user(uid)
    assert "$" in user["password_hash"]  # scrypt format: salt$hash
```

- [ ] **Step 2: Run to verify current state**

Run: `python -m pytest tests/test_team.py::test_cli_team_init_uses_scrypt -v`

Expected: PASS (this test uses `hash_password` directly, which is already scrypt)

- [ ] **Step 3: Update `cli.py` — `team init` command**

In `matteros/cli.py`, find the `team_init` function (~line 1137). Replace:

```python
import secrets
temp_password = secrets.token_urlsafe(16)
import hashlib
password_hash = hashlib.sha256(temp_password.encode()).hexdigest()
```

With:

```python
import secrets
from matteros.team.users import hash_password
temp_password = secrets.token_urlsafe(16)
password_hash = hash_password(temp_password)
```

And replace `role="admin"` with `role="dev"`.

- [ ] **Step 4: Update `cli.py` — `team add-user` command**

In `matteros/cli.py`, find the `team_add_user` function (~line 1173). Same replacement:

```python
import secrets
temp_password = secrets.token_urlsafe(16)
import hashlib
password_hash = hashlib.sha256(temp_password.encode()).hexdigest()
```

With:

```python
import secrets
from matteros.team.users import hash_password
temp_password = secrets.token_urlsafe(16)
password_hash = hash_password(temp_password)
```

Also update the `role` option help text and default choices to reference the new roles. The `role` parameter's type hint should use the new valid roles.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/test_team.py tests/test_web_auth_sessions.py -v 2>&1 | tail -40`

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/cli.py tests/test_team.py
git commit -m "feat(cli): use scrypt hashing and new role names in team commands

team init creates 'dev' role (was 'admin'). team add-user accepts
new role names. Both use hash_password() instead of SHA-256."
```

---

### Task 8: Update Old Web Auth Tests

**Files:**
- Modify: `tests/test_web_auth.py`

- [ ] **Step 1: Rewrite `test_web_auth.py` for session-based auth**

The old tests reference `AUTH_QUERY_PARAM` and the bootstrap token, which no longer exist. Replace `tests/test_web_auth.py`:

```python
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
```

- [ ] **Step 2: Run updated tests**

Run: `python -m pytest tests/test_web_auth.py -v 2>&1 | tail -15`

Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_auth.py
git commit -m "test(web): update web auth tests for session-based login

Replace old single-token tests with session-based auth. Tests now
create a user, log in via POST /login, and use session cookies."
```

---

### Task 9: Full Test Suite Verification

**Files:** None (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v --tb=short 2>&1 | tail -80`

Expected: All tests pass. Pay attention to any tests that relied on the old `AUTH_QUERY_PARAM` or `app.state.web_token`.

- [ ] **Step 2: Check for any remaining references to old auth**

Run: `grep -rn "AUTH_QUERY_PARAM\|AUTH_COOKIE_NAME\|web_token\|auth_query_param\|auth_cookie_name" matteros/ tests/ --include="*.py"`

Expected: No matches (all old references removed).

- [ ] **Step 3: Run security-specific test subset**

Run: `python -m pytest tests/test_web_auth_sessions.py -v 2>&1`

Verify all 16 tests pass, covering spec security test cases:
- Unauthenticated redirect
- Expired session
- Permission denial (paralegal can't trigger run, can't view audit; solicitor can't access settings)
- Solo mode setup message
- Legacy SHA-256 rejection
- Cookie httponly property
- Login/logout flow

- [ ] **Step 4: Commit any fixes**

If any tests failed in step 1, fix and commit. Otherwise skip this step.

```bash
git add -A
git commit -m "fix: resolve test failures from auth migration"
```
