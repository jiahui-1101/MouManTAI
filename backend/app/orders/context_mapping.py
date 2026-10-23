"""Pure P1 OrderContext to canonical OrderTerms mapping.

This module prepares a typed candidate from tenant-scoped P1 read records and a
server-resolved commercial evidence snapshot. It does not persist, accept,
reserve, send, publish to Core, or establish customer assent.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from app.context.association_schemas import MessageAssociationRecord
from app.context.ingestion_schemas import StoredMessage
from app.context.order_context_schemas import (
    ContextReviewRecord,
    OrderContextRecord,
    OrderContextVersionRecord,
)
from app.orders.terms import (
    Amount,
    ImmutableContract,
    OrderLine,
    OrderTerms,
    PriceSource,
    Quantity,
    Text,
    compare_terms,
)

MappingReadiness = Literal[
    "READY_FOR_VALIDATION",
    "INCOMPLETE",
    "REVIEW_REQUIRED",
    "STALE_SOURCE",
    "IDENTITY_UNVERIFIED",
    "TERMS_CONFLICT",
    "PRICE_SOURCE_UNVERIFIED",
]

AgreementBasis = Literal[
    "UNKNOWN",
    "CUSTOMER_ORIGINAL_OFFER",
    "MATERIAL_AMENDED_PROPOSAL",
    "CUSTOMER_ASSENTED_PROPOSAL",
]


class CommercialOrderLine(ImmutableContract):
    """Exact commercial line values supplied by an internal source adapter."""

    sku: Text
    # Required even when None: absence from P1 is not a verified "no variant".
    variant: Text | None
    quantity: Quantity
    unit: Text
    unit_price: Amount


class PriceSourceAuthorityEvidence(ImmutableContract):
    """Server adapter result binding an approved source lookup to this tenant/customer."""

    tenant_id: Text
    customer_id: Text
    source_id: Text
    source_version: Text
    status: Literal["VERIFIED", "UNVERIFIED"]
    authority_ref: Text | None = None


class PriceDisclosureEvidence(ImmutableContract):
    """Trusted adapter assertion for disclosure of one exact canonical terms hash."""

    tenant_id: Text
    customer_id: Text
    context_id: Text
    context_version: int = Field(ge=1)
    order_request_id: Text
    terms_revision: int = Field(ge=1)
    terms_hash: Text
    source_id: Text
    source_version: Text
    disclosed_at: AwareDatetime
    disclosure_ref: Text
    verification_status: Literal["VERIFIED", "UNVERIFIED"]
    authority_ref: Text | None = None


class CustomerIdentityAssociationEvidence(ImmutableContract):
    """Versioned P1 association snapshot supporting the verified customer link."""

    association_id: Text
    association_version: int = Field(ge=1)
    message_id: Text
    tenant_id: Text
    customer_id: Text
    updated_at: AwareDatetime


class OrderCommercialEvidence(ImmutableContract):
    """Optional commercial/fulfilment snapshot bound to one P1 context version.

    Values are expected to come from an internal, tenant-scoped adapter. This
    model is not an API request and its presence does not make client data
    authoritative. A future adapter must verify the referenced catalog/quote,
    disclosure record, location, and policy against their source of truth.
    """

    tenant_id: Text
    context_id: Text
    context_version: int = Field(ge=1)
    customer_id: Text
    order_request_id: Text | None = None
    terms_revision: int | None = Field(default=None, ge=1)
    items: tuple[CommercialOrderLine, ...] | None = None
    fulfilment_method: Literal["DELIVERY", "PICKUP"] | None = None
    location_ref: Text | None = None
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    business_timezone: Text | None = None
    currency: str | None = None
    fees: Amount | None = None
    tax: Amount | None = None
    discount: Amount | None = None
    total: Amount | None = None
    price_source: PriceSource | None = None
    price_source_authority: PriceSourceAuthorityEvidence | None = None
    price_disclosure_evidence: tuple[PriceDisclosureEvidence, ...] = ()
    binding_policy_ref: Text | None = None


class AcceptanceCandidate(ImmutableContract):
    """Read-only A→B data contract; never an authorization or reservation token."""

    tenant_id: Text
    order_request_id: Text | None = None
    source_context_id: Text
    source_context_version: int = Field(ge=1)
    source_context_version_record_id: Text | None = None
    context_review_actor_id: Text | None = None
    context_review_actor_role: Text | None = None
    context_reviewed_at: AwareDatetime | None = None
    existing_order_id: Text | None = None
    terms_revision: int | None = Field(default=None, ge=1)
    terms_hash: Text | None = None
    canonical_terms: OrderTerms | None = None
    customer_id: Text | None = None
    customer_identity_evidence: tuple[Text, ...] = ()
    customer_identity_associations: tuple[CustomerIdentityAssociationEvidence, ...] = ()
    source_message_ids: tuple[Text, ...] = ()
    source_evidence_refs: tuple[Text, ...] = ()
    price_source_ref: Text | None = None
    price_disclosure_evidence: tuple[PriceDisclosureEvidence, ...] = ()
    agreement_basis: AgreementBasis = "UNKNOWN"
    proposal_id: Text | None = None
    proposal_version: int | None = Field(default=None, ge=1)
    customer_assent_evidence: tuple[Text, ...] = ()
    readiness_status: MappingReadiness
    validation_reason_codes: tuple[Text, ...] = ()
    missing_fields: tuple[Text, ...] = ()
    conflict_fields: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def terms_and_hash_are_bound(self):
        if (self.canonical_terms is None) != (self.terms_hash is None):
            raise ValueError("Canonical terms and their hash must be present together")
        if self.canonical_terms is not None:
            if self.canonical_terms.tenant_id != self.tenant_id:
                raise ValueError("Candidate tenant must match canonical terms")
            if self.canonical_terms.customer_id != self.customer_id:
                raise ValueError("Candidate customer must match canonical terms")
            if self.canonical_terms.order_request_id != self.order_request_id:
                raise ValueError("Candidate OrderRequest reference must match canonical terms")
            if self.canonical_terms.terms_revision != self.terms_revision:
                raise ValueError("Candidate terms revision must match canonical terms")
            if self.canonical_terms.terms_hash != self.terms_hash:
                raise ValueError("Candidate terms hash does not match canonical terms")
            if not self.customer_identity_associations:
                raise ValueError("Canonical terms require versioned customer identity evidence")
            association_ids = tuple(
                row.association_id for row in self.customer_identity_associations
            )
            if association_ids != self.customer_identity_evidence:
                raise ValueError("Customer identity evidence IDs and versions must match")
            if any(
                row.tenant_id != self.tenant_id
                or row.customer_id != self.customer_id
                or row.message_id not in self.source_message_ids
                for row in self.customer_identity_associations
            ):
                raise ValueError("Customer identity evidence must bind to this candidate")
            if not self.price_disclosure_evidence:
                raise ValueError("Canonical terms require structured price disclosure evidence")
            if any(
                row.tenant_id != self.tenant_id
                or row.customer_id != self.customer_id
                or row.order_request_id != self.order_request_id
                or row.terms_revision != self.terms_revision
                or row.terms_hash != self.terms_hash
                or row.source_id != self.canonical_terms.price_source.source_id
                or row.source_version != self.canonical_terms.price_source.source_version
                or row.disclosed_at != self.canonical_terms.price_source.disclosed_at
                or row.verification_status != "VERIFIED"
                or not row.authority_ref
                for row in self.price_disclosure_evidence
            ):
                raise ValueError("Price disclosure evidence must bind to the exact canonical terms")
        if self.agreement_basis == "UNKNOWN" and self.customer_assent_evidence:
            raise ValueError("Unknown agreement basis cannot carry customer-assent evidence")
        return self


def _unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(value for value in values if isinstance(value, str) and value.strip())
    )


def _context_evidence_refs(context: OrderContextRecord) -> tuple[str, ...]:
    refs: list[str] = []
    for entries in context.field_evidence.values():
        for entry in entries:
            if isinstance(entry, str):
                refs.append(entry)
            elif isinstance(entry, dict):
                for name in ("evidence_ref", "evidence_id"):
                    value = entry.get(name)
                    if isinstance(value, str):
                        refs.append(value)
    return _unique(refs)


def _field_evidence_refs(context: OrderContextRecord, field_name: str) -> tuple[str, ...]:
    refs: list[str] = []
    for entry in context.field_evidence.get(field_name, []):
        if isinstance(entry, str):
            refs.append(entry)
        elif isinstance(entry, dict):
            for name in ("evidence_ref", "evidence_id"):
                value = entry.get(name)
                if isinstance(value, str):
                    refs.append(value)
    return _unique(refs)


def _evidence_source_ids(context: OrderContextRecord) -> set[str]:
    source_ids: set[str] = set()
    for entries in context.field_evidence.values():
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("message_id"), str):
                source_ids.add(entry["message_id"])
    return source_ids


def _make_candidate(
    context: OrderContextRecord,
    *,
    readiness: MappingReadiness,
    current_version: OrderContextVersionRecord | None,
    commercial: OrderCommercialEvidence | None,
    source_evidence_refs: tuple[str, ...],
    identity_evidence: tuple[str, ...] = (),
    identity_associations: tuple[CustomerIdentityAssociationEvidence, ...] = (),
    canonical_terms: OrderTerms | None = None,
    reasons: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
    conflicts: tuple[str, ...] = (),
) -> AcceptanceCandidate:
    reviewed_at = context.last_reviewed_at
    if reviewed_at is not None and (reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None):
        reviewed_at = None
    commercial_matches_context = bool(
        commercial is not None
        and commercial.tenant_id == context.tenant_id
        and commercial.context_id == context.context_id
        and commercial.context_version == context.context_version
        and commercial.customer_id == context.customer_id
    )
    safe_commercial = commercial if commercial_matches_context else None
    validated_commercial = (
        safe_commercial
        if readiness == "READY_FOR_VALIDATION" and canonical_terms is not None
        else None
    )
    # Commercial source and disclosure references can identify another
    # tenant's catalog or customer. Publish them only with a fully validated
    # canonical terms candidate; failure results carry reason codes instead.
    safe_price_source_ref = (
        safe_commercial.price_source.source_id
        if readiness == "READY_FOR_VALIDATION"
        and canonical_terms is not None
        and safe_commercial is not None
        and safe_commercial.price_source is not None
        else None
    )
    safe_disclosure_evidence = (
        safe_commercial.price_disclosure_evidence
        if readiness == "READY_FOR_VALIDATION"
        and canonical_terms is not None
        and safe_commercial is not None
        else ()
    )
    return AcceptanceCandidate(
        tenant_id=context.tenant_id,
        order_request_id=validated_commercial.order_request_id if validated_commercial else None,
        source_context_id=context.context_id,
        source_context_version=context.context_version,
        source_context_version_record_id=current_version.version_id if current_version else None,
        context_review_actor_id=context.last_reviewed_by,
        context_review_actor_role=context.last_reviewed_role,
        context_reviewed_at=reviewed_at,
        existing_order_id=(
            context.order_id
            if readiness == "READY_FOR_VALIDATION" and canonical_terms is not None
            else None
        ),
        terms_revision=validated_commercial.terms_revision if validated_commercial else None,
        terms_hash=canonical_terms.terms_hash if canonical_terms else None,
        canonical_terms=canonical_terms,
        customer_id=context.customer_id,
        customer_identity_evidence=identity_evidence,
        customer_identity_associations=identity_associations,
        source_message_ids=tuple(context.source_message_ids),
        source_evidence_refs=source_evidence_refs,
        price_source_ref=safe_price_source_ref,
        price_disclosure_evidence=safe_disclosure_evidence,
        # P1 extraction/review and a matching terms hash are not customer assent.
        agreement_basis="UNKNOWN",
        proposal_id=None,
        proposal_version=None,
        customer_assent_evidence=(),
        readiness_status=readiness,
        validation_reason_codes=_unique(list(reasons)),
        missing_fields=_unique(list(missing)),
        conflict_fields=_unique(list(conflicts)),
    )


def map_order_context(
    context: OrderContextRecord,
    *,
    current_version: OrderContextVersionRecord | None,
    source_messages: tuple[StoredMessage, ...] | list[StoredMessage],
    associations: tuple[MessageAssociationRecord, ...] | list[MessageAssociationRecord],
    reviews: tuple[ContextReviewRecord, ...] | list[ContextReviewRecord],
    commercial_terms: OrderCommercialEvidence | None,
    existing_core_terms: OrderTerms | None = None,
) -> AcceptanceCandidate:
    """Map one reviewed, current P1 context into existing canonical OrderTerms.

    The caller must load all P1 records through a tenant-scoped trusted adapter.
    This function verifies their supplied bindings and versions, but cannot
    independently prove that those records remain current after it returns.
    Backend B must re-read and revalidate all authority before any decision.
    """

    context_refs = _context_evidence_refs(context)
    base_refs = context_refs

    if current_version is None:
        return _make_candidate(
            context,
            readiness="STALE_SOURCE",
            current_version=None,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("CURRENT_CONTEXT_VERSION_MISSING",),
        )
    if (
        current_version.tenant_id != context.tenant_id
        or current_version.context_id != context.context_id
    ):
        return _make_candidate(
            context,
            readiness="STALE_SOURCE",
            current_version=None,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("CURRENT_CONTEXT_BINDING_MISMATCH",),
        )
    base_refs = _unique(list(context_refs) + [current_version.version_id])
    if current_version.context_version != context.context_version:
        return _make_candidate(
            context,
            readiness="STALE_SOURCE",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("CURRENT_CONTEXT_VERSION_MISMATCH",),
        )
    try:
        version_snapshot = OrderContextRecord.model_validate(current_version.snapshot)
    except ValidationError:
        version_snapshot = None
    if version_snapshot is None or version_snapshot.model_dump(mode="json") != context.model_dump(
        mode="json"
    ):
        return _make_candidate(
            context,
            readiness="STALE_SOURCE",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("CURRENT_CONTEXT_SNAPSHOT_MISMATCH",),
        )

    if not context.source_message_ids:
        return _make_candidate(
            context,
            readiness="INCOMPLETE",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("SOURCE_MESSAGES_MISSING",),
            missing=("source_message_ids",),
        )
    if len(context.source_message_ids) != len(set(context.source_message_ids)):
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("DUPLICATE_SOURCE_MESSAGE_ID",),
        )

    source_by_id = {message.message_id: message for message in source_messages}
    if len(source_by_id) != len(source_messages):
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("DUPLICATE_SOURCE_MESSAGE",),
        )
    if set(source_by_id) != set(context.source_message_ids):
        if not source_by_id or set(context.source_message_ids) - set(source_by_id):
            return _make_candidate(
                context,
                readiness="INCOMPLETE",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=base_refs,
                reasons=("SOURCE_MESSAGE_RECORD_MISSING",),
                missing=("source_messages",),
            )
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("SOURCE_MESSAGE_SET_MISMATCH",),
        )
    if any(message.raw.tenant_id != context.tenant_id for message in source_by_id.values()):
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("SOURCE_TENANT_MISMATCH",),
        )
    if not _evidence_source_ids(context).issubset(set(context.source_message_ids)):
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("EVIDENCE_SOURCE_MISMATCH",),
            conflicts=("source_evidence",),
        )

    if context.customer_identity_status != "LINK_VERIFIED" or not context.customer_id:
        return _make_candidate(
            context,
            readiness="IDENTITY_UNVERIFIED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("CUSTOMER_IDENTITY_UNVERIFIED",),
        )

    association_by_id = {association.message_id: association for association in associations}
    if len(association_by_id) != len(associations):
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("DUPLICATE_SOURCE_ASSOCIATION",),
        )
    if len({row.association_id for row in association_by_id.values()}) != len(association_by_id):
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("DUPLICATE_ASSOCIATION_ID",),
        )
    if set(association_by_id) != set(context.source_message_ids):
        return _make_candidate(
            context,
            readiness="IDENTITY_UNVERIFIED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            reasons=("SOURCE_ASSOCIATION_MISSING_OR_UNEXPECTED",),
        )
    identity_refs = _unique([record.association_id for record in association_by_id.values()])
    for association in association_by_id.values():
        if association.tenant_id != context.tenant_id:
            return _make_candidate(
                context,
                readiness="TERMS_CONFLICT",
                current_version=current_version,
                commercial=None,
                source_evidence_refs=base_refs,
                reasons=("SOURCE_TENANT_MISMATCH",),
            )
        if association.status == "CONFLICT" or association.conflicts:
            return _make_candidate(
                context,
                readiness="TERMS_CONFLICT",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=base_refs,
                identity_evidence=identity_refs,
                reasons=("SOURCE_ASSOCIATION_CONFLICT",),
                conflicts=("customer_identity",),
            )
        if association.status != "LINK_VERIFIED" or association.verified_customer is None:
            unresolved = association.status == "LINK_CANDIDATE" or bool(association.candidates)
            return _make_candidate(
                context,
                readiness="REVIEW_REQUIRED" if unresolved else "IDENTITY_UNVERIFIED",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=base_refs,
                identity_evidence=identity_refs,
                reasons=("ASSOCIATION_UNRESOLVED" if unresolved else "SOURCE_IDENTITY_UNVERIFIED",),
            )
        if (
            association.verified_customer.tenant_id != context.tenant_id
            or association.verified_customer.customer_id != context.customer_id
        ):
            return _make_candidate(
                context,
                readiness="TERMS_CONFLICT",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=base_refs,
                identity_evidence=identity_refs,
                reasons=("SOURCE_CUSTOMER_MISMATCH",),
                conflicts=("customer_identity",),
            )
        order_ref = association.verified_order
        if order_ref is not None and (
            order_ref.tenant_id != context.tenant_id or order_ref.customer_id != context.customer_id
        ):
            return _make_candidate(
                context,
                readiness="TERMS_CONFLICT",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=base_refs,
                identity_evidence=identity_refs,
                reasons=("SOURCE_ORDER_MISMATCH",),
                conflicts=("order_id",),
            )
        if context.order_id and (order_ref is None or order_ref.order_id != context.order_id):
            return _make_candidate(
                context,
                readiness="REVIEW_REQUIRED",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=base_refs,
                identity_evidence=identity_refs,
                reasons=("ORDER_ASSOCIATION_UNVERIFIED",),
                conflicts=("order_id",),
            )
        if not context.order_id and order_ref is not None:
            return _make_candidate(
                context,
                readiness="REVIEW_REQUIRED",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=base_refs,
                identity_evidence=identity_refs,
                reasons=("ORDER_ASSOCIATION_UNRESOLVED",),
                conflicts=("order_id",),
            )

    if any(
        association.updated_at.tzinfo is None or association.updated_at.utcoffset() is None
        for association in association_by_id.values()
    ):
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            reasons=("ASSOCIATION_TIMESTAMP_UNVERIFIED",),
        )
    identity_associations = tuple(
        CustomerIdentityAssociationEvidence(
            association_id=association.association_id,
            association_version=association.version,
            message_id=association.message_id,
            tenant_id=association.tenant_id,
            customer_id=association.verified_customer.customer_id,
            updated_at=association.updated_at,
        )
        for association in association_by_id.values()
    )

    current_reviews = [
        review
        for review in reviews
        if review.tenant_id == context.tenant_id
        and review.context_id == context.context_id
        and review.context_version_after == context.context_version
        and review.action in {"ACCEPT_EXTRACTION", "EDIT_FIELD"}
        and review.actor_id == context.last_reviewed_by
        and review.actor_role == context.last_reviewed_role
    ]
    if (
        context.last_reviewed_at is not None
        and (
            context.last_reviewed_at.tzinfo is None or context.last_reviewed_at.utcoffset() is None
        )
    ) or any(
        review.created_at.tzinfo is None or review.created_at.utcoffset() is None
        for review in current_reviews
    ):
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("CURRENT_CONTEXT_REVIEW_TIMESTAMP_UNVERIFIED",),
        )
    if not current_reviews or not context.last_reviewed_at:
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("CURRENT_CONTEXT_REVIEW_REQUIRED",),
        )

    review = max(current_reviews, key=lambda row: row.created_at)
    base_refs = _unique(list(base_refs) + [review.review_id])
    if review.created_at != context.last_reviewed_at:
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("CURRENT_CONTEXT_REVIEW_MISMATCH",),
        )

    if context.conflicts or context.status == "CONFLICT":
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("CONTEXT_TERMS_CONFLICT",),
            conflicts=("context_fields",),
        )
    if context.status != "INFORMATION_READY" or context.missing_fields:
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("CONTEXT_NOT_READY",),
            missing=tuple(context.missing_fields),
        )

    required_context_evidence = ["sku", "quantity", "unit", "requested_delivery_at"]
    if context.special_instructions:
        required_context_evidence.append("special_instructions")
    missing_context_evidence = tuple(
        f"source_evidence:{field}"
        for field in required_context_evidence
        if not _field_evidence_refs(context, field)
    )
    if missing_context_evidence:
        return _make_candidate(
            context,
            readiness="INCOMPLETE",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("CONTEXT_FIELD_EVIDENCE_MISSING",),
            missing=missing_context_evidence,
        )

    if commercial_terms is None:
        return _make_candidate(
            context,
            readiness="INCOMPLETE",
            current_version=current_version,
            commercial=None,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("COMMERCIAL_EVIDENCE_MISSING",),
            missing=("commercial_terms",),
        )

    commercial_binding = (
        commercial_terms.tenant_id == context.tenant_id
        and commercial_terms.context_id == context.context_id
        and commercial_terms.context_version == context.context_version
        and commercial_terms.customer_id == context.customer_id
    )
    if not commercial_binding:
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=None,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("COMMERCIAL_CONTEXT_BINDING_MISMATCH",),
            conflicts=("commercial_context_binding",),
        )

    if context.core_commitment_id and existing_core_terms is None:
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("CORE_TERMS_REVALIDATION_REQUIRED",),
        )

    missing: list[str] = []
    if not commercial_terms.order_request_id:
        missing.append("order_request_id")
    if commercial_terms.terms_revision is None:
        missing.append("terms_revision")
    if not commercial_terms.items:
        missing.append("items")
    for field in (
        "fulfilment_method",
        "location_ref",
        "window_start",
        "window_end",
        "business_timezone",
        "currency",
        "fees",
        "tax",
        "discount",
        "total",
        "binding_policy_ref",
    ):
        if getattr(commercial_terms, field) is None:
            missing.append(field)
    if commercial_terms.price_source is None:
        missing.append("price_source")
    if not commercial_terms.price_disclosure_evidence:
        missing.append("price_disclosure_evidence")
    if missing:
        missing_reasons = {
            "fulfilment_method": "FULFILMENT_METHOD_MISSING",
            "location_ref": "FULFILMENT_LOCATION_MISSING",
        }
        specific_reasons = tuple(
            missing_reasons[field] for field in missing if field in missing_reasons
        )
        return _make_candidate(
            context,
            readiness="INCOMPLETE",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=specific_reasons or ("BINDING_TERMS_INCOMPLETE",),
            missing=tuple(missing),
        )

    price_source = commercial_terms.price_source
    authority = commercial_terms.price_source_authority
    if (
        authority is None
        or authority.status != "VERIFIED"
        or not authority.authority_ref
        or authority.tenant_id != context.tenant_id
        or authority.customer_id != context.customer_id
        or authority.source_id != price_source.source_id
        or authority.source_version != price_source.source_version
    ):
        return _make_candidate(
            context,
            readiness="PRICE_SOURCE_UNVERIFIED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("PRICE_SOURCE_UNVERIFIED",),
        )

    disclosure_refs = _unique(
        [record.disclosure_ref for record in commercial_terms.price_disclosure_evidence]
    )
    if len(disclosure_refs) != len(commercial_terms.price_disclosure_evidence):
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=None,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("DUPLICATE_PRICE_DISCLOSURE_EVIDENCE",),
        )
    if not set(disclosure_refs).issubset(set(price_source.evidence_refs)):
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=None,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("PRICE_DISCLOSURE_EVIDENCE_MISMATCH",),
            conflicts=("price_disclosure_evidence",),
        )
    if any(
        record.verification_status != "VERIFIED" or not record.authority_ref
        for record in commercial_terms.price_disclosure_evidence
    ):
        return _make_candidate(
            context,
            readiness="PRICE_SOURCE_UNVERIFIED",
            current_version=current_version,
            commercial=None,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("PRICE_DISCLOSURE_UNVERIFIED",),
        )

    requested_lines = context.requested_items
    commercial_lines = commercial_terms.items or ()
    if len(requested_lines) != len(commercial_lines):
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("REQUESTED_ITEMS_MISMATCH",),
            conflicts=("items",),
        )
    for requested, commercial in zip(requested_lines, commercial_lines, strict=True):
        try:
            requested_quantity = Decimal(requested.quantity)
        except (InvalidOperation, ValueError):
            requested_quantity = None
        if (
            requested.sku != commercial.sku
            or requested.unit != commercial.unit
            or requested_quantity is None
            or requested_quantity != commercial.quantity
        ):
            return _make_candidate(
                context,
                readiness="TERMS_CONFLICT",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=base_refs,
                identity_evidence=identity_refs,
                identity_associations=identity_associations,
                reasons=("REQUESTED_ITEMS_MISMATCH",),
                conflicts=("items",),
            )

    if commercial_terms.fulfilment_method == "PICKUP":
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("PICKUP_WINDOW_NOT_SUPPORTED_BY_P1_CONTEXT",),
            conflicts=("fulfilment_window",),
        )

    deadline = context.requested_delivery_at
    if (
        deadline is None
        or deadline.tzinfo is None
        or deadline.utcoffset() is None
        or context.delivery_qualifier != "DEADLINE"
    ):
        return _make_candidate(
            context,
            readiness="REVIEW_REQUIRED",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("DELIVERY_TIME_AMBIGUOUS",),
            conflicts=("fulfilment_window",),
        )
    if commercial_terms.window_end != deadline:
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("DELIVERY_WINDOW_CONFLICT",),
            conflicts=("fulfilment_window",),
        )

    try:
        ZoneInfo(commercial_terms.business_timezone or "")
    except (ZoneInfoNotFoundError, ValueError):
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=commercial_terms,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("INVALID_BUSINESS_TIMEZONE",),
            conflicts=("business_timezone",),
        )

    line_values = [
        OrderLine(
            sku=line.sku,
            variant=line.variant,
            quantity=line.quantity,
            unit=line.unit,
            unit_price=line.unit_price,
        )
        for line in commercial_lines
    ]
    additional_evidence = list(price_source.evidence_refs)
    if authority.authority_ref:
        additional_evidence.append(authority.authority_ref)
    additional_evidence.extend(disclosure_refs)
    additional_evidence.extend(
        record.authority_ref
        for record in commercial_terms.price_disclosure_evidence
        if record.authority_ref
    )
    terms_evidence = _unique(list(context_refs) + additional_evidence)
    try:
        mapped_terms = OrderTerms.model_validate(
            {
                "tenant_id": context.tenant_id,
                "order_request_id": commercial_terms.order_request_id,
                "customer_id": context.customer_id,
                "terms_revision": commercial_terms.terms_revision,
                "items": line_values,
                "fulfilment_method": commercial_terms.fulfilment_method,
                "location_ref": commercial_terms.location_ref,
                "window_start": commercial_terms.window_start,
                "window_end": commercial_terms.window_end,
                "business_timezone": commercial_terms.business_timezone,
                "currency": commercial_terms.currency,
                "fees": commercial_terms.fees,
                "tax": commercial_terms.tax,
                "discount": commercial_terms.discount,
                "total": commercial_terms.total,
                "price_source": price_source,
                "special_conditions": (context.special_instructions,)
                if context.special_instructions
                else (),
                "binding_policy_ref": commercial_terms.binding_policy_ref,
                "source_message_ids": tuple(context.source_message_ids),
                "evidence_refs": terms_evidence,
            }
        )
    except ValidationError as exc:
        fields: list[str] = []
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for error in errors():
                loc = error.get("loc") or ()
                if loc and isinstance(loc[0], str):
                    fields.append(loc[0])
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=commercial_terms,
            # The commercial evidence refs are not trusted until OrderTerms
            # validation and disclosure binding both succeed.
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("CANONICAL_TERMS_INVALID",),
            conflicts=_unique(fields),
        )

    disclosure_binding_matches = all(
        record.tenant_id == context.tenant_id
        and record.customer_id == context.customer_id
        and record.context_id == context.context_id
        and record.context_version == context.context_version
        and record.order_request_id == commercial_terms.order_request_id
        and record.terms_revision == commercial_terms.terms_revision
        and record.terms_hash == mapped_terms.terms_hash
        and record.source_id == price_source.source_id
        and record.source_version == price_source.source_version
        and record.disclosed_at == price_source.disclosed_at
        for record in commercial_terms.price_disclosure_evidence
    )
    if not disclosure_binding_matches:
        return _make_candidate(
            context,
            readiness="TERMS_CONFLICT",
            current_version=current_version,
            commercial=None,
            source_evidence_refs=base_refs,
            identity_evidence=identity_refs,
            identity_associations=identity_associations,
            reasons=("PRICE_DISCLOSURE_BINDING_MISMATCH",),
            conflicts=("price_disclosure_evidence",),
        )

    candidate_evidence = _unique(
        list(base_refs)
        + list(context_refs)
        + list(terms_evidence)
        + list(identity_refs)
        + list(disclosure_refs)
        + [
            record.authority_ref
            for record in commercial_terms.price_disclosure_evidence
            if record.authority_ref
        ]
    )
    if existing_core_terms is not None:
        comparison = compare_terms(existing_core_terms, mapped_terms)
        if (
            existing_core_terms.tenant_id != context.tenant_id
            or existing_core_terms.customer_id != context.customer_id
        ):
            return _make_candidate(
                context,
                readiness="TERMS_CONFLICT",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=candidate_evidence,
                identity_evidence=identity_refs,
                identity_associations=identity_associations,
                reasons=("CORE_TERMS_CUSTOMER_MISMATCH",),
                conflicts=("tenant_id", "customer_id"),
            )
        if not comparison.matches:
            return _make_candidate(
                context,
                readiness="TERMS_CONFLICT",
                current_version=current_version,
                commercial=commercial_terms,
                source_evidence_refs=candidate_evidence,
                identity_evidence=identity_refs,
                identity_associations=identity_associations,
                reasons=("PROPOSAL_REQUIRED",),
                conflicts=comparison.changed_fields,
            )

    return _make_candidate(
        context,
        readiness="READY_FOR_VALIDATION",
        current_version=current_version,
        commercial=commercial_terms,
        source_evidence_refs=candidate_evidence,
        identity_evidence=identity_refs,
        identity_associations=identity_associations,
        canonical_terms=mapped_terms,
    )
