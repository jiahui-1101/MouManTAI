"""Structural checks for facts already obtained from trusted read adapters.

These checks cannot authenticate a receipt, consent, or Core transition. They
only prevent inconsistent transfer shapes from driving D-owned read outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .models import (
    EventKind,
    EvidenceTier,
    Milestone,
    OperationalEvent,
    OrderFacts,
    StatusProjection,
    status_matches,
)

_EVIDENCE_KINDS = {
    EventKind.ACCEPTED: frozenset({"ACCEPTANCE", "RESERVATION"}),
    EventKind.PREPARING: frozenset({"PREPARING"}),
    EventKind.READY: frozenset({"OPERATIONAL_READY"}),
    EventKind.OUT_FOR_DELIVERY: frozenset({"OUT_FOR_DELIVERY"}),
    EventKind.COMPLETION_REPORTED: frozenset({"COMPLETION_REPORT"}),
    EventKind.FULFILLED: frozenset({"FULFILMENT"}),
}
_MILESTONE_KIND = {
    Milestone.ORDER_ACCEPTED: EventKind.ACCEPTED,
    Milestone.PREPARING: EventKind.PREPARING,
    Milestone.READY: EventKind.READY,
    Milestone.OUT_FOR_DELIVERY: EventKind.OUT_FOR_DELIVERY,
    Milestone.COMPLETION_REPORTED: EventKind.COMPLETION_REPORTED,
    Milestone.COMPLETED: EventKind.FULFILLED,
}


def _aware(value: datetime | None) -> bool:
    return value is not None and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class EventValidation:
    """A deduplicated event set; any diagnostic other than replay blocks use."""

    events: tuple[OperationalEvent, ...]
    tiers: tuple[tuple[str, EvidenceTier], ...]
    diagnostics: tuple[str, ...]
    identical_replays: int

    @property
    def usable(self) -> bool:
        return not self.diagnostics

    def tier_for(self, event_id: str) -> EvidenceTier | None:
        return dict(self.tiers).get(event_id)


def validate_events(
    facts: OrderFacts,
    status: StatusProjection,
    *,
    as_of: datetime,
    max_age_seconds: int = 3600,
) -> EventValidation:
    """Validate bindings and evidence without inferring a new lifecycle state."""

    problems: list[str] = []
    if not status_matches(facts, status, as_of=as_of, max_age_seconds=max_age_seconds):
        problems.append("STATUS_VECTOR_STALE_OR_MISMATCHED")
    if not _aware(facts.event_window_start) or not _aware(facts.event_window_end):
        problems.append("EVENT_SOURCE_WINDOW_UNKNOWN")
    elif (
        not _aware(facts.snapshot_at)
        or facts.event_window_start.astimezone(UTC) > facts.event_window_end.astimezone(UTC)
        or facts.event_window_end.astimezone(UTC) > facts.snapshot_at.astimezone(UTC)
    ):
        problems.append("EVENT_SOURCE_WINDOW_INVALID")

    evidence = {}
    for item in facts.evidence:
        if not item.ref or item.ref in evidence:
            problems.append("DUPLICATE_OR_EMPTY_EVIDENCE_REF")
        evidence[item.ref] = item
        if (item.tenant_id, item.commitment_id) != (facts.tenant_id, facts.commitment_id):
            problems.append("EVIDENCE_BINDING_MISMATCH")

    seen: dict[str, OperationalEvent] = {}
    versions: dict[int, str] = {}
    tiers: list[tuple[str, EvidenceTier]] = []
    replays = 0
    for event in facts.events:
        previous = seen.get(event.event_id)
        if previous is not None:
            if previous == event:
                replays += 1
            else:
                problems.append("CONFLICTING_EVENT_ID")
            continue
        if not event.event_id:
            problems.append("EMPTY_EVENT_ID")
        seen[event.event_id] = event
        if (event.tenant_id, event.order_id, event.commitment_id) != (
            facts.tenant_id,
            facts.order_id,
            facts.commitment_id,
        ):
            problems.append("EVENT_BINDING_MISMATCH")
        if (
            not isinstance(event.aggregate_version, int)
            or isinstance(event.aggregate_version, bool)
            or event.aggregate_version < 1
            or not isinstance(facts.aggregate_version, int)
            or isinstance(facts.aggregate_version, bool)
            or event.aggregate_version > facts.aggregate_version
        ):
            problems.append("EVENT_VERSION_OUTSIDE_SNAPSHOT")
        if (
            event.aggregate_version in versions
            and versions[event.aggregate_version] != event.event_id
        ):
            problems.append("CONFLICTING_EVENT_VERSION")
        versions[event.aggregate_version] = event.event_id
        if not _aware(event.occurred_at):
            problems.append("EVENT_TIME_NAIVE")
        elif (
            not _aware(facts.snapshot_at)
            or not _aware(as_of)
            or event.occurred_at.astimezone(UTC) > facts.snapshot_at.astimezone(UTC)
            or event.occurred_at.astimezone(UTC) > as_of.astimezone(UTC)
            or (
                _aware(facts.event_window_start)
                and event.occurred_at.astimezone(UTC) < facts.event_window_start.astimezone(UTC)
            )
            or (
                _aware(facts.event_window_end)
                and event.occurred_at.astimezone(UTC) > facts.event_window_end.astimezone(UTC)
            )
        ):
            problems.append("EVENT_OUTSIDE_SOURCE_WINDOW")
        try:
            kind = EventKind(event.kind)
        except ValueError:
            problems.append("UNSUPPORTED_EVENT_KIND")
            continue
        if not event.verified:
            problems.append("EVENT_NOT_VERIFIED_BY_READER")
        if not event.evidence_refs or len(set(event.evidence_refs)) != len(event.evidence_refs):
            problems.append("MISSING_OR_REPEATED_EVENT_EVIDENCE")
        linked = [evidence.get(ref) for ref in event.evidence_refs]
        if not linked or any(item is None for item in linked):
            problems.append("MISSING_EVENT_EVIDENCE")
            continue
        if not _EVIDENCE_KINDS[kind].issubset({item.kind for item in linked}):
            problems.append("WRONG_EVENT_EVIDENCE_KIND")
        allowed = (
            {EvidenceTier.VERIFIED, EvidenceTier.DEMO_ONLY, EvidenceTier.REPORTED}
            if kind == EventKind.COMPLETION_REPORTED
            else {EvidenceTier.VERIFIED, EvidenceTier.DEMO_ONLY}
        )
        if any(item.tier not in allowed for item in linked):
            problems.append("UNTRUSTED_EVENT_EVIDENCE_TIER")
        tier = (
            EvidenceTier.DEMO_ONLY
            if any(item.tier == EvidenceTier.DEMO_ONLY for item in linked)
            else EvidenceTier.REPORTED
            if any(item.tier == EvidenceTier.REPORTED for item in linked)
            else EvidenceTier.VERIFIED
        )
        tiers.append((event.event_id, tier))
        if kind == EventKind.ACCEPTED and facts.agreement_state != "CONFIRMED":
            problems.append("ACCEPTANCE_STATE_CONFLICT")
        if kind == EventKind.FULFILLED and facts.fulfilment_state != "FULFILLED":
            problems.append("FULFILMENT_STATE_CONFLICT")

    if status.milestone != Milestone.NOT_AVAILABLE:
        source = seen.get(status.source_event_id or "")
        if source is None or source.kind != _MILESTONE_KIND.get(status.milestone):
            problems.append("STATUS_SOURCE_MISSING_OR_MISMATCHED")
        elif dict(tiers).get(source.event_id) != status.evidence_tier:
            problems.append("STATUS_EVIDENCE_TIER_MISMATCH")
        if source is not None and any(
            type(event.aggregate_version) is int
            and type(source.aggregate_version) is int
            and event.aggregate_version > source.aggregate_version
            for event in seen.values()
        ):
            problems.append("STATUS_SOURCE_SUPERSEDED")
        if status.milestone != Milestone.ORDER_ACCEPTED and not any(
            event.kind == EventKind.ACCEPTED for event in seen.values()
        ):
            problems.append("ACCEPTANCE_EVENT_MISSING")
    if facts.fulfilment_state == "FULFILLED" and not any(
        event.kind == EventKind.FULFILLED for event in seen.values()
    ):
        problems.append("FULFILMENT_EVENT_MISSING")
    if status.milestone == Milestone.COMPLETION_REPORTED and facts.fulfilment_state == "FULFILLED":
        problems.append("REPORTED_FULFILMENT_CONFLICT")
    return EventValidation(
        tuple(seen.values()), tuple(tiers), tuple(dict.fromkeys(problems)), replays
    )
