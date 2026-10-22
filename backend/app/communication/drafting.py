"""Version-safe draft preparation/retrieval. No channel adapters or message sending."""

from datetime import datetime, timezone
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import create_domain_event
from app.core.models import AuditEventRecord, OutboxEventRecord
from app.core.schemas import CommitmentTerms, CommunicationChannel

from . import templates
from .repository import MessageDraftRepository
from .schemas import (
    CommunicationSummary, CreateCommunicationRequest, MessageDraftView, PrepareDraftRequest,
    RecoveryCommunicationReference, RequestAuthorization,
)
from .service import CommunicationRequestService, _fail, _require_context


class DraftAuthority(Protocol):
    """Trusted server adapter: re-read approval/revocation and enforce action policy.

    Not an alias for create permission. Must validate actor access for this request,
    current approved plan/terms/version/expiry and verified recipient/channel evidence.
    Return None or raise DomainError for missing/revoked approval. Production is unwired.
    Use read-only queries in the passed Session; never commit/rollback or change Core
    here, so the service's currentness locks survive until draft/audit/outbox commit.
    """

    def revalidate_draft(
        self, db: Session, context: RequestContext, reference: RecoveryCommunicationReference,
        terms: CommitmentTerms, *, communication_id: str,
        action: Literal["PREPARE_DRAFT", "READ_DRAFT"],
    ) -> RequestAuthorization | None: ...


class MessageDraftService:
    """Owns a fresh request-scoped transaction; all revalidation precedes reuse."""

    def __init__(self, db: Session, authority: DraftAuthority | None = None):
        self.db = db
        self.authority = authority
        self.requests = CommunicationRequestService(db)
        self.repository = MessageDraftRepository(db)

    def summary(self, context: RequestContext, *, now: datetime | None = None) -> CommunicationSummary:
        """Read-only tenant summary, reusing READ_DRAFT policy/currentness checks.

        No sending persistence exists in this repository. Neither request snapshots
        nor generic audit/outbox status can prove a provider-confirmed send.
        """
        _require_context(context)
        checked_at = self._time(now)
        try:
            total, blocked = self.requests.repository.summary_counts(context.tenant_id)
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise DomainError(
                "COMMUNICATION_SUMMARY_UNAVAILABLE", "Communication statistics storage is unavailable", status_code=503,
            ) from exc
        try:
            reasons = {"sent": "SENDING_RECORDS_UNAVAILABLE"}
            drafted = None
            if self.authority is None:
                reasons["drafted"] = "DRAFT_REVALIDATION_UNAVAILABLE"
            else:
                try:
                    drafted = self._count_current_drafts(context, checked_at)
                except SQLAlchemyError:
                    reasons["drafted"] = "DRAFT_STORAGE_UNAVAILABLE"
                except DomainError:
                    # Includes actor READ_DRAFT denial or an unavailable adapter.
                    # A partial count must never masquerade as a complete total.
                    reasons["drafted"] = "DRAFT_VALIDITY_UNAVAILABLE"
                except ValidationError:
                    reasons["drafted"] = "DRAFT_VALIDITY_UNAVAILABLE"
            return CommunicationSummary(
                tenant_id=context.tenant_id, total=total, drafted=drafted, sent=None,
                needs_attention=blocked, checked_at=checked_at, unavailable_reasons=reasons,
            )
        finally:
            self.db.rollback()  # Release currentness locks; summary writes nothing.

    def _count_current_drafts(self, context: RequestContext, now: datetime) -> int:
        # These are authoritative rejection outcomes: the saved draft cannot be
        # used today. Unknown/infrastructure/policy errors make the metric unavailable.
        ineligible = {
            "COMMITMENT_NOT_FOUND", "PROPOSAL_NOT_FOUND", "SOURCE_EVENT_NOT_FOUND",
            "COMMUNICATION_NOT_FOUND", "COMMITMENT_VERSION_CONFLICT", "STALE_PROPOSAL_VERSION",
            "AMBIGUOUS_PROPOSAL_VERSION", "PROPOSAL_NOT_ELIGIBLE", "PROPOSED_DEADLINE_PASSED",
            "APPROVED_TERMS_REQUIRED", "APPROVAL_EVIDENCE_REQUIRED", "AUTHORIZATION_SCOPE_MISMATCH",
            "APPROVED_TERMS_MISMATCH", "APPROVAL_EXPIRED", "PROPOSAL_EXPIRED", "RECIPIENT_MISMATCH",
            "PROPOSAL_EXPIRY_REQUIRED", "VERIFIED_RECIPIENT_REQUIRED", "AUTHORIZED_CHANNEL_REQUIRED",
            "REQUEST_REFERENCE_CONFLICT", "DRAFT_REVALIDATION_REQUIRED", "DRAFT_INTEGRITY_ERROR",
        }
        valid_requests: set[str] = set()
        for record in self.repository.for_tenant(context.tenant_id):
            if record.communication_id in valid_requests:
                continue
            # Invalid persisted shape cannot be treated as a reliable numeric count.
            saved = self.repository.view(record)
            try:
                expected = self._candidate(
                    context, record.communication_id,
                    PrepareDraftRequest(language=saved.language, template_key=saved.template_key),
                    now, "READ_DRAFT",
                )
                self._verified_snapshot(record, expected)
            except DomainError as exc:
                if exc.code not in ineligible:
                    raise
                continue
            valid_requests.add(record.communication_id)
        return len(valid_requests)

    def _candidate(
        self, context: RequestContext, communication_id: str, command: PrepareDraftRequest,
        now: datetime, action: Literal["PREPARE_DRAFT", "READ_DRAFT"],
    ) -> MessageDraftView:
        _require_context(context)
        request = self.requests.get(context, communication_id)
        if request.reference.tenant_id != context.tenant_id or request.communication_id != communication_id:
            _fail("REQUEST_REFERENCE_CONFLICT", "Persisted request target is inconsistent")
        if self.authority is None:
            _fail("DRAFT_REVALIDATION_UNAVAILABLE", "Trusted draft revalidation is not configured", 503)

        def authorize(db, actor, reference, terms):
            return self.authority.revalidate_draft(
                db, actor, reference, terms, communication_id=communication_id, action=action,
            )

        ref, terms, authority, order_id, proposal_evidence = self.requests.resolve_current(
            context, CreateCommunicationRequest(source_event_id=request.reference.source_event_id),
            now, authorize=authorize,
        )
        if ref != request.reference:
            _fail("REQUEST_REFERENCE_CONFLICT", "Source references changed since request creation")
        if terms != request.proposed_terms:
            _fail("APPROVED_TERMS_MISMATCH", "Proposal terms changed without a new request/version")
        if authority.proposal_expires_at is None:
            _fail("PROPOSAL_EXPIRY_REQUIRED", "Proposal expiry must be authoritatively resolved")
        if not (
            authority.recipient_identity_id and authority.recipient_customer_id
            and authority.recipient_evidence_refs
        ):
            _fail("VERIFIED_RECIPIENT_REQUIRED", "Verified recipient evidence is required")
        if authority.channel in (None, CommunicationChannel.UNKNOWN) or not authority.channel_evidence_refs:
            _fail("AUTHORIZED_CHANNEL_REQUIRED", "Authorized channel evidence is required")
        # Terms/IDs come only from current server-side records and verified authority.
        subject, body = templates.render_message(
            language=command.language, template_key=command.template_key, channel=authority.channel,
            order_id=order_id, commitment_id=ref.commitment_id,
            proposal_id=ref.proposal_id, proposal_version=ref.proposal_version,
            communication_id=communication_id, terms=terms,
        )
        validation_hash = templates.fingerprint({
            "communication_id": communication_id, "order_id": order_id,
            "proposal_evidence_refs": proposal_evidence,
            "authority": authority.model_dump(mode="json"),
            "template_key": command.template_key, "template_version": templates.TEMPLATE_VERSION,
            "language": command.language,
        })
        return MessageDraftView(
            draft_id=f"draft_{uuid4().hex}", tenant_id=context.tenant_id,
            communication_id=communication_id, reference=ref, order_id=order_id,
            template_key=command.template_key, template_version=templates.TEMPLATE_VERSION,
            language=command.language, channel=authority.channel, subject=subject, body=body,
            approved_terms=terms, approval_evidence_refs=authority.approval_evidence_refs,
            proposal_evidence_refs=proposal_evidence,
            recipient_identity_id=authority.recipient_identity_id,
            recipient_evidence_refs=authority.recipient_evidence_refs,
            channel_evidence_refs=authority.channel_evidence_refs,
            content_hash=templates.fingerprint({"subject": subject, "body": body}),
            validation_hash=validation_hash,
            expires_at=min(authority.proposal_expires_at, authority.approval_expires_at),
            created_at=now,
        )

    @staticmethod
    def _verified_snapshot(record, expected: MessageDraftView) -> MessageDraftView:
        try:
            saved = MessageDraftRepository.view(record)
        except ValidationError as exc:
            raise DomainError("DRAFT_INTEGRITY_ERROR", "Stored draft is invalid", status_code=409) from exc
        if saved.validation_hash != expected.validation_hash:
            _fail("DRAFT_REVALIDATION_REQUIRED", "Approval, channel or template changed; prepare again")
        # Hashes alone are not approval or semantic proof. Compare with freshly
        # rendered current terms and every current metadata field as well.
        exclude = {"draft_id", "created_at"}
        if (
            saved.draft_id != record.draft_id or saved.tenant_id != record.tenant_id
            or saved.communication_id != record.communication_id
            or saved.validation_hash != record.validation_hash
            or saved.model_dump(exclude=exclude) != expected.model_dump(exclude=exclude)
        ):
            _fail("DRAFT_INTEGRITY_ERROR", "Stored draft differs from current verified content")
        return saved

    def prepare(
        self, context: RequestContext, communication_id: str, command: PrepareDraftRequest,
        *, now: datetime | None = None,
    ) -> MessageDraftView:
        current_time = self._time(now)
        for attempt in range(2):
            try:
                candidate = self._candidate(context, communication_id, command, current_time, "PREPARE_DRAFT")
                existing = self.repository.by_variant(
                    context.tenant_id, communication_id, candidate.validation_hash,
                )
                if existing is not None:
                    result = self._verified_snapshot(existing, candidate)
                else:
                    self.repository.add(candidate)
                    self._record_preparation(context, candidate)
                    result = candidate
                self.db.commit()
                return result
            except IntegrityError as exc:
                self.db.rollback()
                if attempt:
                    raise DomainError("DRAFT_CONFLICT", "Concurrent draft conflict", status_code=409) from exc
            except SQLAlchemyError as exc:
                self.db.rollback()
                raise DomainError(
                    "DRAFT_PERSISTENCE_UNAVAILABLE", "Draft storage unavailable; verify P5 migration", status_code=503,
                ) from exc
            except Exception:
                self.db.rollback()
                raise
        raise AssertionError("unreachable")

    def get(
        self, context: RequestContext, communication_id: str, draft_id: str,
        *, now: datetime | None = None,
    ) -> MessageDraftView:
        _require_context(context)
        try:
            result = self.validate_current(context, communication_id, draft_id, now=self._time(now))
            self.db.rollback()  # Release revalidation locks; retrieval never writes.
            return result
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise DomainError(
                "DRAFT_PERSISTENCE_UNAVAILABLE", "Draft storage unavailable; verify P5 migration", status_code=503,
            ) from exc
        except Exception:
            self.db.rollback()
            raise

    def validate_current(self, context: RequestContext, communication_id: str, draft_id: str,
                         *, now: datetime) -> MessageDraftView:
        """Same checks as GET, inside the caller-owned transaction; no commit/rollback."""
        _require_context(context)
        record = self.repository.get(context.tenant_id, communication_id, draft_id, lock=True)
        if record is None:
            _fail("DRAFT_NOT_FOUND", "Draft not found in current tenant/request", 404)
        try:
            saved = self.repository.view(record)
            command = PrepareDraftRequest(language=saved.language, template_key=saved.template_key)
        except ValidationError as exc:
            raise DomainError("DRAFT_INTEGRITY_ERROR", "Stored draft is invalid", status_code=409) from exc
        candidate = self._candidate(context, communication_id, command, now, "READ_DRAFT")
        if saved.expires_at <= now:
            _fail("DRAFT_EXPIRED", "Saved draft has expired")
        return self._verified_snapshot(record, candidate)

    @staticmethod
    def _time(now: datetime | None) -> datetime:
        value = now if now is not None else datetime.now(timezone.utc)
        if value.tzinfo is None or value.utcoffset() is None:
            _fail("TIMEZONE_REQUIRED", "now must include a UTC offset", 422)
        return value

    def _record_preparation(self, context: RequestContext, draft: MessageDraftView) -> None:
        event = create_domain_event(
            event_type="communication.draft_prepared", tenant_id=draft.tenant_id,
            commitment_id=draft.reference.commitment_id,
            commitment_version=draft.reference.commitment_version,
            correlation_id=draft.reference.correlation_id,
            causation_id=draft.reference.source_event_id, occurred_at=draft.created_at,
            payload={"communication_id": draft.communication_id, "draft_id": draft.draft_id,
                     "proposal_id": draft.reference.proposal_id,
                     "proposal_version": draft.reference.proposal_version,
                     "template_version": draft.template_version, "language": draft.language,
                     "content_hash": draft.content_hash, "status": "DRAFT"},
        )
        self.db.add(OutboxEventRecord(
            event_id=event.event_id, tenant_id=event.tenant_id, event_type=event.event_type,
            commitment_id=event.commitment_id, commitment_version=event.commitment_version,
            correlation_id=event.correlation_id, causation_id=event.causation_id,
            occurred_at=event.occurred_at, payload=event.payload, status="PENDING", attempts=0,
        ))
        self.db.add(AuditEventRecord(
            audit_id=f"audit_{uuid4().hex}", tenant_id=draft.tenant_id,
            commitment_id=draft.reference.commitment_id, event_type=event.event_type,
            actor_id=context.actor_id, actor_role=context.actor_role, dimension="communication",
            previous_state=None, new_state=event.payload,
            evidence_refs=draft.approval_evidence_refs, reason="Template draft prepared (not approved or sent)",
            correlation_id=event.correlation_id, causation_id=event.causation_id,
            occurred_at=draft.created_at,
        ))
        self.db.flush()
