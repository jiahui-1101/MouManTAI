"""P1-owned persisted normalization/association, P4-owned challenge protocol."""
import hashlib
from .confirmation_authority import P1SyntheticInboundAdapter
from .challenge_delivery import parse_customer_reply
from .demo_policy import deny


class P1BoundReplyAdapter(P1SyntheticInboundAdapter):
    def __init__(self, source, directory, scope):
        super().__init__(source, directory, scope)
        self.target = None

    def read_delivery_reply(self, db, context, message_id, *, now):
        verified = super().resolve(db, context, message_id, now=now)
        if hashlib.sha256(verified.text.encode("utf-8")).hexdigest() != verified.source_digest:
            deny("INBOUND_PROVENANCE_INVALID", "P1 source content digest differs", 409)
        confirmation_id, secret, text = parse_customer_reply(verified.text)
        return confirmation_id, secret, verified.model_copy(update={"text": text})

    def resolve(self, db, context, message_id, *, now):
        confirmation_id, _, verified = self.read_delivery_reply(db, context, message_id, now=now)
        if self.target is None or self.target != confirmation_id:
            deny("CONFIRMATION_RESPONSE_TARGET_MISMATCH", "P1 reply targets a different confirmation", 409)
        return verified


def process_persisted_inbound(service, context, command, *, now=None):
    from .preferences import utc
    service._guard(context, "PROCESS_CONFIRMATION_RESPONSE")
    if not isinstance(service.inbound, P1BoundReplyAdapter):
        deny("VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE", "A bound P1 reader is required", 503)
    target, secret, _ = service.inbound.read_delivery_reply(service.db, context, command.inbound_message_id, now=utc(now))
    service.db.rollback()  # No writes; respond re-reads current identity and provenance.
    service.inbound.target = target
    return service.respond(context, target, command, secret, now=now)
