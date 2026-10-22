"""P4 owns outbound consent. P1 contact verification alone never opts in."""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.events import create_domain_event
from app.core.errors import DomainError
from app.core.models import OutboxEventRecord
from app.core.schemas import ContractModel, OffsetAwareDatetime
from .contacts import DirectoryContactAdapter
from .demo_policy import SyntheticScope, deny
from .models import RecipientPreferenceRecord, RecipientPreferenceChangeRecord
from .templates import fingerprint

PURPOSE = "TRANSACTIONAL_REVISED_TERMS"
POLICY = "p4-consent-v1"
Channel = Literal["MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"]
Id = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r"^\S+$")]


def utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("explicit time offset required")
    return value.astimezone(timezone.utc)


def stored_time(value):
    # SQLite loses timezone on storage; PostgreSQL uses TIMESTAMPTZ.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class ContactHours(ContractModel):
    start_hour: int = Field(default=0, strict=True, ge=0, le=23)
    end_hour: int = Field(default=24, strict=True, ge=1, le=24)

    @model_validator(mode="after")
    def valid(self):
        if self.end_hour <= self.start_hour:
            raise ValueError("Use one same-day interval; overnight windows are unsupported")
        return self


class PreferenceCommand(ContractModel):
    request_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    customer_id: Id
    channel: Channel
    consent_purpose: Literal["TRANSACTIONAL_REVISED_TERMS"] = PURPOSE
    consent_status: Literal["OPTED_IN", "OPTED_OUT"]
    consent_evidence_ref: str = Field(min_length=20, max_length=256, pattern=r"^synthetic:consent:[A-Za-z0-9_-]+$")
    source: Literal["SYNTHETIC_FIXTURE"]
    consent_expires_at: OffsetAwareDatetime
    allowed_contact_hours: ContactHours = Field(default_factory=ContactHours)
    timezone: Literal["UTC", "Asia/Kuala_Lumpur"] = "Asia/Kuala_Lumpur"
    expected_version: int = Field(strict=True, ge=0)


class PreferenceView(ContractModel):
    tenant_id: str
    customer_id: str
    channel: Channel
    consent_purpose: str
    recipient_identity_id: str
    consent_status: Literal["OPTED_IN", "OPTED_OUT"]
    consent_evidence_ref: str
    source: str
    consent_recorded_at: OffsetAwareDatetime
    consent_expires_at: OffsetAwareDatetime
    revoked_at: OffsetAwareDatetime | None
    allowed_contact_hours: ContactHours
    timezone: str
    version: int
    policy_version: str
    last_audit_id: str
    updated_at: OffsetAwareDatetime
    updated_by_actor_id: str


class PreferenceService:
    def __init__(self, db, scope: SyntheticScope, directory):
        self.db, self.scope = db, scope
        self.contacts = DirectoryContactAdapter(directory)

    @staticmethod
    def view(row):
        values = {key: getattr(row, key) for key in PreferenceView.model_fields}
        for key in ("consent_recorded_at", "consent_expires_at", "revoked_at", "updated_at"):
            if values[key] is not None:
                values[key] = stored_time(values[key]).astimezone(timezone.utc)
        return PreferenceView(**values)

    def record(self, tenant, customer, channel, purpose=PURPOSE):
        return self.db.scalar(select(RecipientPreferenceRecord).where(
            RecipientPreferenceRecord.tenant_id == tenant, RecipientPreferenceRecord.customer_id == customer,
            RecipientPreferenceRecord.channel == channel, RecipientPreferenceRecord.consent_purpose == purpose,
        ).with_for_update().execution_options(populate_existing=True))

    def list(self, context):
        self.scope.require(context)
        try:
            return [self.view(row) for row in self.db.scalars(select(RecipientPreferenceRecord).where(
                RecipientPreferenceRecord.tenant_id == context.tenant_id).order_by(
                    RecipientPreferenceRecord.customer_id, RecipientPreferenceRecord.channel))]
        except SQLAlchemyError as exc:
            raise DomainError("CONSENT_STORAGE_UNAVAILABLE", "Recipient preference storage is unavailable", status_code=503) from exc
        finally:
            self.db.rollback()

    def save(self, context, command: PreferenceCommand, *, now=None):
        self.scope.require(context, manager=True)  # Explicit P4 consent guard, not APPROVE_DRAFT.
        now = utc(now)
        digest = fingerprint(command.model_dump(mode="json"))
        try:
            for attempt in range(2):
                try:
                    result = self._save(context, command, now, digest)
                    self.db.commit()
                    return result
                except IntegrityError:
                    self.db.rollback()
                    if attempt:
                        deny("CONSENT_VERSION_CONFLICT", "Concurrent consent change; reload preferences", 409)
        except DomainError:
            self.db.rollback()
            raise
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise DomainError("CONSENT_STORAGE_UNAVAILABLE", "Recipient preference storage is unavailable", status_code=503) from exc

    def _save(self, context, command, now, digest):
        def receipt():
            return self.db.scalar(select(RecipientPreferenceChangeRecord).where(
            RecipientPreferenceChangeRecord.tenant_id == context.tenant_id,
            RecipientPreferenceChangeRecord.request_key == command.request_key).execution_options(populate_existing=True))
        def replay(prior):
            if prior.command_hash != digest or prior.actor_id != context.actor_id:
                deny("CONSENT_IDEMPOTENCY_CONFLICT", "Request key already used for another change", 409)
            return PreferenceView.model_validate(prior.new_state)
        prior = receipt()
        if prior:
            # Retry returns the original receipt, never reactivates a newer opt-out.
            return replay(prior)
        row = self.record(context.tenant_id, command.customer_id, command.channel)
        # A concurrent creator may commit between the first receipt read and row
        # lock. Recheck after acquiring it before reporting a version conflict.
        if row is not None:
            prior = receipt()
            if prior:
                return replay(prior)
        if command.expected_version != (row.version if row else 0):
            deny("CONSENT_VERSION_CONFLICT", "Preference changed; reload before saving", 409)
        if command.consent_status == "OPTED_OUT" and row is None:
            deny("CONSENT_NOT_FOUND", "No stored permission to revoke", 404)
        if command.consent_status == "OPTED_IN":
            identity = self.contacts.resolve(context.tenant_id, command.customer_id, command.channel).sender_identity_id
            if not now < command.consent_expires_at <= now + timedelta(days=30):
                deny("CONSENT_EXPIRY_INVALID", "Synthetic consent must expire within 30 days", 422)
            # Re-opting in after contact/consent changes requires new, explicit evidence.
            if row and row.consent_evidence_ref == command.consent_evidence_ref:
                deny("CONSENT_EVIDENCE_REUSED", "Use a new evidence reference for a new permission decision", 409)
        else:
            # Revocation must work even if P1 is offline, contact changed, or expired.
            identity = row.recipient_identity_id
        previous = self.view(row).model_dump(mode="json") if row else None
        audit_id = f"consent_{uuid4().hex}"
        if row is None:
            row = RecipientPreferenceRecord(tenant_id=context.tenant_id, customer_id=command.customer_id,
                channel=command.channel, consent_purpose=PURPOSE)
            self.db.add(row)
        row.recipient_identity_id = identity
        row.consent_status = command.consent_status
        row.consent_evidence_ref = command.consent_evidence_ref
        row.source = command.source
        # An opt-out changes status immediately, preserving the previous grant interval.
        if command.consent_status == "OPTED_IN":
            row.consent_recorded_at, row.consent_expires_at = now, command.consent_expires_at.astimezone(timezone.utc)
        row.revoked_at = now if command.consent_status == "OPTED_OUT" else None
        row.allowed_contact_hours = command.allowed_contact_hours.model_dump()
        row.timezone, row.version = command.timezone, command.expected_version + 1
        row.policy_version, row.last_audit_id = POLICY, audit_id
        row.updated_at, row.updated_by_actor_id = now, context.actor_id
        self.db.flush()  # Parent before exact-scope journal FK.
        view = self.view(row)
        snapshot = view.model_dump(mode="json")
        self.db.add(RecipientPreferenceChangeRecord(tenant_id=context.tenant_id, audit_id=audit_id,
            request_key=command.request_key, command_hash=digest, customer_id=row.customer_id, channel=row.channel,
            consent_purpose=PURPOSE, version=row.version, previous_state=previous, new_state=snapshot,
            actor_id=context.actor_id, actor_role=context.actor_role, correlation_id=context.correlation_id, occurred_at=now))
        event = create_domain_event(event_type="communication.recipient_preference_changed", tenant_id=context.tenant_id,
            correlation_id=context.correlation_id, causation_id=context.causation_id, occurred_at=now,
            payload={"audit_id": audit_id, "customer_id": row.customer_id, "channel": row.channel,
                     "version": row.version, "consent_status": row.consent_status, "source": row.source})
        self.db.add(OutboxEventRecord(event_id=event.event_id, tenant_id=context.tenant_id, event_type=event.event_type,
            commitment_id=None, commitment_version=None, correlation_id=event.correlation_id, causation_id=event.causation_id,
            occurred_at=now, payload=event.payload, attempts=0, status="PENDING"))
        self.db.flush()
        return view

    def check(self, context, customer, channel, identity, *, now=None):
        """Read current policy inside caller's transaction, locking through send."""
        self.scope.require(context)
        now = utc(now)
        contact = self.contacts.resolve(context.tenant_id, customer, channel)
        if contact.sender_identity_id != identity:
            deny("CONTACT_CHANGED", "Current P1 contact differs from the draft", 409)
        row = self.record(context.tenant_id, customer, channel)
        if row is None:
            deny("CONSENT_REQUIRED", "Explicit transactional permission is required")
        if row.consent_status != "OPTED_IN" or row.revoked_at is not None:
            deny("CONSENT_REVOKED", "Recipient permission was revoked")
        if row.recipient_identity_id != identity:
            deny("CONSENT_RECIPIENT_CHANGED", "Stored permission belongs to an older contact", 409)
        view = self.view(row)
        if not view.consent_recorded_at <= now < view.consent_expires_at:
            deny("CONSENT_EXPIRED", "Recipient permission is not currently valid")
        journal = self.db.get(RecipientPreferenceChangeRecord, (context.tenant_id, row.last_audit_id), populate_existing=True)
        if (view.policy_version != POLICY or view.source != "SYNTHETIC_FIXTURE" or
            not view.consent_evidence_ref.startswith("synthetic:consent:") or journal is None or
            journal.new_state != view.model_dump(mode="json") or
            journal.actor_id != view.updated_by_actor_id or journal.actor_role not in {"OWNER", "MANAGER"}):
            deny("CONSENT_EVIDENCE_INVALID", "Consent policy/audit provenance cannot be verified")
        try:
            local = now.astimezone(ZoneInfo(view.timezone))
        except (ZoneInfoNotFoundError, ValueError):
            deny("CONSENT_TIMEZONE_UNAVAILABLE", "Configured contact timezone is unavailable", 503)
        hours = view.allowed_contact_hours
        if not hours.start_hour <= local.hour < hours.end_hour:
            deny("CONTACT_HOURS_RESTRICTED", "Outside allowed contact hours")
        return view
