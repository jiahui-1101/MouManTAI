"""C3 side-effect-free analysis orchestrator over existing P1 source records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol

from pydantic import ValidationError

from app.context.association_schemas import IdentityLinkStatus, MessageAssociationRecord
from app.context.document_schemas import (
    AttachmentRecord,
    DocumentEvidence,
    DocumentExtractionResult,
)
from app.context.ingestion_schemas import StoredMessage

from .contracts import (
    AnalysisOutcome,
    AttachmentSourceSnapshot,
    CustomerInquiryCandidate,
    EvidenceLink,
    Intent,
    ProviderAttempt,
    ProviderProvenance,
    SemanticAssessment,
    SemanticClaim,
    SourceMessageReference,
    SupplierDelaySignalCandidate,
    VerifiedSupplierIdentity,
)
from .deterministic import RULE_VERSION, classify_deterministically
from .privacy import redact_sensitive_text
from .providers import (
    AnalysisBudget,
    BudgetPolicy,
    GeminiProvider,
    ProviderError,
    QwenProvider,
    SemanticProvider,
)


class SourceContractError(ValueError):
    """The source snapshot crossed tenant, identity, or evidence boundaries."""


class SupplierIdentityResolver(Protocol):
    def resolve_supplier(
        self, *, tenant_id: str, channel: str, sender_identity_id: str
    ) -> VerifiedSupplierIdentity | dict | None: ...


class C3Limits(Protocol):
    max_input_characters: int
    max_segments: int
    max_provider_retries: int


class DefaultLimits:
    def __init__(self, max_input_characters=4_000, max_segments=32, max_provider_retries=1):
        self.max_input_characters = max_input_characters
        self.max_segments = max_segments
        self.max_provider_retries = max_provider_retries

    @classmethod
    def from_env(cls):
        import os

        chars = int(os.environ.get("C3_AI_MAX_INPUT_CHARS", "4000"))
        segments = int(os.environ.get("C3_AI_MAX_SEGMENTS", "32"))
        retries = int(os.environ.get("C3_AI_MAX_RETRIES", "1"))
        if not 256 <= chars <= 4_000 or not 1 <= segments <= 32 or not 0 <= retries <= 1:
            raise ValueError("C3 analysis limits exceed the reviewed safe bounds")
        return cls(chars, segments, retries)


class MessageIntelligenceService:
    """Classify immutable P1 messages without persistence or business side effects."""

    def __init__(
        self,
        *,
        qwen: SemanticProvider | None = None,
        gemini: SemanticProvider | None = None,
        supplier_identity_resolver: SupplierIdentityResolver | None = None,
        budget_policy: BudgetPolicy | None = None,
        limits: C3Limits | None = None,
    ):
        self.qwen, self.gemini = qwen, gemini
        self.supplier_identity_resolver = supplier_identity_resolver
        self.budget_policy = budget_policy
        self.limits = limits or DefaultLimits()

    @classmethod
    def from_env(
        cls, *, supplier_identity_resolver: SupplierIdentityResolver | None = None, transport=None
    ):
        """Create configured provider clients; no credential or provider call is made here."""
        return cls(
            qwen=QwenProvider.from_env(transport=transport),
            gemini=GeminiProvider.from_env(transport=transport),
            supplier_identity_resolver=supplier_identity_resolver,
            budget_policy=BudgetPolicy.from_env(),
            limits=DefaultLimits.from_env(),
        )

    def analyze(
        self,
        message: StoredMessage,
        *,
        association: MessageAssociationRecord | None = None,
        attachments: Sequence[DocumentExtractionResult] = (),
        attachment_records: Sequence[AttachmentRecord] = (),
        now: datetime | None = None,
    ) -> AnalysisOutcome:
        analyzed_at = now or datetime.now(UTC)
        if analyzed_at.tzinfo is None or analyzed_at.utcoffset() is None:
            raise SourceContractError("analysis time must be offset-aware")
        self._validate_source(message, association)
        evidence_items, attachment_reasons, attachment_record_map = self._validate_attachments(
            message, attachments, attachment_records, analyzed_at
        )
        source = self._source_reference(message, attachment_record_map, attachments)
        identity_status, customer_id, association_id, association_version, association_updated_at = (
            self._customer_identity(message, association, analyzed_at)
        )
        deterministic = classify_deterministically(message, tuple(evidence_items))
        reasons = list(deterministic.review_reasons) + attachment_reasons
        provider_attempts: list[ProviderAttempt] = []
        selected_provider = "RULE" if not deterministic.needs_semantic_provider else "NONE"
        provider_version = RULE_VERSION if selected_provider == "RULE" else "unavailable"
        intent: Intent = deterministic.intent
        topic = deterministic.topic
        evidence = list(deterministic.evidence)
        assessment: SemanticAssessment | None = None
        claim_evidence: list[tuple[SemanticClaim, EvidenceLink]] = []

        # If deterministic facts conflict, semantic output cannot overrule that
        # source conflict. AI may still be sampled to populate review provenance.
        should_call_model = deterministic.needs_semantic_provider or deterministic.conflict
        if should_call_model:
            segments, privacy_by_segment, segment_error = self._prompt_segments(
                message, evidence_items
            )
            if segment_error:
                reasons.append(segment_error)
            else:
                assessment, provider_name, model_id = self._classify_with_fallback(
                    segments,
                    privacy_by_segment,
                    provider_attempts,
                    expected_intent=(
                        deterministic.intent
                        if deterministic.intent not in {"UNKNOWN", "OTHER"}
                        else None
                    ),
                    expected_topic=deterministic.topic,
                    expected_delivery_reference=deterministic.delivery_reference,
                    expected_eta=deterministic.reported_eta_text,
                    documents={item.evidence_id: item for item in evidence_items},
                )
                if assessment is not None:
                    selected_provider = provider_name
                    provider_version = model_id
                    if deterministic.conflict:
                        intent, topic = "UNKNOWN", None
                        reasons.append("DETERMINISTIC_SIGNALS_CONFLICT")
                    else:
                        reasons = [
                            reason
                            for reason in reasons
                            if reason != "CLASSIFICATION_REQUIRES_SEMANTIC_REVIEW"
                        ]
                        intent, topic = assessment.intent, assessment.inquiry_topic
                        claim_evidence = self._assessment_claim_evidence(
                            assessment,
                            segments,
                            privacy_by_segment,
                            {item.evidence_id: item for item in evidence_items},
                        )
                        evidence = [link for _, link in claim_evidence]
                elif not provider_attempts or all(
                    attempt.status == "NOT_CONFIGURED" for attempt in provider_attempts
                ):
                    reasons.append("SEMANTIC_PROVIDER_UNAVAILABLE")
                elif not any(attempt.status == "BUDGET_EXCEEDED" for attempt in provider_attempts):
                    if any(attempt.status == "INVALID_OUTPUT" for attempt in provider_attempts):
                        reasons.append(
                            "DETERMINISTIC_CONTRADICTION"
                            if any(
                                attempt.error_code == "DETERMINISTIC_CONTRADICTION"
                                for attempt in provider_attempts
                            )
                            else "AI_OUTPUT_INVALID"
                        )
                    else:
                        reasons.append("SEMANTIC_PROVIDER_FAILED")
                else:
                    reasons.append("SEMANTIC_BUDGET_EXCEEDED")
                if intent in {"UNKNOWN", "CUSTOMER_ORDER_REQUEST"}:
                    reasons.append("HUMAN_REVIEW_REQUIRED")

        if deterministic.conflict:
            intent, topic = "UNKNOWN", None
            if "DETERMINISTIC_SIGNALS_CONFLICT" not in reasons:
                reasons.append("DETERMINISTIC_SIGNALS_CONFLICT")
        elif deterministic.intent == "CUSTOMER_ORDER_REQUEST":
            intent = "CUSTOMER_ORDER_REQUEST"
            topic = None
            reasons.append("ORDER_REQUEST_REQUIRES_BACKEND_HANDOFF")

        customer_candidate: CustomerInquiryCandidate | None = None
        supplier_candidate: SupplierDelaySignalCandidate | None = None
        if intent == "CUSTOMER_INQUIRY":
            inquiry_evidence = [item for item in evidence if item]
            if not inquiry_evidence:
                intent, topic = "UNKNOWN", None
                reasons.append("INQUIRY_EVIDENCE_MISSING")
            else:
                inquiry_reasons = list(reasons)
                if identity_status != "LINK_VERIFIED":
                    inquiry_reasons.append(
                        "SENDER_IDENTITY_UNVERIFIED"
                        if identity_status == "UNVERIFIED"
                        else "SENDER_IDENTITY_AMBIGUOUS"
                    )
                customer_candidate = CustomerInquiryCandidate(
                    tenant_id=message.raw.tenant_id,
                    source=source,
                    customer_id=customer_id if identity_status == "LINK_VERIFIED" else None,
                    identity_status=identity_status,
                    association_id=association_id,
                    association_version=association_version,
                    association_updated_at=association_updated_at,
                    topic=topic or "OTHER",
                    evidence=inquiry_evidence,
                    provenance=ProviderProvenance(
                        provider=selected_provider, version=provider_version
                    ),
                    analyzed_at=analyzed_at,
                    review_required=bool(inquiry_reasons),
                    review_reasons=inquiry_reasons,
                )
                reasons.extend(reason for reason in inquiry_reasons if reason not in reasons)
        if intent == "SUPPLIER_DELAY":
            delay_evidence = [item for item in evidence if item]
            if not delay_evidence:
                intent = "UNKNOWN"
                reasons.append("DELAY_EVIDENCE_MISSING")
            else:
                supplier_identity, identity_error = self._supplier_identity(message, analyzed_at)
                supplier_reasons = list(reasons)
                supplier_reasons.append("REPORTED_CLAIM_NOT_AUTHORITATIVE")
                if identity_error:
                    supplier_reasons.append(identity_error)
                elif supplier_identity is None:
                    supplier_reasons.append("SUPPLIER_IDENTITY_UNVERIFIED")
                supplier_candidate = SupplierDelaySignalCandidate(
                    tenant_id=message.raw.tenant_id,
                    source=source,
                    supplier_id=supplier_identity.supplier_id if supplier_identity else None,
                    supplier_identity_status="VERIFIED" if supplier_identity else "UNVERIFIED",
                    supplier_identity_version=supplier_identity.version
                    if supplier_identity
                    else None,
                    supplier_identity_checked_at=supplier_identity.checked_at
                    if supplier_identity
                    else None,
                    supplier_identity_evidence_refs=supplier_identity.evidence_refs
                    if supplier_identity
                    else [],
                    delivery_reference=(
                        deterministic.delivery_reference
                        or self._claim_value_and_evidence(claim_evidence, "DELIVERY_REFERENCE")[0]
                    ),
                    delivery_reference_evidence=(
                        deterministic.delivery_reference_evidence
                        or self._claim_value_and_evidence(claim_evidence, "DELIVERY_REFERENCE")[1]
                    ),
                    reported_eta_text=(
                        deterministic.reported_eta_text
                        or self._claim_value_and_evidence(claim_evidence, "REPORTED_ETA")[0]
                    ),
                    reported_eta_evidence=(
                        deterministic.reported_eta_evidence
                        or self._claim_value_and_evidence(claim_evidence, "REPORTED_ETA")[1]
                    ),
                    evidence=delay_evidence,
                    provenance=ProviderProvenance(
                        provider=selected_provider, version=provider_version
                    ),
                    analyzed_at=analyzed_at,
                    review_required=True,
                    review_reasons=list(dict.fromkeys(supplier_reasons)),
                )
                reasons.extend(reason for reason in supplier_reasons if reason not in reasons)

        if intent == "UNKNOWN" and not any(
            value in reasons
            for value in (
                "SEMANTIC_PROVIDER_UNAVAILABLE",
                "SEMANTIC_PROVIDER_FAILED",
                "HUMAN_REVIEW_REQUIRED",
                "DETERMINISTIC_SIGNALS_CONFLICT",
                "CLASSIFICATION_REQUIRES_SEMANTIC_REVIEW",
            )
        ):
            reasons.append("CLASSIFICATION_UNKNOWN")
        if attachment_reasons and not reasons:
            reasons.extend(attachment_reasons)
        review_required = bool(reasons) or intent == "UNKNOWN"
        return AnalysisOutcome(
            tenant_id=message.raw.tenant_id,
            source=source,
            intent=intent,
            inquiry_topic=topic,
            provider=selected_provider,
            provider_version=provider_version,
            provider_attempts=provider_attempts,
            customer_inquiry=customer_candidate,
            supplier_delay=supplier_candidate,
            review_required=review_required,
            review_reasons=list(dict.fromkeys(reasons)),
            analyzed_at=analyzed_at,
        )

    def _classify_with_fallback(
        self,
        segments,
        privacy_by_segment,
        attempts,
        *,
        expected_intent,
        expected_topic,
        expected_delivery_reference,
        expected_eta,
        documents,
    ):
        ledger = AnalysisBudget(self.budget_policy)
        last_error = None
        providers = (("QWEN", self.qwen), ("GEMINI", self.gemini))
        for provider_name, provider in providers:
            if provider is None:
                attempts.append(
                    ProviderAttempt(
                        provider=provider_name,
                        attempt_number=1,
                        status="NOT_CONFIGURED",
                        error_code="NOT_CONFIGURED",
                        duration_ms=0,
                    )
                )
                last_error = "NOT_CONFIGURED"
                continue
            for attempt_number in range(1, self.limits.max_provider_retries + 2):
                started = monotonic()
                reserved_cost = None
                try:
                    reserved_cost = ledger.reserve(provider_name, segments)
                    completion = provider.complete(
                        segments,
                        max_output_tokens=(
                            self.budget_policy.max_output_tokens if self.budget_policy else 0
                        ),
                    )
                    if (
                        completion.input_tokens > self.budget_policy.max_input_tokens
                        or completion.output_tokens > self.budget_policy.max_output_tokens
                    ):
                        raise ProviderError("OUTPUT_LIMIT_EXCEEDED")
                    assessment = SemanticAssessment.model_validate_json(completion.content)
                    linked = self._assessment_claim_evidence(
                        assessment, segments, privacy_by_segment, documents
                    )
                    self._validate_claim_values(linked)
                    claimed_delivery_refs = {
                        claim.value
                        for claim in assessment.claims
                        if claim.kind == "DELIVERY_REFERENCE"
                    }
                    claimed_etas = {
                        claim.value for claim in assessment.claims if claim.kind == "REPORTED_ETA"
                    }
                    if (
                        (expected_intent and assessment.intent != expected_intent)
                        or (expected_topic and assessment.inquiry_topic != expected_topic)
                        or (
                            expected_delivery_reference
                            and claimed_delivery_refs
                            and claimed_delivery_refs != {expected_delivery_reference}
                        )
                        or (expected_eta and claimed_etas and claimed_etas != {expected_eta})
                    ):
                        raise ProviderError("DETERMINISTIC_CONTRADICTION")
                    attempts.append(
                        ProviderAttempt(
                            provider=provider_name,
                            attempt_number=attempt_number,
                            status="VALID",
                            input_tokens=completion.input_tokens,
                            output_tokens=completion.output_tokens,
                            estimated_cost_usd=float(reserved_cost),
                            duration_ms=max(0, int((monotonic() - started) * 1000)),
                        )
                    )
                    return (
                        assessment,
                        provider_name,
                        completion.model_id or getattr(provider, "model_id", provider_name),
                    )
                except ProviderError as error:
                    last_error = error.code
                    status = self._attempt_status(error.code)
                    attempts.append(
                        ProviderAttempt(
                            provider=provider_name,
                            attempt_number=attempt_number,
                            status=status,
                            error_code=error.code,
                            estimated_cost_usd=float(reserved_cost)
                            if reserved_cost is not None
                            else None,
                            duration_ms=max(0, int((monotonic() - started) * 1000)),
                        )
                    )
                    if error.retryable and attempt_number <= self.limits.max_provider_retries:
                        continue
                    break
                except (ValidationError, ValueError, KeyError, TypeError):
                    last_error = "INVALID_OUTPUT"
                    attempts.append(
                        ProviderAttempt(
                            provider=provider_name,
                            attempt_number=attempt_number,
                            status="INVALID_OUTPUT",
                            error_code="INVALID_OUTPUT",
                            estimated_cost_usd=float(reserved_cost)
                            if reserved_cost is not None
                            else None,
                            duration_ms=max(0, int((monotonic() - started) * 1000)),
                        )
                    )
                    break
                except Exception:  # noqa: BLE001 - injected provider errors fail closed without leaking details
                    # Never echo provider exception text: it may contain request data or credentials.
                    last_error = "PROVIDER_ERROR"
                    attempts.append(
                        ProviderAttempt(
                            provider=provider_name,
                            attempt_number=attempt_number,
                            status="PROVIDER_ERROR",
                            error_code="PROVIDER_ERROR",
                            estimated_cost_usd=float(reserved_cost)
                            if reserved_cost is not None
                            else None,
                            duration_ms=max(0, int((monotonic() - started) * 1000)),
                        )
                    )
                    break
        return None, "NONE", (last_error or "unavailable")

    @staticmethod
    def _attempt_status(code: str):
        if code == "TIMEOUT":
            return "TIMEOUT"
        if code == "RATE_LIMITED":
            return "RATE_LIMITED"
        if code == "BUDGET_EXCEEDED":
            return "BUDGET_EXCEEDED"
        if code in {"INVALID_OUTPUT", "OUTPUT_LIMIT_EXCEEDED", "DETERMINISTIC_CONTRADICTION"}:
            return "INVALID_OUTPUT"
        return "PROVIDER_ERROR"

    def _prompt_segments(self, message: StoredMessage, documents: list[DocumentEvidence]):
        originals: list[tuple[str, str, str]] = [
            ("MESSAGE_TEXT", message.raw.text, message.message_id)
        ]
        originals.extend(("DOCUMENT_EVIDENCE", item.quote, item.evidence_id) for item in documents)
        if (
            len(originals) > self.limits.max_segments
            or sum(len(text) for _, text, _ in originals) > self.limits.max_input_characters
        ):
            return [], {}, "AI_INPUT_BUDGET_EXCEEDED"
        segments: list[tuple[str, str]] = []
        privacy: dict[str, tuple[str, str, str, object]] = {}
        for index, (kind, original, source_ref) in enumerate(originals):
            segment_id = f"s{index}"
            projection = redact_sensitive_text(original)
            segments.append((segment_id, projection.text))
            privacy[segment_id] = (kind, original, source_ref, projection)
        return segments, privacy, None

    def _assessment_claim_evidence(
        self, assessment: SemanticAssessment, segments, privacy_by_segment, documents
    ):
        segment_map = {segment_id: text for segment_id, text in segments}
        pairs: list[tuple[SemanticClaim, EvidenceLink]] = []
        for claim in assessment.claims:
            citation = claim.evidence
            projected = segment_map.get(citation.segment_id)
            source = privacy_by_segment.get(citation.segment_id)
            if projected is None or source is None or citation.end > len(projected):
                raise ProviderError("INVALID_OUTPUT")
            kind, original, source_ref, redacted = source
            if projected[
                citation.start : citation.end
            ] != citation.quote or redacted.overlaps_hidden(citation.start, citation.end):
                raise ProviderError("INVALID_OUTPUT")
            original_quote = original[citation.start : citation.end]
            if original_quote != citation.quote:
                raise ProviderError("INVALID_OUTPUT")
            if kind == "MESSAGE_TEXT":
                link = EvidenceLink(
                    source_kind="MESSAGE_TEXT",
                    message_id=source_ref,
                    quote=original_quote,
                    start=citation.start,
                    end=citation.end,
                )
            else:
                # The model cites the full existing P1 evidence item. It cannot
                # manufacture offsets or a new OCR/PDF evidence identifier.
                if citation.start != 0 or citation.end != len(original):
                    raise ProviderError("INVALID_OUTPUT")
                doc = documents.get(source_ref)
                if doc is None:
                    raise ProviderError("INVALID_OUTPUT")
                link = EvidenceLink(
                    source_kind="DOCUMENT_EVIDENCE",
                    evidence_id=doc.evidence_id,
                    evidence_ref=doc.evidence_ref,
                    attachment_id=doc.attachment_id,
                    page_number=doc.page_number,
                    quote=doc.quote,
                )
            pairs.append((claim, link))
        if not pairs:
            raise ProviderError("INVALID_OUTPUT")
        return pairs

    @staticmethod
    def _validate_claim_values(pairs: list[tuple[SemanticClaim, EvidenceLink]]):
        for claim, link in pairs:
            if (
                claim.kind in {"DELIVERY_REFERENCE", "REPORTED_ETA"}
                and claim.value not in link.quote
            ):
                raise ProviderError("INVALID_OUTPUT")

    @staticmethod
    def _claim_value_and_evidence(pairs: list[tuple[SemanticClaim, EvidenceLink]], kind: str):
        return next(
            ((claim.value, link) for claim, link in pairs if claim.kind == kind), (None, None)
        )

    @staticmethod
    def _source_reference(
        message: StoredMessage, attachment_records, extractions
    ) -> SourceMessageReference:
        raw = message.raw
        results_by_ref = {item.evidence_ref: item for item in extractions}
        attachment_sources = []
        for source_attachment in raw.attachments:
            record = attachment_records.get(source_attachment.evidence_ref)
            extraction = results_by_ref.get(source_attachment.evidence_ref) if record else None
            attachment_sources.append(
                AttachmentSourceSnapshot(
                    attachment_id=source_attachment.attachment_id,
                    evidence_ref=source_attachment.evidence_ref,
                    media_type=source_attachment.media_type,
                    size_bytes=source_attachment.size_bytes,
                    content_sha256=record.content_sha256 if record else None,
                    attachment_created_at=record.created_at if record else None,
                    extraction_status=extraction.status if extraction else None,
                    extracted_at=extraction.extracted_at if extraction else None,
                    evidence_ids=[item.evidence_id for item in extraction.evidence_items]
                    if extraction
                    else [],
                    extraction_method_versions=sorted(
                        {item.method_version for item in extraction.evidence_items}
                    )
                    if extraction
                    else [],
                )
            )
        return SourceMessageReference(
            tenant_id=raw.tenant_id,
            message_id=message.message_id,
            channel=raw.channel,
            provider_message_id=raw.provider_message_id,
            content_sha256=message.content_sha256,
            received_at=raw.received_at,
            message_at=raw.message_at,
            thread_ref=raw.thread_ref,
            reply_to_provider_message_id=raw.reply_to_provider_message_id,
            attachment_evidence_refs=[item.evidence_ref for item in raw.attachments],
            attachment_sources=attachment_sources,
        )

    @staticmethod
    def _validate_source(message: StoredMessage, association: MessageAssociationRecord | None):
        if not message.raw.tenant_id or not message.message_id or len(message.content_sha256) != 64:
            raise SourceContractError("message source identity or digest is invalid")
        if association is not None:
            if (
                association.tenant_id != message.raw.tenant_id
                or association.message_id != message.message_id
            ):
                raise SourceContractError(
                    "message association does not match source tenant and message"
                )
            if association.updated_at.tzinfo is None or association.updated_at.utcoffset() is None:
                raise SourceContractError("message association timestamp must be offset-aware")

    @staticmethod
    def _customer_identity(message: StoredMessage, association, now):
        if association is None:
            return "UNVERIFIED", None, None, None, None
        if association.status != IdentityLinkStatus.LINK_VERIFIED:
            status = (
                "AMBIGUOUS" if association.status == IdentityLinkStatus.CONFLICT else "UNVERIFIED"
            )
            return status, None, association.association_id, association.version, association.updated_at
        customer = association.verified_customer
        if (
            customer is None
            or customer.active is not True
            or customer.tenant_id != message.raw.tenant_id
        ):
            return (
                "AMBIGUOUS",
                None,
                association.association_id,
                association.version,
                association.updated_at,
            )
        exact_contact = any(
            contact.channel == message.raw.channel
            and contact.sender_identity_id == message.raw.sender_identity_id
            for contact in customer.verified_contacts
        )
        if not exact_contact or association.updated_at > now:
            return (
                "AMBIGUOUS",
                None,
                association.association_id,
                association.version,
                association.updated_at,
            )
        return (
            "LINK_VERIFIED",
            customer.customer_id,
            association.association_id,
            association.version,
            association.updated_at,
        )

    @staticmethod
    def _validate_attachments(message, attachments, attachment_records, now):
        expected = {item.evidence_ref: item for item in message.raw.attachments}
        records: dict[str, AttachmentRecord] = {}
        for record in attachment_records:
            source_attachment = expected.get(record.evidence_ref)
            if (
                source_attachment is None
                or record.tenant_id != message.raw.tenant_id
                or source_attachment.attachment_id != record.attachment_id
                or source_attachment.filename != record.filename
                or source_attachment.media_type != record.media_type
                or source_attachment.size_bytes != record.size_bytes
            ):
                raise SourceContractError(
                    "attachment record does not match source tenant and message metadata"
                )
            if record.evidence_ref in records:
                raise SourceContractError("duplicate tenant-scoped attachment record")
            if (
                record.created_at.tzinfo is None
                or record.created_at.utcoffset() is None
                or record.created_at > now
            ):
                raise SourceContractError("attachment record timestamp is invalid")
            records[record.evidence_ref] = record
        seen: set[str] = set()
        evidence: list[DocumentEvidence] = []
        reasons: list[str] = []
        for result in attachments:
            record = expected.get(result.evidence_ref)
            if record is None or record.attachment_id != result.attachment_id:
                raise SourceContractError("attachment extraction does not match the message source")
            if result.evidence_ref in seen:
                raise SourceContractError("duplicate attachment extraction result")
            seen.add(result.evidence_ref)
            trusted_record = records.get(result.evidence_ref)
            if trusted_record is None:
                reasons.append("ATTACHMENT_METADATA_UNVERIFIED")
                continue
            if (
                result.extracted_at.tzinfo is None
                or result.extracted_at.utcoffset() is None
                or result.extracted_at > now
                or result.extracted_at < trusted_record.created_at
            ):
                raise SourceContractError("attachment extraction timestamp is stale or invalid")
            if record.media_type not in {"application/pdf", "image/png", "image/jpeg"}:
                reasons.append("ATTACHMENT_UNSUPPORTED")
                continue
            if result.status in {"FAILED", "UNSUPPORTED"}:
                reasons.append(
                    "ATTACHMENT_EXTRACTION_FAILED"
                    if result.status == "FAILED"
                    else "ATTACHMENT_UNSUPPORTED"
                )
                continue
            if result.status == "PARTIAL":
                reasons.append("ATTACHMENT_EXTRACTION_PARTIAL")
            for item in result.evidence_items:
                if (
                    item.evidence_ref != result.evidence_ref
                    or item.attachment_id != result.attachment_id
                    or item.page_number > result.page_count
                ):
                    raise SourceContractError(
                        "document evidence does not match existing attachment extraction"
                    )
                if len(item.quote) > 500:
                    reasons.append("ATTACHMENT_EVIDENCE_TOO_LONG")
                else:
                    evidence.append(item)
            if not result.evidence_items:
                reasons.append("ATTACHMENT_EVIDENCE_MISSING")
        for evidence_ref, record in expected.items():
            if evidence_ref not in records:
                reasons.append("ATTACHMENT_METADATA_UNVERIFIED")
            if evidence_ref not in seen:
                reasons.append("ATTACHMENT_EXTRACTION_MISSING")
                if record.media_type not in {"application/pdf", "image/png", "image/jpeg"}:
                    reasons.append("ATTACHMENT_UNSUPPORTED")
        return evidence, list(dict.fromkeys(reasons)), records

    def _supplier_identity(self, message: StoredMessage, now: datetime):
        if self.supplier_identity_resolver is None:
            return None, None
        try:
            result = self.supplier_identity_resolver.resolve_supplier(
                tenant_id=message.raw.tenant_id,
                channel=message.raw.channel,
                sender_identity_id=message.raw.sender_identity_id,
            )
            if result is None:
                return None, None
            identity = VerifiedSupplierIdentity.model_validate(result)
        except Exception:  # noqa: BLE001 - identity lookup failures become non-authoritative review candidates
            return None, "SUPPLIER_IDENTITY_LOOKUP_FAILED"
        if (
            identity.tenant_id != message.raw.tenant_id
            or identity.channel != message.raw.channel
            or identity.sender_identity_id != message.raw.sender_identity_id
            or identity.checked_at > now
        ):
            raise SourceContractError(
                "trusted supplier identity result is not bound to this source"
            )
        return identity, None
