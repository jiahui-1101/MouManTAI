"""Durable P4 customer evidence; never writes the Core agreement or fulfilment."""
from datetime import timedelta
import hashlib
import hmac
import re
import secrets
from uuid import uuid4
from pydantic import ValidationError

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.errors import DomainError
from app.core.events import create_domain_event
from app.core.models import AuditEventRecord, OutboxEventRecord
from .confirmation_schemas import (
    ConfirmationAttemptView, ConfirmationBasis, ConfirmationView, IssuedConfirmation, VerifiedInboundResponse,
)
from .demo_policy import deny
from .models import (
    ConfirmationSessionRecord, ConfirmationAttemptRecord, ConfirmationDecisionRecord, OutboundMessageRecord,
)
from .preferences import stored_time, utc
from .response_rules import classify_response
from .service import _require_context
from .templates import fingerprint

TERMINAL = {"ACCEPT": "ACCEPTED", "REJECT": "REJECTED", "COUNTEROFFER": "COUNTEROFFER_RECEIVED"}
EVENTS = {"ACCEPT": "confirmation.accepted", "REJECT": "confirmation.rejected",
          "COUNTEROFFER": "confirmation.counteroffer_received", "UNKNOWN": "confirmation.unresolved",
          "CLARIFICATION": "confirmation.unresolved"}


def token_digest(value):
    # Token is transported only in a header; invalid input is never echoed in a
    # Pydantic validation error, SQL parameter, audit or DomainError message.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value):
        deny("CONFIRMATION_TOKEN_INVALID", "Invalid confirmation challenge", 403)
    return hashlib.sha256(("p4-confirmation-v1:" + value).encode("ascii")).hexdigest()


class ConfirmationService:
    def __init__(self, db, access, authority, inbound):
        self.db, self.access, self.authority, self.inbound = db, access, authority, inbound

    def _guard(self, context, action):
        _require_context(context)
        if self.access is None:
            deny("CONFIRMATION_ACCESS_UNAVAILABLE", "Trusted confirmation access is unavailable", 503)
        self.access.authorize(context, action)
        validate_storage = getattr(self.access, "validate_storage", None)
        if validate_storage is not None:
            validate_storage(self.db)

    def _outbound(self, context, outbound_id):
        outbound = self.db.scalar(select(OutboundMessageRecord).where(
            OutboundMessageRecord.tenant_id == context.tenant_id, OutboundMessageRecord.outbound_id == outbound_id,
        ).with_for_update().execution_options(populate_existing=True))
        if outbound is None:
            deny("CONFIRMATION_OUTBOUND_NOT_FOUND", "Outbound not found in current tenant", 404)
        if outbound.status != "SENT" or outbound.provider_confirmed is not True or not outbound.provider_reference or not outbound.sent_at:
            deny("CONFIRMATION_OUTBOUND_NOT_ELIGIBLE", "A durable provider-confirmed mock SENT record is required", 409)
        return outbound

    def _basis(self, context, outbound, now):
        if self.authority is None:
            deny("CONFIRMATION_AUTHORITY_UNAVAILABLE", "Current Core/P4 approval reader is unavailable", 503)
        value = self.authority.current_basis(self.db, context, outbound, now=now)
        if not isinstance(value, ConfirmationBasis):
            deny("CONFIRMATION_AUTHORITY_INVALID", "Current authority returned no valid scope", 503)
        value = ConfirmationBasis.model_validate(value.model_dump())
        if (value.reference.tenant_id != context.tenant_id or value.content_hash != outbound.content_hash or
            value.validation_hash != outbound.validation_hash or value.channel != outbound.channel or
            value.recipient_identity_id != outbound.recipient_identity_id or value.expires_at <= now):
            deny("CONFIRMATION_AUTHORITY_MISMATCH", "Current authority does not bind this exact outbound or has expired", 409)
        return value

    def _session(self, context, confirmation_id, *, lock=False):
        query = select(ConfirmationSessionRecord).where(ConfirmationSessionRecord.tenant_id == context.tenant_id,
            ConfirmationSessionRecord.confirmation_id == confirmation_id).execution_options(populate_existing=True)
        row = self.db.scalar(query.with_for_update() if lock else query)
        if row is None:
            deny("CONFIRMATION_NOT_FOUND", "Confirmation not found in current tenant", 404)
        return row

    @staticmethod
    def view(row, now):
        basis = ConfirmationBasis.model_validate(row.binding)
        reasons = []
        if row.revoked_at is not None: reasons.append("CONFIRMATION_REVOKED")
        expired = stored_time(row.expires_at) <= now
        if expired and row.consumed_at is None: reasons.append("CONFIRMATION_EXPIRED")
        return ConfirmationView(confirmation_id=row.confirmation_id, tenant_id=row.tenant_id,
            communication_id=row.communication_id, outbound_id=row.outbound_id, customer_id=row.customer_id,
            channel=row.channel, reference=basis.reference, terms_digest=basis.terms_digest, content_hash=basis.content_hash,
            state="EXPIRED" if expired and row.consumed_at is None else row.state, blocked_reasons=reasons,
            created_at=stored_time(row.created_at), expires_at=stored_time(row.expires_at),
            consumed_at=stored_time(row.consumed_at) if row.consumed_at else None,
            revoked_at=stored_time(row.revoked_at) if row.revoked_at else None)

    def issue(self, context, command, *, now=None):
        self._guard(context, "CREATE_CONFIRMATION")
        now = utc(now)
        try:
            outbound = self._outbound(context, command.outbound_id)
            existing = self.db.scalar(select(ConfirmationSessionRecord).where(
                ConfirmationSessionRecord.tenant_id == context.tenant_id, ConfirmationSessionRecord.outbound_id == outbound.outbound_id))
            if existing is not None:
                deny("CONFIRMATION_ALREADY_ISSUED", "This outbound already has a challenge; plaintext cannot be recovered", 409)
            basis = self._basis(context, outbound, now)
            plain = secrets.token_urlsafe(32)  # 256 bits, generated only after current authority validates.
            row = ConfirmationSessionRecord(tenant_id=context.tenant_id, confirmation_id=f"conf_{uuid4().hex}",
                outbound_id=outbound.outbound_id, communication_id=outbound.communication_id, draft_id=outbound.draft_id,
                approved_review_id=outbound.approved_review_id, customer_id=basis.customer_id,
                recipient_identity_id=basis.recipient_identity_id, channel=basis.channel, token_digest=token_digest(plain),
                binding=basis.model_dump(mode="json"), state="AWAITING_RESPONSE", created_by=context.actor_id, created_at=now,
                expires_at=min(now + timedelta(minutes=command.ttl_minutes), basis.expires_at))
            self.db.add(row)
            self.db.flush()
            self._event(context, row, "confirmation.created", now)
            result = IssuedConfirmation(confirmation=self.view(row, now), confirmation_token=plain)
            self.db.commit()
            return result
        except DomainError:
            self.db.rollback()
            raise
        except IntegrityError:
            self.db.rollback()
            deny("CONFIRMATION_ISSUE_CONFLICT", "A challenge was concurrently issued for this outbound", 409)
        except (SQLAlchemyError, ValidationError):
            self.db.rollback()
            deny("CONFIRMATION_STORAGE_UNAVAILABLE", "Confirmation storage is unavailable", 503)

    def get(self, context, confirmation_id, *, now=None):
        self._guard(context, "READ_CONFIRMATION")
        try:
            return self.view(self._session(context, confirmation_id), utc(now))
        except (SQLAlchemyError, ValidationError):
            deny("CONFIRMATION_STORAGE_UNAVAILABLE", "Confirmation storage is unavailable", 503)
        finally:
            self.db.rollback()

    def list(self, context, *, communication_id=None, now=None):
        self._guard(context, "READ_CONFIRMATION")
        try:
            query = select(ConfirmationSessionRecord).where(ConfirmationSessionRecord.tenant_id == context.tenant_id)
            if communication_id:
                query = query.where(ConfirmationSessionRecord.communication_id == communication_id)
            return [self.view(row, utc(now)) for row in self.db.scalars(query.order_by(ConfirmationSessionRecord.created_at))]
        except (SQLAlchemyError, ValidationError):
            deny("CONFIRMATION_STORAGE_UNAVAILABLE", "Confirmation storage is unavailable", 503)
        finally:
            self.db.rollback()

    @staticmethod
    def attempt_view(attempt, decision):
        return ConfirmationAttemptView(attempt_id=attempt.attempt_id, confirmation_id=attempt.confirmation_id,
            inbound_message_id=attempt.inbound_message_id, intent=decision.intent, reason=decision.reason,
            evidence_refs=attempt.evidence_refs, proposed_changes=decision.proposed_changes,
            received_at=stored_time(attempt.received_at))

    def history(self, context, confirmation_id):
        self._guard(context, "READ_CONFIRMATION")
        try:
            self._session(context, confirmation_id)
            query = select(ConfirmationAttemptRecord, ConfirmationDecisionRecord).join(ConfirmationDecisionRecord,
                (ConfirmationAttemptRecord.tenant_id == ConfirmationDecisionRecord.tenant_id) &
                (ConfirmationAttemptRecord.attempt_id == ConfirmationDecisionRecord.attempt_id)).where(
                    ConfirmationAttemptRecord.tenant_id == context.tenant_id,
                    ConfirmationAttemptRecord.confirmation_id == confirmation_id).order_by(ConfirmationAttemptRecord.received_at)
            return [self.attempt_view(attempt, decision) for attempt, decision in self.db.execute(query)]
        except (SQLAlchemyError, ValidationError):
            deny("CONFIRMATION_STORAGE_UNAVAILABLE", "Confirmation storage is unavailable", 503)
        finally:
            self.db.rollback()

    def revoke(self, context, confirmation_id, *, now=None):
        self._guard(context, "REVOKE_CONFIRMATION")
        now = utc(now)
        try:
            row = self._session(context, confirmation_id, lock=True)
            if row.consumed_at is not None:
                deny("CONFIRMATION_CONSUMED", "A terminal challenge cannot be reused or revoked", 409)
            if row.revoked_at is None:
                row.revoked_at = now
                self._event(context, row, "confirmation.revoked", now)
            result = self.view(row, now)
            self.db.commit()
            return result
        except DomainError:
            self.db.rollback()
            raise
        except (SQLAlchemyError, ValidationError):
            self.db.rollback()
            deny("CONFIRMATION_STORAGE_UNAVAILABLE", "Confirmation storage is unavailable", 503)

    def respond(self, context, confirmation_id, command, token, *, now=None):
        self._guard(context, "PROCESS_CONFIRMATION_RESPONSE")
        now = utc(now)
        digest = token_digest(token)
        try:
            row = self._session(context, confirmation_id, lock=True)
            if not hmac.compare_digest(row.token_digest, digest):
                deny("CONFIRMATION_TOKEN_INVALID", "Invalid confirmation challenge", 403)
            if row.revoked_at is not None: deny("CONFIRMATION_REVOKED", "Challenge was revoked", 409)
            if row.consumed_at is not None: deny("CONFIRMATION_CONSUMED", "Challenge already has a terminal response", 409)
            if stored_time(row.expires_at) <= now: deny("CONFIRMATION_EXPIRED", "Challenge expired", 409)
            if self.inbound is None:
                deny("VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE", "P1 verified inbound authority is unavailable", 503)
            reply = self.inbound.resolve(self.db, context, command.inbound_message_id, now=now)
            if not isinstance(reply, VerifiedInboundResponse):
                deny("CONFIRMATION_IDENTITY_UNVERIFIED", "No trusted verified inbound evidence")
            reply = VerifiedInboundResponse.model_validate(reply.model_dump())
            if (reply.message_id != command.inbound_message_id or reply.tenant_id != row.tenant_id or
                reply.customer_id != row.customer_id or reply.channel != row.channel or
                reply.recipient_identity_id != row.recipient_identity_id):
                deny("CONFIRMATION_IDENTITY_MISMATCH", "Inbound scope does not match the challenge")
            outbound = self._outbound(context, row.outbound_id)
            fresh = self._basis(context, outbound, now)
            if (fresh.model_dump(mode="json") != row.binding or
                (row.customer_id, row.recipient_identity_id, row.channel) !=
                (fresh.customer_id, fresh.recipient_identity_id, fresh.channel)):
                deny("CONFIRMATION_PROPOSAL_CHANGED", "Current terms, proposal, approval or recipient changed", 409)
            classified = classify_response(reply.text)
            if classified.proposal_id is not None and (classified.proposal_id, classified.proposal_version) != (
                fresh.reference.proposal_id, fresh.reference.proposal_version):
                deny("CONFIRMATION_RESPONSE_VERSION_MISMATCH", "Response targets another proposal/version", 409)
            if classified.intent == "ACCEPT" and classified.terms_digest != fresh.terms_digest:
                deny("CONFIRMATION_TERMS_MISMATCH", "Acceptance does not cover the exact approved terms", 409)
            proof = fingerprint({"confirmation_id": row.confirmation_id, **reply.model_dump(mode="json")})
            prior = self.db.scalar(select(ConfirmationAttemptRecord).where(
                ConfirmationAttemptRecord.tenant_id == context.tenant_id,
                or_(ConfirmationAttemptRecord.inbound_message_id == reply.message_id,
                    (ConfirmationAttemptRecord.channel == reply.channel) &
                    (ConfirmationAttemptRecord.provider_message_id == reply.provider_message_id))))
            if prior:
                if prior.confirmation_id != row.confirmation_id or prior.proof_digest != proof:
                    deny("CONFIRMATION_DUPLICATE_CONFLICT", "Provider evidence was rebound or changed", 409)
                decision = self.db.scalar(select(ConfirmationDecisionRecord).where(
                    ConfirmationDecisionRecord.tenant_id == context.tenant_id,
                    ConfirmationDecisionRecord.attempt_id == prior.attempt_id))
                if decision is None:
                    deny("CONFIRMATION_EVIDENCE_INVALID", "Stored response evidence is incomplete", 503)
                result = self.attempt_view(prior, decision)
                self.db.rollback()
                return result
            attempt = ConfirmationAttemptRecord(tenant_id=context.tenant_id, attempt_id=f"response_{uuid4().hex}",
                confirmation_id=row.confirmation_id, inbound_message_id=reply.message_id,
                provider_message_id=reply.provider_message_id, channel=reply.channel, proof_digest=proof,
                source_digest=reply.source_digest, evidence_refs=reply.evidence_refs, received_at=now)
            self.db.add(attempt)
            self.db.flush()
            terminal = classified.intent in TERMINAL
            decision = ConfirmationDecisionRecord(tenant_id=context.tenant_id, decision_id=f"decision_{uuid4().hex}",
                confirmation_id=row.confirmation_id, attempt_id=attempt.attempt_id,
                terminal_confirmation_id=row.confirmation_id if terminal else None, intent=classified.intent,
                reason=classified.reason, proposed_changes=classified.changes, decided_at=now)
            self.db.add(decision)
            row.state = TERMINAL.get(classified.intent, "CLARIFICATION_REQUIRED" if classified.intent == "CLARIFICATION" else "UNRESOLVED")
            row.consumed_at = now if terminal else None
            self._event(context, row, EVENTS[classified.intent], now, reply=reply, decision=decision)
            result = self.attempt_view(attempt, decision)
            self.db.commit()
            return result
        except DomainError:
            self.db.rollback()
            raise
        except IntegrityError:
            self.db.rollback()
            deny("CONFIRMATION_RESPONSE_CONFLICT", "A competing response or duplicate provider message was recorded", 409)
        except (SQLAlchemyError, ValidationError):
            self.db.rollback()
            deny("CONFIRMATION_STORAGE_UNAVAILABLE", "Confirmation transaction could not be persisted", 503)

    def _event(self, context, row, event_type, now, *, reply=None, decision=None):
        basis = ConfirmationBasis.model_validate(row.binding)
        refs = reply.evidence_refs if reply else basis.approval_evidence_refs
        payload = {"confirmation_id": row.confirmation_id, "communication_id": row.communication_id,
            "outbound_id": row.outbound_id, "proposal_id": basis.reference.proposal_id,
            "proposal_version": basis.reference.proposal_version, "terms_digest": basis.terms_digest,
            "response_state": row.state, "evidence_refs": refs, "evidence_scope": "P4_EVIDENCE_ONLY"}
        payload["integration_mode"] = "SYNTHETIC_ONLY"
        if decision:
            payload.update(decision_id=decision.decision_id, attempt_id=decision.attempt_id, intent=decision.intent)
        event = create_domain_event(event_type=event_type, tenant_id=context.tenant_id,
            commitment_id=basis.reference.commitment_id, commitment_version=basis.reference.commitment_version,
            correlation_id=context.correlation_id, causation_id=reply.message_id if reply else context.causation_id,
            occurred_at=now, payload=payload)
        self.db.add(OutboxEventRecord(event_id=event.event_id, tenant_id=event.tenant_id, event_type=event.event_type,
            commitment_id=event.commitment_id, commitment_version=event.commitment_version,
            correlation_id=event.correlation_id, causation_id=event.causation_id, occurred_at=now,
            payload=event.payload, attempts=0, status="PENDING"))
        self.db.add(AuditEventRecord(audit_id=f"audit_{uuid4().hex}", tenant_id=context.tenant_id,
            commitment_id=basis.reference.commitment_id, event_type=event_type, actor_id=context.actor_id,
            actor_role=context.actor_role, dimension="communication", previous_state=None, new_state=payload,
            evidence_refs=refs, reason="P4 confirmation evidence only; Core transition requires a trusted consumer",
            correlation_id=context.correlation_id, causation_id=event.causation_id, occurred_at=now))
        self.db.flush()
