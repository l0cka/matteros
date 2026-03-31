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

**Password hashing:** `hashlib.scrypt` (stdlib). Used consistently in both CLI (`matteros team add-user`, `matteros team init`) and web login verification.

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

## Future: OAuth/OIDC

The session middleware resolves a user from a session cookie. A future OIDC integration would add an alternative path to *create* a session (via OAuth callback) — the rest of the system (permission matrix, route enforcement, templates) remains unchanged. This is a planned future milestone.
