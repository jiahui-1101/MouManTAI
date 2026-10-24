"""Deterministic-first message classification reusing P1 intent/extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.context.deterministic_extraction import ORDER_RE, extract_explicit_fields
from app.context.document_schemas import DocumentEvidence
from app.context.ingestion_schemas import StoredMessage
from app.context.request_intent import ORDER_IMPERATIVE, REQUEST, request_intent

from .contracts import EvidenceLink, InquiryTopic, Intent

RULE_VERSION = "c3-deterministic-v1"

_TOPIC_PATTERNS: tuple[tuple[InquiryTopic, re.Pattern[str]], ...] = (
    (
        "PRICE",
        re.compile(
            r"\b(?:price|how\s+much|cost|pricing|harga|berapa\s+harga)\b|价格|多少钱|收费",
            re.IGNORECASE,
        ),
    ),
    (
        "AVAILABILITY",
        re.compile(
            r"\b(?:available|availability|in\s+stock|have\s+stock|stock|ada\s+stok)\b|有货|有库存|库存",
            re.IGNORECASE,
        ),
    ),
    (
        "DELIVERY",
        re.compile(
            r"\b(?:delivery|deliver|shipping|ship\s+to|eta|hantar|penghantaran)\b|配送|送货|运送|到货",
            re.IGNORECASE,
        ),
    ),
    (
        "PRODUCT_INFO",
        re.compile(
            r"\b(?:product\s+info|catalog|ingredients|specification|specs)\b|产品信息|成分|规格",
            re.IGNORECASE,
        ),
    ),
)
_INQUIRY_MARKER = re.compile(
    r"\b(?:how\s+much|what\s+is\s+the\s+price|do\s+you\s+(?:have|deliver|sell)|"
    r"is\s+there|can\s+i\s+check|could\s+you\s+(?:share|tell)|available\s+to)\b|"
    r"请问|有没有|多少钱|可以.*吗|是否|berapa\s+(?:harga|banyak)|ada\s+.*tak",
    re.IGNORECASE,
)
_DELAY_MARKER = re.compile(
    r"\b(?:delay(?:ed)?|late|postponed|rescheduled|pushed\s+back|running\s+behind|"
    r"terlewat|lambat|tertunda|ditangguh|lewat)\b|延迟|延期|迟到|推迟|晚到",
    re.IGNORECASE,
)
_ETA_RE = re.compile(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2})?\b")


@dataclass(frozen=True)
class DeterministicResult:
    intent: Intent
    topic: InquiryTopic | None
    evidence: tuple[EvidenceLink, ...]
    delivery_reference: str | None
    delivery_reference_evidence: EvidenceLink | None
    reported_eta_text: str | None
    reported_eta_evidence: EvidenceLink | None
    needs_semantic_provider: bool
    conflict: bool
    review_reasons: tuple[str, ...]


def classify_deterministically(
    message: StoredMessage, documents: tuple[DocumentEvidence, ...] = ()
) -> DeterministicResult:
    """Use stable P1 intent plus conservative local terms; unknowns remain unresolved."""
    text = message.raw.text
    p1_intent = request_intent(text)
    # P1's extraction result is reused as a guard against quietly treating an order
    # request as an inquiry. The C3 package does not map those fields into OrderRequest.
    p1_extraction = extract_explicit_fields(message, catalog=())
    reasons: list[str] = []
    if p1_intent == "ADVERSARIAL":
        return DeterministicResult(
            "UNKNOWN", None, (), None, None, None, None, False, False, ("ADVERSARIAL_SOURCE_TEXT",)
        )

    inquiry_matches: list[tuple[InquiryTopic, EvidenceLink]] = []
    delay_evidence: list[EvidenceLink] = []
    references: list[tuple[str, EvidenceLink]] = []
    eta_values: list[tuple[str, EvidenceLink]] = []
    for pattern_topic, pattern in _TOPIC_PATTERNS:
        for match in pattern.finditer(text):
            inquiry_matches.append(
                (pattern_topic, _message_evidence(message, match.start(), match.end()))
            )
    if _INQUIRY_MARKER.search(text) and not inquiry_matches:
        marker = _INQUIRY_MARKER.search(text)
        assert marker is not None
        inquiry_matches.append(("OTHER", _message_evidence(message, marker.start(), marker.end())))
    for match in _DELAY_MARKER.finditer(text):
        delay_evidence.append(_message_evidence(message, match.start(), match.end()))
    for match in ORDER_RE.finditer(text):
        references.append((match.group(0), _message_evidence(message, match.start(), match.end())))
    for match in _ETA_RE.finditer(text):
        eta_values.append((match.group(0), _message_evidence(message, match.start(), match.end())))

    # Existing attachment extraction contributes only pre-existing page evidence.
    for item in documents:
        for topic, pattern in _TOPIC_PATTERNS:
            if pattern.search(item.quote):
                inquiry_matches.append((topic, _document_evidence(item)))
        if _INQUIRY_MARKER.search(item.quote):
            inquiry_matches.append(("OTHER", _document_evidence(item)))
        if _DELAY_MARKER.search(item.quote):
            delay_evidence.append(_document_evidence(item))
        references.extend(
            (match.group(0), _document_evidence(item)) for match in ORDER_RE.finditer(item.quote)
        )
        eta_values.extend(
            (match.group(0), _document_evidence(item)) for match in _ETA_RE.finditer(item.quote)
        )

    topics = {topic for topic, _ in inquiry_matches}
    explicit_order_language = bool(REQUEST.search(text) or ORDER_IMPERATIVE.search(text))
    extracted_order_fact = any(
        field.field_name in {"sku", "quantity"}
        and field.evidence
        and field.validation_status in {"VALID", "INVALID", "UNRESOLVED"}
        for field in p1_extraction.fields
    )
    order_like = explicit_order_language and p1_intent != "NON_ORDER"
    inquiry = bool(inquiry_matches) and (
        p1_intent == "NON_ORDER"
        or (p1_intent == "UNCLASSIFIED" and bool(_INQUIRY_MARKER.search(text)) and not order_like)
    )
    if extracted_order_fact and explicit_order_language:
        reasons.append("P1_ORDER_FIELDS_REQUIRE_ORDERS_HANDOFF")
    supplier_delay = bool(delay_evidence)
    conflict = (inquiry and supplier_delay) or (len(topics) > 1) or (order_like and inquiry)
    if conflict:
        reasons.append("DETERMINISTIC_SIGNALS_CONFLICT")
    if order_like and not inquiry:
        reasons.append("ORDER_REQUEST_REQUIRES_BACKEND_HANDOFF")
        return DeterministicResult(
            "CUSTOMER_ORDER_REQUEST", None, (), None, None, None, None, False, False, tuple(reasons)
        )
    if conflict:
        return DeterministicResult(
            "UNKNOWN",
            None,
            tuple(link for _, link in inquiry_matches) + tuple(delay_evidence),
            None,
            None,
            None,
            None,
            True,
            True,
            tuple(reasons),
        )
    if inquiry:
        selected = tuple(link for topic, link in inquiry_matches if topic in topics)
        # Multiple mentions of a single topic are valid evidence; different topics
        # remain an explicit review condition rather than being silently collapsed.
        return DeterministicResult(
            "CUSTOMER_INQUIRY",
            next(iter(topics)),
            selected,
            None,
            None,
            None,
            None,
            False,
            False,
            (),
        )
    if supplier_delay:
        unique_references = {value for value, _ in references}
        unique_etas = {value for value, _ in eta_values}
        return DeterministicResult(
            "SUPPLIER_DELAY",
            None,
            tuple(delay_evidence),
            next(iter(unique_references)) if len(unique_references) == 1 else None,
            next((link for value, link in references if value in unique_references), None)
            if len(unique_references) == 1
            else None,
            next(iter(unique_etas)) if len(unique_etas) == 1 else None,
            next((link for value, link in eta_values if value in unique_etas), None)
            if len(unique_etas) == 1
            else None,
            False,
            len(unique_references) > 1 or len(unique_etas) > 1,
            ("CONFLICTING_DELAY_REFERENCES",)
            if len(unique_references) > 1 or len(unique_etas) > 1
            else (),
        )
    if p1_intent in {"CANCELLED", "TENTATIVE", "NON_ORDER"}:
        return DeterministicResult("OTHER", None, (), None, None, None, None, False, False, ())
    unique_references = {value for value, _ in references}
    unique_etas = {value for value, _ in eta_values}
    conflicting_delay_fields = len(unique_references) > 1 or len(unique_etas) > 1
    if conflicting_delay_fields:
        reasons.append("CONFLICTING_DELAY_REFERENCES")
    return DeterministicResult(
        "UNKNOWN",
        None,
        (),
        next(iter(unique_references)) if len(unique_references) == 1 else None,
        next((link for value, link in references if value in unique_references), None)
        if len(unique_references) == 1
        else None,
        next(iter(unique_etas)) if len(unique_etas) == 1 else None,
        next((link for value, link in eta_values if value in unique_etas), None)
        if len(unique_etas) == 1
        else None,
        True,
        conflicting_delay_fields,
        tuple(reasons or ("CLASSIFICATION_REQUIRES_SEMANTIC_REVIEW",)),
    )


def _message_evidence(message: StoredMessage, start: int, end: int) -> EvidenceLink:
    return EvidenceLink(
        source_kind="MESSAGE_TEXT",
        message_id=message.message_id,
        quote=message.raw.text[start:end],
        start=start,
        end=end,
    )


def _document_evidence(item: DocumentEvidence) -> EvidenceLink:
    return EvidenceLink(
        source_kind="DOCUMENT_EVIDENCE",
        evidence_id=item.evidence_id,
        evidence_ref=item.evidence_ref,
        attachment_id=item.attachment_id,
        page_number=item.page_number,
        quote=item.quote,
    )
