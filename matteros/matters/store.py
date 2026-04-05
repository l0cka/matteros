"""MatterStore — CRUD layer for matter management tables."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from matteros.core.store import SQLiteStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MatterStore:
    def __init__(self, db: SQLiteStore):
        self._db = db

    # ── Matters ──────────────────────────────────────────────────────

    def create_matter(
        self,
        *,
        title: str,
        type: str,
        priority: str = "medium",
        privileged: bool = True,
        source: str | None = None,
        source_ref: str | None = None,
        metadata: dict | None = None,
        due_date: str | None = None,
        assignee_id: str | None = None,
    ) -> str:
        matter_id = uuid.uuid4().hex[:12]
        now = _now()
        metadata_json = json.dumps(metadata) if metadata is not None else None
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO matters
                    (id, title, type, status, priority, privileged, source,
                     source_ref, metadata_json, due_date, assignee_id,
                     created_at, updated_at)
                VALUES (?, ?, ?, 'new', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    matter_id, title, type, priority, int(privileged),
                    source, source_ref, metadata_json, due_date, assignee_id,
                    now, now,
                ),
            )
            conn.commit()
        return matter_id

    def get_matter(self, matter_id: str) -> dict[str, Any] | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM matters WHERE id = ?", (matter_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("metadata_json"):
            result["metadata"] = json.loads(result["metadata_json"])
        return result

    def update_matter(self, matter_id: str, **fields: Any) -> None:
        allowed = {
            "title", "type", "status", "assignee_id", "priority",
            "privileged", "due_date", "metadata", "resolved_at",
        }
        to_set: dict[str, Any] = {}
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(f"field not allowed: {k}")
            if k == "metadata":
                to_set["metadata_json"] = json.dumps(v) if v is not None else None
            elif k == "privileged":
                to_set["privileged"] = int(v)
            else:
                to_set[k] = v

        to_set["updated_at"] = _now()

        set_clause = ", ".join(f"{col} = ?" for col in to_set)
        values = list(to_set.values()) + [matter_id]

        with self._db.connection() as conn:
            cursor = conn.execute(
                f"UPDATE matters SET {set_clause} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError("not found")
            conn.commit()

    def list_matters(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        assignee_id: str | None = None,
        source_ref: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if type is not None:
            clauses.append("type = ?")
            params.append(type)
        if assignee_id is not None:
            clauses.append("assignee_id = ?")
            params.append(assignee_id)
        if source_ref is not None:
            clauses.append("source_ref = ?")
            params.append(source_ref)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        with self._db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM matters{where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Activities ───────────────────────────────────────────────────

    def add_activity(
        self,
        *,
        matter_id: str,
        actor_id: str | None = None,
        type: str,
        content: dict | None = None,
        visibility: str = "internal",
    ) -> int:
        # If matter is privileged, force visibility to 'internal'
        matter = self.get_matter(matter_id)
        if matter is None:
            raise ValueError(f"matter not found: {matter_id}")
        if matter["privileged"]:
            visibility = "internal"

        content_json = json.dumps(content) if content is not None else None
        now = _now()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO activities
                    (matter_id, actor_id, type, visibility, content_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (matter_id, actor_id, type, visibility, content_json, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_activities(self, matter_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM activities WHERE matter_id = ? ORDER BY created_at ASC",
                (matter_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            raw = d.pop("content_json", None)
            d["content"] = json.loads(raw) if raw else None
            result.append(d)
        return result

    # ── Contacts ─────────────────────────────────────────────────────

    def create_contact(
        self,
        *,
        name: str,
        email: str,
        department: str | None = None,
    ) -> str:
        contact_id = uuid.uuid4().hex[:12]
        now = _now()
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO contacts (id, name, email, department, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (contact_id, name, email, department, now),
            )
            conn.commit()
        return contact_id

    def link_contact(
        self,
        *,
        matter_id: str,
        contact_id: str,
        role: str = "requestor",
    ) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO matter_contacts (matter_id, contact_id, role) VALUES (?, ?, ?)",
                (matter_id, contact_id, role),
            )
            conn.commit()

    def get_contact_by_email(self, email: str) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT id FROM contacts WHERE email = ?", (email,)
            ).fetchone()
            return row["id"] if row else None

    def list_matter_contacts(self, matter_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.*, mc.role
                FROM contacts c
                JOIN matter_contacts mc ON mc.contact_id = c.id
                WHERE mc.matter_id = ?
                """,
                (matter_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Deadlines ────────────────────────────────────────────────────

    def create_deadline(
        self,
        *,
        matter_id: str,
        label: str,
        due_date: str,
        type: str = "hard",
        alert_before: str | None = None,
        recurring: str | None = None,
    ) -> int:
        now = _now()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO deadlines
                    (matter_id, label, due_date, type, alert_before, recurring, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (matter_id, label, due_date, type, alert_before, recurring, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_deadlines(self, matter_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM deadlines WHERE matter_id = ? ORDER BY due_date ASC",
                (matter_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def complete_deadline(self, deadline_id: int) -> None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM deadlines WHERE id = ?", (deadline_id,)
            ).fetchone()
            if not row:
                return

            conn.execute(
                "UPDATE deadlines SET status = 'completed' WHERE id = ?",
                (deadline_id,),
            )

            recurring = row["recurring"]
            if recurring:
                next_due = self._advance_date(row["due_date"], recurring)
                if next_due:
                    now = _now()
                    conn.execute(
                        """
                        INSERT INTO deadlines (matter_id, label, due_date, type, alert_before, recurring, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        (row["matter_id"], row["label"], next_due, row["type"],
                         row["alert_before"], recurring, now),
                    )

            conn.commit()

    @staticmethod
    def _advance_date(due_date: str, duration: str) -> str | None:
        """Advance a date by an ISO 8601 duration (P1Y, P3M, P1M, P7D, etc.)."""
        from datetime import date as date_type
        d = date_type.fromisoformat(due_date[:10])

        if duration.startswith("P") and duration.endswith("Y"):
            years = int(duration[1:-1])
            return d.replace(year=d.year + years).isoformat()
        if duration.startswith("P") and duration.endswith("M"):
            months = int(duration[1:-1])
            new_month = d.month + months
            new_year = d.year + (new_month - 1) // 12
            new_month = ((new_month - 1) % 12) + 1
            import calendar
            max_day = calendar.monthrange(new_year, new_month)[1]
            new_day = min(d.day, max_day)
            return date_type(new_year, new_month, new_day).isoformat()
        if duration.startswith("P") and duration.endswith("D"):
            from datetime import timedelta as td
            days = int(duration[1:-1])
            return (d + td(days=days)).isoformat()

        return None

    def list_upcoming_deadlines(
        self,
        *,
        before: str,
        status: str = "pending",
    ) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT d.*, m.title AS matter_title, m.type AS matter_type
                FROM deadlines d
                JOIN matters m ON m.id = d.matter_id
                WHERE d.due_date <= ? AND d.status = ?
                ORDER BY d.due_date ASC
                """,
                (before, status),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Relationships ────────────────────────────────────────────────

    def add_relationship(
        self,
        *,
        source_id: str,
        target_id: str,
        type: str,
    ) -> int:
        now = _now()
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO matter_relationships (source_id, target_id, type, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (source_id, target_id, type, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_relationships(self, matter_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM matter_relationships
                WHERE source_id = ? OR target_id = ?
                """,
                (matter_id, matter_id),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Deadline helpers (automation) ────────────────────────────────

    def mark_deadline_missed(self, deadline_id: int) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE deadlines SET status = 'missed' WHERE id = ?",
                (deadline_id,),
            )
            conn.commit()

    def list_all_pending_deadlines(self) -> list[dict[str, Any]]:
        """Return all pending deadlines with matter info."""
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT d.*, m.title AS matter_title, m.type AS matter_type,
                       m.privileged AS matter_privileged
                FROM deadlines d
                JOIN matters m ON m.id = d.matter_id
                WHERE d.status = 'pending'
                ORDER BY d.due_date ASC
                """,
            ).fetchall()
        return [dict(r) for r in rows]
