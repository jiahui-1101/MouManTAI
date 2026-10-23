"""Explicitly synthetic tenant/customer/catalog and message evidence."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.order_clarification.engine import advance_issue
from app.order_clarification.models import (
    AnswerEvent,
    Decision,
    FieldGroup,
    Issue,
    ValidationPolicy,
)

NOW = datetime(2026, 10, 24, 4, tzinfo=UTC)


def policy(**changes):
    values = {
        "tenant_id": "synthetic-tenant",
        "catalog_skus": frozenset({"SKU-A", "SKU-B"}),
        "permitted_units": frozenset({"box", "kg"}),
        "max_quantity": Decimal("1000.00"),
        "business_timezone": "Asia/Singapore",
        "earliest_delivery_at": NOW,
        "latest_delivery_at": NOW + timedelta(days=10),
        "max_delivery_window_seconds": 4 * 3600,
        "required_address_fields": frozenset({"street", "postcode"}),
        "permitted_fulfilment_methods": frozenset({"PICKUP", "DELIVERY"}),
        "max_questions": 6,
        "max_age_seconds": 86400,
    }
    return ValidationPolicy(**(values | changes))


def issue(group=FieldGroup.SKU, **changes):
    values = {
        "tenant_id": "synthetic-tenant",
        "customer_id": "synthetic-customer",
        "draft_id": "synthetic-draft",
        "issue_id": "synthetic-issue",
        "version": 1,
        "field_group": group,
        "allowed_candidates": ("SKU-A", "SKU-B"),
        "question_count": 1,
        "question_id": "synthetic-question",
        "question_version": 1,
        "question_sent_at": NOW - timedelta(minutes=10),
        "draft_created_at": NOW - timedelta(hours=1),
        "created_at": NOW - timedelta(hours=1),
        "updated_at": NOW - timedelta(minutes=10),
    }
    return Issue(**(values | changes))


def answer(**changes):
    values = {
        "tenant_id": "synthetic-tenant",
        "customer_id": "synthetic-customer",
        "draft_id": "synthetic-draft",
        "issue_id": "synthetic-issue",
        "issue_version": 1,
        "question_id": "synthetic-question",
        "question_version": 1,
        "answer_id": "synthetic-answer-1",
        "response_source_ref": "synthetic-message-1",
        "verified_customer_link": True,
        "linked_to_question": True,
        "question_send_succeeded": True,
        "answered_at": NOW - timedelta(minutes=1),
        "evidence_refs": ("synthetic-message-1",),
    }
    return AnswerEvent(**(values | changes))


def apply(item=None, event=None, rules=None, **kwargs):
    return advance_issue(
        (item or issue(),),
        event or answer(),
        rules or policy(),
        total_questions_sent=kwargs.get("total_questions_sent", 1),
        now=kwargs.get("now", NOW),
    )


def test_catalog_choice_resolves():
    result = apply(event=answer(selected_sku="SKU-A"))
    assert result.decision == Decision.RESOLVED
    assert result.issues[0].resolved_values == {"sku": "SKU-A"}


def test_catalog_choice_without_prior_candidates_resolves():
    assert (
        apply(issue(allowed_candidates=()), answer(selected_sku="SKU-A")).decision
        == Decision.RESOLVED
    )


def test_strict_catalog_candidate_reduction():
    result = apply(event=answer(remaining_candidates=("SKU-A",)))
    assert result.decision == Decision.VALIDATED_PROGRESS
    assert result.issues[0].allowed_candidates == ("SKU-A",)


@pytest.mark.parametrize(
    "change",
    [
        {"selected_sku": "INVENTED"},
        {"remaining_candidates": ("SKU-A", "SKU-B")},
        {"remaining_candidates": ("INVENTED",)},
        {"selected_sku": "SKU-A", "evidence_refs": ()},
    ],
)
def test_unverified_or_unchanged_sku_no_progress(change):
    assert apply(event=answer(**change)).decision == Decision.NO_PROGRESS


def test_quantity_decimal_and_unit():
    result = apply(issue(FieldGroup.QUANTITY), answer(quantity=Decimal("12.250"), unit="kg"))
    assert result.decision == Decision.RESOLVED
    assert result.issues[0].resolved_values["quantity"] == "12.250"


@pytest.mark.parametrize(
    "quantity,unit",
    [
        (Decimal(0), "kg"),
        (Decimal(1001), "kg"),
        (Decimal(2), "crate"),
    ],
)
def test_invalid_quantity_does_not_resolve(quantity, unit):
    assert (
        apply(issue(FieldGroup.QUANTITY), answer(quantity=quantity, unit=unit)).decision
        != Decision.RESOLVED
    )


def test_nonfinite_quantity_rejected_by_typed_boundary():
    with pytest.raises(ValueError):
        answer(quantity=Decimal("NaN"), unit="kg")


def test_explicit_delivery_and_narrowing():
    start = (NOW + timedelta(days=1, hours=1)).astimezone(timezone(timedelta(hours=8)))
    end = start + timedelta(hours=2)
    first = apply(
        issue(FieldGroup.DELIVERY),
        answer(delivery_start=start, delivery_end=end, delivery_timezone="Asia/Singapore"),
    )
    assert first.decision == Decision.VALIDATED_PROGRESS
    current = first.issues[0].model_copy(
        update={
            "question_id": "synthetic-question-2",
            "question_version": 2,
            "question_count": 2,
            "question_sent_at": NOW,
        }
    )
    second = answer(
        issue_version=2,
        question_id="synthetic-question-2",
        question_version=2,
        answer_id="synthetic-answer-2",
        answered_at=NOW + timedelta(minutes=1),
        delivery_start=start + timedelta(minutes=30),
        delivery_end=start + timedelta(minutes=30),
        delivery_timezone="Asia/Singapore",
    )
    result = apply(current, second, now=NOW + timedelta(minutes=2))
    assert result.decision == Decision.RESOLVED


def test_ambiguous_or_wrong_zone_delivery():
    assert apply(issue(FieldGroup.DELIVERY), answer()).decision == Decision.NO_PROGRESS
    assert (
        apply(
            issue(FieldGroup.DELIVERY),
            answer(
                delivery_start=NOW + timedelta(days=1),
                delivery_end=NOW + timedelta(days=1),
                delivery_timezone="Unknown/Zone",
            ),
        ).decision
        == Decision.NO_PROGRESS
    )


def test_fulfilment_requires_verified_fields_and_choice():
    result = apply(
        issue(FieldGroup.FULFILMENT),
        answer(
            fulfilment_method="DELIVERY",
            address_fields={"street": "Synthetic St", "postcode": "00000"},
            verified_address_fields=frozenset({"street"}),
        ),
    )
    assert result.decision == Decision.VALIDATED_PROGRESS
    assert "postcode" not in result.issues[0].resolved_values
    pickup = apply(issue(FieldGroup.FULFILMENT), answer(fulfilment_method="PICKUP"))
    assert pickup.decision == Decision.RESOLVED


def test_only_affected_issue_counter_resets():
    target = issue(consecutive_no_progress=1)
    other = issue(issue_id="synthetic-other", consecutive_no_progress=1)
    result = advance_issue(
        (target, other), answer(selected_sku="SKU-A"), policy(), total_questions_sent=1, now=NOW
    )
    assert result.issues[0].consecutive_no_progress == 0
    assert result.issues[1] is other


def test_two_answered_no_progress_attempts_review():
    first = apply().issues[0]
    next_issue = first.model_copy(
        update={
            "question_id": "synthetic-question-2",
            "question_version": 2,
            "question_count": 2,
            "question_sent_at": NOW,
        }
    )
    event = answer(
        issue_version=2,
        question_id="synthetic-question-2",
        question_version=2,
        answer_id="synthetic-answer-2",
        answered_at=NOW + timedelta(minutes=1),
    )
    result = apply(next_issue, event, now=NOW + timedelta(minutes=2))
    assert result.decision == Decision.HUMAN_REVIEW
    assert result.issues[0].consecutive_no_progress == 2
    assert result.issues[0].review_reasons == ("TWO_ANSWERED_NO_PROGRESS",)


@pytest.mark.parametrize(
    "change",
    [
        {"linked_to_question": False},
        {"question_send_succeeded": False},
        {"verified_customer_link": False},
    ],
)
def test_missing_link_or_failed_send_does_not_count(change):
    result = apply(event=answer(**change))
    assert result.decision == Decision.IGNORED
    assert result.issues[0].consecutive_no_progress == 0


def test_no_reply_has_no_answer_event_and_no_transition():
    initial = (issue(),)
    assert initial[0].consecutive_no_progress == 0


def test_duplicate_answer_does_not_count_twice():
    initial = issue(processed_answer_ids=("synthetic-answer-1",))
    assert apply(initial).reason == "DUPLICATE_ANSWER"


@pytest.mark.parametrize(
    "change",
    [
        {"issue_version": 2},
        {"question_version": 2},
        {"question_id": "old-question"},
    ],
)
def test_stale_issue_or_question(change):
    assert apply(event=answer(**change)).reason == "STALE_QUESTION_OR_ISSUE"


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "other-tenant"},
        {"customer_id": "other-customer"},
        {"draft_id": "other-draft"},
    ],
)
def test_cross_scope_rejected(change):
    assert apply(event=answer(**change)).reason == "IDENTITY_MISMATCH"


def test_global_question_and_age_caps():
    assert (
        apply(event=answer(selected_sku="SKU-A"), total_questions_sent=6).reason == "MAX_QUESTIONS"
    )
    aged = issue(draft_created_at=NOW - timedelta(days=2))
    assert apply(aged, answer(selected_sku="SKU-A")).reason == "MAX_AGE"


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        answer(answered_at=NOW.replace(tzinfo=None))
