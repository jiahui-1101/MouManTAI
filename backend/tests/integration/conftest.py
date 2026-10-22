"""Explicit synthetic authority for legacy Core journey tests only.

This is a test double, not durable Manager Approval or production authorization.
"""

import pytest

from app.core.errors import DomainError
from app.core.router import get_recovery_execution_authority
from app.main import app


@pytest.fixture
def synthetic_execution_authority():
    class SyntheticExecutionAuthority:
        def verify(self, db, context, commitment_id, request) -> None:
            if context.actor_role not in {"MANAGER", "OWNER"}:
                raise DomainError("APPROVAL_REQUIRED", "Manager role required", status_code=403)
            if request.plan.approval_state.value != "APPROVED":
                raise DomainError("APPROVAL_REQUIRED", "Synthetic plan is not approved", status_code=403)
            if request.plan.tenant_id != context.tenant_id or request.plan.commitment_id != commitment_id:
                raise DomainError("RECOVERY_SCOPE_MISMATCH", "Synthetic plan scope mismatch", status_code=403)

    previous = app.dependency_overrides.get(get_recovery_execution_authority)
    app.dependency_overrides[get_recovery_execution_authority] = SyntheticExecutionAuthority
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_recovery_execution_authority, None)
        else:
            app.dependency_overrides[get_recovery_execution_authority] = previous
