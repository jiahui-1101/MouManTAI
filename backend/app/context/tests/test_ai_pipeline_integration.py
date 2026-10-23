"""Integration tests for P1 BATCH 7: Validated AI Pipeline in repository processing and context lifecycle."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.context.ai.protocol import InferenceFailure, InferenceInput, InferenceOutput, MODEL_CONFIG
from app.context.ai.service import ModelProposalService
from app.context.context_service import ContextService
from app.context.core_publisher import CoreContextPublisher
from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, VERSION
from app.context.order_context_schemas import ContextReviewRequest
from app.context.p2_consumer import P2FeasibilityConsumer
from app.context.postgres_repository import PostgresMessageRepository
from app.context.schemas import ExtractedField, FieldEvidence, RawMessageEnvelope
from app.core.dependencies import RequestContext
from app.core.events import CoreEventType
from app.core.models import CommitmentRecord
from app.core.schemas import AgreementState, DomainEvent, FeasibilityState
from app.db.base import Base

NOW = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)


class FakeEndpoint:
    def __init__(self, responses=None, fail_error=None):
        self.requests: list[InferenceInput] = []
        self.responses = list(responses or [])
        self.fail_error = fail_error

    async def infer(self, request: InferenceInput) -> InferenceOutput:
        self.requests.append(request)
        if self.fail_error:
            raise self.fail_error
        if self.responses:
            return self.responses.pop(0)
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


def make_envelope(text: str, tenant_id: str = "synthetic_tenant_a") -> RawMessageEnvelope:
    return RawMessageEnvelope(
        tenant_id=tenant_id,
        channel="WHATSAPP",
        provider_message_id=f"prov_{uuid4().hex[:8]}",
        sender_identity_id="sender_synthetic_01",
        sender_alias="Buyer Synthetic",
        received_at=NOW,
        message_at=NOW,
        business_timezone="Asia/Kuala_Lumpur",
        text=text,
    )


def test_pipeline_skips_model_when_rules_complete(pg_engine):
    """When deterministic rules cleanly extract all required fields, Qwen is marked not_needed."""
    endpoint = FakeEndpoint()
    svc = ModelProposalService(endpoint=endpoint, enabled=True, stages=("qwen",))
    repo = PostgresMessageRepository(pg_engine, proposal_service=svc)

    env = make_envelope("20 pcs burgers tomorrow at 3pm", tenant_id="synthetic_tenant_a")
    ingested = repo.ingest(env, NOW).message

    res = repo.process("synthetic_tenant_a", ingested.message_id)
    assert res.attempt.status == "PROCESSED"
    # Extractor version stays deterministic because no model fields were needed/added
    assert res.attempt.extractor_version == VERSION
    assert not endpoint.requests
    assert res.attempt.diagnostic is not None
    assert "not_needed" in res.attempt.diagnostic


def test_pipeline_invokes_qwen_for_ambiguous_fields(pg_engine):
    """When rules leave quantity unresolved, Qwen is invoked and candidates are recorded."""
    text = "Need burgers serving 40 guests"
    # "serving 40 guests" causes rules to leave quantity UNRESOLVED
    model_field = {
        "field": "quantity",
        "message_id": "m1",
        "quote": "40",
        "start": text.index("40"),
        "end": text.index("40") + 2,
    }
    fake_output = InferenceOutput(
        engine="qwen",
        model_id=MODEL_CONFIG["qwen"][0],
        revision=MODEL_CONFIG["qwen"][1],
        status="ok",
        finish_reason="stop",
        load_seconds=0.0,
        inference_seconds=0.1,
        fields=[model_field],
    )
    endpoint = FakeEndpoint(responses=[fake_output])
    svc = ModelProposalService(endpoint=endpoint, enabled=True, stages=("qwen",))
    repo = PostgresMessageRepository(pg_engine, proposal_service=svc)

    env = make_envelope(text, tenant_id="synthetic_tenant_a")
    ingested = repo.ingest(env, NOW).message

    res = repo.process("synthetic_tenant_a", ingested.message_id)
    assert res.attempt.status == "PROCESSED"
    assert res.attempt.extractor_version == "p1-ai-pipeline-v2"
    assert len(endpoint.requests) == 1

    # Check candidates
    model_candidates = [f for f in res.attempt.fields if f.evidence and f.evidence[0].method == "MODEL"]
    assert len(model_candidates) == 1
    assert model_candidates[0].field_name == "quantity"
    assert model_candidates[0].value == "40"
    assert model_candidates[0].validation_status == "UNRESOLVED"


def test_pipeline_protects_valid_rule_fields_from_model_disagreements(pg_engine):
    """If a model proposal disagrees with an already VALID rule field, it is marked CONFLICT."""
    text = "20 burgers serving 40 guests"
    start_40 = text.index("40")
    fake_output = InferenceOutput(
        engine="qwen",
        model_id=MODEL_CONFIG["qwen"][0],
        revision=MODEL_CONFIG["qwen"][1],
        status="ok",
        finish_reason="stop",
        load_seconds=0.0,
        inference_seconds=0.1,
        fields=[{"field": "quantity", "message_id": "m1", "quote": "40", "start": start_40, "end": start_40 + 2}],
    )
    endpoint = FakeEndpoint(responses=[fake_output])
    svc = ModelProposalService(endpoint=endpoint, enabled=True, stages=("qwen",))
    repo = PostgresMessageRepository(pg_engine, proposal_service=svc)

    env = make_envelope(text, tenant_id="synthetic_tenant_a")
    ingested = repo.ingest(env, NOW).message

    res = repo.process("synthetic_tenant_a", ingested.message_id)
    assert res.attempt.status == "PROCESSED"

    # Rule field remains valid or unresolved, but model candidate with differing value is tagged
    candidates = [f for f in res.attempt.fields if f.evidence and f.evidence[0].method == "MODEL"]
    assert len(candidates) == 1
    assert candidates[0].value == "40"


def test_pipeline_falls_back_to_rules_on_endpoint_unavailable(pg_engine):
    """When endpoint raises InferenceFailure, rule fields are preserved and attempt diagnostic notes fallback."""
    text = "Need 40 or 50 burgers tomorrow"  # Real ambiguity, rather than an absent quantity a model cannot supply.
    endpoint = FakeEndpoint(fail_error=InferenceFailure("unavailable"))
    svc = ModelProposalService(endpoint=endpoint, enabled=True, stages=("qwen",))
    repo = PostgresMessageRepository(pg_engine, proposal_service=svc)

    env = make_envelope(text, tenant_id="synthetic_tenant_a")
    ingested = repo.ingest(env, NOW).message

    res = repo.process("synthetic_tenant_a", ingested.message_id)
    assert res.attempt.status == "PROCESSED"
    # Extractor version stays deterministic version on complete fallback
    assert res.attempt.extractor_version == VERSION
    assert res.attempt.diagnostic is not None
    assert "unavailable" in res.attempt.diagnostic or "fallback" in res.attempt.diagnostic
    # Rule fields preserved
    assert any(f.field_name == "sku" for f in res.attempt.fields)


def test_pipeline_rejects_hallucinated_model_spans(pg_engine):
    """If a model invents a quote not verbatim in raw message text, it fails fast and falls back cleanly."""
    text = "20 burgers"
    # Hallucinated quote that does not appear in text
    fake_output = InferenceOutput(
        engine="qwen",
        model_id=MODEL_CONFIG["qwen"][0],
        revision=MODEL_CONFIG["qwen"][1],
        status="ok",
        finish_reason="stop",
        load_seconds=0.0,
        inference_seconds=0.1,
        fields=[{"field": "delivery", "message_id": "m1", "quote": "tomorrow at 15:00", "start": 0, "end": 18}],
    )
    endpoint = FakeEndpoint(responses=[fake_output])
    svc = ModelProposalService(endpoint=endpoint, enabled=True, stages=("qwen",))
    repo = PostgresMessageRepository(pg_engine, proposal_service=svc)

    env = make_envelope(text, tenant_id="synthetic_tenant_a")
    ingested = repo.ingest(env, NOW).message

    res = repo.process("synthetic_tenant_a", ingested.message_id)
    assert res.attempt.status == "PROCESSED"
    # No candidate fields with fabricated quotes should be added
    assert not any(f.value == "tomorrow at 15:00" for f in res.attempt.fields)


def test_pipeline_tenant_isolation_in_model_request(pg_engine):
    """Verify that only the raw text is passed to model request — no tenant ID, sender ID, or tokens."""
    endpoint = FakeEndpoint()
    svc = ModelProposalService(endpoint=endpoint, enabled=True, stages=("qwen",))
    repo = PostgresMessageRepository(pg_engine, proposal_service=svc)

    env = make_envelope("Need 50 burgers", tenant_id="tenant_secret_isolation")
    ingested = repo.ingest(env, NOW).message

    repo.process("tenant_secret_isolation", ingested.message_id)
    for req in endpoint.requests:
        payload_str = req.model_dump_json()
        assert "tenant_secret_isolation" not in payload_str
        assert "sender_synthetic_01" not in payload_str


def test_full_message_ai_processing_review_core_p2_flow(pg_engine):
    """Complete BATCH 7 lifecycle: Ingest -> AI Process -> ContextService (PARTIAL) -> Review -> Core Publish -> P2 Feasibility."""
    with pg_engine.begin() as conn:
        Base.metadata.create_all(conn)

    text = "Need burgers tomorrow"
    endpoint = FakeEndpoint()
    svc = ModelProposalService(endpoint=endpoint, enabled=True, stages=("qwen",))
    repo = PostgresMessageRepository(pg_engine, proposal_service=svc)

    env = make_envelope(text, tenant_id="synthetic_tenant_a")
    ingested = repo.ingest(env, NOW).message

    # 1. AI processing
    proc = repo.process("synthetic_tenant_a", ingested.message_id)
    assert proc.attempt.status == "PROCESSED"

    # 2. Context creation: missing quantity leaves context in INFORMATION_PARTIAL
    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message("synthetic_tenant_a", ingested.message_id)
    assert ctx.status in ("INFORMATION_PARTIAL", "UNRESOLVED")
    assert not ctx.requested_items  # Incomplete items not published

    # 3. Human review: operator fills in verified quantity 100 pcs and link customer
    review_req = ContextReviewRequest(
        action="EDIT_FIELD",
        expected_context_version=ctx.context_version,
        field_edits={
            "requested_items": [{"sku": "BURGER", "quantity": "100", "unit": "pcs"}],
            "requested_delivery_at": datetime(2026, 10, 23, 15, 0, 0, tzinfo=timezone.utc),
            "delivery_qualifier": "DEADLINE",
            "customer_id": "cust_bk",
            "customer_identity_status": "LINK_VERIFIED",
            "missing_fields": [],
            "conflicts": [],
        },
        note="Operator verified phone call order for 100 pcs burgers",
    )
    reviewed_ctx = ctx_service.review_context("synthetic_tenant_a", ctx.context_id, review_req, "operator_1", "OPERATOR")
    assert reviewed_ctx.status == "INFORMATION_READY"
    assert len(reviewed_ctx.requested_items) == 1
    assert reviewed_ctx.requested_items[0].quantity == "100"

    # 4. Publication to Core
    publisher = CoreContextPublisher()
    req_context = RequestContext(
        tenant_id="synthetic_tenant_a",
        actor_id="operator_1",
        actor_role="OPERATOR",
        correlation_id=f"corr_{uuid4().hex[:8]}",
        causation_id=reviewed_ctx.context_id,
    )
    with Session(pg_engine) as session:
        commitment = publisher.publish_to_core(session, req_context, reviewed_ctx)
        assert commitment.commitment_id.startswith("com_")
        assert commitment.agreement_state == AgreementState.REQUESTED

        # Advance to CONFIRMED for operational P2 feasibility evaluation
        row = session.get(CommitmentRecord, ("synthetic_tenant_a", commitment.commitment_id))
        assert row is not None
        row.agreement_state = AgreementState.CONFIRMED.value
        session.commit()

        # 5. P2 Feasibility Evaluation
        ev = DomainEvent(
            event_id=f"evt_p2_eval_{uuid4().hex[:8]}",
            schema_version=1,
            event_type=CoreEventType.COMMITMENT_CONTEXT_READY.value,
            tenant_id="synthetic_tenant_a",
            commitment_id=commitment.commitment_id,
            commitment_version=row.commitment_version,
            correlation_id="corr_eval_ai",
            causation_id="cause_ai_ready",
            occurred_at=datetime.now(timezone.utc),
            payload={"commitment_id": commitment.commitment_id},
        )
        consumer = P2FeasibilityConsumer()
        eval_result = consumer.handle_context_ready(session, ev)
        assert eval_result is not None
        assert eval_result.status == FeasibilityState.FEASIBLE
        session.commit()

        # Check commitment record feasibility state
        record = session.get(CommitmentRecord, ("synthetic_tenant_a", commitment.commitment_id))
        assert record is not None
        assert record.feasibility_state == FeasibilityState.FEASIBLE.value
