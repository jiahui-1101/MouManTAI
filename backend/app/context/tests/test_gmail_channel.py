"""Automated tests for Google OAuth and Gmail Inbound Channel Adapter."""

from __future__ import annotations

import base64
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.context.channels.config import GmailChannelConfig
from app.context.channels.gmail import GmailAdapter, GmailAuthError, _strip_html_tags
from app.context.channels.state import ChannelStateManager
from app.context.tests.in_memory_repository import InMemoryMessageRepository

# Valid minimal PDF magic bytes
VALID_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n"
    b"0000000060 00000 n\n0000000111 00000 n\n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


@pytest.fixture
def repo():
    return InMemoryMessageRepository()


@pytest.fixture
def state_mgr(tmp_path):
    return ChannelStateManager(storage_path=tmp_path / "gmail_state.json")


@pytest.fixture
def gmail_config():
    return GmailChannelConfig(
        client_id="test_client_id.apps.googleusercontent.com",
        client_secret="test_client_secret_xyz",
        refresh_token="test_refresh_token_123",
        access_token="test_access_token_abc",
        redirect_uri="http://localhost:8000/v1/channels/gmail/oauth/callback",
        poll_interval_seconds=0.1,
        tenant_id="tenant_gmail_test",
        api_base_url="https://gmail.googleapis.com",
    )


def test_gmail_authorization_url_generation(repo, state_mgr, gmail_config):
    adapter = GmailAdapter(config=gmail_config, repository=repo, state_manager=state_mgr)
    url = adapter.get_authorization_url(state="csrf_nonce_99")

    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    qs = parse_qs(parsed.query)

    assert qs["client_id"] == [gmail_config.client_id]
    assert qs["redirect_uri"] == [gmail_config.redirect_uri]
    assert qs["response_type"] == ["code"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert qs["state"] == ["csrf_nonce_99"]
    assert "https://www.googleapis.com/auth/gmail.readonly" in qs["scope"][0]


def test_gmail_exchange_code(repo, state_mgr, gmail_config):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "oauth2.googleapis.com/token" in str(request.url)
        return httpx.Response(200, json={
            "access_token": "new_access_token_111",
            "refresh_token": "new_refresh_token_222",
            "expires_in": 3600,
            "token_type": "Bearer",
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GmailAdapter(config=gmail_config, repository=repo, state_manager=state_mgr, http_client=client)

    token_data = adapter.exchange_code("auth_code_xyz")
    assert token_data["access_token"] == "new_access_token_111"
    assert token_data["refresh_token"] == "new_refresh_token_222"
    assert adapter.config.access_token == "new_access_token_111"

    saved = state_mgr.get_gmail_tokens(gmail_config.tenant_id)
    assert saved["access_token"] == "new_access_token_111"


def test_gmail_token_refresh_and_invalid_grant_handling(repo, state_mgr, gmail_config):
    # 1. Normal refresh
    def success_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "access_token": "refreshed_access_token_333",
            "expires_in": 3600,
        })

    client = httpx.Client(transport=httpx.MockTransport(handler=success_handler))
    adapter = GmailAdapter(config=gmail_config, repository=repo, state_manager=state_mgr, http_client=client)
    token = adapter.refresh_access_token()
    assert token == "refreshed_access_token_333"

    # 2. Invalid grant (revoked token)
    def revoked_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={
            "error": "invalid_grant",
            "error_description": "Token has been expired or revoked.",
        })

    client_revoked = httpx.Client(transport=httpx.MockTransport(handler=revoked_handler))
    adapter_revoked = GmailAdapter(config=gmail_config, repository=repo, state_manager=state_mgr, http_client=client_revoked)

    with pytest.raises(GmailAuthError) as exc_info:
        adapter_revoked.refresh_access_token()
    assert "expired or been revoked" in str(exc_info.value)

    summary = state_mgr.get_channel_summary("EMAIL", gmail_config.tenant_id)
    assert summary["status"] == "AUTH_EXPIRED"


def test_strip_html_tags_utility():
    html = "<div><p>Hello <b>MouManTAI Team</b>!</p><br/>Please process our <i>PO-9912</i> for 50 burgers.</div>"
    clean = _strip_html_tags(html)
    assert "Hello MouManTAI Team!" in clean
    assert "PO-9912 for 50 burgers." in clean
    assert "<" not in clean and ">" not in clean


def test_gmail_parse_multipart_mime_message(repo, state_mgr, gmail_config):
    adapter = GmailAdapter(config=gmail_config, repository=repo, state_manager=state_mgr)

    body_bytes = b"Dear Sales,\nWe require 80 burgers for tomorrow lunch (24 Oct 12:30pm).\nThanks,\nDavid"

    msg_data = {
        "id": "18f1a2b3c4d5e6f7",
        "threadId": "thread_882910",
        "internalDate": "1729700000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "David Tan <david.tan@sunrisebistro.my>"},
                {"name": "Subject", "value": "Urgent Catering Request: 80 Burgers"},
                {"name": "Date", "value": "Thu, 23 Oct 2026 16:00:00 +0800"},
                {"name": "Message-ID", "value": "<po-882910@sunrisebistro.my>"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64url(body_bytes), "size": len(body_bytes)},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64url(b"<p>HTML fallback version</p>"), "size": 25},
                },
            ],
        },
    }

    envelope = adapter.parse_message(msg_data)
    assert envelope is not None
    assert envelope.tenant_id == gmail_config.tenant_id
    assert envelope.channel == "EMAIL"
    assert envelope.adapter_mode == "REAL"
    assert envelope.provider_message_id == "gmail_18f1a2b3c4d5e6f7"
    assert envelope.sender_identity_id == "david.tan@sunrisebistro.my"
    assert envelope.sender_alias == "David Tan"
    assert envelope.thread_ref == "thread_882910"
    assert "Subject: Urgent Catering Request: 80 Burgers" in envelope.text
    assert "80 burgers for tomorrow lunch" in envelope.text
    assert envelope.attachments == []


def test_gmail_parse_attachment(repo, state_mgr, gmail_config):
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "attachments/att_pdf_11" in url_str:
            return httpx.Response(200, json={"data": _b64url(VALID_PDF_BYTES), "size": len(VALID_PDF_BYTES)})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GmailAdapter(config=gmail_config, repository=repo, state_manager=state_mgr, http_client=client)

    msg_data = {
        "id": "18f1a2b3c4d5e6f8",
        "threadId": "thread_882911",
        "internalDate": "1729700100000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "procurement@campusdining.edu.my"},
                {"name": "Subject", "value": "Official PO Attachment"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64url(b"Please see attached PO document."), "size": 30},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "official_po.pdf",
                    "body": {"attachmentId": "att_pdf_11", "size": len(VALID_PDF_BYTES)},
                },
            ],
        },
    }

    envelope = adapter.parse_message(msg_data)
    assert envelope is not None
    assert len(envelope.attachments) == 1
    att = envelope.attachments[0]
    assert att.filename == "official_po.pdf"
    assert att.media_type == "application/pdf"
    assert att.size_bytes == len(VALID_PDF_BYTES)

    # Verify attachment is saved in repository
    retrieved = repo.get_attachment(gmail_config.tenant_id, att.evidence_ref)
    assert retrieved is not None
    assert retrieved[1] == VALID_PDF_BYTES


def test_gmail_incremental_polling_and_deduplication(repo, state_mgr, gmail_config):
    body_text = b"Restock 50 burgers needed tomorrow."

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "users/me/messages?" in url_str or url_str.endswith("users/me/messages"):
            return httpx.Response(200, json={
                "messages": [{"id": "msg_001"}, {"id": "msg_002"}],
                "resultSizeEstimate": 2,
            })
        if "users/me/messages/msg_001" in url_str:
            return httpx.Response(200, json={
                "id": "msg_001",
                "internalDate": "1729700500000",
                "payload": {
                    "headers": [{"name": "From", "value": "buyer1@biz.my"}, {"name": "Subject", "value": "Order 1"}],
                    "body": {"data": _b64url(body_text)},
                },
            })
        if "users/me/messages/msg_002" in url_str:
            return httpx.Response(200, json={
                "id": "msg_002",
                "internalDate": "1729700600000",
                "payload": {
                    "headers": [{"name": "From", "value": "buyer2@biz.my"}, {"name": "Subject", "value": "Order 2"}],
                    "body": {"data": _b64url(body_text)},
                },
            })
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GmailAdapter(config=gmail_config, repository=repo, state_manager=state_mgr, http_client=client)

    count = adapter.poll_inbox()
    assert count == 2

    # Check cursor updated to highest internalDate
    cursor = state_mgr.get_gmail_cursor(gmail_config.tenant_id)
    assert cursor == 1729700600000

    # Poll second time: seen IDs are skipped in memory/cursor
    count2 = adapter.poll_inbox()
    assert count2 == 0


def test_gmail_get_profile_and_verify_connection(repo, state_mgr, gmail_config):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "users/me/profile" in str(request.url)
        return httpx.Response(200, json={
            "emailAddress": "dedicated-moumantai@gmail.com",
            "messagesTotal": 42,
            "threadsTotal": 15,
            "historyId": "999888",
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GmailAdapter(config=gmail_config, repository=repo, state_manager=state_mgr, http_client=client)

    profile = adapter.get_profile()
    assert profile["emailAddress"] == "dedicated-moumantai@gmail.com"
    assert profile["messagesTotal"] == 42

    verification = adapter.verify_connection()
    assert verification["authenticated"] is True
    assert verification["masked_email"] == "ded***@gmail.com"
    assert verification["messages_total"] == 42


def test_gmail_config_supports_web_and_installed_formats(tmp_path, monkeypatch):
    import json
    from app.context.channels.config import ChannelsConfig

    # 1. Test web format
    web_file = tmp_path / "web_client.json"
    web_file.write_text(json.dumps({
        "web": {
            "client_id": "web_id_123.apps.googleusercontent.com",
            "client_secret": "web_sec_abc",
            "redirect_uris": ["http://localhost:8000/v1/channels/gmail/oauth/callback"],
        }
    }), encoding="utf-8")

    monkeypatch.setenv("GMAIL_CREDENTIALS_FILE", str(web_file))
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)

    cfg = ChannelsConfig.load_from_env()
    assert cfg.gmail.client_id == "web_id_123.apps.googleusercontent.com"
    assert cfg.gmail.client_secret == "web_sec_abc"
    assert cfg.gmail.can_authorize is True

    # 2. Test installed format
    inst_file = tmp_path / "installed_client.json"
    inst_file.write_text(json.dumps({
        "installed": {
            "client_id": "inst_id_456.apps.googleusercontent.com",
            "client_secret": "inst_sec_xyz",
            "redirect_uris": ["http://localhost"],
        }
    }), encoding="utf-8")

    monkeypatch.setenv("GMAIL_CREDENTIALS_FILE", str(inst_file))
    cfg_inst = ChannelsConfig.load_from_env()
    assert cfg_inst.gmail.client_id == "inst_id_456.apps.googleusercontent.com"
    assert cfg_inst.gmail.client_secret == "inst_sec_xyz"


def test_gmail_adapter_discards_stale_tokens_on_new_refresh_token(repo, tmp_path, gmail_config):
    # Setup state manager with OLD tokens
    state_file = tmp_path / "channel_state.json"
    state_mgr = ChannelStateManager(storage_path=state_file)
    state_mgr.save_gmail_tokens(gmail_config.tenant_id, {
        "access_token": "stale_old_access_token",
        "refresh_token": "stale_old_refresh_token",
    })

    # New config with different refresh token
    gmail_config.refresh_token = "brand_new_refresh_token"
    gmail_config.access_token = None

    adapter = GmailAdapter(config=gmail_config, repository=repo, state_manager=state_mgr)

    # Old stale access token MUST NOT be loaded
    assert adapter.config.access_token is None
    assert adapter.config.refresh_token == "brand_new_refresh_token"
