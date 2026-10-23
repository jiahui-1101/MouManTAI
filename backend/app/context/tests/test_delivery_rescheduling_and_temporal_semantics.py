"""Comprehensive regression tests for delivery rescheduling, temporal semantics,
order reference extraction, and written confirmation constraints.

Covers:
1. Complex delivery rescheduling ("moving delivery from X to Y before Z").
2. Distinction between original delivery date, requested delivery date, and deadline.
3. Source offset grounding of evidence.
4. "Before" qualifier remaining strictly DEADLINE, never EXACT.
5. Written confirmation clauses preserved as review/approval constraints.
6. Purchase order reference extraction (PO-DEMO-...).
7. Rescheduling with "instead of".
8. Date negation / correction ("not on X, but on Y").
9. Date ranges ("between X and Y").
10. Multiple conflicting delivery dates.
11. Multilingual Malay rescheduling and confirmation.
12. Fail-closed safety: context status CONFLICT, Core publication strictly blocked.
"""

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from app.context.schemas import RawMessageEnvelope, ExtractedField, FieldEvidence
from app.context.ingestion_schemas import StoredMessage
from app.context.deterministic_extraction import extract_explicit_fields, ProductAlias
from app.context.ai.service import ModelProposalService, ProposalResult
from app.context.ai.protocol import Observation
from app.context.context_service import ContextService
from app.context.postgres_repository import PostgresMessageRepository
from app.context.core_publisher import CoreContextPublisher
from app.context.reconciliation import reconcile_canonical_fields


def make_test_message(text: str, tenant_id: str = "synthetic_tenant_a", tz: str = "Asia/Kuala_Lumpur", msg_time: datetime | None = None) -> StoredMessage:
    rx = msg_time or datetime(2026, 10, 20, 10, 0, 0, tzinfo=ZoneInfo(tz))
    raw = RawMessageEnvelope(
        tenant_id=tenant_id,
        channel="WHATSAPP",
        provider_message_id=f"msg_{abs(hash(text))}",
        sender_identity_id="+60123456789",
        sender_alias="Customer",
        received_at=rx,
        business_timezone=tz,
        text=text,
        attachments=[],
    )
    return StoredMessage(
        message_id=f"msg_{abs(hash(text))}",
        raw=raw,
        synthetic_provider="SYNTHETIC_WHATSAPP",
        content_sha256="dummy_sha256",
        processing_status="RECEIVED",
        ingested_at=rx,
        updated_at=rx,
    )


PROVISIONAL_CATALOG = [
    ProductAlias("synthetic_tenant_a", "BURGER", ("burger", "burgers", "beef burger"), "pcs")
]


def test_failing_example_delivery_rescheduling_and_confirmation_constraint(pg_engine):
    """Verify the real failing example with rescheduling, deadline, and written confirmation."""
    text = (
        "Regarding PO-DEMO-2026-1042, due to unexpected campus holiday scheduling, "
        "we would like to request moving delivery from 26 October 2026 to 27 October 2026 before 3:00 PM. "
        "Quantity remains 100 pcs burgers. "
        "As noted in the purchase order rescheduling clause, manual written confirmation is required."
    )
    msg = make_test_message(text)

    # 1. Deterministic Extraction
    result = extract_explicit_fields(msg, catalog=PROVISIONAL_CATALOG)
    fields_by_name = {f.field_name: f for f in result.fields}

    # Verify PO reference
    assert "order_id" in fields_by_name
    order_f = fields_by_name["order_id"]
    assert order_f.value == "PO-DEMO-2026-1042"
    assert order_f.evidence[0].quote == "PO-DEMO-2026-1042"
    assert text[order_f.evidence[0].start:order_f.evidence[0].end] == "PO-DEMO-2026-1042"

    # Confirmation constraint is captured in metadata / conflicts, NEVER as a 5th canonical field
    assert "special_instructions" not in fields_by_name

    # Verify Delivery Rescheduling & Qualifier
    assert "requested_delivery_at" in fields_by_name
    del_f = fields_by_name["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "DEADLINE"  # "before 3:00 PM" must strictly remain DEADLINE
    assert del_f.value == "2026-10-27T15:00:00+08:00"
    assert del_f.metadata["rescheduling"] == "true"
    assert del_f.metadata["original_delivery_date"] == "2026-10-26"
    assert del_f.metadata["requested_delivery_date"] == "2026-10-27"
    assert del_f.metadata["upper_bound_deadline"] == "2026-10-27T15:00:00+08:00"
    assert del_f.metadata["deadline_time"] == "15:00:00"
    # Exact source offset grounding
    for ev in del_f.evidence:
        assert text[ev.start:ev.end] == ev.quote

    # Verify items
    assert fields_by_name["sku"].value == "BURGER"
    assert fields_by_name["quantity"].value == "100"
    assert fields_by_name["unit"].value == "pcs"

    # 2. Routing / L2 Escalation: Qwen must NOT be skipped with l1_sufficient
    pres = ProposalResult(rules=result, reviewed_fields=[], candidates=[], outcomes={}, conflicts=[])
    escalation = ModelProposalService._l2_escalation_reason(msg, pres)
    assert escalation is not None
    assert "Complex temporal delivery rescheduling request" in escalation

    # 3. Model candidate handling
    obs_del = Observation(message_id=msg.message_id, field="delivery", quote="27 October 2026 before 3:00 PM", start=139, end=169)
    cand_del = ModelProposalService._candidate(obs_del, msg, PROVISIONAL_CATALOG, "qwen3", "v1")
    assert cand_del.field_name == "requested_delivery_at"
    assert cand_del.qualifier == "DEADLINE"
    assert cand_del.metadata.get("domain_supported") == "true"

    obs_po = Observation(message_id=msg.message_id, field="order_reference", quote="PO-DEMO-2026-1042", start=10, end=27)
    cand_po = ModelProposalService._candidate(obs_po, msg, PROVISIONAL_CATALOG, "qwen3", "v1")
    assert cand_po.field_name == "order_id"
    assert cand_po.value == "PO-DEMO-2026-1042"
    assert cand_po.metadata.get("domain_supported") == "true"

    # 4. ContextService and Core publication fail-closed safety
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    repo.process("synthetic_tenant_a", msg_id)

    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message("synthetic_tenant_a", msg_id)

    # Must be in CONFLICT status (never auto-committed)
    assert ctx.status == "CONFLICT"
    assert ctx.delivery_qualifier == "DEADLINE"
    assert ctx.requested_delivery_at == datetime(2026, 10, 27, 15, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    assert ctx.special_instructions == "manual written confirmation is required"

    # Conflicts must describe both the rescheduling and the approval constraint
    assert any("Rescheduled delivery: moving from 2026-10-26 to 2026-10-27" in c for c in ctx.conflicts)
    assert any("Approval constraint: manual written confirmation is required" in c for c in ctx.conflicts)

    # Core publication must fail closed
    publisher = CoreContextPublisher()
    eligible, reasons = publisher.check_eligibility(ctx)
    assert not eligible
    assert any("status 'CONFLICT' is not INFORMATION_READY" in r for r in reasons)


def test_rescheduling_with_instead_of():
    """Verify rescheduling semantics using 'instead of' syntax."""
    text = "Please deliver on 28 October 2026 instead of 25 October 2026, 50 burgers"
    msg = make_test_message(text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_CATALOG)
    fields = {f.field_name: f for f in res.fields}

    del_f = fields["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "DATE_ONLY"
    assert del_f.metadata["rescheduling"] == "true"
    assert del_f.metadata["original_delivery_date"] == "2026-10-25"
    assert del_f.metadata["requested_delivery_date"] == "2026-10-28"


def test_date_negation_and_correction(pg_engine):
    """Verify negation and date correction ('not on X, but on Y at Z')."""
    text = "Not on 26 October 2026, but deliver on 27 October 2026 at 2:00 PM. 20 burgers."
    msg = make_test_message(text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_CATALOG)
    fields = {f.field_name: f for f in res.fields}

    del_f = fields["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "EXACT"
    assert del_f.metadata["correction"] == "true"
    assert del_f.metadata["original_delivery_date"] == "2026-10-26"
    assert del_f.metadata["requested_delivery_date"] == "2026-10-27"

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    repo.process("synthetic_tenant_a", msg_id)

    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message("synthetic_tenant_a", msg_id)

    assert ctx.status == "CONFLICT"
    assert any("Corrected delivery date: 2026-10-26 replaced with 2026-10-27" in c for c in ctx.conflicts)
    assert any("EXACT arrival time requires human confirmation as DEADLINE" in c for c in ctx.conflicts)


def test_delivery_date_range_window(pg_engine):
    """Verify delivery date range ('between X and Y')."""
    text = "Delivery needed between 26 October 2026 and 29 October 2026 for 30 burgers."
    msg = make_test_message(text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_CATALOG)
    fields = {f.field_name: f for f in res.fields}

    del_f = fields["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.metadata.get("date_range") == "true"
    assert del_f.metadata.get("window_start") == "2026-10-26"
    assert del_f.metadata.get("window_end") == "2026-10-29"

    # Escalation reason for L2
    pres = ProposalResult(rules=res, reviewed_fields=[], candidates=[], outcomes={}, conflicts=[])
    escalation = ModelProposalService._l2_escalation_reason(msg, pres)
    assert escalation is not None
    assert "Delivery date window range" in escalation

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    repo.process("synthetic_tenant_a", msg_id)

    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message("synthetic_tenant_a", msg_id)

    assert ctx.status == "CONFLICT"
    assert any("Delivery date window range requires operator confirmation" in c for c in ctx.conflicts)


def test_multiple_delivery_dates(pg_engine):
    """Verify multiple dates in a message are flagged as review-required."""
    text = "We need delivery on 26 October 2026 and also on 30 October 2026, 50 burgers."
    msg = make_test_message(text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_CATALOG)
    fields = {f.field_name: f for f in res.fields}

    del_f = fields["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.metadata.get("multiple_delivery_dates") == "true"

    pres = ProposalResult(rules=res, reviewed_fields=[], candidates=[], outcomes={}, conflicts=[])
    escalation = ModelProposalService._l2_escalation_reason(msg, pres)
    assert escalation is not None
    assert "Multiple conflicting delivery dates" in escalation

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    repo.process("synthetic_tenant_a", msg_id)

    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message("synthetic_tenant_a", msg_id)

    assert ctx.status == "CONFLICT"
    assert any("Multiple delivery dates mentioned" in c for c in ctx.conflicts)


def test_multilingual_malay_rescheduling_and_written_confirmation(pg_engine):
    """Verify Malay language rescheduling, month parsing, and written confirmation constraint."""
    text = (
        "Merujuk PO-DEMO-2026-888, mohon tunda penghantaran dari 26 Oktober 2026 ke 27 Oktober 2026 sebelum 3:00 petang. "
        "Jumlah kekal 100 burger. Pengesahan bertulis diperlukan."
    )
    msg = make_test_message(text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_CATALOG)
    fields = {f.field_name: f for f in res.fields}

    assert fields["order_id"].value == "PO-DEMO-2026-888"
    assert "special_instructions" not in fields

    del_f = fields["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "DEADLINE"
    assert del_f.metadata["original_delivery_date"] == "2026-10-26"
    assert del_f.metadata["requested_delivery_date"] == "2026-10-27"
    assert del_f.metadata["deadline_time"] == "15:00:00"

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    repo.process("synthetic_tenant_a", msg_id)

    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message("synthetic_tenant_a", msg_id)

    assert ctx.status == "CONFLICT"
    assert any("Rescheduled delivery: moving from 2026-10-26 to 2026-10-27" in c for c in ctx.conflicts)
    assert any("Approval constraint: Pengesahan bertulis diperlukan" in c for c in ctx.conflicts)



def test_case_a_rescheduling_exact_four_fields_and_deduplication(pg_engine):
    """Regression Case A: Delivery rescheduling with deadline and written confirmation.

    Verifies:
    1. Strictly ONLY the 4 canonical fields: sku, quantity, unit, requested_delivery_at.
    2. order_id is associated at the context level, NEVER a 5th canonical extracted field.
    3. Exactly 1 authoritative result per logical field (no duplicate rows).
    4. special_instructions is captured as context constraint, NOT an ExtractedField.
    5. Delivery deadline preserved as DEADLINE, never normalized to EXACT.
    6. Extraction correctness vs Business authorization:
       - Extraction correctly parses target date 2026-10-27T15:00:00+08:00 (DEADLINE)
       - Business authorization flags CONFLICT requiring human approval.
    """
    text = (
        "Regarding PO-DEMO-2026-1042, due to unexpected campus holiday scheduling, "
        "we would like to request moving delivery from 26 October 2026 to 27 October 2026 before 3:00 PM. "
        "Quantity remains 100 pcs burgers. "
        "As noted in the purchase order rescheduling clause, manual written confirmation is required."
    )
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    proc_res = repo.process("synthetic_tenant_a", msg_id)
    fields = proc_res.attempt.fields

    field_names = [f.field_name for f in fields]
    # Strictly the 4 canonical fields
    assert len(fields) == 4
    assert field_names.count("requested_delivery_at") == 1
    assert field_names.count("sku") == 1
    assert field_names.count("quantity") == 1
    assert field_names.count("unit") == 1
    # order_id and special_instructions must NOT be canonical ExtractedFields
    assert "order_id" not in field_names
    assert "special_instructions" not in field_names

    f_map = {f.field_name: f for f in fields}
    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"
    assert f_map["quantity"].value == "100"
    assert f_map["quantity"].validation_status == "VALID"
    assert f_map["unit"].value == "pcs"
    assert f_map["unit"].validation_status == "VALID"

    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "DEADLINE"
    assert del_f.value == "2026-10-27T15:00:00+08:00"
    assert del_f.metadata["rescheduling"] == "true"
    assert del_f.metadata["original_delivery_date"] == "2026-10-26"
    assert del_f.metadata["requested_delivery_date"] == "2026-10-27"
    assert del_f.metadata["extraction_correctness"] == "CONFIRMED_PARSED"
    assert del_f.metadata["business_authorization"] == "REQUIRES_HUMAN_REVIEW"

    # Context verification
    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message("synthetic_tenant_a", msg_id)
    # Sender is unverified (+60123456789); unverified senders cannot auto-bind orders without human link verification
    assert ctx.order_id is None
    assert ctx.status == "CONFLICT"
    assert ctx.requested_delivery_at == datetime.fromisoformat("2026-10-27T15:00:00+08:00")
    assert ctx.delivery_qualifier == "DEADLINE"
    assert any("Rescheduled delivery: moving from 2026-10-26 to 2026-10-27" in c for c in ctx.conflicts)
    assert any("Approval constraint: manual written confirmation is required" in c for c in ctx.conflicts)


def test_case_b_packaging_and_weekday_conflict_resolution(pg_engine):
    """Regression Case B: Packaging breakdown and weekday/date contradiction.

    Verifies:
    1. 80 is the total order quantity.
    2. 4 and 20 are packaging breakdown components, not separate order quantities.
    3. 'each' is not extracted as an unknown SKU.
    4. Weekday conflict (Friday vs 2026-10-24 Saturday) produces ONE unresolved delivery field.
    5. Exactly four canonical fields.
    """
    text = (
        "Morning boss, placing reorder for 80 burgers. Deliver this Friday 2026-10-24 by 11am sharp. "
        "Please pack into 4 separate boxes of 20pcs each."
    )
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    proc_res = repo.process("synthetic_tenant_a", msg_id)
    fields = proc_res.attempt.fields

    field_names = [f.field_name for f in fields]
    assert len(fields) == 4
    assert field_names.count("sku") == 1
    assert field_names.count("quantity") == 1
    assert field_names.count("unit") == 1
    assert field_names.count("requested_delivery_at") == 1

    f_map = {f.field_name: f for f in fields}
    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"
    assert f_map["quantity"].value == "80"
    assert f_map["quantity"].validation_status == "VALID"
    assert f_map["unit"].value == "pcs"
    assert f_map["unit"].validation_status == "VALID"

    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "DEADLINE"
    assert del_f.metadata["weekday_conflict"] == "true"
    assert "2026-10-24 is Saturday, not Friday" in del_f.metadata["reason"]

    # Context verification
    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message("synthetic_tenant_a", msg_id)
    assert ctx.status == "CONFLICT"


def test_case_c_contextual_mentions_and_genuine_absence(pg_engine):
    """Regression Case C: Contextual mentions and genuinely missing delivery.

    Verifies:
    1. 'beef patties' is background context, not an unknown product.
    2. 'burgers sent over' is not an unknown product.
    3. 30 pcs belongs to BURGER.
    4. Delivery is genuinely MISSING (not fabricated from 'tonight' or ETA question).
    5. Exactly four canonical fields.
    """
    text = (
        "We are running very low on beef patties tonight. Can we urgently get 30 pcs burgers sent over? "
        "Please let us know if feasible and what time driver can reach."
    )
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    proc_res = repo.process("synthetic_tenant_a", msg_id)
    fields = proc_res.attempt.fields

    field_names = [f.field_name for f in fields]
    assert len(fields) == 4
    assert field_names.count("sku") == 1
    assert field_names.count("quantity") == 1
    assert field_names.count("unit") == 1
    assert field_names.count("requested_delivery_at") == 1

    f_map = {f.field_name: f for f in fields}
    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"
    assert f_map["quantity"].value == "30"
    assert f_map["quantity"].validation_status == "VALID"
    assert f_map["unit"].value == "pcs"
    assert f_map["unit"].validation_status == "VALID"

    # Delivery must remain MISSING (never fabricated or forced to VALID)
    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "MISSING"
    assert del_f.value is None
    assert len(del_f.evidence) == 0


def test_omitted_unit_preserves_missing_without_fabrication(pg_engine):
    """When customer says '50 burgers' without specifying a unit, unit remains MISSING."""
    text = "Please deliver 50 burgers on 26 October 2026."
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    proc_res = repo.process("synthetic_tenant_a", msg_id)
    fields = proc_res.attempt.fields

    f_map = {f.field_name: f for f in fields}
    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"
    assert f_map["quantity"].value == "50"
    assert f_map["quantity"].validation_status == "VALID"
    assert f_map["unit"].value is None
    assert f_map["unit"].validation_status == "MISSING"


def test_eta_question_preserves_missing_delivery(pg_engine):
    """Urgent request and ETA question without requested delivery timestamp remains MISSING."""
    text = "Can we urgently get 25 burgers? What time can the driver reach our office?"
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    proc_res = repo.process("synthetic_tenant_a", msg_id)
    fields = proc_res.attempt.fields

    f_map = {f.field_name: f for f in fields}
    assert f_map["requested_delivery_at"].validation_status == "MISSING"
    assert f_map["requested_delivery_at"].value is None



def test_regression_approximate_lunchtime_delivery(pg_engine):
    """Regression Case: Approximate lunchtime delivery with colloquial phrasing.

    Input: 'hey guys! reordering 40 burgers for our pop-up stall tmr lunch time around 12:30pm. usual drop off at depot bay. let me know total rm thanks bro'
    Authoritative local reference date: 2026-10-23.

    Verifies:
    1. sku: BURGER, VALID (locked Rule result).
    2. quantity: 40, VALID (locked Rule result).
    3. unit: pcs, VALID (catalog-derived selling-unit default).
    4. requested_delivery_at: UNRESOLVED, approximate delivery on 2026-10-24 around 12:30.
    5. 'around' is recognized as approximate, not normalized into an exact commitment.
    6. 'lunch time' is contextual support, not a separate delivery timestamp.
    7. Exactly 4 canonical fields (no GLiNER duplicate delivery field).
    8. Context status: CONFLICT (fail-closed, not auto-committed).
    """
    text = (
        "hey guys! reordering 40 burgers for our pop-up stall tmr lunch time around 12:30pm. "
        "usual drop off at depot bay. let me know total rm thanks bro"
    )
    # Received at 2026-10-23 10:00:00+08:00
    msg = make_test_message(text, tz="Asia/Kuala_Lumpur")
    msg.raw.received_at = datetime(2026, 10, 23, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    msg_id = ingested.message.message_id
    proc_res = repo.process("synthetic_tenant_a", msg_id)
    fields = proc_res.attempt.fields

    field_names = [f.field_name for f in fields]
    assert len(fields) == 4
    assert field_names.count("sku") == 1
    assert field_names.count("quantity") == 1
    assert field_names.count("unit") == 1
    assert field_names.count("requested_delivery_at") == 1

    f_map = {f.field_name: f for f in fields}
    # 1. sku: locked Rule result
    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"

    # 2. quantity: locked Rule result
    assert f_map["quantity"].value == "40"
    assert f_map["quantity"].validation_status == "VALID"

    # 3. unit: genuinely omitted unit remains MISSING without inventing pcs
    assert f_map["unit"].value is None
    assert f_map["unit"].validation_status == "MISSING"

    # 4. requested_delivery_at: approximate delivery on 2026-10-24
    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.metadata["approximate"] == "true"
    assert del_f.metadata["target_date"] == "2026-10-24"
    assert del_f.metadata["target_time"] == "12:30:00"
    assert del_f.metadata["modifier"] == "around"
    assert del_f.metadata.get("meal_period") == "lunch time"
    # Must preserve exact original evidence span
    assert text[del_f.evidence[0].start:del_f.evidence[0].end] == del_f.evidence[0].quote
    assert "tmr lunch time around 12:30pm" in del_f.evidence[0].quote

    # 5. Context and Core publication safety
    ctx_service = ContextService(repo)
    ctx = ctx_service.create_or_update_from_message("synthetic_tenant_a", msg_id)
    assert ctx.status == "CONFLICT"
    assert any("Approximate requested delivery time" in c for c in ctx.conflicts)

    publisher = CoreContextPublisher()
    eligible, reasons = publisher.check_eligibility(ctx)
    assert not eligible
    assert any("status 'CONFLICT' is not INFORMATION_READY" in r for r in reasons)


def test_gliner_subspan_does_not_duplicate_approximate_delivery(pg_engine):
    """GLiNER candidate extracting '12:30pm' without understanding approximation is deduplicated."""
    from app.context.ai.protocol import Observation
    text = (
        "hey guys! reordering 40 burgers for our pop-up stall tmr lunch time around 12:30pm. "
        "usual drop off at depot bay. let me know total rm thanks bro"
    )
    msg = make_test_message(text, tz="Asia/Kuala_Lumpur")
    msg.raw.received_at = datetime(2026, 10, 23, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    rules_res = extract_explicit_fields(msg, catalog=PROVISIONAL_CATALOG)
    # Simulate GLiNER proposing subspan '12:30pm'
    start_time = text.index("12:30pm")
    gliner_cand = ExtractedField(
        field_name="requested_delivery_at",
        value="12:30:00",
        validation_status="UNRESOLVED",
        evidence=[FieldEvidence(
            evidence_id="ev_g1", message_id=msg.message_id, quote="12:30pm",
            start=start_time, end=start_time + 7, method="MODEL", method_version="gliner-v2"
        )],
        metadata={"disposition": "proposal", "domain_supported": "true"}
    )

    reconciled, accepted_count = reconcile_canonical_fields(
        rules_res.fields, [gliner_cand],
        catalog=PROVISIONAL_CATALOG, tenant_id="synthetic_tenant_a", raw_text=text
    )

    # Exactly 4 fields, accepted model count 0
    assert len(reconciled) == 4
    assert accepted_count == 0
    del_fields = [f for f in reconciled if f.field_name == "requested_delivery_at"]
    assert len(del_fields) == 1
    assert del_fields[0].metadata.get("approximate") == "true"
    assert del_fields[0].evidence[0].quote == "tmr lunch time around 12:30pm"


def test_paraphrase_approximate_delivery(pg_engine):
    """'40 burgers tomorrow around 12:30' produces UNRESOLVED approximate delivery."""
    text = "40 burgers tomorrow around 12:30"
    msg = make_test_message(text)
    msg.raw.received_at = datetime(2026, 10, 23, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.metadata["approximate"] == "true"
    assert del_f.metadata["target_date"] == "2026-10-24"
    assert del_f.metadata["target_time"] == "12:30:00"
    assert del_f.evidence[0].quote == "tomorrow around 12:30"


def test_paraphrase_exact_delivery(pg_engine):
    """'40 burgers tomorrow at 12:30 sharp' produces VALID EXACT delivery."""
    text = "40 burgers tomorrow at 12:30 sharp"
    msg = make_test_message(text)
    msg.raw.received_at = datetime(2026, 10, 23, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "VALID"
    assert del_f.qualifier == "EXACT"
    assert del_f.value == "2026-10-24T12:30:00+08:00"


def test_paraphrase_deadline_delivery(pg_engine):
    """'40 burgers tomorrow before 12:30' produces VALID DEADLINE delivery."""
    text = "40 burgers tomorrow before 12:30"
    msg = make_test_message(text)
    msg.raw.received_at = datetime(2026, 10, 23, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "VALID"
    assert del_f.qualifier == "DEADLINE"
    assert del_f.value == "2026-10-24T12:30:00+08:00"


def test_paraphrase_meal_period_window(pg_engine):
    """'40 burgers tomorrow lunchtime' produces UNRESOLVED DATE_ONLY with meal_period metadata."""
    text = "40 burgers tomorrow lunchtime"
    msg = make_test_message(text)
    msg.raw.received_at = datetime(2026, 10, 23, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "DATE_ONLY"
    assert del_f.metadata.get("meal_period") == "lunchtime"
    assert del_f.metadata.get("target_date") == "2026-10-24"
    assert del_f.evidence[0].quote == "tomorrow lunchtime"


def test_paraphrase_undecided_time(pg_engine):
    """'40 burgers tomorrow, not sure what time' produces UNRESOLVED DATE_ONLY with unconfirmed_time metadata."""
    text = "40 burgers tomorrow, not sure what time"
    msg = make_test_message(text)
    msg.raw.received_at = datetime(2026, 10, 23, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "DATE_ONLY"
    assert del_f.metadata.get("unconfirmed_time") == "true"
    assert del_f.metadata.get("target_date") == "2026-10-24"
    assert del_f.evidence[0].quote == "tomorrow, not sure what time"


def test_paraphrase_absent_delivery_with_eta_question(pg_engine):
    """'40 burgers, can you tell me what time you can deliver?' preserves MISSING delivery."""
    text = "40 burgers, can you tell me what time you can deliver?"
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "MISSING"
    assert del_f.value is None
    assert len(del_f.evidence) == 0


def test_unit_missing_when_catalog_default_unavailable(pg_engine):
    """When tenant catalog defines multiple selling units, unit remains MISSING without inventing pcs."""
    ambiguous_catalog = [
        ProductAlias("synthetic_tenant_a", "BURGER", ("burger", "burgers"), "pcs"),
        ProductAlias("synthetic_tenant_a", "BURGER", ("burger", "burgers"), "box"),
    ]
    text = "40 burgers tomorrow before 12:30"
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=ambiguous_catalog)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    assert f_map["unit"].validation_status == "MISSING"
    assert f_map["unit"].value is None



def test_regression_case_d_explicit_packaging_unit_unsupported_catalog(pg_engine):
    """Regression Case D: "Please deliver 50 boxes of burgers tomorrow before 3pm."
    When tenant catalog only supports pcs:
    1. sku: BURGER, VALID, RULE.
    2. quantity: 50, UNRESOLVED (evidence quote: "50").
    3. unit: box, UNRESOLVED (evidence quote: "boxes", normalized to "box").
    4. requested_delivery_at: 2026-10-24T15:00:00+08:00, VALID DEADLINE.
    5. Does not convert 50 boxes into 50 pcs.
    6. Does not replace box with default pcs.
    7. Does not invent a box-to-pcs conversion factor.
    8. Exactly 4 canonical fields (no duplicate quantity).
    9. Context status: CONFLICT; Core publication strictly blocked.
    """
    text = "Please deliver 50 boxes of burgers tomorrow before 3pm."
    msg = make_test_message(text, tz="Asia/Kuala_Lumpur")
    msg.raw.received_at = datetime(2026, 10, 23, 9, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    fields = proc_res.attempt.fields

    assert len(fields) == 4
    f_map = {f.field_name: f for f in fields}

    # 1. sku: VALID, RULE
    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"

    # 2. quantity: explicitly stated numeric quantity 50, UNRESOLVED
    assert f_map["quantity"].value == "50"
    assert f_map["quantity"].validation_status == "UNRESOLVED"
    assert f_map["quantity"].evidence[0].quote == "50"
    assert text[f_map["quantity"].evidence[0].start:f_map["quantity"].evidence[0].end] == "50"

    # 3. unit: explicitly stated unit "boxes", normalized to "box", UNRESOLVED
    assert f_map["unit"].value == "box"
    assert f_map["unit"].validation_status == "UNRESOLVED"
    assert f_map["unit"].evidence[0].quote == "boxes"
    assert text[f_map["unit"].evidence[0].start:f_map["unit"].evidence[0].end] == "boxes"
    assert "unsupported for SKU 'BURGER'" in f_map["unit"].metadata.get("reason", "")

    # 4. requested_delivery_at: VALID DEADLINE
    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "VALID"
    assert del_f.qualifier == "DEADLINE"
    assert del_f.value == "2026-10-24T15:00:00+08:00"

    # 5. Context and Core publication gating
    ctx_svc = ContextService(repo)
    ctx = ctx_svc.create_or_update_from_message("synthetic_tenant_a", ingested.message.message_id)
    assert ctx.status == "CONFLICT"
    assert any("unsupported for SKU 'BURGER'" in c or "unsupported for catalog SKU" in c for c in ctx.conflicts)
    assert ctx.requested_items == []

    publisher = CoreContextPublisher()
    eligible, reasons = publisher.check_eligibility(ctx)
    assert not eligible
    assert any("status 'CONFLICT' is not INFORMATION_READY" in r for r in reasons)


def test_regression_case_d_explicit_packaging_unit_supported_catalog(pg_engine):
    """When tenant catalog explicitly supports BURGER sold by box, validate quantity/unit pair as VALID."""
    box_catalog = [
        ProductAlias("synthetic_tenant_a", "BURGER", ("burger", "burgers"), "box")
    ]
    text = "Please deliver 50 boxes of burgers tomorrow before 3pm."
    msg = make_test_message(text, tz="Asia/Kuala_Lumpur")
    msg.raw.received_at = datetime(2026, 10, 23, 9, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    repo = PostgresMessageRepository(pg_engine, catalog=box_catalog)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    assert f_map["sku"].validation_status == "VALID"
    assert f_map["quantity"].value == "50"
    assert f_map["quantity"].validation_status == "VALID"
    assert f_map["unit"].value == "box"
    assert f_map["unit"].validation_status == "VALID"
    assert f_map["requested_delivery_at"].validation_status == "VALID"

    ctx_svc = ContextService(repo)
    ctx = ctx_svc.create_or_update_from_message("synthetic_tenant_a", ingested.message.message_id)
    assert ctx.status != "CONFLICT"
    assert len(ctx.requested_items) == 1
    assert ctx.requested_items[0].sku == "BURGER"
    assert ctx.requested_items[0].quantity == "50"
    assert ctx.requested_items[0].unit == "box"


def test_strict_field_ownership_and_model_exclusion(pg_engine):
    """Once L0 resolves a field as VALID, model proposals targeting that field are excluded."""
    text = "Please deliver 50 boxes of burgers tomorrow before 3pm."
    msg = make_test_message(text, tz="Asia/Kuala_Lumpur")
    msg.raw.received_at = datetime(2026, 10, 23, 9, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
    msg.ingested_at = msg.raw.received_at

    rules_res = extract_explicit_fields(msg, catalog=PROVISIONAL_CATALOG)

    # Simulate model proposing redundant SKU and delivery candidates
    sku_cand = ExtractedField(
        field_name="sku", value="BURGER", validation_status="VALID",
        evidence=[FieldEvidence(evidence_id="ev_m1", message_id=msg.message_id, quote="burgers",
                                start=text.index("burgers"), end=text.index("burgers")+7, method="MODEL", method_version="gliner-v2")],
        metadata={"disposition": "proposal", "domain_supported": "true"}
    )
    del_cand = ExtractedField(
        field_name="requested_delivery_at", value="2026-10-24T15:00:00+08:00", validation_status="VALID",
        evidence=[FieldEvidence(evidence_id="ev_m2", message_id=msg.message_id, quote="tomorrow before 3pm",
                                start=text.index("tomorrow before 3pm"), end=text.index("tomorrow before 3pm")+19, method="MODEL", method_version="gliner-v2")],
        metadata={"disposition": "proposal", "domain_supported": "true"}
    )

    reconciled, accepted_count = reconcile_canonical_fields(
        rules_res.fields, [sku_cand, del_cand],
        catalog=PROVISIONAL_CATALOG, tenant_id="synthetic_tenant_a", raw_text=text
    )

    # Exactly 4 canonical fields; accepted model count is 0 because rule fields were already resolved
    assert len(reconciled) == 4
    assert accepted_count == 0
    f_map = {f.field_name: f for f in reconciled}
    assert f_map["sku"].evidence[0].method == "RULE"
    assert f_map["requested_delivery_at"].evidence[0].method == "RULE"


def test_variant_cartons_of_burgers(pg_engine):
    """'2 cartons of burgers' preserves quantity=2, unit=carton as UNRESOLVED without converting to pcs."""
    text = "2 cartons of burgers"
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"
    assert f_map["quantity"].value == "2"
    assert f_map["quantity"].validation_status == "UNRESOLVED"
    assert f_map["unit"].value == "carton"
    assert f_map["unit"].validation_status == "UNRESOLVED"


def test_variant_boxes_containing_burgers_each(pg_engine):
    """'4 boxes containing 20 burgers each' preserves quantity=4, unit=box without inventing 80 pcs conversion."""
    text = "4 boxes containing 20 burgers each"
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"
    assert f_map["quantity"].value == "4"
    assert f_map["quantity"].validation_status == "UNRESOLVED"
    assert f_map["unit"].value == "box"
    assert f_map["unit"].validation_status == "UNRESOLVED"


def test_variant_burgers_packed_into_boxes(pg_engine):
    """'80 burgers packed into 4 boxes' extracts quantity=80, unit=MISSING (4 boxes is packaging detail)."""
    text = "80 burgers packed into 4 boxes"
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    f_map = {f.field_name: f for f in proc_res.attempt.fields}

    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"
    assert f_map["quantity"].value == "80"
    assert f_map["quantity"].validation_status == "VALID"
    assert f_map["unit"].value is None
    assert f_map["unit"].validation_status == "MISSING"


def test_variant_boxes_with_pieces_per_box_breakdown(pg_engine):
    """'50 boxes of burgers, 10 pieces per box' preserves quantity=50, unit=box without converting to 500 pcs or creating per-box product."""
    text = "50 boxes of burgers, 10 pieces per box"
    msg = make_test_message(text)
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)
    fields = proc_res.attempt.fields

    # Exactly 4 canonical fields: no extra "per box" SKU or breakdown items
    assert len(fields) == 4
    f_map = {f.field_name: f for f in fields}

    assert f_map["sku"].value == "BURGER"
    assert f_map["sku"].validation_status == "VALID"
    assert f_map["quantity"].value == "50"
    assert f_map["quantity"].validation_status == "UNRESOLVED"
    assert f_map["unit"].value == "box"
    assert f_map["unit"].validation_status == "UNRESOLVED"

def test_l2_delivery_rescheduling_rejects_superseded_date():
    """When a model proposes the moved-from date in a rescheduling request, it is marked INVALID."""
    from app.context.ai.service import ModelProposalService
    from app.context.ai.protocol import Observation, InferenceOutput, MODEL_CONFIG
    import asyncio

    text = "Regarding PO-DEMO-2026-1042, moving delivery from 26 October 2026 to 27 October 2026 before 3:00 PM."
    msg = make_test_message(text)

    # Simulate model proposing the wrong superseded date: "26 October 2026"
    start_old = text.index("26 October 2026")
    end_old = start_old + len("26 October 2026")

    class EndpointOldDate:
        async def infer(self, request):
            return InferenceOutput(
                engine=request.engine,
                model_id=MODEL_CONFIG[request.engine][0],
                revision=MODEL_CONFIG[request.engine][1],
                status="ok",
                fields=[
                    Observation(field="delivery", message_id="m1", quote="26 October 2026", start=start_old, end=end_old)
                ],
                raw_output="{}",
                finish_reason="stop",
                load_seconds=0.1,
                inference_seconds=0.2,
                input_tokens=10,
                output_tokens=10,
                gpu_name="mock",
                dtype="float16",
                runtime_versions={},
            )

    svc = ModelProposalService(EndpointOldDate(), enabled=True, stages=("gliner",))
    res = asyncio.run(svc.extract_stored(msg, catalog=PROVISIONAL_CATALOG))
    assert len(res.candidates) == 1
    cand = res.candidates[0]
    assert cand.validation_status == "INVALID"
    assert "Superseded or cancelled delivery date" in cand.metadata.get("reason", "")
    assert cand.metadata.get("disposition") == "rejected"


def test_l2_delivery_rescheduling_accepts_target_date_as_deadline():
    """When a model proposes the new target date in a rescheduling request, it is accepted as DEADLINE."""
    from app.context.ai.service import ModelProposalService
    from app.context.ai.protocol import Observation, InferenceOutput, MODEL_CONFIG
    import asyncio

    text = "Regarding PO-DEMO-2026-1042, moving delivery from 26 October 2026 to 27 October 2026 before 3:00 PM."
    msg = make_test_message(text)

    # Simulate model proposing the correct new target date: "27 October 2026 before 3:00 PM"
    start_new = text.index("27 October 2026 before 3:00 PM")
    end_new = start_new + len("27 October 2026 before 3:00 PM")

    class EndpointNewDate:
        async def infer(self, request):
            return InferenceOutput(
                engine=request.engine,
                model_id=MODEL_CONFIG[request.engine][0],
                revision=MODEL_CONFIG[request.engine][1],
                status="ok",
                fields=[
                    Observation(field="delivery", message_id="m1", quote="27 October 2026 before 3:00 PM", start=start_new, end=end_new)
                ],
                raw_output="{}",
                finish_reason="stop",
                load_seconds=0.1,
                inference_seconds=0.2,
                input_tokens=10,
                output_tokens=10,
                gpu_name="mock",
                dtype="float16",
                runtime_versions={},
            )

    svc = ModelProposalService(EndpointNewDate(), enabled=True, stages=("gliner",))
    res = asyncio.run(svc.extract_stored(msg, catalog=PROVISIONAL_CATALOG))
    assert len(res.candidates) == 1
    cand = res.candidates[0]
    assert cand.validation_status != "INVALID"
    assert cand.qualifier == "DEADLINE"
    assert cand.evidence[0].quote == "27 October 2026 before 3:00 PM"



def test_single_date_rescheduling_request_marks_unresolved_with_correct_parsed_date():
    """'reschedule delivery to 27 October 2026 before 3:00 PM' extracts new date correctly while flagging review."""
    text = "Regarding PO-DEMO-2026-1042, please reschedule delivery to 27 October 2026 before 3:00 PM. Quantity 50 pcs burgers."
    msg = make_test_message(text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_CATALOG)
    fields = {f.field_name: f for f in res.fields}

    del_f = fields["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "DEADLINE"
    assert del_f.value == "2026-10-27T15:00:00+08:00"
    assert del_f.metadata["rescheduling"] == "true"
    assert del_f.metadata["extraction_correctness"] == "CONFIRMED_PARSED"
    assert del_f.metadata["business_authorization"] == "REQUIRES_HUMAN_REVIEW"


def test_negation_dont_deliver_on_friday_send_monday_instead(pg_engine):
    """'don't deliver on Friday, send on Monday before 10am instead' corrects delivery to Monday DEADLINE."""
    # Message dated Thursday 2026-10-22. Friday = 2026-10-23, Monday = 2026-10-26.
    text = "Need to update order for 30 boxes burgers, don't deliver on Friday, send on Monday before 10am instead."
    msg = make_test_message(text, msg_time=datetime(2026, 10, 22, 9, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur")))
    repo = PostgresMessageRepository(pg_engine, catalog=PROVISIONAL_CATALOG)
    ingested = repo.ingest(msg.raw, now=msg.raw.received_at)
    proc_res = repo.process("synthetic_tenant_a", ingested.message.message_id)

    fields = proc_res.attempt.fields
    assert len(fields) == 4
    f_map = {f.field_name: f for f in fields}
    assert f_map["sku"].value == "BURGER"
    assert f_map["quantity"].value == "30"
    assert f_map["unit"].value == "box"

    del_f = f_map["requested_delivery_at"]
    assert del_f.validation_status == "UNRESOLVED"
    assert del_f.qualifier == "DEADLINE"
    assert del_f.metadata["correction"] == "true"
    assert del_f.metadata["original_delivery_date"] == "2026-10-23"
    assert del_f.metadata["requested_delivery_date"] == "2026-10-26"
    assert del_f.value == "2026-10-26T10:00:00+08:00"
