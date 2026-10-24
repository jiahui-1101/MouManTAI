from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.context.dev_database import create_p1_engine
from app.context.postgres_repository import InboundMessage, PostgresMessageRepository, fingerprint
from app.context.repository import DuplicateConflict, PersistenceUnavailable
from app.context.schemas import RawMessageEnvelope

NOW = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)


def envelope(**changes):
    return RawMessageEnvelope(**(dict(tenant_id="tenant_a", channel="WHATSAPP", provider_message_id="delivery_1",
        sender_identity_id="platform_sender_1", sender_alias="Synthetic buyer", text="  Need 100 burgers\n明天 before 3pm.  ",
        received_at="2026-10-20T10:01:00+08:00", message_at="2026-10-20T10:00:00+08:00",
        thread_ref="thread_1", reply_to_provider_message_id="previous_1", language="en-MY",
        attachments=[dict(attachment_id="attachment_1", filename="request.pdf", media_type="application/pdf", size_bytes=100, evidence_ref="synthetic_ref_1")]) | changes))


def test_durable_original_and_metadata_across_new_engine(pg_engine):
    original = envelope()
    result = PostgresMessageRepository(pg_engine).ingest(original, NOW)
    assert not result.duplicate
    schema = pg_engine.get_execution_options()["schema_translate_map"]["p1_dev"]
    pg_engine.dispose()
    restarted = create_p1_engine(pg_engine.url.render_as_string(hide_password=False)).execution_options(schema_translate_map={"p1_dev": schema})
    try:
        saved = PostgresMessageRepository(restarted).get("tenant_a", result.message.message_id)
        assert saved.raw == original
        assert saved.raw.text == "  Need 100 burgers\n明天 before 3pm.  "
        assert saved.raw.message_at.isoformat() == "2026-10-20T02:00:00+00:00"
        assert saved.ingested_at == NOW == saved.updated_at
        assert saved.processing_status == "RECEIVED"
        assert saved.synthetic_provider == "SYNTHETIC_WHATSAPP"
    finally:
        restarted.dispose()


def test_duplicate_returns_original_without_rewriting_first_receipt(pg_engine):
    repository = PostgresMessageRepository(pg_engine)
    first = repository.ingest(envelope(), NOW)
    second = repository.ingest(envelope(received_at="2026-10-21T12:00:00+08:00"), NOW)
    assert second.duplicate
    assert second.message == first.message
    assert repository.list("tenant_a").total == 1


@pytest.mark.parametrize("changes", [{"text": "different"}, {"sender_identity_id": "other"},
    {"thread_ref": "other"}, {"message_at": "2026-10-21T00:00:00Z"}, {"attachments": []}, {"sender_alias": "Other alias"}])
def test_conflicting_duplicates_never_overwrite(pg_engine, changes):
    repo = PostgresMessageRepository(pg_engine)
    first = repo.ingest(envelope(), NOW)
    with pytest.raises(DuplicateConflict):
        repo.ingest(envelope(**changes), NOW)
    assert repo.get("tenant_a", first.message.message_id) == first.message
    assert repo.list("tenant_a").total == 1


def test_database_constraint_cannot_be_bypassed(pg_engine):
    PostgresMessageRepository(pg_engine).ingest(envelope(), NOW)
    with Session(pg_engine) as session:
        row = session.scalar(select(InboundMessage))
        values = {column.name: getattr(row, column.name) for column in InboundMessage.__table__.columns}
    values["message_id"] = "bypass-attempt"
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as connection:
            connection.execute(InboundMessage.__table__.insert().values(**values))
    schema = pg_engine.get_execution_options()["schema_translate_map"]["p1_dev"]
    assert any(
        index["name"] == "uq_p1_delivery_legacy" and index["unique"]
        for index in inspect(pg_engine).get_indexes("inbound_messages", schema=schema)
    )


def test_concurrent_identical_delivery_has_one_winner(pg_engine):
    barrier = Barrier(4)
    def deliver(_):
        barrier.wait(timeout=10)
        return PostgresMessageRepository(pg_engine).ingest(envelope(), NOW)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(deliver, range(4)))
    assert len({r.message.message_id for r in results}) == 1
    assert sum(not r.duplicate for r in results) == 1
    assert PostgresMessageRepository(pg_engine).list("tenant_a").total == 1


def test_concurrent_conflicting_delivery_preserves_winner(pg_engine):
    barrier = Barrier(2)
    def deliver(text):
        barrier.wait(timeout=10)
        try:
            return PostgresMessageRepository(pg_engine).ingest(envelope(text=text), NOW)
        except DuplicateConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(deliver, ["first proposal", "second proposal"]))
    assert sum(r is not None for r in results) == 1
    winner = next(r for r in results if r is not None)
    assert PostgresMessageRepository(pg_engine).get("tenant_a", winner.message.message_id) == winner.message


def test_tenant_scoped_queries_literal_search_and_stable_pagination(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    first = repo.ingest(envelope(), NOW).message
    other = repo.ingest(envelope(tenant_id="tenant_b"), NOW).message
    repo.ingest(envelope(provider_message_id="delivery_2", text="100% complete_marker"), NOW)
    repo.ingest(envelope(provider_message_id="delivery_3", text="nothing else"), NOW)
    assert repo.list("tenant_a").total == 3
    assert repo.get("tenant_a", other.message_id) is None
    assert repo.get("tenant_b", first.message_id) is None
    assert repo.list("tenant_b").total == 1
    assert repo.list("tenant_a", channel="EMAIL").total == 0
    assert repo.list("tenant_a", search="BUYER").total == 3
    assert repo.list("tenant_a", search="%").total == 1
    assert repo.list("tenant_a", search="明天").items[0].message_id == first.message_id
    assert repo.list("tenant_a", search="delivery_3").total == 1
    pages = [repo.list("tenant_a", limit=1, offset=n).items[0].message_id for n in range(3)]
    assert pages == sorted(pages, reverse=True)
    assert len(set(pages)) == 3
    assert repo.list("tenant_a", processing_status="PROCESSED").total == 0
    assert len(repo.awaiting_processing("tenant_a")) == 3


def test_missing_storage_is_sanitized():
    with pytest.raises(PersistenceUnavailable):
        create_p1_engine("sqlite:///never-allowed")
    engine = create_p1_engine("postgresql+psycopg://fake:secret@127.0.0.1:1/missing")
    try:
        for operation in [lambda: PostgresMessageRepository(engine).ingest(envelope(), NOW),
                          lambda: PostgresMessageRepository(engine).get("tenant_a", "missing"),
                          lambda: PostgresMessageRepository(engine).list("tenant_a"),
                          lambda: PostgresMessageRepository(engine).read_order_context_source("tenant_a", "missing")]:
            with pytest.raises(PersistenceUnavailable) as captured:
                operation()
            assert "secret" not in str(captured.value)
    finally:
        engine.dispose()


def test_fingerprint_excludes_only_delivery_observation_and_normalizes_offsets():
    assert fingerprint(envelope()) == fingerprint(envelope(received_at="2026-10-22T00:00:00Z", message_at="2026-10-20T02:00:00Z"))
    assert fingerprint(envelope()) != fingerprint(envelope(text=envelope().text.strip()))


@pytest.mark.parametrize("changes", [{"text": "a" * 20_001}, {"provider_message_id": "a" * 201},
    {"attachments": [dict(attachment_id=str(n), filename="x", media_type="text/plain", size_bytes=1, evidence_ref="x") for n in range(11)]},
    {"message_at": "2026-10-20T10:00:00"}])
def test_ingestion_size_and_time_bounds(changes):
    with pytest.raises(ValidationError):
        envelope(**changes)
