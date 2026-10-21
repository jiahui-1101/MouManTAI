from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.fixture_loader import load_demo_fixture
from app.core.schemas import BusinessContext, DomainEvent


def test_demo_fixture_validates_all_shared_contracts() -> None:
    fixture = load_demo_fixture()

    assert fixture.tenant_id == "tenant_demo_01"
    assert fixture.commitment.commitment_id == "com_001"
    assert fixture.commitment.agreement_state.value == "CONFIRMED"
    assert fixture.feasibility_assessment.status.value == "INFEASIBLE"
    assert len(fixture.recovery_plans) == 2
    assert fixture.confirmation.state.value == "ACCEPTED"
    assert fixture.commitment.fulfilment_state.value == "NOT_STARTED"
    assert fixture.fulfilment_evidence["verified"] is False


def test_decimal_values_are_serialized_as_wire_strings() -> None:
    fixture = load_demo_fixture()

    assert fixture.commitment.terms.quantity == Decimal("100")
    assert fixture.recovery_plans[0].model_dump(mode="json")["estimated_extra_cost"] == "80.00"


def test_legacy_ready_input_is_normalized_to_canonical_status() -> None:
    context = BusinessContext.model_validate(
        {
            "tenant_id": "tenant_demo_01",
            "context_id": "ctx_legacy",
            "source_message_ids": ["msg_legacy"],
            "requested_items": [{"sku": "BURGER", "quantity": "1", "unit": "pcs"}],
            "context_version": 1,
            "status": "READY",
        }
    )

    assert context.status.value == "INFORMATION_READY"


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="explicit UTC offset"):
        DomainEvent.model_validate(
            {
                "event_id": "evt_001",
                "schema_version": 1,
                "event_type": "commitment.created",
                "tenant_id": "tenant_demo_01",
                "correlation_id": "corr_001",
                "occurred_at": "2026-10-21T10:00:00",
            }
        )


def test_feasibility_assessment_allows_empty_affected_commitments_for_feasible() -> None:
    from app.core.schemas import FeasibilityAssessment, FeasibilityState, SolverStatus

    assessment = FeasibilityAssessment.model_validate(
        {
            "assessment_id": "fa_001",
            "tenant_id": "tenant_demo_01",
            "commitment_id": "com_001",
            "commitment_version": 1,
            "snapshot_version": 100,
            "status": "FEASIBLE",
            "constraints": [],
            "affected_commitment_ids": [],
            "evidence_refs": ["ev_001"],
            "solver_status": "COMPLETED",
            "assumptions": ["Sufficient inventory"],
            "assessed_at": "2026-10-21T10:00:00+08:00",
        }
    )

    assert assessment.status == FeasibilityState.FEASIBLE
    assert assessment.affected_commitment_ids == []


def test_feasibility_assessment_allows_empty_affected_commitments_for_unknown() -> None:
    from app.core.schemas import FeasibilityAssessment, FeasibilityState, SolverStatus

    assessment = FeasibilityAssessment.model_validate(
        {
            "assessment_id": "fa_002",
            "tenant_id": "tenant_demo_01",
            "commitment_id": "com_002",
            "commitment_version": 1,
            "snapshot_version": 101,
            "status": "UNKNOWN",
            "constraints": [],
            "affected_commitment_ids": [],
            "evidence_refs": [],
            "solver_status": "UNKNOWN",
            "assumptions": ["Awaiting supplier confirmation"],
            "assessed_at": "2026-10-21T10:15:00+08:00",
        }
    )

    assert assessment.status == FeasibilityState.UNKNOWN
    assert assessment.affected_commitment_ids == []


def test_feasibility_assessment_defaults_affected_commitments_to_empty_list() -> None:
    from app.core.schemas import FeasibilityAssessment

    assessment = FeasibilityAssessment.model_validate(
        {
            "assessment_id": "fa_003",
            "tenant_id": "tenant_demo_01",
            "commitment_id": "com_003",
            "commitment_version": 1,
            "snapshot_version": 102,
            "status": "FEASIBLE",
            "solver_status": "COMPLETED",
            "assessed_at": "2026-10-21T10:30:00+08:00",
        }
    )

    assert assessment.affected_commitment_ids == []


def test_feasible_assessment_example_fixture_validates() -> None:
    import json
    from pathlib import Path
    from app.core.schemas import FeasibilityAssessment

    fixture_path = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "feasible_assessment_example.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    feasible = FeasibilityAssessment.model_validate(data["feasible_example"])
    assert feasible.status.value == "FEASIBLE"
    assert feasible.affected_commitment_ids == []

    unknown = FeasibilityAssessment.model_validate(data["unknown_example"])
    assert unknown.status.value == "UNKNOWN"
    assert unknown.affected_commitment_ids == []

    infeasible = FeasibilityAssessment.model_validate(data["infeasible_isolated_example"])
    assert infeasible.status.value == "INFEASIBLE"
    assert infeasible.affected_commitment_ids == []
