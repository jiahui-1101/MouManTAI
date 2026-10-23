from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

TENANT = "tenant_a"
CUSTOMER = "customer_a"
CONTEXT = "context_a"
MESSAGE = "message_a"
NOW = datetime(2026, 10, 24, 8, tzinfo=UTC)


def make_context(**updates):
    from app.context.order_context_schemas import OrderContextRecord

    data = {
        "context_id": CONTEXT,
        "tenant_id": TENANT,
        "order_id": None,
        "customer_id": CUSTOMER,
        "customer_identity_status": "LINK_VERIFIED",
        "status": "INFORMATION_READY",
        "context_version": 3,
        "requested_items": [{"sku": "CUP", "quantity": "100.00", "unit": "pcs"}],
        "requested_delivery_at": "2026-10-25T11:00:00+08:00",
        "delivery_qualifier": "DEADLINE",
        "special_instructions": "Food safe packaging",
        "source_message_ids": [MESSAGE],
        "field_evidence": {
            "sku": [{"evidence_ref": "ev_sku", "message_id": MESSAGE, "method": "RULE"}],
            "quantity": [{"evidence_ref": "ev_quantity", "message_id": MESSAGE, "method": "RULE"}],
            "unit": [{"evidence_ref": "ev_unit", "message_id": MESSAGE, "method": "RULE"}],
            "requested_delivery_at": [
                {"evidence_ref": "ev_deadline", "message_id": MESSAGE, "method": "HUMAN"}
            ],
            "special_instructions": [
                {"evidence_ref": "ev_instructions", "message_id": MESSAGE, "method": "HUMAN"}
            ],
        },
        "missing_fields": [],
        "conflicts": [],
        "last_reviewed_by": "reviewer_a",
        "last_reviewed_role": "MANAGER",
        "last_reviewed_at": "2026-10-24T08:00:00Z",
        "core_commitment_id": None,
        "published_to_core_at": None,
        "created_at": "2026-10-24T07:00:00Z",
        "updated_at": "2026-10-24T08:00:00Z",
    }
    return OrderContextRecord.model_validate(data | updates)


def make_current_version(context=None, **updates):
    from app.context.order_context_schemas import OrderContextVersionRecord

    context = context or make_context()
    return OrderContextVersionRecord.model_validate(
        {
            "version_id": "context_version_3",
            "context_id": context.context_id,
            "tenant_id": context.tenant_id,
            "context_version": context.context_version,
            "snapshot": context.model_dump(mode="json"),
            "change_type": "HUMAN_ACCEPT",
            "actor_id": "reviewer_a",
            "actor_role": "MANAGER",
            "reason": "Reviewed request fields",
            "created_at": "2026-10-24T08:00:00Z",
        }
        | updates
    )


def make_context_review(context=None, **updates):
    from app.context.order_context_schemas import ContextReviewRecord

    context = context or make_context()
    return ContextReviewRecord.model_validate(
        {
            "review_id": "review_a",
            "tenant_id": context.tenant_id,
            "context_id": context.context_id,
            "context_version_before": context.context_version - 1,
            "context_version_after": context.context_version,
            "action": "EDIT_FIELD",
            "actor_id": context.last_reviewed_by,
            "actor_role": context.last_reviewed_role,
            "field_changes": {},
            "note": "Reviewed the current order context",
            "created_at": context.last_reviewed_at.isoformat(),
        }
        | updates
    )


def make_source_message(**updates):
    from app.context.ingestion_schemas import StoredMessage
    from app.context.schemas import RawMessageEnvelope

    raw = RawMessageEnvelope.model_validate(
        {
            "tenant_id": TENANT,
            "channel": "WHATSAPP",
            "provider_message_id": "provider_message_a",
            "sender_identity_id": "sender_a",
            "sender_alias": "Buyer A",
            "received_at": "2026-10-24T07:30:00Z",
            "text": "Please deliver 100 cups by 11am tomorrow",
            "adapter_mode": "REAL",
        }
    )
    return StoredMessage.model_validate(
        {
            "message_id": MESSAGE,
            "raw": raw.model_dump(mode="json"),
            "synthetic_provider": None,
            "provider": "WHATSAPP_CLOUD_API",
            "source_label": "WhatsApp",
            "content_sha256": "a" * 64,
            "processing_status": "PROCESSED",
            "extractor_version": "p1-test",
            "ingested_at": "2026-10-24T07:30:01Z",
            "updated_at": "2026-10-24T07:30:01Z",
        }
        | updates
    )


def make_association(**updates):
    from app.context.association_schemas import MessageAssociationRecord

    return MessageAssociationRecord.model_validate(
        {
            "association_id": "association_a",
            "tenant_id": TENANT,
            "message_id": MESSAGE,
            "status": "LINK_VERIFIED",
            "verified_customer": {
                "customer_id": CUSTOMER,
                "tenant_id": TENANT,
                "legal_name": "Buyer A Ltd",
                "display_name": "Buyer A",
            },
            "verified_order": None,
            "candidates": [],
            "conflicts": [],
            "last_decision": None,
            "version": 2,
            "updated_at": "2026-10-24T08:00:00Z",
        }
        | updates
    )


def make_commercial(**updates):
    from app.orders.context_mapping import OrderCommercialEvidence

    return OrderCommercialEvidence.model_validate(
        {
            "tenant_id": TENANT,
            "context_id": CONTEXT,
            "context_version": 3,
            "customer_id": CUSTOMER,
            "order_request_id": "order_request_a",
            "terms_revision": 1,
            "items": [
                {
                    "sku": "CUP",
                    "variant": "500ml",
                    "quantity": "100.00",
                    "unit": "pcs",
                    "unit_price": "2.00",
                }
            ],
            "fulfilment_method": "DELIVERY",
            "location_ref": "address_version_4",
            "window_start": "2026-10-25T10:00:00+08:00",
            "window_end": "2026-10-25T11:00:00+08:00",
            "business_timezone": "Asia/Kuala_Lumpur",
            "currency": "MYR",
            "fees": "5.00",
            "tax": "0",
            "discount": "0",
            "total": "205.00",
            "price_source": {
                "source_type": "APPROVED_CATALOG",
                "source_id": "catalog_a",
                "source_version": "catalog_v3",
                "policy_ref": "pricing_policy_v3",
                "disclosed_at": "2026-10-24T07:40:00Z",
                "evidence_refs": ["ev_disclosure"],
            },
            "price_source_authority": {
                "tenant_id": TENANT,
                "customer_id": CUSTOMER,
                "source_id": "catalog_a",
                "source_version": "catalog_v3",
                "status": "VERIFIED",
                "authority_ref": "catalog_record_a_v3",
            },
            "price_disclosure_evidence": ["ev_disclosure"],
            "binding_policy_ref": "policy_v3",
        }
        | updates
    )


def map_context(*, context=None, current_version=None, source_messages=None,
                associations=None, reviews=None, commercial=None, existing_core_terms=None):
    from app.orders.context_mapping import map_order_context

    context = context or make_context()
    return map_order_context(
        context,
        current_version=current_version if current_version is not None else make_current_version(context),
        source_messages=source_messages if source_messages is not None else [make_source_message()],
        associations=associations if associations is not None else [make_association()],
        reviews=reviews if reviews is not None else [make_context_review(context)],
        commercial_terms=commercial if commercial is not None else make_commercial(),
        existing_core_terms=existing_core_terms,
    )


def test_complete_mapping_uses_canonical_terms_and_preserves_evidence_without_claiming_assent():
    from app.orders.terms import OrderTerms

    context = make_context()
    result = map_context(context=context)

    assert result.readiness_status == "READY_FOR_VALIDATION"
    assert isinstance(result.canonical_terms, OrderTerms)
    assert result.canonical_terms.items[0].quantity == Decimal("100.00")
    assert result.canonical_terms.items[0].variant == "500ml"
    assert result.canonical_terms.window_end == context.requested_delivery_at
    assert result.canonical_terms.special_conditions == (context.special_instructions,)
    assert result.canonical_terms.source_message_ids == (MESSAGE,)
    assert {"ev_sku", "ev_quantity", "ev_unit", "ev_deadline", "ev_disclosure"}.issubset(
        result.source_evidence_refs
    )
    assert result.terms_hash == result.canonical_terms.terms_hash
    assert result.agreement_basis == "UNKNOWN"
    assert result.customer_assent_evidence == ()
    assert result.proposal_id is None and result.proposal_version is None
    assert result.order_request_id == "order_request_a"


def test_missing_order_request_id_is_incomplete_and_never_replaced_with_context_id():
    result = map_context(commercial=make_commercial(order_request_id=None))

    assert result.readiness_status == "INCOMPLETE"
    assert result.canonical_terms is None
    assert "order_request_id" in result.missing_fields
    assert result.source_context_id == CONTEXT


@pytest.mark.parametrize(
    "updates,expected_missing",
    [
        ({"price_source": None, "price_source_authority": None}, "price_source"),
        ({"price_disclosure_evidence": []}, "price_disclosure_evidence"),
        ({"currency": None}, "currency"),
        ({"fees": None}, "fees"),
        ({"tax": None}, "tax"),
        ({"discount": None}, "discount"),
        ({"total": None}, "total"),
        ({"location_ref": None}, "location_ref"),
        ({"window_start": None}, "window_start"),
        ({"window_end": None}, "window_end"),
        ({"business_timezone": None}, "business_timezone"),
        ({"fulfilment_method": None}, "fulfilment_method"),
        ({"terms_revision": None}, "terms_revision"),
        ({"binding_policy_ref": None}, "binding_policy_ref"),
    ],
)
def test_missing_binding_commercial_data_fails_closed(updates, expected_missing):
    result = map_context(commercial=make_commercial(**updates))

    assert result.readiness_status == "INCOMPLETE"
    assert result.canonical_terms is None
    assert expected_missing in result.missing_fields


def test_unverified_price_source_and_missing_disclosure_do_not_create_canonical_terms():
    unverified = make_commercial(
        price_source_authority={
            "tenant_id": TENANT,
            "customer_id": CUSTOMER,
            "source_id": "catalog_a",
            "source_version": "catalog_v3",
            "status": "UNVERIFIED",
            "authority_ref": None,
        }
    )
    result = map_context(commercial=unverified)
    assert result.readiness_status == "PRICE_SOURCE_UNVERIFIED"
    assert result.canonical_terms is None
    assert "PRICE_SOURCE_UNVERIFIED" in result.validation_reason_codes

    no_disclosure = make_commercial(price_disclosure_evidence=[])
    result = map_context(commercial=no_disclosure)
    assert result.readiness_status == "INCOMPLETE"
    assert "price_disclosure_evidence" in result.missing_fields


def test_identity_requires_verified_context_and_every_source_message_association():
    unverified_context = make_context(customer_identity_status="UNVERIFIED")
    result = map_context(context=unverified_context)
    assert result.readiness_status == "IDENTITY_UNVERIFIED"
    assert result.canonical_terms is None

    unverified_assoc = make_association(status="LINK_CANDIDATE")
    result = map_context(associations=[unverified_assoc])
    assert result.readiness_status == "REVIEW_REQUIRED"
    assert "ASSOCIATION_UNRESOLVED" in result.validation_reason_codes
    assert result.customer_id == CUSTOMER

    unknown_assoc = make_association(status="UNVERIFIED", verified_customer=None)
    result = map_context(associations=[unknown_assoc])
    assert result.readiness_status == "IDENTITY_UNVERIFIED"


def test_context_without_current_human_review_is_not_mapped_as_trusted():
    result = map_context(reviews=[])
    assert result.readiness_status == "REVIEW_REQUIRED"
    assert "CURRENT_CONTEXT_REVIEW_REQUIRED" in result.validation_reason_codes
    assert result.canonical_terms is None


def test_stale_or_inconsistent_context_version_fails_closed():
    context = make_context()
    stale = make_current_version(context, context_version=2)
    result = map_context(context=context, current_version=stale)
    assert result.readiness_status == "STALE_SOURCE"
    assert result.canonical_terms is None

    mismatched_snapshot = make_current_version(context)
    snapshot = deepcopy(mismatched_snapshot.snapshot)
    snapshot["requested_items"][0]["quantity"] = "999"
    stale_snapshot = mismatched_snapshot.model_copy(update={"snapshot": snapshot})
    result = map_context(context=context, current_version=stale_snapshot)
    assert result.readiness_status == "STALE_SOURCE"

    foreign_version = make_current_version(context, tenant_id="other_tenant_secret")
    result = map_context(context=context, current_version=foreign_version)
    assert result.readiness_status == "STALE_SOURCE"
    assert "other_tenant_secret" not in str(result.model_dump(mode="json"))


def test_wrong_tenant_customer_and_source_order_links_never_leak_foreign_ids():
    context = make_context()
    wrong_tenant_message = make_source_message(
        raw={
            **make_source_message().raw.model_dump(mode="json"),
            "tenant_id": "other_tenant_secret",
        }
    )
    result = map_context(context=context, source_messages=[wrong_tenant_message])
    assert result.readiness_status == "TERMS_CONFLICT"
    assert "SOURCE_TENANT_MISMATCH" in result.validation_reason_codes
    assert "other_tenant_secret" not in str(result.model_dump(mode="json"))

    wrong_customer = make_association(
        verified_customer={
            "customer_id": "other_customer_secret",
            "tenant_id": TENANT,
            "legal_name": "Other",
            "display_name": "Other",
        }
    )
    result = map_context(context=context, associations=[wrong_customer])
    assert result.readiness_status == "TERMS_CONFLICT"
    assert "SOURCE_CUSTOMER_MISMATCH" in result.validation_reason_codes
    assert "other_customer_secret" not in str(result.model_dump(mode="json"))


def test_unresolved_association_conflicts_or_context_conflicts_require_review():
    conflict_context = make_context(status="CONFLICT", conflicts=["quantity differs"])
    result = map_context(context=conflict_context)
    assert result.readiness_status == "TERMS_CONFLICT"
    assert result.canonical_terms is None

    ambiguous = make_association(
        status="LINK_CANDIDATE",
        verified_customer=None,
        candidates=[
            {
                "customer_id": CUSTOMER,
                "customer_name": "Buyer A",
                "order_id": None,
                "match_type": "TRUSTED_SENDER",
                "reasons": ["Two possible context links"],
                "evidence": [],
                "confidence": 0.5,
            }
        ],
    )
    result = map_context(associations=[ambiguous])
    assert result.readiness_status == "REVIEW_REQUIRED"
    assert "ASSOCIATION_UNRESOLVED" in result.validation_reason_codes


@pytest.mark.parametrize(
    "context_updates,commercial_updates,reason",
    [
        ({"requested_delivery_at": None}, {}, "DELIVERY_TIME_AMBIGUOUS"),
        ({"delivery_qualifier": "DATE_ONLY"}, {}, "DELIVERY_TIME_AMBIGUOUS"),
        ({}, {"fulfilment_method": None}, "FULFILMENT_METHOD_MISSING"),
        ({}, {"location_ref": None}, "FULFILMENT_LOCATION_MISSING"),
        ({}, {"business_timezone": "Not/AZone"}, "INVALID_BUSINESS_TIMEZONE"),
        ({}, {"window_end": "2026-10-25T10:30:00+08:00"}, "DELIVERY_WINDOW_CONFLICT"),
    ],
)
def test_ambiguous_or_conflicting_fulfilment_details_are_not_inferred(
    context_updates, commercial_updates, reason
):
    result = map_context(
        context=make_context(**context_updates),
        commercial=make_commercial(**commercial_updates),
    )

    assert result.readiness_status in {"INCOMPLETE", "REVIEW_REQUIRED", "TERMS_CONFLICT"}
    assert result.canonical_terms is None
    assert reason in result.validation_reason_codes


def test_material_sku_quantity_or_price_change_against_existing_core_requires_proposal():
    from app.orders.terms import OrderTerms

    original = map_context().canonical_terms
    assert original is not None

    changed_context = make_context(
        requested_items=[{"sku": "CUP", "quantity": "120", "unit": "pcs"}]
    )
    quantity_change = make_commercial(
        items=[{
            "sku": "CUP", "variant": "500ml", "quantity": "120", "unit": "pcs",
            "unit_price": "2.00",
        }],
        total="245.00",
    )
    result = map_context(context=changed_context, commercial=quantity_change, existing_core_terms=original)
    assert result.readiness_status == "TERMS_CONFLICT"
    assert result.canonical_terms is None
    assert "PROPOSAL_REQUIRED" in result.validation_reason_codes
    assert "items" in result.conflict_fields

    price_change = make_commercial(
        items=[{
            "sku": "CUP", "variant": "500ml", "quantity": "100", "unit": "pcs",
            "unit_price": "3.00",
        }],
        total="305.00",
    )
    result = map_context(commercial=price_change, existing_core_terms=original)
    assert result.readiness_status == "TERMS_CONFLICT"
    assert "PROPOSAL_REQUIRED" in result.validation_reason_codes

    assert isinstance(original, OrderTerms)


def test_existing_core_commitment_requires_authoritative_terms_for_comparison():
    context = make_context(core_commitment_id="commitment_a")
    result = map_context(context=context)
    assert result.readiness_status == "REVIEW_REQUIRED"
    assert "CORE_TERMS_REVALIDATION_REQUIRED" in result.validation_reason_codes
    assert result.canonical_terms is None


def test_duplicate_replayed_sources_and_missing_field_evidence_are_rejected():
    context = make_context(source_message_ids=[MESSAGE, MESSAGE])
    result = map_context(context=context)
    assert result.readiness_status == "REVIEW_REQUIRED"
    assert "DUPLICATE_SOURCE_MESSAGE_ID" in result.validation_reason_codes

    no_evidence = make_context(field_evidence={"sku": [{"evidence_ref": "ev_sku"}]})
    result = map_context(context=no_evidence)
    assert result.readiness_status == "INCOMPLETE"
    assert "source_evidence:quantity" in result.missing_fields
    assert result.canonical_terms is None


def test_missing_sources_and_duplicate_or_foreign_association_records_fail_closed():
    result = map_context(source_messages=[])
    assert result.readiness_status == "INCOMPLETE"
    assert "source_messages" in result.missing_fields

    result = map_context(associations=[make_association(), make_association()])
    assert result.readiness_status == "REVIEW_REQUIRED"
    assert "DUPLICATE_SOURCE_ASSOCIATION" in result.validation_reason_codes

    foreign_assoc = make_association(tenant_id="other_tenant_secret")
    result = map_context(associations=[foreign_assoc])
    assert result.readiness_status == "TERMS_CONFLICT"
    assert "SOURCE_TENANT_MISMATCH" in result.validation_reason_codes
    assert "other_tenant_secret" not in str(result.model_dump(mode="json"))


def test_price_authority_must_bind_exact_tenant_customer_source_and_version():
    wrong_source = make_commercial(
        price_source_authority={
            "tenant_id": TENANT,
            "customer_id": CUSTOMER,
            "source_id": "other_catalog",
            "source_version": "catalog_v3",
            "status": "VERIFIED",
            "authority_ref": "some_record",
        }
    )
    result = map_context(commercial=wrong_source)
    assert result.readiness_status == "PRICE_SOURCE_UNVERIFIED"
    assert result.canonical_terms is None

    foreign_commercial = make_commercial(
        tenant_id="other_tenant_secret",
        order_request_id="foreign_order_request_secret",
    )
    result = map_context(commercial=foreign_commercial)
    assert result.readiness_status == "TERMS_CONFLICT"
    rendered = str(result.model_dump(mode="json"))
    assert "other_tenant_secret" not in rendered
    assert "foreign_order_request_secret" not in rendered


def test_untrusted_extra_fields_and_floating_money_are_rejected():
    from app.orders.context_mapping import OrderCommercialEvidence

    data = make_commercial().model_dump(mode="python")
    with pytest.raises(ValidationError):
        OrderCommercialEvidence.model_validate(data | {"approved": True})

    data = make_commercial().model_dump(mode="python")
    data["fees"] = 1.1
    with pytest.raises(ValidationError):
        OrderCommercialEvidence.model_validate(data)


def test_mapping_has_no_core_or_external_side_effects_and_existing_hash_contract_is_unchanged():
    from app.orders.terms import compare_terms

    original = map_context().canonical_terms
    assert original is not None
    before = original.terms_hash
    result = map_context(existing_core_terms=original)
    assert result.readiness_status == "READY_FOR_VALIDATION"
    assert result.terms_hash == before
    assert compare_terms(original, result.canonical_terms).matches
    assert original.terms_hash == before
