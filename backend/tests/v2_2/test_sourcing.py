"""Synthetic trusted-reader shapes test mechanics, not external authenticity."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.sourcing.dossier import build_dossier
from app.sourcing.history import DeliveryFact, HistorySnapshot, analyze_history
from app.sourcing.ports import load_authenticated_history, load_authenticated_quote
from app.sourcing.recovery_handoff import RecoveryContext, prepare_alternative_supply
from app.sourcing.replies import NormalizedReply, consolidate_replies
from app.sourcing.rfq import RFQRequirement, prepare_rfq
from app.sourcing.selection import SelectionRequest, preview_selection
from app.suppliers.comparison import CategorySpec, SupplierOffer, SupplierRequirement

NOW = datetime(2026, 10, 24, 8, tzinfo=UTC)


def schema():
    return CategorySpec(
        tenant_id="t",
        category_id="container",
        version=1,
        authority="SME_CONFIG",
        approval_ref="approval-1",
        evidence_refs=("catalog-1",),
        hard_fields=(
            {"name": "material", "kind": "TEXT"},
            {"name": "food_safe", "kind": "BOOLEAN"},
        ),
    )


def requirement():
    return SupplierRequirement(
        tenant_id="t",
        category_id="container",
        spec_version=1,
        properties=({"name": "material", "value": "PP"}, {"name": "food_safe", "value": True}),
        quantity="100",
        unit="pcs",
        needed_by=NOW + timedelta(days=3),
        currency="MYR",
    )


def offer(supplier="b", **updates):
    value = {
        "tenant_id": "t",
        "supplier_id": supplier,
        "quote_id": f"q-{supplier}",
        "quote_version": 1,
        "category_id": "container",
        "spec_version": 1,
        "properties": (
            {"name": "material", "value": "PP", "evidence_refs": ("material",)},
            {"name": "food_safe", "value": True, "evidence_refs": ("safety",)},
        ),
        "evidence_refs": (f"message-{supplier}",),
        "price_per_pack": "30",
        "units_per_pack": "10",
        "unit": "pcs",
        "moq": "10",
        "currency": "MYR",
        "pack_evidence_refs": ("pack",),
        "availability": "VERIFIED",
        "available_quantity": "200",
        "availability_evidence_refs": ("available",),
        "verified_property_names": frozenset(("material", "food_safe")),
        "verification_evidence_refs": ("technical",),
        "quoted_arrival": NOW + timedelta(days=2),
        "arrival_evidence_refs": ("arrival",),
        "valid_until": NOW + timedelta(days=1),
    }
    return SupplierOffer.model_validate(value | updates)


def fact(po="po-1", **updates):
    value = {
        "tenant_id": "t",
        "supplier_id": "b",
        "purchase_order_id": po,
        "purchase_order_version": 1,
        "quote_id": "q-b",
        "quote_version": 1,
        "sku": "container",
        "unit": "pcs",
        "promised_quantity": "100",
        "promised_at": NOW - timedelta(days=2),
        "promise_baseline_ref": "approved-po-1",
        "received_quantity": "100",
        "received_at": NOW - timedelta(days=3),
        "receipt_id": f"receipt-{po}",
        "quality_accepted": True,
        "original_evidence_refs": ("po-source",),
        "receipt_evidence_refs": ("goods-receipt",),
        "source_version": "v1",
        "recorded_at": NOW - timedelta(days=1),
        "trust_tier": "VERIFIED",
        "integration_mode": "SYNTHETIC",
    }
    return DeliveryFact.model_validate(value | updates)


def history(*facts, **updates):
    value = {
        "tenant_id": "t",
        "supplier_id": "b",
        "facts": facts,
        "source_watermark": "snapshot-1",
        "complete": True,
        "consistent_read": True,
        "business_timezone": "Asia/Singapore",
        "observed_at": NOW,
        "promise_policy": "ORIGINAL_APPROVED",
        "integration_mode": "SYNTHETIC",
    }
    return HistorySnapshot.model_validate(value | updates)


def rfq_request(**updates):
    value = {
        "tenant_id": "t",
        "sourcing_case_id": "case-1",
        "requirement_id": "req-1",
        "requirement_version": 1,
        "category_id": "container",
        "spec_version": 1,
        "sku": "container",
        "quantity": "100",
        "unit": "pcs",
        "hard_properties": (
            {"name": "material", "value": "PP", "evidence_refs": ("requirement-material",)},
            {"name": "food_safe", "value": True, "evidence_refs": ("requirement-safe",)},
        ),
        "needed_by": NOW + timedelta(days=3),
        "recipient_supplier_ids": ("a", "b", "c"),
        "evidence_refs": ("request-source",),
        "business_timezone": "Asia/Singapore",
        "source_context_version": "ctx-1",
        "template_id": "rfq-template",
        "template_version": 1,
        "template_approval_ref": "template-approval-1",
    }
    return RFQRequirement.model_validate(value | updates)


def test_three_supplier_sourcing_flow_has_no_operational_side_effects():
    a = offer(
        "a",
        price_per_pack="15",
        units_per_pack="5",
        availability="CLAIMED",
        availability_evidence_refs=(),
        verification_evidence_refs=(),
        properties=({"name": "material", "value": "PP", "evidence_refs": ("a-mat",)},),
    )
    b = offer("b")
    c = offer(
        "c",
        properties=(
            {"name": "material", "value": "PET", "evidence_refs": ("c-mat",)},
            {"name": "food_safe", "value": True, "evidence_refs": ("c-safe",)},
        ),
        availability="CLAIMED",
        availability_evidence_refs=(),
        quoted_arrival=NOW + timedelta(days=1),
    )
    metrics = analyze_history(history(fact(), fact("po-2"), fact("po-3")))
    assert metrics.on_time_rate == Decimal(1)
    assert metrics.eligible_denominator == 3
    assert "SYNTHETIC_EVIDENCE_NOT_LIVE_AUTHORITY" in metrics.limitations
    dossier = build_dossier(schema(), requirement(), (a, b, c), (metrics,), now=NOW)
    assert [entry.canonical_status for entry in dossier] == ["UNKNOWN", "MATCHES", "INCOMPATIBLE"]
    assert dossier[0].normalized_unit_cost == Decimal(3)  # price alone is not substitutability
    assert dossier[0].cost_comparable_for_selection is False
    assert dossier[1].cost_comparable_for_selection is True
    assert dossier[1].historical_on_time_rate == Decimal(1)
    request = rfq_request()
    draft = prepare_rfq(request, schema(), now=NOW, verified_recipients=frozenset(("a", "b", "c")))
    assert draft.readiness == "READY_FOR_P4_REVIEW"
    assert all(
        e.canonical_content_hash == draft.canonical_content_hash and e.dispatch_status == "NOT_SENT"
        for e in draft.envelopes
    )
    assert (
        prepare_rfq(
            request, schema(), now=NOW, verified_recipients=frozenset(("a", "b", "c"))
        ).draft_id
        == draft.draft_id
    )
    replies = consolidate_replies(
        request,
        draft,
        (
            NormalizedReply(
                tenant_id="t",
                sourcing_case_id="case-1",
                requirement_version=1,
                supplier_id="b",
                supplier_identity_verified=True,
                identity_evidence_refs=("identity-b",),
                message_id="message-b",
                source_refs=("message-b",),
                quote_id="q-b",
                quote_version=1,
                offer=b,
                received_at=NOW,
            ),
        ),
        now=NOW,
    )
    assert replies[0].readiness == "COMPLETE_FOR_COMPARISON"
    revised_a = offer(
        "a",
        quote_version=2,
        properties=(
            {"name": "material", "value": "PP", "evidence_refs": ("a-v2-material",)},
            {"name": "food_safe", "value": True, "evidence_refs": ("a-v2-safety",)},
        ),
        availability="CLAIMED",
        availability_evidence_refs=(),
        verification_evidence_refs=(),
    )
    revised_reply = NormalizedReply(
        tenant_id="t",
        sourcing_case_id="case-1",
        requirement_version=1,
        supplier_id="a",
        supplier_identity_verified=True,
        identity_evidence_refs=("identity-a",),
        message_id="message-a-v2",
        source_refs=("message-a-v2",),
        quote_id="q-a",
        quote_version=2,
        offer=revised_a,
        received_at=NOW,
    )
    assert consolidate_replies(request, draft, (revised_reply,), now=NOW)[0].readiness == "PARTIAL"
    assert (
        build_dossier(schema(), requirement(), (revised_a,), (), now=NOW)[0].canonical_status
        == "CONDITIONAL"
    )
    selection = preview_selection(
        SelectionRequest(
            tenant_id="t",
            sourcing_case_id="case-1",
            requirement_id="req-1",
            requirement_version=1,
            supplier_id="b",
            quote_id="q-b",
            quote_version=1,
            spec_version=1,
            reason_draft="Fits specified container and arrival window",
            source_context_version="ctx-1",
            current_source_context_version="ctx-1",
        ),
        dossier[1],
    )
    assert selection.advisory_status == "PREVIEW_ONLY"
    handoff = prepare_alternative_supply(
        RecoveryContext(
            tenant_id="t",
            commitment_id="commitment-1",
            commitment_version=2,
            sourcing_case_id="case-1",
            quantity="100",
            unit="pcs",
            requirement_deadline=NOW + timedelta(days=3),
            current_source_version="ctx-1",
            evidence_refs=("risk-event",),
        ),
        selection,
        dossier[1],
        now=NOW,
    )
    assert handoff.status == "CONDITIONAL"
    assert handoff.received_inventory is False and handoff.p2_feasibility_override is False
    assert "PURCHASE_AUTHORITY" in handoff.missing_prerequisites


@pytest.mark.parametrize(
    "updates",
    [
        {"trust_tier": "REPORTED", "receipt_evidence_refs": ()},
        {"received_quantity": None, "received_at": None, "receipt_id": None},
        {"original_evidence_refs": ()},
    ],
)
def test_unverified_or_missing_history_never_becomes_success(updates):
    result = analyze_history(history(fact(**updates)))
    assert result.on_time_rate is None and result.eligible_denominator == 0
    assert result.missing_evidence == 1


def test_history_late_partial_quality_and_incomplete_page():
    f = fact(received_quantity="90", received_at=NOW, quality_accepted=False)
    result = analyze_history(history(f))
    assert result.known_late == 1 and result.known_partial == 1 and result.quality_exceptions == 1
    assert result.on_time_rate == Decimal(0)
    partial = analyze_history(history(f, complete=False))
    assert partial.on_time_rate is None and partial.evidence_coverage is None


@pytest.mark.parametrize(
    "facts,changes",
    [
        ((fact(tenant_id="other"),), {}),
        ((fact(supplier_id="other"),), {}),
        ((fact(), fact(received_quantity="50")), {}),
        ((fact(), fact("po-2", receipt_id="receipt-po-1")), {}),
        ((fact(received_at=NOW + timedelta(days=1)),), {}),
        ((fact(),), {"consistent_read": False}),
    ],
)
def test_history_rejects_cross_scope_conflict_future_and_inconsistent_reads(facts, changes):
    with pytest.raises(ValueError):
        analyze_history(history(*facts, **changes))


def test_history_idempotent_replay_and_versioned_correction():
    original = fact()
    correction = fact(
        purchase_order_version=2,
        source_version="v2",
        supersedes_source_version="v1",
        promised_at=NOW - timedelta(days=4),
        promise_baseline_ref="approved-rebase-2",
    )
    assert analyze_history(history(original, original)).eligible_denominator == 1
    assert (
        analyze_history(history(correction, original, promise_policy="APPROVED_REBASE")).known_late
        == 1
    )
    with pytest.raises(ValueError):
        analyze_history(history(correction))
    assert analyze_history(history(original, promise_policy="UNAPPROVED")).on_time_rate is None


def test_dossier_and_selection_fail_closed_on_scope_and_versions():
    metric = analyze_history(history(fact()))
    with pytest.raises(ValueError):
        build_dossier(
            schema(),
            requirement(),
            (offer(),),
            (metric.model_copy(update={"tenant_id": "other"}),),
            now=NOW,
        )
    entry = build_dossier(schema(), requirement(), (offer(),), (), now=NOW)[0]
    with pytest.raises(ValueError):
        preview_selection(
            SelectionRequest(
                tenant_id="other",
                sourcing_case_id="case-1",
                requirement_id="req-1",
                requirement_version=1,
                supplier_id="b",
                quote_id="q-b",
                quote_version=1,
                spec_version=1,
                reason_draft="reason",
                source_context_version="v1",
                current_source_context_version="v1",
            ),
            entry,
        )
    assert entry.historical_on_time_rate is None


def test_rfq_missing_fields_changes_hash_and_never_sends():
    request = rfq_request(hard_properties=(), template_id=None, template_version=None)
    draft = prepare_rfq(request, schema(), now=NOW)
    assert draft.readiness == "NEEDS_REQUIREMENT_REVIEW"
    assert {"material", "food_safe", "APPROVED_RFQ_TEMPLATE"} <= set(draft.missing_information)
    assert draft.dispatch_status == "NOT_SENT"
    assert (
        draft.draft_id
        != prepare_rfq(rfq_request(requirement_version=2), schema(), now=NOW).draft_id
    )
    full = prepare_rfq(rfq_request(), schema(), now=NOW)
    fewer_recipients = prepare_rfq(
        rfq_request(recipient_supplier_ids=("a", "b")), schema(), now=NOW
    )
    assert fewer_recipients.draft_id != full.draft_id
    assert fewer_recipients.canonical_content_hash == full.canonical_content_hash
    with pytest.raises(ValidationError):
        rfq_request(recipient_supplier_ids=("a", "a"))
    with pytest.raises(ValidationError):
        rfq_request(business_timezone="Mars/Olympus")


def test_reply_partial_duplicate_conflict_and_wrong_identity():
    request = rfq_request()
    draft = prepare_rfq(request, schema(), now=NOW)
    partial_offer = offer(
        "a",
        properties=(),
        price_per_pack=None,
        units_per_pack=None,
        availability="CLAIMED",
        availability_evidence_refs=(),
    )
    reply = NormalizedReply(
        tenant_id="t",
        sourcing_case_id="case-1",
        requirement_version=1,
        supplier_id="a",
        supplier_identity_verified=True,
        identity_evidence_refs=("identity-a",),
        message_id="m1",
        source_refs=("m1",),
        quote_id="q-a",
        quote_version=1,
        offer=partial_offer,
        received_at=NOW,
    )
    assert consolidate_replies(request, draft, (reply, reply), now=NOW)[0].readiness == "PARTIAL"
    changed = reply.model_copy(
        update={"message_id": "m2", "offer": partial_offer.model_copy(update={"moq": Decimal(20)})}
    )
    assert consolidate_replies(request, draft, (reply, changed), now=NOW)[0].readiness == "CONFLICT"
    with pytest.raises(ValueError):
        consolidate_replies(
            request,
            draft,
            (reply.model_copy(update={"supplier_identity_verified": False}),),
            now=NOW,
        )
    with pytest.raises(ValueError):
        consolidate_replies(
            request, draft, (reply.model_copy(update={"requirement_version": 2}),), now=NOW
        )


def test_trusted_reader_boundary_checks_identity_versions_and_evidence():
    class HistoryReader:
        def read_history(self, **_kwargs):
            return history(fact())

    class QuoteReader:
        def read_quote(self, **_kwargs):
            return offer()

    class IdentityReader:
        def verified_supplier(self, **_kwargs):
            return True

    class EvidenceReader:
        def authenticated_refs(self, **kwargs):
            return frozenset(kwargs["refs"])

    assert (
        load_authenticated_history(
            tenant_id="t",
            supplier_id="b",
            history_reader=HistoryReader(),
            evidence_reader=EvidenceReader(),
            identity_reader=IdentityReader(),
        ).source_watermark
        == "snapshot-1"
    )
    assert (
        load_authenticated_quote(
            tenant_id="t",
            supplier_id="b",
            quote_id="q-b",
            quote_version=1,
            source_watermark="snapshot-1",
            quote_reader=QuoteReader(),
            evidence_reader=EvidenceReader(),
            identity_reader=IdentityReader(),
        ).quote_id
        == "q-b"
    )

    class DenyingEvidence:
        def authenticated_refs(self, **_kwargs):
            return frozenset()

    with pytest.raises(ValueError):
        load_authenticated_history(
            tenant_id="t",
            supplier_id="b",
            history_reader=HistoryReader(),
            evidence_reader=DenyingEvidence(),
            identity_reader=IdentityReader(),
        )
    with pytest.raises(ValueError):
        load_authenticated_history(
            tenant_id="t",
            supplier_id="b",
            expected_source_watermark="snapshot-2",
            history_reader=HistoryReader(),
            evidence_reader=EvidenceReader(),
            identity_reader=IdentityReader(),
        )
    with pytest.raises(ValueError):
        load_authenticated_quote(
            tenant_id="t",
            supplier_id="b",
            quote_id="q-b",
            quote_version=2,
            source_watermark="snapshot-1",
            quote_reader=QuoteReader(),
            evidence_reader=EvidenceReader(),
            identity_reader=IdentityReader(),
        )


def test_recovery_handoff_rejects_stale_selected_context():
    entry = build_dossier(schema(), requirement(), (offer(),), (), now=NOW)[0]
    selection = preview_selection(
        SelectionRequest(
            tenant_id="t",
            sourcing_case_id="case-1",
            requirement_id="req-1",
            requirement_version=1,
            supplier_id="b",
            quote_id="q-b",
            quote_version=1,
            spec_version=1,
            reason_draft="Fit",
            source_context_version="v1",
            current_source_context_version="v1",
        ),
        entry,
    )
    context = RecoveryContext(
        tenant_id="t",
        commitment_id="commitment-1",
        commitment_version=1,
        sourcing_case_id="case-1",
        quantity="100",
        unit="pcs",
        requirement_deadline=NOW + timedelta(days=3),
        current_source_version="v2",
        evidence_refs=("risk",),
    )
    with pytest.raises(ValueError):
        prepare_alternative_supply(context, selection, entry, now=NOW)
