"""C3 message-intelligence contracts: fixture-only, with no provider/network sends."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.context.association_schemas import (
    CustomerAccount,
    IdentityLinkStatus,
    MessageAssociationRecord,
    PlatformIdentity,
)
from app.context.document_schemas import (
    AttachmentRecord,
    DocumentEvidence,
    DocumentExtractionResult,
)
from app.context.ingestion_schemas import StoredMessage
from app.context.schemas import RawMessageEnvelope
from app.message_intelligence.adapters import (
    ApprovedInquiryFact,
    CurrentP1MessageReader,
    TrustedDeliverySnapshot,
    draft_customer_inquiry,
    validate_supplier_delay,
)
from app.message_intelligence.contracts import (
    CustomerInquiryCandidate,
    VerifiedSupplierIdentity,
)
from app.message_intelligence.service import MessageIntelligenceService, SourceContractError

NOW = datetime(2026, 10, 25, 4, 0, tzinfo=UTC)
TENANT = "tenant_c3_test"


class FixtureGateway:
    def __init__(self, assessment):
        self.assessment = assessment
        self.prompts = []

    def classify(self, segments):
        self.prompts.append(segments)
        return SimpleNamespace(
            assessment=self.assessment,
            provider="QWEN",
            model_id="fixture-qwen",
            attempts=[],
        )


class CurrentSourceFixture:
    def __init__(self, msg, association=None):
        self.msg, self.association = msg, association

    def current_verified_tenant_id(self):
        return self.msg.raw.tenant_id

    def get(self, tenant_id, message_id):
        return (
            self.msg
            if (tenant_id, message_id) == (self.msg.raw.tenant_id, self.msg.message_id)
            else None
        )

    def get_association(self, tenant_id, message_id):
        return self.association


def canonical_message(text):
    msg = message(text)
    raw = msg.raw.model_copy(
        update={
            "source_authenticity": "VERIFIED",
            "provider_account_id": "tg_bot_business_1",
            "provider_native_message_id": msg.raw.provider_message_id,
        }
    )
    return msg.model_copy(
        update={"raw": raw, "content_sha256": sha256(text.encode("utf-8")).hexdigest()}
    )


def test_current_p1_reader_drafts_only_from_verified_approved_facts():
    msg = canonical_message("What is the price?")
    association = verified_customer_association(msg)
    source = CurrentSourceFixture(msg, association)
    reader = CurrentP1MessageReader(source, source)
    outcome = reader.analyze(msg.message_id, MessageIntelligenceService(), now=NOW)
    assert outcome.customer_inquiry is not None
    assert outcome.source.provider_account_id == "tg_bot_business_1"
    assert outcome.source.provider_native_message_id == msg.raw.provider_message_id
    assert outcome.source.source_authenticity == "VERIFIED"

    class Facts:
        def read_public_inquiry_fact(self, tenant_id, topic):
            return ApprovedInquiryFact(
                tenant_id=tenant_id,
                topic=topic,
                text="The approved public price is RM 10.",
                evidence_refs=("catalog:v3:price",),
                source_version=3,
                checked_at=NOW,
            )

    draft = draft_customer_inquiry(outcome.customer_inquiry, reader=reader, facts=Facts(), now=NOW)
    assert draft.business_evidence == ("catalog:v3:price",)
    assert draft.source_content_sha256 == msg.content_sha256
    assert draft.send_authorized is False
    with pytest.raises(SourceContractError):
        draft_customer_inquiry(
            outcome.customer_inquiry, reader=reader, facts=Facts(), now=NOW + timedelta(minutes=6)
        )
    source.association = None
    with pytest.raises(SourceContractError):
        draft_customer_inquiry(outcome.customer_inquiry, reader=reader, facts=Facts(), now=NOW)


def test_current_reader_rejects_real_channel_without_verified_account_scope():
    msg = canonical_message("What is the price?")
    raw = msg.raw.model_copy(update={"source_authenticity": "UNVERIFIED"})
    source = CurrentSourceFixture(msg.model_copy(update={"raw": raw}))
    with pytest.raises(SourceContractError, match="verified account-bound provenance"):
        CurrentP1MessageReader(source, source).analyze(msg.message_id, MessageIntelligenceService())


def test_supplier_handoff_requires_exact_current_p2_snapshot():
    msg = canonical_message("PO-450 delivery is delayed until 2026-10-29")
    source = CurrentSourceFixture(msg)
    reader = CurrentP1MessageReader(source, source)
    candidate = reader.analyze(
        msg.message_id,
        MessageIntelligenceService(supplier_identity_resolver=VerifiedSupplierResolver()),
        now=NOW,
    ).supplier_delay
    assert candidate is not None

    class P2:
        def read_delivery(self, tenant_id, supplier_id, reference):
            return TrustedDeliverySnapshot(
                tenant_id=tenant_id,
                supplier_id=supplier_id,
                delivery_reference=reference,
                snapshot_version=4,
                snapshot_at=NOW,
                expected_eta=NOW,
                evidence_refs=("p2:snapshot:4",),
            )

    assessment = validate_supplier_delay(
        candidate,
        reader=reader,
        p2=P2(),
        supplier_identity=VerifiedSupplierResolver(),
        now=NOW,
    )
    assert assessment.snapshot_version == 4
    assert assessment.status == "POTENTIAL_DELAY_REPORTED"
    assert assessment.state_mutated is False

    class WrongP2(P2):
        def read_delivery(self, tenant_id, supplier_id, reference):
            row = super().read_delivery(tenant_id, supplier_id, reference)
            return row.model_copy(update={"supplier_id": "another_supplier"})

    with pytest.raises(SourceContractError):
        validate_supplier_delay(
            candidate,
            reader=reader,
            p2=WrongP2(),
            supplier_identity=VerifiedSupplierResolver(),
            now=NOW,
        )
    source.msg = canonical_message("PO-450 delivery was delayed until 2026-10-30")
    with pytest.raises(SourceContractError):
        validate_supplier_delay(
            candidate,
            reader=reader,
            p2=P2(),
            supplier_identity=VerifiedSupplierResolver(),
            now=NOW,
        )


def message(text: str, *, tenant: str = TENANT, attachments=()) -> StoredMessage:
    return StoredMessage(
        message_id="msg_c3_001",
        raw=RawMessageEnvelope(
            tenant_id=tenant,
            channel="TELEGRAM",
            provider_message_id="tg_update_9931",
            sender_identity_id="tg_user_771",
            sender_alias="Test sender",
            received_at=NOW,
            message_at=NOW,
            text=text,
            attachments=list(attachments),
            thread_ref="tg_chat_41",
            reply_to_provider_message_id="tg_message_9910",
            adapter_mode="REAL",
            source_authenticity="VERIFIED",
            provider_account_id="tg_bot_business_1",
            provider_native_message_id="tg_update_9931",
        ),
        provider="TELEGRAM_BOT_API",
        source_label="Real Telegram",
        content_sha256="a" * 64,
        processing_status="RECEIVED",
        ingested_at=NOW,
        updated_at=NOW,
    )


def verified_customer_association(msg: StoredMessage) -> MessageAssociationRecord:
    raw = msg.raw
    return MessageAssociationRecord(
        association_id="assoc_c3_001",
        tenant_id=raw.tenant_id,
        message_id=msg.message_id,
        status=IdentityLinkStatus.LINK_VERIFIED,
        verified_customer=CustomerAccount(
            customer_id="cust_c3_001",
            tenant_id=raw.tenant_id,
            legal_name="Test Customer Ltd",
            display_name="Test Customer",
            verified_channels=[raw.channel],
            verified_contacts=[
                PlatformIdentity(
                    channel=raw.channel,
                    sender_identity_id=raw.sender_identity_id,
                    sender_alias=raw.sender_alias,
                )
            ],
        ),
        version=2,
        updated_at=NOW,
    )


class VerifiedSupplierResolver:
    def resolve_supplier(self, *, tenant_id, channel, sender_identity_id):
        assert tenant_id == TENANT
        assert channel == "TELEGRAM"
        assert sender_identity_id == "tg_user_771"
        return VerifiedSupplierIdentity(
            tenant_id=TENANT,
            channel="TELEGRAM",
            sender_identity_id="tg_user_771",
            supplier_id="supplier_c3_001",
            status="VERIFIED",
            evidence_refs=["supplier_contact_v4"],
            checked_at=NOW,
            version=4,
        )


def test_deterministic_customer_inquiry_reuses_existing_intent_rules():
    msg = message("How much is one box of chicken nuggets?")

    result = MessageIntelligenceService().analyze(
        msg, association=verified_customer_association(msg), now=NOW
    )

    assert result.intent == "CUSTOMER_INQUIRY"
    assert result.customer_inquiry is not None
    assert result.customer_inquiry.topic == "PRICE"
    assert result.customer_inquiry.identity_status == "LINK_VERIFIED"
    assert result.customer_inquiry.association_id == "assoc_c3_001"
    assert result.customer_inquiry.source.provider_message_id == "tg_update_9931"
    assert result.customer_inquiry.source.reply_to_provider_message_id == "tg_message_9910"
    assert result.provider_attempts == []
    assert result.customer_inquiry.candidate_only is True
    assert result.review_required is False


def test_candidate_contract_rejects_evidence_from_another_message():
    msg = message("How much is one box of chicken nuggets?")
    result = MessageIntelligenceService().analyze(
        msg, association=verified_customer_association(msg), now=NOW
    )
    payload = result.customer_inquiry.model_dump()
    payload["evidence"][0]["message_id"] = "foreign_message"

    with pytest.raises(ValueError, match="source message"):
        CustomerInquiryCandidate.model_validate(payload)


def test_future_customer_association_time_becomes_human_review_candidate():
    msg = message("How much is one box of chicken nuggets?")
    association = verified_customer_association(msg).model_copy(
        update={"updated_at": NOW + timedelta(days=1)}
    )

    result = MessageIntelligenceService().analyze(msg, association=association, now=NOW)

    assert result.customer_inquiry.identity_status == "AMBIGUOUS"
    assert result.customer_inquiry.customer_id is None
    assert result.review_required is True
    assert "SENDER_IDENTITY_AMBIGUOUS" in result.review_reasons
    assert result.human_review_candidate is not None


def test_supplier_delay_is_a_reported_candidate_even_for_verified_supplier():
    msg = message("Our PO-991 delivery is delayed until 2026-10-28.")
    service = MessageIntelligenceService(supplier_identity_resolver=VerifiedSupplierResolver())

    result = service.analyze(msg, now=NOW)

    candidate = result.supplier_delay
    assert candidate is not None
    assert candidate.supplier_id == "supplier_c3_001"
    assert candidate.supplier_identity_status == "VERIFIED"
    assert candidate.delivery_reference == "PO-991"
    assert candidate.reported_eta_text == "2026-10-28"
    assert candidate.candidate_only is True
    assert candidate.review_required is True
    assert "REPORTED_CLAIM_NOT_AUTHORITATIVE" in candidate.review_reasons
    assert result.p2_event_created is False


def test_future_supplier_identity_check_becomes_unverified_review_candidate():
    class FutureSupplierResolver(VerifiedSupplierResolver):
        def resolve_supplier(self, **kwargs):
            identity = super().resolve_supplier(**kwargs)
            return identity.model_copy(update={"checked_at": NOW + timedelta(days=1)})

    result = MessageIntelligenceService(
        supplier_identity_resolver=FutureSupplierResolver()
    ).analyze(message("Our PO-991 delivery is delayed until 2026-10-28."), now=NOW)

    assert result.supplier_delay.supplier_id is None
    assert result.supplier_delay.supplier_identity_status == "UNVERIFIED"
    assert "SUPPLIER_IDENTITY_CHECK_FROM_FUTURE" in result.review_reasons
    assert result.human_review_candidate is not None


def test_cross_tenant_association_is_rejected_before_provider_call():
    msg = message("What is your price?")
    association = verified_customer_association(msg).model_copy(
        update={"tenant_id": "tenant_other"}
    )
    gateway = FixtureGateway({"intent": "OTHER", "inquiry_topic": None, "claims": []})

    with pytest.raises(SourceContractError):
        MessageIntelligenceService(semantic_gateway=gateway).analyze(
            msg, association=association, now=NOW
        )

    assert gateway.prompts == []


def test_shared_gateway_result_is_schema_and_source_validated():
    text = "What would be the best option for getting this to our office?"
    claim = {
        "kind": "INQUIRY",
        "value": "delivery options",
        "evidence": {"segment_id": "s0", "quote": text, "start": 0, "end": len(text)},
    }
    gateway = FixtureGateway(
        {"intent": "CUSTOMER_INQUIRY", "inquiry_topic": "DELIVERY", "claims": [claim]}
    )
    msg = message(text)
    result = MessageIntelligenceService(semantic_gateway=gateway).analyze(
        msg, association=verified_customer_association(msg), now=NOW
    )
    assert result.provider == "QWEN"
    assert result.customer_inquiry is not None
    assert result.customer_inquiry.evidence[0].quote == text

    claim["evidence"]["quote"] = "invented source"
    rejected = MessageIntelligenceService(semantic_gateway=gateway).analyze(
        msg, association=verified_customer_association(msg), now=NOW
    )
    assert rejected.review_required
    assert "AI_OUTPUT_INVALID" in rejected.review_reasons
    assert len(gateway.prompts) == 2


def test_unverified_identity_keeps_inquiry_candidate_in_human_review():
    msg = message("How much does it cost?")

    result = MessageIntelligenceService().analyze(msg, now=NOW)

    assert result.customer_inquiry is not None
    assert result.customer_inquiry.identity_status == "UNVERIFIED"
    assert result.customer_inquiry.review_required is True
    assert "SENDER_IDENTITY_UNVERIFIED" in result.customer_inquiry.review_reasons


def test_provider_never_receives_tenant_sender_or_unredacted_contact_data():
    text = "Please email alice@example.com about delivery to +60123456789."
    gateway = FixtureGateway({"intent": "OTHER", "inquiry_topic": None, "claims": []})
    msg = message(text)

    MessageIntelligenceService(semantic_gateway=gateway).analyze(msg, now=NOW)

    prompt = "\n".join(text for _, text in gateway.prompts[0])
    assert "alice@example.com" not in prompt
    assert "+60123456789" not in prompt
    assert TENANT not in prompt
    assert "tg_user_771" not in prompt


def test_document_candidate_cites_existing_page_evidence_only():
    attachment = {
        "attachment_id": "att_c3_001",
        "filename": "supplier_note.pdf",
        "media_type": "application/pdf",
        "size_bytes": 120,
        "evidence_ref": "ev_att_c3_001",
    }
    extraction = DocumentExtractionResult(
        attachment_id="att_c3_001",
        evidence_ref="ev_att_c3_001",
        status="SUCCESS",
        document_type="PDF",
        page_count=1,
        text_content="Delivery has been postponed until 2026-10-29.",
        evidence_items=[
            DocumentEvidence(
                evidence_id="doc_ev_001",
                evidence_ref="ev_att_c3_001",
                attachment_id="att_c3_001",
                page_number=1,
                quote="Delivery has been postponed until 2026-10-29.",
                method="PDF_TEXT",
                method_version="p1-pdf-v1",
            )
        ],
        extracted_at=NOW,
    )
    record = AttachmentRecord(
        attachment_id="att_c3_001",
        tenant_id=TENANT,
        evidence_ref="ev_att_c3_001",
        filename="supplier_note.pdf",
        media_type="application/pdf",
        size_bytes=120,
        content_sha256="b" * 64,
        created_at=NOW,
    )
    msg = message("Please see attached supplier update.", attachments=[attachment])
    resolver = VerifiedSupplierResolver()

    result = MessageIntelligenceService(supplier_identity_resolver=resolver).analyze(
        msg, attachments=[extraction], attachment_records=[record], now=NOW
    )

    assert result.supplier_delay is not None
    citation = result.supplier_delay.evidence[0]
    assert citation.evidence_id == "doc_ev_001"
    assert citation.evidence_ref == "ev_att_c3_001"
    assert citation.page_number == 1
    assert result.supplier_delay.source.attachment_sources[0].content_sha256 == "b" * 64
    assert result.supplier_delay.source.attachment_sources[0].extraction_method_versions == [
        "p1-pdf-v1"
    ]


def test_failed_attachment_extraction_is_review_candidate_without_claim():
    attachment = {
        "attachment_id": "att_c3_002",
        "filename": "bad.pdf",
        "media_type": "application/pdf",
        "size_bytes": 12,
        "evidence_ref": "ev_att_c3_002",
    }
    extraction = DocumentExtractionResult(
        attachment_id="att_c3_002",
        evidence_ref="ev_att_c3_002",
        status="FAILED",
        document_type="PDF",
        page_count=0,
        diagnostic="unreadable",
        extracted_at=NOW,
    )
    record = AttachmentRecord(
        attachment_id="att_c3_002",
        tenant_id=TENANT,
        evidence_ref="ev_att_c3_002",
        filename="bad.pdf",
        media_type="application/pdf",
        size_bytes=12,
        content_sha256="c" * 64,
        created_at=NOW,
    )
    result = MessageIntelligenceService().analyze(
        message("See attached", attachments=[attachment]),
        attachments=[extraction],
        attachment_records=[record],
        now=NOW,
    )

    assert result.review_required is True
    assert "ATTACHMENT_EXTRACTION_FAILED" in result.review_reasons
    assert result.supplier_delay is None
    assert result.customer_inquiry is None


def test_stale_attachment_extraction_is_rejected_before_analysis():
    attachment = {
        "attachment_id": "att_c3_003",
        "filename": "old.pdf",
        "media_type": "application/pdf",
        "size_bytes": 12,
        "evidence_ref": "ev_att_c3_003",
    }
    record = AttachmentRecord(
        attachment_id="att_c3_003",
        tenant_id=TENANT,
        evidence_ref="ev_att_c3_003",
        filename="old.pdf",
        media_type="application/pdf",
        size_bytes=12,
        content_sha256="d" * 64,
        created_at=NOW,
    )
    stale = DocumentExtractionResult(
        attachment_id="att_c3_003",
        evidence_ref="ev_att_c3_003",
        status="SUCCESS",
        document_type="PDF",
        page_count=1,
        text_content="delivery postponed",
        evidence_items=[
            DocumentEvidence(
                evidence_id="doc_ev_003",
                evidence_ref="ev_att_c3_003",
                attachment_id="att_c3_003",
                page_number=1,
                quote="delivery postponed",
                method="PDF_TEXT",
                method_version="p1-pdf-v1",
            )
        ],
        extracted_at=NOW - timedelta(minutes=1),
    )

    with pytest.raises(SourceContractError):
        MessageIntelligenceService().analyze(
            message("See attached", attachments=[attachment]),
            attachments=[stale],
            attachment_records=[record],
            now=NOW,
        )
