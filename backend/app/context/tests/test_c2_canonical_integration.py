"""C2 provider fixtures → registered HTTP adapter → canonical PostgreSQL."""

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.context.channels.config import ChannelsConfig, TelegramChannelConfig, WhatsAppChannelConfig
from app.context.channels.manager import ChannelManager
from app.context.channels.router import get_manager, router
from app.context.channels.state import ChannelStateManager
from app.context.postgres_repository import PostgresMessageRepository


def telegram_update(native_id, parent=None, chat=77):
    message = {
        "message_id": native_id,
        "from": {"id": 77},
        "chat": {"id": chat},
        "date": 1792800000,
        "text": "Please clarify this request",
    }
    if parent is not None:
        message["reply_to_message"] = {"message_id": parent, "chat": {"id": chat}}
    return {"update_id": native_id, "tenant_id": "untrusted-tenant", "message": message}


@pytest.mark.parametrize("parent_first", [True, False])
def test_telegram_http_persists_native_parents_and_reconciles_replays(
    pg_engine, tmp_path, parent_first
):
    repo = PostgresMessageRepository(pg_engine)
    config = ChannelsConfig(
        telegram=TelegramChannelConfig(
            bot_token="12345:fixture-token", tenant_id="tenant-c2", webhook_secret="fixture-secret"
        )
    )
    manager = ChannelManager(config, repo, ChannelStateManager(tmp_path / "tg.json"))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_manager] = lambda: manager
    headers = {"X-Telegram-Bot-Api-Secret-Token": "fixture-secret"}
    updates = [telegram_update(49), telegram_update(52, 49)]
    if not parent_first:
        updates.reverse()
    with TestClient(app) as client:
        assert client.post("/v1/channels/telegram/webhook", json=updates[0]).status_code == 403
        results = [
            client.post("/v1/channels/telegram/webhook", json=u, headers=headers) for u in updates
        ]
        assert all(r.status_code == 200 for r in results)
        for update in updates:
            replay = client.post("/v1/channels/telegram/webhook", json=update, headers=headers)
            assert replay.status_code == 200 and replay.json()["duplicate"]
        # Telegram IDs are chat-local. This same native parent cannot satisfy
        # a quote in another chat or alter the first child's exact source link.
        missing = client.post(
            "/v1/channels/telegram/webhook", json=telegram_update(53, 49, chat=88), headers=headers
        )
        assert missing.status_code == 200
    rows = repo.list("tenant-c2").items
    child = next(r for r in rows if r.raw.provider_native_message_id == "52")
    assert child.raw.provider_account_id == "12345"
    assert child.raw.source_authenticity == "VERIFIED"
    assert child.raw.reply_to_provider_message_id == "49"
    assert repo.resolve_exact_parent("tenant-c2", child.message_id).state == "REFERENCE_MATCH"
    assert (
        repo.resolve_exact_parent("tenant-c2", missing.json()["message_id"]).state == "UNRESOLVED"
    )
    assert repo.list("untrusted-tenant").total == 0
    assert len(rows) == 3


def test_whatsapp_signed_http_replay_preserves_canonical_source(pg_engine, tmp_path):
    repo = PostgresMessageRepository(pg_engine)
    config = ChannelsConfig(
        whatsapp=WhatsAppChannelConfig(
            phone_number_id="phone-a",
            app_secret="fixture-secret",
            access_token="fixture-token",
            verify_token="fixture-verify",
            tenant_id="tenant-c2",
        )
    )
    manager = ChannelManager(config, repo, ChannelStateManager(tmp_path / "wa.json"))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_manager] = lambda: manager
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "phone-a"},
                            "messages": [
                                {
                                    "id": "wamid.child",
                                    "from": "6012345",
                                    "timestamp": "1792800000",
                                    "type": "text",
                                    "text": {"body": "Please clarify"},
                                    "context": {"id": "wamid.parent"},
                                }
                            ],
                        },
                    }
                ]
            }
        ],
    }
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"fixture-secret", raw, hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        assert client.post("/v1/channels/whatsapp/webhook", content=raw).status_code == 401
        for _ in range(2):
            response = client.post(
                "/v1/channels/whatsapp/webhook",
                content=raw,
                headers={"X-Hub-Signature-256": signature},
            )
            assert response.status_code == 200
    rows = repo.list("tenant-c2").items
    assert len(rows) == 1
    assert rows[0].raw.provider_account_id == "phone-a"
    assert rows[0].raw.provider_native_message_id == "wamid.child"
    assert rows[0].raw.reply_to_provider_message_id == "wamid.parent"
    assert repo.resolve_exact_parent("tenant-c2", rows[0].message_id).state == "UNRESOLVED"
