"""Per-matter authorization for the in-house legal ops model."""
from __future__ import annotations

from typing import Any

_CONTACT_VISIBLE_FIELDS = {"id", "title", "status", "due_date", "priority"}


def can_access_matter(
    *,
    user: dict[str, Any] | None = None,
    contact_id: str | None = None,
    matter: dict[str, Any],
    linked_contact_ids: list[str] | None = None,
) -> bool:
    if user is not None:
        role = user.get("role", "")
        if role in ("legal", "gc"):
            return True
        return False

    if contact_id is not None:
        if matter.get("privileged", 1):
            return False
        if linked_contact_ids is None:
            return False
        return contact_id in linked_contact_ids

    return False


def visible_matter_fields(
    *,
    user: dict[str, Any] | None = None,
    contact_id: str | None = None,
    matter: dict[str, Any],
) -> dict[str, Any]:
    if user is not None:
        role = user.get("role", "")
        if role in ("legal", "gc"):
            return matter

    return {k: v for k, v in matter.items() if k in _CONTACT_VISIBLE_FIELDS}
