"""Network-free local simulation only; outcomes configured server-side, never by HTTP."""
from dataclasses import dataclass
from typing import Literal, Protocol
from .schemas import MessageDraftView
from .templates import fingerprint

MOCK_CHANNELS = frozenset({"MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"})


@dataclass(frozen=True)
class SendEnvelope:
    outbound_id: str
    draft: MessageDraftView


@dataclass(frozen=True)
class ProviderResult:
    status: Literal["SENT", "FAILED", "DELIVERY_UNKNOWN"]
    provider_reference: str | None = None
    error_code: str | None = None


class OutboundProvider(Protocol):
    def submit(self, envelope: SendEnvelope) -> ProviderResult: ...


class LocalMockProvider:
    def __init__(self, outcome: Literal["SENT", "FAILED", "DELIVERY_UNKNOWN"] = "SENT"):
        if outcome not in {"SENT", "FAILED", "DELIVERY_UNKNOWN"}:
            raise ValueError("Unsupported local mock outcome")
        self.outcome = outcome

    def submit(self, envelope: SendEnvelope) -> ProviderResult:
        if envelope.draft.channel not in MOCK_CHANNELS:
            return ProviderResult("FAILED", error_code="UNSUPPORTED_MOCK_CHANNEL")
        if self.outcome == "DELIVERY_UNKNOWN":
            raise TimeoutError("Local deterministic uncertain outcome")
        reference = "mock_" + fingerprint({"tenant": envelope.draft.tenant_id,
            "outbound": envelope.outbound_id, "channel": envelope.draft.channel,
            "content_hash": envelope.draft.content_hash})
        return ProviderResult(self.outcome, reference,
            "MOCK_PROVIDER_REJECTED" if self.outcome == "FAILED" else None)
