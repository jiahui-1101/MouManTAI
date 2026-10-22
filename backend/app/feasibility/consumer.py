"""Fail-closed P2 consumer for Core ``commitment.confirmed`` outbox events.

No production provider or subscriber is configured here. P5 must inject the
session-bound persisted source and transactional writer at integration time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import (
    AuditEventRecord,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
)
from app.core.outbox import to_domain_event
from app.core.schemas import Commitment, CommitmentTerms, DomainEvent, FeasibilityAssessment

from .api_schemas import AssessCommitmentRequest
from .history import to_core_assessment
from .ports import AssessmentWriter
from .production import EvaluationSnapshot
from .service import EvaluationResult, evaluate, evaluation_identity


SubscriberHandler = Callable[[Session, DomainEvent], Any]
TransactionalAssessmentWriter = AssessmentWriter


@dataclass(frozen=True)
class TrustedCurrentEvaluationInput:
    """Session-bound resolver output; synthetic inputs are rejected at runtime."""

    snapshot: EvaluationSnapshot
    commitment: Commitment
    source_mode: Literal["PERSISTED_OPERATIONAL", "SYNTHETIC_FIXTURE"]
    source_evidence_refs: tuple[str, ...]


class CurrentOperationalSourceProvider(Protocol):
    """P5 boundary for authenticated, complete, fresh operational evidence.

    ``resolve_current`` must bind tenant, Commitment terms and versions, validate
    source authenticity/completeness/freshness, and lock the current snapshot row
    for the caller-owned transaction. ``validate_current`` must recheck the exact
    snapshot identity/version after P2 evaluation while retaining the lock through
    the dispatcher's commit or rollback.
    """

    def resolve_current(
        self,
        session: Session,
        tenant_id: str,
        commitment_id: str,
        commitment_version: int,
    ) -> TrustedCurrentEvaluationInput: ...

    def validate_current(
        self,
        session: Session,
        tenant_id: str,
        snapshot_id: str,
        snapshot_version: int,
    ) -> None: ...


def _validated_event(value: DomainEvent | dict[str, Any]) -> DomainEvent:
    raw = value.model_dump() if isinstance(value, DomainEvent) else value
    required_identity = (
        "event_id",
        "tenant_id",
        "commitment_id",
        "commitment_version",
        "correlation_id",
    )
    if isinstance(raw, dict) and any(
        key not in raw
        or raw[key] is None
        or (isinstance(raw[key], str) and not raw[key].strip())
        for key in required_identity
    ):
        raise DomainError(
            "P2_CONFIRMED_EVENT_IDENTITY_MISSING",
            "P2 confirmed event is missing required event, tenant, commitment, version, or correlation identity",
            status_code=422,
        )
    try:
        event = DomainEvent.model_validate(raw)
    except (ValidationError, AttributeError, TypeError) as exc:
        raise DomainError(
            "P2_CONFIRMED_EVENT_INVALID",
            "P2 confirmed evaluator received an invalid Core event envelope",
            status_code=422,
        ) from exc
    if event.event_type != "commitment.confirmed":
        raise DomainError(
            "P2_CONFIRMED_EVENT_TYPE_INVALID",
            "P2 confirmed evaluator accepts only commitment.confirmed events",
            status_code=422,
        )
    if event.schema_version != 1:
        raise DomainError(
            "P2_CONFIRMED_EVENT_SCHEMA_UNSUPPORTED",
            "P2 confirmed evaluator supports Core event schema version 1",
            status_code=422,
        )
    if (
        not event.event_id.strip()
        or not event.tenant_id.strip()
        or not event.commitment_id
        or not event.commitment_id.strip()
        or event.commitment_version is None
        or not event.correlation_id.strip()
    ):
        raise DomainError(
            "P2_CONFIRMED_EVENT_IDENTITY_MISSING",
            "P2 confirmed event is missing required event, tenant, commitment, version, or correlation identity",
            status_code=422,
        )
    return event


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _validate_persisted_event(session: Session, event: DomainEvent) -> None:
    record = session.get(OutboxEventRecord, event.event_id)
    if record is None:
        raise DomainError(
            "P2_CONFIRMED_EVENT_PROVENANCE_MISSING",
            "Confirmed event has no matching persisted Core outbox record",
            status_code=409,
        )
    try:
        persisted = to_domain_event(record)
    except (ValidationError, ValueError) as exc:
        raise DomainError(
            "P2_CONFIRMED_EVENT_PROVENANCE_INVALID",
            "Persisted Core outbox record is not a valid confirmed event",
            status_code=409,
        ) from exc
    if persisted != event:
        raise DomainError(
            "P2_CONFIRMED_EVENT_PROVENANCE_MISMATCH",
            "Dispatcher event does not match its persisted Core outbox envelope",
            status_code=409,
        )


def _confirmation_evidence(
    session: Session,
    event: DomainEvent,
    commitment: CommitmentRecord,
) -> tuple[str, ...]:
    payload = event.payload
    if not isinstance(payload, dict):
        raise DomainError(
            "P2_CONFIRMATION_PROVENANCE_MISSING",
            "Confirmed event is missing its persisted confirmation reference",
            status_code=422,
        )
    proposal_id = payload.get("proposal_id")
    proposal_version = payload.get("proposal_version")
    audit_id = payload.get("audit_id")
    evidence_refs = payload.get("evidence_refs")
    if (
        payload.get("commitment_id") != event.commitment_id
        or payload.get("decision") != "ACCEPT"
        or not isinstance(proposal_id, str)
        or not proposal_id.strip()
        or type(proposal_version) is not int
        or proposal_version < 1
        or not isinstance(audit_id, str)
        or not audit_id.strip()
        or not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in evidence_refs)
        or len(evidence_refs) != len(set(evidence_refs))
    ):
        raise DomainError(
            "P2_CONFIRMATION_PROVENANCE_MISSING",
            "Confirmed event lacks valid proposal, acceptance, audit, or evidence references",
            status_code=422,
        )

    audit = session.get(AuditEventRecord, audit_id)
    proposal = session.get(CommitmentProposalRecord, (event.tenant_id, proposal_id))
    state = audit.new_state if audit is not None else None
    core_terms = commitment.terms
    if isinstance(core_terms, dict):
        core_terms = {
            key: value
            for key, value in core_terms.items()
            if key in {"sku", "quantity", "unit", "deadline", "special_instructions"}
        }
    try:
        effective_terms = CommitmentTerms.model_validate(core_terms).model_dump(mode="json")
    except (ValidationError, TypeError, ValueError):
        effective_terms = None
    if effective_terms is None or (
        proposal is not None
        and proposal.revised_terms is not None
        and not _proposal_terms_match(proposal.revised_terms, effective_terms)
    ):
        raise DomainError(
            "P2_CONFIRMATION_TERMS_MISMATCH",
            "Accepted proposal terms are missing, invalid, or differ from the confirmed Core Commitment terms",
            status_code=409,
        )

    if (
        proposal is None
        or proposal.commitment_id != event.commitment_id
        or proposal.proposal_version != proposal_version
        or proposal.status != "ACCEPTED"
        or audit is None
        or commitment.tenant_id != event.tenant_id
        or commitment.commitment_id != event.commitment_id
        or commitment.agreement_state != "CONFIRMED"
        or type(commitment.commitment_version) is not int
        or commitment.commitment_version != event.commitment_version
        or audit.tenant_id != event.tenant_id
        or audit.tenant_id != commitment.tenant_id
        or audit.commitment_id != event.commitment_id
        or audit.commitment_id != commitment.commitment_id
        or audit.event_type != "commitment.confirmed"
        or audit.dimension != "agreement"
        or audit.actor_role not in {"OWNER", "MANAGER"}
        or audit.correlation_id != event.correlation_id
        or audit.causation_id != event.causation_id
        or _aware(audit.occurred_at) != event.occurred_at
        or audit.evidence_refs != evidence_refs
        or not isinstance(state, dict)
        or state.get("agreement_state") != "CONFIRMED"
        or state.get("agreement_state") != commitment.agreement_state
        or type(state.get("commitment_version")) is not int
        or state.get("commitment_version") != event.commitment_version
        or state.get("commitment_version") != commitment.commitment_version
    ):
        raise DomainError(
            "P2_CONFIRMATION_PROVENANCE_MISMATCH",
            "Persisted Core confirmation audit does not match the event identity and evidence",
            status_code=409,
        )
    return tuple(evidence_refs)


def _proposal_terms_match(proposal_terms: Any, effective_terms: dict[str, Any]) -> bool:
    try:
        normalized = CommitmentTerms.model_validate(proposal_terms).model_dump(mode="json")
    except (ValidationError, TypeError, ValueError):
        return False
    return normalized == effective_terms


def _validate_current_input(
    resolved: TrustedCurrentEvaluationInput,
    *,
    event: DomainEvent,
    persisted_commitment: Commitment,
    now: datetime,
) -> None:
    if resolved.source_mode != "PERSISTED_OPERATIONAL":
        raise DomainError(
            "P2_SYNTHETIC_SOURCE_REJECTED",
            "Confirmed event evaluation requires a persisted operational source provider",
            status_code=503,
        )
    snapshot, commitment = resolved.snapshot, resolved.commitment
    operational = snapshot.operational
    if (
        snapshot.current_snapshot_version is None
        or snapshot.current_snapshot_version != operational.snapshot_version
        or operational.tenant_id != event.tenant_id
        or commitment.tenant_id != event.tenant_id
        or commitment.commitment_id != event.commitment_id
        or commitment.commitment_version != event.commitment_version
        or commitment.agreement_state.value != "CONFIRMED"
        or commitment.model_dump(mode="json") != persisted_commitment.model_dump(mode="json")
    ):
        raise DomainError(
            "P2_OPERATIONAL_SOURCE_BINDING_MISMATCH",
            "Current operational snapshot or commitment does not match the persisted confirmed event",
            status_code=409,
        )
    if (
        operational.validation_status.value != "VALID"
        or operational.freshness_status.value != "CURRENT"
        or operational.captured_at > now
        or snapshot.as_of > now
        or snapshot.as_of < operational.captured_at
    ):
        raise DomainError(
            "P2_OPERATIONAL_SOURCE_INCOMPLETE_OR_STALE",
            "Current operational source is incomplete, stale, or time-inconsistent",
            status_code=503,
        )

    known_refs: set[str] = set()
    for source in operational.sources:
        if (
            source.source_ref is None
            or source.valid_through is None
            or source.valid_through < now
            or source.source_ref.lower().startswith("synthetic://")
        ):
            raise DomainError(
                "P2_OPERATIONAL_SOURCE_INCOMPLETE_OR_STALE",
                "Current operational source is incomplete, stale, or synthetic",
                status_code=503,
            )
        known_refs.update(source.evidence_refs)
    if snapshot.production is not None:
        target_plans = tuple(
            plan
            for plan in snapshot.production.plans
            if plan.commitment_id == event.commitment_id
        )
        if any(plan.commitment_version != event.commitment_version for plan in target_plans):
            raise DomainError(
                "P2_OPERATIONAL_SOURCE_BINDING_MISMATCH",
                "Production plan does not match the confirmed Commitment version",
                status_code=409,
            )
        for source in snapshot.production.sources:
            if (
                source.tenant_id != event.tenant_id
                or source.valid_through < now
                or source.source_ref.lower().startswith("synthetic://")
            ):
                raise DomainError(
                    "P2_OPERATIONAL_SOURCE_INCOMPLETE_OR_STALE",
                    "Current production source is stale or synthetic",
                    status_code=503,
                )
            known_refs.update(source.evidence_refs)
    if (
        not resolved.source_evidence_refs
        or len(resolved.source_evidence_refs) != len(set(resolved.source_evidence_refs))
        or any(not ref.strip() for ref in resolved.source_evidence_refs)
        or not set(resolved.source_evidence_refs).issubset(known_refs)
    ):
        raise DomainError(
            "P2_OPERATIONAL_SOURCE_EVIDENCE_MISSING",
            "Trusted source provider did not return evidence references bound to the current snapshot",
            status_code=503,
        )


def _validate_writer_result(persisted: FeasibilityAssessment, result: EvaluationResult) -> None:
    if persisted != to_core_assessment(result):
        raise DomainError(
            "P2_ASSESSMENT_PERSISTENCE_MISMATCH",
            "Core assessment writer returned a projection that differs from the exact P2 evaluation",
            status_code=409,
        )


def create_p2_confirmed_evaluator(
    source_provider: CurrentOperationalSourceProvider | None = None,
    assessment_writer: TransactionalAssessmentWriter | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> SubscriberHandler:
    """Build an injectable dispatcher handler; unconfigured dependencies fail closed."""

    def handler(session: Session, event: DomainEvent | dict[str, Any]) -> FeasibilityAssessment:
        if source_provider is None or assessment_writer is None:
            raise DomainError(
                "P2_CONFIRMED_EVALUATOR_NOT_CONFIGURED",
                "P2 confirmed evaluator requires authoritative source and assessment writer dependencies",
                status_code=503,
            )
        validated = _validated_event(event)
        _validate_persisted_event(session, validated)
        commitment_record = session.scalar(
            select(CommitmentRecord)
            .where(
                CommitmentRecord.tenant_id == validated.tenant_id,
                CommitmentRecord.commitment_id == validated.commitment_id,
            )
            .with_for_update()
        )
        if commitment_record is None or commitment_record.agreement_state != "CONFIRMED":
            raise DomainError(
                "P2_CONFIRMED_EVENT_COMMITMENT_MISMATCH",
                "Confirmed event has no matching confirmed Core commitment",
                status_code=409,
            )
        if commitment_record.commitment_version != validated.commitment_version:
            code = (
                "P2_CONFIRMED_EVENT_STALE"
                if commitment_record.commitment_version > validated.commitment_version
                else "P2_CONFIRMED_EVENT_VERSION_MISMATCH"
            )
            raise DomainError(
                code,
                "Confirmed event does not target the exact current commitment version",
                status_code=409,
            )
        confirmation_refs = _confirmation_evidence(session, validated, commitment_record)
        if not set(confirmation_refs).issubset(set(commitment_record.evidence_refs or [])):
            raise DomainError(
                "P2_CONFIRMATION_PROVENANCE_MISMATCH",
                "Confirmation evidence is absent from the persisted Core commitment",
                status_code=409,
            )

        from app.core.service import CommitmentService

        service_context = RequestContext(
            tenant_id=validated.tenant_id,
            actor_id="service_p2_confirmed_evaluator",
            actor_role="SERVICE",
            correlation_id=validated.correlation_id,
            causation_id=validated.event_id,
        )
        persisted_commitment = CommitmentService().get(
            session, service_context, validated.commitment_id
        )
        resolved = source_provider.resolve_current(
            session,
            validated.tenant_id,
            validated.commitment_id,
            validated.commitment_version,
        )
        now = (clock or (lambda: datetime.now(timezone.utc)))()
        if now.tzinfo is None or now.utcoffset() is None:
            raise DomainError("P2_CLOCK_INVALID", "P2 evaluation clock must be offset-aware", status_code=500)
        _validate_current_input(
            resolved,
            event=validated,
            persisted_commitment=persisted_commitment,
            now=now,
        )
        try:
            resolved = TrustedCurrentEvaluationInput(
                snapshot=EvaluationSnapshot.model_validate(
                    resolved.snapshot.model_dump(exclude_computed_fields=True)
                ),
                commitment=Commitment.model_validate(resolved.commitment.model_dump()),
                source_mode=resolved.source_mode,
                source_evidence_refs=resolved.source_evidence_refs,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise DomainError(
                "P2_OPERATIONAL_SOURCE_INVALID",
                "Trusted current operational provider returned an invalid snapshot or Commitment",
                status_code=503,
            ) from exc
        _validate_current_input(
            resolved,
            event=validated,
            persisted_commitment=persisted_commitment,
            now=now,
        )
        try:
            result = evaluate(resolved.snapshot, None, persisted_commitment)
        except ValueError as exc:
            raise DomainError(
                "P2_EVALUATION_INPUT_INVALID",
                "Trusted current operational input does not match the persisted Commitment",
                status_code=409,
            ) from exc
        if (
            result.assessment_id != evaluation_identity(resolved.snapshot, None, persisted_commitment)
            or result.tenant_id != validated.tenant_id
            or result.commitment_id != validated.commitment_id
            or result.commitment_version != validated.commitment_version
            or result.snapshot_id != resolved.snapshot.operational.snapshot_id
            or result.snapshot_version != resolved.snapshot.operational.snapshot_version
            or result.assessed_at != resolved.snapshot.as_of
        ):
            raise DomainError(
                "P2_EVALUATION_RESULT_BINDING_MISMATCH",
                "P2 calculation result is not bound to the confirmed Commitment and current snapshot",
                status_code=409,
            )

        source_provider.validate_current(
            session,
            validated.tenant_id,
            resolved.snapshot.operational.snapshot_id,
            resolved.snapshot.operational.snapshot_version,
        )
        request = AssessCommitmentRequest(
            expected_commitment_version=validated.commitment_version,
            expected_snapshot_version=resolved.snapshot.operational.snapshot_version,
        )
        persisted_assessment = assessment_writer.assess(
            session,
            service_context,
            persisted_commitment,
            request,
            snapshot=resolved.snapshot,
            result=result,
            commit=False,
        )
        _validate_writer_result(persisted_assessment, result)
        return persisted_assessment

    return handler
