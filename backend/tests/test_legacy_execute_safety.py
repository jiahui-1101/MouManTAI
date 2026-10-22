"""The public legacy execute route must fail closed without durable approval authority."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.core.models import AuditEventRecord, OutboxEventRecord
from app.core.policy import authorize


def test_approve_plan_policy_requires_manager_or_owner() -> None:
    with pytest.raises(DomainError) as error:
        authorize("user_staff_01", "STAFF", "APPROVE_PLAN", plan_version=1)
    assert error.value.code == "APPROVAL_REQUIRED"
    authorize("user_manager_01", "MANAGER", "APPROVE_PLAN", plan_version=1)


def _request(*, tenant: str = "tenant_demo_01", commitment: str = "com_execute_guard") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "expected_commitment_version": 1,
        "plan": {
            "tenant_id": tenant,
            "recovery_case_id": "rc_execute_guard",
            "plan_id": "plan_execute_guard",
            "plan_version": 1,
            "commitment_id": commitment,
            "based_on_assessment_id": "fa_execute_guard",
            "snapshot_version": 1,
            "feasibility_status": "FEASIBLE",
            "estimated_extra_cost": "0",
            "currency": "MYR",
            "estimated_delay_minutes": 0,
            "actions": [{
                "action_id": "act_execute_guard",
                "type": "REALLOCATE_STOCK",
                "requires_approval": True,
                "idempotency_key": "idem_execute_guard",
            }],
            "approval_state": "APPROVED",
            "execution_state": "PENDING",
        },
        "current_snapshot_version": 1,
        "approved_at": (now - timedelta(minutes=1)).isoformat(),
        "approval_expires_at": (now + timedelta(hours=1)).isoformat(),
        "reason": "Client claims this plan was approved",
    }


@pytest.mark.parametrize(
    ("actor", "role_header", "expected_code"),
    [
        ("user_staff_01", "MANAGER", "APPROVAL_REQUIRED"),
        ("unknown_actor", "MANAGER", "APPROVAL_REQUIRED"),
        ("user_manager_01", "MANAGER", "EXECUTION_APPROVAL_UNAVAILABLE"),
    ],
)
def test_public_execute_rejects_demo_identity_and_client_approval_claims(
    client: TestClient,
    session: Session,
    actor: str,
    role_header: str,
    expected_code: str,
) -> None:
    response = client.post(
        "/v1/commitments/com_execute_guard/recovery/execute",
        headers={"X-Tenant-ID": "tenant_demo_01", "X-Actor-ID": actor, "X-Actor-Role": role_header},
        json=_request(),
    )
    assert response.status_code == (403 if expected_code == "APPROVAL_REQUIRED" else 503)
    assert response.json()["code"] == expected_code
    assert session.scalars(select(AuditEventRecord)).all() == []
    assert session.scalars(select(OutboxEventRecord)).all() == []


@pytest.mark.parametrize("change", [
    {"approved_at": "2030-01-01T00:00:00+00:00"},
    {"approval_expires_at": "2020-01-01T00:00:00+00:00"},
    {"expected_commitment_version": 99},
])
def test_public_execute_rejects_forged_or_stale_claims_without_authority(
    client: TestClient, change: dict
) -> None:
    request = _request()
    request.update(change)
    response = client.post(
        "/v1/commitments/com_execute_guard/recovery/execute",
        headers={"X-Tenant-ID": "tenant_demo_01", "X-Actor-ID": "user_manager_01"},
        json=request,
    )
    assert response.status_code == 503
    assert response.json()["code"] == "EXECUTION_APPROVAL_UNAVAILABLE"


def test_public_execute_rejects_cross_tenant_plan_before_authority(client: TestClient) -> None:
    response = client.post(
        "/v1/commitments/com_execute_guard/recovery/execute",
        headers={"X-Tenant-ID": "tenant_demo_01", "X-Actor-ID": "user_manager_01"},
        json=_request(tenant="tenant_other"),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "RECOVERY_SCOPE_MISMATCH"
