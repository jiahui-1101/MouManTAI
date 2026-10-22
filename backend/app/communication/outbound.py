"""Durable one-submission intent. An uncertain/crashed send is never auto-replayed."""
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, OutboxEventRecord
from app.core.events import create_domain_event
from .models import OutboundMessageRecord, SendAttemptRecord
from .providers import MOCK_CHANNELS, OutboundProvider, ProviderResult, SendEnvelope
from .repository import OutboundRepository
from .review import DraftReviewService
from .schemas import SendAuthorization, SendEligibility, SendMessageRequest
from .service import _check_authority_availability, _fail, _require_context


class SendAuthority(Protocol):
    """Read-only explicit SEND_MESSAGE policy, current actor/membership and scope."""
    def authorize_send(self, db: Session, context: RequestContext, *, draft, review) -> SendAuthorization | None: ...


class RuntimeSendAuthority:
    def check_availability(self):
        raise DomainError("SEND_AUTHORITY_UNAVAILABLE", "Trusted SEND_MESSAGE permission is unavailable", status_code=503,
            details={"integration_status": "UNAVAILABLE", "missing_capabilities": [
                "CORE_AUTHENTICATED_ACTOR_AND_TENANT_MEMBERSHIP", "CORE_SEND_MESSAGE_ACTION_POLICY",
                "CORE_P3_CURRENT_APPROVAL_AND_P1_VERIFIED_CONTACT_CONSENT"]})

    def authorize_send(self, db, context, *, draft, review):
        self.check_availability()


class OutboundService:
    def __init__(self, db: Session, draft_authority, review_authority, authority: SendAuthority | None, provider: OutboundProvider):
        self.db, self.authority, self.provider = db, authority, provider
        self.reviews = DraftReviewService(db, draft_authority, review_authority)
        self.repository = OutboundRepository(db)

    def _preflight(self, context):
        _require_context(context)
        if self.authority is None:
            _fail("SEND_AUTHORITY_UNAVAILABLE", "Trusted sending permission is unavailable", 503)
        _check_authority_availability(self.authority)

    def _validate(self, context, communication_id, draft_id, now):
        self._preflight(context)
        draft, review = self.reviews.validate_for_send(context, communication_id, draft_id, now=now)
        if draft.channel not in MOCK_CHANNELS:
            _fail("UNSUPPORTED_MOCK_CHANNEL", "Only contract-declared local mock channels are supported", 409)
        grant = self.authority.authorize_send(self.db, context,
            draft=draft.model_copy(deep=True), review=review.model_copy(deep=True))
        if not isinstance(grant, SendAuthorization):
            _fail("SEND_FORBIDDEN", "SEND_MESSAGE permission is required", 403)
        try:
            grant = SendAuthorization.model_validate(grant.model_dump())
        except ValidationError:
            _fail("SEND_AUTHORITY_INVALID", "Invalid sending grant", 503)
        if (grant.tenant_id, grant.actor_id, grant.actor_role, grant.communication_id, grant.draft_id,
            grant.review_id, grant.content_hash, grant.validation_hash, grant.action) != (
            context.tenant_id, context.actor_id, context.actor_role, communication_id, draft_id,
            review.review_id, draft.content_hash, draft.validation_hash, "SEND_MESSAGE") or grant.expires_at <= now:
            _fail("SEND_FORBIDDEN", "Sending grant is expired or does not bind this exact actor and draft", 403)
        return draft, review, grant

    def eligibility(self, context, communication_id, draft_id, *, now=None):
        current = self.reviews.drafts._time(now)
        try:
            draft, review, grant = self._validate(context, communication_id, draft_id, current)
            existing = self.repository.by_draft(context.tenant_id, draft_id)
            return SendEligibility(tenant_id=context.tenant_id, communication_id=communication_id, draft_id=draft_id,
                can_send=existing is None, content_hash=draft.content_hash, approved_review_id=review.review_id,
                expires_at=min(draft.expires_at, review.expires_at, grant.expires_at),
                blocked_reason="SEND_ALREADY_ATTEMPTED" if existing else None, checked_at=current)
        except DomainError as error:
            if error.status_code in {400, 404, 422}:
                raise
            return SendEligibility(tenant_id=context.tenant_id, communication_id=communication_id, draft_id=draft_id,
                can_send=False, blocked_reason=error.code, checked_at=current)
        except SQLAlchemyError as error:
            raise DomainError("SEND_STORAGE_UNAVAILABLE", "Sending eligibility storage is unavailable", status_code=503) from error
        finally:
            self.db.rollback()

    def history(self, context, communication_id):
        _require_context(context)
        try:
            self.reviews.drafts.requests.get(context, communication_id)
            return [self.repository.view(row) for row in self.repository.list(context.tenant_id, communication_id)]
        except SQLAlchemyError as error:
            raise DomainError("SEND_STORAGE_UNAVAILABLE", "Sending history storage is unavailable", status_code=503) from error
        finally:
            self.db.rollback()

    def send(self, context, communication_id, draft_id, command: SendMessageRequest, *, now=None):
        current = self.reviews.drafts._time(now)
        self._preflight(context)
        # Claim is serialized by the exact draft lock and both database uniques.
        for retry in range(2):
            try:
                draft, review, grant = self._validate(context, communication_id, draft_id, current)
                if command.expected_content_hash != draft.content_hash:
                    _fail("SEND_CONTENT_CHANGED", "Inspect the current approved content before sending", 409)
                existing = self.repository.by_key(context.tenant_id, command.request_key)
                if existing and (existing.draft_id != draft_id or existing.communication_id != communication_id):
                    _fail("SEND_IDEMPOTENCY_CONFLICT", "This sending key belongs to another target", 409)
                existing = existing or self.repository.by_draft(context.tenant_id, draft_id)
                if existing:
                    if existing.request_key != command.request_key:
                        _fail("SEND_ALREADY_ATTEMPTED", "This draft already has a durable submission intent", 409)
                    result = self.repository.view(existing)
                    self.db.rollback()
                    return result  # No provider call, including FAILED/UNKNOWN/QUEUED.
                row = OutboundMessageRecord(tenant_id=context.tenant_id, outbound_id=f"outbound_{uuid4().hex}",
                    communication_id=communication_id, draft_id=draft_id, approved_review_id=review.review_id,
                    content_hash=draft.content_hash, validation_hash=draft.validation_hash, channel=draft.channel,
                    recipient_identity_id=draft.recipient_identity_id, request_key=command.request_key,
                    status="QUEUED", provider_confirmed=False, authorization_evidence=grant.model_dump(mode="json"),
                    correlation_id=context.correlation_id, created_at=current, updated_at=current)
                self.db.add(row)
                self.db.flush()
                attempt = SendAttemptRecord(tenant_id=context.tenant_id, outbound_id=row.outbound_id,
                    attempt_number=1, status="QUEUED", started_at=current)
                self.db.add(attempt)
                self._audit(context, row, "communication.send_queued", current)
                self.db.commit()  # Durable claim precedes every possible provider side effect.
                break
            except IntegrityError as error:
                self.db.rollback()
                if retry:
                    raise DomainError("SEND_CONFLICT", "Concurrent sending claim conflict", status_code=409) from error
            except SQLAlchemyError as error:
                self.db.rollback()
                raise DomainError("SEND_STORAGE_UNAVAILABLE", "Sending intent could not be saved", status_code=503) from error
            except Exception:
                self.db.rollback()
                raise
        # Commit a conservative UNKNOWN marker BEFORE submission. No recovery path
        # may replay this intent. If outcome persistence fails, this marker survives.
        try:
            # Revalidate after the claim commit, since authority may have changed.
            current = self.reviews.drafts._time(now)
            draft, review, grant = self._validate(context, communication_id, draft_id, current)
            row = self.repository.by_draft(context.tenant_id, draft_id)
            attempt = self.db.get(SendAttemptRecord, (context.tenant_id, row.outbound_id, 1))
            row.status = attempt.status = "DELIVERY_UNKNOWN"
            row.last_error_code = attempt.error_code = "PROVIDER_RESULT_PENDING"
            row.updated_at = current
            self._audit(context, row, "communication.send_submission_started", current)
            self.db.flush()
            fallback = self.repository.view(row)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        try:
            # Reacquire currentness locks after the durable UNKNOWN commit and
            # hold them through provider submission/result persistence.
            current = self.reviews.drafts._time(now)
            draft, review, grant = self._validate(context, communication_id, draft_id, current)
        except Exception:
            self.db.rollback()
            raise
        try:
            result = self.provider.submit(SendEnvelope(row.outbound_id, draft))
            if not isinstance(result, ProviderResult) or result.status not in {"SENT", "FAILED", "DELIVERY_UNKNOWN"}:
                raise ValueError("Invalid provider result")
            if result.status == "SENT" and not result.provider_reference:
                raise ValueError("Unconfirmed provider success")
            if result.provider_reference and len(result.provider_reference) > 128:
                raise ValueError("Invalid provider reference")
        except TimeoutError:
            result = ProviderResult("DELIVERY_UNKNOWN", error_code="PROVIDER_TIMEOUT")
        except Exception:
            result = ProviderResult("DELIVERY_UNKNOWN", error_code="PROVIDER_RESULT_UNCERTAIN")
        try:
            current = self.reviews.drafts._time(now)
            row.status = attempt.status = result.status
            row.provider_reference = attempt.provider_reference = result.provider_reference
            row.provider_confirmed = result.status == "SENT"
            row.last_error_code = attempt.error_code = result.error_code or (
                "MOCK_PROVIDER_REJECTED" if result.status == "FAILED" else "PROVIDER_RESULT_UNCERTAIN" if result.status == "DELIVERY_UNKNOWN" else None)
            row.updated_at = current
            row.sent_at = current if result.status == "SENT" else None
            row.failed_at = current if result.status == "FAILED" else None
            attempt.finished_at = current
            self._audit(context, row, "communication.mock_sent" if row.provider_confirmed else "communication.send_result", current)
            self.db.flush()
            value = self.repository.view(row)
            self.db.commit()
            return value
        except Exception:
            # Submission may have succeeded. Return ONLY the already-committed
            # UNKNOWN state; never roll back the durable intent and submit again.
            self.db.rollback()
            return fallback

    def _audit(self, context, row, event_type, now):
        reference = self.reviews.drafts.requests.get(context, row.communication_id).reference
        event = create_domain_event(event_type=event_type, tenant_id=context.tenant_id,
            commitment_id=reference.commitment_id, commitment_version=reference.commitment_version,
            correlation_id=context.correlation_id, causation_id=reference.source_event_id, occurred_at=now,
            payload={"outbound_id": row.outbound_id, "communication_id": row.communication_id,
                "draft_id": row.draft_id, "review_id": row.approved_review_id, "status": row.status,
                "content_hash": row.content_hash, "provider_reference": row.provider_reference,
                "provider_confirmed": row.provider_confirmed, "provider_mode": "LOCAL_MOCK",
                "evidence_refs": row.authorization_evidence["evidence_refs"]})
        self.db.add(OutboxEventRecord(event_id=event.event_id, tenant_id=event.tenant_id,
            event_type=event.event_type, commitment_id=event.commitment_id, commitment_version=event.commitment_version,
            correlation_id=event.correlation_id, causation_id=event.causation_id, occurred_at=now,
            payload=event.payload, status="PENDING", attempts=0))
        self.db.add(AuditEventRecord(audit_id=f"audit_{uuid4().hex}", tenant_id=context.tenant_id,
            commitment_id=reference.commitment_id,
            event_type=event_type, actor_id=context.actor_id, actor_role=context.actor_role, dimension="communication",
            previous_state=None, new_state=event.payload, evidence_refs=row.authorization_evidence["evidence_refs"],
            reason="Local mock outbound; no delivery, acceptance or fulfilment implied",
            correlation_id=context.correlation_id, causation_id=reference.source_event_id, occurred_at=now))
