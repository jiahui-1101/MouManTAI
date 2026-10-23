"""Deterministic per-issue transition, with no order authority or side effects."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import (
    AnswerEvent,
    Decision,
    FieldGroup,
    Issue,
    IssueState,
    Transition,
    ValidationPolicy,
    aware,
)


def _validated_change(issue: Issue, event: AnswerEvent, policy: ValidationPolicy):
    """Return (decision, values, candidates, fields); unverified claims yield no progress."""
    values = dict(issue.resolved_values)
    fields = set(issue.verified_fields)
    candidates = issue.allowed_candidates
    if not event.evidence_refs or event.response_source_ref not in event.evidence_refs:
        return Decision.NO_PROGRESS, values, candidates, fields

    if issue.field_group == FieldGroup.SKU:
        if event.selected_sku in policy.catalog_skus and (
            not candidates or event.selected_sku in candidates
        ):
            values["sku"] = event.selected_sku
            return Decision.RESOLVED, values, candidates, fields | {"sku"}
        narrowed = event.remaining_candidates
        if (
            narrowed
            and len(set(narrowed)) == len(narrowed)
            and set(narrowed) < set(candidates)
            and set(narrowed) <= policy.catalog_skus
        ):
            return Decision.VALIDATED_PROGRESS, values, narrowed, fields

    elif issue.field_group == FieldGroup.QUANTITY:
        quantity = event.quantity
        unit = event.unit
        if unit in policy.permitted_units and "unit" not in fields:
            values["unit"] = unit
            fields.add("unit")
        if (
            type(quantity) is Decimal
            and quantity.is_finite()
            and Decimal(0) < quantity <= policy.max_quantity
            and unit in policy.permitted_units
        ):
            values.update(quantity=str(quantity), unit=unit)
            return Decision.RESOLVED, values, candidates, fields | {"quantity", "unit"}
        if fields != set(issue.verified_fields):
            return Decision.VALIDATED_PROGRESS, values, candidates, fields

    elif issue.field_group == FieldGroup.DELIVERY:
        start, end = event.delivery_start, event.delivery_end
        try:
            zone = ZoneInfo(policy.business_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return Decision.NO_PROGRESS, values, candidates, fields
        if (
            event.delivery_timezone == policy.business_timezone
            and start
            and end
            and policy.earliest_delivery_at <= start <= end <= policy.latest_delivery_at
            and (end - start).total_seconds() <= policy.max_delivery_window_seconds
            and start.astimezone(zone).utcoffset() == start.utcoffset()
            and end.astimezone(zone).utcoffset() == end.utcoffset()
        ):
            old_start = values.get("delivery_start")
            old_end = values.get("delivery_end")
            if old_start and old_end:
                previous_start = datetime.fromisoformat(old_start)
                previous_end = datetime.fromisoformat(old_end)
                if not (
                    previous_start <= start
                    and end <= previous_end
                    and (start > previous_start or end < previous_end)
                ):
                    return Decision.NO_PROGRESS, values, candidates, fields
            values.update(
                delivery_start=start.isoformat(),
                delivery_end=end.isoformat(),
                delivery_timezone=policy.business_timezone,
            )
            decision = Decision.RESOLVED if start == end else Decision.VALIDATED_PROGRESS
            return decision, values, candidates, fields | {"delivery_window"}

    elif issue.field_group == FieldGroup.FULFILMENT:
        method = event.fulfilment_method
        if method in policy.permitted_fulfilment_methods and method != values.get("method"):
            values["method"] = method
            fields.add("method")
        for key in policy.required_address_fields & event.verified_address_fields:
            value = event.address_fields.get(key, "").strip()
            if value and value != values.get(key):
                values[key] = value
                fields.add(key)
        if values.get("method") == "PICKUP":
            return Decision.RESOLVED, values, candidates, fields
        if values.get("method") == "DELIVERY" and policy.required_address_fields <= fields:
            return Decision.RESOLVED, values, candidates, fields
        if fields != set(issue.verified_fields):
            return Decision.VALIDATED_PROGRESS, values, candidates, fields

    return Decision.NO_PROGRESS, dict(issue.resolved_values), candidates, set(issue.verified_fields)


def advance_issue(
    issues: tuple[Issue, ...],
    event: AnswerEvent,
    policy: ValidationPolicy,
    *,
    total_questions_sent: int,
    now: datetime,
) -> Transition:
    """Apply one trusted linked answer; unchanged issues are returned verbatim.

    Caller must atomically persist the returned state and deduplicate answer IDs. A missing
    question, failed send, timeout, or identity/version mismatch never becomes an attempt.
    """
    aware(now)
    if total_questions_sent < 0 or len({i.issue_id for i in issues}) != len(issues):
        raise ValueError("invalid trusted issue snapshot")
    position = next((n for n, i in enumerate(issues) if i.issue_id == event.issue_id), None)
    if position is None:
        return Transition(decision=Decision.IGNORED, reason="ISSUE_NOT_FOUND", issues=issues)
    issue = issues[position]

    def unchanged(reason: str) -> Transition:
        return Transition(decision=Decision.IGNORED, reason=reason, issues=issues)

    if (
        policy.tenant_id != issue.tenant_id
        or event.tenant_id != issue.tenant_id
        or event.customer_id != issue.customer_id
        or event.draft_id != issue.draft_id
    ):
        return unchanged("IDENTITY_MISMATCH")
    if event.answer_id in issue.processed_answer_ids:
        return unchanged("DUPLICATE_ANSWER")
    if (
        event.issue_version != issue.version
        or event.question_id != issue.question_id
        or event.question_version != issue.question_version
    ):
        return unchanged("STALE_QUESTION_OR_ISSUE")
    if issue.state != IssueState.OPEN:
        return unchanged("ISSUE_NOT_OPEN")
    if (
        not event.verified_customer_link
        or not event.linked_to_question
        or not event.question_send_succeeded
        or issue.question_sent_at is None
        or issue.question_count < 1
        or event.answered_at < issue.question_sent_at
        or event.answered_at > now
    ):
        return unchanged("UNVERIFIED_OR_UNSENT_ANSWER")
    if policy.latest_delivery_at < policy.earliest_delivery_at:
        return unchanged("INVALID_POLICY")

    decision, values, candidates, fields = _validated_change(issue, event, policy)
    no_progress = issue.consecutive_no_progress + (decision == Decision.NO_PROGRESS)
    reasons = list(issue.review_reasons)
    if no_progress >= 2:
        reasons.append("TWO_ANSWERED_NO_PROGRESS")
    if total_questions_sent >= policy.max_questions:
        reasons.append("MAX_QUESTIONS")
    if (now - issue.draft_created_at).total_seconds() >= policy.max_age_seconds:
        reasons.append("MAX_AGE")
    state = (
        IssueState.HUMAN_REVIEW
        if reasons
        else IssueState.RESOLVED
        if decision == Decision.RESOLVED
        else IssueState.OPEN
    )
    updated = issue.model_copy(
        update={
            "version": issue.version + 1,
            "allowed_candidates": candidates,
            "resolved_values": values,
            "verified_fields": tuple(sorted(fields)),
            "consecutive_no_progress": no_progress if decision == Decision.NO_PROGRESS else 0,
            "processed_answer_ids": (*issue.processed_answer_ids, event.answer_id),
            "evidence_refs": (*issue.evidence_refs, *event.evidence_refs),
            "state": state,
            "review_reasons": tuple(dict.fromkeys(reasons)),
            "updated_at": now,
        }
    )
    result = list(issues)
    result[position] = updated
    return Transition(
        decision=Decision.HUMAN_REVIEW if reasons else decision,
        reason=reasons[0] if reasons else decision.value,
        issues=tuple(result),
    )
