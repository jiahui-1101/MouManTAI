"""Authorization policy and role guards for consequential actions (D-005, R43)."""

from __future__ import annotations

from typing import Any

from .errors import DomainError

CONSEQUENTIAL_ACTIONS = {
    "EXECUTE_PLAN",
    "SUBMIT_PURCHASE_ORDER",
    "CANCEL_COMMITMENT",
    "APPROVE_PROPOSAL",
    "APPROVE_PLAN",
}


def authorize(
    actor: str,
    actor_role: str,
    action_type: str,
    plan_version: int | None = None,
    business_context: Any | None = None,
) -> None:
    """Enforce server-resolved role-based authorization for consequential actions (D-005, R43)."""
    if action_type in CONSEQUENTIAL_ACTIONS:
        if actor_role not in {"OWNER", "MANAGER"}:
            raise DomainError(
                "APPROVAL_REQUIRED",
                f"Role '{actor_role}' is not authorized to execute consequential action '{action_type}'; manager or owner authorization required",
                status_code=403,
            )
