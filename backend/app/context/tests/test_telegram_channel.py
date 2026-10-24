"""Automated tests for Telegram Bot API Inbound Channel Adapter."""

from __future__ import annotations

import io
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from app.context.channels.config import TelegramChannelConfig
from app.context.channels.state import ChannelStateManager
from app.context.channels.telegram import TelegramAdapter, TelegramApiError
from app.context.schemas import RawMessageEnvelope
from app.context.tests.in_memory_repository import InMemoryMessageRepository

# Valid 1x1 JPEG magic bytes for testing attachment validation
VALID_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4"
    b"\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)

# Valid minimal PDF magic bytes
VALID_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n"
    b"0000000060 00000 n\n0000000111 00000 n\n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
)


@pytest.fixture
def repo():
    return InMemoryMessageRepository()


@pytest.fixture
def state_mgr(tmp_path):
    return ChannelStateManager(storage_path=tmp_path / "tg_state.json")


@pytest.fixture
def tg_config():
    return TelegramChannelConfig(
        bot_token="123456789:TEST_BOT_TOKEN",
        mode="polling",
        poll_interval_seconds=0.1,
        poll_timeout_seconds=1,
        tenant_id="tenant_tg_test",
        api_base_url="https://api.telegram.org",
    )


def test_telegram_get_me_and_webhook_info(repo, state_mgr, tg_config):
    def handler(request: httpx.Request) -> httpx.Response:
        if "getMe" in str(request.url):
            return httpx.Response(200, json={"ok": True, "result": {"id": 123456789, "is_bot": True, "username": "test_bot"}})
        if "getWebhookInfo" in str(request.url):
            return httpx.Response(200, json={"ok": True, "result": {"url": "https://example.com/webhook", "has_custom_certificate": False, "pending_update_count": 0}})
        if "deleteWebhook" in str(request.url):
            return httpx.Response(200, json={"ok": True, "result": True, "description": "Webhook was deleted"})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TelegramAdapter(config=tg_config, repository=repo, state_manager=state_mgr, http_client=client)

    me = adapter.get_me()
    assert me["username"] == "test_bot"

    wh_info = adapter.get_webhook_info()
    assert wh_info["url"] == "https://example.com/webhook"

    deleted = adapter.delete_webhook()
    assert deleted is True


def test_conflict_prevention_webhook_cleared_on_polling_start(repo, state_mgr, tg_config):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "getWebhookInfo" in url_str:
            calls.append("getWebhookInfo")
            return httpx.Response(200, json={"ok": True, "result": {"url": "https://active-hook.com/wh"}})
        if "deleteWebhook" in url_str:
            calls.append("deleteWebhook")
            return httpx.Response(200, json={"ok": True, "result": True})
        if "getUpdates" in url_str:
            calls.append("getUpdates")
            return httpx.Response(200, json={"ok": True, "result": []})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TelegramAdapter(config=tg_config, repository=repo, state_manager=state_mgr, http_client=client)

    adapter.start_polling()
    time.sleep(0.3)
    adapter.stop_polling()

    assert "getWebhookInfo" in calls
    assert "deleteWebhook" in calls
    assert "getUpdates" in calls


def test_telegram_parse_text_message_and_tenant_isolation(repo, state_mgr, tg_config):
    adapter = TelegramAdapter(config=tg_config, repository=repo, state_manager=state_mgr)

    update = {
        "update_id": 1001,
        "message": {
            "message_id": 42,
            "from": {"id": 888999, "is_bot": False, "first_name": "Uncle", "last_name": "Lim", "username": "uncle_lim"},
            "chat": {"id": -100123456789, "type": "group", "title": "Burger Orders Group"},
            "date": 1729700000,
            "text": "Hello boss, need 100 burgers tomorrow before 3pm please!",
        },
    }

    envelope = adapter.parse_update(update)
    assert envelope is not None
    assert envelope.tenant_id == tg_config.tenant_id  # Enforces configured tenant
    assert envelope.channel == "TELEGRAM"
    assert envelope.adapter_mode == "REAL"
    assert envelope.provider_message_id == "tg_-100123456789_42"
    assert envelope.sender_identity_id == "888999"
    assert envelope.sender_alias == "uncle_lim"
    assert "100 burgers" in envelope.text
    assert envelope.thread_ref == "-100123456789"
    assert envelope.attachments == []


def test_telegram_parse_document_attachment(repo, state_mgr, tg_config):
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "getFile" in url_str:
            return httpx.Response(200, json={"ok": True, "result": {"file_id": "doc_123", "file_path": "documents/po_2026.pdf"}})
        if "file/bot" in url_str:
            return httpx.Response(200, content=VALID_PDF_BYTES)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TelegramAdapter(config=tg_config, repository=repo, state_manager=state_mgr, http_client=client)

    update = {
        "update_id": 1002,
        "message": {
            "message_id": 43,
            "from": {"id": 555666, "first_name": "Sarah", "username": "sarah_c"},
            "chat": {"id": 555666, "type": "private"},
            "date": 1729700100,
            "caption": "Attached is our purchase order PO-8891.",
            "document": {
                "file_id": "doc_123",
                "file_name": "po_2026.pdf",
                "mime_type": "application/pdf",
                "file_size": len(VALID_PDF_BYTES),
            },
        },
    }

    envelope = adapter.parse_update(update)
    assert envelope is not None
    assert len(envelope.attachments) == 1
    att = envelope.attachments[0]
    assert att.filename == "po_2026.pdf"
    assert att.media_type == "application/pdf"
    assert att.size_bytes == len(VALID_PDF_BYTES)
    assert envelope.native_attachment_source_ids == ["doc_123"]

    # Verify attachment is persisted in repository
    retrieved = repo.get_attachment(tg_config.tenant_id, att.evidence_ref)
    assert retrieved is not None
    record, content = retrieved
    assert record.filename == "po_2026.pdf"
    assert content == VALID_PDF_BYTES


def test_telegram_parse_photo_attachment(repo, state_mgr, tg_config):
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "getFile" in url_str:
            return httpx.Response(200, json={"ok": True, "result": {"file_id": "photo_hi_res", "file_path": "photos/receipt.jpg"}})
        if "file/bot" in url_str:
            return httpx.Response(200, content=VALID_JPEG_BYTES)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TelegramAdapter(config=tg_config, repository=repo, state_manager=state_mgr, http_client=client)

    update = {
        "update_id": 1003,
        "message": {
            "message_id": 44,
            "from": {"id": 111222, "first_name": "David"},
            "chat": {"id": 111222, "type": "private"},
            "date": 1729700200,
            "photo": [
                {"file_id": "photo_thumbnail", "width": 100, "height": 100},
                {"file_id": "photo_hi_res", "width": 800, "height": 800},
            ],
            "caption": "Payment receipt screenshot",
        },
    }

    envelope = adapter.parse_update(update)
    assert envelope is not None
    assert len(envelope.attachments) == 1
    att = envelope.attachments[0]
    assert att.filename == "photo.jpg"
    assert att.media_type == "image/jpeg"

    # Verify attachment stored
    retrieved = repo.get_attachment(tg_config.tenant_id, att.evidence_ref)
    assert retrieved is not None
    assert retrieved[1] == VALID_JPEG_BYTES


def test_telegram_offset_advancement_and_duplicate_prevention(repo, state_mgr, tg_config):
    adapter = TelegramAdapter(config=tg_config, repository=repo, state_manager=state_mgr)

    update1 = {
        "update_id": 5001,
        "message": {
            "message_id": 101,
            "from": {"id": 123, "first_name": "Alice"},
            "chat": {"id": 123},
            "date": 1729700300,
            "text": "First order: 20 burgers tomorrow",
        },
    }

    # Process first update
    res1 = adapter.process_update(update1, source_verified=True)
    assert res1 is not None
    assert res1.duplicate is False
    assert state_mgr.get_telegram_offset(tg_config.tenant_id) == 5001

    # Ingest same update again -> duplicate detected
    res2 = adapter.process_update(update1, source_verified=True)
    assert res2 is not None
    assert res2.duplicate is True


def test_telegram_poll_once_lifecycle_and_restart(repo, state_mgr, tg_config):
    update_feed = [
        {"update_id": 201, "message": {"message_id": 1, "from": {"id": 1}, "chat": {"id": 1}, "date": 1729700400, "text": "Msg 1"}},
        {"update_id": 202, "message": {"message_id": 2, "from": {"id": 1}, "chat": {"id": 1}, "date": 1729700401, "text": "Msg 2"}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": update_feed})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TelegramAdapter(config=tg_config, repository=repo, state_manager=state_mgr, http_client=client)

    count = adapter.poll_once()
    assert count == 2
    assert state_mgr.get_telegram_offset(tg_config.tenant_id) == 202

    # Second poll with same updates skips all because update_id <= 202
    count_second = adapter.poll_once()
    assert count_second == 0


def test_telegram_api_failure_records_error_in_state(repo, state_mgr, tg_config):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TelegramAdapter(config=tg_config, repository=repo, state_manager=state_mgr, http_client=client)

    with pytest.raises(TelegramApiError):
        adapter.poll_once()

    summary = state_mgr.get_channel_summary("TELEGRAM", tg_config.tenant_id)
    assert summary["last_error"] is not None
    assert "Telegram getUpdates network error" in summary["last_error"]
