from collections.abc import Generator
from datetime import datetime, timedelta, timezone
import importlib

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.errors import DomainError
from app.core.router import router as core_router
from app.core.schemas import Commitment, FeasibilityAssessment
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


def _flatten_routes(router) -> list:
    flattened = []
    for route in router.routes:
        included_router = getattr(route, "original_router", None)
        if included_router is None:
            flattened.append(route)
        else:
            flattened.extend(_flatten_routes(included_router))
    return flattened


def _route_method_paths(router) -> list[tuple[str, str]]:
    return sorted(
        (method, route.path)
        for route in _flatten_routes(router)
        for method in (getattr(route, "methods", None) or set())
    )


class RecordingAssessmentHistoryReader:
    def __init__(self, *, result=None, error: DomainError | None = None, listed=None) -> None:
        self.result = result
        self.error = error
        self.listed = listed or []
        self.get_calls: list[tuple[str, str, str]] = []
        self.list_calls: list[tuple[str, str]] = []

    def get_assessment(self, db, context, commitment_id: str, assessment_id: str):
        self.get_calls.append((context.tenant_id, commitment_id, assessment_id))
        if self.error is not None:
            raise self.error
        return self.result

    def list_for_commitment(self, db, context, commitment_id: str):
        self.list_calls.append((context.tenant_id, commitment_id))
        return self.listed


def test_feasibility_routers_are_separately_mountable_and_compatibly_combined() -> None:
    router_module = importlib.import_module("app.feasibility.router")
    expected_by_router = {
        "feasibility_read_router": {
            ("GET", "/v1/commitments/{commitment_id}/assessments"),
            ("GET", "/v1/commitments/{commitment_id}/assessments/{assessment_id}"),
            ("GET", "/v1/impacts/{impact_id}"),
        },
        "feasibility_assessment_router": {
            ("POST", "/v1/commitments/{commitment_id}/assess"),
        },
        "feasibility_supplier_event_router": {
            ("POST", "/v1/operations/events/supplier-delay"),
        },
        "feasibility_internal_router": {
            ("POST", "/internal/feasibility/evaluate"),
        },
    }

    for router_name, expected_routes in expected_by_router.items():
        actual_routes = _route_method_paths(getattr(router_module, router_name))
        assert set(actual_routes) == expected_routes
        assert len(actual_routes) == len(expected_routes)

    expected_combined_routes = set().union(*expected_by_router.values())
    combined_routes = _route_method_paths(router_module.router)
    assert router_module.router is feasibility_router
    assert all(method == "GET" for method, _ in _route_method_paths(
        router_module.feasibility_read_router
    ))
    assert set(combined_routes) == expected_combined_routes
    assert len(combined_routes) == len(expected_combined_routes) == 6

    assessment_path = "/v1/commitments/{commitment_id}/assess"
    assessment_endpoint = next(
        route.endpoint
        for route in _flatten_routes(router_module.feasibility_assessment_router)
        if route.path == assessment_path
    )
    combined_assessment_endpoint = next(
        route.endpoint
        for route in _flatten_routes(router_module.router)
        if route.path == assessment_path
    )
    assert combined_assessment_endpoint is assessment_endpoint

    core_assessment_routes = {
        (method, route.path)
        for route in _flatten_routes(core_router)
        for method in (getattr(route, "methods", None) or set())
        if route.path == assessment_path
    }
    assert ("POST", assessment_path) not in core_assessment_routes


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
    internal_context = RequestContext(
        tenant_id="tenant-synthetic-p2",
        actor_id="service_p2_feasibility",
        actor_role="SERVICE",
        correlation_id="corr_p2_internal_router_test",
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_request_context] = lambda: context
    app.dependency_overrides[get_internal_request_context] = lambda: internal_context
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


def _assessment_for_lookup(commitment: dict, assessment_id: str) -> FeasibilityAssessment:
    return FeasibilityAssessment(
        assessment_id=assessment_id,
        tenant_id=commitment["tenant_id"],
        commitment_id=commitment["commitment_id"],
        commitment_version=commitment["commitment_version"],
        snapshot_version=101,
        status="FEASIBLE",
        solver_status="COMPLETED",
        assessed_at=datetime.now(timezone.utc),
    )


def test_assessment_lookup_returns_exact_persisted_result_without_recalculation(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commitment = _create_confirmed_commitment(api_client)
    assessment = _assessment_for_lookup(commitment, "fa_exact_lookup_001")
    reader = RecordingAssessmentHistoryReader(result=assessment)
    api_client.app.dependency_overrides[get_assessment_history] = lambda: reader

    router_module = importlib.import_module("app.feasibility.router")
    monkeypatch.setattr(
        router_module,
        "evaluate",
        lambda *args, **kwargs: pytest.fail("lookup must not calculate a new assessment"),
    )
    response = api_client.get(
        f"/v1/commitments/{commitment['commitment_id']}/assessments/{assessment.assessment_id}"
    )

    assert response.status_code == 200, response.text
    assert response.json() == assessment.model_dump(mode="json")
    assert reader.get_calls == [
        (commitment["tenant_id"], commitment["commitment_id"], assessment.assessment_id)
    ]
    assert reader.list_calls == []


def test_assessment_lookup_returns_not_found_for_missing_assessment_id(
    api_client: TestClient,
) -> None:
    commitment = _create_confirmed_commitment(api_client)
    reader = RecordingAssessmentHistoryReader(
        error=DomainError(
            "ASSESSMENT_NOT_FOUND",
            "Authoritative assessment was not found",
            status_code=404,
        )
    )
    api_client.app.dependency_overrides[get_assessment_history] = lambda: reader

    response = api_client.get(
        f"/v1/commitments/{commitment['commitment_id']}/assessments/fa_missing_lookup"
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ASSESSMENT_NOT_FOUND"
    assert reader.get_calls == [
        (commitment["tenant_id"], commitment["commitment_id"], "fa_missing_lookup")
    ]


def test_assessment_lookup_hides_cross_tenant_commitment(
    api_client: TestClient,
) -> None:
    commitment = _create_confirmed_commitment(api_client)
    assessment = _assessment_for_lookup(commitment, "fa_cross_tenant_lookup")
    reader = RecordingAssessmentHistoryReader(result=assessment)
    api_client.app.dependency_overrides[get_assessment_history] = lambda: reader
    api_client.app.dependency_overrides[get_request_context] = lambda: RequestContext(
        tenant_id="tenant-other",
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_other_tenant",
    )

    response = api_client.get(
        f"/v1/commitments/{commitment['commitment_id']}/assessments/{assessment.assessment_id}"
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COMMITMENT_NOT_FOUND"
    assert reader.get_calls == []


def test_assessment_lookup_fails_closed_without_history_dependency(
    api_client: TestClient,
) -> None:
    commitment = _create_confirmed_commitment(api_client)
    response = api_client.get(
        f"/v1/commitments/{commitment['commitment_id']}/assessments/fa_unavailable_lookup"
    )

    assert response.status_code == 503
    assert response.json()["code"] == "P2_ASSESSMENT_HISTORY_NOT_CONFIGURED"


def test_assessment_lookup_propagates_advisory_provenance_rejection(
    api_client: TestClient,
) -> None:
    from app.core.events import CoreEventType
    from app.core.feasibility_adapters import AuthoritativeAssessmentHistoryReader
    from app.core.models import AuditEventRecord

    commitment = _create_confirmed_commitment(api_client)
    assessment_id = "fa_advisory_lookup"
    audit = AuditEventRecord(
        audit_id="aud_advisory_lookup_01",
        tenant_id=commitment["tenant_id"],
        commitment_id=commitment["commitment_id"],
        event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
        actor_id="service_p2",
        actor_role="SERVICE",
        dimension="feasibility",
        previous_state={},
        new_state={
            "advisory": True,
            "assessment_id": assessment_id,
            "feasibility_state": "FEASIBLE",
            "commitment_version": commitment["commitment_version"],
            "snapshot_version": 101,
        },
        evidence_refs=[],
        reason="Advisory lookup regression",
        correlation_id="corr_advisory_lookup",
        occurred_at=datetime.now(timezone.utc),
    )
    db_generator = api_client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        db.add(audit)
        db.commit()
    finally:
        db_generator.close()
    api_client.app.dependency_overrides[get_assessment_history] = (
        lambda: AuthoritativeAssessmentHistoryReader()
    )

    response = api_client.get(
        f"/v1/commitments/{commitment['commitment_id']}/assessments/{assessment_id}"
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ASSESSMENT_PROVENANCE_MISSING"
    assert response.json()["details"]["field"] == "advisory"


@pytest.mark.parametrize(
    "field,wrong_value",
    [
        ("assessment_id", "fa_other_lookup"),
        ("tenant_id", "tenant-other"),
        ("commitment_id", "com_other_lookup"),
    ],
)
def test_assessment_lookup_rejects_mismatched_reader_identity(
    api_client: TestClient,
    field: str,
    wrong_value: str,
) -> None:
    commitment = _create_confirmed_commitment(api_client)
    assessment = _assessment_for_lookup(commitment, "fa_requested_lookup")
    mismatched = assessment.model_copy(update={field: wrong_value})
    reader = RecordingAssessmentHistoryReader(result=mismatched)
    api_client.app.dependency_overrides[get_assessment_history] = lambda: reader

    response = api_client.get(
        f"/v1/commitments/{commitment['commitment_id']}/assessments/fa_requested_lookup"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ASSESSMENT_PROVENANCE_MISMATCH"
    assert field in response.json()["details"]["mismatched_fields"]


def test_assessment_list_get_remains_list_reader_operation(api_client: TestClient) -> None:
    commitment = _create_confirmed_commitment(api_client)
    assessment = _assessment_for_lookup(commitment, "fa_list_lookup")
    reader = RecordingAssessmentHistoryReader(listed=[assessment])
    api_client.app.dependency_overrides[get_assessment_history] = lambda: reader

    response = api_client.get(
        f"/v1/commitments/{commitment['commitment_id']}/assessments"
    )

    assert response.status_code == 200, response.text
    assert response.json() == [assessment.model_dump(mode="json")]
    assert reader.list_calls == [(commitment["tenant_id"], commitment["commitment_id"])]
    assert reader.get_calls == []


def _evaluation_payload() -> dict:
    snapshot, commitment = build_production_example()
    return {
        "snapshot": snapshot.model_dump(mode="json", exclude_computed_fields=True),
        "commitment": commitment.model_dump(mode="json"),
        "proposed_changes": None,
    }


def _assessment_inputs(core_commitment: dict) -> tuple:
    snapshot, fixture_commitment = build_production_example()
    core = Commitment.model_validate(core_commitment)
    resolved = fixture_commitment.model_copy(
        update={
            "tenant_id": core.tenant_id,
            "commitment_id": core.commitment_id,
            "order_id": core.order_id,
            "customer_id": core.customer_id,
            "terms": core.terms,
            "agreement_state": core.agreement_state,
            "commitment_version": core.commitment_version,
        }
    )
    snapshot = _snapshot_with_commitment_terms(snapshot, resolved).model_copy(
        update={"current_snapshot_version": snapshot.operational.snapshot_version}
    )
    return snapshot, resolved


def _snapshot_with_commitment_terms(snapshot, commitment: Commitment):
    matched = False
    confirmed_commitments = []
    for row in snapshot.operational.confirmed_commitments:
        if row.commitment_id not in {"com-001", commitment.commitment_id}:
            confirmed_commitments.append(row)
            continue
        matched = True
        line = row.lines[0].model_copy(
            update={
                "sku_id": commitment.terms.sku,
                "quantity": commitment.terms.quantity,
                "unit": commitment.terms.unit,
            }
        )
        confirmed_commitments.append(
            row.model_copy(
                update={
                    "tenant_id": commitment.tenant_id,
                    "commitment_id": commitment.commitment_id,
                    "commitment_version": commitment.commitment_version,
                    "delivery_deadline": commitment.terms.deadline,
                    "lines": (line,),
                }
            )
        )
    assert matched, "fixture target commitment must be present in the snapshot"
    operational = snapshot.operational.model_copy(
        update={"confirmed_commitments": tuple(confirmed_commitments)}
    )
    return snapshot.model_copy(update={"operational": operational})


def _changed_commitment(core: Commitment, mismatch: str) -> Commitment:
    data = core.model_dump(mode="python")
    terms = core.terms.model_dump(mode="python")
    if mismatch == "tenant_id":
        data["tenant_id"] = "tenant-resolver-mismatch"
    elif mismatch == "order_id":
        data["order_id"] = "order-resolver-mismatch"
    elif mismatch == "customer_id":
        data["customer_id"] = "customer-resolver-mismatch"
    elif mismatch == "agreement_state":
        data["agreement_state"] = "OFFERED"
    elif mismatch == "terms.quantity":
        terms["quantity"] = "125"
    elif mismatch == "terms.deadline":
        terms["deadline"] = core.terms.deadline + timedelta(days=1)
    elif mismatch == "terms.special_instructions":
        terms["special_instructions"] = "Pack sauce separately"
    else:
        raise AssertionError(f"unsupported mismatch test: {mismatch}")
    data["terms"] = terms
    return Commitment.model_validate(data)


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
    assert "shared_output_blocker" not in result
    assert "affected_commitment_ids" not in result
    assert authority.calls == 1


def test_internal_evaluate_rejects_untrusted_requester_before_authority_or_solver(
    api_client: TestClient,
) -> None:
    payload = _evaluation_payload()
    authority = FixtureEvaluationAuthority()
    api_client.app.dependency_overrides[get_evaluation_input_authority] = lambda: authority
    api_client.app.dependency_overrides[get_internal_request_context] = lambda: RequestContext(
        tenant_id=payload["commitment"]["tenant_id"],
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_untrusted_internal_call",
    )

    response = api_client.post("/internal/feasibility/evaluate", json=payload)

    assert response.status_code == 403
    assert response.json()["code"] == "P2_INTERNAL_CALLER_NOT_AUTHORIZED"
    assert authority.calls == 0


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


def test_internal_evaluate_rejects_resolved_baseline_terms_before_evaluation(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    payload = _evaluation_payload()
    requested_commitment = Commitment.model_validate(payload["commitment"])
    resolved_commitment = _changed_commitment(requested_commitment, "terms.quantity")
    evaluation_snapshot, _ = build_production_example()
    resolved_snapshot = _snapshot_with_commitment_terms(
        evaluation_snapshot,
        resolved_commitment,
    )
    calls = {"evaluate": 0}

    class ContradictoryAuthority:
        def resolve(self, context, request):
            return resolved_snapshot, resolved_commitment

    router_module = importlib.import_module("app.feasibility.router")

    def recording_evaluate(*args, **kwargs):
        calls["evaluate"] += 1
        raise AssertionError("evaluator must not receive contradictory baseline terms")

    monkeypatch.setattr(router_module, "evaluate", recording_evaluate)
    api_client.app.dependency_overrides[get_evaluation_input_authority] = (
        lambda: ContradictoryAuthority()
    )

    response = api_client.post("/internal/feasibility/evaluate", json=payload)

    assert response.status_code == 409
    assert response.json()["code"] == "COMMITMENT_BINDING_MISMATCH"
    assert "terms.quantity" in response.json()["details"]["mismatched_fields"]
    assert calls["evaluate"] == 0


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


@pytest.mark.parametrize(
    ("mismatch", "mismatch_field"),
    [
        ("tenant_id", "tenant_id"),
        ("order_id", "order_id"),
        ("customer_id", "customer_id"),
        ("terms.quantity", "terms.quantity"),
        ("terms.deadline", "terms.deadline"),
        ("terms.special_instructions", "terms.special_instructions"),
        ("agreement_state", "agreement_state"),
    ],
)
def test_assess_rejects_core_resolver_commitment_mismatch_before_evaluate_or_write(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
    mismatch_field: str,
) -> None:
    core_data = _create_confirmed_commitment(api_client)
    snapshot, core_commitment = _assessment_inputs(core_data)
    resolved_commitment = _changed_commitment(core_commitment, mismatch)
    # Keep the operational row aligned to the resolver so quantity/deadline
    # cases isolate Core-versus-resolver binding, not Phase 3 snapshot checks.
    snapshot = _snapshot_with_commitment_terms(snapshot, resolved_commitment)
    calls = {"evaluate": 0, "writer": 0}

    class AssessmentAuthority:
        def resolve_current(self, context, commitment_id, expected_commitment_version):
            return snapshot, resolved_commitment

    class RecordingWriter:
        def assess(self, *args, **kwargs):
            calls["writer"] += 1
            raise DomainError(
                "TEST_WRITER_CALLED",
                "Writer must not be called for mismatched Core identity",
                status_code=503,
            )

    import importlib
    router_module = importlib.import_module("app.feasibility.router")
    p2_evaluate = router_module.evaluate

    def recording_evaluate(*args, **kwargs):
        calls["evaluate"] += 1
        return p2_evaluate(*args, **kwargs)

    monkeypatch.setattr(router_module, "evaluate", recording_evaluate)
    api_client.app.dependency_overrides[get_evaluation_input_authority] = (
        lambda: AssessmentAuthority()
    )
    api_client.app.dependency_overrides[get_assessment_writer] = lambda: RecordingWriter()

    response = api_client.post(
        f"/v1/commitments/{core_data['commitment_id']}/assess",
        json={"expected_commitment_version": core_data["commitment_version"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "COMMITMENT_BINDING_MISMATCH"
    assert mismatch_field in response.json()["details"]["mismatched_fields"]
    assert calls == {"evaluate": 0, "writer": 0}


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


def test_shared_assessment_schema_accepts_empty_actual_impact_set() -> None:
    from app.core.fixture_loader import load_demo_fixture

    payload = load_demo_fixture().feasibility_assessment.model_dump(mode="json")
    assert FeasibilityAssessment.model_validate(payload).affected_commitment_ids
    payload["affected_commitment_ids"] = []

    assessment = FeasibilityAssessment.model_validate(payload)
    assert assessment.affected_commitment_ids == []


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
