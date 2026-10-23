"""Network-free local simulation only; outcomes configured server-side, never by HTTP."""
from dataclasses import dataclass, field
from typing import Literal, Protocol
from .schemas import MessageDraftView
from .templates import fingerprint

MOCK_CHANNELS = frozenset({"MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"})


@dataclass(frozen=True)
class ChallengeDelivery:
    confirmation_id: str
    body: str = field(repr=False)
    payload_hash: str


@dataclass(frozen=True)
class SendEnvelope:
    outbound_id: str
    draft: MessageDraftView
    challenge: ChallengeDelivery | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ProviderResult:
    status: Literal["SENT", "FAILED", "DELIVERY_UNKNOWN"]
    provider_reference: str | None = None
    error_code: str | None = None


class OutboundProvider(Protocol):
    def submit(self, envelope: SendEnvelope) -> ProviderResult: ...


class LocalMockProvider:
    def __init__(self, outcome: Literal["SENT", "FAILED", "DELIVERY_UNKNOWN"] = "SENT", *, receipt_sink=None):
        if outcome not in {"SENT", "FAILED", "DELIVERY_UNKNOWN"}:
            raise ValueError("Unsupported local mock outcome")
        self.outcome = outcome
        self.receipt_sink = receipt_sink

    def submit(self, envelope: SendEnvelope) -> ProviderResult:
        if envelope.draft.channel not in MOCK_CHANNELS:
            return ProviderResult("FAILED", error_code="UNSUPPORTED_MOCK_CHANNEL")
        if self.outcome == "DELIVERY_UNKNOWN":
            raise TimeoutError("Local deterministic uncertain outcome")
        if envelope.challenge is not None:
            expected = fingerprint({"tenant_id": envelope.draft.tenant_id,
                "recipient_identity_id": envelope.draft.recipient_identity_id, "channel": envelope.draft.channel,
                "subject": envelope.draft.subject, "body": envelope.challenge.body})
            if expected != envelope.challenge.payload_hash or self.receipt_sink is None:
                return ProviderResult("FAILED", error_code="SECURE_DELIVERY_UNAVAILABLE")
            if self.outcome == "SENT":
                self.receipt_sink(envelope)  # Recipient transport only; never returned in API history.
        reference = "mock_" + fingerprint({"tenant": envelope.draft.tenant_id,
            "outbound": envelope.outbound_id, "channel": envelope.draft.channel,
            "content_hash": envelope.challenge.payload_hash if envelope.challenge else envelope.draft.content_hash})
        return ProviderResult(self.outcome, reference,
            "MOCK_PROVIDER_REJECTED" if self.outcome == "FAILED" else None)
