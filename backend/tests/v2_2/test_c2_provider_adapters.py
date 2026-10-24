from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.context.channels.config import (
    ChannelsConfig,
    GmailChannelConfig,
    ResendChannelConfig,
    TelegramChannelConfig,
    WhatsAppChannelConfig,
)
from app.context.channels.gmail import GmailAdapter, GmailApiError
from app.context.channels.manager import ChannelManager
from app.context.channels.resend import ResendAdapter, ResendWebhookError
from app.context.channels.router import get_manager
from app.context.channels.router import router as channels_router
from app.context.channels.state import ChannelStateManager
from app.context.channels.telegram import TelegramAdapter, TelegramApiError
from app.context.channels.whatsapp import WhatsAppAdapter, WhatsAppWebhookError
from app.context.tests.in_memory_repository import InMemoryMessageRepository


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


@pytest.fixture
def repo():
    return InMemoryMessageRepository()


@pytest.fixture
def state_mgr(tmp_path):
    return ChannelStateManager(storage_path=tmp_path / "c2_state.json")


def test_telegram_preserves_native_reply_reference_and_scoped_provider_id(repo, state_mgr):
    config = TelegramChannelConfig(
        bot_token="123456789:fixture-token",
        tenant_id="tenant_tg_c2",
        bot_account_id="123456789",
        webhook_secret="fixture_webhook_secret",
    )
    adapter = TelegramAdapter(config, repo, state_mgr)
    assert adapter.validate_webhook_secret("fixture_webhook_secret") is True
    assert adapter.validate_webhook_secret("wrong") is False
    assert adapter.validate_webhook_secret(None) is False

    envelope = adapter.parse_update({"message": {
        "message_id": 52,
        "from": {"id": 77, "username": "buyer"},
        "chat": {"id": 77, "type": "private"},
        "date": 1792800000,
        "text": "Yes, please confirm the order",
        "reply_to_message": {"message_id": 49},
    }})

    assert envelope is not None
    assert envelope.tenant_id == "tenant_tg_c2"
    assert envelope.provider_message_id == "tg_123456789_77_52"
    assert envelope.thread_ref == "77"
    assert envelope.reply_to_provider_message_id == "tg_123456789_77_49"


def test_telegram_send_is_allowlisted_and_replay_safe(repo, state_mgr):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 901, "chat": {"id": 77}}})

    config = TelegramChannelConfig(
        bot_token="123456789:fixture-token",
        tenant_id="tenant_tg_c2",
        bot_account_id="123456789",
        outbound_enabled=True,
        test_recipient_ids=["77"],
    )
    adapter = TelegramAdapter(config, repo, state_mgr,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = adapter.send_text("77", "Approved factual update", idempotency_key="outbound-1",
        reply_to_message_id=49)
    replay = adapter.send_text("77", "Approved factual update", idempotency_key="outbound-1",
        reply_to_message_id=49)

    assert result.state == "ACCEPTED"
    assert result.provider_message_id == "tg_123456789_77_901"
    assert replay.idempotent_replay is True
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["reply_parameters"] == {"message_id": 49}


def test_telegram_outbound_fails_closed_for_unlisted_recipient(repo, state_mgr):
    config = TelegramChannelConfig(bot_token="123456789:fixture-token", outbound_enabled=True,
        test_recipient_ids=["88"])
    adapter = TelegramAdapter(config, repo, state_mgr)

    with pytest.raises(TelegramApiError, match="recipient"):
        adapter.send_text("77", "message", idempotency_key="blocked")


def test_telegram_document_retrieval_uses_provider_file_api_and_existing_evidence(repo, state_mgr):
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "documents/po.pdf"}})
        if request.url.path.endswith("/documents/po.pdf"):
            return httpx.Response(200, content=pdf)
        return httpx.Response(404)

    config = TelegramChannelConfig(bot_token="123456789:fixture-token", tenant_id="tenant_tg_c2",
        api_base_url="https://api.telegram.test")
    adapter = TelegramAdapter(config, repo, state_mgr,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    envelope = adapter.parse_update({"message": {"message_id": 60, "from": {"id": 77},
        "chat": {"id": 77, "type": "private"}, "date": 1792800000,
        "document": {"file_id": "file-1", "file_name": "po.pdf", "mime_type": "application/pdf"}}})

    assert envelope is not None and len(envelope.attachments) == 1
    saved = repo.get_attachment("tenant_tg_c2", envelope.attachments[0].evidence_ref)
    assert saved is not None and saved[1] == pdf
    assert requests[0].url.path.endswith("/getFile")
    assert requests[1].url.path.endswith("/file/bot123456789:fixture-token/documents/po.pdf")

    unsafe = TelegramAdapter(config, repo, state_mgr, http_client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": True, "result": {"file_path": "../secret.pdf"}}))))
    with pytest.raises(TelegramApiError, match="invalid file path"):
        unsafe.download_file("file-unsafe")


def test_whatsapp_rejects_wrong_phone_number_account_and_preserves_quoted_parent(repo, state_mgr):
    config = WhatsAppChannelConfig(
        phone_number_id="phone-test-1", access_token="fixture-token", app_secret="fixture-secret",
        verify_token="verify", tenant_id="tenant_wa_c2",
    )
    adapter = WhatsAppAdapter(config, repo, state_mgr)
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages",
        "value": {"metadata": {"phone_number_id": "phone-other"}, "messages": []}}]}]}

    with pytest.raises(WhatsAppWebhookError, match="phone number"):
        adapter.parse_webhook_payload(payload)

    payload["entry"][0]["changes"][0]["value"] = {"messages": []}
    with pytest.raises(WhatsAppWebhookError, match="phone number"):
        adapter.parse_webhook_payload(payload)

    payload["entry"][0]["changes"][0]["value"] = {
        "metadata": {"phone_number_id": "phone-test-1"},
        "messages": [{"from": "6012345", "id": "wamid.child", "timestamp": "1792800000",
            "type": "text", "text": {"body": "reply"}, "context": {"id": "wamid.parent"}}],
    }
    envelope = adapter.parse_webhook_payload(payload)[0]
    assert envelope.tenant_id == "tenant_wa_c2"
    assert envelope.provider_message_id == "wamid.child"
    assert envelope.reply_to_provider_message_id == "wamid.parent"


def test_whatsapp_document_retrieval_is_host_bounded_and_saves_evidence(repo, state_mgr):
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "graph.facebook.com":
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/doc-1"})
        if request.url.host == "lookaside.fbsbx.com":
            return httpx.Response(200, content=pdf)
        return httpx.Response(404)

    config = WhatsAppChannelConfig(phone_number_id="phone-test-1", access_token="fixture-token",
        app_secret="fixture-secret", tenant_id="tenant_wa_c2")
    adapter = WhatsAppAdapter(config, repo, state_mgr,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "phone-test-1"}, "messages": [{"from": "6012345",
            "id": "wamid.document", "timestamp": "1792800000", "type": "document",
            "document": {"id": "doc-1", "filename": "po.pdf", "mime_type": "application/pdf"}}]}}]}]}

    envelope = adapter.parse_webhook_payload(payload)[0]

    assert len(envelope.attachments) == 1
    saved = repo.get_attachment("tenant_wa_c2", envelope.attachments[0].evidence_ref)
    assert saved is not None and saved[1] == pdf
    assert requests[1].headers["authorization"] == "Bearer fixture-token"

    unsafe = WhatsAppAdapter(config, repo, state_mgr, http_client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"url": "https://evil.example/steal"}))))
    with pytest.raises(WhatsAppWebhookError, match="trusted Meta media hosts"):
        unsafe.download_media("doc-unsafe")


def test_whatsapp_status_callbacks_are_structured_and_not_ingested(repo, state_mgr):
    config = WhatsAppChannelConfig(phone_number_id="phone-test-1", access_token="fixture-token",
        app_secret="fixture-secret", verify_token="verify", tenant_id="tenant_wa_c2")
    adapter = WhatsAppAdapter(config, repo, state_mgr)
    payload = {"entry": [{"changes": [{"field": "messages", "value": {"metadata": {
        "phone_number_id": "phone-test-1"}, "statuses": [{"id": "wamid.out", "status": "delivered",
        "timestamp": "1792800001", "recipient_id": "6012345"}]}}]}]}

    statuses = adapter.parse_status_callbacks(payload)

    assert len(statuses) == 1
    assert statuses[0].provider_message_id == "wamid.out"
    assert statuses[0].state == "DELIVERED"
    assert statuses[0].tenant_id == "tenant_wa_c2"


def test_whatsapp_send_enforces_window_or_template_and_quotes_parent(repo, state_mgr):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.sent"}]})

    config = WhatsAppChannelConfig(
        phone_number_id="phone-test-1", access_token="fixture-token", app_secret="fixture-secret",
        verify_token="verify", tenant_id="tenant_wa_c2", outbound_enabled=True,
        test_recipient_ids=["6012345"], approved_templates=["hello_world"],
    )
    adapter = WhatsAppAdapter(config, repo, state_mgr,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: datetime(2026, 10, 24, 12, tzinfo=UTC))

    with pytest.raises(WhatsAppWebhookError, match="service window"):
        adapter.send_text("6012345", "reply", idempotency_key="wa-blocked")
    result = adapter.send_text("6012345", "reply", idempotency_key="wa-send-1",
        service_window_expires_at=datetime(2026, 10, 24, 13, tzinfo=UTC),
        reply_to_message_id="wamid.inbound")

    assert result.state == "ACCEPTED"
    body = json.loads(requests[0].content)
    assert body["context"] == {"message_id": "wamid.inbound"}
    template_result = adapter.send_template("6012345", "hello_world", "en_US", idempotency_key="wa-template-1")
    assert template_result.state == "ACCEPTED"
    assert json.loads(requests[1].content)["template"]["name"] == "hello_world"


def test_resend_signature_raw_body_timestamp_and_provider_receive_flow(repo, state_mgr):
    webhook_secret = "whsec_" + base64.b64encode(b"fixture-resend-secret").decode()
    timestamp = str(int(time.time()))
    event_id = "evt_fixture_1"
    raw = json.dumps({"type": "email.received", "data": {"email_id": "recv_1",
        "from": "Buyer <buyer@example.test>", "to": ["orders@example.test"],
        "subject": "PO 1", "message_id": "<inbound-1@example.test>"}}, separators=(",", ":")).encode()
    signature = base64.b64encode(hmac.new(base64.b64decode(webhook_secret[6:]),
        f"{event_id}.{timestamp}.".encode() + raw, hashlib.sha256).digest()).decode()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/emails/receiving/recv_1"):
            return httpx.Response(200, json={"id": "recv_1", "from": "Buyer <buyer@example.test>",
                "to": ["orders@example.test"], "subject": "PO 1", "text": "Please quote 10 boxes.",
                "message_id": "<inbound-1@example.test>", "headers": {"in-reply-to": "<parent@example.test>"}})
        return httpx.Response(404)

    config = ResendChannelConfig(api_key="re_fixture", webhook_secret=webhook_secret,
        tenant_id="tenant_email_c2", inbound_addresses=["orders@example.test"])
    adapter = ResendAdapter(config, repo, state_mgr,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    envelope = adapter.process_received_event(raw,
        {"svix-id": event_id, "svix-timestamp": timestamp, "svix-signature": f"v1,{signature}"})

    assert envelope.tenant_id == "tenant_email_c2"
    assert envelope.provider_message_id == "<inbound-1@example.test>"
    assert envelope.thread_ref == "<inbound-1@example.test>"
    assert envelope.reply_to_provider_message_id == "<parent@example.test>"
    assert "Please quote 10 boxes" in envelope.text
    assert requests[0].headers["authorization"] == "Bearer re_fixture"
    status = adapter.parse_status_event({"type": "email.delivered", "created_at": "2026-10-24T12:00:00Z",
        "data": {"email_id": "sent_1", "message_id": "<sent@example.test>"}})
    assert status is not None and status.state == "DELIVERED"
    assert status.provider_message_id == "<sent@example.test>"

    with pytest.raises(ResendWebhookError, match="signature"):
        adapter.process_received_event(raw + b" ",
            {"svix-id": event_id, "svix-timestamp": timestamp, "svix-signature": f"v1,{signature}"})


def test_signed_resend_route_ingests_via_existing_p1_repository(repo, state_mgr):
    webhook_secret = "whsec_" + base64.b64encode(b"fixture-route-secret").decode()
    raw = json.dumps({"type": "email.received", "data": {"email_id": "route_recv_1",
        "from": "Buyer <buyer@example.test>", "to": ["orders@example.test"],
        "subject": "PO", "message_id": "<route-message@example.test>"}}, separators=(",", ":")).encode()
    timestamp, event_id = str(int(time.time())), "evt_route_1"
    signature = base64.b64encode(hmac.new(base64.b64decode(webhook_secret[6:]),
        f"{event_id}.{timestamp}.".encode() + raw, hashlib.sha256).digest()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer re_fixture"
        return httpx.Response(200, json={"id": "route_recv_1", "from": "buyer@example.test",
            "to": ["orders@example.test"], "subject": "PO", "text": "Please quote ten boxes.",
            "message_id": "<route-message@example.test>"})

    config = ChannelsConfig(resend=ResendChannelConfig(api_key="re_fixture", webhook_secret=webhook_secret,
        tenant_id="tenant_email_c2", inbound_addresses=["orders@example.test"]))
    manager = ChannelManager(config=config, repository=repo, state_manager=state_mgr)
    manager.resend._custom_client = httpx.Client(transport=httpx.MockTransport(handler))
    test_app = FastAPI()
    test_app.include_router(channels_router)
    test_app.dependency_overrides[get_manager] = lambda: manager
    headers = {"svix-id": event_id, "svix-timestamp": timestamp, "svix-signature": f"v1,{signature}"}

    with TestClient(test_app) as client:
        rejected = client.post("/v1/channels/resend/webhook", content=raw,
            headers={**headers, "svix-signature": "v1,bad"})
        assert rejected.status_code == 401
        assert repo.list("tenant_email_c2").total == 0
        response = client.post("/v1/channels/resend/webhook", content=raw, headers=headers)
        duplicate = client.post("/v1/channels/resend/webhook", content=raw, headers=headers)

    assert response.status_code == 200
    assert response.json()["processed"] is True
    assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
    stored = repo.list("tenant_email_c2", channel="EMAIL").items[0]
    assert stored.raw.provider_message_id == "<route-message@example.test>"
    assert stored.raw.adapter_mode == "REAL"


def test_resend_reply_transport_uses_verified_from_safe_reply_to_and_rfc_headers(repo, state_mgr):
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "email_sent_1", "message_id": "<sent@example.test>"})

    config = ResendChannelConfig(api_key="re_fixture", tenant_id="tenant_email_c2",
        outbound_enabled=True, test_recipients=["buyer@example.test"],
        verified_from_email="MouManTAI <orders@verified.example.test>",
        reply_to_email="support@verified.example.test")
    adapter = ResendAdapter(config, repo, state_mgr,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = adapter.send_reply(to="buyer@example.test", subject="Re: PO",
        text="Approved update", idempotency_key="email-send-1",
        in_reply_to="<inbound@example.test>", references=["<root@example.test>", "<inbound@example.test>"])

    assert result.state == "ACCEPTED"
    assert captured[0].headers["idempotency-key"] == "email-send-1"
    body = json.loads(captured[0].content)
    assert body["from"] == "MouManTAI <orders@verified.example.test>"
    assert body["reply_to"] == ["support@verified.example.test"]
    assert body["headers"]["In-Reply-To"] == "<inbound@example.test>"
    assert body["headers"]["References"] == "<root@example.test> <inbound@example.test>"


def test_resend_attachment_retrieval_uses_resend_cdn_and_existing_p1_evidence(repo, state_mgr):
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
    webhook_secret = "whsec_" + base64.b64encode(b"fixture-resend-secret").decode()
    timestamp, event_id = str(int(time.time())), "evt_attachment_1"
    raw = json.dumps({"type": "email.received", "data": {"email_id": "recv_att",
        "from": "Buyer <buyer@example.test>", "to": ["orders@example.test"],
        "subject": "PO", "attachments": [{"id": "att_1", "filename": "po.pdf",
            "content_type": "application/pdf"}]}}, separators=(",", ":")).encode()
    signature = base64.b64encode(hmac.new(base64.b64decode(webhook_secret[6:]),
        f"{event_id}.{timestamp}.".encode() + raw, hashlib.sha256).digest()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.resend.com" and request.url.path.endswith("/emails/receiving/recv_att"):
            return httpx.Response(200, json={"id": "recv_att", "from": "buyer@example.test",
                "to": ["orders@example.test"], "subject": "PO", "text": "Please see attached.",
                "created_at": "2026-10-24T11:00:00Z"})
        if request.url.host == "api.resend.com" and request.url.path.endswith("/attachments/att_1"):
            return httpx.Response(200, json={"id": "att_1", "filename": "po.pdf", "size": len(pdf),
                "content_type": "application/pdf",
                "download_url": "https://inbound-cdn.resend.com/recv_att/attachments/att_1?sig=fixture"})
        if request.url.host == "inbound-cdn.resend.com":
            return httpx.Response(200, content=pdf)
        return httpx.Response(404)

    config = ResendChannelConfig(api_key="re_fixture", webhook_secret=webhook_secret,
        tenant_id="tenant_email_c2", inbound_addresses=["orders@example.test"])
    adapter = ResendAdapter(config, repo, state_mgr,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    envelope = adapter.process_received_event(raw,
        {"svix-id": event_id, "svix-timestamp": timestamp, "svix-signature": f"v1,{signature}"})

    assert envelope is not None and len(envelope.attachments) == 1
    stored = repo.get_attachment("tenant_email_c2", envelope.attachments[0].evidence_ref)
    assert stored is not None and stored[1] == pdf


def test_telegram_timeout_is_unknown_and_never_automatically_replayed(repo, state_mgr):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("simulated provider timeout", request=request)

    config = TelegramChannelConfig(bot_token="123456789:fixture-token", outbound_enabled=True,
        test_recipient_ids=["77"])
    adapter = TelegramAdapter(config, repo, state_mgr,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    first = adapter.send_text("77", "message", idempotency_key="timeout-1")
    second = adapter.send_text("77", "message", idempotency_key="timeout-1")

    assert first.state == "UNKNOWN" and first.error_code == "PROVIDER_TIMEOUT"
    assert second.idempotent_replay is True
    assert len(calls) == 1


def test_resend_rejects_header_injection_and_unapproved_recipients(repo, state_mgr):
    config = ResendChannelConfig(api_key="re_fixture", outbound_enabled=True,
        test_recipients=["buyer@example.test"], verified_from_email="orders@verified.example.test")
    adapter = ResendAdapter(config, repo, state_mgr)

    with pytest.raises(ResendWebhookError, match="recipient"):
        adapter.send_reply(to="attacker@example.test", subject="Re: PO", text="x", idempotency_key="blocked")
    with pytest.raises(ResendWebhookError, match="header"):
        adapter.send_reply(to="buyer@example.test", subject="Re: PO", text="x", idempotency_key="blocked2",
            in_reply_to="<bad@example.test>\r\nBcc: attacker@example.test")
    with pytest.raises(ResendWebhookError, match="idempotency key"):
        adapter.send_reply(to="buyer@example.test", subject="Re: PO", text="x", idempotency_key="bad\r\nX: y")


def test_gmail_reply_association_uses_exact_parent_and_keeps_from_as_sender(repo, state_mgr):
    config = GmailChannelConfig(tenant_id="tenant_gmail_c2")
    adapter = GmailAdapter(config, repo, state_mgr)
    msg = {"id": "gmail-native-9", "threadId": "thread-native-2", "internalDate": "1792800000000",
        "payload": {"headers": [
            {"name": "From", "value": "Buyer <buyer@example.test>"},
            {"name": "Reply-To", "value": "attacker@evil.example"},
            {"name": "Subject", "value": "Re: Order"},
            {"name": "Message-ID", "value": "<child@example.test>"},
            {"name": "In-Reply-To", "value": "<exact-parent@example.test>"},
            {"name": "References", "value": "<root@example.test> <exact-parent@example.test>"},
        ], "mimeType": "text/plain", "body": {"data": _b64url(b"Please continue.")}}}

    envelope = adapter.parse_message(msg)

    assert envelope is not None
    assert envelope.sender_identity_id == "buyer@example.test"
    assert envelope.thread_ref == "thread-native-2"
    assert envelope.reply_to_provider_message_id == "<exact-parent@example.test>"


def test_gmail_attachment_retrieval_is_authenticated_and_bounded(repo, state_mgr):
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/messages/msg-1/attachments/att-1"):
            return httpx.Response(200, json={"data": _b64url(pdf)})
        return httpx.Response(200, content=b"{}", headers={"content-length": str(15 * 1024 * 1024)})

    config = GmailChannelConfig(access_token="fixture-token")
    adapter = GmailAdapter(config, repo, state_mgr,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert adapter.download_attachment("msg-1", "att-1") == pdf
    assert requests[0].headers["authorization"] == "Bearer fixture-token"
    with pytest.raises(GmailApiError, match="download_attachment error"):
        adapter.download_attachment("msg-2", "att-2")


def test_safe_get_retries_only_read_gateway_failures():
    from app.context.channels.provider_transport import (
        ProviderPayloadTooLarge,
        read_limited_get,
        safe_get,
    )

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    response = safe_get(httpx.Client(transport=httpx.MockTransport(handler)), "https://provider.test/read")
    assert response.status_code == 200
    assert len(calls) == 2

    oversize_client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"0123456789")))
    with pytest.raises(ProviderPayloadTooLarge):
        read_limited_get(oversize_client, "https://provider.test/media", 5)
