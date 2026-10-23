"""Fail-closed status projection over reader-supplied authoritative facts."""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise

from .models import EventKind, EvidenceTier, Milestone, OrderFacts, StatusProjection

_KIND_TO_MILESTONE = {
    EventKind.ACCEPTED: Milestone.ORDER_ACCEPTED,
    EventKind.PREPARING: Milestone.PREPARING,
    EventKind.READY: Milestone.READY,
    EventKind.OUT_FOR_DELIVERY: Milestone.OUT_FOR_DELIVERY,
    EventKind.COMPLETION_REPORTED: Milestone.COMPLETION_REPORTED,
    EventKind.FULFILLED: Milestone.COMPLETED,
}
_REQUIRED_EVIDENCE = {
    EventKind.ACCEPTED: frozenset({"ACCEPTANCE", "RESERVATION"}),
    EventKind.PREPARING: frozenset({"PREPARING"}),
    EventKind.READY: frozenset({"OPERATIONAL_READY"}),
    EventKind.OUT_FOR_DELIVERY: frozenset({"OUT_FOR_DELIVERY"}),
    EventKind.COMPLETION_REPORTED: frozenset({"COMPLETION_REPORT"}),
    EventKind.FULFILLED: frozenset({"FULFILMENT"}),
}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def project_status(
    facts: OrderFacts, *, as_of: datetime, max_age_seconds: int = 3600
) -> StatusProjection:
    """Inputs must come from a trusted Core/event/evidence reader, never an API body."""

    problems: list[str] = []
    if not all((_aware(as_of), _aware(facts.updated_at), _aware(facts.snapshot_at))):
        problems.append("NAIVE_TIME")
    elif (as_of - facts.snapshot_at).total_seconds() > max_age_seconds or facts.snapshot_at > as_of:
        problems.append("STALE_SNAPSHOT")
    if facts.source_version != facts.aggregate_version or facts.aggregate_version < 1:
        problems.append("STALE_VERSION")
    if not all((facts.tenant_id, facts.order_id, facts.commitment_id, facts.customer_id)):
        problems.append("MISSING_BINDING")
    evidence = {item.ref: item for item in facts.evidence}
    if len(evidence) != len(facts.evidence):
        problems.append("DUPLICATE_EVIDENCE_REF")
    accepted = []
    seen_ids: set[str] = set()
    for event in sorted(
        facts.events, key=lambda e: (e.aggregate_version, e.occurred_at, e.event_id)
    ):
        if event.event_id in seen_ids:
            problems.append("DUPLICATE_EVENT_ID")
        seen_ids.add(event.event_id)
        if (event.tenant_id, event.order_id, event.commitment_id) != (
            facts.tenant_id,
            facts.order_id,
            facts.commitment_id,
        ):
            problems.append("EVENT_BINDING_MISMATCH")
            continue
        if not _aware(event.occurred_at) or event.occurred_at > facts.snapshot_at:
            problems.append("EVENT_TIME_CONFLICT")
            continue
        if event.aggregate_version < 1 or event.aggregate_version > facts.aggregate_version:
            problems.append("EVENT_VERSION_CONFLICT")
            continue
        try:
            kind = EventKind(event.kind)
        except ValueError:
            problems.append("UNSUPPORTED_EVENT")
            continue
        if not event.verified:
            problems.append("UNVERIFIED_EVENT")
            continue
        linked = [evidence.get(ref) for ref in event.evidence_refs]
        if not linked or any(item is None for item in linked):
            problems.append("MISSING_EVIDENCE")
            continue
        if any(
            item.tenant_id != facts.tenant_id
            or item.commitment_id != facts.commitment_id
            or item.tier not in (EvidenceTier.VERIFIED, EvidenceTier.DEMO_ONLY)
            for item in linked
        ):
            problems.append("UNTRUSTED_EVIDENCE")
            continue
        if not _REQUIRED_EVIDENCE[kind].issubset({item.kind for item in linked}):
            problems.append("WRONG_EVIDENCE_KIND")
            continue
        accepted.append((kind, event, linked))

    # A mismatched or contradictory event may be newer than the one we would expose.
    # Suppressing the entire projection is safer than selecting a plausible subset.
    if facts.agreement_state != "CONFIRMED" and any(
        k == EventKind.ACCEPTED for k, _, _ in accepted
    ):
        problems.append("AGREEMENT_CONFLICT")
    if facts.fulfilment_state == "FULFILLED" and not any(
        k == EventKind.FULFILLED for k, _, _ in accepted
    ):
        problems.append("FULFILMENT_EVIDENCE_MISSING")
    if facts.fulfilment_state != "FULFILLED" and any(
        k == EventKind.FULFILLED for k, _, _ in accepted
    ):
        problems.append("FULFILMENT_STATE_CONFLICT")
    ranks = {
        EventKind.ACCEPTED: 1,
        EventKind.PREPARING: 2,
        EventKind.READY: 3,
        EventKind.OUT_FOR_DELIVERY: 4,
        EventKind.COMPLETION_REPORTED: 5,
        EventKind.FULFILLED: 6,
    }
    for previous, current in pairwise(accepted):
        if (
            ranks[current[0]] < ranks[previous[0]]
            or current[1].occurred_at < previous[1].occurred_at
        ):
            problems.append("OUT_OF_ORDER_EVENT")
    if accepted and accepted[0][0] != EventKind.ACCEPTED:
        problems.append("ACCEPTANCE_MISSING")
    if accepted and facts.agreement_state != "CONFIRMED":
        problems.append("AGREEMENT_NOT_CONFIRMED")
    if problems or not accepted:
        return StatusProjection(
            facts.tenant_id,
            facts.order_id,
            facts.commitment_id,
            facts.customer_id,
            Milestone.NOT_AVAILABLE,
            None,
            facts.aggregate_version,
            facts.snapshot_at,
            EvidenceTier.UNKNOWN,
            tuple(dict.fromkeys(problems or ["NO_VERIFIED_MILESTONE"])),
        )
    kind, event, linked = accepted[-1]
    tier = (
        EvidenceTier.DEMO_ONLY
        if any(i.tier == EvidenceTier.DEMO_ONLY for i in linked)
        else EvidenceTier.VERIFIED
    )
    return StatusProjection(
        facts.tenant_id,
        facts.order_id,
        facts.commitment_id,
        facts.customer_id,
        _KIND_TO_MILESTONE[kind],
        event.event_id,
        facts.aggregate_version,
        facts.snapshot_at,
        tier,
        (),
    )
