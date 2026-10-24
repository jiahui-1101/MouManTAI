"""Read-only, authority-checked C3 handoffs over current P1 and business sources.

These previews cannot enqueue review work, create an order, mutate P2, or send via P4.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.context.repository import MessageRepository

from .contracts import (
    AnalysisOutcome,
    CustomerInquiryCandidate,
    SourceMessageReference,
    SupplierDelaySignalCandidate,
    VerifiedSupplierIdentity,
)
from .service import MessageIntelligenceService, SourceContractError, SupplierIdentityResolver


class VerifiedTenantScope(Protocol):
    def current_verified_tenant_id(self) -> str | None: ...


class CurrentP1MessageReader:
    """Resolve an exact tenant-scoped P1 row immediately before analysis or handoff."""

    def __init__(self, repository: MessageRepository, scope: VerifiedTenantScope):
        self.repository, self.scope = repository, scope

    def read(self, message_id: str):
        tenant_id = self.scope.current_verified_tenant_id()
        if not tenant_id or not message_id:
            raise SourceContractError("authenticated tenant and exact message are required")
        message = self.repository.get(tenant_id, message_id)
        if (
            message is None
            or message.message_id != message_id
            or message.raw.tenant_id != tenant_id
        ):
            raise SourceContractError("current tenant-scoped source message is unavailable")
        if sha256(message.raw.text.encode("utf-8")).hexdigest() != message.content_sha256:
            raise SourceContractError("stored message content digest is inconsistent")
        if message.raw.adapter_mode == "REAL" and (
            message.raw.source_authenticity != "VERIFIED"
            or not message.raw.provider_account_id
            or not message.raw.provider_native_message_id
        ):
            raise SourceContractError(
                "real channel source has no verified account-bound provenance"
            )
        association = self.repository.get_association(tenant_id, message_id)
        if association is not None and (
            association.tenant_id != tenant_id or association.message_id != message_id
        ):
            raise SourceContractError("current association is outside source scope")
        records, extractions = [], []
        for attachment in message.raw.attachments:
            stored = self.repository.get_attachment(tenant_id, attachment.evidence_ref)
            if stored is not None:
                records.append(stored[0])
            extracted = self.repository.get_document_extraction(tenant_id, attachment.evidence_ref)
            if extracted is not None:
                extractions.append(extracted)
        return message, association, tuple(records), tuple(extractions)

    def analyze(
        self, message_id: str, service: MessageIntelligenceService, *, now: datetime | None = None
    ) -> AnalysisOutcome:
        message, association, records, extractions = self.read(message_id)
        return service.analyze(
            message,
            association=association,
            attachment_records=records,
            attachments=extractions,
            now=now,
        )

    def assert_current(
        self,
        source: SourceMessageReference,
        *,
        inquiry: CustomerInquiryCandidate | None = None,
    ) -> None:
        message, association, records, extractions = self.read(source.message_id)
        current = MessageIntelligenceService._source_reference(
            message,
            {record.evidence_ref: record for record in records},
            extractions,
        )
        if current != source or source.tenant_id != message.raw.tenant_id:
            raise SourceContractError("candidate source version is stale")
        if (
            inquiry is not None
            and inquiry.identity_status == "LINK_VERIFIED"
            and (
                association is None
                or association.association_id != inquiry.association_id
                or association.version != inquiry.association_version
                or association.updated_at != inquiry.association_updated_at
                or association.verified_customer is None
                or association.verified_customer.customer_id != inquiry.customer_id
            )
        ):
            raise SourceContractError("verified customer identity changed")


class ApprovedInquiryFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=1000)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    source_version: int = Field(ge=1)
    checked_at: datetime


class ApprovedBusinessFacts(Protocol):
    def read_public_inquiry_fact(
        self, tenant_id: str, topic: str
    ) -> ApprovedInquiryFact | None: ...


class InquiryReplyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    message_id: str
    customer_id: str
    text: str
    source_content_sha256: str
    source_evidence: tuple[str, ...]
    business_evidence: tuple[str, ...]
    business_source_version: int
    send_authorized: bool = False


def draft_customer_inquiry(
    candidate: CustomerInquiryCandidate,
    *,
    reader: CurrentP1MessageReader,
    facts: ApprovedBusinessFacts,
    now: datetime,
) -> InquiryReplyDraft:
    """Draft from approved public facts; no customer assent or P4 transport."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise SourceContractError("draft time must be offset-aware")
    if (
        candidate.review_required
        or candidate.identity_status != "LINK_VERIFIED"
        or not candidate.customer_id
    ):
        raise SourceContractError("customer identity or inquiry needs review")
    reader.assert_current(candidate.source, inquiry=candidate)
    fact = facts.read_public_inquiry_fact(candidate.tenant_id, candidate.topic)
    if (
        fact is None
        or fact.tenant_id != candidate.tenant_id
        or fact.topic != candidate.topic
        or fact.checked_at.tzinfo is None
        or fact.checked_at > now
        or now - fact.checked_at > timedelta(minutes=5)
        or not fact.evidence_refs
    ):
        raise SourceContractError("approved current business fact is unavailable")
    return InquiryReplyDraft(
        tenant_id=candidate.tenant_id,
        message_id=candidate.source.message_id,
        customer_id=candidate.customer_id,
        text=fact.text,
        source_content_sha256=candidate.source.content_sha256,
        source_evidence=tuple(
            link.evidence_id or f"{link.message_id}:{link.start}:{link.end}"
            for link in candidate.evidence
        ),
        business_evidence=fact.evidence_refs,
        business_source_version=fact.source_version,
    )


class TrustedDeliverySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    supplier_id: str
    delivery_reference: str
    snapshot_version: int = Field(ge=1)
    snapshot_at: datetime
    expected_eta: datetime
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class TrustedP2DeliveryReader(Protocol):
    def read_delivery(
        self, tenant_id: str, supplier_id: str, reference: str
    ) -> TrustedDeliverySnapshot | None: ...


class SupplierDelayAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    message_id: str
    supplier_id: str
    delivery_reference: str
    reported_eta_text: str
    expected_eta: datetime
    snapshot_version: int
    snapshot_evidence: tuple[str, ...]
    status: str
    review_required: bool = True
    state_mutated: bool = False


def validate_supplier_delay(
    candidate: SupplierDelaySignalCandidate,
    *,
    reader: CurrentP1MessageReader,
    p2: TrustedP2DeliveryReader,
    supplier_identity: SupplierIdentityResolver,
    now: datetime,
) -> SupplierDelayAssessment:
    """Return matching current P2 evidence for human review; do not mutate P2."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise SourceContractError("assessment time must be offset-aware")
    reader.assert_current(candidate.source)
    if (
        candidate.supplier_identity_status != "VERIFIED"
        or not candidate.supplier_id
        or not candidate.delivery_reference
        or not candidate.reported_eta_text
    ):
        raise SourceContractError("supplier, delivery reference or reported ETA is unresolved")
    current_message, _, _, _ = reader.read(candidate.source.message_id)
    try:
        identity = VerifiedSupplierIdentity.model_validate(
            supplier_identity.resolve_supplier(
                tenant_id=candidate.tenant_id,
                channel=current_message.raw.channel,
                sender_identity_id=current_message.raw.sender_identity_id,
            )
        )
    except Exception as error:
        raise SourceContractError("current supplier identity is unavailable") from error
    if (
        identity.tenant_id != candidate.tenant_id
        or identity.channel != current_message.raw.channel
        or identity.sender_identity_id != current_message.raw.sender_identity_id
        or identity.supplier_id != candidate.supplier_id
        or identity.version != candidate.supplier_identity_version
        or identity.checked_at != candidate.supplier_identity_checked_at
        or identity.checked_at > now
        or identity.evidence_refs != candidate.supplier_identity_evidence_refs
    ):
        raise SourceContractError("supplier identity changed since analysis")
    snapshot = p2.read_delivery(
        candidate.tenant_id, candidate.supplier_id, candidate.delivery_reference
    )
    if (
        snapshot is None
        or snapshot.tenant_id != candidate.tenant_id
        or snapshot.supplier_id != candidate.supplier_id
        or snapshot.delivery_reference != candidate.delivery_reference
        or snapshot.snapshot_at.tzinfo is None
        or snapshot.snapshot_at < candidate.analyzed_at
        or snapshot.snapshot_at > now
        or now - snapshot.snapshot_at > timedelta(minutes=5)
        or snapshot.expected_eta.tzinfo is None
        or not snapshot.evidence_refs
    ):
        raise SourceContractError("trusted current P2 delivery evidence is unavailable")
    try:
        reported_date = date.fromisoformat(candidate.reported_eta_text[:10])
    except ValueError as error:
        raise SourceContractError("reported ETA is not an exact calendar date") from error
    expected_date = snapshot.expected_eta.date()
    return SupplierDelayAssessment(
        tenant_id=candidate.tenant_id,
        message_id=candidate.source.message_id,
        supplier_id=candidate.supplier_id,
        delivery_reference=candidate.delivery_reference,
        reported_eta_text=candidate.reported_eta_text,
        expected_eta=snapshot.expected_eta,
        snapshot_version=snapshot.snapshot_version,
        snapshot_evidence=snapshot.evidence_refs,
        status="POTENTIAL_DELAY_REPORTED" if reported_date > expected_date else "UNRESOLVED",
    )
