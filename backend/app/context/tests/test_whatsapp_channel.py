"""Automated tests for Meta WhatsApp Cloud API Inbound Webhook Adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.context.channels.config import WhatsAppChannelConfig
from app.context.channels.state import ChannelStateManager
from app.context.channels.whatsapp import (
    InvalidSignatureError,
    WebhookVerificationError,
    WhatsAppAdapter,
)
from app.context.tests.in_memory_repository import InMemoryMessageRepository

# Valid 1x1 JPEG bytes for media testing
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


@pytest.fixture
def repo():
    return InMemoryMessageRepository()


@pytest.fixture
def state_mgr(tmp_path):
    return ChannelStateManager(storage_path=tmp_path / "wa_state.json")


@pytest.fixture
def wa_config():
    return WhatsAppChannelConfig(
        phone_number_id="109876543210987",
        access_token="EAAX_TEST_ACCESS_TOKEN",
        app_secret="test_meta_app_secret_abc123",
        verify_token="test_my_secure_verify_token_77",
        tenant_id="tenant_wa_test",
        api_base_url="https://graph.facebook.com/v21.0",
    )


def test_whatsapp_webhook_challenge_verification(repo, state_mgr, wa_config):
    adapter = WhatsAppAdapter(config=wa_config, repository=repo, state_manager=state_mgr)

    # 1. Valid handshake
    challenge_val = "1158201244"
    result = adapter.verify_challenge(
        mode="subscribe",
        verify_token="test_my_secure_verify_token_77",
        challenge=challenge_val,
    )
    assert result == challenge_val

    summary = state_mgr.get_channel_summary("WHATSAPP", wa_config.tenant_id)
    assert summary["status"] == "WEBHOOK_VERIFIED"

    # 2. Invalid verify token
    with pytest.raises(WebhookVerificationError) as exc_info:
        adapter.verify_challenge(
            mode="subscribe",
            verify_token="wrong_token_here",
            challenge=challenge_val,
        )
    assert "Invalid hub.verify_token" in str(exc_info.value)

    # 3. Invalid mode
    with pytest.raises(WebhookVerificationError) as exc_info:
        adapter.verify_challenge(
            mode="unsubscribe",
            verify_token=wa_config.verify_token,
            challenge=challenge_val,
        )
    assert "Unsupported hub.mode" in str(exc_info.value)


def test_whatsapp_hmac_signature_validation(repo, state_mgr, wa_config):
    adapter = WhatsAppAdapter(config=wa_config, repository=repo, state_manager=state_mgr)
    payload_bytes = b'{"object":"whatsapp_business_account","entry":[]}'

    # Compute valid signature
    valid_sig_hex = hmac.new(
        wa_config.app_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    valid_header = f"sha256={valid_sig_hex}"

    # 1. Valid signature passes
    assert adapter.validate_signature(payload_bytes, valid_header) is True

    # 2. Tampered body fails
    tampered_bytes = b'{"object":"whatsapp_business_account","entry":[{"tampered":true}]}'
    with pytest.raises(InvalidSignatureError):
        adapter.validate_signature(tampered_bytes, valid_header)

    # 3. Missing header fails
    with pytest.raises(InvalidSignatureError) as exc_info:
        adapter.validate_signature(payload_bytes, None)
    assert "Missing X-Hub-Signature-256 header" in str(exc_info.value)

    # 4. Wrong prefix fails
    with pytest.raises(InvalidSignatureError):
        adapter.validate_signature(payload_bytes, f"sha1={valid_sig_hex}")


def test_whatsapp_parse_inbound_text_message(repo, state_mgr, wa_config):
    adapter = WhatsAppAdapter(config=wa_config, repository=repo, state_manager=state_mgr)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "2291048821",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+60 12-345 6789",
                                "phone_number_id": "109876543210987",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Burger Stall Ops"},
                                    "wa_id": "60123456789",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "60123456789",
                                    "id": "wamid.HBgLNjAxMjM0NTY3ODkVAhIAEhgWM0VCMDEyMzQ1Njc4OTA=",
                                    "timestamp": "1729700000",
                                    "text": {
                                        "body": "Hi MouManTAI! We need 60 burgers delivered tomorrow before 2pm."
                                    },
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    envelopes = adapter.parse_webhook_payload(payload)
    assert len(envelopes) == 1
    env = envelopes[0]

    assert env.tenant_id == wa_config.tenant_id  # Enforces server tenant
    assert env.channel == "WHATSAPP"
    assert env.adapter_mode == "REAL"
    assert env.provider_message_id == "wamid.HBgLNjAxMjM0NTY3ODkVAhIAEhgWM0VCMDEyMzQ1Njc4OTA="
    assert env.sender_identity_id == "60123456789"
    assert env.sender_alias == "Burger Stall Ops"
    assert "60 burgers delivered tomorrow" in env.text
    assert env.attachments == []


def test_whatsapp_parse_media_attachment(repo, state_mgr, wa_config):
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        # 1. Graph API media URL lookup
        if "graph.facebook.com" in url_str and "media_rec_991" in url_str:
            return httpx.Response(200, json={
                "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/rec_991_data",
                "mime_type": "image/jpeg",
                "sha256": hashlib.sha256(VALID_JPEG_BYTES).hexdigest(),
                "file_size": len(VALID_JPEG_BYTES),
                "id": "media_rec_991",
            })
        # 2. Binary download
        if "lookaside.fbsbx.com" in url_str:
            return httpx.Response(200, content=VALID_JPEG_BYTES)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = WhatsAppAdapter(config=wa_config, repository=repo, state_manager=state_mgr, http_client=client)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "109876543210987"},
                            "contacts": [{"wa_id": "60198887777", "profile": {"name": "Sarah Cafe"}}],
                            "messages": [
                                {
                                    "from": "60198887777",
                                    "id": "wamid.HBgLMEDIA991823=",
                                    "timestamp": "1729700100",
                                    "type": "image",
                                    "image": {
                                        "caption": "Transfer slip for deposit payment",
                                        "mime_type": "image/jpeg",
                                        "sha256": "fake_sha",
                                        "id": "media_rec_991",
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    envelopes = adapter.parse_webhook_payload(payload)
    assert len(envelopes) == 1
    env = envelopes[0]

    assert env.provider_message_id == "wamid.HBgLMEDIA991823="
    assert env.text == "Transfer slip for deposit payment"
    assert len(env.attachments) == 1
    assert env.native_attachment_source_ids == ["media_rec_991"]

    att = env.attachments[0]
    assert att.media_type == "image/jpeg"
    assert att.size_bytes == len(VALID_JPEG_BYTES)

    # Check stored in repository
    retrieved = repo.get_attachment(wa_config.tenant_id, att.evidence_ref)
    assert retrieved is not None
    assert retrieved[1] == VALID_JPEG_BYTES


def test_whatsapp_non_message_status_event_handling(repo, state_mgr, wa_config):
    adapter = WhatsAppAdapter(config=wa_config, repository=repo, state_manager=state_mgr)

    # Webhook containing delivery/read status updates, no messages
    status_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "109876543210987"},
                            "statuses": [
                                {
                                    "id": "wamid.HBgL12345678=",
                                    "status": "delivered",
                                    "timestamp": "1729700200",
                                    "recipient_id": "60123456789",
                                },
                                {
                                    "id": "wamid.HBgL12345678=",
                                    "status": "read",
                                    "timestamp": "1729700205",
                                    "recipient_id": "60123456789",
                                },
                            ],
                        },
                    }
                ],
            }
        ],
    }

    # Must return empty list without creating messages or raising error
    envelopes = adapter.parse_webhook_payload(status_payload)
    assert envelopes == []


def test_whatsapp_handle_webhook_event_full_flow(repo, state_mgr, wa_config):
    adapter = WhatsAppAdapter(config=wa_config, repository=repo, state_manager=state_mgr)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "109876543210987"},
                            "contacts": [{"wa_id": "6011223344", "profile": {"name": "Lim Stall"}}],
                            "messages": [
                                {
                                    "from": "6011223344",
                                    "id": "wamid.FLOW_TEST_01",
                                    "timestamp": "1729700300",
                                    "type": "text",
                                    "text": {"body": "Need 50 burgers tomorrow before 3pm."},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(wa_config.app_secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()

    # First delivery
    results1 = adapter.handle_webhook_event(raw_bytes, sig, payload)
    assert len(results1) == 1
    assert results1[0].duplicate is False
    stored = repo.get(wa_config.tenant_id, results1[0].message.message_id)
    assert stored is not None
    assert stored.processing_status == "PROCESSED"  # Auto-triggered extraction

    # Re-delivery of same webhook payload (idempotent duplicate detection)
    results2 = adapter.handle_webhook_event(raw_bytes, sig, payload)
    assert len(results2) == 1
    assert results2[0].duplicate is True
