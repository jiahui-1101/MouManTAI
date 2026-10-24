"""Synthetic input only. Does not extract, associate, emit events or process messages."""

from datetime import datetime, timezone
from typing import Callable

from .ingestion_schemas import IngestResponse
from .repository import MessageRepository
from .schemas import RawMessageEnvelope


class TenantMismatch(Exception):
    pass


class UnsupportedSyntheticChannel(Exception):
    pass


class UnverifiedProviderSource(Exception):
    """A real-channel envelope lacks adapter-owned authentication or identity."""


SUPPORTED_SYNTHETIC_CHANNELS = {"WHATSAPP", "EMAIL", "TELEGRAM", "UNKNOWN"}


class SyntheticMultiChannelAdapter:
    """Declared mock adapter for multi-channel synthetic inputs (WhatsApp, Email, Telegram)."""

    def accept(self, envelope: RawMessageEnvelope) -> RawMessageEnvelope:
        if envelope.channel not in SUPPORTED_SYNTHETIC_CHANNELS:
            raise UnsupportedSyntheticChannel(f"Channel {envelope.channel} is not implemented")
        return envelope.model_copy(
            update={
                "adapter_mode": "SYNTHETIC",
                "source_authenticity": "SYNTHETIC",
            }
        )


# Backwards compatibility alias for existing test references
SyntheticWhatsAppAdapter = SyntheticMultiChannelAdapter


class IngestionService:
    def __init__(self, repository: MessageRepository, clock: Callable[[], datetime] | None = None):
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.adapter = SyntheticMultiChannelAdapter()

    def ingest(self, envelope: RawMessageEnvelope, effective_tenant: str) -> IngestResponse:
        if envelope.tenant_id != effective_tenant:
            raise TenantMismatch("Envelope tenant does not match the server development tenant")
        if envelope.adapter_mode == "REAL":
            if envelope.source_authenticity != "VERIFIED":
                raise UnverifiedProviderSource(
                    "Real channel source was not authenticated by its provider adapter"
                )
            if not envelope.provider_account_id or not envelope.provider_native_message_id:
                raise UnverifiedProviderSource(
                    "Real channel source lacks provider account or native message identity"
                )
            if envelope.channel == "TELEGRAM" and not envelope.conversation_id:
                raise UnverifiedProviderSource("Telegram source lacks native chat identity")
        validated = envelope if envelope.adapter_mode == "REAL" else self.adapter.accept(envelope)
        return self.repository.ingest(validated, self.clock())
