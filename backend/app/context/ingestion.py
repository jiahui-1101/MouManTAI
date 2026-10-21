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


class SyntheticWhatsAppAdapter:
    """Declared mock adapter; no provider signature or real WhatsApp connection."""

    def accept(self, envelope: RawMessageEnvelope) -> RawMessageEnvelope:
        if envelope.channel != "WHATSAPP":
            raise UnsupportedSyntheticChannel("Only the synthetic WhatsApp-shaped adapter is implemented")
        return envelope


class IngestionService:
    def __init__(self, repository: MessageRepository, clock: Callable[[], datetime] | None = None):
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.adapter = SyntheticWhatsAppAdapter()

    def ingest(self, envelope: RawMessageEnvelope, effective_tenant: str) -> IngestResponse:
        if envelope.tenant_id != effective_tenant:
            raise TenantMismatch("Envelope tenant does not match the server development tenant")
        validated = self.adapter.accept(envelope)
        return self.repository.ingest(validated, self.clock())
