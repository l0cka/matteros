"""FastAPI web application for MatterOS.

Self-contained: no Node.js required. Uses HTMX + Jinja2 templates.
Session-based authentication with per-user permissions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from matteros.core.factory import resolve_home
from matteros.core.store import SQLiteStore
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

    # ---------- Deadlines ----------

    @app.get("/deadlines", response_class=HTMLResponse)
    async def deadlines_page(request: Request) -> HTMLResponse:
        store = _store()
        ms = MatterStore(store)
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%dT%H:%M:%S")
        week_end = (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        month_end = (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")

        all_deadlines = ms.list_upcoming_deadlines(before="2099-12-31T23:59:59")

        overdue = []
        this_week = []
        this_month = []
        upcoming = []

        for d in all_deadlines:
            due = d["due_date"][:19]  # normalize to YYYY-MM-DDTHH:MM:SS
            if due < today:
                overdue.append(d)
            else:
                upcoming.append(d)
                if due <= week_end:
                    this_week.append(d)
                elif due <= month_end:
                    this_month.append(d)

        return templates.TemplateResponse(request, "deadlines.html", {
            "overdue": overdue,
            "this_week": this_week,
            "this_month": this_month,
            "upcoming": upcoming,
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

    # ---------- Create Matter ----------

    @app.get("/matters/new", response_class=HTMLResponse)
    async def new_matter_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "matter_form.html", {})

    @app.post("/matters/new")
    async def create_matter_submit(request: Request) -> Response:
        store = _store()
        ms = MatterStore(store)
        user = request.state.user
        form = await request.form()

        title = str(form.get("title", ""))
        type_ = str(form.get("type", "request"))
        priority = str(form.get("priority", "medium"))
        due_date = str(form.get("due_date", "")) or None
        privileged = bool(form.get("privileged"))

        matter_id = ms.create_matter(
            title=title,
            type=type_,
            priority=priority,
            due_date=due_date,
            privileged=privileged,
            assignee_id=user["id"],
        )
        return RedirectResponse(f"/matters/{matter_id}", status_code=303)

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

    # ---------- Matter Actions (comment / status) ----------

    @app.post("/matters/{matter_id}/comment")
    async def post_comment(request: Request, matter_id: str) -> Response:
        store = _store()
        ms = MatterStore(store)
        user = request.state.user
        form = await request.form()
        comment = str(form.get("comment", ""))

        ms.add_activity(
            matter_id=matter_id,
            actor_id=user["id"],
            type="comment",
            content={"text": comment},
        )
        return RedirectResponse(f"/matters/{matter_id}", status_code=303)

    @app.post("/matters/{matter_id}/status")
    async def update_status(request: Request, matter_id: str) -> Response:
        store = _store()
        ms = MatterStore(store)
        user = request.state.user
        form = await request.form()
        status = str(form.get("status", ""))

        valid_statuses = {"new", "in_progress", "on_hold", "resolved"}
        if status not in valid_statuses:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status}")

        ms.update_matter(matter_id, status=status)
        ms.add_activity(
            matter_id=matter_id,
            actor_id=user["id"],
            type="status_change",
            content={"status": status},
        )
        return RedirectResponse(f"/matters/{matter_id}", status_code=303)

    # ---------- Audit ----------

    @app.get("/audit", response_class=HTMLResponse, dependencies=[Depends(require_permission("view_audit"))])
    async def audit_page(request: Request) -> HTMLResponse:
        store = _store()
        events = store.list_audit_events(limit=200)
        events.reverse()
        return templates.TemplateResponse(request, "audit.html", {
            "events": events,
        })

    # ---------- API endpoints ----------

    @app.get("/api/audit", dependencies=[Depends(require_permission("view_audit"))])
    async def api_audit(
        run_id: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict]:
        store = _store()
        if run_id:
            return store.list_audit_events_for_run(run_id=run_id)
        return store.list_audit_events(limit=limit)

    return app
