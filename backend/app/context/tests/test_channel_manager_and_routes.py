"""Automated tests for ChannelManager lifecycle, FastAPI channel routes, and Inbox integration."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.context.channels.config import ChannelsConfig, GmailChannelConfig, TelegramChannelConfig, WhatsAppChannelConfig
from app.context.channels.manager import ChannelManager
from app.context.channels.router import get_manager
from app.context.channels.state import ChannelStateManager
from app.context.dependencies import development_context, local_repository
from app.context.dev_app import app
from app.context.ingestion_schemas import DevelopmentContext
from app.context.tests.in_memory_repository import InMemoryMessageRepository


@pytest.fixture
def repo():
    return InMemoryMessageRepository()


@pytest.fixture
def state_mgr(tmp_path):
    return ChannelStateManager(storage_path=tmp_path / "channels_state.json")


@pytest.fixture
def channels_config():
    return ChannelsConfig(
        telegram=TelegramChannelConfig(
            bot_token="test_bot_123",
            mode="webhook",
            webhook_secret="secret_tg_token_xyz",
            tenant_id="tenant_channel_test",
        ),
        gmail=GmailChannelConfig(
            client_id="client_id_gmail",
            client_secret="client_secret_gmail",
            refresh_token="refresh_token_gmail",
            tenant_id="tenant_channel_test",
        ),
        whatsapp=WhatsAppChannelConfig(
            phone_number_id="wa_phone_id_999",
            access_token="wa_access_token_999",
            app_secret="wa_app_secret_999",
            verify_token="wa_verify_token_999",
            tenant_id="tenant_channel_test",
        ),
    )


@pytest.fixture
def channel_mgr(channels_config, repo, state_mgr):
    return ChannelManager(config=channels_config, repository=repo, state_manager=state_mgr)


@pytest.fixture
def client(channel_mgr, repo):
    app.dependency_overrides[get_manager] = lambda: channel_mgr
    app.dependency_overrides[local_repository] = lambda: repo
    app.dependency_overrides[development_context] = lambda: DevelopmentContext(tenant_id="tenant_channel_test")
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_channel_status_endpoint(client):
    resp = client.get("/v1/channels/status")
    assert resp.status_code == 200
    data = resp.json()

    assert "telegram" in data
    assert "gmail" in data
    assert "whatsapp" in data

    assert data["telegram"]["configured"] is True
    assert data["telegram"]["mode"] == "webhook"
    assert data["gmail"]["configured"] is True
    assert data["whatsapp"]["configured"] is True


def test_telegram_webhook_route(client, channels_config):
    update = {
        "update_id": 9901,
        "message": {
            "message_id": 771,
            "from": {"id": 12345, "first_name": "Uncle", "username": "uncle_bot"},
            "chat": {"id": 12345},
            "date": 1729700000,
            "text": "Telegram order: 40 burgers for tomorrow lunch",
        },
    }

    # 1. Missing secret token when configured -> 403 Forbidden
    bad_resp = client.post("/v1/channels/telegram/webhook", json=update)
    assert bad_resp.status_code == 403

    # 2. Valid secret token -> 200 OK
    headers = {"X-Telegram-Bot-Api-Secret-Token": channels_config.telegram.webhook_secret}
    ok_resp = client.post("/v1/channels/telegram/webhook", json=update, headers=headers)
    assert ok_resp.status_code == 200
    res_data = ok_resp.json()
    assert res_data["ok"] is True
    assert res_data["processed"] is True
    assert res_data["duplicate"] is False
    msg_id = res_data["message_id"]

    # 3. Message appears in Inbox (/v1/messages)
    inbox_resp = client.get("/v1/messages?channel=TELEGRAM")
    assert inbox_resp.status_code == 200
    items = inbox_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["message_id"] == msg_id
    assert items[0]["processing_status"] == "PROCESSED"
    assert "40 burgers" in items[0]["raw"]["text"]


def test_whatsapp_webhook_routes_and_inbox(client, channels_config):
    # 1. Challenge verification (GET)
    verify_resp = client.get(
        "/v1/channels/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=wa_verify_token_999&hub.challenge=challenge_token_889"
    )
    assert verify_resp.status_code == 200
    assert verify_resp.text == "challenge_token_889"

    # 2. Challenge rejection on bad verify token
    bad_verify = client.get(
        "/v1/channels/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=challenge_token_889"
    )
    assert bad_verify.status_code == 403

    # 3. Notification (POST) with valid HMAC signature
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "wa_phone_id_999"},
                            "contacts": [{"wa_id": "60178889999", "profile": {"name": "Burger Bros"}}],
                            "messages": [
                                {
                                    "from": "60178889999",
                                    "id": "wamid.ROUTE_TEST_01",
                                    "timestamp": "1729700050",
                                    "type": "text",
                                    "text": {"body": "50 burgers tomorrow before 3pm please."},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    raw_body = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(channels_config.whatsapp.app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # Reject without signature
    no_sig = client.post("/v1/channels/whatsapp/webhook", content=raw_body)
    assert no_sig.status_code == 401

    # Accept with valid signature
    post_resp = client.post("/v1/channels/whatsapp/webhook", content=raw_body, headers={"X-Hub-Signature-256": sig})
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    assert post_data["status"] == "success"
    assert post_data["received_count"] == 1

    # 4. Appears in Inbox (/v1/messages?channel=WHATSAPP)
    wa_inbox = client.get("/v1/messages?channel=WHATSAPP")
    assert wa_inbox.status_code == 200
    items = wa_inbox.json()["items"]
    assert len(items) == 1
    assert items[0]["raw"]["sender_alias"] == "Burger Bros"
    assert "50 burgers" in items[0]["raw"]["text"]


def test_gmail_oauth_routes(client, channel_mgr):
    # 1. Authorize URL
    auth_resp = client.get("/v1/channels/gmail/oauth/authorize?state=my_state_nonce")
    assert auth_resp.status_code == 200
    url = auth_resp.json()["authorization_url"]
    assert "accounts.google.com/o/oauth2/v2/auth" in url
    assert "state=my_state_nonce" in url

    # 2. Callback with mock code exchange
    def mock_exchange(code: str) -> dict:
        return {"access_token": "mocked_access", "refresh_token": "mocked_refresh"}

    channel_mgr.gmail.exchange_code = mock_exchange  # type: ignore[assignment]

    callback_resp = client.get("/v1/channels/gmail/oauth/callback?code=mock_code_12345")
    assert callback_resp.status_code == 200
    assert callback_resp.json()["status"] == "success"
    assert callback_resp.json()["has_refresh_token"] is True


def test_unconfigured_channel_manager_graceful_lifecycle(repo, state_mgr):
    empty_config = ChannelsConfig()
    mgr = ChannelManager(config=empty_config, repository=repo, state_manager=state_mgr)

    # Starting unconfigured workers does not crash
    mgr.start_configured_workers()
    status = mgr.get_status()
    assert status["telegram"]["configured"] is False
    assert status["gmail"]["configured"] is False
    assert status["whatsapp"]["configured"] is False

    # Polling unconfigured workers skips gracefully
    poll_res = mgr.poll_all_now()
    assert poll_res["telegram"]["status"] == "skipped"
    assert poll_res["gmail"]["status"] == "skipped"

    # Stopping workers is safe
    mgr.stop_all_workers()
