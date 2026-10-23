"""Deterministic advisory retrieval after evidence and policy gates."""

from datetime import timedelta

from .models import (
    CONTEXT_FIELDS,
    CurrentSituation,
    DecisionMemoryCase,
    Match,
    OutcomeClass,
    RetrievalPolicy,
    RetrievalResult,
    SourceMode,
)

VERIFIED = {OutcomeClass.VERIFIED_SUCCESS, OutcomeClass.VERIFIED_FAILURE}


def retrieve(
    current: CurrentSituation,
    cases: tuple[DecisionMemoryCase, ...],
    policy: RetrievalPolicy | None,
    *,
    live: bool,
) -> RetrievalResult:
    if not current.evidence_refs or not current.context_schema:
        return RetrievalResult(status="CONTEXT_UNVERIFIED", eligible_count=0)
    if not set(dict(current.context)) <= CONTEXT_FIELDS[current.domain]:
        return RetrievalResult(status="CONTEXT_UNVERIFIED", eligible_count=0)
    if policy is None or (live and policy.test_only):
        return RetrievalResult(status="POLICY_NOT_APPROVED", eligible_count=0)
    if (
        policy.tenant_id != current.tenant_id
        or policy.domain != current.domain
        or not policy.effective_at <= current.as_of < policy.expires_at
    ):
        return RetrievalResult(status="POLICY_NOT_APPROVED", eligible_count=0)
    context = dict(current.context)
    if not set(policy.required_attributes) <= context.keys():
        return RetrievalResult(status="CONTEXT_UNVERIFIED", eligible_count=0)
    if not set(policy.permitted_dimensions) <= CONTEXT_FIELDS[current.domain]:
        return RetrievalResult(status="POLICY_NOT_APPROVED", eligible_count=0)
    if len(cases) > policy.max_candidates:
        return RetrievalResult(status="SOURCE_INCOMPLETE", eligible_count=0)
    eligible = []
    seen_decisions = set()
    stale = False
    for case in cases:
        if case.tenant_id != current.tenant_id or case.decision_domain != current.domain:
            continue
        if (
            case.context_schema != current.context_schema
            or case.outcome_verification_status not in VERIFIED
        ):
            continue
        if live and case.integration_mode != SourceMode.LIVE:
            continue
        if (
            not case.sme_actor_ref
            or not case.outcome_ref
            or not case.outcome_timestamp
            or (policy.required_outcome_evidence and not case.outcome_evidence_refs)
        ):
            continue
        if case.source_watermark > current.as_of or case.observed_as_of > current.as_of:
            continue
        if current.as_of - case.outcome_timestamp > timedelta(days=policy.max_age_days):
            stale = True
            continue
        if dict(case.hard_constraints) != dict(current.hard_constraints):
            continue
        if not set(policy.required_attributes) <= dict(case.context).keys():
            continue
        if case.sme_decision_ref in seen_decisions:
            continue
        seen_decisions.add(case.sme_decision_ref)
        eligible.append(case)
    if len(eligible) < policy.minimum_eligible_cases:
        return RetrievalResult(
            status="STALE_HISTORY" if stale and not eligible else "INSUFFICIENT_CASE_HISTORY",
            eligible_count=len(eligible),
        )
    matches = []
    for case in eligible:
        past = dict(case.context)
        matching = tuple(
            k for k in policy.permitted_dimensions if k in context and past.get(k) == context[k]
        )
        differing = tuple(
            k
            for k in policy.permitted_dimensions
            if k in context and k in past and past[k] != context[k]
        )
        unknown = tuple(k for k in policy.permitted_dimensions if k not in context or k not in past)
        if not matching:
            continue
        matches.append(
            Match(
                memory_case_id=case.memory_case_id,
                domain=case.decision_domain,
                case_version=case.case_version,
                selected_historical_alternative=case.selected_alternative_ref,
                historical_decision_ref=case.sme_decision_ref,
                historical_outcome_class=case.outcome_verification_status,
                actual_outcome_ref=case.outcome_ref,
                verified_evidence_refs=case.outcome_evidence_refs,
                matching_attributes=matching,
                differing_attributes=differing,
                unknown_attributes=unknown,
                reason_codes=("HARD_CONSTRAINTS_MATCH", "VERIFIED_OUTCOME"),
                source_freshness=case.source_watermark,
                evidence_maturity=case.evidence_maturity,
            )
        )
    matches.sort(
        key=lambda m: (
            -len(m.matching_attributes),
            len(m.differing_attributes),
            -m.source_freshness.timestamp(),
            m.memory_case_id,
        )
    )
    if not matches:
        return RetrievalResult(status="NO_COMPARABLE_CASES", eligible_count=len(eligible))
    return RetrievalResult(
        status="ADVISORY_ONLY",
        eligible_count=len(eligible),
        matches=tuple(matches[: policy.max_results]),
        limitations=("HISTORICAL_CORRELATION_IS_NOT_CAUSATION",),
    )
