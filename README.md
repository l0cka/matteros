# MatterOS

MatterOS is an open-source, self-hosted legal ops command center.

Track contracts, requests, and compliance deadlines in one place — with privilege-aware access controls, auditable logging, and smart automation.

## Why it exists

Legal teams are drowning in work scattered across email, Slack, Jira, and spreadsheets. MatterOS gives a lean legal team:

- a single queue of everything that needs attention
- deadline tracking that won't let things slip
- privilege-aware access controls so sensitive matters stay protected
- an auditable record of what changed, when, and why

## What MatterOS can do today

- **Matter management** — create, track, and resolve matters (contracts, requests, compliance) with flexible metadata
- **My Queue** — see what's assigned to you, sorted by urgency, with overdue alerts
- **Deadline tracking** — first-class deadlines with overdue/upcoming views
- **Activity threads** — comment on matters, track status changes with full audit trail
- **Privilege controls** — privileged matters are invisible to non-legal users, redacted in audit logs, and never sent to external systems
- **Per-matter authorization** — legal/GC roles with contact-scoped visibility for business stakeholders
- **Hash-chained audit logs** in SQLite + JSONL with verification CLI
- **Connectors** — Jira, Slack, Microsoft Graph, GitHub, filesystem, and plugin SDK
- **Web dashboard** — FastAPI + HTMX, no Node.js required
- **TUI dashboard** + CLI for power users
- **Background daemon** — scheduler + activity watcher
- **LLM triage** — classify and route incoming matters (no content generation)

## Install

### Homebrew

```bash
brew tap danielalkurdi/matteros
brew install matteros
```

### Source install (recommended for full feature set)

```bash
git clone https://github.com/danielalkurdi/matteros.git
cd matteros
python -m venv .venv
source .venv/bin/activate
pip install -e '.[all,dev]'
```

### Python fallback (CLI-focused)

```bash
pipx install git+https://github.com/danielalkurdi/matteros.git
```

More install options: [docs/INSTALL.md](./docs/INSTALL.md)

## Quick start (5 minutes)

```bash
matteros init
matteros team init --admin admin
matteros web --open
```

Log in with the temporary password printed by `team init`, then:

1. **My Queue** shows matters assigned to you
2. Click **New Matter** to create your first matter
3. **Deadlines** shows what's coming up
4. **All Matters** shows everything with filters

## Interfaces

### CLI

```bash
matteros --help
```

### TUI

```bash
matteros tui
```

If `textual` is missing:

```bash
pip install -e '.[tui]'
```

### Web dashboard

```bash
matteros web --open
```

Opens the matter management UI at `http://127.0.0.1:8741`. Views: My Queue, All Matters, Deadlines, Matter Detail with activity threads.

If web dependencies are missing:

```bash
pip install -e '.[web]'
```

### Daemon

```bash
matteros daemon start
matteros daemon status
matteros daemon logs --lines 100
```

## Team mode

```bash
matteros team init --admin admin
matteros team add-user alice --role legal
matteros team list-users
```

Roles: `legal` (full matter access) and `gc` (legal + user management + dashboards).

## Safety model

- **Privilege-first** — matters default to privileged; exposure requires explicit action
- **Privilege-aware audit** — privileged matter content is never logged in plain text
- **Per-matter authorization** — contacts see only non-privileged matters they're linked to
- **LLM boundary** — LLM triage receives only metadata, never substance; privileged titles are replaced with generic labels
- Audit events are append-only and hash-linked
- `matteros audit verify` validates chain integrity
- Remote LLMs are opt-in; local provider is default

Deep dive docs:

- [docs/policy-model.md](./docs/policy-model.md)
- [docs/audit-schema.md](./docs/audit-schema.md)
- [docs/threat-model.md](./docs/threat-model.md)
- [docs/connector-specs.md](./docs/connector-specs.md)

## LLM configuration

Core env vars:

- `MATTEROS_MODEL_PROVIDER`: `local` (default), `openai`, `anthropic`
- `MATTEROS_ALLOW_REMOTE_MODELS`: must be `true` for remote providers
- `MATTEROS_LLM_MODEL_ALLOWLIST`: optional comma-separated allowlist
- `MATTEROS_LLM_MAX_RETRIES`, `MATTEROS_LLM_RETRY_BACKOFF_SECONDS`
- `MATTEROS_LLM_TIMEOUT_SECONDS`

Provider keys:

- OpenAI: `OPENAI_API_KEY` (optional `OPENAI_MODEL`, `OPENAI_BASE_URL`)
- Anthropic: `ANTHROPIC_API_KEY` (optional `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_VERSION`)

Doctor command:

```bash
matteros llm doctor
```

## External provider contract tests (VCR)

Skipped by default.

Replay cassettes:

```bash
MATTEROS_RUN_EXTERNAL_TESTS=1 MATTEROS_VCR_RECORD_MODE=none pytest -q -m external
```

Record/update cassettes:

```bash
MATTEROS_RUN_EXTERNAL_TESTS=1 MATTEROS_VCR_RECORD_MODE=once pytest -q -m external
```

## License

AGPLv3 (`AGPL-3.0-only`).
