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


SUPPORTED_SYNTHETIC_CHANNELS = {"WHATSAPP", "EMAIL", "TELEGRAM", "UNKNOWN"}


class SyntheticMultiChannelAdapter:
    """Declared mock adapter for multi-channel synthetic inputs (WhatsApp, Email, Telegram)."""

    def accept(self, envelope: RawMessageEnvelope) -> RawMessageEnvelope:
        if envelope.channel not in SUPPORTED_SYNTHETIC_CHANNELS:
            raise UnsupportedSyntheticChannel(f"Channel {envelope.channel} is not implemented")
        return envelope


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
        validated = self.adapter.accept(envelope)
        return self.repository.ingest(validated, self.clock())
