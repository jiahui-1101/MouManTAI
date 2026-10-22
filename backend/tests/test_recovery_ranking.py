from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.schemas import FeasibilityState
from app.recovery.feasibility import FeasibilityResult, P2FeasibilityAdapter
from app.recovery.models import BusinessPreferences, RecoveryCaseStatus, ValidationSource
from app.recovery.ranking import RankingCandidate, rank_candidates, score_candidate
from app.recovery.service import RecoveryPlanner, RecoveryRepository


def _candidate(
    plan_id: str,
    *,
    status: FeasibilityState = FeasibilityState.FEASIBLE,
    source: ValidationSource = ValidationSource.REAL_P2_VALIDATED,
    cost: str = "0",
    delay: int = 0,
    affected: tuple[str, ...] = (),
    disruption: str = "0",
    supplier_uncertainty: str = "0",
    confirmation: bool = False,
    hard_reasons: tuple[str, ...] = (),
) -> RankingCandidate:
    return RankingCandidate(
        plan_id=plan_id,
        feasibility_status=status,
        validation_source=source,
        additional_cost_myr=Decimal(cost),
        delivery_delay_minutes=delay,
        affected_commitment_ids=affected,
        operational_disruption_level=Decimal(disruption),
        supplier_uncertainty_level=Decimal(supplier_uncertainty),
        customer_confirmation_required=confirmation,
        hard_constraint_reasons=hard_reasons,
    )


def test_score_breakdown_uses_decimal_and_all_six_policy_criteria() -> None:
    prefs = BusinessPreferences(
        cost_weight=Decimal(2),
        delay_weight=Decimal(4),
        affected_commitments_weight=Decimal(5),
        operational_disruption_weight=Decimal(3),
        supplier_uncertainty_weight=Decimal(4),
        customer_confirmation_weight=Decimal(3),
    )
    candidate = _candidate(
        "plan_a",
        cost="150.50",
        delay=720,
        affected=("com_1", "com_2", "com_2"),
        disruption="2",
        supplier_uncertainty="3",
        confirmation=True,
    )

    score = score_candidate(candidate, prefs)

    assert score.additional_cost_myr == Decimal("150.50")
    assert score.affected_commitment_count == 2
    assert score.cost_score == Decimal("3.01")
    assert score.delay_score == Decimal("2.00")
    assert score.affected_commitments_score == Decimal("10.00")
    assert score.operational_disruption_score == Decimal("6.00")
    assert score.supplier_uncertainty_score == Decimal("12.00")
    assert score.customer_confirmation_score == Decimal("3.00")
    assert score.total_score == Decimal("36.01")


@pytest.mark.parametrize(
    ("candidate", "preferences", "reason"),
    [
        (_candidate("hard", hard_reasons=("LOCKED_RESERVATION",)), BusinessPreferences(), "LOCKED_RESERVATION"),
        (_candidate("infeasible", status=FeasibilityState.INFEASIBLE), BusinessPreferences(), "P2_MARKED_INFEASIBLE"),
        (_candidate("unknown", status=FeasibilityState.UNKNOWN), BusinessPreferences(), "FEASIBILITY_UNKNOWN"),
        (
            _candidate("over_cost", cost="101"),
            BusinessPreferences(max_extra_cost=Decimal(100)),
            "EXCEEDS_OWNER_MAX_EXTRA_COST",
        ),
    ],
)
def test_hard_gates_precede_ranking_and_preserve_exclusion_reason(candidate, preferences, reason) -> None:
    decision = rank_candidates([candidate], preferences)[candidate.plan_id]
    assert decision.rank is None
    assert decision.score_breakdown is None
    assert decision.recommended is False
    assert reason in decision.exclusion_reasons


def test_conditional_candidate_is_ranked_with_review_only_recommendation_qualification() -> None:
    candidate = _candidate(
        "conditional",
        status=FeasibilityState.CONDITIONAL,
        source=ValidationSource.TEST_DOUBLE_VALIDATED,
        supplier_uncertainty="5",
    )

    decision = rank_candidates([candidate], BusinessPreferences())[candidate.plan_id]

    assert decision.rank == 1
    assert decision.score_breakdown is not None
    assert decision.recommended is True
    assert decision.recommendation_label == "RECOMMENDED_UNDER_POLICY"
    assert decision.recommendation_qualification == "TEST_DOUBLE_REVIEW_ONLY"
    assert "not approval or execution authorization" in decision.recommendation_reason


def test_deterministic_tie_break_is_independent_of_input_order() -> None:
    first = _candidate("plan_b")
    second = _candidate("plan_a")
    preferences = BusinessPreferences()

    decisions_forward = rank_candidates([first, second], preferences)
    decisions_reverse = rank_candidates([second, first], preferences)

    assert decisions_forward["plan_a"].rank == decisions_reverse["plan_a"].rank == 1
    assert decisions_forward["plan_b"].rank == decisions_reverse["plan_b"].rank == 2
    assert decisions_forward["plan_a"].recommended is True
    assert decisions_reverse["plan_a"].recommended is True


def test_business_preference_weights_can_change_candidate_order() -> None:
    cost_sensitive = rank_candidates(
        [_candidate("costly_fast", cost="100"), _candidate("cheap_slow", delay=1440)],
        BusinessPreferences(cost_weight=Decimal(10), delay_weight=Decimal(1)),
    )
    delay_sensitive = rank_candidates(
        [_candidate("costly_fast", cost="100"), _candidate("cheap_slow", delay=1440)],
        BusinessPreferences(cost_weight=Decimal(1), delay_weight=Decimal(10)),
    )

    assert cost_sensitive["cheap_slow"].rank == 1
    assert delay_sensitive["costly_fast"].rank == 1


def test_service_carries_assessment_snapshot_commitment_and_reasons_into_ranked_plans() -> None:
    class CandidateImpactEvaluator:
        def evaluate(self, snapshot, proposed_changes, commitment):
            return FeasibilityResult(
                status=FeasibilityState.CONDITIONAL,
                solver_status="COMPLETED",
                constraints=["SUPPLIER_CONFIRMATION_PENDING"],
                evidence_refs=["ev_p2_001"],
                assumptions=["Candidate-specific supplier status is pending."],
                validation_source=ValidationSource.TEST_DOUBLE_VALIDATED,
                affected_commitment_ids=["com_001"],
            )

    planner = RecoveryPlanner(repository=RecoveryRepository(), evaluator=CandidateImpactEvaluator())
    case = planner.generate("tenant_demo_01", "com_001", expected_commitment_version=3)

    assert case.status == RecoveryCaseStatus.OPTIONS_READY
    for plan in case.plans:
        assert plan.based_on_assessment_id == "fa_001"
        assert plan.snapshot_version == case.operational_snapshot.snapshot_version == 142
        assert plan.evaluation.commitment_version == case.commitment_version == 3
        assert plan.evaluation.affected_commitment_ids == ["com_001"]
        assert "ev_p2_001" in plan.evaluation.evidence_refs
        assert "Candidate-specific supplier status is pending." in plan.evaluation.assumptions
        assert plan.feasibility_status == FeasibilityState.CONDITIONAL


def test_service_excludes_conditional_results_with_p2_hard_constraints() -> None:
    class HardConstraintEvaluator:
        def evaluate(self, snapshot, proposed_changes, commitment):
            return SimpleNamespace(
                status=FeasibilityState.CONDITIONAL,
                solver_status="COMPLETED",
                constraints=[
                    {
                        "code": "RESERVATION_LOCK",
                        "resource_id": "PACKAGING",
                        "severity": "HARD",
                    }
                ],
                evidence_refs=["ev_lock_001"],
                assumptions=[],
                affected_commitment_ids=["com_001"],
            )

    planner = RecoveryPlanner(
        repository=RecoveryRepository(),
        evaluator=P2FeasibilityAdapter(HardConstraintEvaluator()),
    )
    case = planner.generate("tenant_demo_01", "com_001", expected_commitment_version=3)

    assert case.status == RecoveryCaseStatus.NO_SAFE_PLAN
    assert all(plan.rank is None for plan in case.plans)
    assert all(plan.score_breakdown is None for plan in case.plans)
    assert all(plan.recommended is False for plan in case.plans)
    assert all(plan.evaluation.hard_constraint_reasons == ["RESERVATION_LOCK:PACKAGING"] for plan in case.plans)
