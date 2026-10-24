"""Migrated PostgreSQL proof for provider ingress -> outbox -> C3 review."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.context.ingestion import IngestionService, UnverifiedProviderSource
from app.context.postgres_repository import PostgresMessageRepository
from app.context.schemas import RawMessageEnvelope
from app.core.models import OutboxEventRecord, ProcessedEventRecord
from app.core.outbox import OutboxDispatcher
from app.core.dependencies import get_db
from app.main import app
from app.message_intelligence.consumer import classify_verified_message
from app.message_intelligence.review_models import C3ClassificationRecord, C3ReviewRecord


def _message(*, tenant="tenant-c3", native="native-1", verified=True):
    now = datetime.now(timezone.utc)
    return RawMessageEnvelope(
        tenant_id=tenant, channel="TELEGRAM", provider_message_id=f"tg_{native}",
        provider_account_id="bot-17", provider_native_message_id=native,
        conversation_id="chat-17", sender_identity_id="sender-17",
        sender_alias="Customer", received_at=now, message_at=now,
        text="Please advise", adapter_mode="REAL",
        source_authenticity="VERIFIED" if verified else "UNVERIFIED",
    )


def test_verified_ingress_classifies_once_and_enqueues_review(pg_suite_engine, monkeypatch):
    monkeypatch.setenv("P1_AI_ENABLED", "false")
    repository = PostgresMessageRepository(pg_suite_engine)
    ingestion = IngestionService(repository)
    first = ingestion.ingest(_message(), "tenant-c3")
    assert not first.duplicate
    assert ingestion.ingest(first.message.raw, "tenant-c3").duplicate
    with pytest.raises(UnverifiedProviderSource):
        ingestion.ingest(_message(native="unverified", verified=False), "tenant-c3")

    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber("p1.message_verified", "c3.classification.v1", classify_verified_message)
    with Session(pg_suite_engine) as db:
        events = db.scalars(select(OutboxEventRecord).where(
            OutboxEventRecord.event_type == "p1.message_verified")).all()
        assert len(events) == 1
        assert events[0].payload["provider_account_id"] == "bot-17"
        assert events[0].payload["provider_native_message_id"] == "native-1"
        batch = dispatcher.process_outbox_batch(db)
        assert batch.published_count == 1 and batch.failed_count == 0
        result = db.scalar(select(C3ClassificationRecord).where(
            C3ClassificationRecord.tenant_id == "tenant-c3"))
        assert result is not None
        assert result.outcome["source"]["provider_account_id"] == "bot-17"
        assert result.outcome["source"]["provider_native_message_id"] == "native-1"
        assert result.review_id is not None
        review = db.get(C3ReviewRecord, ("tenant-c3", result.review_id))
        assert review is not None and review.state == "PENDING"
        assert db.scalar(select(func.count()).select_from(ProcessedEventRecord).where(
            ProcessedEventRecord.event_id == events[0].event_id)) == 1
        # Replaying the published event cannot create a second result or review.
        events[0].status = "PENDING"
        db.commit()
        dispatcher.process_outbox_batch(db)
        assert db.scalar(select(func.count()).select_from(C3ClassificationRecord)) == 1
        assert db.scalar(select(func.count()).select_from(C3ReviewRecord)) == 1


def test_mismatched_provider_event_retries_without_c3_mutation(pg_suite_engine, monkeypatch):
    monkeypatch.setenv("P1_AI_ENABLED", "false")
    repository = PostgresMessageRepository(pg_suite_engine)
    IngestionService(repository).ingest(_message(tenant="tenant-retry", native="retry-1"), "tenant-retry")
    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber("p1.message_verified", "c3.classification.v1", classify_verified_message)
    with Session(pg_suite_engine) as db:
        event = db.scalar(select(OutboxEventRecord).where(
            OutboxEventRecord.event_type == "p1.message_verified"))
        authentic = dict(event.payload)
        event.payload = {**authentic, "provider_account_id": "foreign-bot"}
        db.commit()
        batch = dispatcher.process_outbox_batch(db)
        assert batch.failed_count == 1
        assert db.scalar(select(func.count()).select_from(C3ClassificationRecord)) == 0
        assert db.scalar(select(func.count()).select_from(C3ReviewRecord)) == 0
        db.refresh(event)
        event.payload = authentic
        event.next_retry_at = None
        db.commit()
        assert dispatcher.process_outbox_batch(db).published_count == 1
        assert db.scalar(select(func.count()).select_from(C3ClassificationRecord)) == 1


def test_demo_admin_c3_decision_is_keyed_tenant_scoped_and_classification_only(pg_suite_engine, monkeypatch):
    key = "c3-demo-admin-private-key-20261025-123456"
    for name, value in {
        "MOUMANTAI_ISOLATED_E2E": "1", "MOUMANTAI_SYNTHETIC_MODE": "1",
        "MOUMANTAI_ISOLATED_E2E_KEY": key,
        "MOUMANTAI_ISOLATED_E2E_TENANT_ID": "tenant-decision",
        "MOUMANTAI_ISOLATED_E2E_MANAGER_ID": "user_manager_01",
        "MOUMANTAI_DEMO_ADMIN_AUTH": "1", "ENVIRONMENT": "staging",
        "APP_ENV": "synthetic", "P1_AI_ENABLED": "false",
    }.items():
        monkeypatch.setenv(name, value)
    repository = PostgresMessageRepository(pg_suite_engine)
    IngestionService(repository).ingest(_message(tenant="tenant-decision", native="decision-1"), "tenant-decision")
    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber("p1.message_verified", "c3.classification.v1", classify_verified_message)
    with Session(pg_suite_engine) as db:
        assert dispatcher.process_outbox_batch(db).published_count == 1
        review = db.scalar(select(C3ReviewRecord).where(C3ReviewRecord.tenant_id == "tenant-decision"))
        review_id = review.review_id

    def isolated_db():
        with Session(pg_suite_engine) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    try:
        client = TestClient(app)
        path = f"/v1/c3/reviews/{review_id}/decide"
        command = {"action": "CORRECT", "corrected_intent": "OTHER",
                   "expected_revision": 1, "request_key": "decision-key-1",
                   "reason": "Original message needs a human classification"}
        assert client.post(path, json=command).status_code == 403
        headers = {"X-Isolated-E2E-Key": key, "X-Tenant-ID": "tenant-decision",
                   "X-Actor-ID": "user_staff_01"}
        assert client.post(path, headers=headers, json=command).status_code == 403
        headers["X-Actor-ID"] = "user_manager_01"
        headers["X-Tenant-ID"] = "tenant-foreign"
        assert client.post(path, headers=headers, json=command).status_code == 403
        headers["X-Tenant-ID"] = "tenant-decision"
        result = client.post(path, headers=headers, json=command)
        assert result.status_code == 200, result.text
        assert result.json()["decision"] == "CORRECT"
        assert result.json()["corrected_intent"] == "OTHER"
        assert client.post(path, headers=headers, json=command).status_code == 409
        with Session(pg_suite_engine) as db:
            decided = db.get(C3ReviewRecord, ("tenant-decision", review_id))
            assert decided.reviewer_id == "user_manager_01"
            assert decided.authorization_evidence_refs
            assert db.scalar(select(func.count()).select_from(OutboxEventRecord).where(
                OutboxEventRecord.event_type != "p1.message_verified")) == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
