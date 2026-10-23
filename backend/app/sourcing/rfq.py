"""Deterministic common RFQ draft. P4 alone may authorize and dispatch."""

from datetime import datetime
from hashlib import sha256
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from app.orders.terms import ImmutableContract, Quantity, Text
from app.suppliers.comparison import CategorySpec, PropertyValue

QUESTIONS = (
    "exact product specifications",
    "pack size",
    "MOQ",
    "unit price and currency",
    "availability and quantity",
    "quotation validity",
    "delivery lead time and arrival",
    "storage and temperature restrictions",
    "safety and quality evidence",
    "freight and delivery costs",
    "applicable conditions",
)


class RFQRequirement(ImmutableContract):
    tenant_id: Text
    sourcing_case_id: Text
    requirement_id: Text
    requirement_version: int = Field(ge=1)
    category_id: Text
    spec_version: int = Field(ge=1)
    sku: Text
    quantity: Quantity
    unit: Text
    hard_properties: tuple[PropertyValue, ...]
    destination: Text | None = None
    needed_by: AwareDatetime
    delivery_window_start: AwareDatetime | None = None
    quality_constraints: tuple[Text, ...] = ()
    approved_notes: tuple[Text, ...] = ()
    recipient_supplier_ids: tuple[Text, ...]
    evidence_refs: tuple[Text, ...]
    business_timezone: Text
    source_context_version: Text
    template_id: Text | None
    template_version: int | None = Field(default=None, ge=1)
    template_approval_ref: Text | None = None

    @model_validator(mode="after")
    def validate_recipients(self):
        if len(set(self.recipient_supplier_ids)) != len(self.recipient_supplier_ids):
            raise ValueError("Duplicate RFQ recipient")
        if not self.recipient_supplier_ids:
            raise ValueError("RFQ recipient required")
        if self.delivery_window_start and self.delivery_window_start > self.needed_by:
            raise ValueError("Delivery window begins after deadline")
        try:
            ZoneInfo(self.business_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown business timezone") from exc
        return self


class RFQEnvelope(ImmutableContract):
    supplier_id: Text
    canonical_content_hash: Text
    eligibility: Literal["IDENTITY_AND_CHANNEL_POLICY_REQUIRED"] = (
        "IDENTITY_AND_CHANNEL_POLICY_REQUIRED"
    )
    dispatch_status: Literal["NOT_SENT"] = "NOT_SENT"


class RFQDraft(ImmutableContract):
    draft_id: Text
    canonical_content_hash: Text
    canonical_content: tuple[tuple[str, str], ...]
    questions: tuple[Text, ...]
    missing_information: tuple[Text, ...]
    readiness: Literal["READY_FOR_P4_REVIEW", "NEEDS_REQUIREMENT_REVIEW"]
    envelopes: tuple[RFQEnvelope, ...]
    source_context_version: Text
    evidence_refs: tuple[Text, ...]
    authorization_dependency: Literal["P4_VERIFIED_IDENTITY_CONSENT_AND_SEND_APPROVAL"] = (
        "P4_VERIFIED_IDENTITY_CONSENT_AND_SEND_APPROVAL"
    )
    dispatch_status: Literal["NOT_SENT"] = "NOT_SENT"


def prepare_rfq(
    request: RFQRequirement,
    schema: CategorySpec | None,
    *,
    now: datetime,
    verified_recipients: frozenset[str] = frozenset(),
) -> RFQDraft:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Offset-aware current time required")
    missing = set()
    if (
        schema is None
        or schema.tenant_id != request.tenant_id
        or schema.category_id != request.category_id
        or schema.version != request.spec_version
        or schema.authority == "EXAMPLE"
        or not schema.approval_ref
    ):
        missing.add("APPROVED_CATEGORY_SPEC")
    else:
        provided = {prop.name for prop in request.hard_properties if prop.evidence_refs}
        missing.update(field.name for field in schema.hard_fields if field.name not in provided)
    if (
        not request.template_id
        or request.template_version is None
        or not request.template_approval_ref
    ):
        missing.add("APPROVED_RFQ_TEMPLATE")
    if not request.evidence_refs:
        missing.add("SOURCE_EVIDENCE")
    if request.needed_by <= now:
        missing.add("REQUIREMENT_EXPIRED")
    missing.update(
        f"SUPPLIER_IDENTITY:{supplier}"
        for supplier in request.recipient_supplier_ids
        if supplier not in verified_recipients
    )
    # The content is shared verbatim. Recipient identity appears only in envelopes.
    content = (
        ("tenant_id", request.tenant_id),
        ("sourcing_case_id", request.sourcing_case_id),
        ("requirement_id", request.requirement_id),
        ("requirement_version", str(request.requirement_version)),
        ("category_id", request.category_id),
        ("spec_version", str(request.spec_version)),
        ("sku", request.sku),
        ("quantity", str(request.quantity)),
        ("unit", request.unit),
        ("needed_by", request.needed_by.isoformat()),
        ("destination", request.destination or "UNKNOWN"),
        (
            "delivery_window_start",
            request.delivery_window_start.isoformat()
            if request.delivery_window_start
            else "UNKNOWN",
        ),
        (
            "hard_properties",
            repr(
                tuple(
                    sorted(
                        (p.name, p.value, p.unit, p.evidence_refs) for p in request.hard_properties
                    )
                )
            ),
        ),
        ("quality_constraints", repr(request.quality_constraints)),
        ("approved_notes", repr(request.approved_notes)),
        ("evidence_refs", repr(request.evidence_refs)),
        ("source_context_version", request.source_context_version),
        ("template", f"{request.template_id or 'UNKNOWN'}:{request.template_version or 'UNKNOWN'}"),
        ("template_approval_ref", request.template_approval_ref or "UNKNOWN"),
    )
    digest = sha256(repr(content).encode("utf-8")).hexdigest()
    draft_digest = sha256(
        repr((digest, tuple(sorted(request.recipient_supplier_ids)))).encode("utf-8")
    ).hexdigest()
    return RFQDraft(
        draft_id=f"rfq-{draft_digest[:20]}",
        canonical_content_hash=digest,
        canonical_content=content,
        questions=QUESTIONS,
        missing_information=tuple(sorted(missing)),
        readiness="NEEDS_REQUIREMENT_REVIEW" if missing else "READY_FOR_P4_REVIEW",
        envelopes=tuple(
            RFQEnvelope(supplier_id=s, canonical_content_hash=digest)
            for s in sorted(request.recipient_supplier_ids)
        ),
        source_context_version=request.source_context_version,
        evidence_refs=request.evidence_refs,
    )
