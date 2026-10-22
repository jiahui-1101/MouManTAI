"""Explicit synthetic scope; header simulation never authenticates production."""
from dataclasses import dataclass
import os

from app.core.dependencies import ACTOR_ROLES, RequestContext
from app.core.errors import DomainError
from app.core import policy


def deny(code, message, status=403):
    raise DomainError(code, message, status_code=status)


@dataclass(frozen=True)
class SyntheticScope:
    enabled: bool = False
    tenants: frozenset[str] = frozenset()

    @classmethod
    def from_environment(cls):
        # Existing integration_mode=SYNTHETIC is a response label, not an opt-in.
        # Unknown environments/configuration stay closed, including conflicting prod.
        mode = os.getenv("P4_RUNTIME_MODE", "")
        environment = os.getenv("APP_ENV", "")
        names = frozenset(x.strip() for x in os.getenv("P4_SYNTHETIC_TENANTS", "").split(",") if x.strip())
        known = frozenset({"synthetic_tenant_a", "synthetic_tenant_b"})
        valid = mode == "SYNTHETIC" and environment == "synthetic" and bool(names) and names <= known
        return cls(valid, names if valid else frozenset())

    def require(self, context: RequestContext, *, manager=False):
        if not self.enabled:
            deny("PRODUCTION_AUTH_UNAVAILABLE", "Trusted production authentication is unavailable", 503)
        if context.tenant_id not in self.tenants:
            deny("SYNTHETIC_SCOPE_DENIED", "Tenant is outside the explicit synthetic scope")
        current = ACTOR_ROLES.get(context.actor_id)
        if current not in {"OWNER", "MANAGER", "STAFF"} or current != context.actor_role:
            deny("SYNTHETIC_ACTOR_INVALID", "Current synthetic actor mapping is invalid")
        if manager and current not in {"OWNER", "MANAGER"}:
            deny("MANAGER_PERMISSION_DENIED", "A synthetic owner or manager is required")

    def authorize(self, context, action):
        self.require(context, manager=True)
        # Core currently silently accepts unknown action names. Do not call one.
        if action not in policy.CONSEQUENTIAL_ACTIONS:
            deny("CORE_ACTION_POLICY_UNAVAILABLE", f"Core has not declared {action}", 503)
        policy.authorize(actor=context.actor_id, actor_role=context.actor_role, action_type=action)
