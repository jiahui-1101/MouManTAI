"""Registered API workflow against the persistent Mock Orbyte source."""

import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import httpx
import pytest
from mock_order_fixtures import mock_snapshot, mock_terms
from sqlalchemy import func, select

from app.core.models import AuditEventRecord, CommitmentRecord, OutboxEventRecord
from app.feasibility.persisted_sources import read_snapshot, stage_snapshot
from app.feasibility.production import EvaluationSnapshot
from app.orders.models import (
    MockOrbyteReservationRecord,
    MockOrbyteStateRecord,
    MockOrderSourceRecord,
)

KEY = "synthetic-test-key-" + "a" * 32
HEADERS = {"X-Tenant-ID": "tenant_001", "X-Actor-ID": "manager_v22", "X-Isolated-E2E-Key": KEY}
BASE = "/v1/backend-v2"


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", KEY)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", "manager_v22")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID", "tenant_001")


def seed(session, *, stock="150", request_id="order_test", quantity="10", state=True,
         next_outcome="NORMAL"):
    now = datetime.now(UTC)
    terms = mock_terms("tenant_001", request_id=request_id, quantity=quantity)
    session.add(MockOrderSourceRecord(
        tenant_id="tenant_001", source_id=f"source_{request_id}",
        customer_id=terms.customer_id, source_version=1,
        terms=terms.model_dump(mode="json"), customer_request_ref="evidence_order",
        price_disclosure_ref="evidence_disclosure",
        observed_at=now - timedelta(hours=1), valid_through=now + timedelta(hours=1),
        status="CURRENT",
    ))
    if state:
        snapshot = mock_snapshot(stock=stock)
        session.add(MockOrbyteStateRecord(
            tenant_id="tenant_001", snapshot_version=1,
            snapshot_payload=snapshot.model_dump(mode="json", exclude_computed_fields=True),
            next_outcome=next_outcome, updated_at=now,
        ))
    session.commit()
    return terms


def import_review(client, terms):
    imported = client.post(BASE + "/order-requests/import-mock", headers=HEADERS,
                           json={"source_id": f"source_{terms.order_request_id}",
                                 "expected_source_version": 1})
    assert imported.status_code == 201, imported.text
    reviewed = client.post(BASE + f"/order-requests/{terms.order_request_id}/review",
                           headers=HEADERS, json={"expected_request_version": 1,
                                                  "decision": "REVIEWED", "reason": "Reviewed synthetic request"})
    assert reviewed.status_code == 200, reviewed.text


def approve(client, terms, **changes):
    return client.post(BASE + f"/order-requests/{terms.order_request_id}/accept-mock",
                       headers=HEADERS, json={
                           "expected_request_version": 2,
                           "expected_terms_hash": terms.terms_hash,
                           "expected_snapshot_version": 1,
                           "idempotency_key": f"accept_{terms.order_request_id}",
                           "reason": "Explicit synthetic SME approval",
                       } | changes)


def seed_p2_operational_schedule(session, terms, *, schedule=True, stale=False):
    snapshot = mock_snapshot(tenant_id=terms.tenant_id)
    data = snapshot.model_dump(exclude_computed_fields=True)
    data["operational"]["snapshot_id"] = f"p2-order-source-{terms.order_request_id}"
    if schedule:
        data["production"]["plans"] = (*data["production"]["plans"], {
            "tenant_id": terms.tenant_id,
            "commitment_id": f"com_{terms.order_request_id}",
            "commitment_version": 1,
            "line_id": f"com_{terms.order_request_id}-line-1",
            "start_at": terms.window_start,
            "dispatch_cutoff_at": terms.window_end,
            "source_refs": ("production-plans",),
        })
    if stale:
        plan_source = next(source for source in data["production"]["sources"]
                           if source["source_id"] == "production-plans")
        plan_source["valid_through"] = plan_source["observed_at"]
    p2_snapshot = EvaluationSnapshot.model_validate(data)
    stage_snapshot(session, p2_snapshot, current=True)
    session.commit()
    return p2_snapshot


def test_http_order_review_p2_reservation_commitment_and_replay(client, session, isolated):
    terms = seed(session)
    import_review(client, terms)
    resource = client.get(BASE + "/mock-orbyte/resources", headers=HEADERS)
    assert resource.status_code == 200, resource.text
    assert resource.json()["snapshot"]["operational"]["snapshot_version"] == 1
    feasibility = client.get(BASE + "/order-requests/order_test/feasibility", headers=HEADERS)
    assert feasibility.status_code == 200, feasibility.text
    assert feasibility.json()["assessment"]["status"] == "FEASIBLE"
    assert feasibility.json()["request_version"] == 2
    accepted = approve(client, terms)
    assert accepted.status_code == 200, accepted.text
    data = accepted.json()
    assert data["order_request"]["decision_status"] == "ACCEPTED"
    assert data["commitment"]["agreement_state"] == "CONFIRMED"
    assert data["commitment"]["feasibility_state"] == "FEASIBLE"
    assert data["reservation"]["status"] == "CONFIRMED"
    assert data["operational_projection"]["status"] == "UNRESOLVED"
    assert data["operational_projection"]["reason_codes"] == ["P2_OPERATIONAL_SNAPSHOT_UNAVAILABLE"]
    assert data["reservation"]["mode"] == "MOCK"
    status = client.get(BASE + "/commitments/com_order_test/status-preview", headers=HEADERS)
    assert status.status_code == 200, status.text
    assert status.json()["customer_status"] == "ORDER_ACCEPTED"
    assert status.json()["acceptance_verified"] is True
    assert status.json()["integration_mode"] == "MOCK"
    operational = client.get(BASE + "/order-requests/order_test/operational-status", headers=HEADERS)
    assert operational.status_code == 200
    assert operational.json()["customer_status"] == "ORDER_ACCEPTED"
    assert operational.json()["actual_delivery"] == "NOT_AVAILABLE"
    timeline = client.get(BASE + "/order-requests/order_test/timeline", headers=HEADERS)
    assert timeline.status_code == 200
    assert {event["event_type"] for event in timeline.json()} >= {
        "order.request_imported", "order.request_reviewed",
        "order.request_accepted", "commitment.mock_order_accepted",
    }
    operation = data["reservation"]["operation_id"]
    assert client.get(BASE + f"/mock-orbyte/reservations/{operation}", headers=HEADERS).json() == data["reservation"]
    assert client.get(BASE + "/mock-orbyte/resources", headers=HEADERS).json()["snapshot"]["operational"]["snapshot_version"] == 2
    assert approve(client, terms).json()["reservation"]["operation_id"] == operation
    assert approve(client, terms, expected_snapshot_version=2).status_code == 409
    session.expire_all()
    assert session.get(CommitmentRecord, ("tenant_001", "com_order_test")) is not None
    assert session.scalar(select(func.count()).select_from(MockOrbyteReservationRecord)) == 1
    assert session.scalar(select(func.count()).select_from(AuditEventRecord).where(
        AuditEventRecord.event_type == "commitment.mock_order_accepted")) == 1
    assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 4


def test_acceptance_projects_only_from_exact_current_p2_schedule(client, session, isolated):
    terms = seed(session, request_id="order_projected")
    p2_before = seed_p2_operational_schedule(session, terms)
    import_review(client, terms)

    accepted = approve(client, terms)
    assert accepted.status_code == 200, accepted.text
    projection = accepted.json()["operational_projection"]
    assert projection["status"] == "PROJECTED"
    assert projection["acceptance_event_id"]
    assert projection["snapshot_version"] == 2

    p2_current = read_snapshot(session, terms.tenant_id)
    projected = next(row for row in p2_current.operational.confirmed_commitments
                     if row.commitment_id == f"com_{terms.order_request_id}")
    assert projected.commitment_version == accepted.json()["commitment"]["commitment_version"]
    assert projected.delivery_deadline == terms.window_end
    assert projected.lines[0].line_id == f"com_{terms.order_request_id}-line-1"
    assert projected.lines[0].material_use_at == terms.window_start
    assert p2_current.operational.snapshot_version == p2_before.operational.snapshot_version + 1

    replay = approve(client, terms)
    assert replay.status_code == 200, replay.text
    assert replay.json()["operational_projection"]["status"] == "ALREADY_PROJECTED"
    assert read_snapshot(session, terms.tenant_id).operational.snapshot_version == 2


@pytest.mark.parametrize(
    ("schedule", "stale", "reason"),
    [(False, False, "P2_SCHEDULE_MISSING"), (True, True, "P2_SCHEDULE_STALE_OR_INVALID")],
)
def test_acceptance_stays_unresolved_without_fresh_p2_schedule(
    client, session, isolated, schedule, stale, reason,
):
    terms = seed(session, request_id=f"order_unresolved_{reason.lower()}")
    before = seed_p2_operational_schedule(session, terms, schedule=schedule, stale=stale)
    import_review(client, terms)

    accepted = approve(client, terms)
    assert accepted.status_code == 200, accepted.text
    projection = accepted.json()["operational_projection"]
    assert projection["status"] == "UNRESOLVED"
    assert reason in projection["reason_codes"]
    assert projection["snapshot_version"] is None

    current = read_snapshot(session, terms.tenant_id)
    assert current.operational.snapshot_version == before.operational.snapshot_version
    assert all(row.commitment_id != f"com_{terms.order_request_id}"
               for row in current.operational.confirmed_commitments)


def test_registered_mock_inquiry_to_accepted_commitment(client, session, isolated):
    now = datetime.now(UTC)
    terms = mock_terms("tenant_001", request_id="order_inquiry")
    resources = client.post(BASE + "/mock-orbyte/resources", headers=HEADERS,
                            json={"stock_quantity": "150"})
    assert resources.status_code == 201, resources.text
    assert resources.json()["integration_mode"] == "MOCK"
    assert client.post(BASE + "/mock-orbyte/resources", headers=HEADERS,
                       json={"stock_quantity": "150"}).status_code == 409
    inquiry = client.post(BASE + "/mock-orbyte/inquiries", headers=HEADERS, json={
        "source_id": "source_order_inquiry", "source_version": 1,
        "terms": terms.model_dump(mode="json"),
        "customer_request_ref": "evidence_order",
        "price_disclosure_ref": "evidence_disclosure",
        "observed_at": (now - timedelta(minutes=1)).isoformat(),
        "valid_through": (now + timedelta(hours=1)).isoformat(),
    })
    assert inquiry.status_code == 201, inquiry.text
    assert inquiry.json()["integration_mode"] == "MOCK"
    import_review(client, terms)
    accepted = approve(client, terms)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["commitment"]["agreement_state"] == "CONFIRMED"


def test_registered_mock_contract_and_identity_boundary(client, isolated, monkeypatch):
    spec = client.get("/openapi.json").json()
    for path, methods in {
        "/v1/backend-v2/mock-orbyte/resources": {"get", "post"},
        "/v1/backend-v2/mock-orbyte/inquiries": {"post"},
        "/v1/backend-v2/order-requests/import-mock": {"post"},
        "/v1/backend-v2/order-requests/{order_request_id}/review": {"post"},
        "/v1/backend-v2/order-requests/{order_request_id}/feasibility": {"get"},
        "/v1/backend-v2/order-requests/{order_request_id}/accept-mock": {"post"},
        "/v1/backend-v2/order-requests/{order_request_id}/reconcile-mock": {"post"},
        "/v1/backend-v2/order-requests/{order_request_id}/operational-status": {"get"},
    }.items():
        assert methods <= set(spec["paths"][path])
    assert client.post(BASE + "/mock-orbyte/resources", headers=HEADERS | {
        "X-Actor-ID": "untrusted_other"}, json={"stock_quantity": "150"}).status_code == 403
    assert client.post(BASE + "/mock-orbyte/resources", headers=HEADERS,
                       json={"stock_quantity": 150.5}).status_code == 422
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID")
    assert client.post(BASE + "/mock-orbyte/resources", headers=HEADERS,
                       json={"stock_quantity": "150"}).status_code == 503


def test_live_http_postgresql_inquiry_to_accepted_commitment(
    test_engine, tmp_path, isolated,
):
    if test_engine.dialect.name != "postgresql":
        pytest.skip("Live socket integration requires migrated PostgreSQL")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    log_path = tmp_path / "mock-order-uvicorn.log"
    server_env = dict(os.environ, DATABASE_URL=os.environ["TEST_DATABASE_URL"],
                      MOUMANTAI_ISOLATED_E2E_TENANT_ID="tenant_socket_order")
    with log_path.open("wb") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", str(port)], cwd=os.getcwd(), env=server_env,
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=8) as http:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if http.get("/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(0.2)
            else:
                pytest.fail(log_path.read_text(errors="replace")[-3000:])
            tenant = "tenant_socket_order"
            headers = HEADERS | {"X-Tenant-ID": tenant}
            terms = mock_terms(tenant, request_id="socket_order")
            now = datetime.now(UTC)
            resources = http.post(BASE + "/mock-orbyte/resources", headers=headers,
                                  json={"stock_quantity": "150"})
            assert resources.status_code == 201, resources.text
            inquiry = http.post(BASE + "/mock-orbyte/inquiries", headers=headers, json={
                "source_id": "socket_inquiry", "source_version": 1,
                "terms": terms.model_dump(mode="json"),
                "customer_request_ref": "evidence_order",
                "price_disclosure_ref": "evidence_disclosure",
                "observed_at": (now - timedelta(minutes=1)).isoformat(),
                "valid_through": (now + timedelta(hours=1)).isoformat(),
            })
            assert inquiry.status_code == 201, inquiry.text
            imported = http.post(BASE + "/order-requests/import-mock", headers=headers,
                                 json={"source_id": "socket_inquiry", "expected_source_version": 1})
            assert imported.status_code == 201, imported.text
            reviewed = http.post(BASE + "/order-requests/socket_order/review", headers=headers,
                                 json={"expected_request_version": 1, "decision": "REVIEWED",
                                       "reason": "SME reviewed synthetic request"})
            assert reviewed.status_code == 200, reviewed.text
            feasibility = http.get(BASE + "/order-requests/socket_order/feasibility", headers=headers)
            assert feasibility.status_code == 200, feasibility.text
            assert feasibility.json()["assessment"]["status"] == "FEASIBLE"
            accepted = http.post(BASE + "/order-requests/socket_order/accept-mock", headers=headers,
                                 json={"expected_request_version": 2,
                                       "expected_terms_hash": terms.terms_hash,
                                       "expected_snapshot_version": 1,
                                       "idempotency_key": "socket_accept_123",
                                       "reason": "SME approves synthetic commitment"})
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["reservation"]["status"] == "CONFIRMED"
            assert accepted.json()["commitment"]["agreement_state"] == "CONFIRMED"
            status = http.get(BASE + "/order-requests/socket_order/operational-status", headers=headers)
            assert status.status_code == 200, status.text
            assert status.json()["customer_status"] == "ORDER_ACCEPTED"
            assert status.json()["actual_delivery"] == "NOT_AVAILABLE"
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def test_insufficient_stock_never_accepts_or_reserves(client, session, isolated):
    terms = seed(session, stock="100")
    import_review(client, terms)
    feasibility = client.get(BASE + "/order-requests/order_test/feasibility", headers=HEADERS)
    assert feasibility.status_code == 200
    assert feasibility.json()["assessment"]["status"] in {"INFEASIBLE", "UNKNOWN"}
    response = approve(client, terms)
    assert response.status_code == 409
    assert response.json()["code"] == "P2_NOT_FEASIBLE"
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0
    assert session.scalar(select(func.count()).select_from(MockOrbyteReservationRecord)) == 0


@pytest.mark.parametrize("version", [True, 1.5, "1", 0])
def test_malformed_decision_versions_rejected(client, session, isolated, version):
    terms = seed(session)
    import_review(client, terms)
    assert approve(client, terms, expected_request_version=version).status_code == 422
    assert approve(client, terms, expected_snapshot_version=version).status_code == 422
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0


def test_stale_terms_tenant_and_actor_rejected(client, session, isolated):
    terms = seed(session)
    import_review(client, terms)
    assert approve(client, terms, expected_terms_hash="order-terms-v1:" + "0" * 64).status_code == 409
    assert approve(client, terms, expected_snapshot_version=2).status_code == 409
    assert client.post(BASE + "/order-requests/order_test/accept-mock",
                       headers=HEADERS | {"X-Tenant-ID": "tenant_b"}, json={
                           "expected_request_version": 2, "expected_terms_hash": terms.terms_hash,
                           "expected_snapshot_version": 1, "idempotency_key": "accept_other",
                           "reason": "attempt",
                       }).status_code == 403
    assert client.post(BASE + "/order-requests/order_test/accept-mock",
                       headers=HEADERS | {"X-Actor-ID": "user_staff_01"}, json={
                           "expected_request_version": 2, "expected_terms_hash": terms.terms_hash,
                           "expected_snapshot_version": 1, "idempotency_key": "accept_other",
                           "reason": "attempt",
                       }).status_code == 403
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0


def test_unknown_outcome_reconciles_before_new_approval(client, session, isolated):
    terms = seed(session, next_outcome="UNKNOWN")
    import_review(client, terms)
    unknown = approve(client, terms)
    assert unknown.status_code == 202, unknown.text
    data = unknown.json()
    assert data["reservation"]["status"] == "UNKNOWN"
    assert data["order_request"]["decision_status"] == "RESERVATION_UNKNOWN"
    assert data["commitment"] is None
    assert approve(client, terms).json()["reservation"]["operation_id"] == data["reservation"]["operation_id"]
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0
    operation_id = data["reservation"]["operation_id"]
    reconciled = client.post(BASE + "/order-requests/order_test/reconcile-mock", headers=HEADERS,
                             json={"operation_id": operation_id})
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["reservation"]["status"] == "FAILED"
    assert reconciled.json()["order_request"]["decision_status"] == "REVIEWED"
    assert client.get(BASE + f"/mock-orbyte/reservations/{operation_id}",
                      headers=HEADERS).json()["status"] == "FAILED"
    accepted = approve(client, terms, expected_request_version=4, idempotency_key="accept_retry_123")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["reservation"]["status"] == "CONFIRMED"
    assert approve(client, terms).status_code == 409


def test_mock_reservation_rejection_leaves_order_reviewed(client, session, isolated):
    terms = seed(session, next_outcome="REJECT")
    import_review(client, terms)
    rejected = approve(client, terms)
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "MOCK_RESERVATION_REJECTED"
    operation = rejected.json()["details"]["operation_id"]
    assert client.get(BASE + f"/mock-orbyte/reservations/{operation}",
                      headers=HEADERS).json()["status"] == "FAILED"
    assert approve(client, terms).json()["details"]["operation_id"] == operation
    assert client.get(BASE + "/order-requests/order_test", headers=HEADERS).json()["decision_status"] == "REVIEWED"
    assert session.scalar(select(func.count()).select_from(MockOrbyteReservationRecord)) == 1
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0
    assert approve(client, terms, idempotency_key="accept_reject_retry").status_code == 200


def test_postgres_concurrent_orders_cannot_overallocate(client, session, test_engine, isolated):
    if test_engine.dialect.name != "postgresql":
        pytest.skip("Row-lock contention requires PostgreSQL")
    first = seed(session, stock="115", request_id="order_one")
    second = seed(session, state=False, request_id="order_two")
    import_review(client, first)
    import_review(client, second)
    barrier = Barrier(2)

    def submit(terms):
        barrier.wait(timeout=5)
        return approve(client, terms)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(submit, first)
        two = pool.submit(submit, second)
        responses = [one.result(timeout=20), two.result(timeout=20)]
    assert sorted(response.status_code for response in responses) == [200, 409], [r.text for r in responses]
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(MockOrbyteReservationRecord).where(
        MockOrbyteReservationRecord.status == "CONFIRMED")) == 1
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 1
    state = session.get(MockOrbyteStateRecord, "tenant_001")
    assert state.snapshot_version == 2


def test_postgres_concurrent_duplicate_approval_replays_one_receipt(client, session, test_engine, isolated):
    if test_engine.dialect.name != "postgresql":
        pytest.skip("Concurrent duplicate command requires PostgreSQL")
    terms = seed(session)
    import_review(client, terms)
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=5)
        return approve(client, terms)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(submit)
        two = pool.submit(submit)
        responses = [one.result(timeout=20), two.result(timeout=20)]
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert responses[0].json()["reservation"]["operation_id"] == responses[1].json()["reservation"]["operation_id"]
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(MockOrbyteReservationRecord)) == 1
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 1
