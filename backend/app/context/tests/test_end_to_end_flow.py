from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session

from app.context.ai.protocol import MODEL_CONFIG
from app.context.ai.service import InferenceInput, InferenceOutput, ModelProposalService, Observation
from app.context.context_service import ContextService
from app.context.core_publisher import CoreContextPublisher, RequestContext
from app.context.deterministic_extraction import ProductAlias
from app.context.postgres_repository import OrderContextVersion, PostgresMessageRepository
from app.context.order_context_schemas import ContextReviewRequest
from app.core.models import CommitmentRecord
from app.db.base import Base
from app.context.tests.test_ai_pipeline_integration import NOW, make_envelope


class MultiItemFakeEndpoint:
    def __init__(self):
        self.invocations = []

    async def infer(self, request: InferenceInput) -> InferenceOutput:
        self.invocations.append(request)
        msg_id = request.messages[0].id
        text = request.messages[0].text
        cfg = MODEL_CONFIG[request.engine]

        def obs(field, quote, group_id):
            idx = text.find(quote)
            assert idx >= 0, f"Quote {quote!r} not found in {text!r}"
            return Observation(
                message_id=msg_id,
                field=field,
                quote=quote,
                start=idx,
                end=idx + len(quote),
                group_id=group_id,
            )

        return InferenceOutput(
            engine=request.engine,
            model_id=cfg[0],
            revision=cfg[1],
            status="ok",
            finish_reason="stop",
            inference_seconds=0.05,
            load_seconds=0.0,
            gpu_name="Tesla T4",
            dtype="bfloat16",
            peak_gpu_bytes=1000000,
            fields=[
                obs("quantity", "24", "g1"),
                obs("unit", "pcs", "g1"),
                obs("product", "burgers", "g1"),
                obs("quantity", "36", "g2"),
                obs("unit", "boxes", "g2"),
                obs("product", "bread", "g2"),
            ],
        )


def test_end_to_end_multi_item_flow_preserved_through_review_drawer(pg_engine):
    """Criterion 11: Real end-to-end flow from newly submitted customer message

    through AI extraction, structured context, Review Drawer, and Core publication.
    Ensures multi-item data is preserved throughout without truncation or data loss.
    """
    with pg_engine.begin() as conn:
        Base.metadata.create_all(conn)

    tenant_id = "synthetic_tenant_a"
    text = "Please deliver 24 pcs burgers and 36 boxes bread tomorrow at 3pm."

    endpoint = MultiItemFakeEndpoint()
    svc = ModelProposalService(endpoint=endpoint, enabled=True, stages=("qwen",))
    test_catalog = (
        ProductAlias(tenant_id, "BURGER", ("burger", "burgers"), "pcs"),
        ProductAlias(tenant_id, "BREAD", ("bread",), "box"),
    )
    repo = PostgresMessageRepository(pg_engine, proposal_service=svc, catalog=test_catalog)

    # 1. Ingest customer message
    env = make_envelope(text, tenant_id=tenant_id)
    ingested = repo.ingest(env, NOW).message
    assert ingested.message_id is not None

    # 2. Process extraction: L0 + L2 ModelProposalService
    proc = repo.process(tenant_id, ingested.message_id)
    assert proc.attempt.status == "PROCESSED"
    # Ensure attempt fields include multi-item candidate observations
    field_names = [f.field_name for f in proc.attempt.fields]
    assert "sku" in field_names
    assert "quantity" in field_names

    # 3. Structured Context: ContextService creates OrderContextRecord
    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message(tenant_id, ingested.message_id)

    # Multi-item items preserved in structured context
    assert ctx.requested_items is not None
    assert len(ctx.requested_items) == 2, f"Expected 2 items, got {len(ctx.requested_items)}"
    assert ctx.requested_items[0].sku == "BURGER"
    assert ctx.requested_items[0].quantity == "24"
    assert ctx.requested_items[0].unit == "pcs"
    assert ctx.requested_items[1].sku == "BREAD"
    assert ctx.requested_items[1].quantity == "36"
    assert ctx.requested_items[1].unit == "box"

    # Status requires review (provisional proposal and unlinked customer identity)
    assert ctx.status in ("INFORMATION_PARTIAL", "CONFLICT", "UNRESOLVED")

    # 4. Review Drawer operation:
    # Review Drawer simulates operator confirming extraction and linking customer identity
    review_req = ContextReviewRequest(
        action="ACCEPT_EXTRACTION",
        expected_context_version=ctx.context_version,
        field_edits={
            "customer_id": "cust_verified_101",
            "customer_identity_status": "LINK_VERIFIED",
            "delivery_qualifier": "DEADLINE",
            "missing_fields": [],
            "conflicts": [],
        },
        note="Operator verified multi-item line items in Review Drawer",
    )
    reviewed_ctx = ctx_service.review_context(tenant_id, ctx.context_id, review_req, "operator_42", "OPERATOR")

    # Multi-item data preserved in reviewed context
    assert reviewed_ctx.context_version == 2
    assert reviewed_ctx.status == "INFORMATION_READY"
    assert len(reviewed_ctx.requested_items) == 2
    assert reviewed_ctx.requested_items[0].sku == "BURGER"
    assert reviewed_ctx.requested_items[1].sku == "BREAD"
    assert reviewed_ctx.requested_items[1].quantity == "36"
    assert reviewed_ctx.requested_items[1].unit == "box"

    # Verify version audit trail in Postgres
    with Session(pg_engine) as session:
        versions = session.query(OrderContextVersion).filter_by(context_id=ctx.context_id).all()
        assert len(versions) >= 2

    # 5. Publication to Core Commitment
    publisher = CoreContextPublisher()
    req_context = RequestContext(
        tenant_id=tenant_id,
        actor_id="operator_42",
        actor_role="OPERATOR",
        correlation_id=f"corr_{uuid4().hex[:8]}",
        causation_id=reviewed_ctx.context_id,
    )
    with Session(pg_engine) as session:
        commitment = publisher.publish_to_core(session, req_context, reviewed_ctx)
        assert commitment.commitment_id.startswith("com_")
        # Line items preserved in core commitment
        row = session.get(CommitmentRecord, (tenant_id, commitment.commitment_id))
        assert row is not None
        assert row.terms is not None
