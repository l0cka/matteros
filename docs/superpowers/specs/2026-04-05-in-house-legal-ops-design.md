# MatterOS: In-House Legal Ops Redesign

## Overview

Redesign MatterOS from a playbook-driven legal ops tool (focused on time capture for private law firms) into a matter management platform for lean in-house legal teams. The core problem: small legal teams are drowning in contracts, business requests, and compliance deadlines, tracking everything across email, spreadsheets, and Slack.

## Primary User

The working in-house lawyer (2-3 person team). The system also serves the GC (dashboard/visibility) and business stakeholders (request status via Jira), but the working lawyer's daily experience anchors all design decisions.

## Core Workflows

1. **Contract lifecycle** — tracking agreements through review, approval, signature, renewal
2. **Request triage** — business throws requests at legal; track what's open, who's handling it, don't drop things
3. **Compliance & deadlines** — regulatory filings, board governance, entity management; don't miss the thing that gets you fined

## Domain Model

### Matter

The central unit of work. All three workflows (contracts, requests, compliance) are matters with different shapes.

- `id` — unique identifier
- `title` — short description
- `type` — contract, request, compliance, or custom
- `status` — new, in_progress, on_hold, resolved
- `assignee` — legal team member
- `created_at`, `due_date`, `priority`
- `privileged: bool` — controls visibility and logging behavior
- `metadata: dict` — flexible key-value for type-specific fields (counterparty, contract value, jurisdiction, renewal date, etc.)
- `relationships: list` — links to other matters (e.g., "renewal of", "triggered by", "blocks")
- `source` — how it was created (manual, jira, email, slack)

Status workflow is universal: `new` -> `in_progress` -> `resolved` / `on_hold`. No complex per-type state machines. The meaning comes from the type and metadata, not the status.

### Activity

Things that happen on a matter: comments, status changes, file attachments, deadline updates.

- Each activity has a `visibility` flag: `internal` (legal-only) or `external` (visible to business stakeholders)
- Privileged matters only allow `internal` activities by default

### Contact

Business stakeholders who submit requests or are parties to contracts.

- Lightweight: name, email, department
- Can view status/due dates on non-privileged matters they're linked to, but never substance

### Deadline

First-class entity, not just a date field on a matter.

- Linked to a matter
- `type`: hard or soft
- `alert_before` period (configurable)
- Supports recurring deadlines (annual filings, renewal dates)
- Auto-generates next occurrence when the current one resolves

### Matter Relationships

Matters can link to other matters with typed relationships. A contract renewal links to the original agreement, the business request that triggered it, and the compliance filing it affects. The UI starts simple (flat list) and surfaces relationships progressively.

## Views

### For the working lawyer

1. **My Queue** (default landing page) — assigned matters sorted by urgency. Overdue first, then by due date. The "open MatterOS, see what needs attention" experience.
2. **All Matters** — filterable/searchable list. Filter by type, status, assignee, due date range.
3. **Deadlines** — calendar-style view of upcoming deadlines across all matters. The "what's coming at us this week/month" view.
4. **Matter Detail** — title, status, metadata, activity thread, linked matters, deadlines, files.

### For the GC

Same as legal team views, plus team-wide dashboards and deadline overview.

### For business stakeholders

No MatterOS access. Status syncs back to Jira (see below).

## Jira Integration

Business submits requests via a Jira project they already use. MatterOS syncs those tickets in as matters, legal works them in MatterOS, and status updates push back to Jira.

- **Inbound:** New Jira ticket in the legal project -> auto-creates a matter in MatterOS
- **Outbound:** Status changes in MatterOS -> update the Jira ticket status
- **Privilege boundary:** Only status and due date sync back to Jira. Activity, comments, and privileged content stay in MatterOS. Enforced at the connector level.

## Automation

### 1. Intake

- **Jira sync** — new tickets become matters
- **Email intake** — emails to a designated address create matters. Subject becomes title, sender becomes contact, body stored as first activity (marked `internal`)
- **Slack** — messages in a legal request channel create matters via the Slack connector

### 2. Deadline Alerts

- Configurable alert windows (e.g., 30/14/7/1 days before)
- Delivered via Slack notification, email digest, or surfaced in My Queue
- Recurring deadlines auto-generate the next occurrence when resolved

### 3. Stale Matter Detection

- "No activity in X days" nudges for in-progress matters
- Configurable per matter type (contracts tolerate longer gaps than requests)

### 4. Smart Triage (LLM-assisted, privilege-safe)

- On intake, suggest: matter type, priority, likely assignee based on past patterns
- Classification and routing only. No content generation, no drafting.
- LLM only sees non-privileged metadata (title, type, source). Never substance.
- For privileged matters: title is replaced with a generic label before LLM processing

## Privilege & Access Model

### Matter-level privilege

- `privileged: true` set at creation. Default for manually created matters, configurable per intake source.
- Privileged matters are invisible to business stakeholders — not redacted, absent.
- Privilege can be downgraded (privileged -> non-privileged) but upgrading requires confirmation since activities may have already been exposed.

### Access tiers

- **Legal team** — sees everything. Full activity thread, metadata, relationships.
- **GC / head of legal** — same as legal team, plus team-wide dashboards.
- **Business stakeholder** — sees only non-privileged matters they're linked to as a contact. Status, due date, title only. No activity, files, or comments. Served via Jira sync, not MatterOS UI.

### Audit logging

- All access to privileged matters is logged (who viewed what, when)
- Privileged matter content is never logged in plain text — only matter ID and action type
- Jira sync and Slack notifications never include privileged matter content

### LLM boundary

- LLM triage receives only: title, type, source, priority
- For privileged matters: title replaced with "Privileged matter #[id]"
- No matter substance ever reaches the LLM

## Database Schema

The existing playbook-centric tables (`runs`, `steps`, `approvals`) are replaced by first-class matter tables. This is a hard prerequisite — no feature work begins until these tables exist and the web/API layer reads from them.

### Tables

**matters**
```
id              TEXT PRIMARY KEY
title           TEXT NOT NULL
type            TEXT NOT NULL  -- contract, request, compliance, custom
status          TEXT NOT NULL DEFAULT 'new'  -- new, in_progress, on_hold, resolved
assignee_id     TEXT REFERENCES users(id)
priority        TEXT DEFAULT 'medium'  -- low, medium, high, urgent
privileged      INTEGER NOT NULL DEFAULT 1  -- privilege-first: default protected
source          TEXT  -- manual, jira, email, slack
source_ref      TEXT  -- external ID (e.g., Jira ticket key)
metadata_json   TEXT  -- flexible key-value for type-specific fields
created_at      TEXT NOT NULL
updated_at      TEXT NOT NULL
due_date        TEXT
resolved_at     TEXT
```

**activities**
```
id              INTEGER PRIMARY KEY AUTOINCREMENT
matter_id       TEXT NOT NULL REFERENCES matters(id)
actor_id        TEXT REFERENCES users(id)
type            TEXT NOT NULL  -- comment, status_change, file_attach, deadline_update, assignment
visibility      TEXT NOT NULL DEFAULT 'internal'  -- internal, external
content_json    TEXT  -- activity payload (redacted in audit, see below)
created_at      TEXT NOT NULL
```
- On privileged matters, visibility is forced to `internal` at write time — the application layer does not rely on callers to set this correctly.

**contacts**
```
id              TEXT PRIMARY KEY
name            TEXT NOT NULL
email           TEXT NOT NULL UNIQUE
department      TEXT
created_at      TEXT NOT NULL
```

**matter_contacts**
```
matter_id       TEXT NOT NULL REFERENCES matters(id)
contact_id      TEXT NOT NULL REFERENCES contacts(id)
role            TEXT DEFAULT 'requestor'  -- requestor, counterparty, stakeholder
PRIMARY KEY (matter_id, contact_id)
```

**deadlines**
```
id              INTEGER PRIMARY KEY AUTOINCREMENT
matter_id       TEXT NOT NULL REFERENCES matters(id)
label           TEXT NOT NULL
due_date        TEXT NOT NULL
type            TEXT NOT NULL DEFAULT 'hard'  -- hard, soft
alert_before    TEXT  -- ISO 8601 duration (e.g., P14D, P30D)
recurring       TEXT  -- recurrence rule (e.g., P1Y for annual)
status          TEXT NOT NULL DEFAULT 'pending'  -- pending, completed, missed
created_at      TEXT NOT NULL
```

**matter_relationships**
```
id              INTEGER PRIMARY KEY AUTOINCREMENT
source_id       TEXT NOT NULL REFERENCES matters(id)
target_id       TEXT NOT NULL REFERENCES matters(id)
type            TEXT NOT NULL  -- renewal_of, triggered_by, blocks, related_to
created_at      TEXT NOT NULL
UNIQUE (source_id, target_id, type)
```

### Migration strategy

- New tables are added via the existing migration runner in `matteros/core/migrations/`.
- The old `runs`, `steps`, and `approvals` tables are retained but deprecated — no new code reads from them. They can be dropped in a future release.
- The web/API layer is rewritten to query `matters`/`activities`/`deadlines` instead of `runs`/`steps`.

## Privilege-Aware Audit Logging

The current audit logger (`matteros/core/audit.py`) writes full event payloads as plaintext JSON into both SQLite and the JSONL audit file. This violates the privilege boundary. The audit system must be redesigned before any matter data flows through it.

### Redaction model

Audit events are split into two categories at write time:

**Safe metadata (always logged in full):**
- Matter ID, event type, actor ID, timestamp
- Status changes (old status, new status)
- Assignment changes (old assignee, new assignee)
- Deadline created/updated/completed (deadline ID, due date)
- Access events (matter ID, accessor ID, action)

**Sensitive content (redacted for privileged matters):**
- Activity content (comments, notes)
- Matter metadata values (counterparty names, contract values)
- File attachment names and content
- Email/Slack message bodies from intake

### Implementation

- The audit logger receives a `privileged: bool` flag with every event.
- When `privileged=True`, the `data_json` field stores only the safe metadata fields listed above. Sensitive content is omitted entirely — not masked, not hashed, not stored.
- When `privileged=False`, the full payload is logged as today.
- The JSONL audit file follows the same rules. Hash chaining continues to work — it chains over whatever payload is written, redacted or not.
- A new audit event type `privileged_access` logs every read of a privileged matter: `{matter_id, accessor_id, action, timestamp}`. No content.

### Connector-level enforcement

- Jira sync connector: only emits status and due_date fields, never activity content. For privileged matters, sync is disabled entirely.
- Slack notification connector: messages contain only matter ID, status, and due date. Privileged matters produce no Slack notifications.
- These boundaries are enforced in the connector implementations, not in the UI or API layer.

## Authorization Model

The current role-based system (`dev`, `reviewer`, etc. with global permissions like `view_runs`) cannot express contact-scoped visibility. It must be replaced with a subject-plus-object authorization model.

### Subjects

- **Legal team member** — a user with role `legal`. Full access to all matters.
- **GC** — a user with role `gc`. Same as legal, plus team dashboards.
- **Contact** — a contact record (not a user). No MatterOS login. Visibility is expressed through the Jira sync boundary, not through direct access.

### Authorization rules

All matter access is evaluated per-matter, not by global role:

1. **Legal team / GC** — can read/write all matters, all activities, all metadata. No restrictions.
2. **Contact visibility** (for Jira sync / future API) — a contact can see a matter only if:
   - The matter is linked to them in `matter_contacts`, AND
   - The matter has `privileged = false`
   - Visible fields: `title`, `status`, `due_date`, `priority` only. No activities, metadata, files, or relationships.
3. **Privileged matters** — invisible to contacts entirely. The Jira sync skips them. No status, no title, no acknowledgment of existence.

### Enforcement points

- **Web API layer** — every matter query filters by the requesting user's authorization. Legal/GC users see all; contacts (if a future portal is added) see only linked non-privileged matters with field projection.
- **Jira sync connector** — evaluates `privileged` and `matter_contacts` before syncing any status update. Privileged matters are never synced.
- **Audit logger** — logs all access to privileged matters as `privileged_access` events (see above).

### Migration from current auth

- Existing roles (`dev`, `reviewer`) map to `legal`.
- The `admin` role maps to `gc`.
- Contact records are a new entity — no existing users need migration.
- The permission strings (`view_runs`, `view_audit`, etc.) are replaced with the matter-level rules above. Old permission checks in the web layer are removed.

## Architecture

### Retained from current codebase

- **SQLite store** — hash-chained audit verification retained
- **Connector framework** — Jira, Slack, email, filesystem connectors already exist
- **Event bus** — real-time updates
- **Web layer** — FastAPI + HTMX + Jinja2 (no Node.js)
- **LLM adapter** — used only for triage classification
- **Daemon** — background automation

### Rethought

- **Domain model** — new tables (`matters`, `activities`, `contacts`, `deadlines`, `matter_relationships`) replace playbook-centric `runs`/`steps` tables. See Database Schema section.
- **Audit logger** — privilege-aware redaction at write time. See Privilege-Aware Audit Logging section.
- **Authorization** — subject-plus-object model replacing global role permissions. See Authorization Model section.
- **Runner -> Automation Engine** — step-based runner becomes event-driven. Instead of "run a playbook," it's "when a Jira ticket is created, execute the intake automation."
- **Playbooks become internal** — YAML playbook concept can still exist for defining automation recipes, but users never see or edit them. Automations configured through the web UI.

### Build sequence

These must be implemented in order — each layer depends on the previous:

1. **Database schema + migrations** — matter tables, contact tables, deadline tables, relationship tables
2. **Privilege-aware audit logger** — redaction model, privileged_access events, connector-level enforcement
3. **Authorization model** — subject-plus-object evaluation, per-matter access checks
4. **Core matter CRUD** — create/read/update matters, activities, deadlines, contacts
5. **Web UI** — My Queue, All Matters, Deadlines, Matter Detail views
6. **Automation engine** — intake (Jira/email/Slack), deadline alerts, stale detection, LLM triage
7. **Jira sync** — bidirectional sync with privilege boundary enforcement

### Deployment

- Self-hosted, single binary spirit. SQLite, no external database.
- Sensitive data never leaves the server except through explicit connector sync (non-privileged metadata only).

## Design Constraints

- **No LLM drafting of legal responses** — keeps the lawyer in the loop, avoids privilege waiver risks
- **Privilege-first** — default to protected; exposure requires explicit action
- **Meet the business where they are** — Jira for status, not another portal
- **Low adoption friction** — should feel simpler than a spreadsheet, not more complex
