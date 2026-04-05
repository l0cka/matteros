"""FastAPI web application for MatterOS.

Self-contained: no Node.js required. Uses HTMX + Jinja2 templates.
Session-based authentication with per-user permissions.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from matteros.core.config import load_config
from matteros.core.events import EventBus
from matteros.core.factory import resolve_home
from matteros.core.store import SQLiteStore
from matteros.drafts.manager import DraftManager
from matteros.matters.store import MatterStore
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
from matteros.web.run_service import RunService


def create_app(*, home: Path | None = None) -> FastAPI:
    home_dir = resolve_home(home)
    app = FastAPI(title="MatterOS", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    def _store() -> SQLiteStore:
        return SQLiteStore(home_dir / "matteros.db")

    @app.middleware("http")
    async def _session_middleware(request: Request, call_next):
        # Allow login page without auth
        if request.url.path in ("/login",):
            response = await call_next(request)
            return response

        store = _store()

        # Solo mode: no users exist
        if not has_users(store):
            if request.url.path == "/":
                return templates.TemplateResponse(request, "login.html", {
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

    @app.on_event("startup")
    async def _startup() -> None:
        # Ensure DB exists
        _store()

    # ---------- Login / Logout ----------

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        store = _store()
        return templates.TemplateResponse(request, "login.html", {
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
            return templates.TemplateResponse(request, "login.html", {
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

    # ---------- My Queue (dashboard) ----------

    @app.get("/", response_class=HTMLResponse)
    async def my_queue(request: Request) -> HTMLResponse:
        store = _store()
        ms = MatterStore(store)
        user = request.state.user
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        # Get matters assigned to this user, excluding resolved
        all_assigned = ms.list_matters(assignee_id=user["id"])
        matters = [m for m in all_assigned if m.get("status") != "resolved"]

        # Mark overdue
        for m in matters:
            if m.get("due_date") and m["due_date"][:10] < today:
                m["is_overdue"] = True
            else:
                m["is_overdue"] = False

        overdue_count = sum(1 for m in matters if m["is_overdue"])

        # Sort: overdue first, then by due_date (nulls last), then by priority
        priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}

        def sort_key(m: dict) -> tuple:
            return (
                0 if m["is_overdue"] else 1,
                m["due_date"][:10] if m.get("due_date") else "9999-99-99",
                priority_order.get(m.get("priority", "medium"), 2),
            )

        matters.sort(key=sort_key)

        # Upcoming deadlines (next 7 days)
        next_week = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%d")
        upcoming_deadlines = ms.list_upcoming_deadlines(before=next_week)

        return templates.TemplateResponse(request, "my_queue.html", {
            "matters": matters,
            "overdue_count": overdue_count,
            "upcoming_deadlines": upcoming_deadlines,
        })

    # ---------- All Matters ----------

    @app.get("/matters", response_class=HTMLResponse)
    async def all_matters(
        request: Request,
        status: str | None = Query(None),
        type: str | None = Query(None),
    ) -> HTMLResponse:
        store = _store()
        ms = MatterStore(store)
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if type:
            filters["type"] = type
        matters = ms.list_matters(**filters)

        return templates.TemplateResponse(request, "all_matters.html", {
            "matters": matters,
            "filter_status": status or "",
            "filter_type": type or "",
        })

    # ---------- Matter Detail ----------

    @app.get("/matters/{matter_id}", response_class=HTMLResponse)
    async def matter_detail(request: Request, matter_id: str) -> HTMLResponse:
        store = _store()
        ms = MatterStore(store)
        matter = ms.get_matter(matter_id)
        if not matter:
            raise HTTPException(status_code=404, detail="Matter not found")

        activities = ms.list_activities(matter_id)
        deadlines = ms.list_deadlines(matter_id)
        relationships = ms.list_relationships(matter_id)

        return templates.TemplateResponse(request, "matter_detail.html", {
            "matter": matter,
            "activities": activities,
            "deadlines": deadlines,
            "relationships": relationships,
        })

    # ---------- Runs ----------

    @app.get("/runs", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_runs"))])
    async def runs_page(request: Request) -> HTMLResponse:
        store = _store()
        conn = store._connect()
        try:
            rows = conn.execute(
                "SELECT id, playbook_name, status, started_at, ended_at, dry_run "
                "FROM runs ORDER BY started_at DESC LIMIT 50"
            ).fetchall()
        finally:
            conn.close()

        return templates.TemplateResponse(request, "runs.html", {
            "runs": [dict(r) for r in rows],
        })

    @app.get("/runs/new", response_class=HTMLResponse, dependencies=[Depends(require_permission("run_playbooks"))])
    async def run_trigger_page(request: Request) -> HTMLResponse:
        svc = _run_service()
        playbooks = svc.list_playbooks()
        return templates.TemplateResponse(request, "run_trigger.html", {
            "playbooks": playbooks,
        })

    @app.get("/runs/{run_id}", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_runs"))])
    async def run_detail(request: Request, run_id: str) -> HTMLResponse:
        store = _store()
        conn = store._connect()
        try:
            run_row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if not run_row:
                raise HTTPException(status_code=404, detail="Run not found")
            steps = conn.execute(
                "SELECT * FROM steps WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
            events = conn.execute(
                "SELECT * FROM audit_events WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        finally:
            conn.close()

        return templates.TemplateResponse(request, "run_detail.html", {
            "run": dict(run_row),
            "steps": [dict(s) for s in steps],
            "events": [dict(e) for e in events],
        })

    @app.get("/runs/{run_id}/live", dependencies=[Depends(require_permission("view_runs"))])
    async def run_live_stream(run_id: str, since: int = Query(0, ge=0)) -> StreamingResponse:
        store = _store()

        async def generate():
            last_seq = since
            while True:
                with store.connection() as conn:
                    rows = conn.execute(
                        """
                        SELECT seq, run_id, event_type, step_id, data_json
                        FROM audit_events
                        WHERE run_id = ? AND seq > ?
                        ORDER BY seq ASC
                        LIMIT 100
                        """,
                        (run_id, last_seq),
                    ).fetchall()

                if rows:
                    for row in rows:
                        last_seq = int(row["seq"])
                        payload = {
                            "seq": last_seq,
                            "type": row["event_type"],
                            "run_id": row["run_id"],
                            "step_id": row["step_id"],
                            "data": json.loads(row["data_json"]) if row["data_json"] else {},
                        }
                        yield f"id: {last_seq}\n"
                        yield f"data: {json.dumps(payload)}\n\n"

                        # Stop streaming when run completes or fails
                        if row["event_type"] in ("run.completed", "run.failed"):
                            return
                else:
                    yield ": keepalive\n\n"

                await asyncio.sleep(1.0)

        return StreamingResponse(generate(), media_type="text/event-stream")

    # ---------- Approvals ----------

    @app.get("/approvals", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_runs"))])
    async def approvals_page(request: Request) -> HTMLResponse:
        store = _store()
        conn = store._connect()
        try:
            rows = conn.execute(
                "SELECT a.*, r.playbook_name FROM approvals a "
                "JOIN runs r ON a.run_id = r.id "
                "ORDER BY a.created_at DESC LIMIT 50"
            ).fetchall()
        finally:
            conn.close()

        return templates.TemplateResponse(request, "approvals.html", {
            "approvals": [dict(r) for r in rows],
        })

    # ---------- Drafts ----------

    @app.get("/drafts", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_drafts"))])
    async def drafts_page(request: Request) -> HTMLResponse:
        store = _store()
        manager = DraftManager(store)
        drafts = manager.list_drafts(limit=50)
        return templates.TemplateResponse(request, "drafts.html", {
            "drafts": drafts,
        })

    @app.post("/drafts/{draft_id}/approve")
    async def approve_draft(request: Request, draft_id: str) -> Response:
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

    # ---------- Audit ----------

    @app.get("/audit", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_audit"))])
    async def audit_page(request: Request) -> HTMLResponse:
        store = _store()
        events = store.list_audit_events(limit=200)
        events.reverse()
        return templates.TemplateResponse(request, "audit.html", {
            "events": events,
        })

    # ---------- Settings ----------

    @app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_permission("manage_settings"))])
    async def settings_page(request: Request) -> HTMLResponse:
        loaded = load_config(path=home_dir / "config.yml", home=home_dir)
        return templates.TemplateResponse(request, "settings.html", {
            "config": loaded.config,
            "home": str(home_dir),
        })

    # ---------- SSE for real-time updates ----------

    @app.get("/events/stream", dependencies=[Depends(require_permission("view_runs"))])
    async def event_stream(since: int = Query(0, ge=0)) -> StreamingResponse:
        store = _store()

        async def generate():
            last_seq = since
            while True:
                with store.connection() as conn:
                    rows = conn.execute(
                        """
                        SELECT seq, run_id, event_type, step_id, data_json
                        FROM audit_events
                        WHERE seq > ?
                        ORDER BY seq ASC
                        LIMIT 100
                        """,
                        (last_seq,),
                    ).fetchall()

                if rows:
                    for row in rows:
                        last_seq = int(row["seq"])
                        payload = {
                            "seq": last_seq,
                            "type": row["event_type"],
                            "run_id": row["run_id"],
                            "step_id": row["step_id"],
                            "data": json.loads(row["data_json"]) if row["data_json"] else {},
                        }
                        yield f"id: {last_seq}\n"
                        yield f"data: {json.dumps(payload)}\n\n"
                else:
                    yield ": keepalive\n\n"

                await asyncio.sleep(1.0)

        return StreamingResponse(generate(), media_type="text/event-stream")

    # ---------- API endpoints ----------

    @app.get("/api/runs", dependencies=[Depends(require_permission("view_runs"))])
    async def api_runs(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
        store = _store()
        conn = store._connect()
        try:
            rows = conn.execute(
                "SELECT id, playbook_name, status, started_at, ended_at, dry_run "
                "FROM runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @app.get("/api/audit", dependencies=[Depends(require_permission("view_audit"))])
    async def api_audit(
        run_id: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict]:
        store = _store()
        if run_id:
            return store.list_audit_events_for_run(run_id=run_id)
        return store.list_audit_events(limit=limit)

    # ---------- Run trigger ----------

    _run_event_bus = EventBus()

    def _run_service() -> RunService:
        return RunService(home_dir)

    @app.post("/api/runs", dependencies=[Depends(require_permission("run_playbooks"))])
    async def api_trigger_run(
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        playbook = body.get("playbook")
        if not playbook or not isinstance(playbook, str):
            raise HTTPException(status_code=422, detail="playbook name is required")

        inputs = body.get("inputs", {})
        if not isinstance(inputs, dict):
            raise HTTPException(status_code=422, detail="inputs must be an object")

        dry_run = body.get("dry_run", True)

        svc = _run_service()
        try:
            run_id = svc.trigger_run(
                playbook_name=playbook,
                inputs=inputs,
                dry_run=bool(dry_run),
                event_bus=_run_event_bus,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        return JSONResponse({"run_id": run_id, "status": "started"}, status_code=201)

    return app
