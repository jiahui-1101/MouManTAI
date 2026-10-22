"""Automated unit tests for L0 -> L1 -> L2 routing, caching, and cost-reduction mechanisms."""
import asyncio

import pytest

from app.context.ai.protocol import InferenceFailure, InferenceOutput, MODEL_CONFIG
from app.context.ai.service import ModelProposalService
from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS
from app.context.tests.test_deterministic_extraction import stored


class SpyEndpoint:
    def __init__(self, responses=None, fail=False):
        self.calls = []
        self.fail = fail
        self.responses = responses or {}

    async def infer(self, request):
        self.calls.append(request)
        if self.fail:
            raise InferenceFailure("worker_connection_refused")
        if request.engine in self.responses:
            return self.responses[request.engine]
        return InferenceOutput(
            engine=request.engine,
            model_id=MODEL_CONFIG[request.engine][0],
            revision=MODEL_CONFIG[request.engine][1],
            status="ok",
            finish_reason="stop",
            load_seconds=0.0,
            inference_seconds=0.05,
            fields=[],
        )


def test_l0_sufficient_message_triggers_zero_worker_requests():
    """When deterministic L0 resolves SKU, quantity, and delivery, no AI inference is performed."""
    spy = SpyEndpoint()
    service = ModelProposalService(endpoint=spy, enabled=True, stages=("gliner", "qwen"))
    msg = stored("20 pcs burgers tomorrow at 3pm")
    result = asyncio.run(service.extract_stored(msg, catalog=PROVISIONAL_PRODUCTS))

    assert len(spy.calls) == 0
    assert result.worker_request_count == 0
    assert result.outcomes == {"gliner": "not_needed", "qwen": "not_needed"}
    assert "safely resolved" in result.routing_reasons["gliner"]


def test_unresolved_sku_or_quantity_triggers_l1_gliner():
    """When SKU or quantity cannot be resolved by L0, GLiNER is invoked."""
    text = "nak tempah 25 roti burger esok petang pukul 3"
    start_prod = text.index("roti burger")
    end_prod = start_prod + len("roti burger")
    gliner_res = InferenceOutput(
        engine="gliner",
        model_id=MODEL_CONFIG["gliner"][0],
        revision=MODEL_CONFIG["gliner"][1],
        status="ok",
        finish_reason="stop",
        load_seconds=0.0,
        inference_seconds=0.08,
        fields=[
            {"field": "product", "message_id": "m1", "quote": "roti burger", "start": start_prod, "end": end_prod},
            {"field": "quantity", "message_id": "m1", "quote": "25", "start": text.index("25"), "end": text.index("25") + 2},
        ],
    )
    spy = SpyEndpoint(responses={"gliner": gliner_res})
    service = ModelProposalService(endpoint=spy, enabled=True, stages=("gliner", "qwen"))
    msg = stored(text)
    result = asyncio.run(service.extract_stored(msg, catalog=PROVISIONAL_PRODUCTS))

    assert len(spy.calls) == 1
    assert spy.calls[0].engine == "gliner"
    assert result.worker_request_count == 1
    assert result.outcomes["gliner"] == "proposals_only"
    # When GLiNER resolves the terms, Qwen is bypassed with l1_sufficient
    assert result.outcomes["qwen"] == "l1_sufficient"
    assert len(spy.calls) == 1


def test_reprocessing_unchanged_message_reuses_cache_without_network_calls():
    """Identical message SHA256 reuses in-memory cache without duplicate worker calls."""
    text = "halo boleh hantar burger esok"
    gliner_res = InferenceOutput(
        engine="gliner",
        model_id=MODEL_CONFIG["gliner"][0],
        revision=MODEL_CONFIG["gliner"][1],
        status="ok",
        finish_reason="stop",
        load_seconds=0.0,
        inference_seconds=0.05,
        fields=[
            {"field": "product", "message_id": "m1", "quote": "burger", "start": text.index("burger"), "end": text.index("burger") + 6},
        ],
    )
    spy = SpyEndpoint(responses={"gliner": gliner_res})
    service = ModelProposalService(endpoint=spy, enabled=True, stages=("gliner",))
    msg = stored(text)

    # First call: cache miss, triggers inference
    res1 = asyncio.run(service.extract_stored(msg, catalog=PROVISIONAL_PRODUCTS))
    assert len(spy.calls) == 1
    assert res1.worker_request_count == 1
    assert res1.telemetry["gliner"]["cached"] is False

    # Second call: cache hit, zero new network requests
    res2 = asyncio.run(service.extract_stored(msg, catalog=PROVISIONAL_PRODUCTS))
    assert len(spy.calls) == 1
    assert res2.worker_request_count == 0
    assert res2.telemetry["gliner"]["cached"] is True
    assert "idempotency cache" in res2.routing_reasons["gliner"]


def test_non_order_inquiry_does_not_trigger_ai_extraction():
    """Inquiries, delivery rate questions, and feedback bypass candidate generation."""
    spy = SpyEndpoint()
    service = ModelProposalService(endpoint=spy, enabled=True, stages=("gliner", "qwen"))
    msg = stored("Hello, do you do delivery to Bukit Jalil? What is the price?")
    result = asyncio.run(service.extract_stored(msg, catalog=PROVISIONAL_PRODUCTS))

    assert len(spy.calls) == 0
    assert result.worker_request_count == 0
    assert result.outcomes["gliner"] == "not_needed"
    assert "Non-order inquiry" in result.routing_reasons["gliner"]


def test_ambiguity_remaining_after_l1_selectively_invokes_l2_qwen():
    """When meaningful ambiguity remains after L1 (e.g. unknown product), L2 is invoked."""
    text = "Please prepare 20 mystery_items for tomorrow"
    gliner_res = InferenceOutput(
        engine="gliner",
        model_id=MODEL_CONFIG["gliner"][0],
        revision=MODEL_CONFIG["gliner"][1],
        status="ok",
        finish_reason="stop",
        load_seconds=0.0,
        inference_seconds=0.05,
        fields=[
            {"field": "product", "message_id": "m1", "quote": "mystery_items", "start": text.index("mystery_items"), "end": text.index("mystery_items") + len("mystery_items")},
        ],
    )
    qwen_res = InferenceOutput(
        engine="qwen",
        model_id=MODEL_CONFIG["qwen"][0],
        revision=MODEL_CONFIG["qwen"][1],
        status="ok",
        finish_reason="stop",
        load_seconds=0.0,
        inference_seconds=0.15,
        fields=[],
    )
    spy = SpyEndpoint(responses={"gliner": gliner_res, "qwen": qwen_res})
    service = ModelProposalService(endpoint=spy, enabled=True, stages=("gliner", "qwen"))
    msg = stored(text)
    result = asyncio.run(service.extract_stored(msg, catalog=PROVISIONAL_PRODUCTS))

    # Both GLiNER and Qwen are called because mystery_items is not in catalog (meaningful ambiguity)
    assert len(spy.calls) == 2
    assert spy.calls[0].engine == "gliner"
    assert spy.calls[1].engine == "qwen"
    assert result.outcomes["qwen"] == "proposals_only"


def test_worker_failure_reports_cleanly_without_runaway_retries():
    """Worker failures cleanly populate failure outcome without endless retry loops."""
    spy = SpyEndpoint(fail=True)
    service = ModelProposalService(endpoint=spy, enabled=True, stages=("gliner",))
    msg = stored("nak order burger 5 biji esok")
    result = asyncio.run(service.extract_stored(msg, catalog=PROVISIONAL_PRODUCTS))

    assert len(spy.calls) == 1
    assert result.outcomes["gliner"] == "worker_connection_refused"
    assert not result.candidates
