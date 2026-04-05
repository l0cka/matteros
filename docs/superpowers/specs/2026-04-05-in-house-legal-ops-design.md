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

## Architecture

### Retained from current codebase

- **SQLite store + audit logger** — hash-chained, verified
- **Connector framework** — Jira, Slack, email, filesystem connectors already exist
- **Event bus** — real-time updates
- **Web layer** — FastAPI + HTMX + Jinja2 (no Node.js)
- **LLM adapter** — used only for triage classification
- **Daemon** — background automation

### Rethought

- **Domain model** — new tables (`matters`, `activities`, `contacts`, `deadlines`, `matter_relationships`) replace playbook-centric `runs`/`steps` tables
- **Runner -> Automation Engine** — step-based runner becomes event-driven. Instead of "run a playbook," it's "when a Jira ticket is created, execute the intake automation."
- **Playbooks become internal** — YAML playbook concept can still exist for defining automation recipes, but users never see or edit them. Automations configured through the web UI.

### Deployment

- Self-hosted, single binary spirit. SQLite, no external database.
- Sensitive data never leaves the server except through explicit connector sync (non-privileged metadata only).

## Design Constraints

- **No LLM drafting of legal responses** — keeps the lawyer in the loop, avoids privilege waiver risks
- **Privilege-first** — default to protected; exposure requires explicit action
- **Meet the business where they are** — Jira for status, not another portal
- **Low adoption friction** — should feel simpler than a spreadsheet, not more complex
