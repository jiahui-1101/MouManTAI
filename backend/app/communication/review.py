"""Persistent message review, distinct from Core proposal approval. Never sends."""

from datetime import timezone
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import AuditEventRecord
from app.core.schemas import ApprovalState
from .drafting import DraftAuthority, MessageDraftService
from .templates import fingerprint
from .repository import DraftReviewRepository
from .schemas import (
    ApproveDraftRequest, DraftReviewDecision, DraftReviewView,
    RejectDraftRequest, ReviewAction, ReviewAuthorization, RequestStatus,
)
from .service import _check_authority_availability, _fail, _require_context


class ReviewAuthority(Protocol):
    """P5 must verify identity, tenant membership and action-specific policy.

    Read-only in the supplied Session: no commit/rollback/Core mutations. For an
    existing approval, also revalidate the original reviewer's authorization and
    revocation evidence, returning VALID/REVOKED with evidence, or UNKNOWN.
    Never infer these permissions from the demo role selector alone.
    """

    def authorize_review(self, db: Session, context: RequestContext, *,
                         communication_id: str, draft_id: str, action: ReviewAction,
                         existing_review: DraftReviewDecision | None) -> ReviewAuthorization | None: ...


# Only definite semantic invalidity is latched. Infrastructure/policy unavailability
# fails closed without pretending that revocation has been established.
INVALIDATING = {
    "CONSENT_REVOKED", "CONSENT_EXPIRED", "CONSENT_RECIPIENT_CHANGED", "CONTACT_CHANGED",
    "STALE_PROPOSAL_VERSION", "COMMITMENT_VERSION_CONFLICT", "PROPOSAL_NOT_ELIGIBLE",
    "APPROVAL_EXPIRED", "PROPOSAL_EXPIRED", "DRAFT_EXPIRED", "PROPOSED_DEADLINE_PASSED",
    "APPROVAL_EVIDENCE_REQUIRED", "APPROVED_TERMS_MISMATCH", "AUTHORIZATION_SCOPE_MISMATCH",
    "VERIFIED_RECIPIENT_REQUIRED", "AUTHORIZED_CHANNEL_REQUIRED", "RECIPIENT_MISMATCH",
    "DRAFT_INTEGRITY_ERROR", "DRAFT_REVALIDATION_REQUIRED", "REQUEST_REFERENCE_CONFLICT",
    "REVIEW_REQUEST_BLOCKED", "REVIEW_BINDING_CHANGED", "REVIEW_EXPIRED",
    "REVIEW_AUTHORIZATION_REVOKED", "PROPOSAL_NOT_FOUND", "COMMITMENT_NOT_FOUND",
    "SOURCE_EVENT_NOT_FOUND",
}


class DraftReviewService:
    def __init__(self, db: Session, draft_authority: DraftAuthority | None = None,
                 authority: ReviewAuthority | None = None):
        self.db = db
        self.drafts = MessageDraftService(db, draft_authority)
        self.authority = authority
        self.repository = DraftReviewRepository(db)

    def get(self, context, communication_id, draft_id, *, now=None):
        return self._run(context, communication_id, draft_id, "READ_REVIEW", None, now)

    def approve(self, context, communication_id, draft_id, command: ApproveDraftRequest, *, now=None):
        return self._run(context, communication_id, draft_id, "APPROVE_DRAFT", command, now)

    def reject(self, context, communication_id, draft_id, command: RejectDraftRequest, *, now=None):
        return self._run(context, communication_id, draft_id, "REJECT_DRAFT", command, now)

    def validate_for_send(self, context, communication_id, draft_id, *, now):
        """Revalidate inside Send's transaction; never commit/rollback or grant SEND_MESSAGE."""
        _require_context(context)
        if self.authority is None:
            _fail("REVIEW_AUTHORITY_UNAVAILABLE", "Trusted review authority is unavailable", 503)
        _check_authority_availability(self.authority)
        if self.drafts.repository.get(context.tenant_id, communication_id, draft_id, lock=True) is None:
            _fail("DRAFT_NOT_FOUND", "Draft not found in current scope", 404)
        record = self.repository.get(context.tenant_id, communication_id, draft_id)
        if record is None or record.invalidated_at is not None:
            _fail("SEND_REVIEW_REQUIRED", "A current approved draft review is required")
        decision = self.repository.view(record)
        if decision.action != "APPROVE_DRAFT":
            _fail("SEND_REVIEW_REQUIRED", "Rejected drafts cannot be sent")
        audit = self.db.get(AuditEventRecord, decision.audit_id, populate_existing=True)
        if not audit or audit.tenant_id != context.tenant_id or audit.new_state.get("review_hash") != fingerprint(decision.model_dump(mode="json")):
            _fail("REVIEW_INTEGRITY_ERROR", "Review audit binding is invalid")
        grant = self._authorize(context, communication_id, draft_id, "READ_REVIEW", decision, now)
        draft = self._fresh(context, communication_id, draft_id, decision, grant, now)
        return draft, decision

    def _authorize(self, context, communication_id, draft_id, action, decision, now):
        grant = self.authority.authorize_review(
            self.db, context, communication_id=communication_id, draft_id=draft_id,
            action=action, existing_review=decision,
        )
        if grant is None:
            _fail("REVIEW_FORBIDDEN", "This identity is not authorized for draft review", 403)
        if not isinstance(grant, ReviewAuthorization):
            _fail("REVIEW_AUTHORITY_INVALID", "Invalid review policy result", 503)
        if (grant.tenant_id, grant.actor_id, grant.actor_role, grant.communication_id, grant.draft_id, grant.action) != (
            context.tenant_id, context.actor_id, context.actor_role, communication_id, draft_id, action,
        ) or grant.expires_at <= now:
            _fail("REVIEW_FORBIDDEN", "Review policy does not bind this identity, scope or action", 403)
        return grant

    def _fresh(self, context, communication_id, draft_id, decision, grant, now):
        request = self.drafts.requests.get(context, communication_id)
        row = self.drafts.requests.repository.get(context.tenant_id, communication_id)
        if request.request_status != RequestStatus.READY_FOR_DRAFTING or row.request_status != RequestStatus.READY_FOR_DRAFTING.value:
            _fail("REVIEW_REQUEST_BLOCKED", "Blocked or inactive requests cannot be reviewed")
        draft = self.drafts.validate_current(context, communication_id, draft_id, now=now)
        if decision:
            if decision.expires_at <= now:
                _fail("REVIEW_EXPIRED", "The original review authorization has expired")
            if any(getattr(decision, key) != getattr(draft, key) for key in (
                "tenant_id", "communication_id", "draft_id", "reference", "content_hash",
                "validation_hash", "language", "recipient_identity_id", "channel",
            )):
                _fail("REVIEW_BINDING_CHANGED", "The reviewed draft or approval basis changed")
            if decision.action == "APPROVE_DRAFT":
                if grant.existing_review_status == "UNKNOWN" or not grant.existing_review_evidence_refs:
                    _fail("REVIEW_VALIDATION_UNAVAILABLE", "Original reviewer authorization cannot be verified", 503)
                if grant.existing_review_status == "REVOKED":
                    _fail("REVIEW_AUTHORIZATION_REVOKED", "Original reviewer authorization was revoked")
        return draft

    def _run(self, context: RequestContext, communication_id: str, draft_id: str,
             action: ReviewAction, command, now):
        _require_context(context)
        current_time = self.drafts._time(now)
        if self.authority is None:
            _fail("REVIEW_AUTHORITY_UNAVAILABLE", "Trusted manager-review policy is not configured", 503)
        _check_authority_availability(self.authority)
        for attempt in range(2):
            try:
                # Lock order is identical for GET/approve/reject. The SQL unique
                # constraint also protects absent rows and competing transactions.
                draft_row = self.drafts.repository.get(context.tenant_id, communication_id, draft_id, lock=True)
                if draft_row is None:
                    _fail("DRAFT_NOT_FOUND", "Draft not found in current tenant/request", 404)
                record = self.repository.get(context.tenant_id, communication_id, draft_id)
                decision = self.repository.view(record) if record else None
                if decision:
                    audit = self.db.get(AuditEventRecord, decision.audit_id)
                    if not audit or audit.tenant_id != context.tenant_id or audit.new_state.get("review_hash") != fingerprint(decision.model_dump(mode="json")):
                        _fail("REVIEW_INTEGRITY_ERROR", "Review does not match its immutable audit evidence")
                grant = self._authorize(context, communication_id, draft_id, action, decision, current_time)
                if record and record.invalidated_at is not None:
                    if action != "READ_REVIEW":
                        _fail("REVIEW_INVALIDATED", "This review is permanently invalidated")
                    result = self._view(context, communication_id, draft_id, record, grant, current_time)
                    self.db.rollback()
                    return result
                try:
                    draft = self._fresh(context, communication_id, draft_id, decision, grant, current_time)
                except DomainError as exc:
                    if not record or exc.code not in INVALIDATING:
                        raise
                    self._invalidate(context, record, decision, grant, exc.code, current_time)
                    result = self._view(context, communication_id, draft_id, record, grant, current_time)
                    self.db.commit()
                    if action == "READ_REVIEW":
                        return result
                    raise
                if action != "READ_REVIEW":
                    if command.expected_content_hash != draft.content_hash:
                        _fail("REVIEW_CONTENT_CHANGED", "Reload and inspect the exact draft before reviewing")
                    existing_key = self.repository.by_key(context.tenant_id, command.request_key)
                    if existing_key and (not record or existing_key.review_id != record.review_id):
                        _fail("REVIEW_IDEMPOTENCY_CONFLICT", "Review request key was used for another draft")
                    reason = command.reason.strip() if isinstance(command, RejectDraftRequest) else None
                    if decision:
                        if (decision.request_key, decision.action, decision.reviewer_id, decision.reason) != (
                            command.request_key, action, context.actor_id, reason,
                        ):
                            _fail("REVIEW_ALREADY_DECIDED", "This exact draft already has a terminal decision")
                    else:
                        decision = DraftReviewDecision(
                            review_id=f"review_{uuid4().hex}", tenant_id=context.tenant_id,
                            communication_id=communication_id, draft_id=draft_id, reference=draft.reference,
                            request_key=command.request_key, action=action,
                            reviewer_id=context.actor_id, reviewer_role=context.actor_role,
                            reviewed_at=current_time, expires_at=min(draft.expires_at, grant.expires_at),
                            content_hash=draft.content_hash, validation_hash=draft.validation_hash,
                            language=draft.language, recipient_identity_id=draft.recipient_identity_id,
                            channel=draft.channel, core_approval_evidence_refs=draft.approval_evidence_refs,
                            authorization_evidence_refs=grant.evidence_refs, reason=reason,
                            audit_id=f"audit_{uuid4().hex}", correlation_id=context.correlation_id,
                        )
                        record = self.repository.add(decision)
                        self._audit(context, decision, decision.audit_id,
                                    "communication.draft_approved" if action == "APPROVE_DRAFT" else "communication.draft_rejected",
                                    current_time, grant.evidence_refs)
                result = self._view(context, communication_id, draft_id, record, grant, current_time)
                if action != "READ_REVIEW":
                    self.db.commit()
                else:
                    self.db.rollback()
                return result
            except IntegrityError as exc:
                self.db.rollback()
                if attempt:
                    raise DomainError("REVIEW_CONFLICT", "Concurrent draft review conflict", status_code=409) from exc
            except SQLAlchemyError as exc:
                self.db.rollback()
                raise DomainError("REVIEW_STORAGE_UNAVAILABLE", "Review storage is unavailable; verify P5 migration", status_code=503) from exc
            except ValidationError as exc:
                self.db.rollback()
                raise DomainError("REVIEW_INTEGRITY_ERROR", "Stored review is invalid", status_code=409) from exc
            except Exception:
                self.db.rollback()
                raise
        raise AssertionError("unreachable")

    def _view(self, context, communication_id, draft_id, record, grant, now):
        decision = self.repository.view(record) if record else None
        invalid = record is not None and record.invalidated_at is not None
        state = ApprovalState.INVALIDATED if invalid else (
            ApprovalState.APPROVED if decision and decision.action == "APPROVE_DRAFT" else
            ApprovalState.REJECTED if decision else ApprovalState.PENDING
        )
        return DraftReviewView(
            tenant_id=context.tenant_id, communication_id=communication_id, draft_id=draft_id,
            review_state=state, effective_approval=state == ApprovalState.APPROVED,
            allowed_actions=grant.allowed_actions if not record else [], decision=decision,
            invalidated_at=(record.invalidated_at.replace(tzinfo=timezone.utc) if record.invalidated_at and record.invalidated_at.tzinfo is None else record.invalidated_at) if record else None,
            invalidation_code=record.invalidation_code if record else None,
            invalidation_audit_id=record.invalidation_audit_id if record else None,
            checked_at=now,
        )

    def _invalidate(self, context, record, decision, grant, code, now):
        record.invalidated_at = now.astimezone(timezone.utc)
        record.invalidation_code = code
        record.invalidation_audit_id = f"audit_{uuid4().hex}"
        self._audit(context, decision, record.invalidation_audit_id,
                    "communication.draft_review_invalidated", now,
                    grant.evidence_refs + grant.existing_review_evidence_refs, code)

    def _audit(self, context, decision, audit_id, event_type, now, evidence, invalidation=None):
        self.db.add(AuditEventRecord(
            audit_id=audit_id, tenant_id=context.tenant_id, commitment_id=decision.reference.commitment_id,
            event_type=event_type, actor_id=context.actor_id, actor_role=context.actor_role,
            dimension="communication", previous_state=None,
            new_state={"review_id": decision.review_id, "draft_id": decision.draft_id,
                       "communication_id": decision.communication_id, "content_hash": decision.content_hash,
                       "proposal_id": decision.reference.proposal_id, "proposal_version": decision.reference.proposal_version,
                       "review_action": decision.action, "invalidation_code": invalidation,
                       "review_hash": fingerprint(decision.model_dump(mode="json"))},
            evidence_refs=evidence, reason=invalidation or decision.reason or "Message draft approved; not sent",
            correlation_id=context.correlation_id, causation_id=decision.reference.source_event_id,
            occurred_at=now,
        ))
        self.db.flush()
