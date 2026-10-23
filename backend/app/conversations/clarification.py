"""Pure versioned clarification decisions, NOT a durable conversation service.

P1 must load verified linked messages/questions and atomically persist returned
versions plus review/outbox; P4 owns reminder sends and deduped receipts. No API
may accept a client's identity_verified/progress flag as authority.
"""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from app.core.errors import DomainError
from app.orders.terms import Amount, Evidence, ImmutableContract, Text


class DeliveryWindow(ImmutableContract):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Operating window must end after it starts")
        return self


class ClarificationPolicy(ImmutableContract):
    tenant_id: Text
    version: Text
    business_timezone: Text
    catalog_skus: frozenset[Text]
    allowed_units: frozenset[Text]
    max_quantity: Amount
    max_questions: int = Field(gt=0)
    max_age_seconds: int = Field(gt=0)
    reminder_after_seconds: int = Field(gt=0)
    expire_after_seconds: int = Field(gt=0)
    # Concrete allowable windows are supplied by a trusted tenant policy adapter;
    # an empty list means date resolution unavailable, never unrestricted hours.
    delivery_windows: tuple[DeliveryWindow, ...]

    @model_validator(mode="after")
    def valid_policy(self):
        if self.expire_after_seconds <= self.reminder_after_seconds:
            raise ValueError("Expiry must follow reminder")
        if self.max_quantity <= 0:
            raise ValueError("Maximum quantity must be positive")
        try:
            ZoneInfo(self.business_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Unknown business timezone") from None
        return self


class UnresolvedIssue(ImmutableContract):
    tenant_id: Text
    order_id: Text
    issue_id: Text
    version: int = Field(ge=1)
    kind: Literal["SKU", "QUANTITY", "DELIVERY", "CHOICE"]
    candidates: tuple[Text, ...] = ()
    created_at: AwareDatetime
    consecutive_no_progress: int = Field(default=0, ge=0)
    state: Literal["OPEN", "RESOLVED", "HUMAN_REVIEW"] = "OPEN"
    reason: Text | None = None
    processed_answer_ids: tuple[Text, ...] = ()
    evidence_refs: tuple[Text, ...] = ()
    reminder_sent_at: AwareDatetime | None = None
    last_answer_at: AwareDatetime | None = None
    resolved_quantity: Amount | None = None
    resolved_unit: Text | None = None
    resolved_window_start: AwareDatetime | None = None
    resolved_window_end: AwareDatetime | None = None


class ClarificationQuestion(ImmutableContract):
    tenant_id: Text
    order_id: Text
    issue_id: Text
    question_id: Text
    issue_version: int = Field(ge=1)
    sent_at: AwareDatetime
    send_state: Literal["DRAFT", "FAILED", "SUBMITTED", "UNKNOWN", "SENT", "DELIVERED"]


class LinkedAnswer(ImmutableContract):
    tenant_id: Text
    order_id: Text
    issue_id: Text
    question_id: Text
    answer_id: Text
    identity_verified: bool
    received_at: AwareDatetime
    evidence_refs: Evidence
    candidate_values: tuple[Text, ...] = ()
    quantity: str | None = None
    unit: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    risk_flags: tuple[Text, ...] = ()


def _scope(issue: UnresolvedIssue, question: ClarificationQuestion, policy: ClarificationPolicy,
           now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Offset-aware evaluation time required")
    if (issue.tenant_id != policy.tenant_id or
            (issue.tenant_id, issue.order_id, issue.issue_id) !=
            (question.tenant_id, question.order_id, question.issue_id)):
        raise DomainError("CLARIFICATION_NOT_FOUND", "Clarification was not found", status_code=404)


def _validated_progress(issue: UnresolvedIssue, answer: LinkedAnswer,
                        policy: ClarificationPolicy, now: datetime) -> tuple[bool, bool, dict]:
    if issue.kind in {"SKU", "CHOICE"}:
        supplied, previous = set(answer.candidate_values), set(issue.candidates)
        allowed = policy.catalog_skus if issue.kind == "SKU" else previous
        if (supplied and len(supplied) == len(answer.candidate_values)
                and supplied <= allowed and (not previous or supplied < previous
                                             or len(supplied) == 1 and supplied == previous)):
            return True, len(supplied) == 1, {"candidates": tuple(sorted(supplied))}
    elif issue.kind == "QUANTITY":
        try:
            quantity = Decimal(answer.quantity or "")
            if (quantity.is_finite() and 0 < quantity <= policy.max_quantity
                    and quantity.as_tuple().exponent >= -6 and answer.unit in policy.allowed_units):
                return True, True, {"resolved_quantity": quantity, "resolved_unit": answer.unit}
        except (InvalidOperation, ValueError):
            pass
    elif issue.kind == "DELIVERY":
        try:
            start = datetime.fromisoformat(answer.window_start or "")
            end = datetime.fromisoformat(answer.window_end or "")
            if (start.tzinfo is not None and end.tzinfo is not None and now < start < end
                    and any(window.start.astimezone(UTC) <= start.astimezone(UTC)
                            < end.astimezone(UTC) <= window.end.astimezone(UTC)
                            for window in policy.delivery_windows)):
                return True, True, {"resolved_window_start": start, "resolved_window_end": end}
        except (ValueError, TypeError):
            pass
    return False, False, {}


def apply_answer(issue: UnresolvedIssue, question: ClarificationQuestion, answer: LinkedAnswer,
                 policy: ClarificationPolicy, *, now: datetime, total_questions: int,
                 conversation_started_at: datetime) -> UnresolvedIssue:
    _scope(issue, question, policy, now)
    _validate_conversation_start(conversation_started_at, issue, now)
    if (not answer.identity_verified or
            (answer.tenant_id, answer.order_id, answer.issue_id, answer.question_id) !=
            (issue.tenant_id, issue.order_id, issue.issue_id, question.question_id)):
        raise DomainError("ANSWER_LINK_UNVERIFIED", "Answer is not verifiably linked", status_code=409)
    if question.send_state not in {"SENT", "DELIVERED"}:
        raise DomainError("QUESTION_NOT_SENT", "No successfully sent question", status_code=409)
    if not question.sent_at <= answer.received_at <= now:
        raise DomainError("ANSWER_TIME_INVALID", "Answer time does not follow question", status_code=409)
    if answer.answer_id in issue.processed_answer_ids:
        return issue
    if issue.state != "OPEN" or question.issue_version != issue.version:
        raise DomainError("STALE_ISSUE_VERSION", "Issue is closed or version changed", status_code=409)
    if total_questions < 1:
        raise ValueError("Question budget must include this successfully sent question")
    progress, resolved, changes = _validated_progress(issue, answer, policy, now)
    failures = 0 if progress else issue.consecutive_no_progress + 1
    reason = None
    if answer.risk_flags:
        reason = "RISK_REQUIRES_HUMAN_REVIEW"
    elif total_questions >= policy.max_questions or (now - conversation_started_at).total_seconds() >= policy.max_age_seconds:
        reason = "GLOBAL_CLARIFICATION_BUDGET"
    elif failures >= 2:
        reason = "TWO_ANSWERED_NO_PROGRESS"
    values = issue.model_dump() | changes | dict(
        version=issue.version + 1, consecutive_no_progress=failures,
        state="HUMAN_REVIEW" if reason else "RESOLVED" if resolved else "OPEN", reason=reason,
        processed_answer_ids=(*issue.processed_answer_ids, answer.answer_id),
        evidence_refs=tuple(dict.fromkeys((*issue.evidence_refs, *answer.evidence_refs))),
        last_answer_at=answer.received_at, reminder_sent_at=None,
    )
    return UnresolvedIssue.model_validate(values)


class FollowUpDecision(ImmutableContract):
    action: Literal["WAIT", "NONE", "REMINDER_DUE", "HUMAN_REVIEW"]
    idempotency_key: Text | None = None
    reason: Text | None = None


def follow_up(issue: UnresolvedIssue, question: ClarificationQuestion, policy: ClarificationPolicy, *,
              now: datetime, conversation_started_at: datetime) -> FollowUpDecision:
    """Decision only. Persist intent + dedup key through P4 before any reminder.

    Returned key is stable for a question, independent of scheduler run time.
    Only an actual persisted send receipt sets issue.reminder_sent_at.
    """
    _scope(issue, question, policy, now)
    _validate_conversation_start(conversation_started_at, issue, now)
    if (issue.state != "OPEN" or question.send_state not in {"SENT", "DELIVERED"}
            or issue.last_answer_at is not None and issue.last_answer_at >= question.sent_at):
        return FollowUpDecision(action="NONE")
    if question.issue_version != issue.version:
        raise DomainError("STALE_ISSUE_VERSION", "Question belongs to an older issue version", status_code=409)
    age = (now - conversation_started_at).total_seconds()
    wait = (now - question.sent_at).total_seconds()
    if age >= policy.max_age_seconds or wait >= policy.expire_after_seconds:
        return FollowUpDecision(action="HUMAN_REVIEW", reason="UNANSWERED_EXPIRED")
    if wait >= policy.reminder_after_seconds and issue.reminder_sent_at is None:
        identity = "\0".join((issue.tenant_id, issue.order_id, issue.issue_id, question.question_id))
        return FollowUpDecision(action="REMINDER_DUE", idempotency_key="clarify-reminder:" +
                                sha256(identity.encode()).hexdigest())
    return FollowUpDecision(action="WAIT")


def _validate_conversation_start(start: datetime, issue: UnresolvedIssue, now: datetime) -> None:
    if start.tzinfo is None or start.utcoffset() is None or not start <= issue.created_at <= now:
        raise ValueError("Trusted conversation start must precede issue creation and evaluation")
