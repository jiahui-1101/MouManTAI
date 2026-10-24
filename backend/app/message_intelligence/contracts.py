"""Strict, non-authoritative C3 contracts.

These models are an internal handoff boundary. They are not persistence or
shared Backend A–H schemas and cannot authorize business actions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Intent = Literal[
    "CUSTOMER_INQUIRY",
    "CUSTOMER_ORDER_REQUEST",
    "SUPPLIER_DELAY",
    "OTHER",
    "UNKNOWN",
]
InquiryTopic = Literal["PRICE", "AVAILABILITY", "DELIVERY", "PRODUCT_INFO", "OTHER"]
ClaimKind = Literal[
    "INQUIRY", "SUPPLIER_DELAY", "DELIVERY_REFERENCE", "REPORTED_ETA", "ORDER_REQUEST"
]
ProviderName = Literal["RULE", "QWEN", "GEMINI", "NONE"]


class ProviderEvidence(StrictContract):
    """Ephemeral segment citation returned by a model, never a persisted ID."""

    segment_id: str = Field(min_length=1, max_length=8, pattern=r"^s[0-9]{1,4}$")
    quote: str = Field(min_length=1, max_length=500)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def span_length_matches(self):
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("provider evidence offsets must match quote length")
        return self


class SemanticClaim(StrictContract):
    kind: ClaimKind
    value: str = Field(min_length=1, max_length=200)
    evidence: ProviderEvidence


class SemanticAssessment(StrictContract):
    intent: Intent
    inquiry_topic: InquiryTopic | None = None
    claims: list[SemanticClaim] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def intent_is_supported_by_claim(self):
        kinds = {claim.kind for claim in self.claims}
        if self.intent == "CUSTOMER_INQUIRY":
            if self.inquiry_topic is None or "INQUIRY" not in kinds:
                raise ValueError(
                    "customer inquiry requires a topic and an evidence-backed inquiry claim"
                )
            if kinds & {"SUPPLIER_DELAY", "ORDER_REQUEST"}:
                raise ValueError(
                    "customer inquiry cannot include incompatible order or supplier-delay claims"
                )
        elif self.inquiry_topic is not None:
            raise ValueError("only customer inquiries may declare an inquiry topic")
        if self.intent == "SUPPLIER_DELAY" and "SUPPLIER_DELAY" not in kinds:
            raise ValueError("supplier delay requires an evidence-backed delay claim")
        if self.intent == "SUPPLIER_DELAY" and kinds & {"INQUIRY", "ORDER_REQUEST"}:
            raise ValueError("supplier delay cannot include incompatible inquiry or order claims")
        if self.intent == "CUSTOMER_ORDER_REQUEST" and "ORDER_REQUEST" not in kinds:
            raise ValueError("order request requires an evidence-backed request claim")
        if self.intent == "CUSTOMER_ORDER_REQUEST" and kinds & {"INQUIRY", "SUPPLIER_DELAY"}:
            raise ValueError(
                "order request cannot include incompatible inquiry or supplier-delay claims"
            )
        if self.intent in {"OTHER", "UNKNOWN"} and kinds:
            raise ValueError("other or unknown intent cannot include classified business claims")
        for kind in ("DELIVERY_REFERENCE", "REPORTED_ETA"):
            if len({claim.value for claim in self.claims if claim.kind == kind}) > 1:
                raise ValueError("contradictory values for one supplier-delay field require review")
        return self


class ProviderCompletion(StrictContract):
    content: str = Field(min_length=1, max_length=32_000)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model_id: str | None = Field(default=None, max_length=120)


class ProviderAttempt(StrictContract):
    provider: Literal["QWEN", "GEMINI"]
    attempt_number: int = Field(ge=1, le=2)
    status: Literal[
        "VALID",
        "INVALID_OUTPUT",
        "TIMEOUT",
        "RATE_LIMITED",
        "PROVIDER_ERROR",
        "BUDGET_EXCEEDED",
        "NOT_CONFIGURED",
    ]
    error_code: str | None = Field(default=None, max_length=60)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)


class EvidenceLink(StrictContract):
    """A message span or a citation to existing P1 page evidence."""

    source_kind: Literal["MESSAGE_TEXT", "DOCUMENT_EVIDENCE"]
    quote: str = Field(min_length=1, max_length=500)
    message_id: str | None = Field(default=None, max_length=200)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)
    evidence_id: str | None = Field(default=None, max_length=100)
    evidence_ref: str | None = Field(default=None, max_length=100)
    attachment_id: str | None = Field(default=None, max_length=100)
    page_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def citation_shape_matches_source(self):
        if self.source_kind == "MESSAGE_TEXT":
            if (
                not self.message_id
                or self.start is None
                or self.end is None
                or self.end <= self.start
                or self.end - self.start != len(self.quote)
            ):
                raise ValueError("message evidence requires an exact message text span")
            if any(
                value is not None
                for value in (
                    self.evidence_id,
                    self.evidence_ref,
                    self.attachment_id,
                    self.page_number,
                )
            ):
                raise ValueError("message evidence cannot carry document fields")
        else:
            if not all((self.evidence_id, self.evidence_ref, self.attachment_id, self.page_number)):
                raise ValueError(
                    "document evidence requires existing P1 evidence and page references"
                )
            if self.message_id is not None or self.start is not None or self.end is not None:
                raise ValueError("document evidence does not invent text offsets")
        return self


def _validate_candidate_evidence(
    source: SourceMessageReference, evidence: list[EvidenceLink]
) -> None:
    attachment_sources = {
        (item.evidence_ref, item.attachment_id): set(item.evidence_ids)
        for item in source.attachment_sources
    }
    for link in evidence:
        if link.source_kind == "MESSAGE_TEXT":
            if link.message_id != source.message_id:
                raise ValueError("message evidence must bind to the candidate source message")
        elif link.evidence_id not in attachment_sources.get(
            (link.evidence_ref, link.attachment_id), set()
        ):
            raise ValueError(
                "document evidence must bind to an existing source attachment evidence ID"
            )


class AttachmentSourceSnapshot(StrictContract):
    attachment_id: str = Field(min_length=1, max_length=100)
    evidence_ref: str = Field(min_length=1, max_length=100)
    media_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(ge=0, le=25_000_000)
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    attachment_created_at: datetime | None = None
    extraction_status: Literal["SUCCESS", "PARTIAL", "FAILED", "UNSUPPORTED"] | None = None
    extracted_at: datetime | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    extraction_method_versions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def extraction_timestamp_consistency(self):
        if self.extraction_status is None and (self.extracted_at is not None or self.evidence_ids):
            raise ValueError("attachment evidence requires an extraction result")
        if self.extraction_status is not None and self.extracted_at is None:
            raise ValueError("attachment extraction status requires its source timestamp")
        for timestamp in (self.attachment_created_at, self.extracted_at):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError("attachment source timestamps must be offset-aware")
        if (self.extraction_method_versions and not self.evidence_ids) or len(
            set(self.evidence_ids)
        ) != len(self.evidence_ids):
            raise ValueError("attachment evidence versions require unique existing evidence IDs")
        return self


class SourceMessageReference(StrictContract):
    tenant_id: str = Field(min_length=1, max_length=200)
    message_id: str = Field(min_length=1, max_length=200)
    channel: Literal["WHATSAPP", "EMAIL", "TELEGRAM", "UNKNOWN"]
    provider_message_id: str = Field(min_length=1, max_length=200)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    received_at: datetime
    message_at: datetime | None = None
    thread_ref: str | None = Field(default=None, max_length=200)
    reply_to_provider_message_id: str | None = Field(default=None, max_length=200)
    attachment_evidence_refs: list[str] = Field(default_factory=list, max_length=10)
    attachment_sources: list[AttachmentSourceSnapshot] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def attachment_snapshots_match_message_references(self):
        if [item.evidence_ref for item in self.attachment_sources] != self.attachment_evidence_refs:
            raise ValueError("attachment snapshots must exactly match message attachment refs")
        for timestamp in (self.received_at, self.message_at):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError("source message timestamps must be offset-aware")
        return self


class ProviderProvenance(StrictContract):
    provider: ProviderName
    version: str = Field(min_length=1, max_length=160)


class CustomerInquiryCandidate(StrictContract):
    contract: Literal["customer_inquiry_candidate.v1"] = "customer_inquiry_candidate.v1"
    tenant_id: str = Field(min_length=1, max_length=200)
    source: SourceMessageReference
    customer_id: str | None = Field(default=None, max_length=100)
    identity_status: Literal["LINK_VERIFIED", "UNVERIFIED", "AMBIGUOUS"]
    association_id: str | None = Field(default=None, max_length=200)
    association_version: int | None = Field(default=None, ge=1)
    association_updated_at: datetime | None = None
    topic: InquiryTopic
    evidence: list[EvidenceLink] = Field(min_length=1, max_length=12)
    provenance: ProviderProvenance
    analyzed_at: datetime
    review_required: bool
    review_reasons: list[str] = Field(default_factory=list, max_length=20)
    candidate_only: Literal[True] = True

    @model_validator(mode="after")
    def tenant_and_identity_bindings(self):
        if self.source.tenant_id != self.tenant_id:
            raise ValueError("candidate and source tenant must match")
        _validate_candidate_evidence(self.source, self.evidence)
        if self.identity_status != "LINK_VERIFIED" and self.customer_id is not None:
            raise ValueError("unverified customer identity cannot expose a linked customer ID")
        if self.identity_status == "LINK_VERIFIED" and (
            self.customer_id is None
            or self.association_id is None
            or self.association_version is None
            or self.association_updated_at is None
        ):
            raise ValueError("verified customer identity requires a versioned association source")
        if self.review_reasons and not self.review_required:
            raise ValueError("review reasons require Human Review")
        if self.analyzed_at.tzinfo is None or self.analyzed_at.utcoffset() is None:
            raise ValueError("analysis timestamp must be offset-aware")
        if self.association_updated_at is not None and (
            self.association_updated_at.tzinfo is None
            or self.association_updated_at.utcoffset() is None
        ):
            raise ValueError("association timestamp must be offset-aware")
        if (
            self.identity_status == "LINK_VERIFIED"
            and self.association_updated_at is not None
            and self.association_updated_at > self.analyzed_at
        ):
            raise ValueError("association timestamp cannot be newer than the analysis")
        return self


class SupplierDelaySignalCandidate(StrictContract):
    contract: Literal["supplier_delay_signal_candidate.v1"] = "supplier_delay_signal_candidate.v1"
    tenant_id: str = Field(min_length=1, max_length=200)
    source: SourceMessageReference
    supplier_id: str | None = Field(default=None, max_length=100)
    supplier_identity_status: Literal["VERIFIED", "UNVERIFIED", "AMBIGUOUS"]
    supplier_identity_version: int | None = Field(default=None, ge=1)
    supplier_identity_checked_at: datetime | None = None
    supplier_identity_evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    delivery_reference: str | None = Field(default=None, max_length=200)
    delivery_reference_evidence: EvidenceLink | None = None
    reported_eta_text: str | None = Field(default=None, max_length=200)
    reported_eta_evidence: EvidenceLink | None = None
    evidence: list[EvidenceLink] = Field(min_length=1, max_length=12)
    provenance: ProviderProvenance
    analyzed_at: datetime
    review_required: Literal[True] = True
    review_reasons: list[str] = Field(min_length=1, max_length=20)
    candidate_only: Literal[True] = True

    @model_validator(mode="after")
    def tenant_and_supplier_bindings(self):
        if self.source.tenant_id != self.tenant_id:
            raise ValueError("candidate and source tenant must match")
        relevant_evidence = list(self.evidence)
        if self.delivery_reference_evidence is not None:
            relevant_evidence.append(self.delivery_reference_evidence)
        if self.reported_eta_evidence is not None:
            relevant_evidence.append(self.reported_eta_evidence)
        _validate_candidate_evidence(self.source, relevant_evidence)
        if self.supplier_identity_status == "VERIFIED":
            if (
                not self.supplier_id
                or self.supplier_identity_version is None
                or self.supplier_identity_checked_at is None
                or not self.supplier_identity_evidence_refs
            ):
                raise ValueError(
                    "verified supplier identity requires trusted versioned source evidence"
                )
        elif (
            self.supplier_id is not None
            or self.supplier_identity_version is not None
            or self.supplier_identity_checked_at is not None
        ):
            raise ValueError("unverified supplier identity cannot expose a linked supplier ID")
        if (self.delivery_reference is None) != (self.delivery_reference_evidence is None):
            raise ValueError("delivery reference requires its own evidence link")
        if (self.reported_eta_text is None) != (self.reported_eta_evidence is None):
            raise ValueError("reported ETA requires its own evidence link")
        if (
            self.delivery_reference is not None
            and self.delivery_reference not in self.delivery_reference_evidence.quote
        ):
            raise ValueError("delivery reference must appear in its cited source evidence")
        if (
            self.reported_eta_text is not None
            and self.reported_eta_text not in self.reported_eta_evidence.quote
        ):
            raise ValueError("reported ETA must appear in its cited source evidence")
        if self.supplier_identity_checked_at is not None and (
            self.supplier_identity_checked_at.tzinfo is None
            or self.supplier_identity_checked_at.utcoffset() is None
        ):
            raise ValueError("supplier identity timestamp must be offset-aware")
        if (
            self.supplier_identity_checked_at is not None
            and self.supplier_identity_checked_at > self.analyzed_at
        ):
            raise ValueError("supplier identity check cannot be newer than the analysis")
        if self.analyzed_at.tzinfo is None or self.analyzed_at.utcoffset() is None:
            raise ValueError("analysis timestamp must be offset-aware")
        return self


class HumanReviewCandidate(StrictContract):
    contract: Literal["message_intelligence_review_candidate.v1"] = (
        "message_intelligence_review_candidate.v1"
    )
    tenant_id: str = Field(min_length=1, max_length=200)
    source: SourceMessageReference
    intent: Intent
    review_reasons: list[str] = Field(min_length=1, max_length=20)
    evidence: list[EvidenceLink] = Field(default_factory=list, max_length=12)
    provenance: ProviderProvenance
    analyzed_at: datetime
    candidate_only: Literal[True] = True

    @model_validator(mode="after")
    def source_and_reason_bindings(self):
        if self.source.tenant_id != self.tenant_id:
            raise ValueError("review candidate and source tenant must match")
        _validate_candidate_evidence(self.source, self.evidence)
        if self.analyzed_at.tzinfo is None or self.analyzed_at.utcoffset() is None:
            raise ValueError("analysis timestamp must be offset-aware")
        return self


class AnalysisOutcome(StrictContract):
    tenant_id: str = Field(min_length=1, max_length=200)
    source: SourceMessageReference
    intent: Intent
    inquiry_topic: InquiryTopic | None = None
    provider: ProviderName
    provider_version: str
    provider_attempts: list[ProviderAttempt] = Field(default_factory=list, max_length=4)
    customer_inquiry: CustomerInquiryCandidate | None = None
    supplier_delay: SupplierDelaySignalCandidate | None = None
    human_review_candidate: HumanReviewCandidate | None = None
    review_required: bool
    review_reasons: list[str] = Field(default_factory=list, max_length=20)
    analyzed_at: datetime
    p2_event_created: Literal[False] = False
    p4_send_attempted: Literal[False] = False

    @model_validator(mode="after")
    def candidate_consistency(self):
        if self.source.tenant_id != self.tenant_id:
            raise ValueError("analysis and source tenant must match")
        for candidate in (self.customer_inquiry, self.supplier_delay):
            if candidate is not None and (
                candidate.tenant_id != self.tenant_id or candidate.source != self.source
            ):
                raise ValueError("candidate must bind to the exact analysis source")
        if self.review_required:
            if self.human_review_candidate is None:
                raise ValueError("review-required analysis must include a Human Review candidate")
            if (
                self.human_review_candidate.tenant_id != self.tenant_id
                or self.human_review_candidate.source != self.source
                or self.human_review_candidate.intent != self.intent
                or self.human_review_candidate.review_reasons != self.review_reasons
                or self.human_review_candidate.analyzed_at != self.analyzed_at
            ):
                raise ValueError("Human Review candidate must bind to the exact analysis outcome")
        elif self.human_review_candidate is not None or self.review_reasons:
            raise ValueError("review candidate and reasons require Human Review")
        if self.analyzed_at.tzinfo is None or self.analyzed_at.utcoffset() is None:
            raise ValueError("analysis timestamp must be offset-aware")
        return self


class VerifiedSupplierIdentity(StrictContract):
    """Trusted resolver result. Only an injected server-side registry reader may create it."""

    tenant_id: str = Field(min_length=1, max_length=200)
    channel: Literal["WHATSAPP", "EMAIL", "TELEGRAM", "UNKNOWN"]
    sender_identity_id: str = Field(min_length=1, max_length=200)
    supplier_id: str = Field(min_length=1, max_length=100)
    status: Literal["VERIFIED"]
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    checked_at: datetime
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def checked_at_is_aware(self):
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("supplier identity check time must be offset-aware")
        return self
