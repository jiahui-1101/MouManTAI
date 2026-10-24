"""Mocked provider regressions for the P1 Qwen-primary/Gemini-fallback adapter."""

import asyncio
import json
import os

import httpx
import pytest

from app.context.ai.endpoint import EndpointAdapter, EndpointConfig
from app.context.ai.protocol import MODEL_CONFIG, InferenceFailure, InferenceInput
from app.context.ai.provider_reliability import (
    GeminiConfig,
    GeminiEndpointAdapter,
    QwenGeminiReliabilityAdapter,
    redact_inference_request,
)


def test_unrecognized_provider_error_text_is_reduced_to_a_safe_category():
    failure = InferenceFailure("api_key=synthetic-secret provider response body")

    assert failure.code == "provider_internal_error"
    assert str(failure) == "provider_internal_error"


def inference_request(text="Please deliver 20 buns"):
    return InferenceInput(engine="qwen", messages=[{"id": "m1", "text": text}])


def qwen_answer(fields=None):
    return {
        "engine": "qwen",
        "model_id": MODEL_CONFIG["qwen"][0],
        "revision": MODEL_CONFIG["qwen"][1],
        "status": "ok",
        "finish_reason": "stop",
        "load_seconds": 0.0,
        "inference_seconds": 0.01,
        "fields": fields or [],
    }


def gemini_response(fields=None, *, finish_reason="STOP"):
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "finishReason": finish_reason,
                    "content": {"parts": [{"text": json.dumps({"fields": fields or []})}]},
                }
            ]
        },
    )


def reliability(primary_transport, fallback_transport=None, *, qwen_timeout=0.2, retries=0):
    primary = EndpointAdapter(
        EndpointConfig(
            "https://qwen.example.test/infer", "synthetic-qwen-key", "direct", qwen_timeout
        ),
        transport=primary_transport,
    )
    fallback = GeminiEndpointAdapter(
        GeminiConfig("synthetic-gemini-key", timeout_seconds=0.2, max_retries=retries),
        transport=fallback_transport,
    )
    return QwenGeminiReliabilityAdapter(primary, fallback), primary


def test_qwen_success_means_gemini_is_never_called():
    calls = {"qwen": 0, "gemini": 0}

    def qwen(req):
        calls["qwen"] += 1
        return httpx.Response(200, json=qwen_answer())

    def gemini(req):
        calls["gemini"] += 1
        return gemini_response()

    adapter, _ = reliability(httpx.MockTransport(qwen), httpx.MockTransport(gemini))
    result = asyncio.run(adapter.infer(inference_request()))

    assert result.provider == "qwen"
    assert result.fields == []
    assert calls == {"qwen": 1, "gemini": 0}


@pytest.mark.parametrize(
    "failure", ["timeout", "rate_limit", "server_error", "invalid_json", "schema_invalid"]
)
def test_technical_qwen_failures_fall_back_to_grounded_gemini(failure):
    calls = {"qwen": 0, "gemini": 0}
    text = "Please deliver 20 buns"
    start = text.index("20")

    async def qwen(req):
        calls["qwen"] += 1
        if failure == "timeout":
            await asyncio.sleep(1)
        if failure == "rate_limit":
            return httpx.Response(429)
        if failure == "server_error":
            return httpx.Response(503, text="private provider response")
        if failure == "invalid_json":
            return httpx.Response(200, text="not-json")
        if failure == "schema_invalid":
            return httpx.Response(200, json={"unexpected": "shape"})
        return httpx.Response(200, json=qwen_answer())

    def gemini(req):
        calls["gemini"] += 1
        return gemini_response(
            [
                {
                    "field": "quantity",
                    "message_id": "m1",
                    "quote": "20",
                    "start": start,
                    "end": start + 2,
                }
            ]
        )

    adapter, _ = reliability(
        httpx.MockTransport(qwen),
        httpx.MockTransport(gemini),
        qwen_timeout=0.02 if failure == "timeout" else 0.2,
    )
    result = asyncio.run(adapter.infer(inference_request(text)))

    assert result.provider == "gemini"
    assert result.fallback_trigger in {
        "timeout",
        "rate_limited",
        "service_unavailable",
        "invalid_json",
        "schema_validation",
    }
    assert result.fields[0].quote == "20"
    assert text[result.fields[0].start : result.fields[0].end] == "20"
    assert calls == {"qwen": 1, "gemini": 1}


def test_qwen_endpoint_cannot_claim_gemini_provider_identity():
    calls = {"qwen": 0, "gemini": 0}

    def qwen(req):
        calls["qwen"] += 1
        return httpx.Response(
            200,
            json=qwen_answer()
            | {
                "provider": "gemini",
                "model_id": MODEL_CONFIG["gemini"][0],
                "revision": MODEL_CONFIG["gemini"][1],
            },
        )

    def gemini(req):
        calls["gemini"] += 1
        return gemini_response()

    adapter, _ = reliability(httpx.MockTransport(qwen), httpx.MockTransport(gemini))
    result = asyncio.run(adapter.infer(inference_request()))

    assert result.provider == "gemini"
    assert result.fallback_trigger == "model_mismatch"
    assert calls == {"qwen": 1, "gemini": 1}


def test_grounded_empty_qwen_answer_does_not_trigger_fallback():
    calls = {"qwen": 0, "gemini": 0}

    def qwen(req):
        calls["qwen"] += 1
        return httpx.Response(200, json=qwen_answer())

    def gemini(req):
        calls["gemini"] += 1
        return gemini_response()

    adapter, _ = reliability(httpx.MockTransport(qwen), httpx.MockTransport(gemini))
    result = asyncio.run(adapter.infer(inference_request("Hi, can I ask about delivery?")))

    assert result.provider == "qwen"
    assert result.fields == []
    assert calls == {"qwen": 1, "gemini": 0}


def test_grounded_ambiguous_qwen_answer_is_preserved_without_fallback():
    text = "Need 20 or 40 buns"
    start = text.index("20")
    calls = {"qwen": 0, "gemini": 0}

    def qwen(req):
        calls["qwen"] += 1
        return httpx.Response(
            200,
            json=qwen_answer(
                [
                    {
                        "field": "quantity",
                        "message_id": "m1",
                        "quote": "20 or 40",
                        "start": start,
                        "end": start + len("20 or 40"),
                    }
                ]
            ),
        )

    def gemini(req):
        calls["gemini"] += 1
        return gemini_response()

    adapter, _ = reliability(httpx.MockTransport(qwen), httpx.MockTransport(gemini))
    result = asyncio.run(adapter.infer(inference_request(text)))

    assert calls == {"qwen": 1, "gemini": 0}
    assert result.fields[0].quote == "20 or 40"
    assert text[result.fields[0].start : result.fields[0].end] == "20 or 40"


@pytest.mark.parametrize(
    ("fields", "failure_code"),
    [
        (
            [{"field": "quantity", "message_id": "m1", "quote": "absent", "start": 0, "end": 6}],
            "evidence_mismatch",
        ),
        (
            [{"field": "quantity", "message_id": "foreign", "quote": "20", "start": 0, "end": 2}],
            "missing_source_or_invalid_span",
        ),
    ],
)
def test_ungrounded_qwen_output_fails_closed_without_fallback(fields, failure_code):
    calls = {"qwen": 0, "gemini": 0}

    def qwen(req):
        calls["qwen"] += 1
        return httpx.Response(200, json=qwen_answer(fields))

    def gemini(req):
        calls["gemini"] += 1
        return gemini_response()

    adapter, _ = reliability(httpx.MockTransport(qwen), httpx.MockTransport(gemini))
    with pytest.raises(InferenceFailure) as error:
        asyncio.run(adapter.infer(inference_request()))

    assert error.value.code == failure_code
    assert error.value.audit["review_required"] is True
    assert calls == {"qwen": 1, "gemini": 0}


def test_gemini_schema_invalid_result_is_sanitized_and_requires_review():
    def qwen(req):
        return httpx.Response(429)

    def gemini(req):
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [{"text": '{"fields":[{"field":"commitment_confirmed"}]}'}]
                        },
                    }
                ]
            },
        )

    adapter, _ = reliability(httpx.MockTransport(qwen), httpx.MockTransport(gemini))
    with pytest.raises(InferenceFailure) as error:
        asyncio.run(adapter.infer(inference_request()))

    assert error.value.code == "schema_validation"
    assert error.value.audit["validation_outcome"] == "BOTH_FAILED"
    assert error.value.audit["review_required"] is True
    assert "synthetic-gemini-key" not in str(error.value)


def test_fallback_endpoint_must_return_gemini_provider_identity():
    class FailedQwen:
        async def infer(self, request):
            raise InferenceFailure("rate_limited")

    class QwenImpersonator:
        async def infer(self, request):
            return qwen_answer()

    adapter = QwenGeminiReliabilityAdapter(FailedQwen(), QwenImpersonator())
    with pytest.raises(InferenceFailure) as error:
        asyncio.run(adapter.infer(inference_request()))

    assert error.value.audit["fallback_error"] == "model_mismatch"
    assert error.value.audit["review_required"] is True


def test_same_minimized_redacted_input_reaches_both_providers_and_restores_offsets():
    source = "Hi Alice, PO-9217 deliver 20 buns. Call +65 9123 4567 or alice@example.test."
    request = inference_request(source)
    masked = redact_inference_request(request)
    observed = {}
    start = source.index("20")

    def qwen(req):
        observed["qwen"] = json.loads(req.content)["messages"][0]["text"]
        return httpx.Response(503)

    def gemini(req):
        payload = json.loads(req.content)
        observed["gemini"] = json.loads(payload["contents"][0]["parts"][0]["text"])[0]["text"]
        return gemini_response(
            [
                {
                    "field": "quantity",
                    "message_id": "m1",
                    "quote": "20",
                    "start": start,
                    "end": start + 2,
                }
            ]
        )

    adapter, _ = reliability(httpx.MockTransport(qwen), httpx.MockTransport(gemini))
    result = asyncio.run(adapter.infer(request))

    assert observed["qwen"] == observed["gemini"] == masked.request.messages[0].text
    for secret in ("Alice", "PO-9217", "+65 9123 4567", "alice@example.test"):
        assert secret not in observed["qwen"]
        assert secret not in observed["gemini"]
    assert result.fields[0].quote == "20"
    assert source[result.fields[0].start : result.fields[0].end] == "20"
    assert result.redacted_span_count >= 3


def test_gemini_retries_are_bounded_and_exclude_raw_error_bodies():
    calls = 0

    def qwen(req):
        return httpx.Response(429)

    def gemini(req):
        nonlocal calls
        calls += 1
        if calls <= 3:
            return httpx.Response(429, text="private error and key data")
        return gemini_response()

    adapter, _ = reliability(httpx.MockTransport(qwen), httpx.MockTransport(gemini), retries=1)
    with pytest.raises(InferenceFailure) as error:
        asyncio.run(adapter.infer(inference_request()))

    assert calls == 2
    assert error.value.audit["fallback_attempts"] == 2
    assert "private error" not in str(error.value)
    assert "synthetic-gemini-key" not in str(error.value)


def test_gemini_timeout_is_bounded_and_not_retried():
    calls = 0

    async def gemini(req):
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)
        return gemini_response()

    adapter = GeminiEndpointAdapter(
        GeminiConfig("synthetic-gemini-key", timeout_seconds=0.1, max_retries=2),
        transport=httpx.MockTransport(gemini),
    )
    with pytest.raises(InferenceFailure, match="timeout"):
        asyncio.run(adapter.infer(inference_request()))

    assert calls == 1


def test_credentials_absent_keeps_qwen_primary_and_returns_review_when_it_fails():
    def qwen(req):
        return httpx.Response(429)

    primary = EndpointAdapter(
        EndpointConfig("https://qwen.example.test/infer", "synthetic-qwen-key", "direct"),
        transport=httpx.MockTransport(qwen),
    )
    adapter = QwenGeminiReliabilityAdapter(primary, fallback=None)

    with pytest.raises(InferenceFailure) as error:
        asyncio.run(adapter.infer(inference_request()))

    assert error.value.audit["fallback_error"] == "credentials_missing"
    assert error.value.audit["review_required"] is True


@pytest.mark.skipif(
    os.environ.get("P1_RUN_REAL_GEMINI_SMOKE") != "1" or not os.environ.get("P1_GEMINI_API_KEY"),
    reason="Set P1_RUN_REAL_GEMINI_SMOKE=1 and P1_GEMINI_API_KEY to opt in to a live Gemini call",
)
def test_opt_in_live_gemini_smoke_uses_synthetic_input():
    adapter = GeminiEndpointAdapter(GeminiConfig.from_env_or_none())
    result = asyncio.run(adapter.infer(inference_request("Hello")))
    assert result.provider == "gemini"
    assert result.fields == []


def test_identifier_mask_preserves_ordinary_words_and_masks_compact_ids():
    from app.context.ai.provider_reliability import redact_source_text

    original = "Is it possible for the supplier to review PO450 and PO-451?"
    masked, spans = redact_source_text(original)
    assert "possible" in masked
    assert "supplier" in masked
    assert "PO450" not in masked
    assert "PO-451" not in masked
    assert len(masked) == len(original)
    assert len(spans) == 2
