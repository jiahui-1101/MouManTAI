from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core.schemas import FeasibilityState

from .models import BusinessPreferences, PlanScoreBreakdown, ValidationSource


@dataclass(frozen=True)
class RankingCandidate:
    plan_id: str
    feasibility_status: FeasibilityState
    validation_source: ValidationSource
    additional_cost_myr: Decimal
    delivery_delay_minutes: int
    affected_commitment_ids: tuple[str, ...]
    operational_disruption_level: Decimal
    supplier_uncertainty_level: Decimal
    customer_confirmation_required: bool
    hard_constraint_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RankingDecision:
    plan_id: str
    score_breakdown: PlanScoreBreakdown | None
    rank: int | None
    exclusion_reasons: tuple[str, ...]
    recommended: bool
    recommendation_label: str | None
    recommendation_qualification: str | None
    recommendation_reason: str | None


def score_candidate(candidate: RankingCandidate, preferences: BusinessPreferences) -> PlanScoreBreakdown:
    """Return a lower-is-better weighted score with explicit normalized units.

    Cost is scored per MYR 100, delay per 1,440 minutes, affected commitments
    per commitment, disruption and supplier uncertainty on 0–5 ordinal scales,
    and customer confirmation as 0/1. Decimal arithmetic is used throughout.
    """

    cost_score = preferences.cost_weight * candidate.additional_cost_myr / Decimal(100)
    delay_score = preferences.delay_weight * Decimal(candidate.delivery_delay_minutes) / Decimal(1440)
    affected_count = len(set(candidate.affected_commitment_ids))
    affected_score = preferences.affected_commitments_weight * Decimal(affected_count)
    disruption_score = preferences.operational_disruption_weight * candidate.operational_disruption_level
    supplier_score = preferences.supplier_uncertainty_weight * candidate.supplier_uncertainty_level
    confirmation_score = preferences.customer_confirmation_weight * Decimal(
        int(candidate.customer_confirmation_required)
    )
    total = sum(
        (cost_score, delay_score, affected_score, disruption_score, supplier_score, confirmation_score),
        Decimal(0),
    ).quantize(Decimal("0.01"))
    return PlanScoreBreakdown(
        additional_cost_myr=candidate.additional_cost_myr,
        delivery_delay_minutes=candidate.delivery_delay_minutes,
        affected_commitment_count=affected_count,
        operational_disruption_level=candidate.operational_disruption_level,
        supplier_uncertainty_level=candidate.supplier_uncertainty_level,
        customer_confirmation_required=candidate.customer_confirmation_required,
        cost_score=cost_score.quantize(Decimal("0.01")),
        delay_score=delay_score.quantize(Decimal("0.01")),
        affected_commitments_score=affected_score.quantize(Decimal("0.01")),
        operational_disruption_score=disruption_score.quantize(Decimal("0.01")),
        supplier_uncertainty_score=supplier_score.quantize(Decimal("0.01")),
        customer_confirmation_score=confirmation_score.quantize(Decimal("0.01")),
        total_score=total,
        policy_weights=preferences,
    )


def _exclusion_reasons(candidate: RankingCandidate, preferences: BusinessPreferences) -> tuple[str, ...]:
    reasons = list(dict.fromkeys(candidate.hard_constraint_reasons))
    if candidate.feasibility_status == FeasibilityState.INFEASIBLE:
        reasons.append("P2_MARKED_INFEASIBLE")
    elif candidate.feasibility_status in {FeasibilityState.UNKNOWN, FeasibilityState.NOT_ASSESSED}:
        reasons.append(f"FEASIBILITY_{candidate.feasibility_status.value}")
    if preferences.max_extra_cost is not None and candidate.additional_cost_myr > preferences.max_extra_cost:
        reasons.append("EXCEEDS_OWNER_MAX_EXTRA_COST")
    return tuple(dict.fromkeys(reasons))


def rank_candidates(
    candidates: Sequence[RankingCandidate], preferences: BusinessPreferences
) -> dict[str, RankingDecision]:
    """Apply hard gates first, score remaining candidates, then stable tie-break.

    Conditional candidates remain rankable and retain their conditions. Unknown,
    not-assessed, infeasible and hard-policy-violating candidates remain in the
    returned mapping but receive no rank or recommendation.
    """

    if len({candidate.plan_id for candidate in candidates}) != len(candidates):
        raise ValueError("plan_id values must be unique within a ranking set")

    scored: list[tuple[RankingCandidate, PlanScoreBreakdown]] = []
    decisions: dict[str, RankingDecision] = {}
    for candidate in candidates:
        exclusions = _exclusion_reasons(candidate, preferences)
        if exclusions:
            decisions[candidate.plan_id] = RankingDecision(
                plan_id=candidate.plan_id,
                score_breakdown=None,
                rank=None,
                exclusion_reasons=exclusions,
                recommended=False,
                recommendation_label=None,
                recommendation_qualification=None,
                recommendation_reason=None,
            )
            continue
        scored.append((candidate, score_candidate(candidate, preferences)))

    # Stable tie-breaks are independent of input order: score, cost, delay,
    # affected commitment count, then canonical plan_id.
    scored.sort(
        key=lambda item: (
            item[1].total_score,
            item[1].additional_cost_myr,
            item[1].delivery_delay_minutes,
            item[1].affected_commitment_count,
            item[0].plan_id,
        )
    )

    recommended_id = scored[0][0].plan_id if scored else None
    for rank, (candidate, breakdown) in enumerate(scored, start=1):
        recommended = candidate.plan_id == recommended_id
        if candidate.validation_source == ValidationSource.REAL_P2_VALIDATED:
            qualification = (
                "CONDITIONAL_REVIEW_ONLY"
                if candidate.feasibility_status == FeasibilityState.CONDITIONAL
                or candidate.supplier_uncertainty_level > 0
                or candidate.customer_confirmation_required
                else "AUTHORITATIVE_FEASIBILITY_VALIDATED"
            )
        else:
            qualification = "TEST_DOUBLE_REVIEW_ONLY"
        reason = None
        if recommended:
            reason = (
                "Lowest deterministic weighted score among candidates that pass the configured hard policy; "
                "this is a policy comparison, not approval or execution authorization."
            )
            if qualification != "AUTHORITATIVE_FEASIBILITY_VALIDATED":
                reason += f" Validation qualification: {qualification}."
        decisions[candidate.plan_id] = RankingDecision(
            plan_id=candidate.plan_id,
            score_breakdown=breakdown,
            rank=rank,
            exclusion_reasons=(),
            recommended=recommended,
            recommendation_label="RECOMMENDED_UNDER_POLICY" if recommended else None,
            recommendation_qualification=qualification if recommended else None,
            recommendation_reason=reason,
        )
    return decisions
