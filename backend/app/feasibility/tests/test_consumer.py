"""Regression tests for the confirmed-event P2 evaluator consumer."""

from datetime import datetime, timezone
from importlib import import_module
from importlib.util import find_spec
from inspect import getsource

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import (
    AuditEventRecord,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
    ResourceStockRecord,
)
from app.core.schemas import (
    CommitmentCreateRequest,
    DomainEvent,
    FeasibilityState,
    ProposalConfirmRequest,
    ProposalCreateRequest,
)
from app.core.service import CommitmentService
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.production_fixtures import build_production_example
from app.feasibility.models import SourceKind
from app.feasibility.service import evaluate, evaluation_identity


def test_confirmed_event_consumer_module_exists():
    assert find_spec("app.feasibility.consumer") is not None


def test_consumer_factory_fails_closed_without_injected_authorities():
    factory = getattr(import_module("app.feasibility.consumer"), "create_p2_confirmed_evaluator", None)
    assert callable(factory)

    handler = factory()
    with pytest.raises(DomainError, match="authoritative") as error:
        handler(None, None)

    assert error.value.code == "P2_CONFIRMED_EVALUATOR_NOT_CONFIGURED"


def test_consumer_exposes_a_session_aware_trusted_input_contract():
    module = import_module("app.feasibility.consumer")
    assert hasattr(module, "TrustedCurrentEvaluationInput")
    assert hasattr(module, "CurrentOperationalSourceProvider")
    assert hasattr(module, "TransactionalAssessmentWriter")


def test_production_consumer_has_no_synthetic_fixture_fallback():
    module = import_module("app.feasibility.consumer")
    assert "production_fixtures" not in getsource(module)
    assert "build_production_example" not in getsource(module)


def test_consumer_rejects_noncanonical_event_before_source_resolution():
    factory = import_module("app.feasibility.consumer").create_p2_confirmed_evaluator
    event = DomainEvent(
        event_id="evt_wrong_type",
        schema_version=1,
        event_type="commitment.at_risk",
        tenant_id="tenant_consumer",
        commitment_id="com_consumer",
        commitment_version=2,
        correlation_id="corr_consumer",
        occurred_at="2026-10-22T12:00:00+08:00",
    )

    with pytest.raises(DomainError) as error:
        factory(object(), object())(None, event)

    assert error.value.code == "P2_CONFIRMED_EVENT_TYPE_INVALID"


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    for model in (
        CommitmentRecord,
        CommitmentProposalRecord,
        AuditEventRecord,
        OutboxEventRecord,
        ProcessedEventRecord,
        ResourceStockRecord,
    ):
        model.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    engine.dispose()


def create_confirmed_event(session: Session):
    base_snapshot, base_commitment = build_production_example()
    tenant_id = "tenant_consumer_test"
    commitment_id = "com_consumer_test"
    context = RequestContext(
        tenant_id=tenant_id,
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_consumer_test",
    )
    service = CommitmentService()
    service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            commitment_id=commitment_id,
            order_id="ord_consumer_test",
            customer_id="cust_consumer_test",
            terms=base_commitment.terms,
            evidence_refs=["ev_request_consumer"],
        ),
    )
    service.create_proposal(
        session,
        context,
        commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_consumer_test",
            proposal_version=1,
            expected_commitment_version=1,
            reason="Confirm the current terms",
            evidence_refs=["ev_proposal_consumer"],
        ),
    )
    transition = service.confirm_proposal(
        session,
        context,
        commitment_id,
        ProposalConfirmRequest(
            proposal_id="prop_consumer_test",
            proposal_version=1,
            expected_commitment_version=2,
            decision="ACCEPT",
            evidence_refs=["ev_confirmation_consumer"],
            reason="Customer accepted the exact proposal",
            customer_identity_status="LINK_VERIFIED",
        ),
    )
    return context, transition.domain_event


class FakeSourceProvider:
    def __init__(self, resolved, *, expected_snapshot_id=None, expected_snapshot_version=None):
        self.resolved = resolved
        self.resolve_calls = []
        self.validate_calls = []
        self.drift = False
        self.expected_snapshot_id = expected_snapshot_id or resolved.snapshot.operational.snapshot_id
        self.expected_snapshot_version = expected_snapshot_version or resolved.snapshot.operational.snapshot_version

    def resolve_current(self, session, tenant_id, commitment_id, commitment_version):
        self.resolve_calls.append((session, tenant_id, commitment_id, commitment_version))
        return self.resolved

    def validate_current(self, session, tenant_id, snapshot_id, snapshot_version):
        self.validate_calls.append((session, tenant_id, snapshot_id, snapshot_version))
        if self.drift or (snapshot_id, snapshot_version) != (
            self.expected_snapshot_id,
            self.expected_snapshot_version,
        ):
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "Snapshot changed before persistence", status_code=409)


class FakeAssessmentWriter:
    def __init__(self, failure: Exception | None = None):
        self.calls = []
        self.failure = failure

    def assess(self, session, context, commitment, request, *, snapshot, result, commit=True):
        self.calls.append((session, context, commitment, request, snapshot, result, commit))
        if self.failure:
            raise self.failure
        from app.feasibility.history import to_core_assessment

        return to_core_assessment(result)


def trusted_input(session: Session, context=None, *, source_mode="PERSISTED_OPERATIONAL"):
    from app.feasibility.consumer import TrustedCurrentEvaluationInput

    if context is None:
        context, _ = create_confirmed_event(session)
    from app.core.service import CommitmentService

    commitment = CommitmentService().get(session, context, "com_consumer_test")
    snapshot, _ = build_production_example()
    data = snapshot.model_dump(exclude_computed_fields=True)
    op = data["operational"]
    op["tenant_id"] = commitment.tenant_id
    for key in (
        "sku_catalog",
        "bom_components",
        "inventory_lots",
        "reservations",
        "incoming_deliveries",
        "capacity_calendars",
        "confirmed_commitments",
        "unit_conversions",
    ):
        for row in op[key]:
            row["tenant_id"] = commitment.tenant_id
    for row in op["sources"]:
        row["tenant_id"] = commitment.tenant_id
        row["source_ref"] = f"db://{row['source_id']}"
        row["evidence_refs"] = (f"ev_{row['source_id']}",)
    target = op["confirmed_commitments"][0]
    target.update(
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=commitment.commitment_version,
    )
    prod = data["production"]
    prod["tenant_id"] = commitment.tenant_id
    for key in ("resources", "processes", "plans", "jobs"):
        for row in prod[key] or ():
            row["tenant_id"] = commitment.tenant_id
    for row in prod["sources"]:
        row["tenant_id"] = commitment.tenant_id
        row["source_ref"] = f"db://{row['source_id']}"
        row["evidence_refs"] = (f"ev_{row['source_id']}",)
    prod["plans"][0]["commitment_id"] = commitment.commitment_id
    prod["plans"] = ({
        **prod["plans"][0],
        "commitment_id": commitment.commitment_id,
        "commitment_version": commitment.commitment_version,
    },)
    resolved_snapshot = EvaluationSnapshot.model_validate(data)
    return context, TrustedCurrentEvaluationInput(
        snapshot=resolved_snapshot,
        commitment=commitment,
        source_mode=source_mode,
        source_evidence_refs=tuple(ref for source in op["sources"] for ref in source["evidence_refs"]),
    )


def test_valid_confirmed_event_evaluates_current_snapshot_and_stages_exact_result(session):
    from app.feasibility.consumer import create_p2_confirmed_evaluator
    from app.core.models import OutboxEventRecord

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    provider = FakeSourceProvider(resolved)
    writer = FakeAssessmentWriter()
    handler = create_p2_confirmed_evaluator(provider, writer)
    commits = []
    original_commit, original_rollback = session.commit, session.rollback
    session.commit = lambda: commits.append("commit")
    session.rollback = lambda: commits.append("rollback")

    result = handler(session, event)

    expected = evaluate(resolved.snapshot, None, resolved.commitment)
    assert result.assessment_id == expected.assessment_id == evaluation_identity(
        resolved.snapshot, None, resolved.commitment
    )
    assert result.status == expected.status
    assert result.status is FeasibilityState.FEASIBLE
    assert writer.calls[0][0] is session
    assert writer.calls[0][2] == resolved.commitment
    assert writer.calls[0][4] == resolved.snapshot
    assert writer.calls[0][5] == expected
    assert writer.calls[0][6] is False
    assert writer.calls[0][3].expected_commitment_version == event.commitment_version
    assert writer.calls[0][3].expected_snapshot_version == resolved.snapshot.operational.snapshot_version
    assert result.solver_status == expected.solver_status
    assert result.constraints == list(expected.constraints)
    assert result.assumptions == list(expected.assumptions)
    assert result.evidence_refs == list(expected.evidence_refs)
    assert result.assessed_at == resolved.snapshot.as_of
    assert result.affected_commitment_ids == []
    assert provider.resolve_calls == [(session, event.tenant_id, event.commitment_id, event.commitment_version)]
    assert provider.validate_calls == [(
        session,
        event.tenant_id,
        resolved.snapshot.operational.snapshot_id,
        resolved.snapshot.operational.snapshot_version,
    )]
    assert commits == []
    assert session.get(OutboxEventRecord, event.event_id).status == "PENDING"
    assert session.query(ProcessedEventRecord).count() == 0
    session.commit, session.rollback = original_commit, original_rollback


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"schema_version": 2}, "P2_CONFIRMED_EVENT_SCHEMA_UNSUPPORTED"),
        ({"event_id": ""}, "P2_CONFIRMED_EVENT_IDENTITY_MISSING"),
        ({"tenant_id": "tenant_other"}, "P2_CONFIRMED_EVENT_PROVENANCE_MISMATCH"),
        ({"commitment_id": "com_other"}, "P2_CONFIRMED_EVENT_PROVENANCE_MISMATCH"),
        ({"commitment_version": 99}, "P2_CONFIRMED_EVENT_PROVENANCE_MISMATCH"),
    ],
)
def test_event_envelope_schema_and_identity_are_bound_to_persisted_core_event(
    session, changes, expected_code
):
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    invalid_event = event.model_copy(update=changes)

    with pytest.raises(DomainError) as error:
        create_p2_confirmed_evaluator(FakeSourceProvider(resolved), FakeAssessmentWriter())(
            session, invalid_event
        )

    assert error.value.code == expected_code


def test_unconfirmed_or_stale_commitment_cannot_be_evaluated(session):
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    handler = create_p2_confirmed_evaluator(FakeSourceProvider(resolved), FakeAssessmentWriter())
    record = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    record.agreement_state = "OFFERED"
    session.flush()
    with pytest.raises(DomainError) as unconfirmed:
        handler(session, event)
    assert unconfirmed.value.code == "P2_CONFIRMED_EVENT_COMMITMENT_MISMATCH"

    record.agreement_state = "CONFIRMED"
    record.commitment_version += 1
    session.flush()
    with pytest.raises(DomainError) as stale:
        handler(session, event)
    assert stale.value.code == "P2_CONFIRMED_EVENT_STALE"


def test_confirmation_audit_and_accepted_proposal_are_required(session):
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    handler = create_p2_confirmed_evaluator(FakeSourceProvider(resolved), FakeAssessmentWriter())
    proposal = session.get(CommitmentProposalRecord, (event.tenant_id, "prop_consumer_test"))
    proposal.status = "ACTIVE"
    session.flush()

    with pytest.raises(DomainError) as proposal_error:
        handler(session, event)
    assert proposal_error.value.code == "P2_CONFIRMATION_PROVENANCE_MISMATCH"

    proposal.status = "ACCEPTED"
    audit_id = event.payload["audit_id"]
    audit = session.get(AuditEventRecord, audit_id)
    session.delete(audit)
    session.flush()
    with pytest.raises(DomainError) as audit_error:
        handler(session, event)
    assert audit_error.value.code == "P2_CONFIRMATION_PROVENANCE_MISMATCH"


def test_accepted_proposal_terms_matching_effective_core_terms_are_accepted(session):
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    proposal = session.get(CommitmentProposalRecord, (event.tenant_id, "prop_consumer_test"))
    commitment = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    proposal.revised_terms = dict(commitment.terms)
    session.flush()

    writer = FakeAssessmentWriter()
    result = create_p2_confirmed_evaluator(FakeSourceProvider(resolved), writer)(session, event)

    assert len(writer.calls) == 1
    assert writer.calls[0][5].commitment_id == event.commitment_id
    assert result.commitment_version == event.commitment_version


@pytest.mark.parametrize("proposal_terms", ["different", "incomplete"])
def test_accepted_proposal_terms_must_match_effective_core_terms(session, proposal_terms):
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    proposal = session.get(CommitmentProposalRecord, (event.tenant_id, "prop_consumer_test"))
    commitment = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    effective_terms = dict(commitment.terms)
    if proposal_terms == "different":
        effective_terms["quantity"] = "999"
    else:
        effective_terms = {"sku": effective_terms["sku"]}
    proposal.revised_terms = effective_terms
    session.flush()

    handler = create_p2_confirmed_evaluator(FakeSourceProvider(resolved), FakeAssessmentWriter())
    with pytest.raises(DomainError) as error:
        handler(session, event)

    assert error.value.code == "P2_CONFIRMATION_TERMS_MISMATCH"


@pytest.mark.parametrize(
    "audit_changes",
    [
        {"tenant_id": "tenant_other"},
        {"tenant_id": None},
        {"commitment_id": "com_other"},
        {"commitment_id": None},
        {"new_state": {"agreement_state": "OFFERED", "commitment_version": 3}},
        {"new_state": {"agreement_state": "CONFIRMED", "commitment_version": 2}},
        {"new_state": {"commitment_version": 3}},
        {"new_state": {"agreement_state": "CONFIRMED"}},
    ],
)
def test_confirmation_audit_identity_state_and_version_are_required(session, audit_changes):
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    audit = session.get(AuditEventRecord, event.payload["audit_id"])
    missing_identity = {
        field
        for field, value in audit_changes.items()
        if field in {"tenant_id", "commitment_id"} and value is None
    }
    if missing_identity:
        from sqlalchemy.orm.attributes import set_committed_value

        for field, value in audit_changes.items():
            if field in missing_identity:
                set_committed_value(audit, field, value)
            else:
                setattr(audit, field, value)
    else:
        for field, value in audit_changes.items():
            setattr(audit, field, value)
        session.flush()

    handler = create_p2_confirmed_evaluator(FakeSourceProvider(resolved), FakeAssessmentWriter())
    with pytest.raises(DomainError) as error:
        handler(session, event)

    assert error.value.code == "P2_CONFIRMATION_PROVENANCE_MISMATCH"


@pytest.mark.parametrize("source_mode", ["SYNTHETIC_FIXTURE", "PERSISTED_OPERATIONAL"])
def test_source_authority_and_snapshot_binding_fail_closed(session, source_mode):
    from app.feasibility.consumer import TrustedCurrentEvaluationInput, create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context, source_mode=source_mode)
    if source_mode == "PERSISTED_OPERATIONAL":
        invalid_op = resolved.snapshot.operational.model_copy(update={"tenant_id": "tenant_other"})
        invalid_snapshot = resolved.snapshot.model_copy(update={"operational": invalid_op})
        resolved = TrustedCurrentEvaluationInput(
            snapshot=invalid_snapshot,
            commitment=resolved.commitment,
            source_mode=resolved.source_mode,
            source_evidence_refs=resolved.source_evidence_refs,
        )
        expected_code = "P2_OPERATIONAL_SOURCE_BINDING_MISMATCH"
    else:
        expected_code = "P2_SYNTHETIC_SOURCE_REJECTED"
    provider = FakeSourceProvider(resolved)

    with pytest.raises(DomainError) as error:
        create_p2_confirmed_evaluator(provider, FakeAssessmentWriter())(session, event)

    assert error.value.code == expected_code
    assert provider.validate_calls == []


def test_stale_incomplete_and_unlinked_snapshot_evidence_are_rejected(session):
    from app.feasibility.consumer import TrustedCurrentEvaluationInput, create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    handler = create_p2_confirmed_evaluator(FakeSourceProvider(resolved), FakeAssessmentWriter())

    source = resolved.snapshot.operational.sources[0].model_copy(
        update={"valid_through": datetime(2000, 1, 1, tzinfo=timezone.utc)}
    )
    sources = (source, *resolved.snapshot.operational.sources[1:])
    stale_op = resolved.snapshot.operational.model_copy(update={"sources": sources})
    stale_snapshot = resolved.snapshot.model_copy(update={"operational": stale_op})
    stale = TrustedCurrentEvaluationInput(
        snapshot=stale_snapshot,
        commitment=resolved.commitment,
        source_mode=resolved.source_mode,
        source_evidence_refs=resolved.source_evidence_refs,
    )
    with pytest.raises(DomainError) as stale_error:
        create_p2_confirmed_evaluator(FakeSourceProvider(stale), FakeAssessmentWriter())(session, event)
    assert stale_error.value.code == "P2_OPERATIONAL_SOURCE_INCOMPLETE_OR_STALE"

    incomplete_sources = tuple(
        source
        for source in resolved.snapshot.operational.sources
        if source.kind is not SourceKind.LOGISTICS_CUTOFF
    )
    incomplete_op = resolved.snapshot.operational.model_copy(update={"sources": incomplete_sources})
    incomplete_snapshot = resolved.snapshot.model_copy(update={"operational": incomplete_op})
    incomplete = TrustedCurrentEvaluationInput(
        snapshot=incomplete_snapshot,
        commitment=resolved.commitment,
        source_mode=resolved.source_mode,
        source_evidence_refs=resolved.source_evidence_refs,
    )
    with pytest.raises(DomainError) as incomplete_error:
        create_p2_confirmed_evaluator(FakeSourceProvider(incomplete), FakeAssessmentWriter())(
            session, event
        )
    assert incomplete_error.value.code == "P2_OPERATIONAL_SOURCE_INCOMPLETE_OR_STALE"

    unlinked = TrustedCurrentEvaluationInput(
        snapshot=resolved.snapshot,
        commitment=resolved.commitment,
        source_mode=resolved.source_mode,
        source_evidence_refs=("ev_not_in_snapshot",),
    )
    with pytest.raises(DomainError) as evidence_error:
        create_p2_confirmed_evaluator(FakeSourceProvider(unlinked), FakeAssessmentWriter())(session, event)
    assert evidence_error.value.code == "P2_OPERATIONAL_SOURCE_EVIDENCE_MISSING"


def test_snapshot_version_drift_blocks_write_and_handler_does_not_own_rollback(session):
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    provider = FakeSourceProvider(resolved)
    provider.drift = True
    writer = FakeAssessmentWriter()
    handler = create_p2_confirmed_evaluator(provider, writer)
    calls = []
    original_commit, original_rollback = session.commit, session.rollback
    session.commit = lambda: calls.append("commit")
    session.rollback = lambda: calls.append("rollback")

    with pytest.raises(DomainError) as error:
        handler(session, event)

    assert error.value.code == "SNAPSHOT_VERSION_CONFLICT"
    assert writer.calls == []
    assert calls == []
    session.commit, session.rollback = original_commit, original_rollback


def test_source_provider_rejects_changed_snapshot_identity_before_write(session):
    from app.feasibility.consumer import TrustedCurrentEvaluationInput, create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    expected_snapshot_id = resolved.snapshot.operational.snapshot_id
    provider = FakeSourceProvider(resolved, expected_snapshot_id=expected_snapshot_id)
    bad_op = resolved.snapshot.operational.model_copy(update={"snapshot_id": "other-snapshot"})
    bad_snapshot = resolved.snapshot.model_copy(update={"operational": bad_op})
    provider.resolved = TrustedCurrentEvaluationInput(
        snapshot=bad_snapshot,
        commitment=resolved.commitment,
        source_mode=resolved.source_mode,
        source_evidence_refs=resolved.source_evidence_refs,
    )
    writer = FakeAssessmentWriter()

    with pytest.raises(DomainError) as error:
        create_p2_confirmed_evaluator(provider, writer)(session, event)

    assert error.value.code == "SNAPSHOT_VERSION_CONFLICT"
    assert writer.calls == []


def test_writer_failure_is_left_to_dispatcher_transaction(session):
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    failure = RuntimeError("writer unavailable")
    writer = FakeAssessmentWriter(failure=failure)
    calls = []
    original_commit, original_rollback = session.commit, session.rollback
    session.commit = lambda: calls.append("commit")
    session.rollback = lambda: calls.append("rollback")

    with pytest.raises(RuntimeError, match="writer unavailable"):
        create_p2_confirmed_evaluator(FakeSourceProvider(resolved), writer)(session, event)

    assert writer.calls[0][-1] is False
    assert calls == []
    assert session.query(ProcessedEventRecord).count() == 0
    session.commit, session.rollback = original_commit, original_rollback


@pytest.mark.parametrize("status", [FeasibilityState.INFEASIBLE, FeasibilityState.UNKNOWN])
def test_core_writer_receives_exact_infeasible_and_unknown_result_without_handler_state_mutation(
    session, monkeypatch, status
):
    module = import_module("app.feasibility.consumer")
    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    original_evaluate = module.evaluate

    def selected_status(snapshot, proposed_changes, commitment):
        return original_evaluate(snapshot, proposed_changes, commitment).model_copy(update={"status": status})

    monkeypatch.setattr(module, "evaluate", selected_status)
    writer = FakeAssessmentWriter()
    before = session.get(
        CommitmentRecord, (event.tenant_id, event.commitment_id)
    ).feasibility_state

    assessment = module.create_p2_confirmed_evaluator(FakeSourceProvider(resolved), writer)(session, event)

    assert assessment.status is status
    assert writer.calls[0][5].status is status
    assert session.get(CommitmentRecord, (event.tenant_id, event.commitment_id)).feasibility_state == (
        before
    )


def test_dispatcher_commits_core_assessment_atomically_and_duplicate_does_not_repeat_it(session):
    from app.core.feasibility_adapters import AuthoritativeAssessmentWriter
    from app.core.outbox import OutboxDispatcher
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber(
        "commitment.confirmed",
        "p2_confirmed_evaluator",
        create_p2_confirmed_evaluator(FakeSourceProvider(resolved), AuthoritativeAssessmentWriter()),
    )

    dispatcher.process_outbox_batch(session)
    processed = session.get(
        ProcessedEventRecord,
        (event.tenant_id, event.event_id, "p2_confirmed_evaluator"),
    )
    assert processed is not None
    assessment_audits = session.query(AuditEventRecord).filter(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.commitment_id == event.commitment_id,
        AuditEventRecord.event_type.in_(
            ("commitment.lifecycle_changed", "commitment.at_risk")
        ),
    ).count()
    risk_events = session.query(OutboxEventRecord).filter(
        OutboxEventRecord.tenant_id == event.tenant_id,
        OutboxEventRecord.commitment_id == event.commitment_id,
        OutboxEventRecord.event_type == "commitment.at_risk",
    ).count()

    confirmed_record = session.get(OutboxEventRecord, event.event_id)
    confirmed_record.status = "PENDING"
    confirmed_record.published_at = None
    session.commit()
    dispatcher.process_outbox_batch(session)

    assert session.get(
        ProcessedEventRecord,
        (event.tenant_id, event.event_id, "p2_confirmed_evaluator"),
    ) is not None
    assert session.query(AuditEventRecord).filter(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.commitment_id == event.commitment_id,
        AuditEventRecord.event_type.in_(
            ("commitment.lifecycle_changed", "commitment.at_risk")
        ),
    ).count() == assessment_audits
    assert session.query(OutboxEventRecord).filter(
        OutboxEventRecord.tenant_id == event.tenant_id,
        OutboxEventRecord.commitment_id == event.commitment_id,
        OutboxEventRecord.event_type == "commitment.at_risk",
    ).count() == risk_events


def test_dispatcher_rolls_back_core_writer_changes_when_consumer_fails(session):
    from app.core.feasibility_adapters import AuthoritativeAssessmentWriter
    from app.core.outbox import OutboxDispatcher
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    current = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    original_version = current.commitment_version
    baseline_audits = session.query(AuditEventRecord).filter(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.commitment_id == event.commitment_id,
        AuditEventRecord.event_type.in_(
            ("commitment.lifecycle_changed", "commitment.at_risk")
        ),
    ).count()
    actual_writer = AuthoritativeAssessmentWriter()

    class StageThenFailWriter:
        def assess(self, *args, **kwargs):
            actual_writer.assess(*args, **kwargs)
            raise RuntimeError("fail after staged Core assessment")

    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber(
        "commitment.confirmed",
        "p2_confirmed_evaluator",
        create_p2_confirmed_evaluator(FakeSourceProvider(resolved), StageThenFailWriter()),
    )

    dispatcher.process_outbox_batch(session)

    session.expire_all()
    assert session.get(CommitmentRecord, (event.tenant_id, event.commitment_id)).commitment_version == original_version
    assert session.query(AuditEventRecord).filter(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.commitment_id == event.commitment_id,
        AuditEventRecord.event_type.in_(
            ("commitment.lifecycle_changed", "commitment.at_risk")
        ),
    ).count() == baseline_audits
    assert session.get(ProcessedEventRecord, (event.tenant_id, event.event_id, "p2_confirmed_evaluator")) is None
    failed = session.get(OutboxEventRecord, event.event_id)
    assert failed.status == "FAILED"
    assert failed.attempts == 1


def test_infeasible_result_is_delegated_to_core_and_only_core_emits_risk_event(session, monkeypatch):
    from app.core.feasibility_adapters import AuthoritativeAssessmentWriter
    from app.core.outbox import OutboxDispatcher
    from app.feasibility.consumer import create_p2_confirmed_evaluator

    context, event = create_confirmed_event(session)
    _, resolved = trusted_input(session, context)
    module = import_module("app.feasibility.consumer")
    original_evaluate = module.evaluate

    def infeasible(snapshot, proposed_changes, commitment):
        return original_evaluate(snapshot, proposed_changes, commitment).model_copy(
            update={"status": FeasibilityState.INFEASIBLE}
        )

    monkeypatch.setattr(module, "evaluate", infeasible)
    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber(
        "commitment.confirmed",
        "p2_confirmed_evaluator",
        create_p2_confirmed_evaluator(FakeSourceProvider(resolved), AuthoritativeAssessmentWriter()),
    )

    dispatcher.process_outbox_batch(session)

    current = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    assert current.risk_state == "AT_RISK"
    risk_events = session.query(OutboxEventRecord).filter(
        OutboxEventRecord.tenant_id == event.tenant_id,
        OutboxEventRecord.commitment_id == event.commitment_id,
        OutboxEventRecord.event_type == "commitment.at_risk",
    ).all()
    assert len(risk_events) == 1
    assert risk_events[0].status == "PENDING"
    assert session.query(ProcessedEventRecord).filter(
        ProcessedEventRecord.tenant_id == event.tenant_id,
        ProcessedEventRecord.event_id == risk_events[0].event_id,
        ProcessedEventRecord.consumer_name == "p3.recovery_trigger.v1",
    ).count() == 0
