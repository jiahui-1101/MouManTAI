"""Versioned protocol and recipient-only challenge delivery; no raw-token storage."""
import base64
import hashlib
import hmac
import os
import re
from uuid import uuid4

from sqlalchemy import select
from .confirmations import ConfirmationService, token_digest
from .models import ConfirmationSessionRecord
from .preferences import stored_time
from .templates import fingerprint
from .providers import ChallengeDelivery, SendEnvelope
from .demo_policy import deny

PROTOCOL_TEMPLATE = "delivery_change_secure"
PROTOCOL_VERSION = 2
_delivery_sink = None


def configure_isolated_delivery_sink(sink):
    """Server composition only. No API installs or reads a recipient mailbox."""
    global _delivery_sink
    _delivery_sink = sink


def isolated_delivery_sink(): return _delivery_sink


def signing_key():
    value = os.getenv("P4_CHALLENGE_SIGNING_KEY", "")
    if len(value) < 32 or value in {os.getenv("MOUMANTAI_ISOLATED_E2E_KEY"), os.getenv("P4_ISOLATED_PROCESSOR_KEY"), os.getenv("P4_ISOLATED_WORKER_KEY")}:
        deny("CHALLENGE_KEY_UNAVAILABLE", "A separate server challenge key is required", 503)
    return value.encode()


def secret_for(row):
    binding = {"confirmation_id": row.confirmation_id, "outbound_id": row.outbound_id,
        "tenant_id": row.tenant_id, "recipient": row.recipient_identity_id,
        "basis": row.binding, "expires_at": stored_time(row.expires_at).isoformat()}
    return base64.urlsafe_b64encode(hmac.new(signing_key(), fingerprint(binding).encode(), hashlib.sha256).digest()).decode().rstrip("=")


class BoundChallengeDelivery:
    def __init__(self, authority): self.authority = authority

    def prepare(self, db, context, outbound, draft, now):
        if draft.template_key != PROTOCOL_TEMPLATE or draft.template_version != PROTOCOL_VERSION:
            deny("SECURE_REPLY_TEMPLATE_REQUIRED", "Review the secure reply template before sending", 409)
        signing_key()
        if isolated_delivery_sink() is None:
            deny("CUSTOMER_DELIVERY_PORT_UNAVAILABLE", "Trusted recipient delivery sink is not registered", 503)
        basis = self.authority.current_basis(db, context, outbound, now=now)
        row = ConfirmationSessionRecord(tenant_id=context.tenant_id, confirmation_id=f"conf_{uuid4().hex}",
            outbound_id=outbound.outbound_id, communication_id=outbound.communication_id, draft_id=outbound.draft_id,
            approved_review_id=outbound.approved_review_id, customer_id=basis.customer_id,
            recipient_identity_id=basis.recipient_identity_id, channel=basis.channel,
            token_digest="pending", binding=basis.model_dump(mode="json"), state="AWAITING_RESPONSE",
            created_by=context.actor_id, created_at=now, expires_at=basis.expires_at)
        row.token_digest = token_digest(secret_for(row))
        db.add(row)
        db.flush()
        envelope = self.envelope(db, context, outbound, draft, now)
        outbound.authorization_evidence = {**outbound.authorization_evidence,
            "challenge_confirmation_id": row.confirmation_id, "challenge_protocol_version": PROTOCOL_VERSION,
            "delivery_payload_hash": envelope.challenge.payload_hash}
        # Shared factory/envelope remain v1; no raw transport code enters events.
        ConfirmationService(db, None, self.authority, None)._event(context, row, "confirmation.created", now)

    def envelope(self, db, context, outbound, draft, now):
        row = db.scalar(select(ConfirmationSessionRecord).where(
            ConfirmationSessionRecord.tenant_id == context.tenant_id,
            ConfirmationSessionRecord.outbound_id == outbound.outbound_id).execution_options(populate_existing=True))
        if row is None or row.revoked_at or row.consumed_at or stored_time(row.expires_at) <= now:
            deny("CONFIRMATION_INACTIVE", "Bound delivery challenge is unavailable", 409)
        basis = self.authority.current_basis(db, context, outbound, now=now)
        if basis.model_dump(mode="json") != row.binding:
            deny("CONFIRMATION_PROPOSAL_CHANGED", "Delivery challenge no longer binds current terms", 409)
        secret = secret_for(row)
        if not hmac.compare_digest(token_digest(secret), row.token_digest):
            deny("CHALLENGE_KEY_CHANGED", "Challenge key changed; old intent cannot be replayed", 409)
        ref = basis.reference
        reply = f"CONFIRM {row.confirmation_id} {secret}\nACCEPT {ref.proposal_id} v{ref.proposal_version} terms:{basis.terms_digest}"
        body = draft.body + "\n\n" + reply
        digest = fingerprint({"tenant_id": context.tenant_id, "recipient_identity_id": row.recipient_identity_id,
            "channel": row.channel, "subject": draft.subject, "body": body})
        saved_hash = outbound.authorization_evidence.get("delivery_payload_hash")
        if saved_hash is not None and saved_hash != digest:
            deny("CHALLENGE_PAYLOAD_CHANGED", "Transport differs from durable authorized payload hash", 409)
        return SendEnvelope(outbound.outbound_id, draft, ChallengeDelivery(row.confirmation_id, body, digest))


def parse_customer_reply(text):
    match = re.fullmatch(r"CONFIRM (conf_[a-z0-9]+) ([A-Za-z0-9_-]{43,128})\r?\n(.+)", text, re.DOTALL)
    if match is None:
        deny("CONFIRMATION_PROTOCOL_INVALID", "Use the delivered bound response protocol", 422)
    return match.groups()
