from collections.abc import Generator

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.errors import DomainError
from app.core.router import router as core_router
from app.core.schemas import FeasibilityAssessment
from app.db.base import Base
from app.feasibility.api_dependencies import (
    get_assessment_history,
    get_assessment_writer,
    get_evaluation_input_authority,
    get_impact_reader,
    get_internal_request_context,
    get_supplier_delay_processor,
)
from app.feasibility.production_fixtures import build_production_example
from app.feasibility.router import router as feasibility_router


class FixtureEvaluationAuthority:
    def __init__(self, *, version_offset: int = 0) -> None:
        self.calls = 0
        self.version_offset = version_offset

    def resolve(self, context, request):
        self.calls += 1
        snapshot = request.snapshot
        if self.version_offset:
            data = snapshot.model_dump(exclude_computed_fields=True)
            data["operational"]["snapshot_version"] += self.version_offset
            snapshot = type(snapshot).model_validate(data)
        return snapshot, request.commitment


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app = FastAPI()
    app.include_router(core_router)
    app.include_router(feasibility_router)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "correlation_id": exc.correlation_id or "corr_test",
                "details": exc.details,
            },
        )

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    context = RequestContext(
        tenant_id="tenant-synthetic-p2",
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_p2_router_test",
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_request_context] = lambda: context
    app.dependency_overrides[get_internal_request_context] = lambda: context
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _create_confirmed_commitment(client: TestClient) -> dict:
    created = client.post(
        "/v1/commitments",
        json={
            "order_id": "ord_api_001",
            "customer_id": "cust_api_001",
            "terms": {
                "sku": "BURGER",
                "quantity": "100",
                "unit": "pcs",
                "deadline": "2026-10-24T15:00:00+08:00",
            },
            "evidence_refs": ["ev_request_api_001"],
        },
    )
    assert created.status_code == 201, created.text
    commitment_id = created.json()["commitment_id"]
    offered = client.post(
        f"/v1/commitments/{commitment_id}/transitions",
        json={
            "dimension": "agreement",
            "target_state": "OFFERED",
            "expected_commitment_version": 1,
            "reason": "Prepare synthetic API fixture",
        },
    )
    assert offered.status_code == 200, offered.text
    confirmed = client.post(
        f"/v1/commitments/{commitment_id}/transitions",
        json={
            "dimension": "agreement",
            "target_state": "CONFIRMED",
            "expected_commitment_version": 2,
            "evidence_refs": ["ev_confirm_api_001"],
            "reason": "Synthetic confirmation evidence",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["commitment"]


def _evaluation_payload() -> dict:
    snapshot, commitment = build_production_example()
    return {
        "snapshot": snapshot.model_dump(mode="json", exclude_computed_fields=True),
        "commitment": commitment.model_dump(mode="json"),
        "proposed_changes": None,
    }


def _assessment_inputs(core_commitment: dict) -> tuple:
    snapshot, fixture_commitment = build_production_example()
    confirmed_commitments = tuple(
        row.model_copy(
            update={
                "commitment_id": core_commitment["commitment_id"],
                "commitment_version": core_commitment["commitment_version"],
            }
        )
        if row.commitment_id == fixture_commitment.commitment_id
        else row
        for row in snapshot.operational.confirmed_commitments
    )
    operational = snapshot.operational.model_copy(
        update={"confirmed_commitments": confirmed_commitments}
    )
    snapshot = snapshot.model_copy(
        update={
            "operational": operational,
            "current_snapshot_version": snapshot.operational.snapshot_version,
        }
    )
    commitment = fixture_commitment.model_copy(
        update={
            "commitment_id": core_commitment["commitment_id"],
            "commitment_version": core_commitment["commitment_version"],
        }
    )
    return snapshot, commitment


def test_internal_evaluate_reuses_pure_engine_and_preserves_unknown_metadata(
    api_client: TestClient,
) -> None:
    payload = _evaluation_payload()
    authority = FixtureEvaluationAuthority()
    api_client.app.dependency_overrides[get_evaluation_input_authority] = lambda: authority

    response = api_client.post("/internal/feasibility/evaluate", json=payload)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["tenant_id"] == payload["commitment"]["tenant_id"]
    assert result["commitment_version"] == payload["commitment"]["commitment_version"]
    assert result["snapshot_version"] == payload["snapshot"]["operational"]["snapshot_version"]
    assert result["status"] == "FEASIBLE"
    assert result["solver_status"] == "COMPLETED"
    assert result["shared_output_blocker"] == "P5_AFFECTED_COMMITMENT_IDS_EMPTY_SCHEMA_SUPPORT"
    assert "affected_commitment_ids" not in result
    assert authority.calls == 1


def test_internal_evaluate_rejects_cross_tenant_before_authority_or_solver(
    api_client: TestClient,
) -> None:
    payload = _evaluation_payload()
    authority = FixtureEvaluationAuthority()
    api_client.app.dependency_overrides[get_evaluation_input_authority] = lambda: authority
    api_client.app.dependency_overrides[get_internal_request_context] = lambda: RequestContext(
        tenant_id="tenant-other",
        actor_id="internal-test",
        actor_role="SERVICE",
        correlation_id="corr_cross_tenant",
    )

    response = api_client.post("/internal/feasibility/evaluate", json=payload)

    assert response.status_code == 403
    assert response.json()["code"] == "TENANT_SCOPE_MISMATCH"
    assert authority.calls == 0


def test_internal_evaluate_is_blocked_without_p5_internal_authorization(
    api_client: TestClient,
) -> None:
    payload = _evaluation_payload()
    api_client.app.dependency_overrides.pop(get_internal_request_context)

    response = api_client.post("/internal/feasibility/evaluate", json=payload)

    assert response.status_code == 503
    assert response.json()["code"] == "P2_INTERNAL_AUTH_NOT_CONFIGURED"


def test_internal_evaluate_rejects_authority_version_mismatch(api_client: TestClient) -> None:
    payload = _evaluation_payload()
    authority = FixtureEvaluationAuthority(version_offset=1)
    api_client.app.dependency_overrides[get_evaluation_input_authority] = lambda: authority

    response = api_client.post("/internal/feasibility/evaluate", json=payload)

    assert response.status_code == 409
    assert response.json()["code"] == "EVALUATION_INPUT_VERSION_CONFLICT"
    assert authority.calls == 1


def test_internal_evaluate_preserves_stale_unknown_and_evidence(api_client: TestClient) -> None:
    payload = _evaluation_payload()
    payload["snapshot"]["current_snapshot_version"] = (
        payload["snapshot"]["operational"]["snapshot_version"] + 1
    )
    api_client.app.dependency_overrides[get_evaluation_input_authority] = lambda: FixtureEvaluationAuthority()

    response = api_client.post("/internal/feasibility/evaluate", json=payload)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "UNKNOWN"
    assert result["solver_status"] == "STALE"
    assert result["snapshot_id"] == payload["snapshot"]["operational"]["snapshot_id"]
    assert result["snapshot_version"] == payload["snapshot"]["operational"]["snapshot_version"]
    assert "STALE_SNAPSHOT_VERSION" in {item["code"] for item in result["constraints"]}
    assert result["evidence_refs"]


def test_internal_hypothetical_evaluation_uses_same_engine_without_mutation(
    api_client: TestClient,
) -> None:
    from app.feasibility.production import ProposedChanges
    from app.feasibility.service import evaluate

    snapshot, commitment = build_production_example()
    proposal = ProposedChanges(
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        expected_commitment_version=commitment.commitment_version,
        expected_snapshot_version=snapshot.operational.snapshot_version,
        quantity="60",
        evidence_refs=("synthetic-p3-partial-delivery-proposal",),
    )
    before_snapshot = snapshot.model_dump_json(exclude_computed_fields=True)
    before_commitment = commitment.model_dump_json()
    payload = {
        "snapshot": snapshot.model_dump(mode="json", exclude_computed_fields=True),
        "commitment": commitment.model_dump(mode="json"),
        "proposed_changes": proposal.model_dump(mode="json"),
    }
    api_client.app.dependency_overrides[get_evaluation_input_authority] = lambda: FixtureEvaluationAuthority()

    response = api_client.post("/internal/feasibility/evaluate", json=payload)
    expected = evaluate(snapshot, proposal, commitment)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected.status.value == "CONDITIONAL"
    assert response.json()["constraints"] == [
        item.model_dump(mode="json") for item in expected.constraints
    ]
    assert response.json()["snapshot_version"] == expected.snapshot_version
    assert snapshot.model_dump_json(exclude_computed_fields=True) == before_snapshot
    assert commitment.model_dump_json() == before_commitment


def test_assess_checks_core_tenant_and_version_then_reports_missing_persistence(
    api_client: TestClient,
) -> None:
    commitment = _create_confirmed_commitment(api_client)
    stale = api_client.post(
        f"/v1/commitments/{commitment['commitment_id']}/assess",
        json={"expected_commitment_version": commitment["commitment_version"] - 1},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "COMMITMENT_VERSION_CONFLICT"
    assert stale.json()["details"]["current_commitment_version"] == commitment["commitment_version"]

    current = api_client.post(
        f"/v1/commitments/{commitment['commitment_id']}/assess",
        json={"expected_commitment_version": commitment["commitment_version"]},
    )
    assert current.status_code == 503
    assert current.json()["code"] == "P2_ASSESSMENT_PERSISTENCE_NOT_CONFIGURED"


def test_assess_passes_authoritative_p2_result_to_writer_without_claiming_persistence(
    api_client: TestClient,
) -> None:
    from app.feasibility.service import evaluate

    core_commitment = _create_confirmed_commitment(api_client)
    snapshot, authoritative_commitment = _assessment_inputs(core_commitment)
    expected = evaluate(snapshot, None, authoritative_commitment)

    class AssessmentAuthority:
        def resolve_current(self, context, commitment_id, expected_commitment_version):
            assert commitment_id == core_commitment["commitment_id"]
            assert expected_commitment_version == core_commitment["commitment_version"]
            return snapshot, authoritative_commitment

    class UnavailableWriter:
        def assess(self, db, context, commitment, request, *, snapshot=None, result=None):
            assert snapshot is not None
            assert snapshot.operational.snapshot_id == expected.snapshot_id
            assert result is not None
            assert result.model_dump(mode="json") == expected.model_dump(mode="json")
            raise DomainError(
                "P2_TEST_WRITER_UNAVAILABLE",
                "Test writer did not commit an assessment",
                status_code=503,
                correlation_id=context.correlation_id,
            )

    api_client.app.dependency_overrides[get_evaluation_input_authority] = (
        lambda: AssessmentAuthority()
    )
    api_client.app.dependency_overrides[get_assessment_writer] = lambda: UnavailableWriter()

    response = api_client.post(
        f"/v1/commitments/{core_commitment['commitment_id']}/assess",
        json={"expected_commitment_version": core_commitment["commitment_version"]},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "P2_TEST_WRITER_UNAVAILABLE"


@pytest.mark.parametrize(
    ("current_snapshot_version", "expected_status", "expected_code"),
    [
        (None, 503, "P2_CURRENT_SNAPSHOT_VERSION_UNAVAILABLE"),
        (2, 409, "SNAPSHOT_VERSION_CONFLICT"),
    ],
)
def test_assess_rejects_unavailable_or_stale_current_snapshot_version(
    api_client: TestClient,
    current_snapshot_version: int | None,
    expected_status: int,
    expected_code: str,
) -> None:
    core_commitment = _create_confirmed_commitment(api_client)
    snapshot, authoritative_commitment = _assessment_inputs(core_commitment)
    snapshot = snapshot.model_copy(
        update={"current_snapshot_version": current_snapshot_version}
    )

    class AssessmentAuthority:
        def resolve_current(self, context, commitment_id, expected_commitment_version):
            return snapshot, authoritative_commitment

    class UnusedWriter:
        def assess(self, *args, **kwargs):
            pytest.fail("writer must not receive input with no current snapshot version")

    api_client.app.dependency_overrides[get_evaluation_input_authority] = (
        lambda: AssessmentAuthority()
    )
    api_client.app.dependency_overrides[get_assessment_writer] = lambda: UnusedWriter()

    response = api_client.post(
        f"/v1/commitments/{core_commitment['commitment_id']}/assess",
        json={"expected_commitment_version": core_commitment["commitment_version"]},
    )

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code


def test_assess_rejects_body_tenant_authority_and_malformed_version(api_client: TestClient) -> None:
    commitment = _create_confirmed_commitment(api_client)
    with_client_tenant = api_client.post(
        f"/v1/commitments/{commitment['commitment_id']}/assess",
        json={
            "expected_commitment_version": commitment["commitment_version"],
            "tenant_id": "tenant-other",
        },
    )
    assert with_client_tenant.status_code == 422

    malformed = api_client.post(
        f"/v1/commitments/{commitment['commitment_id']}/assess",
        json={"expected_commitment_version": 0},
    )
    assert malformed.status_code == 422


def test_assessment_history_and_impact_get_do_not_claim_unavailable_storage(
    api_client: TestClient,
) -> None:
    commitment = _create_confirmed_commitment(api_client)
    history = api_client.get(
        f"/v1/commitments/{commitment['commitment_id']}/assessments"
    )
    impact = api_client.get("/v1/impacts/impact_unknown")

    assert history.status_code == 503
    assert history.json()["code"] == "P2_ASSESSMENT_HISTORY_NOT_CONFIGURED"
    assert impact.status_code == 503
    assert impact.json()["code"] == "P2_IMPACT_PERSISTENCE_NOT_CONFIGURED"


def test_assessment_routes_do_not_leak_missing_or_cross_tenant_commitments(
    api_client: TestClient,
) -> None:
    missing_assessment = api_client.post(
        "/v1/commitments/com_missing/assess",
        json={"expected_commitment_version": 1},
    )
    missing_history = api_client.get("/v1/commitments/com_missing/assessments")

    assert missing_assessment.status_code == 404
    assert missing_history.status_code == 404
    assert missing_assessment.json()["code"] == "COMMITMENT_NOT_FOUND"
    assert missing_history.json()["code"] == "COMMITMENT_NOT_FOUND"

    commitment = _create_confirmed_commitment(api_client)
    api_client.app.dependency_overrides[get_request_context] = lambda: RequestContext(
        tenant_id="tenant-other",
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_other_tenant",
    )
    cross_tenant = api_client.get(
        f"/v1/commitments/{commitment['commitment_id']}/assessments"
    )
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["code"] == "COMMITMENT_NOT_FOUND"


def test_supplier_delay_requires_scoped_typed_evidence_and_reports_blocked_outbox(
    api_client: TestClient,
) -> None:
    payload = _supplier_delay_payload()
    mismatch = api_client.post(
        "/v1/operations/events/supplier-delay",
        json={
            "change": {**payload["change"], "tenant_id": "tenant-other"},
            "source_evidence": {
                **payload["source_evidence"],
                "tenant_id": "tenant-other",
            },
        },
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["code"] == "TENANT_SCOPE_MISMATCH"

    missing_evidence = api_client.post(
        "/v1/operations/events/supplier-delay",
        json={"change": payload["change"]},
    )
    assert missing_evidence.status_code == 422

    unavailable = api_client.post("/v1/operations/events/supplier-delay", json=payload)
    duplicate = api_client.post("/v1/operations/events/supplier-delay", json=payload)
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "P2_SUPPLIER_DELAY_OUTBOX_NOT_CONFIGURED"
    assert duplicate.status_code == 503
    assert duplicate.json()["code"] == unavailable.json()["code"]


def test_supplier_delay_rejects_untyped_or_unmatched_evidence(api_client: TestClient) -> None:
    payload = _supplier_delay_payload()
    wrong_type = {
        **payload,
        "source_evidence": {**payload["source_evidence"], "evidence_type": "QUOTE"},
    }
    wrong_delivery = {
        **payload,
        "source_evidence": {**payload["source_evidence"], "delivery_id": "delivery_other"},
    }
    same_version = {
        **payload,
        "change": {
            **payload["change"],
            "after_snapshot_version": payload["change"]["before_snapshot_version"],
        },
    }

    for invalid in (wrong_type, wrong_delivery, same_version):
        response = api_client.post("/v1/operations/events/supplier-delay", json=invalid)
        assert response.status_code == 422


def test_shared_assessment_schema_rejects_empty_actual_impact_set() -> None:
    from app.core.fixture_loader import load_demo_fixture

    payload = load_demo_fixture().feasibility_assessment.model_dump(mode="json")
    assert FeasibilityAssessment.model_validate(payload).affected_commitment_ids
    payload["affected_commitment_ids"] = []

    with pytest.raises(ValidationError):
        FeasibilityAssessment.model_validate(payload)


def _supplier_delay_payload() -> dict:
    from app.feasibility.fixtures import build_supplier_delay_scenario
    from app.feasibility.impact import OperationalChange, OperationalChangeType, ResourceKey, ResourceKind
    from app.feasibility.models import SupplierDeliveryEvidence, SupplierDeliveryEvidenceType

    scenario = build_supplier_delay_scenario()
    before, after = scenario.before, scenario.after
    delivery = next(
        row for row in after.incoming_deliveries if row.delivery_id == "delivery-patty-001"
    )
    evidence = next(
        item
        for source in after.sources
        for item in source.supplier_delivery_evidence
        if item.evidence_type is SupplierDeliveryEvidenceType.ETA_CHANGE
    )
    change = OperationalChange(
        event_id="evt_supplier_delay_api_001",
        tenant_id=after.tenant_id,
        correlation_id="corr_supplier_delay_api_001",
        event_type=OperationalChangeType.SUPPLIER_DELIVERY_CHANGED,
        occurred_at=after.captured_at,
        before_snapshot_version=before.snapshot_version,
        after_snapshot_version=after.snapshot_version,
        resource_keys=(
            ResourceKey(kind=ResourceKind.SUPPLIER_DELIVERY, resource_id=delivery.delivery_id),
        ),
        evidence_refs=(evidence.evidence_ref,),
    )
    typed_evidence = SupplierDeliveryEvidence(
        evidence_id=evidence.evidence_id,
        tenant_id=evidence.tenant_id,
        delivery_id=evidence.delivery_id,
        supplier_id=evidence.supplier_id,
        evidence_type=evidence.evidence_type,
        evidence_ref=evidence.evidence_ref,
        observed_at=evidence.observed_at,
    )
    return {
        "change": change.model_dump(mode="json"),
        "source_evidence": typed_evidence.model_dump(mode="json"),
    }
