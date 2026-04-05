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
        db = SQLiteStore(home / "matteros.db")
        um = UserManager(db)
        user = um.get_user_by_username("lawyer")

        m1 = ms.create_matter(title="Urgent NDA", type="contract", priority="urgent")
        ms.update_matter(m1, assignee_id=user["id"])
        ms.create_matter(title="Unassigned", type="request")

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
        ms.create_matter(title="Open", type="request")
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
