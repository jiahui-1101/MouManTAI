"""Side-effect-free no-reply plan. P4 retains outbound and scheduling authority."""

from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from .models import StrictModel, aware


class FollowUpAction(StrEnum):
    WAITING = "WAITING"
    REMINDER_ELIGIBLE = "REMINDER_ELIGIBLE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    EXPIRED = "EXPIRED"
    NO_ACTION = "NO_ACTION"


class ExpiryAction(StrEnum):
    HUMAN_REVIEW = "HUMAN_REVIEW"
    EXPIRE = "EXPIRE"


class FollowUpPolicy(StrictModel):
    tenant_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    business_timezone: str = Field(min_length=1)
    allowed_from: time
    allowed_until: time
    max_reminders: int = Field(ge=0, le=1)
    expiry_action: ExpiryAction


class SchedulingFacts(StrictModel):
    tenant_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    question_version: int = Field(ge=1)
    sent_at: datetime | None
    response_due_at: datetime | None
    escalate_or_expire_at: datetime | None
    send_history_complete: bool
    response_history_complete: bool
    eligible_reply_received: bool
    reminders_sent: int = Field(ge=0)
    reminder_dedup_keys: frozenset[str] = frozenset()
    channel_permitted: bool
    awaiting_customer: bool

    @field_validator("sent_at", "response_due_at", "escalate_or_expire_at")
    @classmethod
    def check_time(cls, value: datetime | None) -> datetime | None:
        return aware(value) if value is not None else None


class FollowUpPlan(StrictModel):
    action: FollowUpAction
    reason: str
    reminder_dedup_key: str | None = None


def plan_no_reply(
    facts: SchedulingFacts,
    policy: FollowUpPolicy | None,
    *,
    now: datetime,
) -> FollowUpPlan:
    """Return an advisory action; caller must recheck and atomically reserve a send in P4."""
    aware(now)

    def no_action(reason: str) -> FollowUpPlan:
        return FollowUpPlan(action=FollowUpAction.NO_ACTION, reason=reason)

    if policy is None or policy.tenant_id != facts.tenant_id:
        return no_action("POLICY_UNAVAILABLE")
    try:
        zone = ZoneInfo(policy.business_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return no_action("INVALID_TIMEZONE")
    if (
        policy.allowed_from.tzinfo
        or policy.allowed_until.tzinfo
        or policy.allowed_from >= policy.allowed_until
    ):
        return no_action("INVALID_COMMUNICATION_WINDOW")
    if (
        not facts.send_history_complete
        or not facts.response_history_complete
        or facts.sent_at is None
        or facts.response_due_at is None
        or facts.escalate_or_expire_at is None
    ):
        return no_action("AUTHORITATIVE_HISTORY_UNAVAILABLE")
    if (
        facts.sent_at > facts.response_due_at
        or facts.response_due_at >= facts.escalate_or_expire_at
        or facts.reminders_sent > policy.max_reminders
        or now < facts.sent_at
    ):
        return no_action("INCONSISTENT_TIMING_OR_HISTORY")
    if facts.eligible_reply_received or not facts.awaiting_customer:
        return no_action("REPLY_OR_TERMINAL_STATE")
    if now >= facts.escalate_or_expire_at:
        action = (
            FollowUpAction.EXPIRED
            if policy.expiry_action == ExpiryAction.EXPIRE
            else FollowUpAction.HUMAN_REVIEW_REQUIRED
        )
        return FollowUpPlan(action=action, reason="UNANSWERED_DEADLINE")
    if now < facts.response_due_at:
        return FollowUpPlan(action=FollowUpAction.WAITING, reason="RESPONSE_WINDOW_OPEN")
    if facts.reminders_sent >= policy.max_reminders or policy.max_reminders == 0:
        return FollowUpPlan(action=FollowUpAction.WAITING, reason="REMINDER_LIMIT_REACHED")
    key = (
        f"clarification-reminder:{facts.tenant_id}:{facts.draft_id}:"
        f"{facts.question_id}:{facts.question_version}:1"
    )
    if key in facts.reminder_dedup_keys:
        return FollowUpPlan(action=FollowUpAction.WAITING, reason="REMINDER_ALREADY_RESERVED")
    if not facts.channel_permitted:
        return FollowUpPlan(action=FollowUpAction.WAITING, reason="CHANNEL_NOT_PERMITTED")
    local_time = now.astimezone(zone).timetz().replace(tzinfo=None)
    if not policy.allowed_from <= local_time < policy.allowed_until:
        return FollowUpPlan(action=FollowUpAction.WAITING, reason="OUTSIDE_COMMUNICATION_WINDOW")
    return FollowUpPlan(
        action=FollowUpAction.REMINDER_ELIGIBLE, reason="UNANSWERED_DUE", reminder_dedup_key=key
    )
