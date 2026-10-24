"""C2 integration guards; provider accounts never grant business authority."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from app.context.channels.config import (
    ChannelsConfig,
    GmailChannelConfig,
    ResendChannelConfig,
    TelegramChannelConfig,
    WhatsAppChannelConfig,
)
from app.context.channels.gmail import GmailAdapter, GmailAuthError
from app.context.channels.resend import ResendAdapter, ResendWebhookError
from app.context.channels.state import ChannelStateManager
from app.context.channels.whatsapp import WhatsAppAdapter, WhatsAppWebhookError
from app.context.tests.in_memory_repository import InMemoryMessageRepository


def test_telegram_explicit_bot_must_match_token_account():
    with pytest.raises(ValidationError, match="account"):
        TelegramChannelConfig(bot_token="12345:fixture-token", bot_account_id="54321")


def test_telegram_conflicting_account_environment_aliases_fail_closed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_ID", "12345")
    monkeypatch.setenv("TELEGRAM_BOT_ACCOUNT_ID", "54321")
    with pytest.raises(ValueError, match="account"):
        ChannelsConfig.load_from_env()


def test_whatsapp_ingests_only_the_exact_signature_verified_body(tmp_path):
    repo = InMemoryMessageRepository()
    config = WhatsAppChannelConfig(
        tenant_id="tenant-c2", phone_number_id="phone-a", app_secret="fixture-secret"
    )
    adapter = WhatsAppAdapter(config, repo, ChannelStateManager(tmp_path / "state.json"))
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "phone-a"},
                            "messages": [
                                {
                                    "id": "wamid.original",
                                    "from": "60111111111",
                                    "type": "text",
                                    "text": {"body": "Original evidence"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"fixture-secret", raw, hashlib.sha256).hexdigest()
    altered = json.loads(raw)
    altered["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "Tampered"
    with pytest.raises(WhatsAppWebhookError, match="body"):
        adapter.handle_webhook_event(raw, signature, altered)
    assert repo.list("tenant-c2").total == 0


def test_resend_parser_requires_server_account_before_any_retrieval(tmp_path):
    config = ResendChannelConfig(
        api_key="fixture",
        webhook_secret="fixture",
        tenant_id="tenant-c2",
        inbound_addresses=["orders@example.test"],
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "one", "from": "buyer@example.test", "text": "body"})

    adapter = ResendAdapter(
        config,
        InMemoryMessageRepository(),
        ChannelStateManager(tmp_path / "rs.json"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ResendWebhookError, match="account"):
        adapter.process_received_event(
            b'{"type":"email.received","data":{"email_id":"one","to":["orders@example.test"]}}',
            {},
            signature_verified=True,
        )
    assert requests == []


def test_resend_references_alone_never_assert_an_exact_parent(tmp_path):
    config = ResendChannelConfig(
        api_key="fixture",
        webhook_secret="fixture",
        tenant_id="tenant-c2",
        account_id="orders@example.test",
        inbound_addresses=["orders@example.test"],
    )
    data = {
        "id": "one",
        "from": "buyer@example.test",
        "to": ["orders@example.test"],
        "text": "Source body",
        "message_id": "<one@example.test>",
        "headers": {"references": "<unproven-parent@example.test>"},
    }
    adapter = ResendAdapter(
        config,
        InMemoryMessageRepository(),
        ChannelStateManager(tmp_path / "rs.json"),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))
        ),
    )
    envelope = adapter.process_received_event(
        b'{"type":"email.received","data":{"email_id":"one","to":["orders@example.test"]}}',
        {},
        signature_verified=True,
    )
    assert envelope.provider_account_id == "orders@example.test"
    assert envelope.provider_native_message_id == "one"
    assert envelope.rfc_message_id == "<one@example.test>"
    assert envelope.reply_to_provider_message_id is None
    assert envelope.rfc_in_reply_to == []
    assert envelope.rfc_references == ["<unproven-parent@example.test>"]
    # Even an internal caller cannot bypass the unapproved provider provenance
    # gate by handing this parsed envelope directly to canonical ingestion.
    from app.context.ingestion import IngestionService, UnverifiedProviderSource

    with pytest.raises(UnverifiedProviderSource):
        IngestionService(adapter.repository).ingest(envelope, "tenant-c2")


def test_gmail_stale_verified_state_cannot_authorize_another_oauth_account(tmp_path):
    state = ChannelStateManager(tmp_path / "gmail.json")
    state.set_verified_account_id("EMAIL", "tenant-c2", "old@example.test")
    state.save_gmail_cursor("tenant-c2", 1792800000000)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"emailAddress": "new@example.test"})

    adapter = GmailAdapter(
        GmailChannelConfig(
            client_id="fixture",
            client_secret="fixture",
            access_token="fixture",
            tenant_id="tenant-c2",
        ),
        InMemoryMessageRepository(),
        state,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(GmailAuthError, match="mailbox|account"):
        adapter.poll_inbox()
    assert all(request.url.path.endswith("/profile") for request in requests)


def test_gmail_verify_cannot_rebind_existing_cursor_to_new_mailbox(tmp_path):
    state = ChannelStateManager(tmp_path / "gmail-startup.json")
    state.set_verified_account_id("EMAIL", "tenant-c2", "old@example.test")
    state.save_gmail_cursor("tenant-c2", 1792800000000)
    adapter = GmailAdapter(
        GmailChannelConfig(
            client_id="fixture",
            client_secret="fixture",
            access_token="fixture",
            tenant_id="tenant-c2",
        ),
        InMemoryMessageRepository(),
        state,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"emailAddress": "new@example.test"})
            )
        ),
    )
    assert adapter.verify_connection()["authenticated"] is False
    assert (
        state.get_channel_summary("EMAIL", "tenant-c2")["verified_account_id"] == "old@example.test"
    )


def test_gmail_inline_attachment_names_do_not_collide_or_overwrite(tmp_path):
    repo = InMemoryMessageRepository()
    adapter = GmailAdapter(
        GmailChannelConfig(tenant_id="tenant-c2", mailbox_account_id="old@example.test"),
        repo,
        ChannelStateManager(tmp_path / "gmail-media.json"),
    )
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
    part = {
        "filename": "quote.pdf",
        "mimeType": "application/pdf",
        "body": {"data": base64.urlsafe_b64encode(pdf).decode()},
    }
    _, attachments = adapter._extract_body_and_attachments(
        "native-1", {"parts": [part, part]}, datetime.now(UTC)
    )
    assert len(attachments) == 2
    assert len({a.evidence_ref for a in attachments}) == 2
    original_refs = {a.evidence_ref for a in attachments}
    adapter.config.mailbox_account_id = "other@example.test"
    _, other_account = adapter._extract_body_and_attachments(
        "native-1", {"parts": [part, part]}, datetime.now(UTC)
    )
    assert original_refs.isdisjoint({a.evidence_ref for a in other_account})
    adapter.config.mailbox_account_id = "old@example.test"
    changed = {**part, "body": {"data": base64.urlsafe_b64encode(pdf + b"changed").decode()}}
    _, changed_bytes = adapter._extract_body_and_attachments(
        "native-1", {"parts": [changed]}, datetime.now(UTC)
    )
    assert original_refs.isdisjoint({a.evidence_ref for a in changed_bytes})
    assert all(repo.get_attachment("tenant-c2", ref)[1] == pdf for ref in original_refs)


def test_resend_status_requires_native_provider_id(tmp_path):
    adapter = ResendAdapter(
        ResendChannelConfig(tenant_id="tenant-c2"),
        InMemoryMessageRepository(),
        ChannelStateManager(tmp_path / "rs-status.json"),
    )
    receipt = adapter.parse_status_event(
        {
            "type": "email.delivered",
            "data": {"email_id": "native-1", "message_id": "<rfc@example.test>"},
        }
    )
    assert receipt.provider_message_id == "native-1"
    assert (
        adapter.parse_status_event(
            {"type": "email.delivered", "data": {"message_id": "<rfc@example.test>"}}
        )
        is None
    )
