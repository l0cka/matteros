# In-House Legal Ops Web UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the playbook-centric web UI (runs, approvals, drafts) with matter management views: My Queue, All Matters, Deadlines, and Matter Detail — the working in-house lawyer's daily experience.

**Architecture:** Rewrite `matteros/web/app.py` to serve matter-based routes using `MatterStore` and the new authorization model. Keep the existing FastAPI + HTMX + Jinja2 stack. Templates reuse the existing dark theme from `base.html`. Auth middleware stays, but nav and permissions update to the new role model.

**Tech Stack:** FastAPI, Jinja2, HTMX 1.9, SQLite (via MatterStore), pytest + TestClient

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `matteros/web/app.py` | Replace run/draft routes with matter routes. Keep login/logout/middleware. |
| Modify | `matteros/web/templates/base.html` | Update nav links from runs/approvals to matters/deadlines |
| Create | `matteros/web/templates/my_queue.html` | My Queue view — assigned matters sorted by urgency |
| Create | `matteros/web/templates/all_matters.html` | All Matters — filterable list |
| Create | `matteros/web/templates/matter_detail.html` | Matter detail — metadata, activities, deadlines, relationships |
| Create | `matteros/web/templates/deadlines.html` | Deadline calendar view |
| Create | `matteros/web/templates/matter_form.html` | Create/edit matter form |
| Create | `tests/test_web_matters.py` | Tests for all matter web routes |

---

### Task 1: Update Base Template Navigation

**Files:**
- Modify: `matteros/web/templates/base.html`

- [ ] **Step 1: Update the nav links**

Replace the nav section in `matteros/web/templates/base.html` (lines 51-64). Remove the old permission-gated links for runs, approvals, drafts, settings. Replace with matter-based navigation:

```html
        <a href="/" {% if request.url.path == "/" %}class="active"{% endif %}>My Queue</a>
        <a href="/matters" {% if request.url.path == "/matters" %}class="active"{% endif %}>All Matters</a>
        <a href="/deadlines" {% if request.url.path == "/deadlines" %}class="active"{% endif %}>Deadlines</a>
        {% if "view_audit" in request.state.permissions %}
        <a href="/audit" {% if "/audit" in request.url.path %}class="active"{% endif %}>Audit Log</a>
        {% endif %}
```

- [ ] **Step 2: Add priority/status badge styles**

Add these styles to the existing `<style>` block in `base.html`, after the existing `.badge` styles:

```css
        .badge-urgent { background: #7f1d1d; color: var(--red); }
        .badge-high { background: #713f12; color: var(--yellow); }
        .badge-medium { background: #1e3a5f; color: var(--accent); }
        .badge-low { background: #1e293b; color: var(--muted); }
        .badge-new { background: #1e3a5f; color: var(--accent); }
        .badge-in_progress { background: #713f12; color: var(--yellow); }
        .badge-on_hold { background: #1e293b; color: var(--muted); }
        .badge-resolved { background: #166534; color: var(--green); }
        .badge-overdue { background: #7f1d1d; color: var(--red); }
        .filters { display: flex; gap: 0.75rem; margin-bottom: 1rem; align-items: center; }
        .filters select, .filters input { font-size: 0.8rem; }
        .activity-thread { max-height: 500px; overflow-y: auto; }
        .activity-item { padding: 0.75rem; border-left: 2px solid var(--border); margin-bottom: 0.5rem; }
        .activity-meta { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.25rem; }
        .tab-bar { display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 1rem; }
        .tab-bar a { padding: 0.5rem 1rem; color: var(--muted); text-decoration: none; font-size: 0.85rem; border-bottom: 2px solid transparent; }
        .tab-bar a.active { color: var(--text); border-bottom-color: var(--accent); }
```

- [ ] **Step 3: Commit**

```bash
git add matteros/web/templates/base.html
git commit -m "feat(web): update nav and styles for matter management UI"
```

---

### Task 2: My Queue Route and Template

**Files:**
- Modify: `matteros/web/app.py`
- Create: `matteros/web/templates/my_queue.html`
- Create: `tests/test_web_matters.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_matters.py`:

```python
"""Tests for matter management web routes."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from matteros.core.store import SQLiteStore
from matteros.matters.store import MatterStore
from matteros.team.users import UserManager, hash_password
from matteros.web.app import create_app


def _make_client(home: Path) -> TestClient:
    """Create app with a legal user and return a logged-in client."""
    store = SQLiteStore(home / "matteros.db")
    manager = UserManager(store)
    manager.create_user(username="lawyer", role="legal", password_hash=hash_password("pass"))
    app = create_app(home=home)
    client = TestClient(app)
    client.post("/login", data={"username": "lawyer", "password": "pass"})
    return client


def _matter_store(home: Path) -> MatterStore:
    store = SQLiteStore(home / "matteros.db")
    return MatterStore(store)


class TestMyQueue:
    def test_my_queue_returns_200(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        response = client.get("/")
        assert response.status_code == 200
        assert "My Queue" in response.text

    def test_my_queue_shows_assigned_matters(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)

        # Get the user ID
        db = SQLiteStore(home / "matteros.db")
        um = UserManager(db)
        user = um.get_user_by_username("lawyer")

        m1 = ms.create_matter(title="Urgent NDA", type="contract", priority="urgent")
        ms.update_matter(m1, assignee_id=user["id"])
        m2 = ms.create_matter(title="Unassigned", type="request")

        response = client.get("/")
        assert "Urgent NDA" in response.text
        assert "Unassigned" not in response.text

    def test_my_queue_shows_overdue_badge(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)

        db = SQLiteStore(home / "matteros.db")
        um = UserManager(db)
        user = um.get_user_by_username("lawyer")

        m1 = ms.create_matter(title="Overdue Matter", type="request", due_date="2020-01-01")
        ms.update_matter(m1, assignee_id=user["id"])

        response = client.get("/")
        assert "overdue" in response.text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_matters.py::TestMyQueue -v`
Expected: FAIL — route returns old dashboard content

- [ ] **Step 3: Create the My Queue template**

Create `matteros/web/templates/my_queue.html`:

```html
{% extends "base.html" %}
{% block title %}My Queue{% endblock %}
{% block content %}
<h2>My Queue</h2>
<div class="stats">
    <div class="stat">
        <div class="value">{{ matters | length }}</div>
        <div class="label">Assigned to you</div>
    </div>
    <div class="stat">
        <div class="value">{{ overdue_count }}</div>
        <div class="label">Overdue</div>
    </div>
    <div class="stat">
        <div class="value">{{ upcoming_deadlines | length }}</div>
        <div class="label">Deadlines this week</div>
    </div>
</div>

{% if matters %}
<table>
    <thead>
        <tr><th>Title</th><th>Type</th><th>Status</th><th>Priority</th><th>Due Date</th></tr>
    </thead>
    <tbody>
        {% for m in matters %}
        <tr>
            <td><a href="/matters/{{ m.id }}" style="color: var(--accent)">{{ m.title }}</a></td>
            <td>{{ m.type }}</td>
            <td><span class="badge badge-{{ m.status }}">{{ m.status }}</span></td>
            <td><span class="badge badge-{{ m.priority }}">{{ m.priority }}</span></td>
            <td>
                {% if m.due_date %}
                    {% if m.is_overdue %}<span class="badge badge-overdue">overdue</span>{% endif %}
                    {{ m.due_date[:10] }}
                {% else %}
                    —
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<div class="card" style="text-align:center; color:var(--muted); padding:2rem;">
    No matters assigned to you. You're all caught up.
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Update app.py — replace dashboard route with My Queue**

In `matteros/web/app.py`, add the MatterStore import at the top:

```python
from matteros.matters.store import MatterStore
```

Replace the dashboard route (the `@app.get("/")` handler) with:

```python
    @app.get("/", response_class=HTMLResponse)
    async def my_queue(request: Request) -> HTMLResponse:
        store = _store()
        user = request.state.user
        ms = MatterStore(store)

        matters = ms.list_matters(assignee_id=user["id"])
        # Filter to non-resolved matters
        matters = [m for m in matters if m["status"] != "resolved"]

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        for m in matters:
            m["is_overdue"] = bool(m.get("due_date") and m["due_date"][:10] < today)

        # Sort: overdue first, then by due_date (nulls last), then by priority
        priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        matters.sort(key=lambda m: (
            not m["is_overdue"],
            m.get("due_date") or "9999-99-99",
            priority_order.get(m.get("priority", "medium"), 2),
        ))

        overdue_count = sum(1 for m in matters if m["is_overdue"])

        # Upcoming deadlines for this user's matters
        from datetime import timedelta
        week_from_now = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")
        upcoming_deadlines = ms.list_upcoming_deadlines(before=week_from_now)

        return templates.TemplateResponse(request, "my_queue.html", {
            "matters": matters,
            "overdue_count": overdue_count,
            "upcoming_deadlines": upcoming_deadlines,
        })
```

Add the datetime import at the top of the file if not already present:

```python
from datetime import UTC, datetime, timedelta
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_web_matters.py::TestMyQueue -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/web/app.py matteros/web/templates/my_queue.html tests/test_web_matters.py
git commit -m "feat(web): add My Queue route showing assigned matters"
```

---

### Task 3: All Matters Route and Template

**Files:**
- Modify: `matteros/web/app.py`
- Create: `matteros/web/templates/all_matters.html`
- Modify: `tests/test_web_matters.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_matters.py`:

```python
class TestAllMatters:
    def test_all_matters_returns_200(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        response = client.get("/matters")
        assert response.status_code == 200
        assert "All Matters" in response.text

    def test_all_matters_shows_all(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)
        ms.create_matter(title="Contract A", type="contract")
        ms.create_matter(title="Request B", type="request")

        response = client.get("/matters")
        assert "Contract A" in response.text
        assert "Request B" in response.text

    def test_all_matters_filter_by_status(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)
        m1 = ms.create_matter(title="Open", type="request")
        m2 = ms.create_matter(title="Done", type="request")
        ms.update_matter(m2, status="resolved")

        response = client.get("/matters?status=new")
        assert "Open" in response.text
        assert "Done" not in response.text

    def test_all_matters_filter_by_type(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)
        ms.create_matter(title="NDA", type="contract")
        ms.create_matter(title="Help", type="request")

        response = client.get("/matters?type=contract")
        assert "NDA" in response.text
        assert "Help" not in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_matters.py::TestAllMatters -v`
Expected: FAIL — 404

- [ ] **Step 3: Create the All Matters template**

Create `matteros/web/templates/all_matters.html`:

```html
{% extends "base.html" %}
{% block title %}All Matters{% endblock %}
{% block content %}
<div style="display:flex; align-items:center; gap:1rem; margin-bottom:1rem">
    <h2 style="margin-bottom:0">All Matters</h2>
    <a href="/matters/new" class="btn btn-green" style="font-size:0.75rem">New Matter</a>
</div>

<form class="filters" method="GET" action="/matters">
    <select name="status">
        <option value="">All statuses</option>
        <option value="new" {% if filter_status == "new" %}selected{% endif %}>New</option>
        <option value="in_progress" {% if filter_status == "in_progress" %}selected{% endif %}>In Progress</option>
        <option value="on_hold" {% if filter_status == "on_hold" %}selected{% endif %}>On Hold</option>
        <option value="resolved" {% if filter_status == "resolved" %}selected{% endif %}>Resolved</option>
    </select>
    <select name="type">
        <option value="">All types</option>
        <option value="contract" {% if filter_type == "contract" %}selected{% endif %}>Contract</option>
        <option value="request" {% if filter_type == "request" %}selected{% endif %}>Request</option>
        <option value="compliance" {% if filter_type == "compliance" %}selected{% endif %}>Compliance</option>
    </select>
    <button type="submit" class="btn">Filter</button>
</form>

<table>
    <thead>
        <tr><th>Title</th><th>Type</th><th>Status</th><th>Priority</th><th>Assignee</th><th>Due Date</th></tr>
    </thead>
    <tbody>
        {% for m in matters %}
        <tr>
            <td><a href="/matters/{{ m.id }}" style="color: var(--accent)">{{ m.title }}</a></td>
            <td>{{ m.type }}</td>
            <td><span class="badge badge-{{ m.status }}">{{ m.status }}</span></td>
            <td><span class="badge badge-{{ m.priority }}">{{ m.priority }}</span></td>
            <td>{{ m.assignee_name or "—" }}</td>
            <td>{{ m.due_date[:10] if m.due_date else "—" }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>

{% if not matters %}
<div class="card" style="text-align:center; color:var(--muted); padding:2rem;">
    No matters found.
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Add the All Matters route to app.py**

Add to `matteros/web/app.py`:

```python
    @app.get("/matters", response_class=HTMLResponse)
    async def all_matters(
        request: Request,
        status: str | None = Query(None),
        type: str | None = Query(None),
    ) -> HTMLResponse:
        store = _store()
        ms = MatterStore(store)
        matters = ms.list_matters(status=status, type=type)

        return templates.TemplateResponse(request, "all_matters.html", {
            "matters": matters,
            "filter_status": status or "",
            "filter_type": type or "",
        })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_web_matters.py::TestAllMatters -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/web/app.py matteros/web/templates/all_matters.html tests/test_web_matters.py
git commit -m "feat(web): add All Matters route with status/type filtering"
```

---

### Task 4: Matter Detail Route and Template

**Files:**
- Modify: `matteros/web/app.py`
- Create: `matteros/web/templates/matter_detail.html`
- Modify: `tests/test_web_matters.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_matters.py`:

```python
class TestMatterDetail:
    def test_detail_returns_200(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)
        matter_id = ms.create_matter(title="NDA Review", type="contract")

        response = client.get(f"/matters/{matter_id}")
        assert response.status_code == 200
        assert "NDA Review" in response.text

    def test_detail_shows_activities(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)
        matter_id = ms.create_matter(title="Test", type="request")
        ms.add_activity(matter_id=matter_id, type="comment", content={"text": "Looking into this"})

        response = client.get(f"/matters/{matter_id}")
        assert "Looking into this" in response.text

    def test_detail_shows_deadlines(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)
        matter_id = ms.create_matter(title="Filing", type="compliance")
        ms.create_deadline(matter_id=matter_id, label="Due to regulator", due_date="2026-12-31")

        response = client.get(f"/matters/{matter_id}")
        assert "Due to regulator" in response.text

    def test_detail_404_for_missing(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)

        response = client.get("/matters/nonexistent")
        assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_matters.py::TestMatterDetail -v`
Expected: FAIL — 404

- [ ] **Step 3: Create the Matter Detail template**

Create `matteros/web/templates/matter_detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ matter.title }}{% endblock %}
{% block content %}
<div style="display:flex; align-items:center; gap:1rem; margin-bottom:1rem">
    <a href="/matters" style="color:var(--muted); text-decoration:none;">&larr; All Matters</a>
</div>

<div style="display:flex; align-items:baseline; gap:1rem; margin-bottom:0.5rem">
    <h2 style="margin-bottom:0; text-transform:none; letter-spacing:0">{{ matter.title }}</h2>
    <span class="badge badge-{{ matter.status }}">{{ matter.status }}</span>
    <span class="badge badge-{{ matter.priority }}">{{ matter.priority }}</span>
    {% if matter.privileged %}<span class="badge badge-red">privileged</span>{% endif %}
</div>

<div style="color:var(--muted); font-size:0.8rem; margin-bottom:1.5rem">
    {{ matter.type }} &middot; created {{ matter.created_at[:10] }}
    {% if matter.source %} &middot; via {{ matter.source }}{% endif %}
    {% if matter.assignee_id %} &middot; assigned to {{ matter.assignee_id[:8] }}{% endif %}
</div>

<div class="tab-bar">
    <a href="#activities" class="active">Activity</a>
    <a href="#deadlines">Deadlines ({{ deadlines | length }})</a>
    <a href="#details">Details</a>
</div>

<!-- Activity Thread -->
<div class="card">
    <div class="activity-thread">
        {% for a in activities %}
        <div class="activity-item">
            <div class="activity-meta">
                {{ a.type }} &middot; {{ a.created_at[:19] }}
                {% if a.visibility == "internal" %} &middot; <span style="color:var(--yellow)">internal</span>{% endif %}
            </div>
            {% if a.content and a.content.text %}
            <div>{{ a.content.text }}</div>
            {% endif %}
        </div>
        {% endfor %}
        {% if not activities %}
        <div style="color:var(--muted); padding:1rem; text-align:center;">No activity yet.</div>
        {% endif %}
    </div>

    <form method="POST" action="/matters/{{ matter.id }}/comment" style="margin-top:1rem; display:flex; gap:0.5rem;">
        <input type="text" name="comment" placeholder="Add a comment..." style="flex:1;">
        <button type="submit" class="btn">Post</button>
    </form>
</div>

<!-- Deadlines -->
{% if deadlines %}
<div class="card" style="margin-top:1rem;">
    <h2 style="font-size:0.85rem">Deadlines</h2>
    <table>
        <thead><tr><th>Label</th><th>Due</th><th>Type</th><th>Status</th></tr></thead>
        <tbody>
        {% for d in deadlines %}
        <tr>
            <td>{{ d.label }}</td>
            <td>{{ d.due_date[:10] }}</td>
            <td>{{ d.type }}</td>
            <td><span class="badge badge-{{ 'green' if d.status == 'completed' else 'yellow' }}">{{ d.status }}</span></td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

<!-- Metadata -->
{% if matter.metadata %}
<div class="card" style="margin-top:1rem;">
    <h2 style="font-size:0.85rem">Details</h2>
    <pre>{{ matter.metadata | tojson(indent=2) }}</pre>
</div>
{% endif %}

<!-- Relationships -->
{% if relationships %}
<div class="card" style="margin-top:1rem;">
    <h2 style="font-size:0.85rem">Related Matters</h2>
    {% for r in relationships %}
    <div style="padding:0.25rem 0; font-size:0.85rem;">
        {{ r.type }} &rarr; <a href="/matters/{{ r.target_id }}" style="color:var(--accent)">{{ r.target_id[:8] }}</a>
    </div>
    {% endfor %}
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Add the Matter Detail route to app.py**

Add to `matteros/web/app.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_web_matters.py::TestMatterDetail -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/web/app.py matteros/web/templates/matter_detail.html tests/test_web_matters.py
git commit -m "feat(web): add Matter Detail route with activities, deadlines, relationships"
```

---

### Task 5: Add Comment and Status Update Routes

**Files:**
- Modify: `matteros/web/app.py`
- Modify: `tests/test_web_matters.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_matters.py`:

```python
class TestMatterActions:
    def test_post_comment(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)
        matter_id = ms.create_matter(title="Test", type="request")

        response = client.post(
            f"/matters/{matter_id}/comment",
            data={"comment": "New comment here"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        activities = ms.list_activities(matter_id)
        assert len(activities) == 1
        assert activities[0]["content"]["text"] == "New comment here"

    def test_update_status(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)
        matter_id = ms.create_matter(title="Test", type="request")

        response = client.post(
            f"/matters/{matter_id}/status",
            data={"status": "in_progress"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        matter = ms.get_matter(matter_id)
        assert matter["status"] == "in_progress"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_matters.py::TestMatterActions -v`
Expected: FAIL — 404/405

- [ ] **Step 3: Add the comment and status routes**

Add to `matteros/web/app.py`:

```python
    @app.post("/matters/{matter_id}/comment")
    async def post_comment(request: Request, matter_id: str) -> Response:
        store = _store()
        ms = MatterStore(store)
        matter = ms.get_matter(matter_id)
        if not matter:
            raise HTTPException(status_code=404, detail="Matter not found")

        form = await request.form()
        comment = str(form.get("comment", "")).strip()
        if comment:
            user = request.state.user
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
        matter = ms.get_matter(matter_id)
        if not matter:
            raise HTTPException(status_code=404, detail="Matter not found")

        form = await request.form()
        new_status = str(form.get("status", ""))
        if new_status in ("new", "in_progress", "on_hold", "resolved"):
            old_status = matter["status"]
            ms.update_matter(matter_id, status=new_status)
            user = request.state.user
            ms.add_activity(
                matter_id=matter_id,
                actor_id=user["id"],
                type="status_change",
                content={"old_status": old_status, "new_status": new_status},
            )
        return RedirectResponse(f"/matters/{matter_id}", status_code=303)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_matters.py::TestMatterActions -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add matteros/web/app.py tests/test_web_matters.py
git commit -m "feat(web): add comment and status update routes for matters"
```

---

### Task 6: Create Matter Route and Form

**Files:**
- Modify: `matteros/web/app.py`
- Create: `matteros/web/templates/matter_form.html`
- Modify: `tests/test_web_matters.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_matters.py`:

```python
class TestCreateMatter:
    def test_new_matter_form_returns_200(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        response = client.get("/matters/new")
        assert response.status_code == 200
        assert "New Matter" in response.text

    def test_create_matter_redirects(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)

        response = client.post(
            "/matters/new",
            data={
                "title": "New Contract",
                "type": "contract",
                "priority": "high",
                "privileged": "1",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "/matters/" in response.headers["location"]

    def test_create_matter_persists(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)

        client.post(
            "/matters/new",
            data={
                "title": "Test Matter",
                "type": "request",
                "priority": "medium",
            },
        )

        ms = _matter_store(home)
        matters = ms.list_matters()
        assert len(matters) == 1
        assert matters[0]["title"] == "Test Matter"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_matters.py::TestCreateMatter -v`
Expected: FAIL — 404/405

- [ ] **Step 3: Create the matter form template**

Create `matteros/web/templates/matter_form.html`:

```html
{% extends "base.html" %}
{% block title %}New Matter{% endblock %}
{% block content %}
<div style="display:flex; align-items:center; gap:1rem; margin-bottom:1rem">
    <a href="/matters" style="color:var(--muted); text-decoration:none;">&larr; All Matters</a>
</div>
<h2>New Matter</h2>

<form method="POST" action="/matters/new" class="card">
    <div class="field" style="margin-bottom:1rem;">
        <label style="display:block; font-size:0.8rem; color:var(--muted); margin-bottom:0.3rem;">Title</label>
        <input type="text" name="title" required style="width:100%;">
    </div>
    <div style="display:flex; gap:1rem; margin-bottom:1rem;">
        <div style="flex:1;">
            <label style="display:block; font-size:0.8rem; color:var(--muted); margin-bottom:0.3rem;">Type</label>
            <select name="type" style="width:100%;">
                <option value="request">Request</option>
                <option value="contract">Contract</option>
                <option value="compliance">Compliance</option>
                <option value="custom">Custom</option>
            </select>
        </div>
        <div style="flex:1;">
            <label style="display:block; font-size:0.8rem; color:var(--muted); margin-bottom:0.3rem;">Priority</label>
            <select name="priority" style="width:100%;">
                <option value="low">Low</option>
                <option value="medium" selected>Medium</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
            </select>
        </div>
    </div>
    <div style="display:flex; gap:1rem; margin-bottom:1rem;">
        <div style="flex:1;">
            <label style="display:block; font-size:0.8rem; color:var(--muted); margin-bottom:0.3rem;">Due Date</label>
            <input type="date" name="due_date">
        </div>
        <div style="flex:1; display:flex; align-items:flex-end;">
            <label style="font-size:0.8rem; color:var(--muted); display:flex; align-items:center; gap:0.5rem;">
                <input type="checkbox" name="privileged" value="1" checked> Privileged
            </label>
        </div>
    </div>
    <button type="submit" class="btn btn-green">Create Matter</button>
</form>
{% endblock %}
```

- [ ] **Step 4: Add the create matter routes**

Add to `matteros/web/app.py`. IMPORTANT: place the `/matters/new` GET route BEFORE the `/matters/{matter_id}` route so FastAPI matches it first:

```python
    @app.get("/matters/new", response_class=HTMLResponse)
    async def new_matter_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "matter_form.html", {})

    @app.post("/matters/new")
    async def create_matter(request: Request) -> Response:
        store = _store()
        ms = MatterStore(store)
        form = await request.form()

        title = str(form.get("title", "")).strip()
        if not title:
            raise HTTPException(status_code=422, detail="Title is required")

        matter_type = str(form.get("type", "request"))
        priority = str(form.get("priority", "medium"))
        due_date = str(form.get("due_date", "")).strip() or None
        privileged = form.get("privileged") == "1"

        user = request.state.user
        matter_id = ms.create_matter(
            title=title,
            type=matter_type,
            priority=priority,
            privileged=privileged,
            due_date=due_date,
            assignee_id=user["id"],
        )
        return RedirectResponse(f"/matters/{matter_id}", status_code=303)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_web_matters.py::TestCreateMatter -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/web/app.py matteros/web/templates/matter_form.html tests/test_web_matters.py
git commit -m "feat(web): add create matter form and route"
```

---

### Task 7: Deadlines Route and Template

**Files:**
- Modify: `matteros/web/app.py`
- Create: `matteros/web/templates/deadlines.html`
- Modify: `tests/test_web_matters.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_matters.py`:

```python
class TestDeadlines:
    def test_deadlines_returns_200(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        response = client.get("/deadlines")
        assert response.status_code == 200
        assert "Deadlines" in response.text

    def test_deadlines_shows_upcoming(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        client = _make_client(home)
        ms = _matter_store(home)
        matter_id = ms.create_matter(title="Filing", type="compliance")
        ms.create_deadline(matter_id=matter_id, label="Q4 Report", due_date="2027-12-31")

        response = client.get("/deadlines")
        assert "Q4 Report" in response.text
        assert "Filing" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_matters.py::TestDeadlines -v`
Expected: FAIL — 404

- [ ] **Step 3: Create the deadlines template**

Create `matteros/web/templates/deadlines.html`:

```html
{% extends "base.html" %}
{% block title %}Deadlines{% endblock %}
{% block content %}
<h2>Deadlines</h2>
<div class="stats">
    <div class="stat">
        <div class="value">{{ overdue | length }}</div>
        <div class="label">Overdue</div>
    </div>
    <div class="stat">
        <div class="value">{{ this_week | length }}</div>
        <div class="label">This Week</div>
    </div>
    <div class="stat">
        <div class="value">{{ this_month | length }}</div>
        <div class="label">This Month</div>
    </div>
</div>

{% if overdue %}
<h2 style="color:var(--red)">Overdue</h2>
<table>
    <thead><tr><th>Matter</th><th>Deadline</th><th>Due</th><th>Type</th></tr></thead>
    <tbody>
    {% for d in overdue %}
    <tr>
        <td><a href="/matters/{{ d.matter_id }}" style="color:var(--accent)">{{ d.matter_title }}</a></td>
        <td>{{ d.label }}</td>
        <td><span class="badge badge-overdue">{{ d.due_date[:10] }}</span></td>
        <td>{{ d.type }}</td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% endif %}

{% if upcoming %}
<h2>Upcoming</h2>
<table>
    <thead><tr><th>Matter</th><th>Deadline</th><th>Due</th><th>Type</th></tr></thead>
    <tbody>
    {% for d in upcoming %}
    <tr>
        <td><a href="/matters/{{ d.matter_id }}" style="color:var(--accent)">{{ d.matter_title }}</a></td>
        <td>{{ d.label }}</td>
        <td>{{ d.due_date[:10] }}</td>
        <td>{{ d.type }}</td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% endif %}

{% if not overdue and not upcoming %}
<div class="card" style="text-align:center; color:var(--muted); padding:2rem;">
    No deadlines found.
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Add the deadlines route**

Add to `matteros/web/app.py`:

```python
    @app.get("/deadlines", response_class=HTMLResponse)
    async def deadlines_page(request: Request) -> HTMLResponse:
        store = _store()
        ms = MatterStore(store)

        today = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00")
        week = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")
        month = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%dT23:59:59")
        far_future = "2099-12-31T23:59:59"

        all_pending = ms.list_upcoming_deadlines(before=far_future)

        overdue = [d for d in all_pending if d["due_date"] < today]
        this_week = [d for d in all_pending if today <= d["due_date"] <= week]
        this_month = [d for d in all_pending if today <= d["due_date"] <= month]
        upcoming = [d for d in all_pending if d["due_date"] >= today]

        return templates.TemplateResponse(request, "deadlines.html", {
            "overdue": overdue,
            "this_week": this_week,
            "this_month": this_month,
            "upcoming": upcoming,
        })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_web_matters.py::TestDeadlines -v`
Expected: All 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add matteros/web/app.py matteros/web/templates/deadlines.html tests/test_web_matters.py
git commit -m "feat(web): add Deadlines route with overdue/upcoming grouping"
```

---

### Task 8: Clean Up Old Routes and Full Regression Test

**Files:**
- Modify: `matteros/web/app.py`

- [ ] **Step 1: Remove old playbook-centric routes**

In `matteros/web/app.py`, remove these route handlers that reference the old model:
- `runs_page` (`GET /runs`)
- `run_trigger_page` (`GET /runs/new`)
- `run_detail` (`GET /runs/{run_id}`)
- `run_live_stream` (`GET /runs/{run_id}/live`)
- `approvals_page` (`GET /approvals`)
- `drafts_page` (`GET /drafts`)
- `approve_draft` (`POST /drafts/{draft_id}/approve`)
- `reject_draft` (`POST /drafts/{draft_id}/reject`)
- `settings_page` (`GET /settings`)
- `api_runs` (`GET /api/runs`)
- `api_trigger_run` (`POST /api/runs`)
- `event_stream` (`GET /events/stream`)

Also remove:
- The `RunService` import and `_run_service()` helper
- The `_run_event_bus` instance
- The `DraftManager` import

Keep:
- Login/logout routes
- Session middleware
- Audit page route (`GET /audit`)
- Audit API route (`GET /api/audit`)

- [ ] **Step 2: Remove old templates**

Delete these template files that are no longer used:
- `matteros/web/templates/dashboard.html`
- `matteros/web/templates/runs.html`
- `matteros/web/templates/run_detail.html`
- `matteros/web/templates/run_trigger.html`
- `matteros/web/templates/approvals.html`
- `matteros/web/templates/drafts.html`
- `matteros/web/templates/settings.html`

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ --ignore=tests/cassettes -v`

Some old web tests will fail because the routes they tested are removed. Remove or update these test files:
- `tests/test_web_run_sse.py` — references removed `/runs/{id}/live` route
- `tests/test_web_run_trigger.py` — references removed `/api/runs` route
- `tests/test_web_sse_new_events.py` — references removed `/events/stream` route
- `tests/test_run_service.py` — tests RunService which is no longer used from web

For each, either delete the file if it only tests removed functionality, or keep it if it tests code still used by the CLI.

- [ ] **Step 4: Verify all tests pass**

Run: `pytest tests/ --ignore=tests/cassettes -q`
Expected: All tests PASS with 0 failures

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(web): remove old playbook routes and templates, clean up imports"
```

---

## Summary

After completing all 8 tasks:

- **My Queue** (`/`) — shows the logged-in lawyer's assigned matters sorted by urgency
- **All Matters** (`/matters`) — filterable list of all matters with status/type filters
- **Matter Detail** (`/matters/{id}`) — full view with activity thread, deadlines, relationships, comment posting, status updates
- **Deadlines** (`/deadlines`) — grouped by overdue/this week/this month
- **Create Matter** (`/matters/new`) — form for creating new matters
- **Old routes removed** — runs, approvals, drafts, settings pages cleaned up

**Next plans:** Automation Engine (intake, deadline alerts, stale detection, LLM triage) and Jira Sync.
