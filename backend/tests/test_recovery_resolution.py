"""P3 Commitment lookup and demo/auth boundaries; no live recovery execution."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import CommitmentRecord
from app.core.schemas import AgreementState, FeasibilityState, RecoveryState, RiskState
from app.recovery import router as recovery_api
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.integrations import P5CommitmentReader
from app.recovery.models import RecoveryTriggerReference
from app.recovery.service import RecoveryPlanner, RecoveryRepository


def _headers(tenant: str = "tenant_resolution") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Actor-ID": "user_manager_01", "X-Correlation-ID": "corr-resolution"}


def _context(tenant: str = "tenant_resolution") -> RequestContext:
    return RequestContext(tenant, "user_manager_01", "MANAGER", "corr-resolution")


def _save_core_commitment(session, commitment_id: str = "com_not_demo"):
    source = load_demo_recovery_inputs().commitment
    commitment = source.model_copy(update={
        "tenant_id": "tenant_resolution", "commitment_id": commitment_id,
        "commitment_version": 5,
        "agreement_state": AgreementState.CONFIRMED,
        "feasibility_state": FeasibilityState.INFEASIBLE,
        "risk_state": RiskState.AT_RISK,
        "recovery_state": RecoveryState.RECOVERY_REQUIRED,
    })
    session.add(CommitmentRecord(
        tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        order_id=commitment.order_id, customer_id=commitment.customer_id,
        terms=commitment.terms.model_dump(mode="json"),
        agreement_state=commitment.agreement_state.value,
        feasibility_state=commitment.feasibility_state.value,
        risk_state=commitment.risk_state.value,
        recovery_state=commitment.recovery_state.value,
        fulfilment_state=commitment.fulfilment_state.value,
        commitment_version=commitment.commitment_version,
        evidence_refs=commitment.evidence_refs, updated_at=commitment.updated_at,
    ))
    session.commit()
    return commitment


def _trigger(commitment):
    return RecoveryTriggerReference(
        event_id="evt_resolution_lookup", tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=commitment.commitment_version,
        assessment_id="fa_resolution_lookup", assessment_commitment_version=4,
        assessment_provenance_status="SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED",
        snapshot_version=142, correlation_id="corr-resolution",
        evidence_refs=["ev_resolution_lookup"], occurred_at=datetime.now(UTC),
    )


def test_core_reader_resolves_arbitrary_id_without_fixture_fallback(session) -> None:
    commitment = _save_core_commitment(session)
    planner = RecoveryPlanner(repository=RecoveryRepository(), commitment_reader=P5CommitmentReader())
    assert planner._get_commitment(commitment.tenant_id, commitment.commitment_id,
                                   db=session, request_context=_context()).commitment_id == "com_not_demo"
    for tenant, commitment_id in [
        ("tenant_other", "com_not_demo"), ("tenant_unknown", "com_not_demo"),
        ("tenant_resolution", "com_001"), ("tenant_resolution", "com_missing"),
    ]:
        with pytest.raises(DomainError) as error:
            planner._get_commitment(tenant, commitment_id, db=session, request_context=_context(tenant))
        assert error.value.status_code == 404
    with pytest.raises(DomainError, match="server session and context"):
        planner._get_commitment(commitment.tenant_id, commitment.commitment_id)


def test_mismatched_reader_identity_is_rejected(session) -> None:
    commitment = _save_core_commitment(session)

    class WrongCommitmentReader:
        def get_commitment(self, db, context, commitment_id, *, expected_commitment_version=None):
            return commitment.model_copy(update={"commitment_id": "com_other"})

    planner = RecoveryPlanner(repository=RecoveryRepository(), commitment_reader=WrongCommitmentReader())
    with pytest.raises(DomainError) as error:
        planner.get_case(commitment.tenant_id, commitment.commitment_id,
                         db=session, request_context=_context())
    assert error.value.code == "RECOVERY_CASE_NOT_FOUND"


def test_core_backed_case_routes_preserve_id_and_block_planning_without_p2_inputs(
    session, client: TestClient, monkeypatch,
) -> None:
    commitment = _save_core_commitment(session)
    planner = RecoveryPlanner(repository=RecoveryRepository(), commitment_reader=P5CommitmentReader())
    case, created, _ = planner.create_trigger_case(commitment, _trigger(commitment))
    assert created and case.commitment_id == "com_not_demo"
    monkeypatch.setattr(recovery_api, "default_recovery_planner", planner)

    path = f"/v1/recovery/cases/{commitment.commitment_id}"
    pending = client.get(path, headers=_headers())
    trigger = client.get(f"{path}/trigger", headers=_headers())
    assert pending.status_code == 409 and pending.json()["code"] == "RECOVERY_EVALUATION_INPUTS_PENDING"
    assert trigger.status_code == 200
    assert (trigger.json()["tenant_id"], trigger.json()["commitment_id"]) == (
        commitment.tenant_id, commitment.commitment_id
    )
    assert trigger.json()["storage_mode"] == "IN_MEMORY_SYNTHETIC"
    blocked = client.post(f"{path}/generate", headers=_headers(),
                          json={"expected_commitment_version": commitment.commitment_version})
    assert blocked.status_code == 409 and blocked.json()["code"] == "AUTHORITATIVE_RECOVERY_INPUT_REQUIRED"
    assert client.get(path, headers=_headers("tenant_other")).status_code == 404
    assert client.get(path, headers=_headers("tenant_unknown")).status_code == 404
    assert client.get("/v1/recovery/cases/com_001", headers=_headers()).json()["code"] == "COMMITMENT_NOT_FOUND"


def test_explicit_demo_is_isolated_from_real_com_001_and_cannot_authorize_approval(
    session, client: TestClient,
) -> None:
    _save_core_commitment(session, "com_001")
    demo = client.get("/v1/recovery/cases/demo", headers=_headers("tenant_demo_01"))
    assert demo.status_code == 200
    assert demo.json()["commitment_id"] == "com_001"
    assert demo.json()["storage_mode"] == "IN_MEMORY_SYNTHETIC"
    real = client.get("/v1/recovery/cases/com_001", headers=_headers())
    assert real.status_code == 404 and real.json()["code"] == "RECOVERY_CASE_NOT_FOUND"
    forged = client.post(
        "/v1/recovery/plans/plan_a/approve", headers={**_headers("tenant_demo_01"), "X-Actor-Role": "MANAGER"},
        json={"expected_commitment_version": 3, "expected_plan_version": 1,
              "expected_snapshot_version": 142, "reason": "forged", "actor_role": "MANAGER", "approved": True},
    )
    assert forged.status_code in {403, 422}
    assert forged.json()["code"] in {"VERIFIED_ACTOR_REQUIRED", "REQUEST_VALIDATION_ERROR"}


def test_plan_reader_requires_parent_case_and_current_core_tenant_lookup(session) -> None:
    commitment = _save_core_commitment(session)
    planner = RecoveryPlanner(repository=RecoveryRepository(), commitment_reader=P5CommitmentReader())
    case, _, _ = planner.create_trigger_case(commitment, _trigger(commitment))
    # A copied synthetic plan exercises read scoping only; it is not executable or authoritative.
    demo_plan = RecoveryPlanner().generate(
        "tenant_demo_01", "com_001", expected_commitment_version=3
    ).plans[0].model_copy(deep=True)
    demo_plan.plan_id = "plan_resolution_read_only"
    demo_plan.tenant_id = commitment.tenant_id
    demo_plan.commitment_id = commitment.commitment_id
    demo_plan.recovery_case_id = case.case_id
    demo_plan.evaluation.plan_id = demo_plan.plan_id
    demo_plan.evaluation.tenant_id = commitment.tenant_id
    demo_plan.evaluation.commitment_id = commitment.commitment_id
    case.plans = [demo_plan]
    planner.repository.save_case(case)

    read = planner.get_plan(commitment.tenant_id, demo_plan.plan_id,
                            db=session, request_context=_context())
    assert (read.tenant_id, read.commitment_id, read.recovery_case_id) == (
        commitment.tenant_id, commitment.commitment_id, case.case_id
    )
    with pytest.raises(DomainError) as wrong_tenant:
        planner.get_plan("tenant_other", demo_plan.plan_id, db=session,
                         request_context=_context("tenant_other"))
    assert wrong_tenant.value.status_code == 404
    session.delete(session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id)))
    session.commit()
    with pytest.raises(DomainError) as missing_parent:
        planner.get_plan(commitment.tenant_id, demo_plan.plan_id,
                         db=session, request_context=_context())
    assert missing_parent.value.code == "COMMITMENT_NOT_FOUND"


def test_core_risk_resolution_blocks_planning_even_with_old_trigger(session) -> None:
    commitment = _save_core_commitment(session)
    planner = RecoveryPlanner(repository=RecoveryRepository(), commitment_reader=P5CommitmentReader())
    planner.create_trigger_case(commitment, _trigger(commitment))
    row = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    row.risk_state = RiskState.NORMAL.value
    row.commitment_version = 6
    session.commit()
    with pytest.raises(DomainError) as error:
        planner.generate(commitment.tenant_id, commitment.commitment_id,
                         expected_commitment_version=6, db=session, request_context=_context())
    assert error.value.code == "RECOVERY_COMMITMENT_NOT_ELIGIBLE"
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id).plans == []


def test_conditional_assessment_cannot_enter_core_backed_planning(session) -> None:
    commitment = _save_core_commitment(session)
    planner = RecoveryPlanner(repository=RecoveryRepository(), commitment_reader=P5CommitmentReader())
    case, _, _ = planner.create_trigger_case(commitment, _trigger(commitment))
    fixture = load_demo_recovery_inputs()
    case.trigger_assessment = fixture.assessment.model_copy(update={
        "tenant_id": commitment.tenant_id, "commitment_id": commitment.commitment_id,
        "status": FeasibilityState.CONDITIONAL,
    })
    case.operational_snapshot = fixture.snapshot
    planner.repository.save_case(case)
    with pytest.raises(DomainError) as error:
        planner.generate(commitment.tenant_id, commitment.commitment_id,
                         expected_commitment_version=commitment.commitment_version,
                         db=session, request_context=_context())
    assert error.value.code == "INFEASIBLE_ASSESSMENT_REQUIRED"
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id).plans == []
