"""Pure P1-normalized RFQ reply consolidation; no message ingestion or acceptance."""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field

from app.orders.terms import ImmutableContract, Text
from app.sourcing.rfq import RFQDraft, RFQRequirement, prepare_rfq
from app.suppliers.comparison import SupplierOffer


class NormalizedReply(ImmutableContract):
    tenant_id: Text
    sourcing_case_id: Text
    requirement_version: int = Field(ge=1, strict=True)
    supplier_id: Text
    supplier_identity_verified: bool
    identity_evidence_refs: tuple[Text, ...]
    message_id: Text
    source_refs: tuple[Text, ...]
    quote_id: Text
    quote_version: int = Field(ge=1, strict=True)
    offer: SupplierOffer
    received_at: AwareDatetime


class ReplySummary(ImmutableContract):
    supplier_id: Text
    quote_id: Text
    quote_version: int = Field(ge=1, strict=True)
    message_ids: tuple[Text, ...]
    source_refs: tuple[Text, ...]
    readiness: Literal["COMPLETE_FOR_COMPARISON", "PARTIAL", "CONFLICT", "EXPIRED"]
    missing_information: tuple[Text, ...]
    contradictory_terms: bool
    selected: Literal[False] = False


def consolidate_replies(
    request: RFQRequirement, draft: RFQDraft, replies: Sequence[NormalizedReply], *, now: datetime
) -> tuple[ReplySummary, ...]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Offset-aware current time required")
    expected = prepare_rfq(request, None, now=now)
    if (
        draft.canonical_content_hash != expected.canonical_content_hash
        or draft.canonical_content != expected.canonical_content
        or draft.draft_id != expected.draft_id
        or tuple(e.supplier_id for e in draft.envelopes)
        != tuple(e.supplier_id for e in expected.envelopes)
    ):
        raise ValueError("RFQ draft version mismatch")
    messages: dict[str, NormalizedReply] = {}
    grouped: dict[tuple[str, str, int], list[NormalizedReply]] = {}
    for reply in replies:
        if (
            reply.tenant_id != request.tenant_id
            or reply.sourcing_case_id != request.sourcing_case_id
            or reply.requirement_version != request.requirement_version
            or reply.supplier_id not in request.recipient_supplier_ids
            or not reply.supplier_identity_verified
            or not reply.identity_evidence_refs
            or not reply.source_refs
            or reply.offer.tenant_id != request.tenant_id
            or (reply.offer.supplier_id, reply.offer.quote_id, reply.offer.quote_version)
            != (reply.supplier_id, reply.quote_id, reply.quote_version)
        ):
            raise ValueError("Unbound or unverified supplier reply")
        old = messages.get(reply.message_id)
        if old is not None:
            if old != reply:
                raise ValueError("Conflicting inbound message replay")
            continue
        messages[reply.message_id] = reply
        grouped.setdefault((reply.supplier_id, reply.quote_id, reply.quote_version), []).append(
            reply
        )
    summaries = []
    hard = {p.name for p in request.hard_properties}
    for key, versions in sorted(grouped.items()):
        offer = versions[0].offer
        conflict = any(item.offer != offer for item in versions[1:])
        answered = {p.name for p in offer.properties if p.evidence_refs}
        missing = set(hard - answered)
        if (
            offer.price_per_pack is None
            or offer.units_per_pack is None
            or not offer.pack_evidence_refs
        ):
            missing.add("PRICE_AND_PACK")
        if not offer.evidence_refs:
            missing.add("QUOTE_SOURCE_EVIDENCE")
        if offer.moq is None:
            missing.add("MOQ")
        if offer.availability != "VERIFIED" or not offer.availability_evidence_refs:
            missing.add("VERIFIED_AVAILABILITY")
        if offer.quoted_arrival is None:
            missing.add("ARRIVAL_ESTIMATE")
        expired = now >= offer.valid_until
        status = (
            "CONFLICT"
            if conflict
            else "EXPIRED"
            if expired
            else "PARTIAL"
            if missing
            else "COMPLETE_FOR_COMPARISON"
        )
        summaries.append(
            ReplySummary(
                supplier_id=key[0],
                quote_id=key[1],
                quote_version=key[2],
                message_ids=tuple(sorted(r.message_id for r in versions)),
                source_refs=tuple(sorted({ref for r in versions for ref in r.source_refs})),
                readiness=status,
                missing_information=tuple(sorted(missing)),
                contradictory_terms=conflict,
            )
        )
    return tuple(summaries)
