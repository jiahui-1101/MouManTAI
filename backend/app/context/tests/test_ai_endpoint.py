import asyncio
import json

import httpx
import pytest

from app.context.ai.endpoint import EndpointAdapter, EndpointConfig
from app.context.ai.protocol import InferenceFailure, InferenceInput, InferenceOutput, MODEL_CONFIG, validate_evidence


def request():
    return InferenceInput(engine="qwen", messages=[{"id": "m1", "text": "🍔 bread bread"}])


def answer(**updates):
    return dict(engine="qwen", model_id=MODEL_CONFIG["qwen"][0], revision=MODEL_CONFIG["qwen"][1],
                status="ok", finish_reason="stop", load_seconds=0.1, inference_seconds=0.2,
                fields=[dict(field="product", message_id="m1", quote="bread", start=8, end=13)]) | updates


def test_repeated_quote_is_disambiguated_by_real_unicode_offsets():
    assert validate_evidence(InferenceOutput.model_validate(answer()), request()).fields[0].start == 8


@pytest.mark.parametrize("update", [
    {"revision": "unapproved"}, {"status": "invalid_output"}, {"finish_reason": "length"},
    {"fields": [{"field": "product", "message_id": "foreign", "quote": "bread", "start": 8, "end": 13}]},
    {"fields": [{"field": "product", "message_id": "m1", "quote": "invented", "start": 8, "end": 13}]},
])
def test_evidence_and_checkpoint_cannot_be_weakened(update):
    with pytest.raises(InferenceFailure):
        validate_evidence(InferenceOutput.model_validate(answer(**update)), request())


def test_runpod_envelope_contains_only_minimal_context_and_execution_policy():
    def handler(req):
        payload = json.loads(req.content)
        assert payload["policy"] == {"executionTimeout": 90000, "ttl": 120000}
        assert set(payload["input"]) == {"engine", "messages"}
        assert "tenant_id" not in req.content.decode()
        assert req.headers["authorization"] == "Bearer secret-not-logged"
        return httpx.Response(200, json={"status": "COMPLETED", "output": answer()})
    config = EndpointConfig("https://test.invalid/runsync", "secret-not-logged")
    adapter = EndpointAdapter(config, transport=httpx.MockTransport(handler))
    assert asyncio.run(adapter.infer(request())).engine == "qwen"
    assert "secret-not-logged" not in repr(config)


@pytest.mark.parametrize("response", [httpx.Response(302, headers={"location": "https://elsewhere.invalid"}),
    httpx.Response(503, text="private details"), httpx.Response(200, text="not JSON"),
    httpx.Response(200, json={"status": "IN_PROGRESS"}), httpx.Response(200, content=b"a" * 140000)])
def test_failed_or_redirected_request_is_not_retried_or_success(response):
    calls = []
    def handler(req):
        calls.append(req)
        return response
    adapter = EndpointAdapter(EndpointConfig("https://test.invalid/runsync", "key"), transport=httpx.MockTransport(handler))
    with pytest.raises(InferenceFailure) as error:
        asyncio.run(adapter.infer(request()))
    assert len(calls) == 1 and not adapter.busy
    assert "private details" not in str(error.value)


def test_total_timeout_and_concurrency_limit():
    async def handler(req):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"status": "COMPLETED", "output": answer()})
    adapter = EndpointAdapter(EndpointConfig("https://test.invalid/runsync", "key", timeout_seconds=0.02),
                              transport=httpx.MockTransport(handler))
    async def exercise():
        first = asyncio.create_task(adapter.infer(request()))
        await asyncio.sleep(0)
        with pytest.raises(InferenceFailure, match="busy"):
            await adapter.infer(request())
        with pytest.raises(InferenceFailure, match="timeout"):
            await first
    asyncio.run(exercise())


def test_protocol_rejects_excess_context_and_authority_fields():
    with pytest.raises(ValueError):
        InferenceInput(engine="qwen", messages=[{"id": "m1", "text": "x" * 4001}])
    invalid = answer(fields=[dict(field="identity_verified", message_id="m1", quote="bread", start=8, end=13)])
    with pytest.raises(ValueError):
        InferenceOutput.model_validate(invalid)


def test_queued_job_is_polled_not_resubmitted():
    calls = []
    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "POST":
            return httpx.Response(200, json={"id": "job_1", "status": "IN_QUEUE"})
        return httpx.Response(200, json={"id": "job_1", "status": "COMPLETED", "executionTime": 100,
                                         "output": answer()})
    adapter = EndpointAdapter(EndpointConfig("https://test.invalid/run", "key"), transport=httpx.MockTransport(handler))
    assert asyncio.run(adapter.infer(request())).status == "ok"
    assert calls == [("POST", "/run"), ("GET", "/status/job_1")]
    assert adapter.last_provider_metrics["executionTime"] == 100


def test_timeout_attempts_bounded_cancellation_of_known_job_only():
    calls = []
    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json={"id": "job_1", "status": "CANCELLED" if "/cancel/" in req.url.path else "IN_PROGRESS"})
    adapter = EndpointAdapter(EndpointConfig("https://test.invalid/run", "key", timeout_seconds=0.02), transport=httpx.MockTransport(handler))
    with pytest.raises(InferenceFailure, match="timeout"):
        asyncio.run(adapter.infer(request()))
    assert calls == ["/run", "/cancel/job_1"]
    assert adapter.last_provider_metrics["cancel_status"] == "CANCELLED"
