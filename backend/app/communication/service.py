"""Communication request intake; retains the Commit 01 pure inspection helper."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.dependencies import ACTOR_ROLES, RequestContext
from app.core.errors import DomainError
from app.core.events import CoreEventType, create_domain_event
from app.core.models import (
    AuditEventRecord, CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord,
)
from app.core.outbox import to_domain_event
from app.core.schemas import CommitmentTerms, CommunicationChannel, DomainEvent

from .repository import CommunicationRequestRepository, OutboundRepository
from .schemas import (
    CommunicationRequestView, CreateCommunicationRequest, RecoveryCommunicationReference,
    RequestAuthorization, RequestStatus,
)


def inspect_recovery_communication_event(
    event: DomainEvent,
    *,
    expected_tenant_id: str,
) -> RecoveryCommunicationReference:
    """Validate reference shape against a server-resolved tenant, without any IO.

    This is NOT a subscriber, freshness check, identity verifier or approval gate.
    Current authority must be resolved by future P3/P5 adapters before any command.
    Only known references are projected; additional payload data is not forwarded.
    """
    if not expected_tenant_id.strip():
        raise DomainError("TENANT_REQUIRED", "A resolved tenant is required", status_code=400)
    if event.tenant_id != expected_tenant_id:
        raise DomainError("TENANT_MISMATCH", "Event tenant does not match context", status_code=403)
    if event.event_type != CoreEventType.RECOVERY_COMMUNICATION_REQUESTED.value:
        raise DomainError(
            "UNSUPPORTED_COMMUNICATION_EVENT", "Unexpected communication event type",
            status_code=422,
        )
    if event.schema_version != 1:
        raise DomainError(
            "UNSUPPORTED_EVENT_SCHEMA", "Unsupported event schema version", status_code=422,
        )
    if not event.commitment_id or event.payload.get("commitment_id") != event.commitment_id:
        raise DomainError(
            "COMMITMENT_ID_MISMATCH", "Event envelope and payload targets must match",
            status_code=422,
        )
    try:
        return RecoveryCommunicationReference.model_validate({
            "source_event_id": event.event_id,
            "tenant_id": event.tenant_id,
            "correlation_id": event.correlation_id,
            "causation_id": event.causation_id,
            "occurred_at": event.occurred_at,
            "commitment_id": event.commitment_id,
            "commitment_version": event.commitment_version,
            "plan_id": event.payload.get("plan_id"),
            "plan_version": event.payload.get("plan_version"),
            "proposal_id": event.payload.get("proposal_id"),
            "proposal_version": event.payload.get("proposal_version"),
        })
    except ValidationError as exc:
        # Do not copy arbitrary payload values into API errors or logs.
        raise DomainError(
            "INVALID_COMMUNICATION_REFERENCE", "Event contains missing or invalid references",
            status_code=422,
        ) from exc


class RequestAuthority(Protocol):
    """P3/P5 integration port, not implemented by a production test double.

    Must authorize this actor to create this request and read real approval evidence,
    versioned terms and optional verified recipient/channel data. Raise DomainError
    on policy denial; return None if approval evidence cannot be established.
    Query through the supplied Session without committing or mutating Core records.
    """

    def authorize_request(
        self, db: Session, context: RequestContext, reference: RecoveryCommunicationReference,
        terms: CommitmentTerms,
    ) -> RequestAuthorization | None: ...


@dataclass(frozen=True)
class CurrentCommunicationBasis:
    """Current Core facts only; NOT approval, authentication, consent or expiry proof."""

    reference: RecoveryCommunicationReference
    terms: CommitmentTerms
    order_id: str
    customer_id: str
    proposal_evidence_refs: tuple[str, ...]


def _check_authority_availability(authority) -> None:
    # Optional integration preflight; it can only block, never grant permission.
    # Legacy adapters still implement the existing action-specific Protocols.
    check = getattr(authority, "check_availability", None)
    if check is not None:
        check()


def _require_context(context: RequestContext) -> None:
    if not context.tenant_id.strip():
        raise DomainError("TENANT_REQUIRED", "A resolved tenant is required", status_code=400)
    if ACTOR_ROLES.get(context.actor_id) != context.actor_role:
        raise DomainError("FORBIDDEN", "Unknown or inconsistent demo actor", status_code=403)


def _fail(code: str, message: str, status_code: int = 409) -> None:
    raise DomainError(code, message, status_code=status_code)


class CommunicationRequestService:
    """Owns its request-scoped transaction; do not wrap Core's committing commands.

    Reads Core records but only writes P4 records and the existing audit/outbox tables.
    No schema creation, inbound parsing, sending or Commitment mutation occurs.
    """

    def __init__(self, db: Session, authority: RequestAuthority | None = None):
        self.db = db
        self.repository = CommunicationRequestRepository(db)
        self.authority = authority

    def create(
        self, context: RequestContext, command: CreateCommunicationRequest,
        *, now: datetime | None = None,
    ) -> CommunicationRequestView:
        _require_context(context)
        if self.authority is None:
            _fail(
                "COMMUNICATION_AUTHORITY_UNAVAILABLE",
                "P5 must configure request creation policy and trusted approval reader", 503,
            )
        _check_authority_availability(self.authority)
        current_time = now if now is not None else datetime.now(timezone.utc)
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            _fail("TIMEZONE_REQUIRED", "now must include a UTC offset", 422)
        # The same transaction locks the commitment/proposal on PostgreSQL. Unique
        # constraints remain the final guard. A collision is revalidated once after rollback.
        for attempt in range(2):
            try:
                result = self._create_once(context, command, current_time)
                self.db.commit()
                return result
            except IntegrityError as exc:
                self.db.rollback()
                if attempt:
                    raise DomainError(
                        "COMMUNICATION_REQUEST_CONFLICT", "Concurrent request conflict", status_code=409,
                    ) from exc
            except SQLAlchemyError as exc:
                self.db.rollback()
                raise DomainError(
                    "COMMUNICATION_PERSISTENCE_UNAVAILABLE",
                    "Communication storage unavailable; verify P5 migration and database", status_code=503,
                ) from exc
            except Exception:
                self.db.rollback()
                raise
        raise AssertionError("unreachable")

    def resolve_current(
        self, context: RequestContext, command: CreateCommunicationRequest, now: datetime,
        *, authorize: Callable[
            [Session, RequestContext, RecoveryCommunicationReference, CommitmentTerms],
            RequestAuthorization | None,
        ] | None = None,
    ) -> tuple[RecoveryCommunicationReference, CommitmentTerms, RequestAuthorization, str, list[str]]:
        """Read/lock current authority without creating a request or committing.

        Shared by request intake and drafting. The caller owns commit/rollback and
        must supply its action-specific authorization callback when not creating.
        """
        _require_context(context)
        if authorize is None:
            if self.authority is None:
                _fail("COMMUNICATION_AUTHORITY_UNAVAILABLE", "Trusted authority is required", 503)
            _check_authority_availability(self.authority)
            authorize = self.authority.authorize_request
        basis = self.read_current_basis(context, command, now)
        ref, terms = basis.reference, basis.terms
        authorization = authorize(
            self.db, context, ref.model_copy(deep=True), terms.model_copy(deep=True),
        )
        if authorization is None:
            _fail("APPROVAL_EVIDENCE_REQUIRED", "Trusted approval evidence is required", 403)
        if not isinstance(authorization, RequestAuthorization):
            _fail("COMMUNICATION_AUTHORITY_INVALID", "Invalid authority adapter result", 503)
        # Validate a fresh copy: callers cannot bypass the schema with model_construct.
        try:
            authorization = RequestAuthorization.model_validate(authorization.model_dump())
        except ValidationError as exc:
            raise DomainError(
                "COMMUNICATION_AUTHORITY_INVALID", "Invalid authority evidence", status_code=503,
            ) from exc
        if authorization.reference != ref:
            _fail("AUTHORIZATION_SCOPE_MISMATCH", "Approval does not bind this event and versions", 403)
        if authorization.approved_terms != terms:
            _fail("APPROVED_TERMS_MISMATCH", "Proposal terms differ from approved terms")
        if authorization.approval_expires_at <= now:
            _fail("APPROVAL_EXPIRED", "Request approval has expired")
        if authorization.proposal_expires_at is not None and authorization.proposal_expires_at <= now:
            _fail("PROPOSAL_EXPIRED", "Proposal has expired")
        if authorization.recipient_customer_id not in (None, basis.customer_id):
            _fail("RECIPIENT_MISMATCH", "Recipient is linked to a different customer", 403)

        return ref, terms, authorization, basis.order_id, list(basis.proposal_evidence_refs)

    def read_current_basis(
        self, context: RequestContext, command: CreateCommunicationRequest, now: datetime,
    ) -> CurrentCommunicationBasis:
        """Read/lock real Core facts using the caller's Session; no authorization.

        Deliberately does not promote an ACTIVE proposal, an outbox row or generic
        audit evidence to manager approval or trusted source provenance. The Core
        schema currently cannot prove those facts. No commit, rollback or mutation.
        The caller owns the transaction and must separately verify authority.
        """
        _require_context(context)
        if now.tzinfo is None or now.utcoffset() is None:
            _fail("TIMEZONE_REQUIRED", "now must include a UTC offset", 422)
        source = self.db.scalar(select(OutboxEventRecord).where(
            OutboxEventRecord.event_id == command.source_event_id,
            OutboxEventRecord.tenant_id == context.tenant_id,
        ).execution_options(populate_existing=True))
        if source is None:
            _fail("SOURCE_EVENT_NOT_FOUND", "Source event not found in current tenant", 404)
        ref = inspect_recovery_communication_event(
            to_domain_event(source), expected_tenant_id=context.tenant_id,
        )
        commitment = self.db.scalar(select(CommitmentRecord).where(
            CommitmentRecord.tenant_id == context.tenant_id,
            CommitmentRecord.commitment_id == ref.commitment_id,
        ).with_for_update().execution_options(populate_existing=True))
        if commitment is None:
            _fail("COMMITMENT_NOT_FOUND", "Commitment not found", 404)
        if commitment.commitment_version != ref.commitment_version:
            _fail("COMMITMENT_VERSION_CONFLICT", "Source event uses a stale commitment version")
        proposal = self.db.scalar(select(CommitmentProposalRecord).where(
            CommitmentProposalRecord.tenant_id == context.tenant_id,
            CommitmentProposalRecord.proposal_id == ref.proposal_id,
        ).with_for_update().execution_options(populate_existing=True))
        if proposal is None:
            _fail("PROPOSAL_NOT_FOUND", "Proposal not found in current tenant", 404)
        if proposal.commitment_id != ref.commitment_id:
            _fail("COMMITMENT_ID_MISMATCH", "Proposal targets a different commitment", 422)
        if proposal.proposal_version != ref.proposal_version:
            _fail("STALE_PROPOSAL_VERSION", "Proposal version does not match event")
        latest = self.db.scalars(select(CommitmentProposalRecord).where(
            CommitmentProposalRecord.tenant_id == context.tenant_id,
            CommitmentProposalRecord.commitment_id == ref.commitment_id,
        ).order_by(CommitmentProposalRecord.proposal_version.desc()).execution_options(populate_existing=True)).all()
        if not latest or latest[0].proposal_version != ref.proposal_version:
            _fail("STALE_PROPOSAL_VERSION", "A newer proposal exists")
        if sum(p.proposal_version == ref.proposal_version for p in latest) != 1:
            _fail("AMBIGUOUS_PROPOSAL_VERSION", "Proposal version is not unique for commitment")
        if proposal.status != "ACTIVE" or commitment.agreement_state != "OFFERED":
            _fail("PROPOSAL_NOT_ELIGIBLE", "Proposal must be ACTIVE on an OFFERED commitment")
        if not proposal.revised_terms:
            _fail("APPROVED_TERMS_REQUIRED", "Explicit proposal terms are required", 422)
        try:
            terms = CommitmentTerms.model_validate(proposal.revised_terms)
        except ValidationError as exc:
            raise DomainError("INVALID_PROPOSAL_TERMS", "Proposal terms are invalid", status_code=422) from exc
        if terms.deadline is None:
            _fail("INVALID_PROPOSAL_TERMS", "Proposal delivery deadline is required for communication", 422)
        if terms.deadline <= now:
            _fail("PROPOSED_DEADLINE_PASSED", "Proposal delivery deadline has passed")
        return CurrentCommunicationBasis(
            reference=ref, terms=terms, order_id=commitment.order_id,
            customer_id=commitment.customer_id, proposal_evidence_refs=tuple(proposal.evidence_refs),
        )

    def _create_once(
        self, context: RequestContext, command: CreateCommunicationRequest, now: datetime,
    ) -> CommunicationRequestView:
        ref, terms, authorization, _, proposal_evidence = self.resolve_current(context, command, now)

        existing = self.repository.by_event(ref.tenant_id, ref.source_event_id)
        if existing is None:
            existing = self.repository.by_proposal(ref)
        if existing is not None:
            view = self.repository.view(existing)
            fields = ("tenant_id", "commitment_id", "plan_id", "plan_version", "proposal_id", "proposal_version")
            if any(getattr(view.reference, key) != getattr(ref, key) for key in fields):
                _fail("IDEMPOTENCY_CONFLICT", "Source or proposal was rebound to different plan terms")
            if view.proposed_terms != terms:
                _fail("IDEMPOTENCY_CONFLICT", "Proposal terms changed without a new version")
            self._ensure_source(view.communication_id, ref)
            return view

        reasons = []
        if authorization.proposal_expires_at is None:
            reasons.append("PROPOSAL_EXPIRY_REQUIRED")
        if not (
            authorization.recipient_identity_id and authorization.recipient_evidence_refs
            and authorization.recipient_customer_id is not None
        ):
            reasons.append("VERIFIED_RECIPIENT_REQUIRED")
        if authorization.channel in (None, CommunicationChannel.UNKNOWN) or not authorization.channel_evidence_refs:
            reasons.append("AUTHORIZED_CHANNEL_REQUIRED")
        expiry = (
            min(authorization.proposal_expires_at, authorization.approval_expires_at)
            if authorization.proposal_expires_at is not None else None
        )
        view = CommunicationRequestView(
            communication_id=f"comm_{uuid4().hex}", reference=ref,
            request_status=RequestStatus.BLOCKED if reasons else RequestStatus.READY_FOR_DRAFTING,
            blocking_reasons=reasons, proposed_terms=terms,
            approval_evidence_refs=authorization.approval_evidence_refs,
            approval_expires_at=authorization.approval_expires_at,
            proposal_evidence_refs=proposal_evidence,
            recipient_identity_id=authorization.recipient_identity_id,
            recipient_evidence_refs=authorization.recipient_evidence_refs,
            channel=authorization.channel, channel_evidence_refs=authorization.channel_evidence_refs,
            expires_at=expiry,
            created_by=context.actor_id, created_at=now,
        )
        self.repository.add(view)
        self._ensure_source(view.communication_id, ref)
        # Use existing audit/outbox primitives without touching authoritative states.
        event = create_domain_event(
            event_type="communication.requested", tenant_id=ref.tenant_id,
            commitment_id=ref.commitment_id, commitment_version=ref.commitment_version,
            correlation_id=ref.correlation_id, causation_id=ref.source_event_id, occurred_at=now,
            payload={"communication_id": view.communication_id, "proposal_id": ref.proposal_id,
                     "proposal_version": ref.proposal_version, "request_status": view.request_status.value},
        )
        self.db.add(OutboxEventRecord(
            event_id=event.event_id, tenant_id=event.tenant_id, event_type=event.event_type,
            commitment_id=event.commitment_id, commitment_version=event.commitment_version,
            correlation_id=event.correlation_id, causation_id=event.causation_id,
            occurred_at=event.occurred_at, payload=event.payload, attempts=0, status="PENDING",
        ))
        self.db.add(AuditEventRecord(
            audit_id=f"audit_{uuid4().hex}", tenant_id=ref.tenant_id,
            commitment_id=ref.commitment_id, event_type=event.event_type,
            actor_id=context.actor_id, actor_role=context.actor_role, dimension="communication",
            previous_state=None, new_state=event.payload,
            evidence_refs=authorization.approval_evidence_refs, reason="Communication request intake",
            correlation_id=ref.correlation_id, causation_id=ref.source_event_id, occurred_at=now,
        ))
        self.db.flush()
        return view

    def _ensure_source(self, communication_id: str, ref: RecoveryCommunicationReference) -> None:
        if self.repository.by_event(ref.tenant_id, ref.source_event_id) is None:
            self.repository.add_source(communication_id, ref)

    def get(self, context: RequestContext, communication_id: str) -> CommunicationRequestView:
        _require_context(context)
        try:
            record = self.repository.get(context.tenant_id, communication_id)
            if record is None:
                _fail("COMMUNICATION_NOT_FOUND", "Communication request not found", 404)
            return self._with_outbound(self.repository.view(record))
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise DomainError(
                "COMMUNICATION_PERSISTENCE_UNAVAILABLE", "Communication storage unavailable", status_code=503,
            ) from exc

    def list(
        self, context: RequestContext, *, commitment_id: str | None = None,
        request_status: RequestStatus | None = None,
    ) -> list[CommunicationRequestView]:
        _require_context(context)
        try:
            return [self._with_outbound(self.repository.view(record)) for record in self.repository.list(
                context.tenant_id, commitment_id, request_status,
            )]
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise DomainError(
                "COMMUNICATION_PERSISTENCE_UNAVAILABLE", "Communication storage unavailable", status_code=503,
            ) from exc

    def _with_outbound(self, view: CommunicationRequestView) -> CommunicationRequestView:
        # Read-only display projection; intake's immutable snapshot is untouched.
        try:
            with self.db.begin_nested():
                statuses = {row.status for row in OutboundRepository(self.db).list(
                    view.reference.tenant_id, view.communication_id)}
            status = next((s for s in ("SENT", "FAILED", "DELIVERY_UNKNOWN", "QUEUED") if s in statuses), None)
            return view.model_copy(update={"outbound_status": status})
        except SQLAlchemyError:
            return view.model_copy(update={"outbound_status": None})
