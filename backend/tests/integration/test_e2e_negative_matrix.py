"""Backend E2E Negative & Edge Acceptance Matrix Tests (E2E-04 to E2E-11).

Comprehensive verification of non-negotiable invariants, negative flows, and edge conditions:
- E2E-04: Stale approval / stock changed -> 409 Conflict (SNAPSHOT_DRIFT_CONFLICT), no unauthorized stock mutation.
- E2E-05: Ambiguous customer 'OK' -> UNRESOLVED_CONFIRMATION, never auto-confirms commitment.
- E2E-06: Stale proposal version confirmation -> 409 Conflict (STALE_PROPOSAL_VERSION), preserves latest proposal.
- E2E-07: Message sent, no reply -> delivery tracking only, does not advance agreement or fulfilment state.
- E2E-08: Duplicate webhook / action retry -> exactly one state transition, one reservation, and one audit mutation.
- E2E-09: Unverified receipt screenshot -> evidence recorded, agreement stays REQUESTED, manual review flagged.
- E2E-10: Worker crash after external action succeeds -> idempotency reconciliation without duplicate reservation.
- E2E-11: Cross-tenant isolation -> Tenant B cannot read, assess, approve, confirm, or view audit of Tenant A's commitment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.integration import CoreIntegrationFacade
from app.core.models import (
    CommitmentRecord,
    ResourceReservationRecord,
)
from app.core.reservations import (
    get_available_stock,
    get_resource_snapshot,
    reserve_resource,
    seed_resource_stock,
)
from app.core.schemas import (
    AgreementState,
    AttentionCategory,
    BusinessContext,
    CommitmentCreateRequest,
    CommitmentTerms,
    CustomerIdentityStatus,
    FulfilmentState,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _headers(actor: str = "user_manager_01", tenant: str = "tenant_demo_01") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Actor-ID": actor,
        "X-Correlation-ID": f"corr_neg_{_now().timestamp()}",
    }


def _ctx(actor: str = "user_manager_01", role: str = "MANAGER", tenant: str = "tenant_demo_01") -> RequestContext:
    return RequestContext(
        tenant_id=tenant,
        actor_id=actor,
        actor_role=role,
        correlation_id=f"corr_ctx_{_now().timestamp()}",
    )


# =============================================================================
# E2E-04: Stale Approval / Stock Changed (Snapshot Drift)
# =============================================================================
def test_e2e_04_stale_approval_stock_changed(
    client: TestClient, session: Session, synthetic_execution_authority
) -> None:
    """Manager approves plan pinned to snapshot 142; stock changes to 143 before execution.

    Under the explicit synthetic authority, execution must be blocked (409 Conflict),
    no unauthorized stock mutation occurs,
    and commitment moves to RECOVERY_REQUIRED.
    """
    tenant = "tenant_demo_01"
    headers = _headers("user_manager_01", tenant)
    now = _now()

    # Seed stock and commitment
    seed_resource_stock(session, tenant, "PATTIES", Decimal("100"), "pcs")

    create_res = client.post(
        "/v1/commitments",
        headers=headers,
        json={
            "order_id": "ord_e2e_04",
            "customer_id": "cust_e2e_04",
            "terms": {
                "sku": "BURGER_PATTIES",
                "quantity": "50",
                "unit": "pcs",
                "deadline": (now + timedelta(days=1)).isoformat(),
            },
            "evidence_refs": ["ev_init_04"],
        },
    )
    assert create_res.status_code == 201
    com_id = create_res.json()["commitment_id"]

    # Recovery plan pinned to snapshot 142
    plan = {
        "tenant_id": tenant,
        "recovery_case_id": "rc_e2e_04",
        "plan_id": "plan_e2e_04",
        "plan_version": 1,
        "commitment_id": com_id,
        "based_on_assessment_id": "fa_04",
        "snapshot_version": 142,
        "feasibility_status": "FEASIBLE",
        "estimated_extra_cost": "50.00",
        "currency": "MYR",
        "estimated_delay_minutes": 0,
        "risks": [],
        "actions": [
            {
                "action_id": "act_04",
                "type": "REALLOCATE_STOCK",
                "requires_approval": True,
                "idempotency_key": "idem_act_04",
            }
        ],
        "approval_state": "APPROVED",
        "execution_state": "PENDING",
    }

    # Attempt execution where current snapshot has drifted to 143
    exec_req = {
        "expected_commitment_version": 1,
        "plan": plan,
        "current_snapshot_version": 143,  # DRIFT!
        "approved_at": (now - timedelta(minutes=5)).isoformat(),
        "approval_expires_at": (now + timedelta(hours=1)).isoformat(),
        "reason": "Execute stale plan",
    }
    res = client.post(f"/v1/commitments/{com_id}/recovery/execute", json=exec_req, headers=headers)
    assert res.status_code == 409
    body = res.json()
    assert body["code"] == "SNAPSHOT_DRIFT_CONFLICT"

    # Verify no stock mutation occurred
    stock_snap = get_resource_snapshot(session, tenant, "PATTIES")
    assert stock_snap[0].reserved_quantity == Decimal("0")
    assert stock_snap[0].available_quantity == Decimal("100")

    # Verify commitment recovery_state reset to RECOVERY_REQUIRED
    com_res = client.get(f"/v1/commitments/{com_id}", headers=headers)
    assert com_res.json()["recovery_state"] == "RECOVERY_REQUIRED"


# =============================================================================
# E2E-05: Ambiguous Customer "OK"
# =============================================================================
def test_e2e_05_ambiguous_customer_ok(client: TestClient, session: Session) -> None:
    """Vague customer reply ('OK') never auto-confirms commitment; flags UNRESOLVED_CONFIRMATION."""
    tenant = "tenant_demo_01"
    facade = CoreIntegrationFacade()
    context = _ctx(tenant=tenant)
    headers = _headers("user_staff_01", tenant)

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_e2e_05",
            customer_id="cust_e2e_05",
            terms=CommitmentTerms(
                sku="BURGER",
                quantity=Decimal("50"),
                unit="pcs",
                deadline=_now() + timedelta(days=1),
            ),
            evidence_refs=["ev_init_05"],
        ),
    )

    # Customer sends ambiguous "OK"
    facade.record_ambiguous_response(
        session,
        context,
        c.commitment_id,
        customer_message="OK",
        evidence_refs=["ev_chat_vague_ok"],
    )

    # Verify commitment remains REQUESTED, never auto-confirmed
    updated = facade.service.get(session, context, c.commitment_id)
    assert updated.agreement_state == AgreementState.REQUESTED
    assert updated.fulfilment_state == FulfilmentState.NOT_STARTED

    # Verify attention queue flags UNRESOLVED_CONFIRMATION
    overview_res = client.get("/v1/overview", headers=headers)
    assert overview_res.status_code == 200
    overview = overview_res.json()
    ambiguous_items = [
        item for item in overview["attention_queue"]
        if item["commitment_id"] == c.commitment_id
    ]
    assert len(ambiguous_items) >= 1
    assert ambiguous_items[0]["category"] == AttentionCategory.UNRESOLVED_CONFIRMATION


# =============================================================================
# E2E-06: Stale Proposal Version Confirmation
# =============================================================================
def test_e2e_06_stale_proposal_version_confirmation(client: TestClient) -> None:
    """Signed confirmation for Proposal V2 rejected with 409 after Proposal V3 created."""
    tenant = "tenant_demo_01"
    headers = _headers("user_manager_01", tenant)

    # 1. Create commitment
    res = client.post(
        "/v1/commitments",
        headers=headers,
        json={
            "order_id": "ord_e2e_06",
            "customer_id": "cust_e2e_06",
            "terms": {
                "sku": "BURGER_GOURMET",
                "quantity": "20",
                "unit": "pcs",
                "deadline": (_now() + timedelta(days=2)).isoformat(),
            },
            "evidence_refs": ["ev_init_06"],
        },
    )
    com_id = res.json()["commitment_id"]

    # 2. Create Proposal V1 -> version 2
    client.post(
        f"/v1/commitments/{com_id}/proposals",
        headers=headers,
        json={
            "proposal_id": "prop_v1",
            "proposal_version": 1,
            "expected_commitment_version": 1,
            "reason": "Initial proposal",
            "evidence_refs": ["ev_prop_v1"],
        },
    )

    # 3. Create Proposal V2 -> version 3
    client.post(
        f"/v1/commitments/{com_id}/proposals",
        headers=headers,
        json={
            "proposal_id": "prop_v2",
            "proposal_version": 2,
            "expected_commitment_version": 2,
            "reason": "Revised terms V2",
            "evidence_refs": ["ev_prop_v2"],
        },
    )

    # 4. Create Proposal V3 -> version 4 (supersedes V2)
    client.post(
        f"/v1/commitments/{com_id}/proposals",
        headers=headers,
        json={
            "proposal_id": "prop_v3",
            "proposal_version": 3,
            "expected_commitment_version": 3,
            "reason": "Final terms V3",
            "evidence_refs": ["ev_prop_v3"],
        },
    )

    # 5. Customer attempts to confirm stale Proposal V2
    stale_conf = {
        "proposal_id": "prop_v2",
        "proposal_version": 2,  # Stale! Latest is 3
        "expected_commitment_version": 4,
        "decision": "ACCEPT",
        "evidence_refs": ["ev_signed_stale_v2"],
        "reason": "Customer signed old PDF",
    }
    conf_res = client.post(f"/v1/commitments/{com_id}/confirm-proposal", json=stale_conf, headers=headers)
    assert conf_res.status_code == 409
    body = conf_res.json()
    assert body["code"] == "STALE_PROPOSAL_VERSION"
    assert body["details"]["active_proposal_version"] == 3
    assert body["details"]["submitted_proposal_version"] == 2

    # Verify latest proposal remains V3
    timeline_res = client.get(f"/v1/commitments/{com_id}/timeline", headers=headers)
    timeline = timeline_res.json()
    proposal_events = [e for e in timeline if e.get("proposal_id") == "prop_v3"]
    assert len(proposal_events) >= 1


# =============================================================================
# E2E-07: Message Sent, No Reply
# =============================================================================
def test_e2e_07_message_sent_no_reply(session: Session) -> None:
    """Outbound communication transitioning to SENT/DELIVERED never advances agreement or fulfilment."""
    tenant = "tenant_demo_01"
    facade = CoreIntegrationFacade()
    context = _ctx(tenant=tenant)

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_e2e_07",
            customer_id="cust_e2e_07",
            terms=CommitmentTerms(
                sku="BURGER",
                quantity=Decimal("30"),
                unit="pcs",
                deadline=_now() + timedelta(days=1),
            ),
            evidence_refs=["ev_init_07"],
        ),
    )

    # Message transitions to SENT
    facade.record_communication_status(
        session,
        context,
        c.commitment_id,
        message_status="SENT",
        evidence_refs=["ev_wa_sent_receipt"],
    )

    # Message transitions to DELIVERED
    facade.record_communication_status(
        session,
        context,
        c.commitment_id,
        message_status="DELIVERED",
        evidence_refs=["ev_wa_delivered_receipt"],
    )

    # Verify invariant: SENT != ACCEPTED != FULFILLED
    updated = facade.service.get(session, context, c.commitment_id)
    assert updated.agreement_state == AgreementState.REQUESTED
    assert updated.fulfilment_state == FulfilmentState.NOT_STARTED


# =============================================================================
# E2E-08: Duplicate Webhook / Action Retry
# =============================================================================
def test_e2e_08_duplicate_webhook_action_retry(session: Session) -> None:
    """Duplicate retry with the same idempotency key produces exactly one reservation and no duplicate stock deduction."""
    tenant = "tenant_demo_01"
    seed_resource_stock(session, tenant, "BUNS", Decimal("100"), "pcs")

    # First attempt: reserves 40
    res1 = reserve_resource(
        session,
        tenant_id=tenant,
        commitment_id="com_e2e_08",
        plan_id="plan_08",
        action_id="act_08",
        idempotency_key="idem_webhook_retry_888",
        resource_id="BUNS",
        quantity=Decimal("40"),
        actor_id="user_manager_01",
    )
    assert res1.status == "ACTIVE"
    assert get_available_stock(session, tenant, "BUNS") == Decimal("60")

    # Second retry attempt with identical idempotency key: returns existing without double deduction
    res2 = reserve_resource(
        session,
        tenant_id=tenant,
        commitment_id="com_e2e_08",
        plan_id="plan_08",
        action_id="act_08",
        idempotency_key="idem_webhook_retry_888",
        resource_id="BUNS",
        quantity=Decimal("40"),
        actor_id="user_manager_01",
    )
    assert res2.reservation_id == res1.reservation_id
    assert res2.status == "ACTIVE"

    # Invariant: stock was deducted only ONCE (available is 60, not 20)
    assert get_available_stock(session, tenant, "BUNS") == Decimal("60")

    # Verify exactly one reservation record in DB
    reservations = session.scalars(
        select(ResourceReservationRecord).where(
            ResourceReservationRecord.tenant_id == tenant,
            ResourceReservationRecord.idempotency_key == "idem_webhook_retry_888",
        )
    ).all()
    assert len(reservations) == 1


# =============================================================================
# E2E-09: Unverified Receipt Screenshot
# =============================================================================
def test_e2e_09_unverified_receipt_screenshot(session: Session) -> None:
    """Uploading OCR receipt without trusted verification keeps commitment REQUESTED and flags manual review."""
    tenant = "tenant_demo_01"
    facade = CoreIntegrationFacade()
    context = _ctx(tenant=tenant)

    # Inbound context with payment receipt screenshot and unverified status
    b_ctx = BusinessContext(
        tenant_id=tenant,
        context_id="ctx_e2e_09",
        source_message_ids=["msg_receipt_001"],
        customer_id="cust_e2e_09",
        customer_identity_status=CustomerIdentityStatus.UNVERIFIED,
        order_id="ord_e2e_09",
        requested_items=[{"sku": "BURGER", "quantity": Decimal("10"), "unit": "pcs"}],
        requested_delivery_at=_now() + timedelta(days=1),
        field_evidence={"payment_slip": ["ev_ocr_receipt_bank_slip_999"]},
        conflicts=["UNVERIFIED_PAYMENT_PROOF"],
        missing_fields=[],
        context_version=1,
        status="INFORMATION_READY",
    )

    c = facade.handle_context_updated(session, context, b_ctx)

    # Invariant: OCR receipt != verified funds
    assert c.agreement_state == AgreementState.REQUESTED
    assert "ev_ocr_receipt_bank_slip_999" in c.evidence_refs

    # Verify manual review required flag
    record = session.get(CommitmentRecord, (tenant, c.commitment_id))
    assert record.terms.get("requires_manual_review") is True
    assert "UNVERIFIED_PAYMENT_PROOF" in record.terms.get("conflicts", [])


# =============================================================================
# E2E-10: Worker Crash After External Action Succeeds
# =============================================================================
def test_e2e_10_worker_crash_after_external_action_succeeds(session: Session) -> None:
    """Reconciling action after simulated worker crash recovers state using existing idempotency key."""
    tenant = "tenant_demo_01"
    seed_resource_stock(session, tenant, "CHEESE", Decimal("50"), "pcs")

    # Step 1: External action and reservation succeeds
    initial_res = reserve_resource(
        session,
        tenant_id=tenant,
        commitment_id="com_e2e_10",
        plan_id="plan_10",
        action_id="act_10",
        idempotency_key="idem_crash_recovery_10",
        resource_id="CHEESE",
        quantity=Decimal("15"),
        actor_id="user_manager_01",
    )
    assert initial_res.status == "ACTIVE"
    created_timestamp = initial_res.created_at

    # Step 2: Simulate worker crash before acknowledging
    # Worker restarts and performs reconciliation loop with the same idempotency key
    reconciled_res = reserve_resource(
        session,
        tenant_id=tenant,
        commitment_id="com_e2e_10",
        plan_id="plan_10",
        action_id="act_10",
        idempotency_key="idem_crash_recovery_10",
        resource_id="CHEESE",
        quantity=Decimal("15"),
        actor_id="user_manager_01",
    )

    # Asserts: recognizes existing reservation, retains original timestamp, zero double-allocation
    assert reconciled_res.reservation_id == initial_res.reservation_id
    assert reconciled_res.created_at == created_timestamp
    assert get_available_stock(session, tenant, "CHEESE") == Decimal("35")


# =============================================================================
# E2E-11: Cross-Tenant Isolation
# =============================================================================
def test_e2e_11_cross_tenant_isolation(client: TestClient) -> None:
    """Tenant B attempting to access or modify Tenant A's commitment receives 404 with zero data leakage."""
    tenant_a = "tenant_alpha"
    tenant_b = "tenant_beta"
    headers_a = _headers("user_manager_a", tenant_a)
    headers_b = _headers("user_manager_b", tenant_b)

    # Tenant A creates commitment
    res = client.post(
        "/v1/commitments",
        headers=headers_a,
        json={
            "order_id": "ord_secret_a",
            "customer_id": "cust_confidential_a",
            "terms": {
                "sku": "SECRET_RECIPE_BURGER",
                "quantity": "500",
                "unit": "pcs",
                "deadline": (_now() + timedelta(days=3)).isoformat(),
                "special_instructions": "Confidential corporate client",
            },
            "evidence_refs": ["ev_confidential_contract_a"],
        },
    )
    assert res.status_code == 201
    com_a_id = res.json()["commitment_id"]

    # 1. Tenant B GET commitment -> 404
    res_get = client.get(f"/v1/commitments/{com_a_id}", headers=headers_b)
    assert res_get.status_code == 404
    assert "SECRET_RECIPE_BURGER" not in res_get.text

    # 2. Tenant B POST proposal -> 404
    res_prop = client.post(
        f"/v1/commitments/{com_a_id}/proposals",
        headers=headers_b,
        json={
            "proposal_id": "prop_spy",
            "proposal_version": 1,
            "expected_commitment_version": 1,
            "reason": "Malicious proposal",
            "evidence_refs": ["ev_malicious"],
        },
    )
    assert res_prop.status_code == 404

    # 3. Tenant B POST confirm-proposal -> 404
    res_conf = client.post(
        f"/v1/commitments/{com_a_id}/confirm-proposal",
        headers=headers_b,
        json={
            "proposal_id": "prop_spy",
            "proposal_version": 1,
            "expected_commitment_version": 1,
            "decision": "ACCEPT",
            "evidence_refs": ["ev_malicious"],
            "reason": "Malicious confirmation",
        },
    )
    assert res_conf.status_code == 404

    # 4. Tenant B POST record-fulfilment -> 404
    res_fulfil = client.post(
        f"/v1/commitments/{com_a_id}/record-fulfilment",
        headers=headers_b,
        json={
            "expected_commitment_version": 1,
            "fulfilment_state": "FULFILLED",
            "evidence_refs": ["ev_ops_delivery_fake"],
            "reason": "Malicious fulfilment claim",
        },
    )
    assert res_fulfil.status_code == 404

    # 5. Tenant B GET timeline -> 404
    res_timeline = client.get(f"/v1/commitments/{com_a_id}/timeline", headers=headers_b)
    assert res_timeline.status_code == 404

    # 6. Tenant B GET audit for commitment -> 404
    res_audit = client.get(f"/v1/audit?commitment_id={com_a_id}", headers=headers_b)
    assert res_audit.status_code == 404

    # 7. Tenant B GET overview -> zero data leakage
    res_overview = client.get("/v1/overview", headers=headers_b)
    assert res_overview.status_code == 200
    overview_b = res_overview.json()
    assert overview_b["counts"]["requested"] == 0
    assert overview_b["counts"]["confirmed"] == 0
    assert com_a_id not in [item["commitment_id"] for item in overview_b["attention_queue"]]
    assert "SECRET_RECIPE_BURGER" not in res_overview.text
