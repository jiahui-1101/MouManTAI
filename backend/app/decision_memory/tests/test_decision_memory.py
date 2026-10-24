from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.decision_memory.assembly import assemble_case
from app.decision_memory.governance import propose_review
from app.decision_memory.lessons import summarize
from app.decision_memory.models import (
    CaseInput,
    CurrentSituation,
    Domain,
    Event,
    Evidence,
    OutcomeClass,
    RetrievalPolicy,
    SourceManifest,
    SourceMode,
)
from app.decision_memory.retrieval import retrieve
from app.decision_memory.service import DecisionMemoryService
from app.decision_memory.validation import HistoryValidationError, validate_source

T = datetime(2026, 10, 20, tzinfo=UTC)


def event(case, kind, minute, **extra):
    return Event(
        event_id=f"{case}-{kind}-{minute}",
        tenant_id="tenant-demo",
        commitment_id=f"commit-{case}",
        recovery_case_id=f"recovery-{case}",
        plan_id=f"plan-{case}",
        plan_version=1,
        source_snapshot_id="snapshot-1",
        source_snapshot_version=1,
        kind=kind,
        ref=f"ref-{case}-{kind}-{minute}",
        occurred_at=T + timedelta(minutes=minute),
        subject_id=f"commit-{case}",
        **extra,
    )


def fixture(case="A", *, outcome="SUCCESS", proof=True, customer_agreement=False):
    alternatives = (
        event(case, "ALTERNATIVE", 1, status="ALTERNATIVE_SUPPLY"),
        event(case, "ALTERNATIVE", 2, status="RESCHEDULE"),
        event(case, "ALTERNATIVE", 3, status="REVISED_DEADLINE"),
    )
    chosen = {"A": 0, "B": 1, "C": 2}[case]
    stages = (
        event(case, "SITUATION", 0, evidence_ids=(f"situation-{case}",)),
        *alternatives,
        event(
            case,
            "DECISION",
            4,
            actor_ref=f"sme-{case}",
            selected_ref=alternatives[chosen].ref,
            evidence_ids=(f"reason-{case}",),
        ),
        event(case, "APPROVAL", 5, status="APPROVED"),
        event(case, "EXECUTION", 6, status="CONFIRMED" if case == "A" else "ATTEMPTED"),
        event(case, "OUTCOME", 7, status=outcome, evidence_ids=(f"proof-{case}",) if proof else ()),
    )
    evidences = [
        Evidence(
            evidence_id=f"situation-{case}",
            owner="SYNTHETIC",
            subject_id=f"commit-{case}",
            kind="SITUATION",
            source_version=1,
            occurred_at=T,
        ),
        Evidence(
            evidence_id=f"reason-{case}",
            owner="SYNTHETIC",
            subject_id=f"commit-{case}",
            kind="HUMAN_REASON",
            source_version=1,
            occurred_at=T + timedelta(minutes=4),
        ),
    ]
    if proof:
        evidences.append(
            Evidence(
                evidence_id=f"proof-{case}",
                owner="SYNTHETIC",
                subject_id=f"commit-{case}",
                kind="BUSINESS_RESOLUTION" if case == "A" else "CUSTOMER_MESSAGE_SENT",
                source_version=1,
                occurred_at=T + timedelta(minutes=7),
                authenticated=True,
            )
        )
    return CaseInput(
        memory_case_id=f"memory-{case}",
        case_version=1,
        domain=Domain.RECOVERY,
        tenant_id="tenant-demo",
        commitment_id=f"commit-{case}",
        order_id=f"order-{case}",
        recovery_case_id=f"recovery-{case}",
        business_context_ref=f"context-{case}",
        business_context_version=1,
        context_schema="recovery-v1",
        context=(
            ("disruption", "supplier_delay"),
            ("resource", "food_packaging"),
            ("urgency", "soon" if case != "C" else "later"),
        ),
        hard_constraints=(("food_safe", "required"),),
        events=stages,
        evidence=tuple(evidences),
    )


def manifest(mode=SourceMode.DEMO_ONLY):
    return SourceManifest(
        tenant_id="tenant-demo",
        source_reader_id="test-reader",
        source_snapshot_id="snapshot-1",
        source_snapshot_version=1,
        source_version=1,
        source_watermark=T + timedelta(days=1),
        covered_time_start=T,
        covered_time_end=T + timedelta(hours=1),
        as_of=T + timedelta(days=2),
        pagination_complete=True,
        source_population_complete=True,
        integration_mode=mode,
        evidence_maturity="SYNTHETIC",
        provenance_refs=("test-fixture",),
    )


def current():
    return CurrentSituation(
        tenant_id="tenant-demo",
        domain=Domain.RECOVERY,
        situation_version=1,
        business_context_ref="context-current",
        context_schema="recovery-v1",
        context=(
            ("disruption", "supplier_delay"),
            ("resource", "food_packaging"),
            ("urgency", "soon"),
        ),
        hard_constraints=(("food_safe", "required"),),
        evidence_refs=("verified-current-context",),
        as_of=T + timedelta(days=2),
    )


def policy(minimum=1, test_only=True):
    return RetrievalPolicy(
        policy_id="test-policy",
        policy_version=1,
        tenant_id="tenant-demo",
        domain=Domain.RECOVERY,
        minimum_eligible_cases=minimum,
        required_attributes=("disruption", "resource"),
        permitted_dimensions=("disruption", "resource", "urgency"),
        max_age_days=30,
        max_candidates=10,
        max_results=3,
        retention_ref="test-retention",
        privacy_ref="test-privacy",
        approval_ref="test-approval",
        effective_at=T,
        expires_at=T + timedelta(days=30),
        test_only=test_only,
    )


def test_three_case_demo_and_fail_closed_history():
    raw = (fixture("A"), fixture("B", proof=False), fixture("C", proof=True))
    checked = validate_source(manifest(), raw)
    cases = tuple(assemble_case(c, manifest()) for c in checked)
    assert [c.outcome_verification_status for c in cases] == [
        OutcomeClass.VERIFIED_SUCCESS,
        OutcomeClass.REPORTED_ONLY,
        OutcomeClass.REPORTED_ONLY,
    ]
    assert cases[0].approval_granted and cases[0].execution_status == "CONFIRMED"
    assert cases[1].approval_granted and cases[1].execution_status == "ATTEMPTED"
    assert len(cases[0].alternatives_refs) == 3
    assert retrieve(current(), cases, policy(2), live=False).status == "INSUFFICIENT_CASE_HISTORY"
    result = retrieve(current(), cases, policy(), live=False)
    assert result.status == "ADVISORY_ONLY" and len(result.matches) == 1
    assert result.matches[0].matching_attributes == ("disruption", "resource", "urgency")
    assert (
        retrieve(current(), cases, policy(test_only=False), live=True).status
        == "INSUFFICIENT_CASE_HISTORY"
    )
    assert retrieve(current(), cases, policy(), live=True).status == "POLICY_NOT_APPROVED"
    insight = summarize(cases)
    assert (insight.verified_count, insight.success_count, insight.unknown_count) == (1, 1, 2)
    proposal = propose_review("tenant-demo", Domain.RECOVERY, insight)
    assert proposal.human_review_required and not proposal.execution_authorized
    assert "DEMO_ONLY_NO_BUSINESS_PERFORMANCE_CLAIM" in proposal.uncertainties


@pytest.mark.parametrize(
    "change,code",
    [
        ({"tenant_id": "other"}, "TENANT_MISMATCH"),
        ({"commitment_id": "wrong"}, "EVENT_ASSOCIATION_MISMATCH"),
        ({"recovery_case_id": "wrong"}, "RECOVERY_ASSOCIATION_MISMATCH"),
    ],
)
def test_source_rejects_cross_association(change, code):
    with pytest.raises(HistoryValidationError, match=code):
        validate_source(manifest(), (fixture().model_copy(update=change),))


def test_replay_and_conflict():
    case = fixture()
    repeated = case.model_copy(update={"events": case.events + (case.events[0],)})
    assert len(validate_source(manifest(), (repeated,))[0].events) == len(case.events)
    changed = case.events[0].model_copy(update={"ref": "conflicting"})
    with pytest.raises(HistoryValidationError, match="CONFLICTING_EVENT_REPLAY"):
        validate_source(manifest(), (case.model_copy(update={"events": case.events + (changed,)}),))
    with pytest.raises(HistoryValidationError, match="CONFLICTING_CASE_REPLAY"):
        validate_source(manifest(), (case, repeated))


def test_incomplete_snapshot_and_mixed_evidence():
    with pytest.raises(HistoryValidationError, match="SOURCE_INCOMPLETE"):
        validate_source(manifest().model_copy(update={"pagination_complete": False}), (fixture(),))
    with pytest.raises(HistoryValidationError, match="MIXED_SYNTHETIC_LIVE"):
        validate_source(manifest(SourceMode.LIVE), (fixture(),))


def test_plan_version_chronology_and_selection():
    case = fixture()
    events = list(case.events)
    approval_index = next(i for i, e in enumerate(events) if e.kind == "APPROVAL")
    events[approval_index] = events[approval_index].model_copy(update={"plan_version": 2})
    with pytest.raises(HistoryValidationError, match="PLAN_VERSION_MISMATCH"):
        assemble_case(case.model_copy(update={"events": tuple(events)}), manifest())
    decisions = tuple(
        e.model_copy(update={"selected_ref": "missing"}) if e.kind == "DECISION" else e
        for e in case.events
    )
    with pytest.raises(HistoryValidationError, match="INVALID_ALTERNATIVES"):
        assemble_case(case.model_copy(update={"events": decisions}), manifest())


def test_outcome_correction_conflict_and_failure():
    case = fixture()
    conflicting = event("A", "OUTCOME", 8, status="FAILURE", evidence_ids=("proof-A",))
    assert (
        assemble_case(
            case.model_copy(update={"events": case.events + (conflicting,)}), manifest()
        ).outcome_verification_status
        == OutcomeClass.CONFLICTING_EVIDENCE
    )
    corrected = conflicting.model_copy(
        update={"corrects_id": case.events[-1].event_id, "evidence_ids": ("corrected-proof",)}
    )
    new_proof = Evidence(
        evidence_id="corrected-proof",
        owner="SYNTHETIC",
        subject_id="commit-A",
        kind="BUSINESS_RESOLUTION",
        source_version=2,
        occurred_at=T + timedelta(minutes=8),
        corrects_id="proof-A",
        authenticated=True,
    )
    result = assemble_case(
        case.model_copy(
            update={"events": case.events + (corrected,), "evidence": case.evidence + (new_proof,)}
        ),
        manifest().model_copy(update={"source_version": 2}),
    )
    assert result.outcome_verification_status == OutcomeClass.VERIFIED_FAILURE
    assert result.outcome_ref == corrected.ref


def test_hard_mismatch_and_bounded_determinism():
    case = assemble_case(fixture(), manifest())
    wrong = current().model_copy(update={"hard_constraints": (("food_safe", "not_required"),)})
    assert retrieve(wrong, (case,), policy(), live=False).status == "INSUFFICIENT_CASE_HISTORY"
    assert (
        retrieve(current(), (case, case), policy(), live=False).matches[0].memory_case_id
        == "memory-A"
    )


def test_live_service_requires_server_owned_adapters():
    assert DecisionMemoryService().retrieve_similar_cases(current()).status == "SOURCE_UNAVAILABLE"

    class Identity:
        def identity(self):
            return "other-tenant", "actor"

    service = DecisionMemoryService(identity=Identity(), history=object(), authenticity=object())
    assert service.retrieve_similar_cases(current()).status == "CONTEXT_UNVERIFIED"


def test_service_demo_reader_and_missing_owner_policy():
    class Identity:
        def identity(self):
            return "tenant-demo", "manager-1"

    class History:
        def read(self, tenant_id, domain, as_of, limit):
            assert (tenant_id, domain, limit) == ("tenant-demo", "RECOVERY", 1000)
            return manifest(), (fixture(),)

    class Authenticity:
        def verify(self, source, cases):
            return source.source_reader_id == "test-reader" and bool(cases)

        def verify_current(self, situation, actor_id):
            return bool(situation.evidence_refs) and actor_id == "manager-1"

    service = DecisionMemoryService(Identity(), History(), None, Authenticity())
    assert service.retrieve_similar_cases(current()).status == "SOURCE_UNAVAILABLE"
    assert service.retrieve_similar_cases(current(), live=False).status == "POLICY_NOT_APPROVED"

    class Policy:
        def approved_policy(self, tenant_id, domain):
            return policy()

    service = DecisionMemoryService(Identity(), History(), Policy(), Authenticity())
    assert service.retrieve_similar_cases(current(), live=False).status == "ADVISORY_ONLY"
    assert service.summarize_verified_outcomes(current()) == "SOURCE_UNAVAILABLE"

    class RejectCurrent(Authenticity):
        def verify_current(self, situation, actor_id):
            return False

    denied = DecisionMemoryService(Identity(), History(), Policy(), RejectCurrent())
    assert denied.retrieve_similar_cases(current(), live=False).status == "CONTEXT_UNVERIFIED"


@pytest.mark.parametrize(
    "manifest_change,error",
    [
        ({"source_watermark": T - timedelta(days=1)}, "INVALID_WATERMARK"),
        ({"missing_source_names": ("Core",)}, "SOURCE_INCOMPLETE"),
        ({"source_snapshot_version": 2}, "SNAPSHOT_MISMATCH"),
    ],
)
def test_manifest_fail_closed(manifest_change, error):
    with pytest.raises(HistoryValidationError, match=error):
        validate_source(manifest().model_copy(update=manifest_change), (fixture(),))


def test_future_event_and_superseded_evidence_fail_closed():
    case = fixture()
    event_future = case.events[-1].model_copy(update={"occurred_at": T + timedelta(days=3)})
    with pytest.raises(HistoryValidationError, match="FUTURE_EVENT"):
        validate_source(
            manifest(), (case.model_copy(update={"events": case.events[:-1] + (event_future,)}),)
        )
    old_manifest = manifest().model_copy(update={"source_version": 0})
    with pytest.raises(HistoryValidationError, match="SUPERSEDED_SOURCE_VERSION"):
        validate_source(old_manifest, (case,))


def test_missing_human_actor_and_wrong_snapshot_are_rejected():
    case = fixture()
    changed = tuple(
        e.model_copy(update={"actor_ref": None}) if e.kind == "DECISION" else e for e in case.events
    )
    with pytest.raises(HistoryValidationError, match="UNVERIFIED_DECISION"):
        assemble_case(case.model_copy(update={"events": changed}), manifest())
    changed = tuple(
        e.model_copy(update={"source_snapshot_id": "other"}) if e.kind == "OUTCOME" else e
        for e in case.events
    )
    with pytest.raises(HistoryValidationError, match="SNAPSHOT_MISMATCH"):
        validate_source(manifest(), (case.model_copy(update={"events": changed}),))


def test_reported_claims_never_become_verified_outcomes():
    cases = tuple(assemble_case(fixture("C", proof=True), manifest()) for _ in range(1))
    assert cases[0].outcome_verification_status == OutcomeClass.REPORTED_ONLY
    assert retrieve(current(), cases, policy(), live=False).status == "INSUFFICIENT_CASE_HISTORY"
    unapproved = policy().model_copy(update={"effective_at": T + timedelta(days=3)})
    assert retrieve(current(), cases, unapproved, live=False).status == "POLICY_NOT_APPROVED"


def test_different_context_and_candidate_bound():
    case = assemble_case(fixture(), manifest())
    different = current().model_copy(
        update={
            "context": (
                ("disruption", "supplier_delay"),
                ("resource", "other"),
                ("urgency", "later"),
            )
        }
    )
    match = retrieve(different, (case,), policy(), live=False).matches[0]
    assert match.matching_attributes == ("disruption",)
    assert match.differing_attributes == ("resource", "urgency")
    unrelated = different.model_copy(
        update={"context": (("disruption", "other"), ("resource", "other"), ("urgency", "later"))}
    )
    assert retrieve(unrelated, (case,), policy(), live=False).status == "NO_COMPARABLE_CASES"
    limited = policy().model_copy(update={"max_candidates": 1})
    assert retrieve(current(), (case, case), limited, live=False).status == "SOURCE_INCOMPLETE"


def test_service_rejects_future_reader_snapshot():
    class Identity:
        def identity(self):
            return "tenant-demo", "manager-1"

    class History:
        def read(self, tenant_id, domain, as_of, limit):
            return manifest().model_copy(update={"as_of": T + timedelta(days=3)}), (fixture(),)

    class Authenticity:
        def verify(self, source, cases):
            return True

        def verify_current(self, situation, actor_id):
            return True

    service = DecisionMemoryService(Identity(), History(), None, Authenticity())
    assert service.retrieve_similar_cases(current(), live=False).status == "SOURCE_INCOMPLETE"


def test_pydantic_immutability_and_aware_time():
    with pytest.raises(ValidationError):
        current().model_copy(update={"as_of": datetime(2026, 10, 20)}).model_validate(
            {**current().model_dump(), "as_of": datetime(2026, 10, 20)}
        )
    with pytest.raises(ValidationError):
        RetrievalPolicy(**{**policy().model_dump(), "minimum_eligible_cases": 0})
