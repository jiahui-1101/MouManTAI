"""Regression tests for the trusted, read-only P1 OrderContext source adapter."""

from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest

TENANT = "tenant_a"
CUSTOMER = "customer_a"
CONTEXT = "context_a"
MESSAGE = "message_a"
NOW = datetime(2026, 10, 24, 8, tzinfo=UTC)
DELIVERY = "2026-10-25T11:00:00+08:00"
MESSAGE_TEXT = f"CUP 5 pcs {DELIVERY}"


class StaticTenantScope:
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id

    def current_verified_tenant_id(self):
        return self.tenant_id


class SnapshotRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.reads = []

    def read_order_context_source(self, tenant_id, context_id):
        self.reads.append((tenant_id, context_id))
        if self.snapshot is None:
            return None
        return self.snapshot


def _source_record(evidence_id, token, value):
    start = MESSAGE_TEXT.index(token)
    end = start + len(token)
    return {
        "evidence_id": evidence_id,
        "message_id": MESSAGE,
        "start": start,
        "end": end,
        "quote": token,
        "method": "RULE",
        "method_version": "rules-v1",
        "normalized_value": value,
    }


def make_snapshot():
    from app.context.association_schemas import (
        CustomerAccount,
        MessageAssociationRecord,
    )
    from app.context.ingestion_schemas import (
        ExtractionAttemptRecord,
        StoredMessage,
    )
    from app.context.order_context_schemas import (
        ContextReviewRecord,
        OrderContextRecord,
        OrderContextVersionRecord,
        RequestedItem,
    )
    from app.context.schemas import (
        ExtractedField,
        FieldEvidence,
        RawMessageEnvelope,
    )

    evidence = {
        "sku": [_source_record("ev_sku", "CUP", "CUP")],
        "quantity": [_source_record("ev_quantity", "5", "5")],
        "unit": [_source_record("ev_unit", "pcs", "pcs")],
        "requested_delivery_at": [_source_record("ev_delivery", DELIVERY, DELIVERY)],
    }
    context = OrderContextRecord(
        context_id=CONTEXT,
        tenant_id=TENANT,
        customer_id=CUSTOMER,
        customer_identity_status="LINK_VERIFIED",
        status="INFORMATION_READY",
        context_version=2,
        requested_items=[RequestedItem(sku="CUP", quantity="5", unit="pcs")],
        requested_delivery_at=NOW.replace(day=25, hour=3),
        delivery_qualifier="DEADLINE",
        source_message_ids=[MESSAGE],
        field_evidence=evidence,
        last_reviewed_by="reviewer_a",
        last_reviewed_role="MANAGER",
        last_reviewed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    context_version = OrderContextVersionRecord(
        version_id="context_version_2",
        context_id=CONTEXT,
        tenant_id=TENANT,
        context_version=2,
        snapshot=context.model_dump(mode="json"),
        change_type="EDIT_FIELD",
        actor_id="reviewer_a",
        actor_role="MANAGER",
        created_at=NOW,
    )
    review = ContextReviewRecord(
        review_id="review_a",
        tenant_id=TENANT,
        context_id=CONTEXT,
        context_version_before=1,
        context_version_after=2,
        action="EDIT_FIELD",
        actor_id="reviewer_a",
        actor_role="MANAGER",
        field_changes={"requested_items": {"old": [], "new": [{"sku": "CUP"}]}},
        created_at=NOW,
    )
    raw = RawMessageEnvelope(
        tenant_id=TENANT,
        channel="WHATSAPP",
        provider_message_id="provider_message_a",
        sender_identity_id="sender_a",
        sender_alias="Buyer A",
        received_at=NOW,
        message_at=NOW,
        text=MESSAGE_TEXT,
        adapter_mode="REAL",
    )
    message = StoredMessage(
        message_id=MESSAGE,
        raw=raw,
        synthetic_provider=None,
        provider="WHATSAPP_CLOUD_API",
        source_label="WhatsApp",
        content_sha256=sha256(MESSAGE_TEXT.encode()).hexdigest(),
        processing_status="PROCESSED",
        extractor_version="rules-v1",
        ingested_at=NOW,
        updated_at=NOW,
    )
    extracted_fields = []
    for field_name, entries in evidence.items():
        for entry in entries:
            extracted_fields.append(
                ExtractedField(
                    field_name=field_name,
                    value=entry["normalized_value"],
                    validation_status="VALID",
                    evidence=[
                        FieldEvidence(
                            **{
                                key: entry[key]
                                for key in (
                                    "evidence_id",
                                    "message_id",
                                    "start",
                                    "end",
                                    "quote",
                                    "method",
                                    "method_version",
                                )
                            }
                        )
                    ],
                )
            )
    extraction = ExtractionAttemptRecord(
        attempt_id="attempt_a",
        tenant_id=TENANT,
        message_id=MESSAGE,
        extractor_version="rules-v1",
        input_content_sha256=message.content_sha256,
        status="PROCESSED",
        fields=extracted_fields,
        started_at=NOW,
        completed_at=NOW,
    )
    association = MessageAssociationRecord(
        association_id="association_a",
        tenant_id=TENANT,
        message_id=MESSAGE,
        status="LINK_VERIFIED",
        verified_customer=CustomerAccount(
            customer_id=CUSTOMER,
            tenant_id=TENANT,
            legal_name="Buyer A Ltd",
            display_name="Buyer A",
        ),
        version=7,
        updated_at=NOW,
    )
    return SimpleNamespace(
        context=context,
        context_versions=(context_version,),
        context_reviews=(review,),
        source_messages=(message,),
        associations=(association,),
        extraction_attempts=(extraction,),
    )


def read(snapshot=None, *, tenant_id=TENANT, expected_context_version=2):
    from app.orders.p1_source_reader import P1OrderContextSourceReader

    repository = SnapshotRepository(snapshot if snapshot is not None else make_snapshot())
    reader = P1OrderContextSourceReader(
        repository,
        tenant_scope=StaticTenantScope(tenant_id),
    )
    return reader.read_candidate(
        CONTEXT,
        expected_context_version=expected_context_version,
    ), repository


def test_current_p1_snapshot_is_loaded_but_stays_incomplete_without_commercial_reader():
    snapshot = make_snapshot()
    result, repository = read(snapshot)

    assert repository.reads == [(TENANT, CONTEXT)]
    assert result.status == "INCOMPLETE"
    assert result.candidate is not None
    assert result.candidate.readiness_status == "INCOMPLETE"
    assert result.candidate.canonical_terms is None
    assert result.candidate.order_request_id is None
    assert result.candidate.terms_hash is None
    assert result.candidate.agreement_basis == "UNKNOWN"
    assert result.candidate.customer_assent_evidence == ()
    assert result.candidate.source_context_version_record_id == "context_version_2"
    assert result.candidate.customer_identity_associations[0].association_version == 7
    assert "COMMERCIAL_EVIDENCE_MISSING" in result.candidate.validation_reason_codes


def test_missing_trusted_tenant_scope_fails_closed_before_repository_read():
    from app.orders.p1_source_reader import P1OrderContextSourceReader

    repository = SnapshotRepository(make_snapshot())
    reader = P1OrderContextSourceReader(repository, tenant_scope=None)

    result = reader.read_candidate(CONTEXT, expected_context_version=2)

    assert result.status == "IDENTITY_UNVERIFIED"
    assert result.candidate is None
    assert result.reason_codes == ("TRUSTED_TENANT_SCOPE_UNAVAILABLE",)
    assert repository.reads == []


def test_cross_tenant_snapshot_is_not_reflected_in_candidate_or_error():
    foreign_snapshot = make_snapshot()
    foreign_snapshot.context = foreign_snapshot.context.model_copy(
        update={"tenant_id": "other_tenant_secret", "customer_id": "other_customer_secret"}
    )
    repository = SnapshotRepository(foreign_snapshot)
    from app.orders.p1_source_reader import P1OrderContextSourceReader

    result = P1OrderContextSourceReader(
        repository,
        tenant_scope=StaticTenantScope(TENANT),
    ).read_candidate(CONTEXT, expected_context_version=2)

    assert result.status == "REVIEW_REQUIRED"
    assert result.candidate is None
    assert "other_tenant_secret" not in str(result.model_dump(mode="json"))
    assert "other_customer_secret" not in str(result.model_dump(mode="json"))


def test_requested_stale_context_version_returns_stale_source_without_mapping():
    result, _ = read(expected_context_version=1)

    assert result.status == "STALE_SOURCE"
    assert result.candidate is None
    assert result.reason_codes == ("EXPECTED_CONTEXT_VERSION_STALE",)


def test_current_context_without_matching_current_version_record_is_stale():
    snapshot = make_snapshot()
    snapshot.context_versions = (
        snapshot.context_versions[0].model_copy(update={"context_version": 1}),
    )

    result, _ = read(snapshot)

    assert result.status == "STALE_SOURCE"
    assert result.candidate is None


def test_missing_human_review_stays_review_required():
    snapshot = make_snapshot()
    snapshot.context_reviews = ()

    result, _ = read(snapshot)

    assert result.status == "REVIEW_REQUIRED"
    assert result.candidate is not None
    assert result.candidate.canonical_terms is None
    assert "CURRENT_CONTEXT_REVIEW_REQUIRED" in result.candidate.validation_reason_codes


def test_conflicting_customer_association_is_not_mapped():
    from app.context.association_schemas import IdentityLinkStatus

    snapshot = make_snapshot()
    snapshot.associations = (
        snapshot.associations[0].model_copy(
            update={
                "status": IdentityLinkStatus.CONFLICT,
                "conflicts": ["customer mismatch"],
            }
        ),
    )

    result, _ = read(snapshot)

    assert result.status == "TERMS_CONFLICT"
    assert result.candidate is not None
    assert result.candidate.canonical_terms is None
    assert "SOURCE_ASSOCIATION_CONFLICT" in result.candidate.validation_reason_codes


def test_unresolvable_evidence_span_requires_review_before_mapping():
    snapshot = make_snapshot()
    snapshot.context.field_evidence["sku"][0]["quote"] = "NOT IN MESSAGE"
    snapshot.context_versions = (
        snapshot.context_versions[0].model_copy(
            update={"snapshot": snapshot.context.model_dump(mode="json")}
        ),
    )

    result, _ = read(snapshot)

    assert result.status == "REVIEW_REQUIRED"
    assert result.candidate is None
    assert "SOURCE_EVIDENCE_PROVENANCE_UNVERIFIED" in result.reason_codes


@pytest.mark.parametrize(
    "unsupported_evidence",
    [
        {"method": "OCR", "method_version": "ocr-v1"},
        {"method": "PDF_TEXT", "method_version": "pdf-text-v1"},
        {
            "evidence_id": None,
            "message_id": None,
            "method": "OCR",
            "method_version": "ocr-v1",
            "evidence_ref": "attachment-only-reference",
        },
    ],
)
def test_unsupported_document_or_attachment_evidence_fails_closed(unsupported_evidence):
    snapshot = make_snapshot()
    entry = {**snapshot.context.field_evidence["sku"][0], **unsupported_evidence}
    snapshot.context.field_evidence["sku"] = [entry]
    snapshot.context_versions = (
        snapshot.context_versions[0].model_copy(
            update={"snapshot": snapshot.context.model_dump(mode="json")}
        ),
    )

    result, _ = read(snapshot)

    assert result.status == "REVIEW_REQUIRED"
    assert result.candidate is None
    assert result.reason_codes == ("SOURCE_EVIDENCE_PROVENANCE_UNVERIFIED",)
    assert "attachment-only-reference" not in str(result.model_dump(mode="json"))


def test_current_context_must_equal_its_authoritative_version_snapshot():
    snapshot = make_snapshot()
    snapshot.context.requested_items[0].sku = "OTHER"

    result, _ = read(snapshot)

    assert result.status == "STALE_SOURCE"
    assert result.candidate is None
    assert result.reason_codes == ("CURRENT_CONTEXT_SNAPSHOT_MISMATCH",)


def test_current_human_item_edit_can_supersede_older_extraction_values():
    from app.context.order_context_schemas import RequestedItem

    snapshot = make_snapshot()
    edited = [{"sku": "MUG", "quantity": "5", "unit": "pcs"}]
    snapshot.context = snapshot.context.model_copy(
        update={
            "requested_items": [RequestedItem.model_validate(edited[0])],
            "field_evidence": {
                **snapshot.context.field_evidence,
                "requested_items": [
                    {
                        "evidence_ref": "review_a",
                        "method": "HUMAN",
                        "actor_id": "reviewer_a",
                        "context_version": 2,
                        "normalized_value": edited,
                    }
                ],
            },
        }
    )
    snapshot.context_reviews = (
        snapshot.context_reviews[0].model_copy(
            update={"field_changes": {"requested_items": {"old": [], "new": edited}}}
        ),
    )
    snapshot.context_versions = (
        snapshot.context_versions[0].model_copy(
            update={"snapshot": snapshot.context.model_dump(mode="json")}
        ),
    )

    result, _ = read(snapshot)

    assert result.status == "INCOMPLETE"
    assert result.candidate is not None
    assert result.candidate.canonical_terms is None
    assert "COMMERCIAL_EVIDENCE_MISSING" in result.candidate.validation_reason_codes


def test_context_source_references_are_loaded_using_only_the_verified_tenant():
    result, repository = read(tenant_id=TENANT)

    assert repository.reads == [(TENANT, CONTEXT)]
    assert result.candidate is not None
    assert result.candidate.tenant_id == TENANT


def test_cross_tenant_source_message_is_suppressed_before_mapping():
    snapshot = make_snapshot()
    snapshot.source_messages = (
        snapshot.source_messages[0].model_copy(
            update={
                "raw": snapshot.source_messages[0].raw.model_copy(
                    update={"tenant_id": "foreign_tenant_secret"}
                )
            }
        ),
    )

    result, _ = read(snapshot)

    assert result.status == "REVIEW_REQUIRED"
    assert result.candidate is None
    assert "foreign_tenant_secret" not in str(result.model_dump(mode="json"))


def test_source_content_hash_mismatch_requires_review():
    snapshot = make_snapshot()
    snapshot.source_messages = (
        snapshot.source_messages[0].model_copy(update={"content_sha256": "0" * 64}),
    )

    result, _ = read(snapshot)

    assert result.status == "REVIEW_REQUIRED"
    assert result.reason_codes == ("SOURCE_EVIDENCE_PROVENANCE_UNVERIFIED",)
    assert result.candidate is None


def test_extraction_from_stale_message_content_cannot_back_current_context():
    snapshot = make_snapshot()
    snapshot.extraction_attempts = (
        snapshot.extraction_attempts[0].model_copy(update={"input_content_sha256": "0" * 64}),
    )

    result, _ = read(snapshot)

    assert result.status == "REVIEW_REQUIRED"
    assert result.reason_codes == ("SOURCE_EVIDENCE_PROVENANCE_UNVERIFIED",)
    assert result.candidate is None


def test_evidence_value_must_match_the_current_context_value():
    snapshot = make_snapshot()
    snapshot.context.field_evidence["sku"][0]["normalized_value"] = "OTHER"
    snapshot.context_versions = (
        snapshot.context_versions[0].model_copy(
            update={"snapshot": snapshot.context.model_dump(mode="json")}
        ),
    )

    result, _ = read(snapshot)

    assert result.status == "REVIEW_REQUIRED"
    assert result.reason_codes == ("SOURCE_EVIDENCE_PROVENANCE_UNVERIFIED",)
    assert result.candidate is None


def test_provider_channel_mismatch_requires_review():
    snapshot = make_snapshot()
    snapshot.source_messages = (
        snapshot.source_messages[0].model_copy(update={"provider": "GMAIL_API"}),
    )

    result, _ = read(snapshot)

    assert result.status == "REVIEW_REQUIRED"
    assert result.candidate is None


def test_missing_original_source_message_is_incomplete():
    snapshot = make_snapshot()
    snapshot.source_messages = ()

    result, _ = read(snapshot)

    assert result.status == "INCOMPLETE"
    assert result.candidate is not None
    assert "SOURCE_MESSAGE_RECORD_MISSING" in result.candidate.validation_reason_codes


def test_cross_tenant_association_customer_binding_is_suppressed():
    snapshot = make_snapshot()
    association = snapshot.associations[0].model_copy(
        update={
            "verified_customer": snapshot.associations[0].verified_customer.model_copy(
                update={"tenant_id": "foreign_tenant_secret"}
            )
        }
    )
    snapshot.associations = (association,)

    result, _ = read(snapshot)

    assert result.status == "REVIEW_REQUIRED"
    assert result.candidate is None
    assert "foreign_tenant_secret" not in str(result.model_dump(mode="json"))
