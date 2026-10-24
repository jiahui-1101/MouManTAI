from datetime import UTC, datetime

import pytest

from app.context.channels.config import (
    GmailChannelConfig,
    TelegramChannelConfig,
    WhatsAppChannelConfig,
)
from app.context.channels.gmail import GmailAdapter
from app.context.channels.state import ChannelStateManager
from app.context.channels.telegram import TelegramAdapter, TelegramApiError
from app.context.channels.whatsapp import InvalidWhatsAppAccountError, WhatsAppAdapter
from app.context.tests.in_memory_repository import InMemoryMessageRepository


def test_telegram_native_quote_and_account_scope_are_wired(tmp_path):
    adapter = TelegramAdapter(
        TelegramChannelConfig(
            bot_token="123456789:token",
            tenant_id="tenant-a",
        ),
        InMemoryMessageRepository(),
        state_manager=ChannelStateManager(storage_path=tmp_path / "telegram.json"),
        clock=lambda: datetime(2026, 10, 24, tzinfo=UTC),
    )
    update = {
        "update_id": 91,
        "message": {
            "message_id": 44,
            "date": 1792756800,
            "from": {"id": 700, "username": "buyer"},
            "chat": {"id": -10055},
            "reply_to_message": {"message_id": 43, "chat": {"id": -10055}},
            "text": "Yes, please update the order",
        },
    }

    envelope = adapter.parse_update(update)

    assert envelope is not None
    assert envelope.provider_account_id == "123456789"
    assert envelope.provider_native_message_id == "44"
    assert envelope.conversation_id == "-10055"
    assert envelope.reply_to_provider_message_id == "43"
    assert envelope.relationship_source == "PROVIDER_QUOTE"
    assert envelope.correlation_id == "telegram-update:91"
    assert envelope.source_authenticity == "UNVERIFIED"


def test_whatsapp_context_parent_and_authenticated_business_account_are_wired(tmp_path):
    config = WhatsAppChannelConfig(
        phone_number_id="business-phone-9",
        access_token="test-token",
        app_secret="test-secret",
        verify_token="verify-token",
        tenant_id="tenant-a",
    )
    adapter = WhatsAppAdapter(
        config,
        InMemoryMessageRepository(),
        state_manager=ChannelStateManager(storage_path=tmp_path / "whatsapp.json"),
        clock=lambda: datetime(2026, 10, 24, tzinfo=UTC),
    )
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "business-phone-9"},
                            "contacts": [{"wa_id": "601000", "profile": {"name": "Buyer"}}],
                            "messages": [
                                {
                                    "id": "wamid.child",
                                    "from": "601000",
                                    "timestamp": "1792756800",
                                    "type": "text",
                                    "context": {"id": "wamid.parent"},
                                    "text": {"body": "That date works"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    envelopes = adapter.parse_webhook_payload(payload, correlation_id="callback:test")

    assert len(envelopes) == 1
    assert envelopes[0].provider_account_id == "business-phone-9"
    assert envelopes[0].provider_native_message_id == "wamid.child"
    assert envelopes[0].conversation_id == "601000"
    assert envelopes[0].reply_to_provider_message_id == "wamid.parent"
    assert envelopes[0].relationship_source == "PROVIDER_QUOTE"
    assert envelopes[0].source_authenticity == "UNVERIFIED"


def test_email_rfc_parent_stays_separate_from_gmail_thread(tmp_path):
    config = GmailChannelConfig(
        client_id="client-id",
        client_secret="client-secret",
        mailbox_account_id="owner@example.com",
        tenant_id="tenant-a",
    )
    adapter = GmailAdapter(
        config,
        InMemoryMessageRepository(),
        state_manager=ChannelStateManager(storage_path=tmp_path / "gmail.json"),
    )
    message = {
        "id": "gmail-native-44",
        "threadId": "gmail-thread-a",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Buyer <buyer@example.net>"},
                {"name": "Message-ID", "value": "<child@example.net>"},
                {"name": "In-Reply-To", "value": "<parent@example.net>"},
                {"name": "References", "value": "<root@example.net> <parent@example.net>"},
            ],
            "body": {"data": "VGhhdCBkYXRlIHdvcmtz"},
        },
    }

    envelope = adapter.parse_message(message)

    assert envelope is not None
    assert envelope.provider_account_id == "owner@example.com"
    assert envelope.provider_native_message_id == "gmail-native-44"
    assert envelope.thread_ref == envelope.conversation_id == "gmail-thread-a"
    assert envelope.rfc_message_id == "<child@example.net>"
    assert envelope.rfc_in_reply_to == ["<parent@example.net>"]
    assert envelope.rfc_references == ["<root@example.net>", "<parent@example.net>"]
    assert envelope.reply_to_provider_message_id == "<parent@example.net>"
    assert envelope.relationship_source == "SENDER_HEADER"
    assert envelope.source_authenticity == "UNVERIFIED"


def test_telegram_adapter_rejects_unverified_update(tmp_path):
    adapter = TelegramAdapter(
        TelegramChannelConfig(
            bot_token="123456789:token",
            tenant_id="tenant-a",
        ),
        InMemoryMessageRepository(),
        state_manager=ChannelStateManager(storage_path=tmp_path / "telegram.json"),
    )

    with pytest.raises(TelegramApiError, match="not authenticated"):
        adapter.process_update({"update_id": 1, "message": {}}, source_verified=False)


def test_whatsapp_signed_payload_account_must_match_configured_phone(tmp_path):
    config = WhatsAppChannelConfig(
        phone_number_id="business-phone-9",
        access_token="test-token",
        app_secret="test-secret",
        verify_token="verify-token",
        tenant_id="tenant-a",
    )
    adapter = WhatsAppAdapter(
        config,
        InMemoryMessageRepository(),
        state_manager=ChannelStateManager(storage_path=tmp_path / "whatsapp.json"),
    )

    with pytest.raises(InvalidWhatsAppAccountError):
        adapter.parse_webhook_payload(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "field": "messages",
                                "value": {
                                    "metadata": {"phone_number_id": "other-phone"},
                                    "messages": [],
                                },
                            }
                        ]
                    }
                ],
            }
        )
