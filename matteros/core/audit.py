from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from matteros.core.store import SQLiteStore

_SAFE_FIELDS = {
    "matter_id", "event_type", "action",
    "old_status", "new_status",
    "old_assignee", "new_assignee",
    "deadline_id", "due_date",
    "accessor_id",
}


@dataclass(slots=True)
class VerificationResult:
    ok: bool
    run_id: str
    checked_events: int
    source: str
    failure_seq: int | None = None
    reason: str | None = None
    details: str | None = None
    last_seq: int | None = None
    last_event_hash: str | None = None


class AuditLogger:
    def __init__(self, store: SQLiteStore, jsonl_path: Path):
        self.store = store
        self.jsonl_path = jsonl_path
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        *,
        run_id: str,
        event_type: str,
        actor: str,
        step_id: str | None,
        data: dict[str, Any],
        privileged: bool = False,
    ) -> dict[str, Any]:
        if privileged:
            data = self._redact(data, event_type)
        timestamp = datetime.now(UTC).isoformat()
        prev_hash = self.store.get_last_audit_hash(run_id)

        payload = self._build_payload(
            run_id=run_id,
            timestamp=timestamp,
            event_type=event_type,
            actor=actor,
            step_id=step_id,
            data=data,
            prev_hash=prev_hash,
        )
        event_hash = self._compute_event_hash(payload)

        event = {**payload, "event_hash": event_hash}
        seq = self.store.insert_audit_event(
            run_id=run_id,
            timestamp=timestamp,
            event_type=event_type,
            actor=actor,
            step_id=step_id,
            data_json=json.dumps(data, sort_keys=True),
            prev_hash=prev_hash,
            event_hash=event_hash,
        )

        event["seq"] = seq
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

        return event

    def _redact(self, data: dict[str, Any], event_type: str) -> dict[str, Any]:
        """Strip sensitive fields from data, keeping only safe metadata."""
        redacted = {"event_type": event_type}
        for key, value in data.items():
            if key in _SAFE_FIELDS:
                redacted[key] = value
        return redacted

    def verify_run(
        self,
        *,
        run_id: str,
        source: Literal["db", "jsonl", "both"] = "both",
    ) -> VerificationResult:
        if source == "db":
            events = self.store.list_audit_events_for_run(run_id=run_id)
            return self.verify_events(run_id=run_id, events=events, source="db")

        if source == "jsonl":
            try:
                events = self._load_jsonl_events_for_run(run_id=run_id)
            except ValueError as exc:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=0,
                    source="jsonl",
                    reason="parse_error",
                    details=str(exc),
                )
            return self.verify_events(run_id=run_id, events=events, source="jsonl")

        if source != "both":
            raise ValueError("source must be db, jsonl, or both")

        db_events = self.store.list_audit_events_for_run(run_id=run_id)
        db_result = self.verify_events(run_id=run_id, events=db_events, source="db")
        if not db_result.ok:
            return db_result

        try:
            jsonl_events = self._load_jsonl_events_for_run(run_id=run_id)
        except ValueError as exc:
            return VerificationResult(
                ok=False,
                run_id=run_id,
                checked_events=0,
                source="jsonl",
                reason="parse_error",
                details=str(exc),
            )

        jsonl_result = self.verify_events(run_id=run_id, events=jsonl_events, source="jsonl")
        if not jsonl_result.ok:
            return jsonl_result

        return self._compare_sources(
            run_id=run_id,
            db_events=db_events,
            jsonl_events=jsonl_events,
        )

    def verify_events(
        self,
        *,
        run_id: str,
        events: list[dict[str, Any]],
        source: str,
    ) -> VerificationResult:
        if not events:
            return VerificationResult(
                ok=False,
                run_id=run_id,
                checked_events=0,
                source=source,
                reason="missing_event",
                details="no audit events found for run",
            )

        expected_prev_hash: str | None = None
        checked_events = 0
        last_seq: int | None = None
        last_event_hash: str | None = None

        for event in events:
            seq = self._coerce_seq(event.get("seq"))
            if seq is None:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=checked_events,
                    source=source,
                    reason="parse_error",
                    details="event is missing integer seq",
                )

            event_run_id = event.get("run_id")
            if not isinstance(event_run_id, str) or event_run_id != run_id:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=checked_events,
                    source=source,
                    failure_seq=seq,
                    reason="parse_error",
                    details=f"event run_id mismatch at seq {seq}",
                )

            event_data = event.get("data")
            if not isinstance(event_data, dict):
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=checked_events,
                    source=source,
                    failure_seq=seq,
                    reason="parse_error",
                    details=f"event data must be an object at seq {seq}",
                )

            prev_hash = event.get("prev_hash")
            if prev_hash is not None and not isinstance(prev_hash, str):
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=checked_events,
                    source=source,
                    failure_seq=seq,
                    reason="parse_error",
                    details=f"prev_hash must be string or null at seq {seq}",
                )

            if prev_hash != expected_prev_hash:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=checked_events,
                    source=source,
                    failure_seq=seq,
                    reason="prev_hash_mismatch",
                    details=(
                        f"expected prev_hash={expected_prev_hash!r}, got prev_hash={prev_hash!r}"
                    ),
                )

            payload = self._build_payload(
                run_id=event_run_id,
                timestamp=str(event.get("timestamp", "")),
                event_type=str(event.get("event_type", "")),
                actor=str(event.get("actor", "")),
                step_id=event.get("step_id"),
                data=event_data,
                prev_hash=prev_hash,
            )
            computed_hash = self._compute_event_hash(payload)

            event_hash = event.get("event_hash")
            if not isinstance(event_hash, str) or not event_hash:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=checked_events,
                    source=source,
                    failure_seq=seq,
                    reason="parse_error",
                    details=f"event_hash must be a non-empty string at seq {seq}",
                )

            if event_hash != computed_hash:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=checked_events,
                    source=source,
                    failure_seq=seq,
                    reason="event_hash_mismatch",
                    details=(
                        f"expected event_hash={computed_hash}, got event_hash={event_hash}"
                    ),
                )

            checked_events += 1
            expected_prev_hash = event_hash
            last_seq = seq
            last_event_hash = event_hash

        return VerificationResult(
            ok=True,
            run_id=run_id,
            checked_events=checked_events,
            source=source,
            last_seq=last_seq,
            last_event_hash=last_event_hash,
        )

    def _load_jsonl_events_for_run(self, *, run_id: str) -> list[dict[str, Any]]:
        if not self.jsonl_path.exists():
            raise FileNotFoundError(f"audit jsonl file not found: {self.jsonl_path}")

        events: list[dict[str, Any]] = []
        with self.jsonl_path.open("r", encoding="utf-8") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON on line {line_no}") from exc

                if not isinstance(item, dict):
                    raise ValueError(f"audit event line {line_no} must be a JSON object")

                if item.get("run_id") == run_id:
                    events.append(item)

        return events

    def _compare_sources(
        self,
        *,
        run_id: str,
        db_events: list[dict[str, Any]],
        jsonl_events: list[dict[str, Any]],
    ) -> VerificationResult:
        db_by_seq: dict[int, dict[str, Any]] = {}
        jsonl_by_seq: dict[int, dict[str, Any]] = {}

        for event in db_events:
            seq = self._coerce_seq(event.get("seq"))
            if seq is None:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=0,
                    source="db",
                    reason="parse_error",
                    details="db event is missing integer seq",
                )
            if seq in db_by_seq:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=0,
                    source="db",
                    failure_seq=seq,
                    reason="parse_error",
                    details=f"duplicate db seq {seq}",
                )
            db_by_seq[seq] = event

        for event in jsonl_events:
            seq = self._coerce_seq(event.get("seq"))
            if seq is None:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=0,
                    source="jsonl",
                    reason="parse_error",
                    details="jsonl event is missing integer seq",
                )
            if seq in jsonl_by_seq:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=0,
                    source="jsonl",
                    failure_seq=seq,
                    reason="parse_error",
                    details=f"duplicate jsonl seq {seq}",
                )
            jsonl_by_seq[seq] = event

        seqs = sorted(set(db_by_seq) | set(jsonl_by_seq))
        if not seqs:
            return VerificationResult(
                ok=False,
                run_id=run_id,
                checked_events=0,
                source="both",
                reason="missing_event",
                details="no audit events found for run",
            )

        for seq in seqs:
            db_event = db_by_seq.get(seq)
            jsonl_event = jsonl_by_seq.get(seq)
            if db_event is None or jsonl_event is None:
                missing_source = "db" if db_event is None else "jsonl"
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=min(len(db_by_seq), len(jsonl_by_seq)),
                    source="both",
                    failure_seq=seq,
                    reason="missing_event",
                    details=f"event missing in {missing_source} at seq {seq}",
                )

            db_hash = db_event.get("event_hash")
            jsonl_hash = jsonl_event.get("event_hash")
            if db_hash != jsonl_hash:
                return VerificationResult(
                    ok=False,
                    run_id=run_id,
                    checked_events=min(len(db_by_seq), len(jsonl_by_seq)),
                    source="both",
                    failure_seq=seq,
                    reason="event_hash_mismatch",
                    details=f"db/jsonl hash mismatch at seq {seq}",
                )

        last_seq = seqs[-1]
        return VerificationResult(
            ok=True,
            run_id=run_id,
            checked_events=len(seqs),
            source="both",
            last_seq=last_seq,
            last_event_hash=str(db_by_seq[last_seq].get("event_hash")),
        )

    def _build_payload(
        self,
        *,
        run_id: str,
        timestamp: str,
        event_type: str,
        actor: str,
        step_id: Any,
        data: dict[str, Any],
        prev_hash: str | None,
    ) -> dict[str, Any]:
        normalized_step_id: str | None
        if step_id is None:
            normalized_step_id = None
        elif isinstance(step_id, str):
            normalized_step_id = step_id
        else:
            normalized_step_id = str(step_id)

        return {
            "run_id": run_id,
            "timestamp": timestamp,
            "event_type": event_type,
            "actor": actor,
            "step_id": normalized_step_id,
            "data": data,
            "prev_hash": prev_hash,
        }

    def _compute_event_hash(self, payload: dict[str, Any]) -> str:
        prev_hash = payload.get("prev_hash")
        prefix = prev_hash if isinstance(prev_hash, str) else ""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256((prefix + canonical).encode("utf-8")).hexdigest()

    def _coerce_seq(self, value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None
