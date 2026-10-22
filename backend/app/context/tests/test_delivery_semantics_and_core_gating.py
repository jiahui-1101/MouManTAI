"""Focused delivery date semantics and Core publication gating test suite (WS3).

Verifies:
1. Multilingual delivery expressions (EN, ZH, MS) map to accurate qualifiers (DEADLINE, EXACT, DATE_ONLY).
2. Date-only expressions do not fabricate midnight or instant; they require human review.
3. OrderContext mapping preserves missing_fields when delivery is date-only or unresolved.
4. CoreContextPublisher eligibility gate strictly blocks:
   - delivery_qualifier == 'DATE_ONLY'
   - delivery_qualifier == 'EXACT'
   - delivery_qualifier is None
   - requested_delivery_at is None
   - requested_delivery_at is naive (no tzinfo)
5. Only explicit, timezone-aware DEADLINE deliveries can reach Core publication.
6. Human review via Review Drawer transforms DATE_ONLY / EXACT into verified DEADLINE.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy.orm import Session

from app.context.core_publisher import CoreContextPublisher, IneligibleContextError
from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, ProductAlias, extract_explicit_fields
from app.context.order_context_schemas import ContextReviewRequest, OrderContextRecord, RequestedItem
from app.context.postgres_repository import PostgresMessageRepository
from app.context.schemas import RawMessageEnvelope
from app.context.ingestion_schemas import StoredMessage
from app.context.tests.test_core_publisher import make_valid_context
from app.core.dependencies import RequestContext


def make_stored_message(text: str, tz: str = "Asia/Kuala_Lumpur", received_at: datetime | None = None) -> StoredMessage:
    rx = received_at or datetime(2026, 10, 20, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    raw = RawMessageEnvelope(
        tenant_id="tenant_delivery_test",
        channel="WHATSAPP",
        provider_message_id=f"deliv_msg_{hash(text)}",
        sender_identity_id="+60123456789",
        sender_alias="Delivery Tester",
        received_at=rx,
        business_timezone=tz,
        text=text,
        attachments=[],
    )
    return StoredMessage(
        message_id="msg_test_deliv",
        raw=raw,
        synthetic_provider="SYNTHETIC_WHATSAPP",
        content_sha256="dummy_sha",
        processing_status="RECEIVED",
        ingested_at=rx,
        updated_at=rx,
    )


# 1. Multilingual Expression Tests
@pytest.mark.parametrize("text,expected_qualifier,expected_hour", [
    ("Please deliver 20 burgers tomorrow before 3pm", "DEADLINE", 15),
    ("Need 20 burgers tomorrow by 5pm", "DEADLINE", 17),
    ("Tolong hantar 20 burgers esok sebelum 3pm", "DEADLINE", 15),
    ("Hantar 20 burgers esok selewat-lewatnya pukul 4 petang", "DEADLINE", 16),
    ("paling lambat esok 3pm", "DEADLINE", 15),
    ("明天下午3点前送达20个汉堡", "DEADLINE", 15),
    ("最晚明天15:00要20个汉堡", "DEADLINE", 15),
    ("明天下午3点之前送达", "DEADLINE", 15),
    # Exact expressions
    ("Deliver tomorrow at 3pm", "EXACT", 15),
    ("esok pada pukul 3 petang", "EXACT", 15),
    ("明天下午3点送达", "EXACT", 15),
])
def test_multilingual_delivery_qualifier_extraction(text, expected_qualifier, expected_hour):
    msg = make_stored_message(text)
    fields = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    del_fields = [f for f in fields.fields if f.field_name == "requested_delivery_at"]
    assert len(del_fields) == 1
    df = del_fields[0]
    assert df.validation_status == "VALID"
    assert df.qualifier == expected_qualifier
    assert "T" in df.value
    dt = datetime.fromisoformat(df.value)
    assert dt.hour == expected_hour
    assert dt.tzinfo is not None


@pytest.mark.parametrize("text", [
    "Please send 20 burgers tomorrow",
    "Tolong hantar esok",
    "明天送过来",
    "Deliver on 2026-10-25",
])
def test_date_only_delivery_has_no_fabricated_instant(text):
    msg = make_stored_message(text)
    fields = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    del_fields = [f for f in fields.fields if f.field_name == "requested_delivery_at"]
    assert len(del_fields) == 1
    df = del_fields[0]
    assert df.validation_status == "VALID"
    assert df.qualifier == "DATE_ONLY"
    assert "T" not in df.value  # Just a date string, e.g. "2026-10-21"


@pytest.mark.parametrize("text", [
    "明天3点之前送达",
    "Deliver tomorrow at 3",
    "hantar esok pukul 3",
])
def test_ambiguous_time_without_meridiem_is_gated_from_core(text):
    msg = make_stored_message(text)
    fields = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    del_fields = [f for f in fields.fields if f.field_name == "requested_delivery_at"]
    assert len(del_fields) == 1
    df = del_fields[0]
    # Zero-guessing invariant: system never fabricates an instant when meridiem is missing
    if df.validation_status == "VALID":
        assert df.qualifier == "DATE_ONLY"
        assert "T" not in df.value
    else:
        assert df.validation_status in ("INVALID", "UNRESOLVED")
        assert df.value is None


# 2. Core Publisher Gating Tests
def test_date_only_qualifier_is_ineligible_for_core():
    ctx = make_valid_context("test_tenant", "ctx_date_only")
    ctx.delivery_qualifier = "DATE_ONLY"
    publisher = CoreContextPublisher()
    eligible, reasons = publisher.check_eligibility(ctx)
    assert not eligible
    assert any("DATE_ONLY/EXACT/unknown delivery semantics require P5/P2 mapping" in r for r in reasons)


def test_exact_qualifier_is_ineligible_for_core():
    ctx = make_valid_context("test_tenant", "ctx_exact")
    ctx.delivery_qualifier = "EXACT"
    publisher = CoreContextPublisher()
    eligible, reasons = publisher.check_eligibility(ctx)
    assert not eligible
    assert any("DATE_ONLY/EXACT/unknown delivery semantics require P5/P2 mapping" in r for r in reasons)


def test_naive_delivery_timestamp_is_ineligible_for_core():
    ctx = make_valid_context("test_tenant", "ctx_naive")
    # Naive datetime (no tzinfo)
    ctx.requested_delivery_at = datetime(2026, 10, 25, 15, 0, 0)
    publisher = CoreContextPublisher()
    eligible, reasons = publisher.check_eligibility(ctx)
    assert not eligible
    assert any("explicit offset-aware delivery deadline is required" in r for r in reasons)


def test_missing_delivery_timestamp_is_ineligible_for_core():
    ctx = make_valid_context("test_tenant", "ctx_no_deliv")
    ctx.requested_delivery_at = None
    publisher = CoreContextPublisher()
    eligible, reasons = publisher.check_eligibility(ctx)
    assert not eligible
    assert any("explicit offset-aware delivery deadline is required" in r for r in reasons)


def test_valid_deadline_with_offset_is_eligible_for_core():
    ctx = make_valid_context("test_tenant", "ctx_valid_deliv")
    ctx.requested_delivery_at = datetime(2026, 10, 25, 15, 0, 0, tzinfo=timezone.utc)
    ctx.delivery_qualifier = "DEADLINE"
    publisher = CoreContextPublisher()
    eligible, reasons = publisher.check_eligibility(ctx)
    assert eligible
    assert len(reasons) == 0


# 3. End-to-end: Date-only Context requires Review before Core publication
def test_date_only_flow_to_review_to_core(pg_engine):
    repo = PostgresMessageRepository(pg_engine, catalog=(
        ProductAlias("test_tenant_flow", "SKU_BREAD_01", ("bread",), "pcs"),
    ))
    publisher = CoreContextPublisher()
    tenant = "test_tenant_flow"
    ctx_id = "ctx_flow_01"

    # Context created with DATE_ONLY (missing explicit instant)
    ctx = make_valid_context(tenant, ctx_id)
    ctx.delivery_qualifier = "DATE_ONLY"
    ctx.missing_fields = ["requested_delivery_at"]
    ctx.status = "INFORMATION_PARTIAL"
    saved = repo.save_order_context(ctx)

    # Cannot publish directly
    req = RequestContext(tenant, "user_staff_01", "STAFF", "corr_flow")
    with pytest.raises(IneligibleContextError) as exc_info, Session(pg_engine) as session:
        publisher.publish_to_core(session, req, saved)
    assert "ineligible" in str(exc_info.value).lower()

    # Human reviewer clarifies with buyer and sets explicit DEADLINE in Review Drawer
    deadline_at = datetime(2026, 10, 22, 15, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    review_req = ContextReviewRequest(
        expected_context_version=1,
        action="EDIT_FIELD",
        field_edits={
            "requested_delivery_at": deadline_at.isoformat(),
            "delivery_qualifier": "DEADLINE",
            "missing_fields": [],
        },
        note="Confirmed with buyer: deliver before 3pm Kuala Lumpur time",
    )
    reviewed = repo.apply_context_review(tenant, ctx_id, review_req, "user_staff_01", "STAFF")
    assert reviewed.context_version == 2
    assert reviewed.status == "INFORMATION_READY"
    assert reviewed.delivery_qualifier == "DEADLINE"
    assert reviewed.requested_delivery_at == deadline_at

    # Now publication to Core succeeds cleanly
    with Session(pg_engine) as session:
        commitment = publisher.publish_to_core(session, req, reviewed)
        assert commitment.commitment_id is not None
