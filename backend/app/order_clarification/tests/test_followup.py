"""All policy, schedule, and identity values are synthetic fixtures."""

from datetime import UTC, datetime, time, timedelta

import pytest

from app.order_clarification.followup import (
    ExpiryAction,
    FollowUpAction,
    FollowUpPolicy,
    SchedulingFacts,
    plan_no_reply,
)

NOW = datetime(2026, 10, 24, 4, tzinfo=UTC)  # noon in synthetic SG policy


def policy(**changes):
    values = {
        "tenant_id": "synthetic-tenant",
        "policy_id": "synthetic-policy-v1",
        "business_timezone": "Asia/Singapore",
        "allowed_from": time(9),
        "allowed_until": time(18),
        "max_reminders": 1,
        "expiry_action": ExpiryAction.HUMAN_REVIEW,
    }
    return FollowUpPolicy(**(values | changes))


def facts(**changes):
    values = {
        "tenant_id": "synthetic-tenant",
        "draft_id": "synthetic-draft",
        "question_id": "synthetic-question",
        "question_version": 1,
        "sent_at": NOW - timedelta(hours=2),
        "response_due_at": NOW - timedelta(hours=1),
        "escalate_or_expire_at": NOW + timedelta(hours=2),
        "send_history_complete": True,
        "response_history_complete": True,
        "eligible_reply_received": False,
        "reminders_sent": 0,
        "channel_permitted": True,
        "awaiting_customer": True,
    }
    return SchedulingFacts(**(values | changes))


def plan(f=None, p=None, now=NOW):
    return plan_no_reply(f or facts(), p or policy(), now=now)


def test_one_reminder_and_deduplication():
    first = plan()
    assert first.action == FollowUpAction.REMINDER_ELIGIBLE
    assert first.reminder_dedup_key
    assert (
        plan(facts(reminder_dedup_keys=frozenset({first.reminder_dedup_key}))).action
        == FollowUpAction.WAITING
    )
    assert plan(facts(reminders_sent=1)).action == FollowUpAction.WAITING


def test_reply_and_waiting_preclude_reminder():
    assert plan(facts(eligible_reply_received=True)).action == FollowUpAction.NO_ACTION
    assert plan(facts(response_due_at=NOW + timedelta(hours=1))).action == FollowUpAction.WAITING


def test_expiry_or_review_after_later_deadline():
    later = NOW + timedelta(hours=3)
    assert plan(now=later).action == FollowUpAction.HUMAN_REVIEW_REQUIRED
    assert (
        plan(p=policy(expiry_action=ExpiryAction.EXPIRE), now=later).action
        == FollowUpAction.EXPIRED
    )


@pytest.mark.parametrize(
    "change",
    [
        {"send_history_complete": False},
        {"response_history_complete": False},
        {"sent_at": None},
        {"response_due_at": None},
        {"escalate_or_expire_at": None},
        {"response_due_at": NOW + timedelta(hours=3)},
    ],
)
def test_missing_history_and_inconsistent_timing_fail_closed(change):
    assert plan(facts(**change)).action == FollowUpAction.NO_ACTION


def test_missing_policy_invalid_timezone_and_cross_tenant_fail_closed():
    assert plan_no_reply(facts(), None, now=NOW).action == FollowUpAction.NO_ACTION
    assert plan(p=policy(business_timezone="Unknown/Zone")).action == FollowUpAction.NO_ACTION
    assert plan(p=policy(tenant_id="other-tenant")).action == FollowUpAction.NO_ACTION


def test_business_window_and_channel_permission():
    assert plan(now=NOW + timedelta(hours=10)).action == FollowUpAction.HUMAN_REVIEW_REQUIRED
    assert (
        plan(p=policy(allowed_from=time(13), allowed_until=time(17))).action
        == FollowUpAction.WAITING
    )
    assert plan(facts(channel_permitted=False)).action == FollowUpAction.WAITING


def test_naive_schedule_rejected():
    with pytest.raises(ValueError):
        facts(sent_at=NOW.replace(tzinfo=None))
