"""Tests for updated roles and permissions."""
from __future__ import annotations

from matteros.team.users import VALID_ROLES, ROLE_PERMISSIONS


def test_valid_roles_include_legal_and_gc():
    assert "legal" in VALID_ROLES
    assert "gc" in VALID_ROLES


def test_legal_role_permissions():
    perms = ROLE_PERMISSIONS["legal"]
    assert "manage_matters" in perms
    assert "view_matters" in perms
    assert "view_audit" in perms
    assert "manage_deadlines" in perms
    assert "manage_contacts" in perms


def test_gc_role_permissions():
    perms = ROLE_PERMISSIONS["gc"]
    assert "manage_matters" in perms
    assert "view_matters" in perms
    assert "manage_users" in perms
    assert "view_audit" in perms
    assert "view_dashboard" in perms
    assert "manage_deadlines" in perms
    assert "manage_contacts" in perms


def test_gc_has_all_legal_permissions():
    legal = ROLE_PERMISSIONS["legal"]
    gc = ROLE_PERMISSIONS["gc"]
    assert legal.issubset(gc)
