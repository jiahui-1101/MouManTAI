"""Synthetic trusted-reader fixtures; no claim of production authentication."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.operational_reporting.models import (
    EventKind,
    Evidence,
    EvidenceTier,
    Milestone,
    OperationalEvent,
    OrderFacts,
    RecipientPolicy,
    SendHistory,
    StatusProjection,
    Template,
)
from app.operational_reporting.planning import Eligibility, feedback_readiness, plan_milestone
from app.operational_reporting.reporting import aggregate_daily

NOW = datetime(2026, 10, 24, 4, tzinfo=UTC)


def event(kind=EventKind.ACCEPTED, version=1, *, when=None, refs=("accept", "reserve")):
    return OperationalEvent(
        f"e{version}", kind, "t", "o", "c", version, when or NOW - timedelta(minutes=10), refs, True
    )


def facts(*, events=None, fulfilment="NOT_STARTED", due=None):
    events = (event(),) if events is None else events
    version = max((e.aggregate_version for e in events), default=1)
    return OrderFacts(
        "t",
        "o",
        "c",
        "customer",
        "CONFIRMED",
        fulfilment,
        version,
        version,
        NOW,
        NOW,
        due,
        events,
        (
            Evidence("accept", "ACCEPTANCE", EvidenceTier.VERIFIED, "t", "c"),
            Evidence("reserve", "RESERVATION", EvidenceTier.VERIFIED, "t", "c"),
            Evidence("done", "FULFILMENT", EvidenceTier.VERIFIED, "t", "c"),
        ),
    )


def status(order, milestone=Milestone.ORDER_ACCEPTED, *, tier=EvidenceTier.VERIFIED):
    return StatusProjection(
        order.tenant_id,
        order.order_id,
        order.commitment_id,
        order.customer_id,
        milestone,
        order.events[-1].event_id if order.events else None,
        order.aggregate_version,
        order.snapshot_at,
        tier,
        (),
    )


def recipient(**changes):
    return replace(
        RecipientPolicy(
            "t", "o", "customer", "identity", "MOCK_EMAIL", True, True, True, True, "policy-1"
        ),
        **changes,
    )


def plan(order=None, projected=None, source=None, target=None, history=None, bound=None, *, at=NOW):
    order = order or facts()
    projected = projected or status(order)
    source = source or order.events[0]
    target = target or Template("accepted", "v1", Milestone.ORDER_ACCEPTED)
    history = history or SendHistory(True, frozenset())
    return plan_milestone(order, projected, source, bound or recipient(), target, history, as_of=at)


def test_exact_milestone_intent_and_dedup():
    proposed = plan()
    assert proposed.result == Eligibility.ELIGIBLE
    assert (
        proposed.event_id,
        proposed.event_version,
        proposed.template_id,
        proposed.template_version,
    ) == ("e1", 1, "accepted", "v1")
    assert (
        plan(history=SendHistory(True, frozenset({proposed.dedup_key}))).result
        == Eligibility.ALREADY_HANDLED
    )


def test_binding_consent_channel_and_history_gates():
    assert plan(bound=recipient(tenant_id="other")).result == Eligibility.BLOCKED
    assert plan(bound=recipient(customer_id="other")).result == Eligibility.BLOCKED
    assert plan(bound=recipient(identity_verified=False)).result == Eligibility.BLOCKED
    assert plan(bound=recipient(channel_capable=False)).result == Eligibility.BLOCKED
    assert plan(bound=recipient(consent=False)).result == Eligibility.BLOCKED
    assert plan(bound=recipient(consent=None)).result == Eligibility.UNKNOWN
    assert plan(history=SendHistory(False, frozenset())).result == Eligibility.UNKNOWN
    assert plan(source=replace(event(), tenant_id="other")).result == Eligibility.BLOCKED


def test_stale_mismatched_unknown_and_superseded_status():
    order = facts()
    projected = status(order)
    assert plan(order=replace(order, source_version=0)).result == Eligibility.UNKNOWN
    assert (
        plan(order=order, projected=replace(projected, aggregate_version=2)).result
        == Eligibility.UNKNOWN
    )
    assert (
        plan(order=order, projected=replace(projected, tenant_id="other")).result
        == Eligibility.UNKNOWN
    )
    assert (
        plan(order=order, projected=replace(projected, milestone=Milestone.NOT_AVAILABLE)).result
        == Eligibility.UNKNOWN
    )
    assert (
        plan(order=order, projected=replace(projected, evidence_tier=EvidenceTier.UNKNOWN)).result
        == Eligibility.UNKNOWN
    )
    assert plan(at=NOW + timedelta(hours=2)).result == Eligibility.UNKNOWN
    assert plan(source=replace(event(), verified=False)).result == Eligibility.BLOCKED
    old, new = event(), event(EventKind.READY, 2, refs=("ready",))
    order = facts(events=(old, new))
    projected = status(order, Milestone.READY)
    template = Template("ready", "v1", Milestone.READY)
    assert plan(order, projected, old, template).result == Eligibility.BLOCKED
    assert plan(order, projected, new, template).result == Eligibility.ELIGIBLE
    assert (
        plan(order, projected, replace(new, kind="READY_FOR_REVIEW"), template).result
        == Eligibility.BLOCKED
    )


def test_feedback_only_after_evidenced_fulfilment_and_dedup():
    accepted = facts()
    history = SendHistory(True, frozenset())
    assert (
        feedback_readiness(accepted, status(accepted), recipient(), history, as_of=NOW).result
        == Eligibility.BLOCKED
    )
    completed = facts(
        events=(event(), event(EventKind.FULFILLED, 2, refs=("done",))), fulfilment="FULFILLED"
    )
    projected = status(completed, Milestone.COMPLETED)
    invite = feedback_readiness(completed, projected, recipient(), history, as_of=NOW)
    assert invite.result == Eligibility.ELIGIBLE
    assert (
        feedback_readiness(
            completed, projected, recipient(consent=False), history, as_of=NOW
        ).result
        == Eligibility.BLOCKED
    )
    assert (
        feedback_readiness(
            completed, projected, recipient(customer_id="wrong"), history, as_of=NOW
        ).result
        == Eligibility.BLOCKED
    )
    assert (
        feedback_readiness(
            completed,
            replace(projected, evidence_tier=EvidenceTier.UNKNOWN),
            recipient(),
            history,
            as_of=NOW,
        ).result
        == Eligibility.UNKNOWN
    )
    assert (
        feedback_readiness(
            completed,
            projected,
            recipient(),
            SendHistory(True, frozenset({invite.dedup_key})),
            as_of=NOW,
        ).result
        == Eligibility.ALREADY_HANDLED
    )
    assert (
        feedback_readiness(
            replace(completed, events=(event(),)), projected, recipient(), history, as_of=NOW
        ).result
        == Eligibility.UNKNOWN
    )


def test_daily_timezone_on_time_and_late_boundary():
    due = datetime(2026, 10, 23, 16, 30, tzinfo=UTC)
    accepted = event(when=due - timedelta(hours=1))
    done = event(EventKind.FULFILLED, 2, when=due, refs=("done",))
    order = facts(events=(accepted, done), fulfilment="FULFILLED", due=due)
    report = aggregate_daily(
        "t",
        date(2026, 10, 24),
        "Asia/Singapore",
        ((order, status(order, Milestone.COMPLETED)),),
        as_of=NOW,
    )
    assert (
        report.due_orders,
        report.verified_fulfilled_orders,
        report.on_time_fulfilled_orders,
        report.late_fulfilled_orders,
    ) == (1, 1, 1, 0)
    assert report.window_start.utcoffset() == timedelta(hours=8)
    late = replace(order, events=(accepted, replace(done, occurred_at=due + timedelta(seconds=1))))
    report = aggregate_daily(
        "t",
        date(2026, 10, 24),
        "Asia/Singapore",
        ((late, status(late, Milestone.COMPLETED)),),
        as_of=NOW,
    )
    assert (report.on_time_fulfilled_orders, report.late_fulfilled_orders) == (0, 1)


def test_partial_coverage_reported_completion_and_unknown_actuals():
    due = NOW - timedelta(minutes=5)
    one = facts(due=due)
    two = replace(facts(events=(), due=due), order_id="other", commitment_id="other")
    report_event = event(EventKind.COMPLETION_REPORTED, 2, refs=("report",))
    three = facts(events=(event(), report_event), fulfilment="UNVERIFIED", due=due)
    three = replace(
        three,
        order_id="third",
        commitment_id="third",
        events=tuple(replace(e, order_id="third", commitment_id="third") for e in three.events),
    )
    report = aggregate_daily(
        "t",
        due.date(),
        "UTC",
        (
            (one, status(one)),
            (two, status(two, Milestone.NOT_AVAILABLE)),
            (three, status(three, Milestone.COMPLETION_REPORTED)),
        ),
        as_of=NOW,
    )
    assert report.eligible_denominator == 3
    assert report.data_coverage == Decimal(2) / Decimal(3)
    assert report.missing_unknown_evidence == 1
    assert report.completion_reported_unverified == 1
    assert report.verified_fulfilled_orders == 0
    assert all(item.duration is None for item in report.actuals)


def test_optional_actuals_require_evidence_and_matching_units():
    order = facts(due=NOW)
    order = replace(
        order,
        planned_quantity=Decimal(12),
        actual_quantity=Decimal(10),
        quantity_unit="kg",
        actual_quantity_unit="kg",
        planned_quantity_ref="plan",
        actual_quantity_ref="actual",
        planned_duration_minutes=Decimal(30),
        actual_duration_minutes=None,
        evidence=order.evidence
        + (
            Evidence("plan", "PLAN", EvidenceTier.VERIFIED, "t", "c"),
            Evidence("actual", "ACTUAL", EvidenceTier.VERIFIED, "t", "c"),
        ),
    )
    report = aggregate_daily("t", NOW.date(), "UTC", ((order, status(order)),), as_of=NOW)
    assert report.actuals[0].quantity is not None and report.actuals[0].duration is None
    mismatch = replace(order, actual_quantity_unit="units")
    report = aggregate_daily("t", NOW.date(), "UTC", ((mismatch, status(mismatch)),), as_of=NOW)
    assert report.actuals[0].quantity is None
