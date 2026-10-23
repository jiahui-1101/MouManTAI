"""Deterministic durable scheduling. No shared worker or Core state mutations.

Each reminder is a NEW authorized repeat-contact intent, not a retry of the
original outbound. Only an exact, currently approved draft may be repeated.
An UNKNOWN/FAILED attempt is never automatically submitted again.
"""
from datetime import timedelta
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.errors import DomainError
from app.core.events import create_domain_event
from app.core.models import AuditEventRecord, CommitmentRecord, OutboxEventRecord
from .confirmation_schemas import ConfirmationBasis
from .models import ConfirmationSessionRecord, FollowUpTaskRecord, ReminderAttemptRecord
from .followup_schemas import FollowUpView, ReminderAuthorization, SLAPolicy
from .preferences import stored_time, utc
from .providers import LocalMockProvider, ProviderResult, SendEnvelope
from .service import _require_context
from .demo_policy import deny
from .templates import fingerprint


class FollowUpAuthority(Protocol):
    def authorize(self, db, context, *, action, confirmation_id, policy_digest, now) -> ReminderAuthorization: ...


class RuntimeFollowUpAuthority:
    def authorize(self, db, context, **kwargs):
        deny("FOLLOWUP_AUTHORITY_UNAVAILABLE",
             "Trusted follow-up policy and repeat-contact authorization are not connected", 503)


def lock_confirmation(db, context, confirmation_id):
    """Core anchor FIRST, then session, then task/attempt/consent (D-041).

    Initial scope lookup is read-only. All callers re-read under the lock.
    Used by both the scheduler and terminal confirmation writes.
    """
    row = db.get(ConfirmationSessionRecord, (context.tenant_id, confirmation_id))
    if row is None:
        deny("CONFIRMATION_NOT_FOUND", "Confirmation not found in current tenant", 404)
    basis = ConfirmationBasis.model_validate(row.binding)
    core = db.scalar(select(CommitmentRecord).where(
        CommitmentRecord.tenant_id == context.tenant_id,
        CommitmentRecord.commitment_id == basis.reference.commitment_id,
    ).with_for_update().execution_options(populate_existing=True))
    if core is None:
        deny("COMMITMENT_NOT_FOUND", "Commitment not found in current tenant", 404)
    return db.scalar(select(ConfirmationSessionRecord).where(
        ConfirmationSessionRecord.tenant_id == context.tenant_id,
        ConfirmationSessionRecord.confirmation_id == confirmation_id,
    ).with_for_update().execution_options(populate_existing=True))


def emit(db, context, task, event_type, now, *, evidence_refs, reminder=None):
    payload = {"task_id": task.task_id, "communication_id": task.communication_id,
        "confirmation_id": task.confirmation_id, "proposal_id": task.proposal_id,
        "proposal_version": task.proposal_version, "policy_version": task.policy["version"],
        "status": task.status, "reason_code": task.reason_code, "reminders_sent": task.reminders_sent,
        "evidence_refs": evidence_refs, "provider_mode": "LOCAL_MOCK", "evidence_scope": "P4_FOLLOWUP_ONLY"}
    if reminder:
        payload.update(reminder_id=reminder.reminder_id, sequence=reminder.sequence,
            delivery_status=reminder.status, content_hash=reminder.content_hash,
            provider_reference=reminder.provider_reference)
    # No identity, token, message body or customer response is copied into events.
    core = db.get(CommitmentRecord, (context.tenant_id, task.commitment_id))
    event = create_domain_event(event_type=event_type, tenant_id=context.tenant_id,
        commitment_id=task.commitment_id, commitment_version=core.commitment_version,
        correlation_id=context.correlation_id, causation_id=task.confirmation_id,
        occurred_at=now, payload=payload)
    db.add(OutboxEventRecord(event_id=event.event_id, tenant_id=context.tenant_id,
        event_type=event_type, commitment_id=event.commitment_id, commitment_version=event.commitment_version,
        correlation_id=event.correlation_id, causation_id=event.causation_id, occurred_at=now,
        payload=payload, status="PENDING", attempts=0))
    db.add(AuditEventRecord(audit_id=f"audit_{uuid4().hex}", tenant_id=context.tenant_id,
        commitment_id=task.commitment_id, event_type=event_type, actor_id=context.actor_id,
        actor_role=context.actor_role, dimension="communication", previous_state=None, new_state=payload,
        evidence_refs=evidence_refs, reason="Durable follow-up; delivery is not acceptance or fulfilment",
        correlation_id=event.correlation_id, causation_id=event.causation_id, occurred_at=now))


def cancel_for_confirmation(db, context, confirmation, reason, now):
    """Participates in caller transaction; NEVER commits independently."""
    rows = db.scalars(select(FollowUpTaskRecord).where(
        FollowUpTaskRecord.tenant_id == context.tenant_id,
        FollowUpTaskRecord.confirmation_id == confirmation.confirmation_id,
    ).with_for_update().execution_options(populate_existing=True)).all()
    for task in rows:
        if task.status in {"CANCELLED", "ESCALATED"}:
            continue
        task.status, task.reason_code, task.next_due_at, task.updated_at = "CANCELLED", reason, None, now
        emit(db, context, task, "communication.followup_cancelled", now,
             evidence_refs=[f"p4:confirmation:{confirmation.confirmation_id}"])


class FollowUpService:
    def __init__(self, db, authority, confirmations, outbound, preferences):
        self.db, self.authority, self.confirmations = db, authority, confirmations
        self.outbound, self.preferences = outbound, preferences

    def _grant(self, context, action, now, confirmation_id=None, policy=None):
        _require_context(context)
        digest = fingerprint(policy) if policy is not None else None
        if self.authority is None:
            deny("FOLLOWUP_AUTHORITY_UNAVAILABLE", "Trusted follow-up authorization is unavailable", 503)
        grant = self.authority.authorize(self.db, context, action=action,
            confirmation_id=confirmation_id, policy_digest=digest, now=now)
        if not isinstance(grant, ReminderAuthorization):
            deny("FOLLOWUP_FORBIDDEN", "Explicit trusted follow-up authorization is required", 403)
        try:
            grant = ReminderAuthorization.model_validate(grant.model_dump())
        except ValidationError:
            deny("FOLLOWUP_AUTHORITY_INVALID", "Trusted follow-up authorization is invalid", 503)
        if (grant.tenant_id, grant.actor_id, grant.action, grant.confirmation_id, grant.policy_digest) != (
            context.tenant_id, context.actor_id, action, confirmation_id, digest) or grant.expires_at <= now:
            deny("FOLLOWUP_FORBIDDEN", "Authorization is expired or bound to another scope", 403)
        return grant

    @staticmethod
    def view(row):
        values = {name: getattr(row, name) for name in FollowUpView.model_fields}
        for name in ("next_due_at", "escalation_at", "last_reminder_at", "created_at", "updated_at"):
            if values[name] is not None:
                values[name] = stored_time(values[name])
        return FollowUpView(**values)

    def list(self, context):
        try:
            self._grant(context, "READ_FOLLOWUP", utc())
            return [self.view(row) for row in self.db.scalars(select(FollowUpTaskRecord).where(
                FollowUpTaskRecord.tenant_id == context.tenant_id).order_by(FollowUpTaskRecord.created_at))]
        finally:
            self.db.rollback()

    def _task(self, context, task_id):
        task = self.db.get(FollowUpTaskRecord, (context.tenant_id, task_id))
        if task is None:
            deny("FOLLOWUP_NOT_FOUND", "Follow-up not found in tenant", 404)
        confirmation = lock_confirmation(self.db, context, task.confirmation_id)
        task = self.db.scalar(select(FollowUpTaskRecord).where(
            FollowUpTaskRecord.tenant_id == context.tenant_id, FollowUpTaskRecord.task_id == task_id,
        ).with_for_update().execution_options(populate_existing=True))
        return task, confirmation

    def _current(self, context, row, now):
        if row.consumed_at is not None or row.revoked_at is not None or stored_time(row.expires_at) <= now:
            deny("FOLLOWUP_CONFIRMATION_INACTIVE", "Confirmation is terminal, expired or revoked", 409)
        outbound = self.confirmations._outbound(context, row.outbound_id)
        basis = self.confirmations._basis(context, outbound, now)
        if basis.model_dump(mode="json") != row.binding:
            deny("CONFIRMATION_PROPOSAL_CHANGED", "Current proposal or approval differs from confirmation", 409)
        if self.preferences is None:
            deny("CONSENT_AUTHORITY_UNAVAILABLE", "Current recipient permission is unavailable", 503)
        self.preferences.check(context, basis.customer_id, basis.channel, basis.recipient_identity_id, now=now)
        return outbound, basis

    def schedule(self, context, command, *, now=None):
        now = utc(now)
        policy = command.policy.model_dump(mode="json")
        try:
            grant = self._grant(context, "SCHEDULE_FOLLOWUP", now, command.confirmation_id, policy)
            row = lock_confirmation(self.db, context, command.confirmation_id)
            prior = self.db.scalar(select(FollowUpTaskRecord).where(
                FollowUpTaskRecord.tenant_id == context.tenant_id,
                FollowUpTaskRecord.request_key == command.request_key))
            digest = fingerprint(command.model_dump(mode="json"))
            if prior:
                if prior.command_hash != digest:
                    deny("FOLLOWUP_IDEMPOTENCY_CONFLICT", "Key belongs to a different schedule", 409)
                return self.view(prior)  # Never revive cancelled/escalated work.
            self._current(context, row, now)
            basis = ConfirmationBasis.model_validate(row.binding)
            # Scheduling late must not silently extend the customer's SLA.
            due = stored_time(row.created_at) + timedelta(seconds=command.policy.response_sla_seconds)
            escalation = due + timedelta(seconds=(command.policy.max_reminders - 1) *
                command.policy.minimum_interval_seconds + command.policy.escalation_delay_seconds)
            escalation = max(due, escalation)
            if escalation >= stored_time(row.expires_at):
                deny("FOLLOWUP_SLA_EXCEEDS_EXPIRY", "SLA must fit within the trusted confirmation expiry", 422)
            task = FollowUpTaskRecord(tenant_id=context.tenant_id, task_id=f"followup_{uuid4().hex}",
                communication_id=row.communication_id, confirmation_id=row.confirmation_id,
                commitment_id=basis.reference.commitment_id, proposal_id=basis.reference.proposal_id,
                proposal_version=basis.reference.proposal_version, request_key=command.request_key,
                command_hash=digest, policy=policy, status="WAITING", reminders_sent=0,
                next_due_at=due, escalation_at=escalation, created_at=now, updated_at=now)
            self.db.add(task)
            self.db.flush()
            emit(self.db, context, task, "communication.followup_scheduled", now, evidence_refs=grant.evidence_refs)
            value = self.view(task)
            self.db.commit()
            return value
        except IntegrityError:
            deny("FOLLOWUP_ALREADY_SCHEDULED", "One follow-up workflow per communication across all channels", 409)
        except SQLAlchemyError as error:
            raise DomainError("FOLLOWUP_STORAGE_UNAVAILABLE", "Schedule could not be persisted", status_code=503) from error
        finally:
            self.db.rollback()

    def cancel(self, context, task_id, reason, *, now=None):
        now = utc(now)
        try:
            self._grant(context, "READ_FOLLOWUP", now)
            task, row = self._task(context, task_id)
            self._grant(context, "CANCEL_FOLLOWUP", now, row.confirmation_id, task.policy)
            # Store a bounded reason category, not untrusted free text in events.
            cancel_for_confirmation(self.db, context, row, "MANUAL_CANCELLATION", now)
            value = self.view(task)
            self.db.commit()
            return value
        finally:
            self.db.rollback()

    def run_due(self, context, *, now=None, limit=50):
        """Bounded, tenant-scoped deterministic entry point. No caller clock via HTTP."""
        supplied_time = now
        now = utc(now)
        try:
            self._grant(context, "READ_FOLLOWUP", now)
            identifiers = list(self.db.scalars(select(FollowUpTaskRecord.task_id).where(
                FollowUpTaskRecord.tenant_id == context.tenant_id,
                FollowUpTaskRecord.status.in_(["WAITING", "BLOCKED", "DISPATCHING"]),
                FollowUpTaskRecord.next_due_at <= now,
            ).order_by(FollowUpTaskRecord.next_due_at, FollowUpTaskRecord.task_id).limit(min(max(limit, 1), 100))))
        finally:
            self.db.rollback()
        return [self.process(context, identifier, now=supplied_time) for identifier in identifiers]

    def _state(self, context, task, status, reason, now, refs):
        if (task.status, task.reason_code) != (status, reason):
            task.status, task.reason_code, task.updated_at = status, reason, now
            if status in {"CANCELLED", "ESCALATED"}:
                task.next_due_at = None
            event = "communication.escalation_required" if status == "ESCALATED" else "communication.followup_" + status.lower()
            emit(self.db, context, task, event, now, evidence_refs=refs)

    def _validate_dispatch(self, context, task, row, now):
        grant = self._grant(context, "DISPATCH_REMINDER", now, row.confirmation_id, task.policy)
        outbound, basis = self._current(context, row, now)
        draft, review, send_grant = self.outbound._validate(context, outbound.communication_id, outbound.draft_id, now)
        policy = SLAPolicy.model_validate(task.policy)
        local = now.astimezone(ZoneInfo(policy.timezone))
        if not policy.contact_hours.start_hour <= local.hour < policy.contact_hours.end_hour:
            deny("CONTACT_HOURS_RESTRICTED", "Outside SLA contact hours", 403)
        return draft, grant, send_grant

    def process(self, context, task_id, *, now=None):
        supplied_time = now
        # Test clocks stay deterministic; real processing re-reads wall time
        # after the durable claim and any lock wait, before external effects.
        clock = lambda: utc(supplied_time)
        now = clock()
        try:
            self._grant(context, "READ_FOLLOWUP", now)
            task, row = self._task(context, task_id)
            grant = self._grant(context, "DISPATCH_REMINDER", now, row.confirmation_id, task.policy)
            if task.status in {"CANCELLED", "ESCALATED"}:
                return self.view(task)
            if task.status == "DISPATCHING":
                # Recovery is escalation, never another provider call. The
                # conservative intent survives a crash at every send boundary.
                if now >= stored_time(task.escalation_at):
                    self._state(context, task, "ESCALATED", "REMINDER_OUTCOME_UNRECONCILED", now, grant.evidence_refs)
                    value = self.view(task)
                    self.db.commit()
                    return value
                return self.view(task)
            if stored_time(task.next_due_at) > now:
                return self.view(task)
            if row.consumed_at or row.revoked_at or stored_time(row.expires_at) <= now:
                self._state(context, task, "CANCELLED", "CONFIRMATION_INACTIVE", now, grant.evidence_refs)
            elif now >= stored_time(task.escalation_at):
                self._state(context, task, "ESCALATED", "RESPONSE_SLA_EXCEEDED", now, grant.evidence_refs)
            else:
                policy = SLAPolicy.model_validate(task.policy)
                if task.reminders_sent >= policy.max_reminders:
                    task.next_due_at = task.escalation_at
                else:
                    try:
                        draft, grant, send_grant = self._validate_dispatch(context, task, row, now)
                    except DomainError as error:
                        self._state(context, task, "CANCELLED" if error.code in {"CONSENT_REVOKED", "CONSENT_EXPIRED"} else "BLOCKED",
                            error.code, now, grant.evidence_refs)
                        # Contact-hour restriction defers deterministically, never bypasses consent.
                        if error.code == "CONTACT_HOURS_RESTRICTED":
                            task.next_due_at = min(now + timedelta(minutes=15), stored_time(task.escalation_at))
                    else:
                        return self._submit(context, task, row, draft, grant, send_grant, now, clock)
            value = self.view(task)
            self.db.commit()
            return value
        finally:
            self.db.rollback()

    def _submit(self, context, task, row, draft, grant, send_grant, now, clock):
        # Only the network-free P4 local provider is allowed on this path.
        if type(self.outbound.provider) is not LocalMockProvider:
            deny("REMINDER_PROVIDER_UNSUPPORTED", "Reminders support only the built-in local mock", 503)
        reminder = ReminderAttemptRecord(tenant_id=context.tenant_id, reminder_id=f"reminder_{uuid4().hex}",
            task_id=task.task_id, sequence=task.reminders_sent + 1, status="DELIVERY_UNKNOWN",
            evidence_refs=grant.evidence_refs + send_grant.evidence_refs, content_hash=draft.content_hash,
            channel=draft.channel, error_code="PROVIDER_RESULT_PENDING", started_at=now)
        task.status, task.reason_code, task.updated_at = "DISPATCHING", "PROVIDER_RESULT_PENDING", now
        self.db.add(reminder)
        self.db.flush()
        emit(self.db, context, task, "communication.followup_due", now,
            evidence_refs=reminder.evidence_refs, reminder=reminder)
        fallback = self.view(task)
        reminder_id, task_id = reminder.reminder_id, task.task_id
        self.db.commit()  # UNKNOWN intent is durable BEFORE any possible effect.
        try:
            task, row = self._task(context, task_id)
            if task.status != "DISPATCHING":
                return self.view(task)  # Terminal response/cancel won after intent commit.
            now = clock()
            draft, grant, send_grant = self._validate_dispatch(context, task, row, now)
            reminder = self.db.get(ReminderAttemptRecord, (context.tenant_id, reminder_id))
            reminder.evidence_refs = list(dict.fromkeys(reminder.evidence_refs + grant.evidence_refs + send_grant.evidence_refs))
            # Locks held through provider and result commit; never blindly retry UNKNOWN.
            try:
                result = self.outbound.provider.submit(SendEnvelope(reminder_id, draft))
                if not isinstance(result, ProviderResult) or result.status not in {"SENT", "FAILED", "DELIVERY_UNKNOWN"}:
                    raise ValueError("Invalid result")
                if result.status == "SENT" and not result.provider_reference:
                    raise ValueError("Missing provider evidence")
            except TimeoutError:
                result = ProviderResult("DELIVERY_UNKNOWN", error_code="PROVIDER_TIMEOUT")
            except Exception:
                result = ProviderResult("DELIVERY_UNKNOWN", error_code="PROVIDER_RESULT_UNCERTAIN")
            reminder.status, reminder.provider_reference = result.status, result.provider_reference
            reminder.error_code, reminder.finished_at = result.error_code, now
            if result.status == "SENT":
                policy = SLAPolicy.model_validate(task.policy)
                task.reminders_sent += 1
                task.last_reminder_at = now
                task.status, task.reason_code = "WAITING", None
                task.next_due_at = min(now + timedelta(seconds=policy.minimum_interval_seconds), stored_time(task.escalation_at))
            else:
                self._state(context, task, "ESCALATED", "REMINDER_" + result.status, now, reminder.evidence_refs)
            task.updated_at = now
            emit(self.db, context, task, "communication.reminder_result", now,
                evidence_refs=reminder.evidence_refs, reminder=reminder)
            value = self.view(task)
            self.db.commit()
            return value
        except DomainError:
            # Authority changed after the durable claim: leave UNKNOWN/DISPATCHING
            # for operator reconciliation. No provider submission took place.
            self.db.rollback()
            raise
        except SQLAlchemyError:
            self.db.rollback()
            return fallback
