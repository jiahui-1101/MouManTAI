"""Read-only outcome counts with explicit denominators and limitations."""

from .models import DecisionMemoryCase, FrozenModel, OutcomeClass, SourceMode


class OutcomeInsight(FrozenModel):
    verified_count: int
    success_count: int
    failure_count: int
    unknown_count: int
    source_case_ids: tuple[str, ...]
    outcome_refs: tuple[str, ...]
    limitations: tuple[str, ...]


def summarize(cases: tuple[DecisionMemoryCase, ...]) -> OutcomeInsight:
    verified = tuple(
        c
        for c in cases
        if c.outcome_verification_status
        in (OutcomeClass.VERIFIED_SUCCESS, OutcomeClass.VERIFIED_FAILURE)
    )
    limitations = ["NO_CAUSAL_OR_OPTIMALITY_CLAIM"]
    if not verified:
        limitations.append("NO_ELIGIBLE_DENOMINATOR")
    if len(verified) < 10:
        limitations.append("SMALL_SAMPLE")
    if any(c.integration_mode == SourceMode.DEMO_ONLY for c in cases):
        limitations.append("DEMO_ONLY_NO_BUSINESS_PERFORMANCE_CLAIM")
    return OutcomeInsight(
        verified_count=len(verified),
        success_count=sum(
            c.outcome_verification_status == OutcomeClass.VERIFIED_SUCCESS for c in verified
        ),
        failure_count=sum(
            c.outcome_verification_status == OutcomeClass.VERIFIED_FAILURE for c in verified
        ),
        unknown_count=len(cases) - len(verified),
        source_case_ids=tuple(c.memory_case_id for c in verified),
        outcome_refs=tuple(c.outcome_ref for c in verified if c.outcome_ref),
        limitations=tuple(limitations),
    )
