from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from app.operational_reporting.models import (
    EventKind,
    Evidence,
    EvidenceTier,
    Milestone,
    ReportingSource,
    SendHistory,
)
from app.operational_reporting.planning import Eligibility, feedback_readiness
from app.operational_reporting.reporting import aggregate_daily
from app.operational_reporting.tests.test_d1 import (
    NOW,
    event,
    facts,
    manifest,
    plan,
    recipient,
    status,
)
from app.operational_reporting.validation import validate_events


def summary(order, projected=None, *, day=None, source=None, tz="UTC", as_of=NOW):
    day = day or as_of.astimezone(ZoneInfo(tz)).date()
    return aggregate_daily(
        "t",
        day,
        tz,
        ((order, projected or status(order)),),
        as_of=as_of,
        source=source or manifest(day, tz),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "other"},
        {"order_id": "other"},
        {"commitment_id": "other"},
    ],
)
def test_cross_scope_accepted_event_never_counts_or_plans(change):
    order = facts(due=NOW)
    corrupted = replace(order, events=(replace(order.events[0], **change),))
    assert (
        "EVENT_BINDING_MISMATCH"
        in validate_events(corrupted, status(corrupted), as_of=NOW).diagnostics
    )
    report = summary(corrupted)
    assert report.accepted_orders == 0 and report.missing_unknown_evidence == 1
    assert (
        plan(order=corrupted, projected=status(corrupted), source=corrupted.events[0]).result
        != Eligibility.ELIGIBLE
    )


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "other"},
        {"order_id": "other"},
        {"commitment_id": "other"},
        {"aggregate_version": 3},
        {"aggregate_version": 0},
    ],
)
def test_cross_scope_or_invalid_version_fulfilment_never_counts(change):
    order = facts(
        events=(event(), event(EventKind.FULFILLED, 2, refs=("done",))),
        fulfilment="FULFILLED",
        due=NOW,
    )
    changed = replace(order, events=(order.events[0], replace(order.events[1], **change)))
    report = summary(changed, status(changed, Milestone.COMPLETED))
    assert report.verified_fulfilled_orders == 0
    assert report.on_time_fulfilled_orders == 0
    assert report.late_fulfilled_orders == 0
    assert report.accepted_orders == 0


def test_identical_replay_collapses_without_double_count():
    order = facts(due=NOW)
    repeated = replace(order, events=(order.events[0], order.events[0]))
    result = validate_events(repeated, status(repeated), as_of=NOW)
    assert result.usable and result.identical_replays == 1 and len(result.events) == 1
    assert summary(repeated).accepted_orders == 1


def test_conflicting_event_id_and_event_version_fail_closed():
    order = facts(due=NOW)
    conflict = replace(order, events=(event(), replace(event(), evidence_refs=("accept",))))
    assert (
        "CONFLICTING_EVENT_ID" in validate_events(conflict, status(conflict), as_of=NOW).diagnostics
    )
    assert summary(conflict).accepted_orders == 0
    same_version = replace(order, events=(event(), replace(event(), event_id="other")))
    assert (
        "CONFLICTING_EVENT_VERSION"
        in validate_events(same_version, status(same_version), as_of=NOW).diagnostics
    )
    assert summary(same_version).accepted_orders == 0


@pytest.mark.parametrize(
    "change,code",
    [
        ({"aggregate_version": 2}, "EVENT_VERSION_OUTSIDE_SNAPSHOT"),
        ({"occurred_at": datetime(2026, 10, 24, 4, 1, tzinfo=UTC)}, "EVENT_OUTSIDE_SOURCE_WINDOW"),
        ({"occurred_at": datetime(2026, 10, 24, 3, 50)}, "EVENT_TIME_NAIVE"),
        ({"kind": "READY_FOR_REVIEW"}, "UNSUPPORTED_EVENT_KIND"),
        ({"evidence_refs": ()}, "MISSING_EVENT_EVIDENCE"),
        ({"evidence_refs": ("accept", "accept", "reserve")}, "MISSING_OR_REPEATED_EVENT_EVIDENCE"),
    ],
)
def test_bad_event_shape_fails_closed(change, code):
    order = facts(due=NOW)
    changed = replace(order, events=(replace(order.events[0], **change),))
    assert code in validate_events(changed, status(changed), as_of=NOW).diagnostics
    assert summary(changed).accepted_orders == 0
    assert (
        plan(order=changed, projected=status(changed), source=changed.events[0]).result
        != Eligibility.ELIGIBLE
    )


def test_future_event_rejected_against_as_of_and_snapshot_with_boundary_allowed():
    future = event(when=NOW + timedelta(seconds=1))
    # Snapshot contains a future event relative to the evaluation instant.
    later_snapshot = facts(events=(future,))
    later_snapshot = replace(
        later_snapshot,
        updated_at=NOW + timedelta(seconds=2),
        snapshot_at=NOW + timedelta(seconds=2),
        event_window_end=NOW + timedelta(seconds=2),
    )
    result = validate_events(later_snapshot, status(later_snapshot), as_of=NOW)
    assert "EVENT_OUTSIDE_SOURCE_WINDOW" in result.diagnostics
    assert (
        plan(order=later_snapshot, projected=status(later_snapshot), source=future).result
        != Eligibility.ELIGIBLE
    )
    # Event is future-dated relative to an otherwise current source snapshot.
    early_snapshot = facts(events=(future,))
    assert (
        "EVENT_OUTSIDE_SOURCE_WINDOW"
        in validate_events(
            early_snapshot, status(early_snapshot), as_of=NOW + timedelta(minutes=1)
        ).diagnostics
    )
    assert (
        plan(
            order=early_snapshot,
            projected=status(early_snapshot),
            source=future,
            at=NOW + timedelta(minutes=1),
            bound=recipient(valid_until=NOW + timedelta(hours=2)),
        ).result
        != Eligibility.ELIGIBLE
    )
    # Equality at both trusted bounds is permitted.
    boundary = facts(events=(event(when=NOW),))
    assert (
        plan(order=boundary, projected=status(boundary), source=boundary.events[0]).result
        == Eligibility.ELIGIBLE
    )


def test_stale_event_and_superseded_out_of_order_source_rejected():
    old = event(when=NOW - timedelta(minutes=61))
    order = facts(events=(old,))
    assert plan(order=order, projected=status(order), source=old).result == Eligibility.BLOCKED
    newer = event(EventKind.READY, 2, when=NOW - timedelta(minutes=5), refs=("ready",))
    order = facts(events=(old, newer))
    projected = replace(
        status(order, Milestone.READY),
        source_event_id=old.event_id,
        milestone=Milestone.ORDER_ACCEPTED,
    )
    assert "STATUS_SOURCE_SUPERSEDED" in validate_events(order, projected, as_of=NOW).diagnostics
    assert plan(order=order, projected=projected, source=old).result != Eligibility.ELIGIBLE


def test_event_outside_reader_window_and_stale_status():
    order = facts(due=NOW)
    too_narrow = replace(order, event_window_start=NOW - timedelta(minutes=1))
    assert (
        "EVENT_OUTSIDE_SOURCE_WINDOW"
        in validate_events(too_narrow, status(too_narrow), as_of=NOW).diagnostics
    )
    stale = replace(status(order), aggregate_version=2)
    assert (
        "STATUS_VECTOR_STALE_OR_MISMATCHED" in validate_events(order, stale, as_of=NOW).diagnostics
    )
    assert summary(order, stale).accepted_orders == 0


@pytest.mark.parametrize(
    "evidence_change,code",
    [
        ({"tenant_id": "other"}, "EVIDENCE_BINDING_MISMATCH"),
        ({"commitment_id": "other"}, "EVIDENCE_BINDING_MISMATCH"),
        ({"tier": EvidenceTier.UNKNOWN}, "UNTRUSTED_EVENT_EVIDENCE_TIER"),
        ({"kind": "SUPPLIER_CLAIM"}, "WRONG_EVENT_EVIDENCE_KIND"),
    ],
)
def test_evidence_binding_tier_and_kind(evidence_change, code):
    order = facts(due=NOW)
    changed = replace(
        order, evidence=(replace(order.evidence[0], **evidence_change), *order.evidence[1:])
    )
    assert code in validate_events(changed, status(changed), as_of=NOW).diagnostics
    assert summary(changed).accepted_orders == 0


def test_duplicate_evidence_ref_conflict_and_demo_only_live_gate():
    order = facts(due=NOW)
    duplicate = replace(
        order, evidence=order.evidence + (replace(order.evidence[0], kind="OTHER"),)
    )
    assert (
        "DUPLICATE_OR_EMPTY_EVIDENCE_REF"
        in validate_events(duplicate, status(duplicate), as_of=NOW).diagnostics
    )
    demo = replace(
        order,
        evidence=tuple(
            replace(e, tier=EvidenceTier.DEMO_ONLY) if e.ref in {"accept", "reserve"} else e
            for e in order.evidence
        ),
    )
    projected = status(demo, tier=EvidenceTier.DEMO_ONLY)
    assert validate_events(demo, projected, as_of=NOW).usable
    assert plan(order=demo, projected=projected).result == Eligibility.UNKNOWN
    report = summary(demo, projected)
    assert report.accepted_orders == 0 and report.data_coverage == 0


def test_superseded_status_source_and_missing_consent_policy_history():
    accepted = event()
    ready = event(EventKind.READY, 2, refs=("ready",))
    order = facts(events=(accepted, ready), due=NOW)
    old = replace(status(order), source_event_id=accepted.event_id)
    assert "STATUS_SOURCE_SUPERSEDED" in validate_events(order, old, as_of=NOW).diagnostics
    assert plan(order=order, projected=old, source=accepted).result == Eligibility.UNKNOWN
    assert plan(bound=recipient(valid_until=None)).result == Eligibility.UNKNOWN
    assert plan(bound=recipient(valid_until=NOW)).result == Eligibility.BLOCKED
    assert plan(history=SendHistory(False, frozenset())).result == Eligibility.UNKNOWN


def test_incomplete_pagination_and_missing_sources_are_explicit():
    order = facts(due=NOW)
    source = manifest(NOW.date(), "UTC")
    report = summary(order, source=source)
    assert not report.source_complete and "SOURCE_INCOMPLETE" in report.limitations
    missing = replace(source, missing_sources=("orders-page-2",))
    report = summary(order, source=missing)
    assert "SOURCES_MISSING" in report.limitations
    assert report.eligible_denominator == 1  # supplied subset only


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "other"},
        {"watermark_at": NOW + timedelta(seconds=1)},
        {"window_start": NOW - timedelta(hours=1)},
        {"complete": True},
    ],
)
def test_invalid_reporting_source_manifest_rejected(change):
    source = replace(manifest(NOW.date(), "UTC"), **change)
    with pytest.raises(ValueError, match="reporting source"):
        summary(facts(due=NOW), source=source)


def test_duplicate_order_rejected():
    order = facts(due=NOW)
    with pytest.raises(ValueError, match="duplicate order"):
        aggregate_daily(
            "t",
            NOW.date(),
            "UTC",
            ((order, status(order)), (order, status(order))),
            as_of=NOW,
            source=manifest(NOW.date(), "UTC"),
        )


def test_demo_fulfilment_never_counts_as_live_or_invites_feedback():
    done = event(EventKind.FULFILLED, 2, refs=("done",))
    order = facts(events=(event(), done), fulfilment="FULFILLED", due=NOW)
    order = replace(
        order,
        evidence=tuple(
            replace(e, tier=EvidenceTier.DEMO_ONLY) if e.ref == "done" else e
            for e in order.evidence
        ),
    )
    projected = status(order, Milestone.COMPLETED, tier=EvidenceTier.DEMO_ONLY)
    report = summary(order, projected)
    assert report.verified_fulfilled_orders == 0
    assert "DEMO_ONLY_EXCLUDED" in report.limitations
    assert (
        feedback_readiness(
            order, projected, recipient(), SendHistory(True, frozenset()), as_of=NOW
        ).result
        == Eligibility.UNKNOWN
    )


def test_reported_completion_and_missing_fulfilment_proof():
    done = event(EventKind.FULFILLED, 2, refs=("missing",))
    order = facts(events=(event(), done), fulfilment="FULFILLED", due=NOW)
    assert summary(order, status(order, Milestone.COMPLETED)).verified_fulfilled_orders == 0
    assert (
        feedback_readiness(
            order,
            status(order, Milestone.COMPLETED),
            recipient(),
            SendHistory(True, frozenset()),
            as_of=NOW,
        ).result
        == Eligibility.UNKNOWN
    )


def test_feedback_rejects_stale_fulfilment_source_and_wrong_customer():
    done = event(EventKind.FULFILLED, 2, refs=("done",))
    order = facts(events=(event(), done), fulfilment="FULFILLED", due=NOW)
    projected = status(order, Milestone.COMPLETED)
    history = SendHistory(True, frozenset())
    assert (
        feedback_readiness(
            replace(order, source_version=1), projected, recipient(), history, as_of=NOW
        ).result
        == Eligibility.UNKNOWN
    )
    assert (
        feedback_readiness(
            order, replace(projected, customer_id="other"), recipient(), history, as_of=NOW
        ).result
        == Eligibility.UNKNOWN
    )
    assert (
        feedback_readiness(
            order, projected, recipient(customer_id="other"), history, as_of=NOW
        ).result
        == Eligibility.BLOCKED
    )


@pytest.mark.parametrize(
    "actual,unit",
    [
        (None, "kg"),
        (Decimal("NaN"), "kg"),
        (Decimal("Infinity"), "kg"),
        (Decimal(-1), "kg"),
        (Decimal(3), "items"),
    ],
)
def test_optional_actuals_reject_missing_nonfinite_negative_and_unit_mismatch(actual, unit):
    order = facts(due=NOW)
    order = replace(
        order,
        planned_quantity=Decimal(3),
        actual_quantity=actual,
        quantity_unit="kg",
        actual_quantity_unit=unit,
        planned_quantity_ref="plan",
        actual_quantity_ref="actual",
        evidence=order.evidence
        + (
            Evidence("plan", "PLAN", EvidenceTier.VERIFIED, "t", "c"),
            Evidence("actual", "ACTUAL", EvidenceTier.VERIFIED, "t", "c"),
        ),
    )
    assert summary(order).actuals[0].quantity is None


def test_midnight_and_dst_fall_back_compare_real_instants():
    zone = ZoneInfo("America/New_York")
    day = date(2026, 11, 1)
    due = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    done_at = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    as_of = datetime(2026, 11, 2, 6, tzinfo=UTC)
    accepted = event(when=datetime(2026, 11, 1, 0, 30, tzinfo=zone))
    done = event(EventKind.FULFILLED, 2, when=done_at, refs=("done",))
    order = facts(events=(accepted, done), fulfilment="FULFILLED", due=due)
    order = replace(
        order,
        updated_at=as_of,
        snapshot_at=as_of,
        event_window_start=datetime(2026, 11, 1, 0, tzinfo=zone),
        event_window_end=as_of,
    )
    start = datetime(2026, 11, 1, 0, tzinfo=zone)
    end = datetime(2026, 11, 2, 0, tzinfo=zone)
    source = ReportingSource("t", start, end, as_of, True, True)
    report = summary(
        order,
        status(order, Milestone.COMPLETED),
        day=day,
        source=source,
        tz="America/New_York",
        as_of=as_of,
    )
    assert report.source_complete
    assert (
        report.due_orders,
        report.verified_fulfilled_orders,
        report.on_time_fulfilled_orders,
        report.late_fulfilled_orders,
    ) == (1, 1, 0, 1)
    assert (end.astimezone(UTC) - start.astimezone(UTC)) == timedelta(hours=25)
