"""Registered HTTP -> durable request workflow; fixtures are explicitly synthetic."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from test_terms import terms_data

from app.core.models import CommitmentRecord, OutboxEventRecord
from app.orders.models import MockOrderSourceRecord, OrderRequestAuditRecord, OrderRequestRecord
from app.orders.terms import OrderTerms

KEY = "synthetic-test-key-" + "q" * 32
HEADERS = {"X-Tenant-ID": "tenant_a", "X-Actor-ID": "manager_v22", "X-Isolated-E2E-Key": KEY}
BASE = "/v1/backend-v2/order-requests"


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", KEY)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", "manager_v22")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID", "tenant_a")


def seed_source(session):
    now = datetime.now(UTC)
    values = terms_data()
    values["evidence_refs"] = ["evidence_order", "evidence_disclosure"]
    values["price_source"]["disclosed_at"] = (now - timedelta(hours=1)).isoformat()
    values["window_start"] = (now + timedelta(days=1)).isoformat()
    values["window_end"] = (now + timedelta(days=1, hours=1)).isoformat()
    terms = OrderTerms.model_validate(values)
    session.add(MockOrderSourceRecord(
        tenant_id="tenant_a", source_id="source_a", customer_id="customer_a",
        source_version=1, terms=terms.model_dump(mode="json"),
        customer_request_ref="evidence_order", price_disclosure_ref="evidence_disclosure",
        observed_at=now - timedelta(hours=1), valid_through=now + timedelta(hours=1),
        status="CURRENT",
    ))
    session.commit()
    return terms


def import_command(client, **changes):
    return client.post(BASE + "/import-mock", headers=HEADERS,
                       json={"source_id": "source_a", "expected_source_version": 1} | changes)


def test_import_review_readback_audit_and_outbox(client, session, isolated):
    terms = seed_source(session)
    imported = import_command(client)
    assert imported.status_code == 201, imported.text
    value = imported.json()
    assert value["integration_mode"] == "MOCK"
    assert value["decision_status"] == "PENDING"
    assert value["terms_hash"] == terms.terms_hash
    assert value["terms"]["items"][0]["quantity"] == "100.00"
    assert value["request_version"] == 1
    assert client.get(BASE + "/order_a", headers=HEADERS).json() == value
    assert len(client.get(BASE, headers=HEADERS).json()) == 1
    reviewed = client.post(BASE + "/order_a/review", headers=HEADERS, json={
        "expected_request_version": 1, "decision": "REVIEWED", "reason": "Synthetic customer request reviewed",
    })
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["decision_status"] == "REVIEWED"
    assert reviewed.json()["request_version"] == 2
    session.expire_all()
    assert session.get(OrderRequestRecord, ("tenant_a", "order_a")).decision_status == "REVIEWED"
    assert session.scalar(select(func.count()).select_from(OrderRequestAuditRecord)) == 2
    assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 2
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0


def test_duplicate_import_and_review_do_not_repeat_events(client, session, isolated):
    seed_source(session)
    assert import_command(client).status_code == 201
    assert import_command(client).status_code == 201
    first = client.post(BASE + "/order_a/review", headers=HEADERS, json={
        "expected_request_version": 1, "decision": "REJECTED", "reason": "Synthetic refusal",
    })
    assert first.status_code == 200
    duplicate = client.post(BASE + "/order_a/review", headers=HEADERS, json={
        "expected_request_version": 1, "decision": "REJECTED", "reason": "Synthetic refusal",
    })
    assert duplicate.status_code == 409
    assert session.scalar(select(func.count()).select_from(OrderRequestAuditRecord)) == 2


def test_tenant_actor_and_production_boundary(client, session, isolated, monkeypatch):
    seed_source(session)
    assert import_command(client, source_id="unknown").status_code == 404
    assert client.post(BASE + "/import-mock", headers=HEADERS | {"X-Tenant-ID": "tenant_b"},
                       json={"source_id": "source_a", "expected_source_version": 1}).status_code == 403
    assert client.post(BASE + "/import-mock", headers=HEADERS | {"X-Actor-ID": "user_staff_01"},
                       json={"source_id": "source_a", "expected_source_version": 1}).status_code == 403
    assert client.post(BASE + "/import-mock", headers=HEADERS | {"X-Isolated-E2E-Key": "bad"},
                       json={"source_id": "source_a", "expected_source_version": 1}).status_code == 403
    assert import_command(client).status_code == 201
    assert client.get(BASE + "/order_a", headers=HEADERS | {"X-Tenant-ID": "tenant_b"}).status_code == 403
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(BASE, headers=HEADERS).status_code == 503
    assert import_command(client).status_code == 503


@pytest.mark.parametrize("version", [True, 1.5, "1", 0, -1])
def test_invalid_source_versions_rejected(client, session, isolated, version):
    seed_source(session)
    assert import_command(client, expected_source_version=version).status_code == 422
    assert session.scalar(select(func.count()).select_from(OrderRequestRecord)) == 0


def test_source_change_and_expiry_fail_closed(client, session, isolated):
    seed_source(session)
    assert import_command(client, expected_source_version=2).status_code == 409
    assert import_command(client).status_code == 201
    source = session.get(MockOrderSourceRecord, ("tenant_a", "source_a"))
    source.source_version = 2
    session.commit()
    response = client.post(BASE + "/order_a/review", headers=HEADERS, json={
        "expected_request_version": 1, "decision": "REVIEWED", "reason": "review",
    })
    assert response.status_code == 409
    assert response.json()["code"] == "STALE_SOURCE_VERSION"
    source.valid_through = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    assert import_command(client, expected_source_version=2).status_code == 409
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0
