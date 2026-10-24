"""Typed P1 classification and inert durable C3 review regressions."""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.context.ai.protocol import (
    MODEL_CONFIG,
    InferenceFailure,
    InferenceInput,
    InferenceOutput,
    SourceText,
)
from app.context.ai.provider_reliability import (
    GeminiConfig,
    GeminiEndpointAdapter,
    QwenGeminiReliabilityAdapter,
)
from app.core.dependencies import RequestContext
from app.message_intelligence.adapters import CurrentP1MessageReader
from app.message_intelligence.p1_gateway import P1ClassificationGateway
from app.message_intelligence.review import C3ReviewService, ReviewDecision, ReviewGrant
from app.message_intelligence.review_models import C3ReviewRecord
from app.message_intelligence.service import MessageIntelligenceService, SourceContractError
from tests.test_message_intelligence import NOW, CurrentSourceFixture, canonical_message

ASSESSMENT = {"intent": "CUSTOMER_INQUIRY", "inquiry_topic": "PRODUCT_INFO", "claims": [
    {"kind": "INQUIRY", "value": "pack sizes", "evidence": {
        "segment_id": "s0", "quote": "pack sizes", "start": 10, "end": 20,
    }}]}


class Primary:
    def __init__(self, failure=None, raw=None):
        self.failure, self.raw, self.calls = failure, raw, 0

    async def infer(self, request):
        self.calls += 1
        assert request.task == "c3_classification"
        if self.failure:
            raise InferenceFailure(self.failure)
        return InferenceOutput(
            engine="qwen", provider="qwen", model_id=MODEL_CONFIG["qwen"][0],
            revision=MODEL_CONFIG["qwen"][1], status="invalid_output" if self.raw else "ok",
            raw_output=self.raw or "", classification=None if self.raw else ASSESSMENT,
            finish_reason="stop", load_seconds=0, inference_seconds=0,
        )


class Fallback:
    def __init__(self):
        self.calls = 0

    async def infer(self, request):
        self.calls += 1
        return InferenceOutput(
            engine="qwen", provider="gemini", model_id=MODEL_CONFIG["gemini"][0],
            revision=MODEL_CONFIG["gemini"][1], status="ok", classification=ASSESSMENT,
            finish_reason="stop", load_seconds=0, inference_seconds=0,
        )


@pytest.mark.parametrize("failure,raw,expected", [
    (None, None, "QWEN"), ("timeout", None, "GEMINI"),
    (None, "malformed", "GEMINI"),
])
def test_shared_gateway_success_and_eligible_fallback(failure, raw, expected):
    primary, fallback = Primary(failure, raw), Fallback()
    gateway = P1ClassificationGateway(QwenGeminiReliabilityAdapter(primary, fallback))
    result = gateway.classify([("s0", "Are these pack sizes suitable?")])
    assert result.provider == expected
    assert result.assessment.claims[0].evidence.quote == "pack sizes"
    assert primary.calls == 1
    assert fallback.calls == (expected == "GEMINI")


def test_valid_unknown_does_not_call_fallback():
    class Ambiguous(Primary):
        async def infer(self, request):
            self.calls += 1
            return InferenceOutput(
                engine="qwen", provider="qwen", model_id=MODEL_CONFIG["qwen"][0],
                revision=MODEL_CONFIG["qwen"][1], status="ok",
                classification={"intent": "UNKNOWN", "inquiry_topic": None, "claims": []},
                finish_reason="stop", load_seconds=0, inference_seconds=0,
            )
    primary, fallback = Ambiguous(), Fallback()
    result = P1ClassificationGateway(QwenGeminiReliabilityAdapter(primary, fallback)).classify(
        [("s0", "Please help with this")])
    assert result.assessment.intent == "UNKNOWN"
    assert fallback.calls == 0


def test_forged_provenance_and_invalid_span_fail_closed_without_fallback():
    class Forged(Primary):
        async def infer(self, request):
            result = await super().infer(request)
            return result.model_copy(update={"model_id": "forged-model"})

    fallback = Fallback()
    result = P1ClassificationGateway(QwenGeminiReliabilityAdapter(Forged(), fallback)).classify(
        [("s0", "Are these pack sizes suitable?")])
    assert result.provider == "GEMINI"  # technical model mismatch permits fallback

    class BadSpan(Primary):
        async def infer(self, request):
            result = await super().infer(request)
            payload = result.classification.model_dump()
            payload["claims"][0]["evidence"]["quote"] = "pack sizez"
            return result.model_copy(update={
                "classification": type(result.classification).model_validate(payload)})

    fallback = Fallback()
    with pytest.raises(InferenceFailure, match="source_evidence_invalid"):
        P1ClassificationGateway(QwenGeminiReliabilityAdapter(BadSpan(), fallback)).classify(
            [("s0", "Are these pack sizes suitable?")])
    assert fallback.calls == 0


def test_gemini_classification_uses_typed_task_schema():
    def respond(request):
        payload = json.loads(request.content)
        assert "classification" not in payload["contents"][0]["parts"][0]["text"]
        assert payload["generationConfig"]["responseFormat"]["text"]["schema"]["properties"]["intent"]
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(ASSESSMENT)}]}}]})

    adapter = GeminiEndpointAdapter(GeminiConfig(api_key="synthetic-test-key", max_retries=0),
                                    transport=httpx.MockTransport(respond))
    output = asyncio.run(adapter.infer(InferenceInput(
        engine="qwen", task="c3_classification",
        messages=[SourceText(id="s0", text="Are these pack sizes suitable?")],
    )))
    assert output.classification.intent == "CUSTOMER_INQUIRY"
    assert output.validation_outcome == "VALIDATED"


class Authority:
    def authorize(self, db, context, *, review_id, action):
        return ReviewGrant(tenant_id=context.tenant_id, actor_id=context.actor_id,
                           action=action, evidence_refs=("p5:verified-review-policy:v1",),
                           expires_at=NOW + timedelta(hours=1))


@pytest.mark.parametrize("action,corrected_intent", [
    ("APPROVE", None), ("REJECT", None), ("CORRECT", "OTHER"),
])
def test_durable_review_decision_is_tenant_scoped_and_stale_safe(action, corrected_intent):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    C3ReviewRecord.__table__.create(engine)
    msg = canonical_message("Please advise")
    source = CurrentSourceFixture(msg)
    reader = CurrentP1MessageReader(source, source)
    with Session(engine) as db:
        reviews = C3ReviewService(db, reader, Authority())
        row = reviews.enqueue(msg.message_id, MessageIntelligenceService(), now=NOW)
        assert row is not None and row.reason_codes
        assert reviews.enqueue(msg.message_id, MessageIntelligenceService(), now=NOW).review_id == row.review_id
        wrong = RequestContext("another_tenant", "reviewer", "MANAGER", "corr")
        command = ReviewDecision(action=action, corrected_intent=corrected_intent, expected_revision=1,
                                 request_key="decision-one", reason="Manual reading of original message")
        with pytest.raises(SourceContractError, match="tenant"):
            reviews.decide(wrong, row.review_id, command, now=NOW)
        context = RequestContext(msg.raw.tenant_id, "reviewer", "MANAGER", "corr")
        source.msg = canonical_message("Different source text")
        with pytest.raises(SourceContractError, match="stale"):
            reviews.decide(context, row.review_id, command, now=NOW)
        source.msg = msg
        decided = reviews.decide(context, row.review_id, command, now=NOW)
        assert decided.state == "DECIDED" and decided.decision == action
        assert decided.corrected_intent == corrected_intent
        assert decided.authorization_evidence_refs == ["p5:verified-review-policy:v1"]
        with pytest.raises(SourceContractError, match="stale"):
            reviews.decide(context, row.review_id, command, now=NOW)


def test_c3_review_exists_in_migrated_postgres(pg_suite_engine):
    assert "c3_message_reviews" in inspect(pg_suite_engine).get_table_names()
    msg = canonical_message("Please advise")
    source = CurrentSourceFixture(msg)
    with Session(pg_suite_engine) as db:
        row = C3ReviewService(db, CurrentP1MessageReader(source, source)).enqueue(
            msg.message_id, MessageIntelligenceService(), now=NOW)
        assert row is not None and row.tenant_id == msg.raw.tenant_id
        db.expire_all()
        assert db.get(C3ReviewRecord, (msg.raw.tenant_id, row.review_id)).state == "PENDING"


def test_review_rejects_tampered_model_provenance():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    C3ReviewRecord.__table__.create(engine)
    msg = canonical_message("Please advise")
    source = CurrentSourceFixture(msg)
    with Session(engine) as db:
        reviews = C3ReviewService(db, CurrentP1MessageReader(source, source), Authority())
        row = reviews.enqueue(msg.message_id, MessageIntelligenceService(), now=NOW)
        row.candidate_snapshot = {**row.candidate_snapshot, "provenance": {
            "provider": "QWEN", "version": "forged-model"}}
        db.commit()
        command = ReviewDecision(action="REJECT", expected_revision=1,
                                 request_key="reject-tampered", reason="Untrusted provenance")
        context = RequestContext(msg.raw.tenant_id, "reviewer", "MANAGER", "corr")
        with pytest.raises(SourceContractError, match="integrity"):
            reviews.decide(context, row.review_id, command, now=NOW)
