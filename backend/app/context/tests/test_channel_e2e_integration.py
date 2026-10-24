"""End-to-end integration test for Real Inbound Channels through the Shared P1 Pipeline:
Inbound Provider -> Channel Adapter -> Normalized Message -> Persistence ->
L0 Extraction Pipeline -> OrderContext -> Human Review -> P5 Core Publisher.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.context.channels.config import TelegramChannelConfig
from app.context.channels.state import ChannelStateManager
from app.context.channels.telegram import TelegramAdapter
from app.context.context_service import ContextService
from app.context.core_publisher import CoreContextPublisher
from app.context.order_context_schemas import (
    ContextReviewRequest,
    ContextUpdateRequest,
    OrderContextRecord,
    RequestedItem,
)
from app.context.tests.in_memory_repository import InMemoryMessageRepository


@pytest.fixture
def repo():
    return InMemoryMessageRepository()


@pytest.fixture
def state_mgr(tmp_path):
    return ChannelStateManager(storage_path=tmp_path / "e2e_state.json")


def test_channel_to_inbox_to_core_full_flow(repo, state_mgr):
    tenant_id = "tenant_telegram_e2e"
    config = TelegramChannelConfig(
        bot_token="test_token_999",
        bot_account_id="e2e-telegram-account",
        tenant_id=tenant_id,
    )
    adapter = TelegramAdapter(config=config, repository=repo, state_manager=state_mgr)

    # 1. Inbound Provider: Telegram sends a multi-item customer order
    update = {
        "update_id": 8801,
        "message": {
            "message_id": 501,
            "from": {"id": 998877, "username": "customer_burger_king", "first_name": "BK Ops"},
            "chat": {"id": 998877},
            "date": 1729700000,
            "text": "Hello! We need 100 burgers tomorrow before 3pm please. Normal delivery.",
        },
    }

    # 2. Channel Adapter normalizes and ingests
    ingest_res = adapter.process_update(update, source_verified=True)
    assert ingest_res is not None
    assert ingest_res.duplicate is False
    msg_id = ingest_res.message.message_id

    # 3. Message persisted and auto-processed
    stored = repo.get(tenant_id, msg_id)
    assert stored is not None
    assert stored.raw.channel == "TELEGRAM"
    assert stored.processing_status == "PROCESSED"

    # 4. Idempotency: duplicate update delivery does not create duplicate message
    dup_res = adapter.process_update(update, source_verified=True)
    assert dup_res is not None
    assert dup_res.duplicate is True
    assert dup_res.message.message_id == msg_id

    # 5. Extraction verification: extraction attempt contains field-level evidence spans
    attempt = repo.get_latest_extraction(tenant_id, msg_id)
    assert attempt is not None
    assert attempt.status == "PROCESSED"
    field_names = {f.field_name for f in attempt.fields}
    assert "product" in field_names or "quantity" in field_names

    # 6. OrderContext creation from message
    ctx_service = ContextService(repository=repo)
    context = ctx_service.create_or_update_from_message(tenant_id, msg_id)
    assert context.tenant_id == tenant_id
    assert context.context_version == 1

    # 7. Human Review: staff reviews and accepts extraction
    review_req = ContextReviewRequest(
        expected_context_version=context.context_version,
        action="ACCEPT_EXTRACTION",
        note="Verified with Uncle Lim over Telegram chat",
        field_edits={},
    )
    updated_ctx = repo.apply_context_review(
        tenant_id=tenant_id,
        context_id=context.context_id,
        request=review_req,
        actor_id="staff_user_1",
        actor_role="STAFF",
    )
    assert updated_ctx.context_version == 2
    assert updated_ctx.last_reviewed_by == "staff_user_1"

    # 8. P5 Core Publisher handoff
    publisher = CoreContextPublisher()
    eligible, reasons = publisher.check_eligibility(updated_ctx)
    assert eligible is True
    assert reasons == []

    # Map to canonical Core BusinessContext
    biz_ctx = publisher.to_business_context(updated_ctx)
    assert biz_ctx.tenant_id == tenant_id
    assert biz_ctx.context_id == context.context_id
    assert biz_ctx.customer_id == "cust_bk_01"
    assert len(biz_ctx.requested_items) == 1
    assert biz_ctx.requested_items[0].sku == "BURGER"
    assert biz_ctx.requested_items[0].quantity == 100


def test_channel_tenant_isolation_enforced(repo, state_mgr):
    tenant_a = "tenant_telegram_isolation_a"
    tenant_b = "tenant_telegram_isolation_b"

    config_a = TelegramChannelConfig(bot_token="token_a", bot_account_id="account-a", tenant_id=tenant_a)
    adapter_a = TelegramAdapter(config=config_a, repository=repo, state_manager=state_mgr)

    # Inbound message for tenant A
    update = {
        "update_id": 9001,
        "message": {"message_id": 1, "from": {"id": 1}, "chat": {"id": 1}, "date": 1729700000, "text": "Tenant A Order"},
    }
    res = adapter_a.process_update(update, source_verified=True)
    assert res is not None
    msg_id = res.message.message_id

    # Tenant A sees it
    assert repo.get(tenant_a, msg_id) is not None
    assert repo.list(tenant_a).total == 1

    # Tenant B CANNOT see it (tenant isolation)
    assert repo.get(tenant_b, msg_id) is None
    assert repo.list(tenant_b).total == 0
