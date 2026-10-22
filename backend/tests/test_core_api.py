from __future__ import annotations

from fastapi.testclient import TestClient


def _headers(tenant: str = "tenant_test_01", actor: str = "user_manager_01") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Actor-ID": actor,
        "X-Correlation-ID": "corr_test_core_api",
    }


def _create_commitment(client: TestClient, headers: dict[str, str] | None = None) -> dict:
    h = headers or _headers()
    response = client.post(
        "/v1/commitments",
        headers=h,
        json={
            "order_id": "ord_core_001",
            "customer_id": "cust_core_001",
            "terms": {
                "sku": "BURGER_CORE",
                "quantity": "50",
                "unit": "pcs",
                "deadline": "2026-10-24T18:00:00+08:00",
            },
            "evidence_refs": ["ev_core_req_001"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_complete_9_endpoint_surface_and_patch_forbidden(client: TestClient) -> None:
    # 1. GET /health
    health_res = client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"
    assert health_res.json()["service"] == "moumantai-api"

    # Create a base commitment
    created = _create_commitment(client)
    com_id = created["commitment_id"]
    assert created["commitment_version"] == 1
    assert created["agreement_state"] == "REQUESTED"

    # 2. GET /v1/overview
    overview_res = client.get("/v1/overview", headers=_headers())
    assert overview_res.status_code == 200
    overview_data = overview_res.json()
    assert overview_data["tenant_id"] == "tenant_test_01"
    assert overview_data["counts"]["requested"] >= 1
    assert isinstance(overview_data["attention_queue"], list)
    assert isinstance(overview_data["commitments"], list)

    # 3. GET /v1/commitments/{commitment_id}
    get_res = client.get(f"/v1/commitments/{com_id}", headers=_headers())
    assert get_res.status_code == 200
    assert get_res.json()["commitment_id"] == com_id

    # 4. POST /v1/commitments/{commitment_id}/proposals
    proposal_res = client.post(
        f"/v1/commitments/{com_id}/proposals",
        headers=_headers(),
        json={
            "proposal_id": "prop_001",
            "proposal_version": 1,
            "expected_commitment_version": 1,
            "revised_terms": {
                "sku": "BURGER_CORE",
                "quantity": "60",
                "unit": "pcs",
                "deadline": "2026-10-24T20:00:00+08:00",
            },
            "reason": "Customer agreed to revised delivery window",
            "evidence_refs": ["ev_chat_001"],
        },
    )
    assert proposal_res.status_code == 200, proposal_res.text
    prop_body = proposal_res.json()
    assert prop_body["commitment"]["agreement_state"] == "OFFERED"
    assert prop_body["commitment"]["commitment_version"] == 2
    # D-015: Offering a proposal preserves existing terms until explicit acceptance
    assert prop_body["commitment"]["terms"]["quantity"] == "50"

    # 5. POST /v1/commitments/{commitment_id}/confirm-proposal
    confirm_res = client.post(
        f"/v1/commitments/{com_id}/confirm-proposal",
        headers=_headers(actor="user_manager_01"),
        json={
            "proposal_id": "prop_001",
            "proposal_version": 1,
            "expected_commitment_version": 2,
            "decision": "ACCEPT",
            "evidence_refs": ["ev_signed_confirm_001"],
            "reason": "Signed acceptance received from customer",
        },
    )
    assert confirm_res.status_code == 200, confirm_res.text
    confirm_body = confirm_res.json()
    assert confirm_body["commitment"]["agreement_state"] == "CONFIRMED"
    assert confirm_body["commitment"]["commitment_version"] == 3
    # D-015: Revised terms applied upon explicit customer acceptance
    assert confirm_body["commitment"]["terms"]["quantity"] == "60"
    assert confirm_body["domain_event"]["event_type"] == "commitment.confirmed"

    # 6. POST /v1/commitments/{commitment_id}/record-fulfilment
    fulfil_res = client.post(
        f"/v1/commitments/{com_id}/record-fulfilment",
        headers=_headers(actor="user_manager_01"),
        json={
            "expected_commitment_version": 3,
            "fulfilment_state": "FULFILLED",
            "evidence_refs": ["ev_pod_delivery_note_001"],
            "reason": "Delivery completed and signed by recipient",
        },
    )
    assert fulfil_res.status_code == 200, fulfil_res.text
    fulfil_body = fulfil_res.json()
    assert fulfil_body["commitment"]["fulfilment_state"] == "FULFILLED"
    assert fulfil_body["commitment"]["commitment_version"] == 4
    assert fulfil_body["domain_event"]["event_type"] == "commitment.fulfilment_verified"

    # 7. GET /v1/commitments/{commitment_id}/timeline
    timeline_res = client.get(f"/v1/commitments/{com_id}/timeline", headers=_headers())
    assert timeline_res.status_code == 200, timeline_res.text
    timeline = timeline_res.json()
    assert isinstance(timeline, list)
    assert len(timeline) >= 4  # created, proposal_offered, confirmed, fulfilment_verified

    # 8. GET /v1/audit?commitment_id=...
    audit_res = client.get(f"/v1/audit?commitment_id={com_id}", headers=_headers())
    assert audit_res.status_code == 200
    audit_list = audit_res.json()
    assert len(audit_list) >= 4

    # 9. GET /v1/events/{event_id}
    last_event_id = fulfil_body["domain_event"]["event_id"]
    event_res = client.get(f"/v1/events/{last_event_id}", headers=_headers())
    assert event_res.status_code == 200
    assert event_res.json()["event_id"] == last_event_id
    assert event_res.json()["commitment_id"] == com_id

    # Explicitly forbid unrestricted PATCH /v1/commitments/{id}
    patch_res = client.patch(
        f"/v1/commitments/{com_id}",
        headers=_headers(),
        json={"fulfilment_state": "FULFILLED"},
    )
    assert patch_res.status_code == 405, patch_res.text
    patch_err = patch_res.json()
    assert patch_err["code"] == "UNRESTRICTED_PATCH_FORBIDDEN"
    assert "Direct PATCH" in patch_err["message"]
    assert "correlation_id" in patch_err
    assert isinstance(patch_err["details"], dict)


def test_proposal_concurrency_and_cancellation_guards(client: TestClient) -> None:
    created = _create_commitment(client)
    com_id = created["commitment_id"]

    # Version mismatch returns 409 with current_commitment_version
    stale_proposal = client.post(
        f"/v1/commitments/{com_id}/proposals",
        headers=_headers(),
        json={
            "proposal_id": "prop_stale",
            "proposal_version": 1,
            "expected_commitment_version": 999,
            "reason": "Stale attempt",
        },
    )
    assert stale_proposal.status_code == 409
    stale_json = stale_proposal.json()
    assert stale_json["code"] == "COMMITMENT_VERSION_CONFLICT"
    assert stale_json["details"]["current_commitment_version"] == 1


def test_confirm_proposal_guards(client: TestClient) -> None:
    created = _create_commitment(client)
    com_id = created["commitment_id"]

    # Cannot confirm before OFFERED
    not_offered = client.post(
        f"/v1/commitments/{com_id}/confirm-proposal",
        headers=_headers(),
        json={
            "proposal_id": "prop_001",
            "proposal_version": 1,
            "expected_commitment_version": 1,
            "decision": "ACCEPT",
            "evidence_refs": ["ev_test"],
            "reason": "Premature confirm",
        },
    )
    assert not_offered.status_code == 409
    assert not_offered.json()["code"] == "INVALID_STATE_TRANSITION"

    # Make it OFFERED
    client.post(
        f"/v1/commitments/{com_id}/proposals",
        headers=_headers(),
        json={
            "proposal_id": "prop_offer_001",
            "expected_commitment_version": 1,
            "reason": "Offer sent",
        },
    )

    # Staff role cannot confirm proposal (403)
    staff_confirm = client.post(
        f"/v1/commitments/{com_id}/confirm-proposal",
        headers=_headers(actor="user_staff_01"),
        json={
            "proposal_id": "prop_offer_001",
            "proposal_version": 1,
            "expected_commitment_version": 2,
            "decision": "ACCEPT",
            "evidence_refs": ["ev_test"],
            "reason": "Staff attempt",
        },
    )
    assert staff_confirm.status_code == 403
    assert staff_confirm.json()["code"] == "APPROVAL_REQUIRED"

    # Missing evidence rejected (422)
    no_evidence = client.post(
        f"/v1/commitments/{com_id}/confirm-proposal",
        headers=_headers(actor="user_manager_01"),
        json={
            "proposal_id": "prop_offer_001",
            "proposal_version": 1,
            "expected_commitment_version": 2,
            "decision": "ACCEPT",
            "evidence_refs": [],
            "reason": "No evidence",
        },
    )
    assert no_evidence.status_code == 422


def test_record_fulfilment_invariants(client: TestClient) -> None:
    created = _create_commitment(client)
    com_id = created["commitment_id"]

    # Invariant: REQUESTED != CONFIRMED; cannot fulfil an unconfirmed commitment
    premature_fulfil = client.post(
        f"/v1/commitments/{com_id}/record-fulfilment",
        headers=_headers(actor="user_manager_01"),
        json={
            "expected_commitment_version": 1,
            "fulfilment_state": "FULFILLED",
            "evidence_refs": ["ev_mock_delivery"],
            "reason": "Premature delivery",
        },
    )
    assert premature_fulfil.status_code == 409
    assert premature_fulfil.json()["code"] == "INVALID_STATE_TRANSITION"
    assert "must be CONFIRMED" in premature_fulfil.json()["message"]


def test_normalized_error_shapes(client: TestClient) -> None:
    # 1. Missing headers -> 400
    res_400 = client.get("/v1/overview")
    assert res_400.status_code == 400
    err_400 = res_400.json()
    assert err_400["code"] == "AUTH_HEADERS_REQUIRED"
    assert "correlation_id" in err_400
    assert isinstance(err_400["details"], dict)

    # 2. Non-existent commitment -> 404
    res_404 = client.get("/v1/commitments/com_nonexistent_999", headers=_headers())
    assert res_404.status_code == 404
    err_404 = res_404.json()
    assert err_404["code"] == "COMMITMENT_NOT_FOUND"
    assert "correlation_id" in err_404
    assert isinstance(err_404["details"], dict)

    # 3. Validation error -> 422
    res_422 = client.post(
        "/v1/commitments",
        headers=_headers(),
        json={"order_id": "invalid_missing_terms"},
    )
    assert res_422.status_code == 422
    err_422 = res_422.json()
    assert err_422["code"] == "VALIDATION_ERROR"
    assert "errors" in err_422["details"]
    assert "correlation_id" in err_422
