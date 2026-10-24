"""Existing canonical persistence guarantees, not live-provider ingress proof."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.context.postgres_repository import InboundMessage, OrderContext, PostgresMessageRepository
from app.context.repository import DuplicateConflict
from app.context.schemas import RawMessageEnvelope
from app.core.models import OutboxEventRecord


def envelope(provider_id="tg_-100_2", parent="tg_-100_1", **changes):
    values = {
        "tenant_id": "c1_synthetic",
        "channel": "TELEGRAM",
        "provider_message_id": provider_id,
        "sender_identity_id": "42",
        "sender_alias": "SYNTHETIC unverified sender",
        "received_at": datetime(2026, 10, 24, tzinfo=UTC),
        "message_at": datetime(2026, 10, 24, tzinfo=UTC),
        "text": "Synthetic quoted source; not acceptance or assent.",
        "thread_ref": "-100",
        "reply_to_provider_message_id": parent,
    }
    values.update(changes)
    return RawMessageEnvelope(**values)


@pytest.mark.postgres
def test_canonical_repository_preserves_unknown_parent_then_late_parent(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    reply = envelope()
    saved_reply = repo.ingest(reply, reply.received_at).message
    assert saved_reply.raw.reply_to_provider_message_id == "tg_-100_1"
    parent = envelope("tg_-100_1", None)
    repo.ingest(parent, parent.received_at)
    assert repo.get(reply.tenant_id, saved_reply.message_id).raw == reply
    assert repo.list(reply.tenant_id).total == 2
    # Ingest alone does not create contexts, business events or customer assent.
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(OrderContext)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 0


@pytest.mark.postgres
def test_duplicate_redelivery_creates_one_message_and_no_domain_events(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    raw = envelope()
    first = repo.ingest(raw, raw.received_at)
    retry = raw.model_copy(update={"received_at": raw.received_at + timedelta(seconds=5)})
    second = repo.ingest(retry, retry.received_at)
    assert not first.duplicate and second.duplicate
    assert second.message.message_id == first.message.message_id
    assert second.message.raw.received_at == raw.received_at
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(InboundMessage)) == 1
        assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 0


@pytest.mark.postgres
@pytest.mark.parametrize(
    "changes",
    [
        {"text": "Changed source"},
        {"sender_identity_id": "43"},
        {"reply_to_provider_message_id": "tg_-100_9"},
    ],
)
def test_conflicting_provider_identity_does_not_overwrite_original(pg_engine, changes):
    repo = PostgresMessageRepository(pg_engine)
    raw = envelope()
    first = repo.ingest(raw, raw.received_at).message
    with pytest.raises(DuplicateConflict):
        repo.ingest(raw.model_copy(update=changes), raw.received_at)
    assert repo.get(raw.tenant_id, first.message_id).raw == raw


@pytest.mark.postgres
def test_existing_delivery_key_is_tenant_and_channel_scoped(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    raw = envelope()
    saved = repo.ingest(raw, raw.received_at).message
    other_tenant = envelope(tenant_id="other_synthetic")
    other_channel = envelope(channel="WHATSAPP")
    assert not repo.ingest(other_tenant, raw.received_at).duplicate
    assert not repo.ingest(other_channel, raw.received_at).duplicate
    assert repo.get("other_synthetic", saved.message_id) is None
    assert repo.list(raw.tenant_id).total == 2
