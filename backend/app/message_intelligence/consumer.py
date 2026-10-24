"""Retryable C3 classification of verified, canonical P1 ingress."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.context.postgres_repository import PostgresMessageRepository
from app.core.schemas import DomainEvent

from .adapters import CurrentP1MessageReader
from .contracts import AnalysisOutcome
from .review import C3ReviewService
from .review_models import C3ClassificationRecord
from .service import MessageIntelligenceService, SourceContractError


class _EventTenantScope:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def current_verified_tenant_id(self) -> str:
        return self.tenant_id


def classify_verified_message(db: Session, event: DomainEvent) -> None:
    """Outbox subscriber; the dispatcher commits its result and processed marker."""
    if event.event_type != "p1.message_verified":
        raise SourceContractError("unexpected C3 event type")
    payload = event.payload
    message_id = payload.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise SourceContractError("C3 event lacks canonical message ID")

    # Serialize identical events before inference. A crash before commit can
    # repeat an external inference, but never creates two durable results.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        digest = hashlib.sha256(f"{event.tenant_id}\0{message_id}".encode()).digest()[:8]
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"),
                   {"lock_id": int.from_bytes(digest, "big", signed=True)})

    repository = PostgresMessageRepository(db.get_bind())
    reader = CurrentP1MessageReader(repository, _EventTenantScope(event.tenant_id))
    message, _, records, extractions = reader.read(message_id)
    raw = message.raw
    if (raw.adapter_mode != "REAL" or raw.source_authenticity != "VERIFIED"
        or message.content_sha256 != payload.get("content_sha256")
        or message.provider != payload.get("provider")
        or raw.provider_account_id != payload.get("provider_account_id")
        or raw.provider_native_message_id != payload.get("provider_native_message_id")):
        raise SourceContractError("C3 event does not match verified provider source")

    # Provider adapters attempt P1 extraction after ingest, but that attempt is
    # best effort. The durable consumer completes it when ingress was interrupted.
    if message.processing_status == "RECEIVED":
        repository.process(event.tenant_id, message_id)
        message, _, records, extractions = reader.read(message_id)
    elif message.processing_status == "PROCESSING":
        raise SourceContractError("P1 source extraction is still processing")

    source = MessageIntelligenceService._source_reference(
        message, {record.evidence_ref: record for record in records}, extractions)
    source_hash = hashlib.sha256(json.dumps(
        source.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    existing = db.get(C3ClassificationRecord, (event.tenant_id, message_id, source_hash))
    if existing is not None:
        AnalysisOutcome.model_validate(existing.outcome)
        reader.assert_current(source)
        return

    now = datetime.now(timezone.utc)
    classifier = MessageIntelligenceService.from_env()
    outcome = reader.analyze(message_id, classifier, now=now)
    if outcome.source != source:
        raise SourceContractError("C3 source changed during classification")
    reader.assert_current(outcome.source,
                          evidence=tuple(outcome.human_review_candidate.evidence)
                          if outcome.human_review_candidate else ())

    review = C3ReviewService(db, reader).enqueue(
        message_id, classifier, now=now, outcome=outcome, commit=False)
    db.add(C3ClassificationRecord(
        tenant_id=event.tenant_id, message_id=message_id, source_hash=source_hash,
        outcome=outcome.model_dump(mode="json"),
        review_id=review.review_id if review else None, created_at=now,
    ))
