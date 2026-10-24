from datetime import datetime, timezone

import pytest

from app.context.channels.reply_framing import ParentResolution
from app.context.ingestion import IngestionService, UnverifiedProviderSource
from app.context.postgres_repository import PostgresMessageRepository
from app.context.schemas import RawMessageEnvelope
from app.context.tests.in_memory_repository import InMemoryMessageRepository

NOW = datetime(2026, 10, 24, 5, 0, tzinfo=timezone.utc)


def real_message(
    native_id: str,
    *,
    account: str = "bot-a",
    tenant: str = "tenant-a",
    channel: str = "TELEGRAM",
    conversation: str = "chat-a",
    parent: str | None = None,
    rfc_id: str | None = None,
    in_reply_to: list[str] | None = None,
    references: list[str] | None = None,
    attachment_sources: list[str] | None = None,
) -> RawMessageEnvelope:
    return RawMessageEnvelope(
        tenant_id=tenant,
        channel=channel,
        provider_message_id=f"{channel.lower()}_{native_id}",
        provider_account_id=account,
        provider_native_message_id=native_id,
        sender_identity_id="sender-1",
        sender_alias="Customer",
        received_at=NOW,
        message_at=NOW,
        text="Please confirm this order",
        thread_ref=conversation,
        conversation_id=conversation,
        reply_to_provider_message_id=parent,
        rfc_message_id=rfc_id,
        rfc_in_reply_to=in_reply_to or [],
        rfc_references=references or [],
        native_attachment_source_ids=attachment_sources or [],
        relationship_source=("SENDER_HEADER" if channel == "EMAIL" and parent else (
            "PROVIDER_QUOTE" if parent else "NONE"
        )),
        adapter_mode="REAL",
        source_authenticity="VERIFIED",
    )


def test_delivery_identity_is_scoped_by_provider_account(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    first = repo.ingest(real_message("same-id", account="bot-a"), NOW)
    other_account = repo.ingest(real_message("same-id", account="bot-b"), NOW)

    assert not first.duplicate
    assert not other_account.duplicate
    assert first.message.message_id != other_account.message.message_id
    assert repo.list("tenant-a").total == 2


def test_same_account_native_duplicate_is_idempotent_and_immutable(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    first = repo.ingest(real_message("same-id"), NOW)
    duplicate = repo.ingest(real_message("same-id"), NOW)

    assert not first.duplicate
    assert duplicate.duplicate
    assert duplicate.message == first.message


def test_exact_parent_uses_provider_account_and_conversation_scope(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    repo.ingest(real_message("parent", conversation="chat-a"), NOW)
    child = repo.ingest(real_message("child", conversation="chat-a", parent="parent"), NOW)
    wrong_chat = repo.ingest(real_message("other-chat-parent", conversation="chat-b", parent="parent"), NOW)
    wrong_account = repo.ingest(real_message("other-account-child", account="bot-b", parent="parent"), NOW)

    assert repo.resolve_exact_parent("tenant-a", child.message.message_id) == ParentResolution(
        "REFERENCE_MATCH", "parent"
    )
    assert repo.resolve_exact_parent("tenant-a", wrong_chat.message.message_id) == ParentResolution(
        "UNRESOLVED"
    )
    assert repo.resolve_exact_parent("tenant-a", wrong_account.message.message_id) == ParentResolution(
        "UNRESOLVED"
    )


def test_parent_arriving_late_reconciles_without_rewriting_source_envelope(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    child = repo.ingest(
        real_message("child", parent="parent", attachment_sources=["native-file-1"]), NOW
    )
    original = child.message.raw
    assert repo.resolve_exact_parent("tenant-a", child.message.message_id) == ParentResolution(
        "UNRESOLVED"
    )

    parent = repo.ingest(real_message("parent"), NOW)

    assert repo.resolve_exact_parent("tenant-a", child.message.message_id) == ParentResolution(
        "REFERENCE_MATCH", "parent"
    )
    persisted = repo.get("tenant-a", child.message.message_id)
    assert persisted.raw == original
    assert persisted.raw.native_attachment_source_ids == ["native-file-1"]
    assert repo.resolve_exact_parent("tenant-a", parent.message.message_id) == ParentResolution(
        "NO_EXACT_PARENT"
    )


def test_email_uses_rfc_message_ids_and_keeps_provider_ids_separate(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    parent = repo.ingest(
        real_message(
            "gmail-native-parent",
            channel="EMAIL",
            account="owner@example.com",
            conversation="gmail-thread-1",
            rfc_id="<parent@example.com>",
        ),
        NOW,
    )
    child = repo.ingest(
        real_message(
            "gmail-native-child",
            channel="EMAIL",
            account="owner@example.com",
            conversation="different-gmail-thread",
            parent="<parent@example.com>",
            rfc_id="<child@example.com>",
            in_reply_to=["<parent@example.com>"],
            references=["<root@example.com>", "<parent@example.com>"],
        ),
        NOW,
    )

    assert repo.resolve_exact_parent("tenant-a", child.message.message_id) == ParentResolution(
        "REFERENCE_MATCH", "gmail-native-parent"
    )
    assert repo.get("tenant-a", parent.message.message_id).raw.rfc_message_id == "<parent@example.com>"


def test_ambiguous_rfc_parent_stays_unresolved_for_review(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    repo.ingest(real_message(
        "gmail-native-a", channel="EMAIL", account="owner@example.com",
        rfc_id="<duplicate@example.com>",
    ), NOW)
    repo.ingest(real_message(
        "gmail-native-b", channel="EMAIL", account="owner@example.com",
        conversation="other-thread", rfc_id="<duplicate@example.com>",
    ), NOW)
    child = repo.ingest(real_message(
        "gmail-native-child", channel="EMAIL", account="owner@example.com",
        parent="<duplicate@example.com>", rfc_id="<child@example.com>",
        in_reply_to=["<duplicate@example.com>"],
    ), NOW)

    assert repo.resolve_exact_parent("tenant-a", child.message.message_id) == ParentResolution(
        "AMBIGUOUS"
    )


def test_legacy_unknown_account_is_not_guessed_as_exact_parent(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    legacy = RawMessageEnvelope(
        tenant_id="tenant-a",
        channel="TELEGRAM",
        provider_message_id="tg_chat-a_parent",
        sender_identity_id="sender-1",
        sender_alias="Customer",
        received_at=NOW,
        text="Old message",
        thread_ref="chat-a",
        adapter_mode="REAL",
    )
    repo.ingest(legacy, NOW)
    child = repo.ingest(real_message("child", parent="parent"), NOW)

    assert repo.resolve_exact_parent("tenant-a", child.message.message_id) == ParentResolution(
        "UNRESOLVED"
    )


def test_real_ingestion_requires_provider_authenticity_and_complete_scope():
    base = real_message("message")
    service = IngestionService(InMemoryMessageRepository())
    with pytest.raises(UnverifiedProviderSource, match="not authenticated"):
        service.ingest(base.model_copy(update={"source_authenticity": "UNVERIFIED"}), "tenant-a")
    missing_scope = RawMessageEnvelope.model_validate(
        base.model_dump(mode="json")
        | {"provider_account_id": None, "provider_native_message_id": None}
    )
    with pytest.raises(UnverifiedProviderSource, match="lacks provider account"):
        service.ingest(missing_scope, "tenant-a")
