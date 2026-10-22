from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.schemas import FeasibilityState
from app.recovery.feasibility import FeasibilityResult, P2FeasibilityAdapter, SyntheticP2Evaluator
from app.recovery.models import (
    BusinessPreferences,
    RecoveryCaseStatus,
    RecoveryStrategy,
    ValidationSource,
)
from app.recovery.service import RecoveryPlanner, RecoveryRepository


def _headers(tenant: str = "tenant_demo_01") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Actor-ID": "user_manager_01",
        "X-Correlation-ID": "corr_recovery_test",
    }


def test_recovery_generation_produces_two_options_on_one_snapshot_and_is_idempotent(client: TestClient) -> None:
    initial = client.get("/v1/recovery/cases/demo", headers=_headers())
    assert initial.status_code == 200, initial.text
    assert initial.json()["plans"] == []
    assert initial.json()["trigger_assessment"]["assessment_id"] == "fa_001"

    generated = client.post(
        "/v1/recovery/cases/demo/generate",
        headers=_headers(),
        json={"expected_commitment_version": 3, "assessment_id": "fa_001"},
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["status"] == RecoveryCaseStatus.OPTIONS_READY
    assert len(body["options"]) == 2
    assert {option["strategy"] for option in body["options"]} == {
        RecoveryStrategy.ALTERNATIVE_SUPPLY,
        RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT,
    }
    assert all(plan["snapshot_version"] == 142 for plan in body["plans"])
    assert body["options"][0]["estimated_extra_cost"] in {"80.00", "0.00"}
    assert all(plan["approval_state"] == "PENDING" for plan in body["plans"])
    assert all(plan["execution_state"] == "NOT_STARTED" for plan in body["plans"])
    assert any(plan["evaluation"]["validation_source"] == ValidationSource.TEST_DOUBLE_VALIDATED for plan in body["plans"])
    assert any(option["feasibility_status"] == FeasibilityState.CONDITIONAL for option in body["options"])
    assert sum(1 for option in body["options"] if option["recommended"]) == 1

    repeated = client.post(
        "/v1/recovery/cases/demo/generate",
        headers=_headers(),
        json={"expected_commitment_version": 3, "assessment_id": "fa_001"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["case_version"] == body["case_version"]
    assert repeated.json()["plans"] == body["plans"]

    plan_id = body["plans"][0]["plan_id"]
    evaluation = client.get(f"/v1/recovery/plans/{plan_id}/evaluation", headers=_headers())
    assert evaluation.status_code == 200
    assert evaluation.json()["plan_id"] == plan_id

    plans = client.get("/v1/recovery/cases/demo/plans", headers=_headers())
    assert plans.status_code == 200
    assert len(plans.json()["plans"]) == 2


def test_recovery_enforces_tenant_and_commitment_version(client: TestClient) -> None:
    wrong_tenant = client.get("/v1/recovery/cases/demo", headers=_headers("tenant_other"))
    assert wrong_tenant.status_code == 404
    assert wrong_tenant.json()["code"] == "TENANT_SCOPE_VIOLATION"

    stale = client.post(
        "/v1/recovery/cases/demo/generate",
        headers=_headers(),
        json={"expected_commitment_version": 2},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "COMMITMENT_VERSION_CONFLICT"
    assert stale.json()["details"]["current_commitment_version"] == 3


def test_no_feasible_options_are_not_recommended() -> None:
    outcomes = {
        strategy: FeasibilityResult(
            status=FeasibilityState.INFEASIBLE,
            solver_status="COMPLETED",
            constraints=["NO_SAFE_PATH"],
            evidence_refs=["ev_test"],
            assumptions=[],
            validation_source=ValidationSource.TEST_DOUBLE_VALIDATED,
        )
        for strategy in ("ALTERNATIVE_SUPPLY", "RESCHEDULE_PARTIAL_FULFILMENT")
    }
    planner = RecoveryPlanner(
        repository=RecoveryRepository(),
        evaluator=SyntheticP2Evaluator(outcomes),
    )
    case = planner.generate(
        "tenant_demo_01",
        "com_001",
        expected_commitment_version=3,
        preferences=BusinessPreferences(),
    )
    assert case.status == RecoveryCaseStatus.NO_SAFE_PLAN
    assert not any(option.recommended for option in case.options)
    assert all(option.feasibility_status == FeasibilityState.INFEASIBLE for option in case.options)


def test_p2_adapter_preserves_pure_evaluator_contract_and_shared_plan_shape() -> None:
    class FakeP2:
        def __init__(self) -> None:
            self.calls: list[tuple[object, dict, object]] = []

        def evaluate(self, snapshot, proposed_changes, commitment):
            self.calls.append((snapshot, proposed_changes, commitment))
            return FeasibilityResult(
                status=FeasibilityState.CONDITIONAL,
                solver_status="COMPLETED",
                constraints=["TEST_CONSTRAINT"],
                evidence_refs=["ev_test"],
                assumptions=["test"],
                validation_source=ValidationSource.TEST_DOUBLE_VALIDATED,
            )

    fake = FakeP2()
    adapter = P2FeasibilityAdapter(fake)
    planner = RecoveryPlanner(repository=RecoveryRepository(), evaluator=adapter)
    case = planner.generate("tenant_demo_01", "com_001", expected_commitment_version=3)

    assert len(fake.calls) == 2
    assert all(plan.evaluation.validation_source == ValidationSource.REAL_P2_VALIDATED for plan in case.plans)
    assert case.plans[0].as_shared_plan().plan_id == case.plans[0].plan_id
    assert all(isinstance(plan.estimated_extra_cost, Decimal) for plan in case.plans)
