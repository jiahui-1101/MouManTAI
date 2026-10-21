"""Comprehensive tests for Task 2C: Persisted extraction, processing API, idempotency, and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.context.dependencies import development_context, local_repository
from app.context.dev_app import app
from app.context.dev_database import create_p1_engine
from app.context.deterministic_extraction import VERSION
from app.context.ingestion_schemas import DevelopmentContext
from app.context.postgres_repository import ExtractionAttempt, PostgresMessageRepository
from app.context.repository import ExtractionNotFound, MessageNotFound
from app.context.schemas import RawMessageEnvelope
from app.context.tests.test_postgres_repository import NOW, envelope


@pytest.fixture
def api(pg_engine):
    repository = PostgresMessageRepository(pg_engine)
    app.dependency_overrides[local_repository] = lambda: repository
    app.dependency_overrides[development_context] = lambda: DevelopmentContext(tenant_id="tenant_a")
    try:
        with TestClient(app) as client:
            yield client, repository
    finally:
        app.dependency_overrides.clear()


def test_process_persists_extraction_and_durability_across_restart(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    msg_env = envelope(text="Please send 50 pcs burgers tomorrow before 3pm.")
    ingested = repo.ingest(msg_env, NOW).message
    assert ingested.processing_status == "RECEIVED"

    # Process message
    res = repo.process("tenant_a", ingested.message_id)
    assert res.reprocessed is False
    assert res.message.processing_status == "PROCESSED"
    assert res.attempt.status == "PROCESSED"
    assert res.attempt.extractor_version == VERSION
    assert res.attempt.input_content_sha256 == ingested.content_sha256
    assert len(res.attempt.fields) > 0

    field_names = {f.field_name for f in res.attempt.fields}
    assert "sku" in field_names
    assert "quantity" in field_names

    # Check restart durability across new engine
    schema = pg_engine.get_execution_options()["schema_translate_map"]["p1_dev"]
    pg_engine.dispose()
    restarted = create_p1_engine(pg_engine.url.render_as_string(hide_password=False)).execution_options(
        schema_translate_map={"p1_dev": schema}
    )
    try:
        restarted_repo = PostgresMessageRepository(restarted)
        retrieved = restarted_repo.get("tenant_a", ingested.message_id)
        assert retrieved.processing_status == "PROCESSED"

        latest = restarted_repo.get_latest_extraction("tenant_a", ingested.message_id)
        assert latest is not None
        assert latest.attempt_id == res.attempt.attempt_id
        assert latest.extractor_version == VERSION
        assert latest.status == "PROCESSED"
        assert len(latest.fields) == len(res.attempt.fields)

        attempts = restarted_repo.list_extraction_attempts("tenant_a", ingested.message_id)
        assert len(attempts) == 1
        assert attempts[0].attempt_id == res.attempt.attempt_id
    finally:
        restarted.dispose()


def test_idempotent_processing_without_reprocess(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    ingested = repo.ingest(envelope(text="Need 10 burgers"), NOW).message

    first = repo.process("tenant_a", ingested.message_id, reprocess=False)
    assert first.reprocessed is False

    # Second call without reprocess=True returns the exact same attempt
    second = repo.process("tenant_a", ingested.message_id, reprocess=False)
    assert second.reprocessed is False
    assert second.attempt.attempt_id == first.attempt.attempt_id
    assert second.attempt.started_at == first.attempt.started_at

    # Only 1 attempt row in DB
    attempts = repo.list_extraction_attempts("tenant_a", ingested.message_id)
    assert len(attempts) == 1


def test_intentional_reprocessing_preserves_history(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    ingested = repo.ingest(envelope(text="Need 100 burgers"), NOW).message

    first = repo.process("tenant_a", ingested.message_id, reprocess=False)
    second = repo.process("tenant_a", ingested.message_id, reprocess=True)

    assert second.reprocessed is True
    assert second.attempt.attempt_id != first.attempt.attempt_id

    # Both attempts are preserved in history in reverse chronological order
    attempts = repo.list_extraction_attempts("tenant_a", ingested.message_id)
    assert len(attempts) == 2
    assert attempts[0].attempt_id == second.attempt.attempt_id
    assert attempts[1].attempt_id == first.attempt.attempt_id

    # get_latest_extraction returns the newest attempt
    latest = repo.get_latest_extraction("tenant_a", ingested.message_id)
    assert latest.attempt_id == second.attempt.attempt_id


def test_concurrent_processing_is_safe(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    ingested = repo.ingest(envelope(text="200 burgers"), NOW).message

    barrier = Barrier(4)

    def worker(_):
        barrier.wait()
        return repo.process("tenant_a", ingested.message_id, reprocess=False)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(worker, range(4)))

    attempt_ids = {r.attempt.attempt_id for r in results}
    # Exactly one unique logical attempt was generated and shared
    assert len(attempt_ids) == 1
    attempts = repo.list_extraction_attempts("tenant_a", ingested.message_id)
    assert len(attempts) == 1


def test_tenant_isolation(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    msg_a = repo.ingest(envelope(tenant_id="tenant_a", provider_message_id="m1"), NOW).message
    msg_b = repo.ingest(envelope(tenant_id="tenant_b", provider_message_id="m2"), NOW).message

    repo.process("tenant_a", msg_a.message_id)

    # Tenant B cannot process or inspect Tenant A's message
    with pytest.raises(MessageNotFound):
        repo.process("tenant_b", msg_a.message_id)

    with pytest.raises(MessageNotFound):
        repo.get_latest_extraction("tenant_b", msg_a.message_id)

    with pytest.raises(MessageNotFound):
        repo.list_extraction_attempts("tenant_b", msg_a.message_id)


def test_nonexistent_message_and_no_extraction(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    with pytest.raises(MessageNotFound):
        repo.process("tenant_a", "nonexistent_msg_id")

    # Ingest message but do not process
    ingested = repo.ingest(envelope(text="raw text"), NOW).message
    with pytest.raises(ExtractionNotFound):
        repo.get_latest_extraction("tenant_a", ingested.message_id)

    # Attempts list is empty
    assert repo.list_extraction_attempts("tenant_a", ingested.message_id) == []


def test_api_process_and_retrieval(api):
    client, repo = api
    payload = envelope(text="Please deliver 15 pcs burgers tomorrow before 3pm.").model_dump(mode="json")
    ingest_res = client.post("/v1/messages/ingest", json=payload)
    assert ingest_res.status_code == 201
    message_id = ingest_res.json()["message"]["message_id"]

    # Before processing: 404 for extraction
    res_404 = client.get(f"/v1/messages/{message_id}/extraction")
    assert res_404.status_code == 404

    # Process via API
    proc_res = client.post(f"/v1/messages/{message_id}/process")
    assert proc_res.status_code == 200
    data = proc_res.json()
    assert data["reprocessed"] is False
    assert data["message"]["processing_status"] == "PROCESSED"
    assert data["attempt"]["status"] == "PROCESSED"
    assert data["attempt"]["extractor_version"] == VERSION
    assert len(data["attempt"]["fields"]) > 0

    # Retrieve latest extraction
    ext_res = client.get(f"/v1/messages/{message_id}/extraction")
    assert ext_res.status_code == 200
    assert ext_res.json()["attempt_id"] == data["attempt"]["attempt_id"]

    # Retrieve history
    hist_res = client.get(f"/v1/messages/{message_id}/attempts")
    assert hist_res.status_code == 200
    assert len(hist_res.json()["items"]) == 1

    # Reprocess via API
    reproc_res = client.post(f"/v1/messages/{message_id}/process?reprocess=true")
    assert reproc_res.status_code == 200
    reproc_data = reproc_res.json()
    assert reproc_data["reprocessed"] is True
    assert reproc_data["attempt"]["attempt_id"] != data["attempt"]["attempt_id"]

    # History now has 2 attempts
    hist_res2 = client.get(f"/v1/messages/{message_id}/attempts")
    assert len(hist_res2.json()["items"]) == 2


def test_failed_attempt_and_safe_retry(pg_engine, monkeypatch):
    import app.context.postgres_repository as pr

    repo = PostgresMessageRepository(pg_engine)
    ingested = repo.ingest(envelope(text="100 burgers please"), NOW).message

    # Simulate an unexpected failure in extraction
    def failing_extract(*args, **kwargs):
        raise RuntimeError("Simulated extractor crash")

    monkeypatch.setattr(pr, "extract_explicit_fields", failing_extract)

    # First attempt fails
    failed_res = repo.process("tenant_a", ingested.message_id)
    assert failed_res.message.processing_status == "PROCESSING_FAILED"
    assert failed_res.attempt.status == "PROCESSING_FAILED"
    assert "Simulated extractor crash" in (failed_res.attempt.diagnostic or "")
    assert failed_res.attempt.completed_at is not None

    # Failed attempt is persisted in history
    history = repo.list_extraction_attempts("tenant_a", ingested.message_id)
    assert len(history) == 1
    assert history[0].status == "PROCESSING_FAILED"

    # Restore normal extractor and safely reprocess/retry
    monkeypatch.undo()

    retry_res = repo.process("tenant_a", ingested.message_id, reprocess=True)
    assert retry_res.message.processing_status == "PROCESSED"
    assert retry_res.attempt.status == "PROCESSED"
    assert retry_res.reprocessed is True
    assert len(retry_res.attempt.fields) > 0

    # Both the failed attempt and the successful retry are preserved in history
    attempts = repo.list_extraction_attempts("tenant_a", ingested.message_id)
    assert len(attempts) == 2
    assert attempts[0].status == "PROCESSED"
    assert attempts[1].status == "PROCESSING_FAILED"

    # Latest extraction is the successful one
    latest = repo.get_latest_extraction("tenant_a", ingested.message_id)
    assert latest.status == "PROCESSED"

