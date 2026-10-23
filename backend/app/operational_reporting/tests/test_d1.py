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
    Template,
)
from app.operational_reporting.planning import Eligibility, feedback_readiness, plan_milestone
from app.operational_reporting.projection import project_status
from app.operational_reporting.reporting import aggregate_daily

NOW = datetime(2026, 10, 24, 4, 0, tzinfo=UTC)


def fixture(*, fulfilment="NOT_STARTED", extra=(), due=None):
    evidence = (
        Evidence("accept", "ACCEPTANCE", EvidenceTier.VERIFIED, "t", "c"),
        Evidence("reserve", "RESERVATION", EvidenceTier.VERIFIED, "t", "c"),
        Evidence("ready", "OPERATIONAL_READY", EvidenceTier.VERIFIED, "t", "c"),
        Evidence("reported", "COMPLETION_REPORT", EvidenceTier.REPORTED, "t", "c"),
        Evidence("done", "FULFILMENT", EvidenceTier.VERIFIED, "t", "c"),
    )
    accepted = OperationalEvent(
        "e1",
        EventKind.ACCEPTED,
        "t",
        "o",
        "c",
        1,
        NOW - timedelta(hours=1),
        ("accept", "reserve"),
        True,
    )
    return OrderFacts(
        "t",
        "o",
        "c",
        "customer",
        "CONFIRMED",
        fulfilment,
        1 + len(extra),
        1 + len(extra),
        NOW,
        NOW,
        due,
        (accepted, *extra),
        evidence,
    )


def event(kind, version, refs, *, at=NOW - timedelta(minutes=10), event_id=None):
    return OperationalEvent(event_id or f"e{version}", kind, "t", "o", "c", version, at, refs, True)


def recipient(**changes):
    base = RecipientPolicy(
        "t", "o", "customer", "identity", "MOCK_EMAIL", True, True, True, True, "policy-1"
    )
    return replace(base, **changes)


def test_authoritative_acceptance_and_non_authorities():
    facts = fixture()
    assert project_status(facts, as_of=NOW).milestone == Milestone.ORDER_ACCEPTED
    assert (
        project_status(replace(facts, agreement_state="REQUESTED"), as_of=NOW).milestone
        == Milestone.NOT_AVAILABLE
    )
    assert (
        project_status(replace(facts, evidence=facts.evidence[:1]), as_of=NOW).milestone
        == Milestone.NOT_AVAILABLE
    )
    assert project_status(replace(facts, events=()), as_of=NOW).milestone == Milestone.NOT_AVAILABLE
    # P2 FEASIBLE and SME approval do not appear in the accepted event/evidence contract.


def test_ready_for_review_is_not_operational_ready():
    facts = fixture(extra=(event("READY_FOR_REVIEW", 2, ("ready",)),))
    assert "UNSUPPORTED_EVENT" in project_status(facts, as_of=NOW).diagnostics
    assert (
        project_status(fixture(extra=(event(EventKind.READY, 2, ("ready",)),)), as_of=NOW).milestone
        == Milestone.READY
    )


def test_reported_is_separate_from_verified_fulfilment():
    reported = event(EventKind.COMPLETION_REPORTED, 2, ("reported",))
    facts = fixture(fulfilment="UNVERIFIED", extra=(reported,))
    assert project_status(facts, as_of=NOW).milestone == Milestone.NOT_AVAILABLE
    verified_report = replace(reported, evidence_refs=("done",))
    assert (
        project_status(
            replace(facts, events=(facts.events[0], verified_report)), as_of=NOW
        ).milestone
        == Milestone.NOT_AVAILABLE
    )
    # A trusted completion report is distinct from the proof of FULFILLED.
    trusted_report = replace(reported, evidence_refs=("reported",))
    trusted_evidence = tuple(
        replace(e, tier=EvidenceTier.VERIFIED) if e.ref == "reported" else e for e in facts.evidence
    )
    facts = replace(facts, events=(facts.events[0], trusted_report), evidence=trusted_evidence)
    assert project_status(facts, as_of=NOW).milestone == Milestone.COMPLETION_REPORTED
    fulfilled = event(EventKind.FULFILLED, 3, ("done",))
    assert (
        project_status(
            replace(
                facts,
                fulfilment_state="FULFILLED",
                aggregate_version=3,
                source_version=3,
                events=(*facts.events, fulfilled),
            ),
            as_of=NOW,
        ).milestone
        == Milestone.COMPLETED
    )
    assert (
        project_status(replace(facts, fulfilment_state="FULFILLED"), as_of=NOW).milestone
        == Milestone.NOT_AVAILABLE
    )


def test_conflicts_bindings_versions_and_order_fail_closed():
    facts = fixture()
    cases = (
        replace(facts, source_version=0),
        replace(facts, snapshot_at=NOW - timedelta(hours=2)),
        replace(
            facts, events=(*facts.events, replace(facts.events[0], event_id="cross", tenant_id="x"))
        ),
        replace(
            facts,
            events=(
                *facts.events,
                event(EventKind.READY, 2, ("ready",)),
                event(EventKind.PREPARING, 3, ("ready",)),
            ),
        ),
        replace(facts, events=(*facts.events, event(EventKind.READY, 5, ("ready",)))),
    )
    for case in cases:
        assert project_status(case, as_of=NOW).milestone == Milestone.NOT_AVAILABLE


def test_milestone_planning_dedup_and_policy():
    facts = fixture()
    template = Template("accepted", "1", Milestone.ORDER_ACCEPTED)
    history = SendHistory(True, frozenset())
    planned = plan_milestone(facts, facts.events[0], recipient(), template, history, as_of=NOW)
    assert planned.result == Eligibility.ELIGIBLE
    assert planned.event_id == "e1" and planned.event_version == 1
    assert (
        plan_milestone(
            facts,
            facts.events[0],
            recipient(),
            template,
            SendHistory(True, frozenset({planned.dedup_key})),
            as_of=NOW,
        ).result
        == Eligibility.ALREADY_HANDLED
    )
    assert (
        plan_milestone(
            facts, facts.events[0], recipient(consent=None), template, history, as_of=NOW
        ).result
        == Eligibility.UNKNOWN
    )
    assert (
        plan_milestone(
            facts, facts.events[0], recipient(channel_capable=False), template, history, as_of=NOW
        ).result
        == Eligibility.BLOCKED
    )
    assert (
        plan_milestone(
            facts, facts.events[0], recipient(tenant_id="other"), template, history, as_of=NOW
        ).result
        == Eligibility.BLOCKED
    )
    assert (
        plan_milestone(
            facts,
            facts.events[0],
            recipient(),
            template,
            SendHistory(False, frozenset()),
            as_of=NOW,
        ).result
        == Eligibility.UNKNOWN
    )


def test_daily_timezone_boundary_coverage_and_missing_duration():
    # 00:30 Singapore is the previous UTC day.
    due = datetime(2026, 10, 23, 16, 30, tzinfo=UTC)
    done = event(EventKind.FULFILLED, 2, ("done",), at=datetime(2026, 10, 23, 16, 30, tzinfo=UTC))
    one = fixture(fulfilment="FULFILLED", extra=(done,), due=due)
    one = replace(
        one,
        snapshot_at=NOW,
        updated_at=NOW,
        events=(replace(one.events[0], occurred_at=due - timedelta(hours=1)), done),
    )
    missing = replace(
        fixture(due=due), order_id="other", commitment_id="other", events=(), evidence=()
    )
    report = aggregate_daily("t", date(2026, 10, 24), "Asia/Singapore", (one, missing), as_of=NOW)
    assert (
        report.due_orders,
        report.verified_fulfilled_orders,
        report.on_time_fulfilled_orders,
        report.late_fulfilled_orders,
    ) == (2, 1, 1, 0)
    assert report.missing_unknown_evidence == 1
    assert report.eligible_denominator == 2 and report.data_coverage == Decimal("0.5")
    assert report.actuals[0].duration is None
    late = replace(done, occurred_at=due + timedelta(seconds=1))
    later = replace(one, events=(one.events[0], late))
    report = aggregate_daily("t", date(2026, 10, 24), "Asia/Singapore", (later,), as_of=NOW)
    assert report.late_fulfilled_orders == 1 and report.on_time_fulfilled_orders == 0


def test_feedback_only_after_verified_fulfilment_and_link():
    facts = fixture()
    history = SendHistory(True, frozenset())
    assert feedback_readiness(facts, recipient(), history, as_of=NOW).result == Eligibility.BLOCKED
    done = fixture(fulfilment="FULFILLED", extra=(event(EventKind.FULFILLED, 2, ("done",)),))
    invitation = feedback_readiness(done, recipient(), history, as_of=NOW)
    assert invitation.result == Eligibility.ELIGIBLE
    assert (
        feedback_readiness(done, recipient(customer_id="wrong"), history, as_of=NOW).result
        == Eligibility.BLOCKED
    )
    assert (
        feedback_readiness(done, recipient(consent=False), history, as_of=NOW).result
        == Eligibility.BLOCKED
    )
    assert (
        feedback_readiness(
            done, recipient(), SendHistory(True, frozenset({invitation.dedup_key})), as_of=NOW
        ).result
        == Eligibility.ALREADY_HANDLED
    )


def test_optional_actuals_need_both_evidence_and_matching_units():
    due = NOW - timedelta(minutes=5)
    base = fixture(due=due)
    base = replace(
        base,
        planned_quantity=Decimal(12),
        actual_quantity=Decimal(10),
        quantity_unit="kg",
        actual_quantity_unit="kg",
        planned_quantity_ref="planned",
        actual_quantity_ref="actual",
        planned_duration_minutes=Decimal(30),
        actual_duration_minutes=None,
        planned_duration_ref="planned",
        actual_duration_ref="actual",
        evidence=base.evidence
        + (
            Evidence("planned", "PLAN", EvidenceTier.VERIFIED, "t", "c"),
            Evidence("actual", "ACTUAL", EvidenceTier.VERIFIED, "t", "c"),
        ),
    )
    report = aggregate_daily("t", due.date(), "UTC", (base,), as_of=NOW)
    assert report.actuals[0].quantity is not None
    assert report.actuals[0].duration is None
    incompatible = replace(base, actual_quantity_unit="units")
    report = aggregate_daily("t", due.date(), "UTC", (incompatible,), as_of=NOW)
    assert report.actuals[0].quantity is None


def test_reported_completion_count_is_not_fulfilled():
    report_event = event(EventKind.COMPLETION_REPORTED, 2, ("reported",))
    base = fixture(fulfilment="UNVERIFIED", extra=(report_event,), due=NOW)
    base = replace(
        base,
        evidence=tuple(
            replace(item, tier=EvidenceTier.VERIFIED) if item.ref == "reported" else item
            for item in base.evidence
        ),
    )
    summary = aggregate_daily("t", NOW.date(), "UTC", (base,), as_of=NOW)
    assert summary.completion_reported_unverified == 1
    assert summary.verified_fulfilled_orders == 0
