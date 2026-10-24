"""C3 message-intelligence contracts: fixture-only, with no provider/network sends."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
from app.message_intelligence.contracts import (
    CustomerInquiryCandidate,
    ProviderCompletion,
    VerifiedSupplierIdentity,
)
from app.message_intelligence.providers import (
    BudgetPolicy,
    GeminiProvider,
    ProviderError,
    ProviderRate,
    QwenProvider,
)
from app.message_intelligence.service import MessageIntelligenceService, SourceContractError

NOW = datetime(2026, 10, 25, 4, 0, tzinfo=UTC)
TENANT = "tenant_c3_test"


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


class ScriptedProvider:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0
        self.prompts = []

    def complete(self, prompt, *, max_output_tokens):
        self.calls += 1
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str):
            return ProviderCompletion(content=reply, input_tokens=80, output_tokens=30)
        return reply


class CapturingHttpTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, headers, body, *, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "body": json.loads(body),
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


def assessment_json(
    *, intent, topic=None, claim_kind, segment_id, text, start=0, end=None, value="true"
):
    end = len(text) if end is None else end
    return json.dumps(
        {
            "intent": intent,
            "inquiry_topic": topic,
            "claims": [
                {
                    "kind": claim_kind,
                    "value": value,
                    "evidence": {
                        "segment_id": segment_id,
                        "quote": text[start:end],
                        "start": start,
                        "end": end,
                    },
                }
            ],
        }
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


def make_test_budget() -> BudgetPolicy:
    rate = ProviderRate(Decimal(1), Decimal(1))
    return BudgetPolicy(
        max_analysis_cost_usd=Decimal(1),
        max_input_tokens=12_000,
        max_output_tokens=512,
        qwen_rate=rate,
        gemini_rate=rate,
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


def test_semantic_supplier_delay_preserves_deterministic_reference_and_eta_evidence():
    text = "Our PO-991 delivery is held up, expected 2026-10-28."
    start = text.index("held up")
    qwen = ScriptedProvider(
        assessment_json(
            intent="SUPPLIER_DELAY",
            claim_kind="SUPPLIER_DELAY",
            segment_id="s0",
            text=text,
            start=start,
            end=start + len("held up"),
            value="reported delay",
        )
    )
    gemini = ScriptedProvider(ProviderError("must_not_be_called"))

    result = MessageIntelligenceService(
        qwen=qwen, gemini=gemini, budget_policy=make_test_budget()
    ).analyze(message(text), now=NOW)

    assert result.supplier_delay.delivery_reference == "PO-991"
    assert result.supplier_delay.delivery_reference_evidence.quote == "PO-991"
    assert result.supplier_delay.reported_eta_text == "2026-10-28"
    assert result.supplier_delay.reported_eta_evidence.quote == "2026-10-28"
    assert result.supplier_delay.review_required is True


def test_output_token_ceiling_falls_back_to_gemini():
    text = "Would availability be possible later this week?"
    qwen = ScriptedProvider(
        ProviderCompletion(
            content=assessment_json(
                intent="CUSTOMER_INQUIRY",
                topic="AVAILABILITY",
                claim_kind="INQUIRY",
                segment_id="s0",
                text=text,
            ),
            input_tokens=80,
            output_tokens=513,
        )
    )
    gemini = ScriptedProvider(
        assessment_json(
            intent="CUSTOMER_INQUIRY",
            topic="AVAILABILITY",
            claim_kind="INQUIRY",
            segment_id="s0",
            text=text,
        )
    )

    result = MessageIntelligenceService(
        qwen=qwen, gemini=gemini, budget_policy=make_test_budget()
    ).analyze(message(text), now=NOW)

    assert [attempt.error_code for attempt in result.provider_attempts] == [
        "OUTPUT_LIMIT_EXCEEDED",
        None,
    ]
    assert result.provider == "GEMINI"
    assert result.customer_inquiry is not None


def test_qwen_valid_output_is_used_without_gemini_fallback():
    text = "What would be the best option for getting this to our office?"
    qwen = ScriptedProvider(
        assessment_json(
            intent="CUSTOMER_INQUIRY",
            topic="DELIVERY",
            claim_kind="INQUIRY",
            segment_id="s0",
            text=text,
        )
    )
    gemini = ScriptedProvider(ProviderError("must_not_be_called"))
    msg = message(text)

    result = MessageIntelligenceService(
        qwen=qwen, gemini=gemini, budget_policy=make_test_budget()
    ).analyze(msg, association=verified_customer_association(msg), now=NOW)

    assert result.intent == "CUSTOMER_INQUIRY"
    assert result.provider == "QWEN"
    assert qwen.calls == 1
    assert gemini.calls == 0
    assert result.customer_inquiry.evidence[0].quote == text
    assert result.customer_inquiry.evidence[0].message_id == msg.message_id


@pytest.mark.parametrize(
    "qwen_failure",
    [
        ProviderError("TIMEOUT", retryable=False),
        '{"intent":"CUSTOMER_INQUIRY","inquiry_topic":"PRICE","unexpected":true}',
    ],
)
def test_gemini_fallback_runs_after_qwen_failure_or_invalid_schema(qwen_failure):
    text = "Would the shipment reach our office before Friday?"
    qwen = ScriptedProvider(qwen_failure)
    gemini = ScriptedProvider(
        assessment_json(
            intent="CUSTOMER_INQUIRY",
            topic="DELIVERY",
            claim_kind="INQUIRY",
            segment_id="s0",
            text=text,
        )
    )
    msg = message(text)

    result = MessageIntelligenceService(
        qwen=qwen, gemini=gemini, budget_policy=make_test_budget()
    ).analyze(msg, association=verified_customer_association(msg), now=NOW)

    assert result.provider == "GEMINI"
    assert qwen.calls == 1
    assert gemini.calls == 1
    assert result.customer_inquiry is not None
    assert result.review_required is False


def test_retryable_qwen_timeout_retries_once_before_accepting_valid_result():
    text = "What would be the best option for getting this to our office?"
    qwen = ScriptedProvider(
        ProviderError("TIMEOUT", retryable=True),
        assessment_json(
            intent="CUSTOMER_INQUIRY",
            topic="DELIVERY",
            claim_kind="INQUIRY",
            segment_id="s0",
            text=text,
        ),
    )
    gemini = ScriptedProvider(ProviderError("must_not_be_called"))
    msg = message(text)

    result = MessageIntelligenceService(
        qwen=qwen, gemini=gemini, budget_policy=make_test_budget()
    ).analyze(msg, association=verified_customer_association(msg), now=NOW)

    assert result.provider == "QWEN"
    assert [attempt.status for attempt in result.provider_attempts] == ["TIMEOUT", "VALID"]
    assert qwen.calls == 2
    assert gemini.calls == 0


def test_explicit_cost_budget_blocks_calls_without_configured_rates():
    text = "Would availability be possible later this week?"
    qwen = ScriptedProvider(ProviderError("must_not_be_called"))
    gemini = ScriptedProvider(ProviderError("must_not_be_called"))
    msg = message(text)
    no_rates = BudgetPolicy(
        max_analysis_cost_usd=Decimal("0.05"),
        max_input_tokens=12_000,
        max_output_tokens=512,
        qwen_rate=None,
        gemini_rate=None,
    )

    result = MessageIntelligenceService(qwen=qwen, gemini=gemini, budget_policy=no_rates).analyze(
        msg, now=NOW
    )

    assert qwen.calls == gemini.calls == 0
    assert result.review_required is True
    assert "SEMANTIC_BUDGET_EXCEEDED" in result.review_reasons


def test_semantic_output_that_contradicts_deterministic_delay_signal_falls_back_and_reviews():
    text = "Our PO-991 delivery is delayed, and the PO-992 delivery will also be delayed."
    qwen = ScriptedProvider(
        assessment_json(
            intent="CUSTOMER_INQUIRY",
            topic="OTHER",
            claim_kind="INQUIRY",
            segment_id="s0",
            text=text,
        )
    )
    gemini = ScriptedProvider(
        assessment_json(
            intent="CUSTOMER_INQUIRY",
            topic="OTHER",
            claim_kind="INQUIRY",
            segment_id="s0",
            text=text,
        )
    )
    msg = message(text)

    result = MessageIntelligenceService(
        qwen=qwen, gemini=gemini, budget_policy=make_test_budget()
    ).analyze(msg, association=verified_customer_association(msg), now=NOW)

    assert qwen.calls == gemini.calls == 1
    assert result.intent == "UNKNOWN"
    assert result.customer_inquiry is None
    assert result.review_required is True
    assert "DETERMINISTIC_CONTRADICTION" in result.review_reasons


def test_incompatible_model_claim_kinds_fall_back_and_create_review_candidate():
    text = "Would the shipment reach our office before Friday?"
    conflicting = json.loads(
        assessment_json(
            intent="CUSTOMER_INQUIRY",
            topic="DELIVERY",
            claim_kind="INQUIRY",
            segment_id="s0",
            text=text,
        )
    )
    conflicting["claims"].append(
        {
            "kind": "SUPPLIER_DELAY",
            "value": "reported delay",
            "evidence": conflicting["claims"][0]["evidence"],
        }
    )
    invalid_output = json.dumps(conflicting)
    qwen = ScriptedProvider(invalid_output)
    gemini = ScriptedProvider(invalid_output)

    result = MessageIntelligenceService(
        qwen=qwen, gemini=gemini, budget_policy=make_test_budget()
    ).analyze(message(text), now=NOW)

    assert qwen.calls == gemini.calls == 1
    assert [attempt.status for attempt in result.provider_attempts] == [
        "INVALID_OUTPUT",
        "INVALID_OUTPUT",
    ]
    assert result.intent == "UNKNOWN"
    assert result.customer_inquiry is None
    assert result.review_required is True
    assert result.human_review_candidate is not None
    assert result.human_review_candidate.source == result.source
    assert result.p2_event_created is False
    assert result.p4_send_attempted is False


def test_qwen_client_uses_configured_regional_endpoint_and_bounded_structured_request():
    content = assessment_json(intent="OTHER", claim_kind="INQUIRY", segment_id="s0", text="hello")
    transport = CapturingHttpTransport(
        SimpleNamespace(
            status=200,
            body=json.dumps(
                {
                    "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 20},
                }
            ).encode(),
        )
    )
    provider = QwenProvider(
        api_key="test-qwen-secret",
        api_base_url="https://region.example/model/v1",
        model_id="qwen-test",
        timeout_seconds=4,
        transport=transport,
    )

    completion = provider.complete([("s0", "hello")], max_output_tokens=96)

    call = transport.calls[0]
    assert call["url"] == "https://region.example/model/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer test-qwen-secret"
    assert call["body"]["max_tokens"] == 96
    assert call["body"]["response_format"] == {"type": "json_object"}
    assert '"additionalProperties":false' in call["body"]["messages"][0]["content"]
    assert "tenant_c3_test" not in json.dumps(call["body"])
    assert completion.input_tokens == 50 and completion.output_tokens == 20


def test_qwen_truncated_output_is_classified_for_fallback():
    transport = CapturingHttpTransport(
        SimpleNamespace(
            status=200,
            body=json.dumps(
                {
                    "choices": [
                        {
                            "message": {"content": '{"intent":"UNKNOWN"'},
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 96},
                }
            ).encode(),
        )
    )
    provider = QwenProvider(
        api_key="test-qwen-secret",
        api_base_url="https://region.example/v1",
        model_id="qwen-test",
        transport=transport,
    )

    with pytest.raises(ProviderError) as error:
        provider.complete([("s0", "hello")], max_output_tokens=96)

    assert error.value.code == "OUTPUT_LIMIT_EXCEEDED"
    assert "test-qwen-secret" not in str(error.value)


def test_gemini_client_uses_header_key_and_json_schema_response():
    content = assessment_json(intent="OTHER", claim_kind="INQUIRY", segment_id="s0", text="hello")
    transport = CapturingHttpTransport(
        SimpleNamespace(
            status=200,
            body=json.dumps(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": content}]}, "finishReason": "STOP"}
                    ],
                    "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 20},
                }
            ).encode(),
        )
    )
    provider = GeminiProvider(
        api_key="test-gemini-secret", model_id="gemini-test", transport=transport
    )

    completion = provider.complete([("s0", "hello")], max_output_tokens=96)

    call = transport.calls[0]
    assert call["url"].endswith("/models/gemini-test:generateContent")
    assert call["headers"]["x-goog-api-key"] == "test-gemini-secret"
    assert "key=" not in call["url"]
    assert call["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert call["body"]["generationConfig"]["responseJsonSchema"]["additionalProperties"] is False
    assert completion.input_tokens == 50 and completion.output_tokens == 20


def test_gemini_max_token_finish_reason_is_not_accepted_as_complete():
    transport = CapturingHttpTransport(
        SimpleNamespace(
            status=200,
            body=json.dumps(
                {
                    "candidates": [
                        {
                            "content": {"parts": [{"text": '{"intent":"UNKNOWN"'}]},
                            "finishReason": "MAX_TOKENS",
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 96},
                }
            ).encode(),
        )
    )
    provider = GeminiProvider(
        api_key="test-gemini-secret", model_id="gemini-test", transport=transport
    )

    with pytest.raises(ProviderError) as error:
        provider.complete([("s0", "hello")], max_output_tokens=96)

    assert error.value.code == "OUTPUT_LIMIT_EXCEEDED"


def test_provider_failure_classification_does_not_echo_response_body_or_secret():
    transport = CapturingHttpTransport(
        SimpleNamespace(status=429, body=b"token=test-qwen-secret private input")
    )
    provider = QwenProvider(
        api_key="test-qwen-secret",
        api_base_url="https://region.example/v1",
        model_id="qwen-test",
        transport=transport,
    )

    with pytest.raises(ProviderError) as error:
        provider.complete([("s0", "hello")], max_output_tokens=64)

    assert error.value.code == "RATE_LIMITED"
    assert error.value.retryable is True
    assert "test-qwen-secret" not in str(error.value)
    assert "private input" not in str(error.value)


def test_invalid_qwen_evidence_falls_back_and_invalid_gemini_requires_review():
    text = "Would availability be possible later this week?"
    malformed = json.loads(
        assessment_json(
            intent="CUSTOMER_INQUIRY",
            topic="AVAILABILITY",
            claim_kind="INQUIRY",
            segment_id="s0",
            text=text,
            start=0,
            end=8,
        )
    )
    malformed["claims"][0]["evidence"]["quote"] = "not source"
    qwen = ScriptedProvider(json.dumps(malformed))
    gemini = ScriptedProvider(json.dumps(malformed))
    msg = message(text)

    result = MessageIntelligenceService(
        qwen=qwen, gemini=gemini, budget_policy=make_test_budget()
    ).analyze(msg, association=verified_customer_association(msg), now=NOW)

    assert qwen.calls == gemini.calls == 1
    assert result.provider == "NONE"
    assert result.review_required is True
    assert "AI_OUTPUT_INVALID" in result.review_reasons
    assert result.customer_inquiry is None


def test_cross_tenant_association_is_rejected_before_provider_call():
    msg = message("What is your price?")
    association = verified_customer_association(msg).model_copy(
        update={"tenant_id": "tenant_other"}
    )
    provider = ScriptedProvider(ProviderError("must_not_be_called"))

    with pytest.raises(SourceContractError):
        MessageIntelligenceService(qwen=provider, budget_policy=make_test_budget()).analyze(
            msg, association=association, now=NOW
        )

    assert provider.calls == 0


def test_unverified_identity_keeps_inquiry_candidate_in_human_review():
    msg = message("How much does it cost?")

    result = MessageIntelligenceService().analyze(msg, now=NOW)

    assert result.customer_inquiry is not None
    assert result.customer_inquiry.identity_status == "UNVERIFIED"
    assert result.customer_inquiry.review_required is True
    assert "SENDER_IDENTITY_UNVERIFIED" in result.customer_inquiry.review_reasons


def test_provider_never_receives_tenant_sender_or_unredacted_contact_data():
    text = "Please email alice@example.com about delivery to +60123456789."
    qwen = ScriptedProvider(
        assessment_json(
            intent="OTHER",
            claim_kind="INQUIRY",
            segment_id="s0",
            text="",
        )
    )
    msg = message(text)

    MessageIntelligenceService(qwen=qwen, budget_policy=make_test_budget()).analyze(msg, now=NOW)

    prompt = "\n".join(text for _, text in qwen.prompts[0])
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


def test_qwen_supplier_candidate_maps_each_claim_to_existing_document_evidence():
    quote = "The shipment for PO-450 has moved to 2026-10-29."
    attachment = {
        "attachment_id": "att_c3_004",
        "filename": "supplier_update.pdf",
        "media_type": "application/pdf",
        "size_bytes": 144,
        "evidence_ref": "ev_att_c3_004",
    }
    record = AttachmentRecord(
        attachment_id="att_c3_004",
        tenant_id=TENANT,
        evidence_ref="ev_att_c3_004",
        filename="supplier_update.pdf",
        media_type="application/pdf",
        size_bytes=144,
        content_sha256="e" * 64,
        created_at=NOW,
    )
    extraction = DocumentExtractionResult(
        attachment_id="att_c3_004",
        evidence_ref="ev_att_c3_004",
        status="SUCCESS",
        document_type="PDF",
        page_count=1,
        text_content=quote,
        evidence_items=[
            DocumentEvidence(
                evidence_id="doc_ev_004",
                evidence_ref="ev_att_c3_004",
                attachment_id="att_c3_004",
                page_number=1,
                quote=quote,
                method="PDF_TEXT",
                method_version="p1-pdf-v1",
            )
        ],
        extracted_at=NOW,
    )
    claims = []
    for kind, value in (
        ("SUPPLIER_DELAY", "true"),
        ("DELIVERY_REFERENCE", "PO-450"),
        ("REPORTED_ETA", "2026-10-29"),
    ):
        claims.append(
            {
                "kind": kind,
                "value": value,
                "evidence": {
                    "segment_id": "s1",
                    "quote": quote,
                    "start": 0,
                    "end": len(quote),
                },
            }
        )
    qwen = ScriptedProvider(
        json.dumps(
            {
                "intent": "SUPPLIER_DELAY",
                "inquiry_topic": None,
                "claims": claims,
            }
        )
    )
    msg = message("Please review the attached supplier update.", attachments=[attachment])

    result = MessageIntelligenceService(
        qwen=qwen,
        budget_policy=make_test_budget(),
        supplier_identity_resolver=VerifiedSupplierResolver(),
    ).analyze(msg, attachments=[extraction], attachment_records=[record], now=NOW)

    candidate = result.supplier_delay
    assert result.provider == "QWEN"
    assert candidate is not None
    assert candidate.supplier_identity_status == "VERIFIED"
    assert candidate.delivery_reference == "PO-450"
    assert candidate.delivery_reference_evidence.evidence_id == "doc_ev_004"
    assert candidate.reported_eta_text == "2026-10-29"
    assert candidate.reported_eta_evidence.evidence_ref == "ev_att_c3_004"
    assert candidate.review_required is True
    assert result.p2_event_created is False


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
