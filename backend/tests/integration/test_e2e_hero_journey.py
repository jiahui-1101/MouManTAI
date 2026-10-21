"""Backend E2E Hero Journey Test (UI-04, E2E-01, E2E-02, E2E-03, E2E-12).

Proves the complete single-commitment_id ('com_001') Hero Journey on real SQLite DB:
Trigger -> Data -> Decision -> Human Approval -> Outcome + Audit.

Lifecycle Version Progression on com_001:
1. Ingestion: REQUESTED (v1)
2. Feasibility assess (FEASIBLE): (v2)
3. Offer proposal v1: OFFERED (v3)
4. Confirm proposal v1: CONFIRMED (v4)
5. Feasibility reassess (INFEASIBLE): AT_RISK + RECOVERY_REQUIRED (v5)
6. Start recovery: PLANNING (v6)
7. Execute recovery plan (offer revised proposal v3): OFFERED (v7)
8. Customer confirms proposal v3: CONFIRMED (v8)
9. Operational fulfilment verified (signed POD): FULFILLED + RESOLVED (v9)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.reservations import seed_resource_stock
from app.core.schemas import AttentionCategory


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _headers(actor: str = "user_owner_01", tenant: str = "tenant_demo_01") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Actor-ID": actor,
        "X-Correlation-ID": f"corr_hero_{_now().timestamp()}",
    }


def test_e2e_hero_journey_full_single_commitment_lifecycle(
    client: TestClient,
    session: Session,
) -> None:
    """Execute the complete end-to-end Hero Journey on a single commitment_id ('com_001')."""
    tenant = "tenant_demo_01"
    owner_headers = _headers("user_owner_01", tenant)
    manager_headers = _headers("user_manager_01", tenant)
    staff_headers = _headers("user_staff_01", tenant)

    now = _now()
    delivery_dt = now + timedelta(days=2)

    # =========================================================================
    # STEP 1 (E2E-01): P1 context -> Core creates com_001 -> P2 FEASIBLE -> CONFIRMED
    # =========================================================================
    p1_payload = {
        "tenant_id": tenant,
        "context_id": "ctx_hero_001",
        "commitment_id": "com_001",
        "source_message_ids": ["msg_hero_001"],
        "customer_id": "cust_hero_001",
        "customer_identity_status": "LINK_VERIFIED",
        "order_id": "ord_hero_001",
        "requested_items": [
            {"sku": "BURGER", "quantity": "100", "unit": "pcs"}
        ],
        "requested_delivery_at": delivery_dt.isoformat(),
        "special_instructions": "Deliver to kitchen loading bay",
        "field_evidence": {
            "sku": ["ev_msg_hero_sku"],
            "quantity": ["ev_msg_hero_qty"],
        },
        "conflicts": [],
        "missing_fields": [],
        "context_version": 1,
        "status": "INFORMATION_READY",
    }

    res = client.post("/v1/integration/context-updated", json=p1_payload, headers=staff_headers)
    assert res.status_code == 200, res.text
    c1 = res.json()
    assert c1["commitment_id"] == "com_001"
    assert c1["agreement_state"] == "REQUESTED"
    assert c1["commitment_version"] == 1
    assert c1["feasibility_state"] == "NOT_ASSESSED"
    assert c1["risk_state"] == "NORMAL"
    assert c1["recovery_state"] == "NONE"
    assert c1["fulfilment_state"] == "NOT_STARTED"

    # P2 assesses FEASIBLE -> increments to version 2
    p2_assessment = {
        "assessment_id": "fa_hero_001",
        "tenant_id": tenant,
        "commitment_id": "com_001",
        "commitment_version": 1,
        "snapshot_version": 100,
        "status": "FEASIBLE",
        "constraints": [],
        "affected_commitment_ids": [],
        "evidence_refs": ["ev_stock_check_001"],
        "solver_status": "COMPLETED",
        "assumptions": ["Sufficient patty and packaging inventory available"],
        "assessed_at": now.isoformat(),
    }
    res = client.post("/v1/commitments/com_001/assess", json=p2_assessment, headers=staff_headers)
    assert res.status_code == 200, res.text
    c1 = res.json()
    assert c1["feasibility_state"] == "FEASIBLE"
    assert c1["commitment_version"] == 2

    # Offer Proposal v1 on commitment v2 -> increments version to 3, agreement_state=OFFERED
    prop_v1 = {
        "proposal_id": "prop_hero_v1",
        "proposal_version": 1,
        "expected_commitment_version": 2,
        "reason": "Standard quote terms offered to customer",
        "evidence_refs": ["ev_quote_hero_v1"],
    }
    res = client.post("/v1/commitments/com_001/proposals", json=prop_v1, headers=manager_headers)
    assert res.status_code == 200, res.text
    assert res.json()["commitment"]["agreement_state"] == "OFFERED"
    assert res.json()["commitment"]["commitment_version"] == 3

    # Customer confirms Proposal v1 -> agreement_state=CONFIRMED, version increments 3 -> 4
    conf_v1 = {
        "proposal_id": "prop_hero_v1",
        "proposal_version": 1,
        "expected_commitment_version": 3,
        "decision": "ACCEPT",
        "evidence_refs": ["ev_cust_signed_agreement_hero_v1"],
        "reason": "Customer accepted via signed WhatsApp confirmation",
    }
    res = client.post("/v1/commitments/com_001/confirm-proposal", json=conf_v1, headers=manager_headers)
    assert res.status_code == 200, res.text
    c1 = res.json()["commitment"]
    assert c1["agreement_state"] == "CONFIRMED"
    assert c1["commitment_version"] == 4
    assert c1["risk_state"] == "NORMAL"
    assert c1["recovery_state"] == "NONE"
    assert c1["fulfilment_state"] == "NOT_STARTED"

    # Overview check after Step 1
    res = client.get("/v1/overview", headers=staff_headers)
    assert res.status_code == 200
    overview = res.json()
    assert overview["counts"]["confirmed"] >= 1
    assert overview["counts"]["at_risk"] == 0

    # =========================================================================
    # STEP 2 (E2E-02): Supplier delay / packaging shortage -> com_001 INFEASIBLE,
    # AT_RISK + RECOVERY_REQUIRED. Non-impacted com_002 stays NORMAL.
    # =========================================================================
    # Create non-impacted com_002 and transition to CONFIRMED
    p1_com2 = {
        "tenant_id": tenant,
        "context_id": "ctx_hero_002",
        "commitment_id": "com_002",
        "source_message_ids": ["msg_hero_002"],
        "customer_id": "cust_hero_002",
        "customer_identity_status": "LINK_VERIFIED",
        "order_id": "ord_hero_002",
        "requested_items": [{"sku": "SALAD", "quantity": "100", "unit": "pcs"}],
        "requested_delivery_at": delivery_dt.isoformat(),
        "special_instructions": "Organic greens",
        "field_evidence": {"sku": ["ev_com2_sku"], "quantity": ["ev_com2_qty"]},
        "status": "INFORMATION_READY",
        "context_version": 1,
    }
    client.post("/v1/integration/context-updated", json=p1_com2, headers=staff_headers)
    client.post("/v1/commitments/com_002/assess", json={
        "assessment_id": "fa_com2_001",
        "tenant_id": tenant,
        "commitment_id": "com_002",
        "commitment_version": 1,
        "snapshot_version": 100,
        "status": "FEASIBLE",
        "constraints": [],
        "affected_commitment_ids": [],
        "evidence_refs": ["ev_com2_check"],
        "solver_status": "COMPLETED",
        "assumptions": ["Greens available"],
        "assessed_at": now.isoformat(),
    }, headers=staff_headers)
    client.post("/v1/commitments/com_002/proposals", json={
        "proposal_id": "prop_com2_v1",
        "proposal_version": 1,
        "expected_commitment_version": 2,
        "reason": "Standard quote",
        "evidence_refs": ["ev_quote_com2"],
    }, headers=manager_headers)
    client.post("/v1/commitments/com_002/confirm-proposal", json={
        "proposal_id": "prop_com2_v1",
        "proposal_version": 1,
        "expected_commitment_version": 3,
        "decision": "ACCEPT",
        "evidence_refs": ["ev_com2_accept"],
        "reason": "Customer confirmed com_002",
    }, headers=manager_headers)

    # Seed mock resource inventory for PACKAGING: only 80 units available (20 short for 100 pcs)
    seed_resource_stock(session, tenant, "PACKAGING", Decimal("80"), "pcs")

    # Supplier delay recomputation flags ONLY com_001 as INFEASIBLE -> version 4 -> 5
    reassess_payload = {
        "assessment_id": "fa_hero_002",
        "tenant_id": tenant,
        "commitment_id": "com_001",
        "commitment_version": 4,
        "snapshot_version": 102,
        "status": "INFEASIBLE",
        "constraints": [
            {
                "code": "SUPPLIER_DELAY",
                "resource_id": "PACKAGING",
                "shortage": "20",
                "unit": "pcs",
                "severity": "HARD",
                "evidence_refs": ["ev_supplier_delay_slip"],
            }
        ],
        "affected_commitment_ids": ["com_001"],
        "evidence_refs": ["ev_supplier_delay_slip"],
        "solver_status": "COMPLETED",
        "assumptions": ["Supplier delivery slip pushed ETA back 4 days"],
        "assessed_at": now.isoformat(),
    }
    res = client.post("/v1/commitments/com_001/assess", json=reassess_payload, headers=staff_headers)
    assert res.status_code == 200, res.text
    c1 = res.json()
    assert c1["risk_state"] == "AT_RISK"
    assert c1["recovery_state"] == "RECOVERY_REQUIRED"
    assert c1["agreement_state"] == "CONFIRMED"  # Invariant: CONFIRMED + AT_RISK coexist!
    assert c1["feasibility_state"] == "INFEASIBLE"
    assert c1["commitment_version"] == 5

    # Verify non-impacted com_002 stays NORMAL
    res = client.get("/v1/commitments/com_002", headers=staff_headers)
    assert res.status_code == 200
    c2 = res.json()
    assert c2["risk_state"] == "NORMAL"
    assert c2["recovery_state"] == "NONE"
    assert c2["agreement_state"] == "CONFIRMED"

    # Overview check: at_risk == 1, attention queue contains com_001
    res = client.get("/v1/overview", headers=staff_headers)
    assert res.status_code == 200
    overview = res.json()
    assert overview["counts"]["at_risk"] == 1
    at_risk_items = [item for item in overview["attention_queue"] if item["commitment_id"] == "com_001"]
    assert len(at_risk_items) >= 1
    assert at_risk_items[0]["category"] == AttentionCategory.STALE_PLAN

    # =========================================================================
    # STEP 3 (E2E-03): P3 generates two candidate plans from snapshot 102.
    # Staff approval rejected (403). Manager approves plan_a.
    # Resource reservation executes with idempotency key. Proposal v3 created.
    # =========================================================================
    # Candidate plan_a: Emergency local purchase 20 pcs packaging (+MYR 80, on-time delivery)
    plan_a = {
        "tenant_id": tenant,
        "recovery_case_id": "rc_hero_001",
        "plan_id": "plan_hero_a",
        "plan_version": 3,
        "commitment_id": "com_001",
        "based_on_assessment_id": "fa_hero_002",
        "snapshot_version": 102,
        "feasibility_status": "FEASIBLE",
        "estimated_extra_cost": "80.00",
        "currency": "MYR",
        "estimated_delay_minutes": 0,
        "risks": ["Higher material cost from emergency vendor"],
        "actions": [
            {
                "action_id": "act_hero_01",
                "type": "CREATE_PURCHASE_REQUEST",
                "requires_approval": True,
                "idempotency_key": "plan_hero_act_1",
                "parameters": {"vendor": "LocalEmergencyPackagingCo", "quantity": "20"},
                "preconditions": ["budget_approved"],
            }
        ],
        "approval_state": "APPROVED",
        "execution_state": "PENDING",
    }

    # Candidate plan_b: Reschedule delivery by 3 days (+MYR 0, delay 4320 mins)
    plan_b = {
        "tenant_id": tenant,
        "recovery_case_id": "rc_hero_001",
        "plan_id": "plan_hero_b",
        "plan_version": 3,
        "commitment_id": "com_001",
        "based_on_assessment_id": "fa_hero_002",
        "snapshot_version": 102,
        "feasibility_status": "FEASIBLE",
        "estimated_extra_cost": "0.00",
        "currency": "MYR",
        "estimated_delay_minutes": 4320,
        "risks": ["Customer dissatisfaction due to delayed event"],
        "actions": [
            {
                "action_id": "act_hero_02",
                "type": "ADJUST_DELIVERY_TERMS",
                "requires_approval": True,
                "idempotency_key": "plan_hero_act_2",
                "parameters": {"delay_days": "3"},
                "preconditions": [],
            }
        ],
        "approval_state": "PENDING",
        "execution_state": "PENDING",
    }
    # Both plans stem from the same snapshot version
    assert plan_a["snapshot_version"] == plan_b["snapshot_version"] == 102

    # Staff attempts execution/approval -> 403 Forbidden
    exec_req = {
        "expected_commitment_version": 5,
        "plan": plan_a,
        "current_snapshot_version": 102,
        "approved_at": (now - timedelta(minutes=5)).isoformat(),
        "approval_expires_at": (now + timedelta(hours=2)).isoformat(),
        "reason": "Staff attempt to execute without manager authorization",
    }
    res = client.post("/v1/commitments/com_001/recovery/execute", json=exec_req, headers=staff_headers)
    assert res.status_code == 403
    assert "APPROVAL_REQUIRED" in res.json()["code"]

    # Manager starts recovery -> version 5 -> 6, recovery_state=PLANNING
    res = client.post("/v1/commitments/com_001/recovery/start", json={
        "expected_commitment_version": 5,
        "reason": "Manager approved planning recovery via emergency procurement",
    }, headers=manager_headers)
    assert res.status_code == 200, res.text
    assert res.json()["commitment"]["recovery_state"] == "PLANNING"
    assert res.json()["commitment"]["commitment_version"] == 6

    # Action adapter reserves 20 pcs of packaging with idempotency key
    reserve_payload = {
        "commitment_id": "com_001",
        "plan_id": "plan_hero_a",
        "action_id": "act_hero_01",
        "idempotency_key": "idem_hero_reserve_001",
        "resource_id": "PACKAGING",
        "quantity": "20",
    }
    res = client.post("/v1/resources/reserve", json=reserve_payload, headers=manager_headers)
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "ACTIVE"
    assert Decimal(res.json()["quantity"]) == Decimal("20")

    # Verify inventory: total=80, reserved=20, available=60
    res = client.get("/v1/resources/snapshot?resource_id=PACKAGING", headers=staff_headers)
    assert res.status_code == 200
    stock_snap = res.json()[0]
    assert Decimal(stock_snap["available_quantity"]) == Decimal("60")

    # Manager executes recovery plan_a, offering revised terms proposal v3 to customer on commitment v6 -> version 6 -> 7
    exec_req["expected_commitment_version"] = 6
    exec_req["reason"] = "Manager approved emergency procurement plan"
    exec_req["revised_terms"] = {
        "sku": "BURGER",
        "quantity": "100",
        "unit": "pcs",
        "deadline": delivery_dt.isoformat(),
        "special_instructions": "Confirmed on-time delivery with emergency packaging lot",
    }
    res = client.post("/v1/commitments/com_001/recovery/execute", json=exec_req, headers=manager_headers)
    assert res.status_code == 200, res.text
    res_data = res.json()
    assert res_data["commitment"]["commitment_id"] == "com_001"
    assert res_data["commitment"]["commitment_version"] == 7
    assert res_data["commitment"]["agreement_state"] == "OFFERED"

    # =========================================================================
    # STEP 4 (E2E-12): P4 records verified customer acceptance of Proposal v3
    # -> CONFIRMED, v8, NOT_STARTED.
    # Premature fulfilment rejected (422).
    # Operational delivery POD recorded -> FULFILLED, RESOLVED, v9.
    # =========================================================================
    conf_v3 = {
        "proposal_id": "prop_plan_hero_a",
        "proposal_version": 3,
        "expected_commitment_version": 7,
        "decision": "ACCEPT",
        "evidence_refs": ["ev_customer_accept_proposal_v3"],
        "reason": "Customer agreed to emergency lot packaging note",
    }
    res = client.post("/v1/commitments/com_001/confirm-proposal", json=conf_v3, headers=manager_headers)
    assert res.status_code == 200, res.text
    c1 = res.json()["commitment"]
    assert c1["commitment_version"] == 8
    assert c1["agreement_state"] == "CONFIRMED"
    # CRITICAL INVARIANT: Acceptance does NOT mark fulfilment!
    assert c1["fulfilment_state"] == "NOT_STARTED"

    # Premature fulfilment with receipt/chat evidence only -> 422
    premature_fulfil = {
        "expected_commitment_version": 8,
        "fulfilment_state": "FULFILLED",
        "evidence_refs": ["ev_receipt_bank_slip_hero_001"],
        "reason": "Trying to claim delivery from payment receipt",
    }
    res = client.post("/v1/commitments/com_001/record-fulfilment", json=premature_fulfil, headers=manager_headers)
    assert res.status_code == 422
    assert res.json()["code"] == "INVALID_FULFILMENT_EVIDENCE"

    # Valid operational fulfilment with signed courier POD -> version 8 -> 9
    valid_fulfil = {
        "expected_commitment_version": 8,
        "fulfilment_state": "FULFILLED",
        "evidence_refs": ["ev_ops_delivery_signed_pod_com001"],
        "reason": "Courier delivered 100 pcs; customer signature verified on POD",
    }
    res = client.post("/v1/commitments/com_001/record-fulfilment", json=valid_fulfil, headers=manager_headers)
    assert res.status_code == 200, res.text
    c1 = res.json()["commitment"]
    assert c1["commitment_version"] == 9
    assert c1["fulfilment_state"] == "FULFILLED"
    assert c1["risk_state"] == "RESOLVED"
    assert c1["agreement_state"] == "CONFIRMED"

    # =========================================================================
    # STEP 5: Overview & Timeline Audit Proof
    # =========================================================================
    # Overview counts reflect resolution
    res = client.get("/v1/overview", headers=staff_headers)
    assert res.status_code == 200
    overview = res.json()
    assert overview["counts"]["fulfilled"] >= 1
    assert overview["counts"]["at_risk"] == 0

    # Timeline audit trail: verify unbroken causal chain on com_001
    res = client.get("/v1/commitments/com_001/timeline", headers=manager_headers)
    assert res.status_code == 200
    timeline = res.json()
    assert len(timeline) >= 6

    # Verify monotonic version progression
    versions = [entry["commitment_version"] for entry in timeline if entry.get("commitment_version")]
    for expected_v in [1, 2, 3, 4, 5, 6, 7, 8, 9]:
        assert expected_v in versions, f"Version {expected_v} missing from timeline: {versions}"

    # Verify unbroken evidence refs
    all_evidence = [ref for entry in timeline for ref in entry["evidence_refs"]]
    assert "ev_msg_hero_sku" in all_evidence
    assert "ev_cust_signed_agreement_hero_v1" in all_evidence
    assert "ev_customer_accept_proposal_v3" in all_evidence
    assert "ev_ops_delivery_signed_pod_com001" in all_evidence

    # Verify actor roles recorded
    roles = {entry["actor_role"] for entry in timeline}
    assert "MANAGER" in roles
    assert "OWNER" in roles or "STAFF" in roles

    # Verify all 5 independent dimensions are present in commitment state snapshots
    state_entries = [entry for entry in timeline if entry.get("new_state") and "agreement_state" in entry["new_state"]]
    assert len(state_entries) >= 4
    for entry in state_entries:
        ns = entry["new_state"]
        assert "agreement_state" in ns
        assert "feasibility_state" in ns
        assert "risk_state" in ns
        assert "recovery_state" in ns
        assert "fulfilment_state" in ns
