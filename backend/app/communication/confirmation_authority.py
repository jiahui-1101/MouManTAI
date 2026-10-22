"""Confirmation authority ports, reusing P4 currentness and P1-owned identity."""
from typing import TYPE_CHECKING, Protocol

from app.core.dependencies import RequestContext
from .contacts import DirectoryContactAdapter
from .demo_policy import SyntheticScope, deny
from .confirmation_schemas import ConfirmationBasis, VerifiedInboundResponse
from .review import DraftReviewService
from .schemas import CreateCommunicationRequest
from .service import CommunicationRequestService
from .templates import fingerprint

if TYPE_CHECKING:
    from app.context.repository import MessageRepository
    from app.context.customer_directory import CustomerDirectory


class ConfirmationAccess(Protocol):
    def authorize(self, context: RequestContext, action: str) -> None: ...


class ConfirmationAuthority(Protocol):
    def current_basis(self, db, context, outbound, *, now) -> ConfirmationBasis: ...


class VerifiedInboundAuthority(Protocol):
    def resolve(self, db, context, message_id: str, *, now) -> VerifiedInboundResponse: ...


class RuntimeConfirmationAccess:
    def authorize(self, context, action):
        scope = SyntheticScope.from_environment()
        scope.require(context, manager=True)
        if action not in {"CREATE_CONFIRMATION", "READ_CONFIRMATION", "REVOKE_CONFIRMATION"}:
            # Existing demo headers cannot authenticate a normalized inbound
            # provider/processor. Do not mint a service grant from an actor ID.
            deny("CONFIRMATION_PROCESSOR_AUTH_UNAVAILABLE", "Authenticated inbound processing authority is unavailable", 503)

    def validate_storage(self, db):
        # This release has only synthetic header authorization. Keep its new
        # confirmation surface on explicitly named disposable PostgreSQL DBs,
        # checked against the ACTUAL Session bind, not a caller/header/env claim.
        url = db.get_bind().engine.url
        if not url.drivername.startswith("postgresql") or not (
            url.database == "p4_migration_test" or (url.database or "").startswith("p4_test_")
        ):
            deny("CONFIRMATION_DISPOSABLE_SCOPE_REQUIRED", "Synthetic confirmation access requires a dedicated disposable PostgreSQL database", 503)


class ExistingP4ConfirmationAuthority:
    def __init__(self, drafts, reviews):
        self.drafts, self.reviews = drafts, reviews

    def current_basis(self, db, context, outbound, *, now):
        draft, review = DraftReviewService(db, self.drafts, self.reviews).validate_for_send(
            context, outbound.communication_id, outbound.draft_id, now=now)
        if (outbound.approved_review_id != review.review_id or outbound.content_hash != draft.content_hash or
            outbound.validation_hash != draft.validation_hash or outbound.channel != draft.channel or
            outbound.recipient_identity_id != draft.recipient_identity_id):
            deny("CONFIRMATION_OUTBOUND_CHANGED", "Outbound does not bind this exact current draft/review", 409)
        current = CommunicationRequestService(db).read_current_basis(context,
            CreateCommunicationRequest(source_event_id=draft.reference.source_event_id), now)
        if current.reference != draft.reference or current.terms != draft.approved_terms:
            deny("CONFIRMATION_PROPOSAL_CHANGED", "Current Core proposal differs from the approved draft", 409)
        return ConfirmationBasis(reference=current.reference, customer_id=current.customer_id,
            recipient_identity_id=draft.recipient_identity_id, channel=draft.channel,
            content_hash=draft.content_hash, validation_hash=draft.validation_hash,
            terms_digest=fingerprint(current.terms.model_dump(mode="json")),
            approval_evidence_refs=draft.approval_evidence_refs,
            expires_at=min(draft.expires_at, review.expires_at))


class UnavailableVerifiedInboundAuthority:
    def resolve(self, db, context, message_id, *, now):
        deny("VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE", "P1 authenticated normalized inbound evidence is not connected", 503)


class P1SyntheticInboundAdapter:
    """Explicitly injected synthetic P1 repository + directory. Never a default.

    Production cannot use P1's synthetic sender directory as identity proof. This
    adapter consumes existing P1 records; it never parses webhooks, sets LINK_VERIFIED
    or creates a customer. The caller still needs separate processor authorization.
    """
    def __init__(self, source: "MessageRepository", directory: "CustomerDirectory", scope: SyntheticScope):
        self.source, self.contacts, self.scope = source, DirectoryContactAdapter(directory), scope

    def resolve(self, db, context, message_id, *, now):
        self.scope.require(context)
        try:
            message = self.source.get(context.tenant_id, message_id)
            association = self.source.get_association(context.tenant_id, message_id)
        except Exception:
            deny("VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE", "P1 normalized evidence cannot currently be read", 503)
        if message is None or message.message_id != message_id or message.raw.tenant_id != context.tenant_id:
            deny("CONFIRMATION_INBOUND_NOT_FOUND", "Inbound evidence not found in tenant", 404)
        if (association is None or association.tenant_id != context.tenant_id or association.message_id != message_id or
            association.status != "LINK_VERIFIED" or association.conflicts or association.verified_customer is None):
            deny("CONFIRMATION_IDENTITY_UNVERIFIED", "P1 has not verified an unambiguous sender/customer link")
        customer = association.verified_customer
        if customer.tenant_id != context.tenant_id or customer.active is not True:
            deny("CONFIRMATION_IDENTITY_MISMATCH", "P1 customer scope or active status is invalid")
        mapping = {"WHATSAPP": "MOCK_WHATSAPP", "EMAIL": "MOCK_EMAIL", "TELEGRAM": "MOCK_TELEGRAM"}
        channel = mapping.get(message.raw.channel)
        if channel is None or message.synthetic_provider != f"SYNTHETIC_{message.raw.channel}":
            deny("CONFIRMATION_CHANNEL_MISMATCH", "Unsupported or non-synthetic inbound channel")
        contact = self.contacts.resolve(context.tenant_id, customer.customer_id, channel)
        if contact.sender_identity_id != message.raw.sender_identity_id:
            deny("CONFIRMATION_IDENTITY_MISMATCH", "Current P1 contact differs from inbound sender")
        return VerifiedInboundResponse(tenant_id=context.tenant_id, message_id=message_id,
            provider_message_id=message.raw.provider_message_id, customer_id=customer.customer_id,
            recipient_identity_id=contact.sender_identity_id, channel=channel, text=message.raw.text,
            source_digest=message.content_sha256,
            evidence_refs=[f"p1:message:{message_id}:sha256:{message.content_sha256}",
                f"p1:association:{association.association_id}:v{association.version}"])
