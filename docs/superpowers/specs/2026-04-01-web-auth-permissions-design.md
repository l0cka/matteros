# Web Auth & Permission Enforcement Design

**Date:** 2026-04-01
**Scope:** Per-user web authentication and role-based permission enforcement for MatterOS web dashboard.

## Summary

Replace the single shared token auth in MatterOS web with per-user login (username + password) and role-based permission enforcement across all web routes. Sessions stored in SQLite. Five legal-team roles with an explicit permission matrix. No new dependencies.

Future milestone: add OAuth/OIDC as an alternative session creation mechanism (the permission system stays the same).

## Roles

Five roles stored as strings in the `users.role` column:

| Role | Slug | Who |
|------|------|-----|
| Dev | `dev` | System administrator / technical operator |
| Partner / GC | `partner_gc` | General Counsel or Partner — business owner |
| Senior Solicitor | `sr_solicitor` | Senior lawyer — supervisory |
| Solicitor | `solicitor` | Day-to-day lawyer |
| Paralegal / Legal Admin | `paralegal` | Support staff |

## Permission Matrix

| Action key | `dev` | `partner_gc` | `sr_solicitor` | `solicitor` | `paralegal` |
|---|---|---|---|---|---|
| `manage_users` | yes | | | | |
| `manage_settings` | yes | yes | | | |
| `run_playbooks` | yes | yes | yes | yes | |
| `create_drafts` | yes | yes | yes | yes | yes |
| `approve_own` | yes | yes | yes | yes | |
| `approve_others` | yes | yes | yes | | |
| `view_runs` | yes | yes | yes | yes | yes |
| `view_audit` | yes | yes | yes | yes | |
| `view_reports` | yes | yes | yes | | |
| `view_drafts` | yes | yes | yes | yes | yes |

This matrix is defined as a dict-of-sets in `matteros/team/users.py`.

## Session Management

### Sessions table

New SQLite table added via migration `v004_sessions.py`:

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
```

- Session ID: `secrets.token_urlsafe(32)`
- Stored in `matteros_session` httponly cookie (reuses existing cookie name)
- Expires after 24 hours
- Deleted on logout or expiry

## Auth Middleware

Replaces the current single-token middleware in `app.py`.

**Flow for every request:**

1. Read `matteros_session` cookie
2. Look up session row in SQLite
3. If valid and not expired: attach user dict to `request.state.user`, continue
4. If invalid/missing/expired and path is not `/login`: redirect to `GET /login`
5. `/login` is the only unauthenticated route

## Login Flow

1. `GET /login` — renders `login.html` (username + password form)
2. `POST /login` — verify password hash against `users.password_hash` → create session row → set httponly cookie → redirect to `/`
3. `POST /logout` — delete session row → clear cookie → redirect to `/login`
4. Failed login — re-render `login.html` with error message

**Password hashing:** `hashlib.scrypt` (stdlib) with a random 16-byte salt. Used consistently in both CLI (`matteros team add-user`, `matteros team init`) and web login verification. The hash is stored as `salt_hex$scrypt_hex` in the `password_hash` column.

**Migrating existing SHA-256 hashes:** The current CLI stores unsalted `hashlib.sha256` hashes. The migration (`v004_sessions.py`) does NOT auto-convert these — there is no way to rehash without the plaintext password. Instead, existing users with SHA-256 hashes will be unable to log in via the web. The admin must re-run `matteros team add-user` to reset their credentials with scrypt. The login verification function detects the hash format (`$` separator = scrypt, otherwise legacy SHA-256 rejected).

**Solo mode:** When no users exist in the DB, the web app renders a message directing the user to run `matteros team init`. No bootstrap URL backdoor.

## Permission Enforcement

### FastAPI dependency

A `require_permission(action: str)` function returns a FastAPI `Depends` callable:

1. Reads `request.state.user` (set by middleware)
2. Looks up user's role
3. Checks against the permission matrix
4. Returns 403 if denied

### Route-to-action mapping

| Route | Action |
|---|---|
| `GET /` (dashboard) | authenticated (any role) |
| `GET /runs`, `GET /runs/{id}` | `view_runs` |
| `POST /api/runs` | `run_playbooks` |
| `GET /runs/new` | `run_playbooks` |
| `GET /drafts` | `view_drafts` |
| `POST /drafts/{id}/approve`, `/reject` | `approve_others` or `approve_own` if own draft |
| `GET /audit` | `view_audit` |
| `GET /settings` | `manage_settings` |
| `GET /api/runs` | `view_runs` |
| `GET /api/audit` | `view_audit` |

### Template-level hiding

Templates receive the user's permission set to conditionally show/hide nav links and action buttons. Server-side checks are the real gate; template hiding is UX only.

## Migration & Backward Compatibility

### Database migration (`v004_sessions.py`)

- Creates `sessions` table
- Maps existing roles: `admin` → `dev`, `attorney` → `solicitor`, `reviewer` → `sr_solicitor`

### Code changes

- `matteros/team/users.py`: update `VALID_ROLES`, update `check_permission()` to use new matrix
- `matteros/web/app.py`: replace single-token middleware with session middleware, add `require_permission` to routes, add login/logout endpoints, remove bootstrap URL logic
- `matteros/web/templates/login.html`: new template
- `matteros/web/templates/base.html`: add user display, logout link, conditional nav
- `matteros/cli.py`: update `team init` and `team add-user` for new role names, use scrypt hashing

### No new dependencies

Uses `hashlib`, `secrets`, `os` from stdlib plus existing FastAPI/Jinja2.

## Security Test Cases

The following paths must have test coverage before this milestone ships:

1. **Unauthenticated redirect** — requests without a valid session cookie to any route (except `/login`) return a redirect to `/login`, not a 200 or data leak.
2. **Expired session** — a session past `expires_at` is treated as unauthenticated; the row is cleaned up.
3. **Permission denial** — each role is tested against at least one route it cannot access (e.g., `paralegal` cannot `POST /api/runs`), confirming a 403 response.
4. **Own-vs-others draft approval** — a `solicitor` can approve their own draft but gets 403 when approving another user's draft. A `sr_solicitor` can approve both.
5. **Solo mode (no users)** — when the `users` table is empty, all web routes return the "run `matteros team init`" message, not a crash or unprotected dashboard.
6. **Legacy SHA-256 hash rejection** — a user whose `password_hash` is an old unsalted SHA-256 hex string cannot log in; they get a clear error.
7. **Session cookie properties** — cookie is `httponly` and `samesite=strict`.

## Future: OAuth/OIDC

The session middleware resolves a user from a session cookie. A future OIDC integration would add an alternative path to *create* a session (via OAuth callback) — the rest of the system (permission matrix, route enforcement, templates) remains unchanged. This is a planned future milestone.
