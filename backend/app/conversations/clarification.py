"""Pure versioned clarification decisions, NOT a durable conversation service.

P1 must load verified linked messages/questions and atomically persist returned
versions plus review/outbox; P4 owns reminder sends and deduped receipts. No API
may accept a client's identity_verified/progress flag as authority.
"""

from datetime import UTC, datetime, time
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
    supported_fulfilment_methods: frozenset[Literal["PICKUP", "DELIVERY"]] = frozenset()
    required_delivery_address_fields: frozenset[Text] = frozenset()
    verified_pickup_option_refs: frozenset[Text] = frozenset()

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
    version: int = Field(ge=1, strict=True)
    kind: Literal["SKU", "QUANTITY", "DELIVERY", "CHOICE", "FULFILMENT"]
    customer_id: Text | None = None
    customer_association_ref: Text | None = None
    customer_association_version: int | None = Field(default=None, ge=1, strict=True)
    source_review_ref: Text | None = None
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
    fulfilment_method: Literal["PICKUP", "DELIVERY"] | None = None
    pickup_option_ref: Text | None = None
    verified_address_field_refs: tuple[Text, ...] = ()


class ClarificationQuestion(ImmutableContract):
    tenant_id: Text
    order_id: Text
    issue_id: Text
    question_id: Text
    question_version: int = Field(default=1, ge=1, strict=True)
    send_receipt_ref: Text | None = None
    issue_version: int = Field(ge=1, strict=True)
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
    fulfilment_method: Literal["PICKUP", "DELIVERY"] | None = None
    pickup_option_ref: Text | None = None
    address_field_refs: tuple[Text, ...] = ()


class TrustedAnswerSource(ImmutableContract):
    """P1/P4 adapter attestation, not proof created by this pure function.

    The adapter must load and check authoritative identity, reviewed source and send
    receipt records in one tenant-scoped snapshot before constructing this value.
    """

    tenant_id: Text
    order_id: Text
    customer_id: Text
    customer_association_ref: Text
    customer_association_version: int = Field(ge=1, strict=True)
    question_id: Text
    question_version: int = Field(ge=1, strict=True)
    answer_id: Text
    source_message_id: Text
    source_message_version_or_digest: Text
    source_review_ref: Text | None = None
    send_receipt_ref: Text
    evidence_ref: Text
    received_at: AwareDatetime
    provenance_status: Literal["VERIFIED", "UNVERIFIED"]


class VerifiedFulfilmentEvidence(ImmutableContract):
    """P1-reviewed option/address references; no raw address or assent text."""

    tenant_id: Text
    order_id: Text
    customer_id: Text
    answer_id: Text
    source_message_id: Text
    policy_version: Text
    method_ref: Text | None = None
    pickup_option_ref: Text | None = None
    address_field_refs: tuple[Text, ...] = ()
    verified: bool


def _scope(
    issue: UnresolvedIssue,
    question: ClarificationQuestion,
    policy: ClarificationPolicy,
    now: datetime,
) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Offset-aware evaluation time required")
    if issue.tenant_id != policy.tenant_id or (issue.tenant_id, issue.order_id, issue.issue_id) != (
        question.tenant_id,
        question.order_id,
        question.issue_id,
    ):
        raise DomainError("CLARIFICATION_NOT_FOUND", "Clarification was not found", status_code=404)


def _validated_progress(
    issue: UnresolvedIssue,
    answer: LinkedAnswer,
    policy: ClarificationPolicy,
    now: datetime,
    fulfilment: VerifiedFulfilmentEvidence | None,
) -> tuple[bool, bool, dict]:
    if issue.kind in {"SKU", "CHOICE"}:
        supplied, previous = set(answer.candidate_values), set(issue.candidates)
        allowed = policy.catalog_skus if issue.kind == "SKU" else previous
        if (
            supplied
            and len(supplied) == len(answer.candidate_values)
            and supplied <= allowed
            and (not previous or supplied < previous or len(supplied) == 1 and supplied == previous)
        ):
            return True, len(supplied) == 1, {"candidates": tuple(sorted(supplied))}
    elif issue.kind == "QUANTITY":
        try:
            quantity = Decimal(answer.quantity or "")
            if (
                quantity.is_finite()
                and 0 < quantity <= policy.max_quantity
                and quantity.as_tuple().exponent >= -6
                and answer.unit in policy.allowed_units
            ):
                return True, True, {"resolved_quantity": quantity, "resolved_unit": answer.unit}
        except (InvalidOperation, ValueError):
            pass
    elif issue.kind == "DELIVERY":
        try:
            start = datetime.fromisoformat(answer.window_start or "")
            end = datetime.fromisoformat(answer.window_end or "")
            if (
                start.tzinfo is not None
                and end.tzinfo is not None
                and now < start < end
                and any(
                    window.start.astimezone(UTC)
                    <= start.astimezone(UTC)
                    < end.astimezone(UTC)
                    <= window.end.astimezone(UTC)
                    for window in policy.delivery_windows
                )
            ):
                return True, True, {"resolved_window_start": start, "resolved_window_end": end}
        except (ValueError, TypeError):
            pass
    elif issue.kind == "FULFILMENT":
        if fulfilment is None or not fulfilment.verified:
            return False, False, {}
        if (
            fulfilment.tenant_id,
            fulfilment.order_id,
            fulfilment.customer_id,
            fulfilment.answer_id,
            fulfilment.policy_version,
        ) != (issue.tenant_id, issue.order_id, issue.customer_id, answer.answer_id, policy.version):
            return False, False, {}
        if not answer.evidence_refs or fulfilment.source_message_id not in answer.evidence_refs:
            return False, False, {}
        method = answer.fulfilment_method or issue.fulfilment_method
        if (
            method is not None
            and method in policy.supported_fulfilment_methods
            and method == fulfilment.method_ref
        ):
            if issue.fulfilment_method is not None and issue.fulfilment_method != method:
                return False, False, {}
            if method == "PICKUP" and (
                answer.pickup_option_ref
                and answer.pickup_option_ref == fulfilment.pickup_option_ref
                and answer.pickup_option_ref in policy.verified_pickup_option_refs
            ):
                return (
                    True,
                    True,
                    {"fulfilment_method": method, "pickup_option_ref": answer.pickup_option_ref},
                )
            if method == "DELIVERY":
                supplied = set(answer.address_field_refs)
                verified = set(fulfilment.address_field_refs)
                previous = set(issue.verified_address_field_refs)
                required = set(policy.required_delivery_address_fields)
                if (
                    required
                    and len(supplied) == len(answer.address_field_refs)
                    and supplied <= verified
                    and supplied <= required
                ):
                    combined = previous | supplied
                    if combined > previous or issue.fulfilment_method != "DELIVERY":
                        return (
                            True,
                            required <= combined,
                            {
                                "fulfilment_method": method,
                                "verified_address_field_refs": tuple(sorted(combined)),
                            },
                        )
                if issue.fulfilment_method != "DELIVERY":
                    return True, False, {"fulfilment_method": method}
    return False, False, {}


def apply_answer(
    issue: UnresolvedIssue,
    question: ClarificationQuestion,
    answer: LinkedAnswer,
    policy: ClarificationPolicy,
    *,
    now: datetime,
    total_questions: int,
    conversation_started_at: datetime,
    trusted_source: TrustedAnswerSource | None = None,
    fulfilment_evidence: VerifiedFulfilmentEvidence | None = None,
) -> UnresolvedIssue:
    _scope(issue, question, policy, now)
    _validate_conversation_start(conversation_started_at, issue, now)
    if not answer.identity_verified or (
        answer.tenant_id,
        answer.order_id,
        answer.issue_id,
        answer.question_id,
    ) != (issue.tenant_id, issue.order_id, issue.issue_id, question.question_id):
        raise DomainError(
            "ANSWER_LINK_UNVERIFIED", "Answer is not verifiably linked", status_code=409
        )
    if (
        trusted_source is None
        or trusted_source.provenance_status != "VERIFIED"
        or issue.customer_id is None
        or issue.customer_association_ref is None
        or issue.customer_association_version is None
        or question.send_receipt_ref is None
    ):
        raise DomainError(
            "ANSWER_SOURCE_UNVERIFIED", "Trusted source binding is unavailable", status_code=409
        )
    if (
        (
            trusted_source.tenant_id,
            trusted_source.order_id,
            trusted_source.customer_id,
            trusted_source.customer_association_ref,
            trusted_source.customer_association_version,
            trusted_source.question_id,
            trusted_source.question_version,
            trusted_source.answer_id,
            trusted_source.send_receipt_ref,
            trusted_source.received_at,
        )
        != (
            issue.tenant_id,
            issue.order_id,
            issue.customer_id,
            issue.customer_association_ref,
            issue.customer_association_version,
            question.question_id,
            question.question_version,
            answer.answer_id,
            question.send_receipt_ref,
            answer.received_at,
        )
        or trusted_source.evidence_ref not in answer.evidence_refs
        or trusted_source.source_message_id not in answer.evidence_refs
        or issue.source_review_ref != trusted_source.source_review_ref
    ):
        raise DomainError(
            "ANSWER_SOURCE_MISMATCH", "Answer source does not match current issue", status_code=409
        )
    if (
        issue.kind == "FULFILMENT"
        and fulfilment_evidence is not None
        and fulfilment_evidence.source_message_id != trusted_source.source_message_id
    ):
        raise DomainError(
            "FULFILMENT_SOURCE_MISMATCH",
            "Fulfilment evidence is from another answer source",
            status_code=409,
        )
    if question.send_state not in {"SENT", "DELIVERED"}:
        raise DomainError("QUESTION_NOT_SENT", "No successfully sent question", status_code=409)
    if not question.sent_at <= answer.received_at <= now:
        raise DomainError(
            "ANSWER_TIME_INVALID", "Answer time does not follow question", status_code=409
        )
    if answer.answer_id in issue.processed_answer_ids:
        return issue
    if issue.state != "OPEN" or question.issue_version != issue.version:
        raise DomainError(
            "STALE_ISSUE_VERSION", "Issue is closed or version changed", status_code=409
        )
    if total_questions < 1:
        raise ValueError("Question budget must include this successfully sent question")
    progress, resolved, changes = _validated_progress(
        issue, answer, policy, now, fulfilment_evidence
    )
    failures = 0 if progress else issue.consecutive_no_progress + 1
    reason = None
    if (
        answer.risk_flags
        or issue.kind == "FULFILMENT"
        and issue.fulfilment_method is not None
        and answer.fulfilment_method not in {None, issue.fulfilment_method}
    ):
        reason = "RISK_REQUIRES_HUMAN_REVIEW"
    elif (
        total_questions >= policy.max_questions
        or (now - conversation_started_at).total_seconds() >= policy.max_age_seconds
    ):
        reason = "GLOBAL_CLARIFICATION_BUDGET"
    elif failures >= 2:
        reason = "TWO_ANSWERED_NO_PROGRESS"
    values = (
        issue.model_dump()
        | changes
        | {
            "version": issue.version + 1,
            "consecutive_no_progress": failures,
            "state": "HUMAN_REVIEW" if reason else "RESOLVED" if resolved else "OPEN",
            "reason": reason,
            "processed_answer_ids": (*issue.processed_answer_ids, answer.answer_id),
            "evidence_refs": tuple(dict.fromkeys((*issue.evidence_refs, *answer.evidence_refs))),
            "last_answer_at": answer.received_at,
            "reminder_sent_at": None,
        }
    )
    return UnresolvedIssue.model_validate(values)


class FollowUpDecision(ImmutableContract):
    action: Literal["WAIT", "NONE", "REMINDER_DUE", "HUMAN_REVIEW"]
    idempotency_key: Text | None = None
    reason: Text | None = None


class DailyContactWindow(ImmutableContract):
    start: time
    end: time

    @model_validator(mode="after")
    def valid_clock(self):
        if self.start.tzinfo or self.end.tzinfo or self.start == self.end:
            raise ValueError("Distinct local naive start/end times required")
        return self


class TrustedContactPolicy(ImmutableContract):
    """P4-supplied contact permission; planner never authorizes transport."""

    tenant_id: Text
    issue_id: Text
    question_id: Text
    question_version: int = Field(ge=1, strict=True)
    version: Text
    clarification_policy_version: Text
    business_timezone: Text
    permitted_weekdays: frozenset[int]
    windows: tuple[DailyContactWindow, ...]
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    allowed_channel: Text
    reminder_limit: int = Field(ge=0, le=1)
    consent_verified: bool

    @model_validator(mode="after")
    def valid_policy(self):
        if (
            self.effective_at >= self.expires_at
            or not self.windows
            or not self.permitted_weekdays
            or not self.permitted_weekdays <= set(range(7))
        ):
            raise ValueError("Invalid contact policy bounds")
        try:
            ZoneInfo(self.business_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Unknown business timezone") from None
        return self


class TrustedQuestionHistory(ImmutableContract):
    """Complete P4/P1 snapshot; missing or unknown outcomes suppress reminders."""

    tenant_id: Text
    order_id: Text
    customer_id: Text
    customer_association_ref: Text
    customer_association_version: int = Field(ge=1, strict=True)
    issue_id: Text
    question_id: Text
    question_version: int = Field(ge=1, strict=True)
    channel: Text
    sent_receipt_ref: Text | None
    send_outcome: Literal["DRAFT", "FAILED", "SUBMITTED", "UNKNOWN", "SENT", "DELIVERED"]
    send_history_complete: bool
    response_history_complete: bool
    linked_reply_id: Text | None = None
    linked_reply_source_ref: Text | None = None
    linked_reply_received_at: AwareDatetime | None = None
    linked_reply_verified: bool = False
    reminder_count: int = Field(ge=0)
    reminder_keys: tuple[Text, ...] = ()
    reminder_outcome_unknown: bool = False


def _contact_allowed(contact: TrustedContactPolicy, now: datetime) -> bool:
    zone = ZoneInfo(contact.business_timezone)
    local = now.astimezone(zone)
    if local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
        return False  # imaginary local wall time in a daylight-saving gap
    # An ambiguous repeated wall time has no unique local communication slot.
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        return False
    clock = local.time().replace(tzinfo=None)
    day = local.weekday()
    for window in contact.windows:
        if window.start < window.end:
            if day in contact.permitted_weekdays and window.start <= clock < window.end:
                return True
        elif (day in contact.permitted_weekdays and clock >= window.start) or (
            (day - 1) % 7 in contact.permitted_weekdays and clock < window.end
        ):
            return True
    return False


def follow_up(
    issue: UnresolvedIssue,
    question: ClarificationQuestion,
    policy: ClarificationPolicy,
    *,
    now: datetime,
    conversation_started_at: datetime,
    history: TrustedQuestionHistory | None = None,
    contact_policy: TrustedContactPolicy | None = None,
    total_questions: int | None = None,
) -> FollowUpDecision:
    """Decision only. Persist intent + dedup key through P4 before any reminder.

    Returned key is stable for a question, independent of scheduler run time.
    Only an actual persisted send receipt sets issue.reminder_sent_at.
    """
    _scope(issue, question, policy, now)
    _validate_conversation_start(conversation_started_at, issue, now)
    if history is None or contact_policy is None or total_questions is None or total_questions < 1:
        return FollowUpDecision(action="NONE", reason="TRUSTED_HISTORY_OR_POLICY_UNAVAILABLE")
    if (
        (
            history.tenant_id,
            history.order_id,
            history.customer_id,
            history.customer_association_ref,
            history.customer_association_version,
            history.issue_id,
            history.question_id,
            history.question_version,
            history.sent_receipt_ref,
        )
        != (
            issue.tenant_id,
            issue.order_id,
            issue.customer_id,
            issue.customer_association_ref,
            issue.customer_association_version,
            issue.issue_id,
            question.question_id,
            question.question_version,
            question.send_receipt_ref,
        )
        or contact_policy.tenant_id != issue.tenant_id
        or contact_policy.clarification_policy_version != policy.version
        or (contact_policy.issue_id, contact_policy.question_id, contact_policy.question_version)
        != (issue.issue_id, question.question_id, question.question_version)
        or contact_policy.business_timezone != policy.business_timezone
        or contact_policy.allowed_channel != history.channel
    ):
        return FollowUpDecision(action="NONE", reason="HISTORY_OR_POLICY_SCOPE_MISMATCH")
    if (
        not history.send_history_complete
        or not history.response_history_complete
        or not contact_policy.consent_verified
        or question.send_receipt_ref is None
        or history.send_outcome not in {"SENT", "DELIVERED"}
        or history.reminder_outcome_unknown
        or question.sent_at > now
    ):
        return FollowUpDecision(action="NONE", reason="AUTHORITY_OR_SEND_UNAVAILABLE")
    if (
        history.linked_reply_id is None
        and history.linked_reply_received_at is not None
        or history.reminder_count == 0
        and issue.reminder_sent_at is not None
        or history.reminder_count == 0
        and history.reminder_keys
    ):
        return FollowUpDecision(action="NONE", reason="HISTORY_INCONSISTENT")
    if history.linked_reply_id is not None:
        if (
            not history.linked_reply_verified
            or history.linked_reply_source_ref is None
            or history.linked_reply_received_at is None
            or history.linked_reply_received_at < question.sent_at
            or history.linked_reply_received_at > now
        ):
            return FollowUpDecision(action="NONE", reason="REPLY_HISTORY_INCONSISTENT")
        return FollowUpDecision(action="NONE", reason="LINKED_REPLY_RECEIVED")
    if (
        issue.state != "OPEN"
        or question.send_state not in {"SENT", "DELIVERED"}
        or issue.last_answer_at is not None
        and issue.last_answer_at >= question.sent_at
    ):
        return FollowUpDecision(action="NONE")
    if question.issue_version != issue.version:
        raise DomainError(
            "STALE_ISSUE_VERSION", "Question belongs to an older issue version", status_code=409
        )
    age = (now - conversation_started_at).total_seconds()
    wait = (now - question.sent_at).total_seconds()
    if total_questions >= policy.max_questions:
        return FollowUpDecision(action="HUMAN_REVIEW", reason="GLOBAL_CLARIFICATION_BUDGET")
    if age >= policy.max_age_seconds or wait >= policy.expire_after_seconds:
        return FollowUpDecision(action="HUMAN_REVIEW", reason="UNANSWERED_EXPIRED")
    if not contact_policy.effective_at <= now < contact_policy.expires_at:
        return FollowUpDecision(action="NONE", reason="CONTACT_POLICY_NOT_CURRENT")
    if history.reminder_count > contact_policy.reminder_limit or history.reminder_count > 1:
        return FollowUpDecision(action="NONE", reason="REMINDER_HISTORY_INCONSISTENT")
    if wait >= policy.reminder_after_seconds and issue.reminder_sent_at is None:
        identity = "\0".join(
            (
                issue.tenant_id,
                issue.order_id,
                issue.issue_id,
                question.question_id,
                str(question.question_version),
            )
        )
        key = "clarify-reminder:" + sha256(identity.encode()).hexdigest()
        if (
            history.reminder_count
            or key in history.reminder_keys
            or contact_policy.reminder_limit == 0
        ):
            return FollowUpDecision(action="WAIT", reason="REMINDER_ALREADY_HANDLED")
        if not _contact_allowed(contact_policy, now):
            return FollowUpDecision(action="WAIT", reason="OUTSIDE_CONTACT_WINDOW")
        return FollowUpDecision(action="REMINDER_DUE", idempotency_key=key)
    return FollowUpDecision(action="WAIT")


def _validate_conversation_start(start: datetime, issue: UnresolvedIssue, now: datetime) -> None:
    if start.tzinfo is None or start.utcoffset() is None or not start <= issue.created_at <= now:
        raise ValueError("Trusted conversation start must precede issue creation and evaluation")
