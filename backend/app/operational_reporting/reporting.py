"""Daily aggregation over versioned facts supplied by a trusted reader."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .models import EventKind, EvidenceTier, Milestone, OrderFacts
from .projection import project_status


@dataclass(frozen=True)
class Measurement:
    planned: Decimal
    actual: Decimal
    unit: str


@dataclass(frozen=True)
class DailyOrderActual:
    order_id: str
    quantity: Measurement | None
    duration: Measurement | None
    delay_reason: str | None


@dataclass(frozen=True)
class DailyReport:
    tenant_id: str
    business_date: date
    timezone: str
    window_start: datetime
    window_end: datetime
    accepted_orders: int
    due_orders: int
    verified_fulfilled_orders: int
    on_time_fulfilled_orders: int
    late_fulfilled_orders: int
    completion_reported_unverified: int
    missing_unknown_evidence: int
    eligible_denominator: int
    data_coverage: Decimal
    actuals: tuple[DailyOrderActual, ...]
    limitations: tuple[str, ...]


def _measurement(
    facts: OrderFacts,
    planned: Decimal | None,
    actual: Decimal | None,
    planned_ref: str | None,
    actual_ref: str | None,
    unit: str,
) -> Measurement | None:
    refs = {e.ref: e for e in facts.evidence}
    if planned is None or actual is None or planned < 0 or actual < 0:
        return None
    if not planned_ref or not actual_ref or not unit:
        return None
    if any(
        ref not in refs
        or refs[ref].tier not in (EvidenceTier.VERIFIED, EvidenceTier.DEMO_ONLY)
        or refs[ref].tenant_id != facts.tenant_id
        or refs[ref].commitment_id != facts.commitment_id
        for ref in (planned_ref, actual_ref)
    ):
        return None
    return Measurement(planned, actual, unit)


def aggregate_daily(
    tenant_id: str,
    business_date: date,
    timezone: str,
    orders: tuple[OrderFacts, ...],
    *,
    as_of: datetime,
) -> DailyReport:
    zone = ZoneInfo(timezone)
    start = datetime.combine(business_date, time.min, zone)
    end = datetime.combine(business_date + timedelta(days=1), time.min, zone)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be offset-aware")
    counts = dict.fromkeys(
        ("accepted", "due", "fulfilled", "on_time", "late", "reported", "unknown"), 0
    )
    actuals: list[DailyOrderActual] = []
    limitations: set[str] = set()
    seen: set[str] = set()
    eligible = 0
    covered = 0
    for facts in orders:
        if facts.tenant_id != tenant_id or facts.order_id in seen:
            raise ValueError("tenant mismatch or duplicate order")
        seen.add(facts.order_id)
        status = project_status(facts, as_of=as_of)
        accepted_events = [e for e in facts.events if e.kind == EventKind.ACCEPTED and e.verified]
        fulfilled_events = [e for e in facts.events if e.kind == EventKind.FULFILLED and e.verified]
        due_today = (
            facts.due_at is not None
            and facts.due_at.tzinfo is not None
            and start <= facts.due_at.astimezone(zone) < end
        )
        accepted_today = status.milestone != Milestone.NOT_AVAILABLE and any(
            start <= e.occurred_at.astimezone(zone) < end for e in accepted_events
        )
        fulfilled_today = status.milestone == Milestone.COMPLETED and any(
            start <= e.occurred_at.astimezone(zone) < end for e in fulfilled_events
        )
        if accepted_today:
            counts["accepted"] += 1
        if due_today:
            counts["due"] += 1
            eligible += 1
            if status.milestone != Milestone.NOT_AVAILABLE:
                covered += 1
            else:
                counts["unknown"] += 1
        if fulfilled_today:
            counts["fulfilled"] += 1
            completion = next(e for e in fulfilled_events if e.event_id == status.source_event_id)
            if facts.due_at is None:
                limitations.add("DUE_TIME_MISSING")
            elif completion.occurred_at <= facts.due_at:
                counts["on_time"] += 1
            else:
                counts["late"] += 1
        if status.milestone == Milestone.COMPLETION_REPORTED and any(
            start <= e.occurred_at.astimezone(zone) < end
            for e in facts.events
            if e.kind == EventKind.COMPLETION_REPORTED
        ):
            counts["reported"] += 1
        quantity = None
        if facts.quantity_unit and facts.quantity_unit == facts.actual_quantity_unit:
            quantity = _measurement(
                facts,
                facts.planned_quantity,
                facts.actual_quantity,
                facts.planned_quantity_ref,
                facts.actual_quantity_ref,
                facts.quantity_unit,
            )
        duration = _measurement(
            facts,
            facts.planned_duration_minutes,
            facts.actual_duration_minutes,
            facts.planned_duration_ref,
            facts.actual_duration_ref,
            "minutes",
        )
        if due_today and (quantity is None or duration is None):
            limitations.add("OPTIONAL_ACTUALS_PARTIAL")
        if due_today and status.milestone == Milestone.NOT_AVAILABLE:
            limitations.add("STATUS_EVIDENCE_PARTIAL")
        if due_today or accepted_today or fulfilled_today:
            actuals.append(
                DailyOrderActual(
                    facts.order_id,
                    quantity,
                    duration,
                    facts.delay_reason if fulfilled_today else None,
                )
            )
    return DailyReport(
        tenant_id,
        business_date,
        timezone,
        start,
        end,
        counts["accepted"],
        counts["due"],
        counts["fulfilled"],
        counts["on_time"],
        counts["late"],
        counts["reported"],
        counts["unknown"],
        eligible,
        Decimal(covered) / Decimal(eligible) if eligible else Decimal(0),
        tuple(actuals),
        tuple(sorted(limitations)),
    )
