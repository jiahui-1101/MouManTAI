from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_db
from app.main import app
from app.db.base import Base


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _headers(tenant: str = "tenant_a", actor: str = "user_manager_01") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Actor-ID": actor,
        "X-Correlation-ID": "corr_registry_test",
    }


def _create(client: TestClient) -> dict:
    response = client.post(
        "/v1/commitments",
        headers=_headers(),
        json={
            "order_id": "ord_001",
            "customer_id": "cust_001",
            "terms": {
                "sku": "BURGER",
                "quantity": "100",
                "unit": "pcs",
                "deadline": "2026-10-24T15:00:00+08:00",
            },
            "evidence_refs": ["ev_request_001"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_registry_enforces_transitions_version_and_audit(client: TestClient) -> None:
    created = _create(client)
    commitment_id = created["commitment_id"]
    assert created["agreement_state"] == "REQUESTED"
    assert created["commitment_version"] == 1

    invalid = client.post(
        f"/v1/commitments/{commitment_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "agreement",
            "target_state": "CONFIRMED",
            "expected_commitment_version": 1,
            "evidence_refs": ["ev_confirm_001"],
            "reason": "Attempted direct confirmation",
        },
    )
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "INVALID_STATE_TRANSITION"

    offered = client.post(
        f"/v1/commitments/{commitment_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "agreement",
            "target_state": "OFFERED",
            "expected_commitment_version": 1,
            "reason": "Proposal prepared",
        },
    )
    assert offered.status_code == 200
    assert offered.json()["commitment"]["commitment_version"] == 2

    confirmed = client.post(
        f"/v1/commitments/{commitment_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "agreement",
            "target_state": "CONFIRMED",
            "expected_commitment_version": 2,
            "evidence_refs": ["ev_confirm_001"],
            "reason": "Customer confirmation verified",
        },
    )
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body["commitment"]["agreement_state"] == "CONFIRMED"
    assert confirmed_body["commitment"]["commitment_version"] == 3
    assert confirmed_body["domain_event"]["event_type"] == "commitment.confirmed"

    stale = client.post(
        f"/v1/commitments/{commitment_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "risk",
            "target_state": "AT_RISK",
            "expected_commitment_version": 2,
            "reason": "Stale client update",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "COMMITMENT_VERSION_CONFLICT"
    assert stale.json()["details"]["current_commitment_version"] == 3

    audit = client.get(f"/v1/audit?commitment_id={commitment_id}", headers=_headers())
    assert audit.status_code == 200
    assert len(audit.json()) == 3

    event_id = confirmed_body["domain_event"]["event_id"]
    event = client.get(f"/v1/events/{event_id}", headers=_headers())
    assert event.status_code == 200
    assert event.json()["commitment_id"] == commitment_id


def test_registry_is_tenant_scoped(client: TestClient) -> None:
    created = _create(client)
    commitment_id = created["commitment_id"]

    response = client.get(
        f"/v1/commitments/{commitment_id}",
        headers=_headers(tenant="tenant_other"),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COMMITMENT_NOT_FOUND"
