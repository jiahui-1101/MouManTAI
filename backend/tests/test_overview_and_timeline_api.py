from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.models import CommitmentRecord, OutboxEventRecord


def _headers(tenant: str = "tenant_alpha", actor: str = "user_manager_01") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Actor-ID": actor,
        "X-Correlation-ID": "corr_overview_timeline_test",
    }


def _create(
    client: TestClient,
    sku: str = "BURGER_01",
    qty: str = "100",
    deadline: str = "2026-10-24T15:00:00+08:00",
    evidence: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    h = headers or _headers()
    res = client.post(
        "/v1/commitments",
        headers=h,
        json={
            "order_id": f"ord_{sku.lower()}",
            "customer_id": "cust_demo_01",
            "terms": {
                "sku": sku,
                "quantity": qty,
                "unit": "pcs",
                "deadline": deadline,
            },
            "evidence_refs": evidence or ["ev_init_req"],
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_overview_counts_and_attention_queue_match_db(client: TestClient) -> None:
    # 1. Commitment 1: Requested
    c1 = _create(client, sku="SKU_REQ")
    c1_id = c1["commitment_id"]

    # 2. Commitment 2: Confirmed + AtRisk
    c2 = _create(client, sku="SKU_AT_RISK")
    c2_id = c2["commitment_id"]
    # Transition to OFFERED then CONFIRMED
    client.post(
        f"/v1/commitments/{c2_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "agreement",
            "target_state": "OFFERED",
            "expected_commitment_version": 1,
            "reason": "Offering proposal",
        },
    )
    client.post(
        f"/v1/commitments/{c2_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "agreement",
            "target_state": "CONFIRMED",
            "expected_commitment_version": 2,
            "evidence_refs": ["ev_customer_signed_002"],
            "reason": "Customer agreed",
        },
    )
    # Mark AT_RISK
    client.post(
        f"/v1/commitments/{c2_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "risk",
            "target_state": "AT_RISK",
            "expected_commitment_version": 3,
            "evidence_refs": ["ev_supplier_delay_001"],
            "reason": "Supplier shipment delayed 48 hours",
        },
    )

    # 3. Commitment 3: Unknown Feasibility
    c3 = _create(client, sku="SKU_UNKNOWN_FEAS")
    c3_id = c3["commitment_id"]
    client.post(
        f"/v1/commitments/{c3_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "feasibility",
            "target_state": "UNKNOWN",
            "expected_commitment_version": 1,
            "evidence_refs": ["ev_solver_incomplete"],
            "reason": "Missing supplier calendar data",
        },
    )

    # 4. Commitment 4: Pending Approval (in recovery)
    c4 = _create(client, sku="SKU_PENDING_APPROVAL")
    c4_id = c4["commitment_id"]
    client.post(
        f"/v1/commitments/{c4_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "recovery",
            "target_state": "PLANNING",
            "expected_commitment_version": 1,
            "reason": "Evaluating alternative suppliers",
        },
    )
    client.post(
        f"/v1/commitments/{c4_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "recovery",
            "target_state": "PENDING_APPROVAL",
            "expected_commitment_version": 2,
            "evidence_refs": ["ev_plan_cost_quote"],
            "reason": "Plan proposed: expedite shipping at extra cost",
        },
    )

    # 5. Commitment 5: Fulfilled
    c5 = _create(client, sku="SKU_FULFILLED")
    c5_id = c5["commitment_id"]
    client.post(
        f"/v1/commitments/{c5_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "agreement",
            "target_state": "OFFERED",
            "expected_commitment_version": 1,
            "reason": "Offer initial terms",
        },
    )
    client.post(
        f"/v1/commitments/{c5_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "agreement",
            "target_state": "CONFIRMED",
            "expected_commitment_version": 2,
            "evidence_refs": ["ev_confirm_005"],
            "reason": "Confirmed by buyer",
        },
    )
    client.post(
        f"/v1/commitments/{c5_id}/record-fulfilment",
        headers=_headers(actor="user_manager_01"),
        json={
            "expected_commitment_version": 3,
            "fulfilment_state": "FULFILLED",
            "evidence_refs": ["ev_delivered_receipt_005"],
            "reason": "Courier delivery confirmation signed",
        },
    )

    # Query GET /v1/overview
    res = client.get("/v1/overview", headers=_headers())
    assert res.status_code == 200, res.text
    overview = res.json()
    counts = overview["counts"]

    # Verify counts match DB truth
    # c1 (requested=1)
    # c2 (confirmed=1, at_risk=1)
    # c3 (requested=1)
    # c4 (requested=1, pending_approval=1)
    # c5 (confirmed=1, fulfilled=1)
    assert counts["requested"] == 3  # c1, c3, c4
    assert counts["confirmed"] == 2  # c2, c5
    assert counts["at_risk"] == 1  # c2
    assert counts["pending_approval"] == 1  # c4
    assert counts["fulfilled"] == 1  # c5

    # Verify Attention Queue
    attention_queue = overview["attention_queue"]
    categories = [item["category"] for item in attention_queue]
    assert "UNKNOWN_FEASIBILITY" in categories
    assert "MANUAL_REVIEW" in categories

    # Verify attention items link to proper targets
    unknown_item = next(item for item in attention_queue if item["category"] == "UNKNOWN_FEASIBILITY")
    assert unknown_item["commitment_id"] == c3_id
    assert unknown_item["deep_link_path"] == f"/impact/{c3_id}"

    manual_review_items = [item for item in attention_queue if item["category"] == "MANUAL_REVIEW"]
    manual_ids = [item["commitment_id"] for item in manual_review_items]
    assert c4_id in manual_ids  # pending approval
    assert c2_id in manual_ids  # at risk


def test_timeline_correlation_and_feature_links(client: TestClient) -> None:
    # Run a multi-step journey with causation and correlation chains
    h_mgr = {
        "X-Tenant-ID": "tenant_timeline",
        "X-Actor-ID": "user_manager_01",
        "X-Correlation-ID": "corr_journey_root",
        "X-Causation-ID": "msg_f1_inbound_001",
    }

    # Step 1: Create request
    c = _create(client, sku="BURGER_HERO", evidence=["ctx_f1_001", "msg_001"], headers=h_mgr)
    com_id = c["commitment_id"]

    # Step 2: Feasibility assessment recorded
    client.post(
        f"/v1/commitments/{com_id}/transitions",
        headers={
            "X-Tenant-ID": "tenant_timeline",
            "X-Actor-ID": "user_manager_01",
            "X-Correlation-ID": "corr_journey_root",
            "X-Causation-ID": "asm_f2_atp_001",
        },
        json={
            "dimension": "feasibility",
            "target_state": "CONDITIONAL",
            "expected_commitment_version": 1,
            "evidence_refs": ["asm_f2_atp_001"],
            "reason": "Capacity allows 100 units if expedited",
        },
    )

    # Step 3: Offer recovery proposal (F3 recovery plan link)
    client.post(
        f"/v1/commitments/{com_id}/proposals",
        headers={
            "X-Tenant-ID": "tenant_timeline",
            "X-Actor-ID": "user_manager_01",
            "X-Correlation-ID": "corr_journey_root",
            "X-Causation-ID": "rec_f3_plan_001",
        },
        json={
            "proposal_id": "prop_revised_001",
            "proposal_version": 1,
            "expected_commitment_version": 2,
            "revised_terms": {
                "sku": "BURGER_HERO",
                "quantity": "100",
                "unit": "pcs",
                "deadline": "2026-10-24T19:00:00+08:00",
            },
            "evidence_refs": ["plan_f3_recovery_001"],
            "reason": "Recovery plan amended delivery window to 19:00",
        },
    )

    # Step 4: Confirm proposal (F4 customer communication link)
    client.post(
        f"/v1/commitments/{com_id}/confirm-proposal",
        headers={
            "X-Tenant-ID": "tenant_timeline",
            "X-Actor-ID": "user_manager_01",
            "X-Correlation-ID": "corr_journey_root",
            "X-Causation-ID": "comm_f4_msg_001",
        },
        json={
            "proposal_id": "prop_revised_001",
            "proposal_version": 1,
            "expected_commitment_version": 3,
            "decision": "ACCEPT",
            "evidence_refs": ["comm_f4_accept_token_001"],
            "reason": "Customer confirmed 19:00 deadline via WhatsApp",
        },
    )

    # Step 5: Fulfilment verified
    client.post(
        f"/v1/commitments/{com_id}/record-fulfilment",
        headers={
            "X-Tenant-ID": "tenant_timeline",
            "X-Actor-ID": "user_manager_01",
            "X-Correlation-ID": "corr_journey_root",
            "X-Causation-ID": "pod_dispatch_001",
        },
        json={
            "expected_commitment_version": 4,
            "fulfilment_state": "FULFILLED",
            "evidence_refs": ["ev_signed_delivery_note_001"],
            "reason": "Final delivery note signed by recipient",
        },
    )

    # Query GET /v1/commitments/{id}/timeline
    res = client.get(
        f"/v1/commitments/{com_id}/timeline",
        headers={"X-Tenant-ID": "tenant_timeline", "X-Actor-ID": "user_manager_01"},
    )
    assert res.status_code == 200, res.text
    timeline = res.json()
    assert len(timeline) >= 5

    # Check chronological ordering
    timestamps = [entry["occurred_at"] for entry in timeline]
    assert timestamps == sorted(timestamps)

    # Check correlation_id and causation_id propagation
    assert all(entry["correlation_id"] == "corr_journey_root" for entry in timeline)

    # Check entity pointers across F1, F2, F3, F4, CORE
    context_ptrs = [entry["context_id"] for entry in timeline if entry.get("context_id")]
    assessment_ptrs = [entry["assessment_id"] for entry in timeline if entry.get("assessment_id")]
    recovery_ptrs = [entry["recovery_case_id"] for entry in timeline if entry.get("recovery_case_id")]
    comm_ptrs = [entry["communication_id"] for entry in timeline if entry.get("communication_id")]
    prop_ptrs = [entry["proposal_id"] for entry in timeline if entry.get("proposal_id")]

    assert "ctx_f1_001" in context_ptrs
    assert "asm_f2_atp_001" in assessment_ptrs
    assert any("plan_f3_recovery_001" in p for p in recovery_ptrs)
    assert any("comm_f4_accept_token_001" in p for p in comm_ptrs)
    assert "prop_revised_001" in prop_ptrs


def test_audit_redaction_and_tenant_isolation(client: TestClient) -> None:
    # 1. Tenant Alpha creates a commitment with private notes and contact info
    h_alpha_mgr = {
        "X-Tenant-ID": "tenant_alpha_iso",
        "X-Actor-ID": "user_manager_01",
        "X-Correlation-ID": "corr_iso_alpha",
    }
    c_alpha = _create(client, sku="SKU_ALPHA", headers=h_alpha_mgr)
    c_alpha_id = c_alpha["commitment_id"]

    # Transition with private financial margin notes and customer email
    trans_res = client.post(
        f"/v1/commitments/{c_alpha_id}/transitions",
        headers=h_alpha_mgr,
        json={
            "dimension": "agreement",
            "target_state": "OFFERED",
            "expected_commitment_version": 1,
            "reason": "[CONFIDENTIAL] Manager approved financial margin of 28% for VIP client at test@example.com",
            "evidence_refs": ["ev_quote_alpha"],
        },
    )
    assert trans_res.status_code == 200

    # 2. Tenant Beta attempts to access Tenant Alpha's resources -> 404
    h_beta = {
        "X-Tenant-ID": "tenant_beta_iso",
        "X-Actor-ID": "user_manager_01",
        "X-Correlation-ID": "corr_iso_beta",
    }

    # GET commitment
    beta_get = client.get(f"/v1/commitments/{c_alpha_id}", headers=h_beta)
    assert beta_get.status_code == 404
    assert beta_get.json()["code"] == "COMMITMENT_NOT_FOUND"

    # GET timeline
    beta_timeline = client.get(f"/v1/commitments/{c_alpha_id}/timeline", headers=h_beta)
    assert beta_timeline.status_code == 404
    assert beta_timeline.json()["code"] == "COMMITMENT_NOT_FOUND"

    # GET audit
    beta_audit = client.get(f"/v1/audit?commitment_id={c_alpha_id}", headers=h_beta)
    assert beta_audit.status_code == 404
    assert beta_audit.json()["code"] == "COMMITMENT_NOT_FOUND"

    # POST proposal on cross-tenant
    beta_prop = client.post(
        f"/v1/commitments/{c_alpha_id}/proposals",
        headers=h_beta,
        json={"expected_commitment_version": 2, "reason": "Cross tenant hack"},
    )
    assert beta_prop.status_code == 404

    # GET overview for Beta shows 0 counts (isolated from Alpha)
    beta_overview = client.get("/v1/overview", headers=h_beta)
    assert beta_overview.status_code == 200
    assert beta_overview.json()["counts"]["requested"] == 0
    assert beta_overview.json()["counts"]["confirmed"] == 0

    # 3. Role-Based Redaction: Manager vs Staff in Tenant Alpha
    # Manager receives unredacted full reason
    mgr_audit_res = client.get(f"/v1/audit?commitment_id={c_alpha_id}", headers=h_alpha_mgr)
    assert mgr_audit_res.status_code == 200
    mgr_audit = mgr_audit_res.json()
    offered_audit_mgr = next(a for a in mgr_audit if a["event_type"] == "commitment.proposal_offered")
    assert "28%" in offered_audit_mgr["reason"]
    assert "test@example.com" in offered_audit_mgr["reason"]

    # Staff receives redacted reason
    h_alpha_staff = {
        "X-Tenant-ID": "tenant_alpha_iso",
        "X-Actor-ID": "user_staff_01",
        "X-Correlation-ID": "corr_staff_read",
    }
    staff_audit_res = client.get(f"/v1/audit?commitment_id={c_alpha_id}", headers=h_alpha_staff)
    assert staff_audit_res.status_code == 200
    staff_audit = staff_audit_res.json()
    offered_audit_staff = next(a for a in staff_audit if a["event_type"] == "commitment.proposal_offered")
    assert "test@example.com" not in offered_audit_staff["reason"]
    assert "[REDACTED" in offered_audit_staff["reason"]

    # Staff timeline is also redacted
    staff_tl_res = client.get(f"/v1/commitments/{c_alpha_id}/timeline", headers=h_alpha_staff)
    assert staff_tl_res.status_code == 200
    staff_tl = staff_tl_res.json()
    offered_tl_staff = next(e for e in staff_tl if e["event_type"] == "commitment.proposal_offered")
    assert "test@example.com" not in offered_tl_staff["approval_reason"]
    assert "[REDACTED" in offered_tl_staff["approval_reason"]


def test_unrestricted_patch_rejected(client: TestClient) -> None:
    created = _create(client)
    com_id = created["commitment_id"]

    res = client.patch(
        f"/v1/commitments/{com_id}",
        headers=_headers(),
        json={"fulfilment_state": "FULFILLED"},
    )
    assert res.status_code == 405
    body = res.json()
    assert body["code"] == "UNRESTRICTED_PATCH_FORBIDDEN"
    assert "Direct PATCH" in body["message"]
    assert "correlation_id" in body
