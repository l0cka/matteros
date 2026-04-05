# MatterOS: Automation Engine

## Overview

An event-driven automation engine that polls external sources (Jira, Slack) for intake, monitors deadlines, and detects stale matters. Runs inside the existing daemon. Polling-based for V1, but handlers are structured so webhook triggers can be added later without rewriting them.

## Scope

**In scope:**
- Jira intake (poll for new issues, create matters)
- Slack intake (poll channel for messages, create matters)
- Deadline alerts (overdue detection, configurable alert windows, Slack notifications)
- Stale matter detection (configurable thresholds per type, nudge activities, Slack alerts)
- Recurring deadline auto-generation

**Out of scope (deferred):**
- Email intake
- LLM triage (auto-classify type/priority/assignee)
- Webhook endpoints (V2)
- Outbound Slack status updates from intake

## Architecture

### AutomationEngine

Runs inside the existing `DaemonRunner`. Manages four handler types on independent poll schedules:

1. **Intake handlers** — poll Jira/Slack for new items, create matters
2. **Deadline checker** — scan deadlines, mark overdue, send alerts
3. **Stale detector** — scan matters with no recent activity, create nudges

Each handler is a plain function: `(MatterStore, AutomationState, config) -> list[str]` returning descriptions of actions taken. The engine calls them on a schedule. Handlers don't know whether they were triggered by a poll or a webhook — this makes webhook support a drop-in addition later.

### Configuration

Lives in `config.yml` under an `automations` key:

```yaml
automations:
  jira_intake:
    enabled: true
    project_key: "LEG"
    poll_interval_minutes: 5
    default_privileged: false
  slack_intake:
    enabled: true
    channel: "legal-requests"
    poll_interval_minutes: 5
    default_privileged: false
  deadline_alerts:
    enabled: true
    check_interval_minutes: 60
    alert_windows_days: [30, 14, 7, 1]
    slack_channel: "legal-alerts"
  stale_detection:
    enabled: true
    check_interval_minutes: 120
    thresholds:
      request: 7
      contract: 14
      compliance: 30
      default: 14
    slack_channel: "legal-alerts"
```

## Jira Intake

### Poll cycle

1. Read last poll timestamp from `automation_state` (key: `jira_intake:last_poll`)
2. Query Jira for issues in the configured project updated since that timestamp
3. For each issue not already tracked (checked via `source_ref` matching Jira issue key):
   - Create a matter: title from summary, type=`request`, source=`jira`, source_ref=`LEG-123`, privileged per config default
   - Create or link a contact from the reporter (matched by email)
   - Store the Jira description as the first activity (marked `internal`)
4. For existing matters with a Jira `source_ref`:
   - If the matter's status changed in MatterOS, push status back to Jira (outbound sync)
   - Skip privileged matters entirely — no outbound sync
5. Update last poll timestamp

### Deduplication

The `source_ref` field is the dedup key. Before creating a matter, check if one exists with that `source_ref`. Polling the same issue twice is a no-op.

### Privilege boundary

- Matters from Jira default to `privileged: false` (configurable)
- Outbound sync only sends status and due_date — never activity content, metadata, or comments
- Privileged matters are never synced outbound

## Slack Intake

### Poll cycle

1. Read last poll timestamp from `automation_state` (key: `slack_intake:last_poll`)
2. Poll Slack channel history for messages since last check (using the existing `SlackConnector`)
3. For each new message not already tracked (dedup by `source_ref` = `<channel_id>:<ts>`):
   - Create a matter: title from first line of message (truncated to 120 chars), type=`request`, source=`slack`, source_ref=`<channel_id>:<ts>`, privileged per config default
   - Create or link a contact from the Slack user profile (name + email)
   - Store the full message as the first activity (marked `internal`)
4. Ignore bot messages, thread replies, and reactions — only top-level human messages create matters
5. Update last poll timestamp

### Privilege boundary

- Matters from Slack default to `privileged: false` (configurable)
- No outbound sync to Slack from intake

## Deadline Checker

### Check cycle

1. Runs on schedule (default: every 60 minutes)
2. Query all pending deadlines
3. For each deadline:
   - If `due_date` has passed: mark status as `missed`, add activity ("Deadline missed: {label}"), send Slack alert
   - If `due_date` is within any configured alert window (30/14/7/1 days): send Slack alert, add activity ("Deadline approaching: {label} — due in {N} days")

### Deduplication

Track sent alerts in `automation_state` with key `deadline_alert:{deadline_id}:{window}`. Same alert is not repeated across poll cycles.

### Recurring deadlines

When a deadline is completed (via the web UI's `complete_deadline`), if it has a `recurring` value (e.g., `P1Y`), auto-create the next deadline with the due date advanced by that interval. This logic lives in the `MatterStore.complete_deadline` method, not in the automation engine.

### Privilege boundary

Slack alerts for privileged matters include only "Deadline approaching for matter #[id]" — no title, no label, no substance.

## Stale Matter Detection

### Check cycle

1. Runs on schedule (default: every 2 hours)
2. Query all matters with status `in_progress` or `new`
3. For each matter, check the timestamp of the most recent activity
4. If no activity within the threshold for that matter type:
   - request: 7 days
   - contract: 14 days
   - compliance: 30 days
   - default: 14 days
5. For stale matters:
   - Add an activity: type=`nudge`, content=`{"text": "No activity for {N} days"}`
   - Send Slack alert

### Deduplication

The nudge activity itself counts as activity. After a nudge fires, the next nudge won't trigger until another full threshold period passes with no other activity. No separate dedup tracking needed.

### Privilege boundary

Slack alerts for privileged matters say "Matter #[id] has had no activity for {N} days" — no title or substance.

## Database

### New table (v006 migration)

```
automation_state
  key         TEXT PRIMARY KEY
  value       TEXT NOT NULL
  updated_at  TEXT NOT NULL
```

Used for:
- Poll cursors: `jira_intake:last_poll`, `slack_intake:last_poll`
- Alert dedup: `deadline_alert:{deadline_id}:{window}`

### Deadline missed status

The existing `deadlines` table already has a `status` field with values `pending`, `completed`. The deadline checker adds a third value: `missed`.

## File Structure

| Path | Responsibility |
|------|---------------|
| `matteros/automation/__init__.py` | Package init |
| `matteros/automation/engine.py` | AutomationEngine: manages poll schedules, dispatches handlers |
| `matteros/automation/intake.py` | Jira and Slack intake handler functions |
| `matteros/automation/deadlines.py` | Deadline checker handler |
| `matteros/automation/stale.py` | Stale matter detection handler |
| `matteros/automation/state.py` | AutomationState: read/write helpers for automation_state table |
| `matteros/core/migrations/v006_automation_state.py` | Migration for automation_state table |

## Integration with Existing Daemon

The `DaemonRunner` currently owns an `EventBus`, `PlaybookScheduler`, and `ActivityWatcher`. The `AutomationEngine` is added alongside them. The daemon starts it; the engine manages its own poll timers. The old scheduler/watcher stay for backwards compatibility with the CLI's playbook functionality.

## Slack Notification Helper

A shared utility used by deadline alerts and stale detection to send Slack messages. Uses the existing `SlackConnector` for delivery. Handles the privilege boundary: checks the matter's `privileged` flag and redacts accordingly before sending.

## Design Constraints

- **Privilege-first** — Slack alerts never contain privileged matter content
- **Idempotent handlers** — polling the same data twice produces no duplicates
- **No LLM in V1** — matters arrive with sensible defaults, lawyer triages manually
- **Webhook-ready** — handlers don't know their trigger source, making webhook endpoints a future drop-in
