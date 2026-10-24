"""C3 side-effect-free analysis orchestrator over existing P1 source records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from app.context.ai.protocol import InferenceFailure
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
    HumanReviewCandidate,
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


class ProviderEvidenceError(ValueError):
    """A semantic result cannot be linked to the exact P1 evidence."""


class SemanticGatewayResult(Protocol):
    assessment: SemanticAssessment
    provider: str
    model_id: str
    attempts: Sequence[ProviderAttempt]


class SemanticGateway(Protocol):
    """The owner-reviewed P1 provider boundary must implement this task."""

    def classify(self, segments: list[tuple[str, str]]) -> SemanticGatewayResult: ...


class SourceContractError(ValueError):
    """The source snapshot crossed tenant, identity, or evidence boundaries."""


class SupplierIdentityResolver(Protocol):
    def resolve_supplier(
        self, *, tenant_id: str, channel: str, sender_identity_id: str
    ) -> VerifiedSupplierIdentity | dict | None: ...


class C3Limits(Protocol):
    max_input_characters: int
    max_segments: int


class DefaultLimits:
    def __init__(self, max_input_characters=4_000, max_segments=32):
        self.max_input_characters = max_input_characters
        self.max_segments = max_segments

    @classmethod
    def from_env(cls):
        import os

        chars = int(os.environ.get("C3_AI_MAX_INPUT_CHARS", "4000"))
        segments = int(os.environ.get("C3_AI_MAX_SEGMENTS", "32"))
        if not 256 <= chars <= 4_000 or not 1 <= segments <= 32:
            raise ValueError("C3 analysis limits exceed the reviewed safe bounds")
        return cls(chars, segments)


class MessageIntelligenceService:
    """Classify immutable P1 messages without persistence or business side effects."""

    def __init__(
        self,
        *,
        semantic_gateway: SemanticGateway | None = None,
        supplier_identity_resolver: SupplierIdentityResolver | None = None,
        limits: C3Limits | None = None,
    ):
        self.semantic_gateway = semantic_gateway
        self.supplier_identity_resolver = supplier_identity_resolver
        self.limits = limits or DefaultLimits()

    @classmethod
    def from_env(cls, *, supplier_identity_resolver: SupplierIdentityResolver | None = None):
        """Activate C3 only through the configured P1 provider boundary."""
        from .p1_gateway import P1ClassificationGateway

        return cls(
            semantic_gateway=P1ClassificationGateway.from_env_or_none(),
            supplier_identity_resolver=supplier_identity_resolver,
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
        (
            identity_status,
            customer_id,
            association_id,
            association_version,
            association_updated_at,
        ) = self._customer_identity(message, association, analyzed_at)
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

        # A source conflict is a Human Review condition, never a model vote.
        should_call_model = deterministic.needs_semantic_provider and not deterministic.conflict
        if should_call_model:
            segments, privacy_by_segment, segment_error = self._prompt_segments(
                message, evidence_items
            )
            if segment_error:
                reasons.append(segment_error)
            else:
                if self.semantic_gateway is None:
                    reasons.append("SEMANTIC_PROVIDER_UNAVAILABLE")
                else:
                    try:
                        result = self.semantic_gateway.classify(segments)
                        if result.provider not in {"QWEN", "GEMINI"}:
                            raise ValueError("invalid semantic provider provenance")
                        assessment = SemanticAssessment.model_validate(result.assessment)
                        claim_evidence = self._assessment_claim_evidence(
                            assessment,
                            segments,
                            privacy_by_segment,
                            {item.evidence_id: item for item in evidence_items},
                        )
                        self._validate_claim_values(claim_evidence)
                        delivery_refs = {
                            claim.value
                            for claim in assessment.claims
                            if claim.kind == "DELIVERY_REFERENCE"
                        }
                        reported_etas = {
                            claim.value
                            for claim in assessment.claims
                            if claim.kind == "REPORTED_ETA"
                        }
                        if (
                            (
                                deterministic.intent not in {"UNKNOWN", "OTHER"}
                                and assessment.intent != deterministic.intent
                            )
                            or (
                                deterministic.topic
                                and assessment.inquiry_topic != deterministic.topic
                            )
                            or (
                                deterministic.delivery_reference
                                and delivery_refs
                                and delivery_refs != {deterministic.delivery_reference}
                            )
                            or (
                                deterministic.reported_eta_text
                                and reported_etas
                                and reported_etas != {deterministic.reported_eta_text}
                            )
                        ):
                            raise SourceContractError("deterministic source contradiction")
                    except SourceContractError:
                        reasons.append("DETERMINISTIC_CONTRADICTION")
                    except (ValueError, TypeError):
                        reasons.append("AI_OUTPUT_INVALID")
                    except InferenceFailure as failure:
                        reasons.append("SEMANTIC_PROVIDER_FAILED")
                        audit = failure.audit or {}
                        provider_attempts.append(ProviderAttempt(
                            provider="QWEN", attempt_number=1,
                            status=self._attempt_status(audit.get("primary_error", failure.code)),
                            error_code=audit.get("primary_error", failure.code),
                            duration_ms=audit.get("primary_latency_ms", failure.latency_ms or 0),
                        ))
                        if audit.get("fallback_attempts", 0):
                            provider_attempts.append(ProviderAttempt(
                                provider="GEMINI", attempt_number=1,
                                status=self._attempt_status(audit.get("fallback_error")),
                                error_code=audit.get("fallback_error"),
                                duration_ms=audit.get("fallback_latency_ms", 0),
                            ))
                    except Exception:  # noqa: BLE001 - never echo provider text
                        reasons.append("SEMANTIC_PROVIDER_FAILED")
                    else:
                        provider_attempts = list(result.attempts)
                        selected_provider = result.provider
                        provider_version = result.model_id
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
                            evidence = [link for _, link in claim_evidence]
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
        review_reasons = list(dict.fromkeys(reasons))
        human_review_candidate = (
            HumanReviewCandidate(
                tenant_id=message.raw.tenant_id,
                source=source,
                intent=intent,
                review_reasons=review_reasons,
                evidence=evidence,
                provenance=ProviderProvenance(provider=selected_provider, version=provider_version),
                analyzed_at=analyzed_at,
            )
            if review_required
            else None
        )
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
            human_review_candidate=human_review_candidate,
            review_required=review_required,
            review_reasons=review_reasons,
            analyzed_at=analyzed_at,
        )

    def _prompt_segments(self, message: StoredMessage, documents: list[DocumentEvidence]):
        originals: list[tuple[str, str, str]] = [
            ("MESSAGE_TEXT", message.raw.text, message.message_id)
        ]
        originals.extend(("DOCUMENT_EVIDENCE", item.quote, item.evidence_id) for item in documents)
        if (
            len(originals) > min(self.limits.max_segments, 4)
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
                raise ProviderEvidenceError("SOURCE_EVIDENCE_INVALID")
            kind, original, source_ref, redacted = source
            if projected[
                citation.start : citation.end
            ] != citation.quote or redacted.overlaps_hidden(citation.start, citation.end):
                raise ProviderEvidenceError("SOURCE_EVIDENCE_INVALID")
            original_quote = original[citation.start : citation.end]
            if original_quote != citation.quote:
                raise ProviderEvidenceError("SOURCE_EVIDENCE_INVALID")
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
                    raise ProviderEvidenceError("SOURCE_EVIDENCE_INVALID")
                doc = documents.get(source_ref)
                if doc is None:
                    raise ProviderEvidenceError("INVALID_OUTPUT")
                link = EvidenceLink(
                    source_kind="DOCUMENT_EVIDENCE",
                    evidence_id=doc.evidence_id,
                    evidence_ref=doc.evidence_ref,
                    attachment_id=doc.attachment_id,
                    page_number=doc.page_number,
                    quote=doc.quote,
                )
            pairs.append((claim, link))
        if not pairs and assessment.intent not in {"UNKNOWN", "OTHER"}:
            raise ProviderEvidenceError("INVALID_OUTPUT")
        return pairs

    @staticmethod
    def _validate_claim_values(pairs: list[tuple[SemanticClaim, EvidenceLink]]):
        for claim, link in pairs:
            if (
                claim.kind in {"DELIVERY_REFERENCE", "REPORTED_ETA"}
                and claim.value not in link.quote
            ):
                raise ProviderEvidenceError("SOURCE_EVIDENCE_INVALID")

    @staticmethod
    def _claim_value_and_evidence(pairs: list[tuple[SemanticClaim, EvidenceLink]], kind: str):
        return next(
            ((claim.value, link) for claim, link in pairs if claim.kind == kind), (None, None)
        )

    @staticmethod
    def _attempt_status(code: str | None):
        if code == "timeout":
            return "TIMEOUT"
        if code == "rate_limited":
            return "RATE_LIMITED"
        if code == "response_budget_exceeded":
            return "BUDGET_EXCEEDED"
        if code in {"credentials_missing", "provider_disabled"}:
            return "NOT_CONFIGURED"
        if code in {"invalid_json", "schema_validation", "incomplete_or_invalid_output", "invalid_output"}:
            return "INVALID_OUTPUT"
        return "PROVIDER_ERROR"

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
            provider=message.provider,
            provider_account_id=raw.provider_account_id,
            provider_native_message_id=raw.provider_native_message_id,
            sender_identity_id=raw.sender_identity_id,
            source_authenticity=raw.source_authenticity,
            adapter_mode=raw.adapter_mode,
            relationship_source=raw.relationship_source,
            content_sha256=message.content_sha256,
            source_updated_at=message.updated_at,
            extractor_version=message.extractor_version,
            received_at=raw.received_at,
            message_at=raw.message_at,
            thread_ref=raw.thread_ref,
            reply_to_provider_message_id=raw.reply_to_provider_message_id,
            rfc_message_id=raw.rfc_message_id,
            rfc_in_reply_to=raw.rfc_in_reply_to,
            rfc_references=raw.rfc_references,
            native_attachment_source_ids=raw.native_attachment_source_ids,
            attachment_evidence_refs=[item.evidence_ref for item in raw.attachments],
            attachment_sources=attachment_sources,
        )

    @staticmethod
    def _validate_source(message: StoredMessage, association: MessageAssociationRecord | None):
        if not message.raw.tenant_id or not message.message_id or len(message.content_sha256) != 64:
            raise SourceContractError("message source identity or digest is invalid")
        if message.raw.adapter_mode == "REAL" and (
            message.raw.source_authenticity != "VERIFIED"
            or not message.raw.provider_account_id
            or not message.raw.provider_native_message_id
        ):
            raise SourceContractError(
                "real channel source has no verified account-bound provenance"
            )
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
            return (
                status,
                None,
                association.association_id,
                association.version,
                association.updated_at,
            )
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
        ):
            raise SourceContractError(
                "trusted supplier identity result is not bound to this source"
            )
        if identity.checked_at > now:
            return None, "SUPPLIER_IDENTITY_CHECK_FROM_FUTURE"
        return identity, None
