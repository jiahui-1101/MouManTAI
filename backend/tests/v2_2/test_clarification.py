from datetime import UTC, datetime, time, timedelta

import pytest
from pydantic import ValidationError

NOW = datetime(2026, 10, 23, 3, tzinfo=UTC)


def issue(**changes):
    from app.conversations.clarification import UnresolvedIssue

    return UnresolvedIssue.model_validate(
        {
            "tenant_id": "a",
            "order_id": "o",
            "issue_id": "sku",
            "version": 1,
            "kind": "SKU",
            "customer_id": "customer-a",
            "customer_association_ref": "p1:association:a",
            "customer_association_version": 2,
            "candidates": ["A", "B", "C"],
            "created_at": NOW - timedelta(hours=1),
        }
        | changes
    )


def question(**changes):
    from app.conversations.clarification import ClarificationQuestion

    return ClarificationQuestion.model_validate(
        {
            "tenant_id": "a",
            "order_id": "o",
            "issue_id": "sku",
            "question_id": "q1",
            "issue_version": 1,
            "question_version": 1,
            "send_receipt_ref": "p4:receipt:q1",
            "sent_at": NOW - timedelta(minutes=10),
            "send_state": "SENT",
        }
        | changes
    )


def source(current=None, q=None, a=None, **changes):
    from app.conversations.clarification import TrustedAnswerSource

    current, q, a = current or issue(), q or question(), a or answer()
    return TrustedAnswerSource.model_validate(
        {
            "tenant_id": current.tenant_id,
            "order_id": current.order_id,
            "customer_id": current.customer_id,
            "customer_association_ref": current.customer_association_ref,
            "customer_association_version": current.customer_association_version,
            "question_id": q.question_id,
            "question_version": q.question_version,
            "answer_id": a.answer_id,
            "source_message_id": "msg1",
            "source_message_version_or_digest": "sha256:synthetic-v1",
            "source_review_ref": current.source_review_ref,
            "send_receipt_ref": q.send_receipt_ref,
            "evidence_ref": "msg1",
            "received_at": a.received_at,
            "provenance_status": "VERIFIED",
        }
        | changes
    )


def answer(**changes):
    from app.conversations.clarification import LinkedAnswer

    return LinkedAnswer.model_validate(
        {
            "tenant_id": "a",
            "order_id": "o",
            "issue_id": "sku",
            "question_id": "q1",
            "answer_id": "a1",
            "identity_verified": True,
            "received_at": NOW,
            "evidence_refs": ["msg1"],
        }
        | changes
    )


def policy(**changes):
    from app.conversations.clarification import ClarificationPolicy

    return ClarificationPolicy.model_validate(
        {
            "tenant_id": "a",
            "version": "1",
            "business_timezone": "Asia/Kuala_Lumpur",
            "catalog_skus": ["A", "B", "C"],
            "allowed_units": ["pcs"],
            "max_quantity": "1000",
            "max_questions": 6,
            "max_age_seconds": 259200,
            "reminder_after_seconds": 86400,
            "expire_after_seconds": 172800,
            "delivery_windows": [
                {"start": NOW + timedelta(days=1), "end": NOW + timedelta(days=5)}
            ],
        }
        | changes
    )


def apply(current=None, q=None, a=None, **kwargs):
    from app.conversations.clarification import apply_answer

    current, q, a = current or issue(), q or question(), a or answer()
    trusted = kwargs["trusted_source"] if "trusted_source" in kwargs else source(current, q, a)
    return apply_answer(
        current,
        q,
        a,
        kwargs.get("policy") or policy(),
        now=NOW,
        total_questions=kwargs.get("total_questions", 1),
        conversation_started_at=kwargs.get("conversation_started_at", current.created_at),
        trusted_source=trusted,
        fulfilment_evidence=kwargs.get("fulfilment_evidence"),
    )


def contact(q=None, **changes):
    from app.conversations.clarification import TrustedContactPolicy

    q = q or question()
    return TrustedContactPolicy.model_validate(
        {
            "tenant_id": "a",
            "issue_id": q.issue_id,
            "question_id": q.question_id,
            "question_version": q.question_version,
            "version": "1",
            "clarification_policy_version": "1",
            "business_timezone": "Asia/Kuala_Lumpur",
            "permitted_weekdays": list(range(7)),
            "windows": [{"start": time(0), "end": time(23, 59)}],
            "effective_at": NOW - timedelta(days=4),
            "expires_at": NOW + timedelta(days=4),
            "allowed_channel": "SYNTHETIC",
            "reminder_limit": 1,
            "consent_verified": True,
        }
        | changes
    )


def history(q=None, **changes):
    from app.conversations.clarification import TrustedQuestionHistory

    q = q or question()
    return TrustedQuestionHistory.model_validate(
        {
            "tenant_id": q.tenant_id,
            "order_id": q.order_id,
            "customer_id": "customer-a",
            "customer_association_ref": "p1:association:a",
            "customer_association_version": 2,
            "issue_id": q.issue_id,
            "question_id": q.question_id,
            "question_version": q.question_version,
            "channel": "SYNTHETIC",
            "sent_receipt_ref": q.send_receipt_ref,
            "send_outcome": q.send_state,
            "send_history_complete": True,
            "response_history_complete": True,
            "reminder_count": 0,
        }
        | changes
    )


def follow(
    current=None, q=None, *, at=NOW, started=None, p=None, h=None, c=None, total_questions=1
):
    from app.conversations.clarification import follow_up

    current, q = current or issue(), q or question()
    h = h or history(q, reminder_count=int(current.reminder_sent_at is not None))
    return follow_up(
        current,
        q,
        p or policy(),
        now=at,
        conversation_started_at=started or current.created_at,
        history=h,
        contact_policy=c or contact(q),
        total_questions=total_questions,
    )


def test_two_consecutive_answered_no_progress_escalate_and_deduplicate():
    first = apply()
    assert first.consecutive_no_progress == 1
    assert first.state == "OPEN"
    assert apply(first, a=answer()) == first  # same response replay
    second = apply(
        first,
        q=question(question_id="q2", issue_version=2),
        a=answer(question_id="q2", answer_id="a2"),
    )
    assert second.consecutive_no_progress == 2
    assert second.state == "HUMAN_REVIEW"
    assert second.reason == "TWO_ANSWERED_NO_PROGRESS"
    assert first.version == 2


def test_candidate_narrowing_resets_only_that_issue_and_preserves_original():
    original = issue(consecutive_no_progress=1)
    narrowed = apply(original, a=answer(candidate_values=["A", "B"]))
    assert narrowed.candidates == ("A", "B")
    assert narrowed.consecutive_no_progress == 0
    assert original.candidates == ("A", "B", "C")
    assert original.consecutive_no_progress == 1
    other_issue = issue(issue_id="date", kind="DELIVERY", consecutive_no_progress=1)
    assert other_issue.consecutive_no_progress == 1


@pytest.mark.parametrize("candidates", [["A", "B", "C"], ["A", "X"], [], ["A", "A"]])
def test_rephrased_expanded_unknown_or_duplicate_candidates_are_not_progress(candidates):
    result = apply(a=answer(candidate_values=candidates))
    assert result.consecutive_no_progress == 1
    assert result.candidates == ("A", "B", "C")


def test_exact_catalog_choice_resolves():
    result = apply(a=answer(candidate_values=["B"]))
    assert result.state == "RESOLVED"
    assert result.candidates == ("B",)
    assert result.evidence_refs == ("msg1",)


@pytest.mark.parametrize(
    "quantity,unit,resolved",
    [
        ("10", "pcs", True),
        ("0", "pcs", False),
        ("1001", "pcs", False),
        ("10", "kg", False),
        ("many", "pcs", False),
        ("NaN", "pcs", False),
    ],
)
def test_quantity_progress_uses_positive_bounded_decimal_and_explicit_unit(
    quantity, unit, resolved
):
    result = apply(issue(kind="QUANTITY"), a=answer(quantity=quantity, unit=unit))
    assert (result.state == "RESOLVED") is resolved


@pytest.mark.parametrize(
    "start,end,resolved",
    [
        ("2026-10-25T10:00:00+08:00", "2026-10-25T11:00:00+08:00", True),
        ("soon", None, False),
        ("2026-10-25T10:00:00", "2026-10-25T11:00:00", False),
        ("2026-10-20T10:00:00+08:00", "2026-10-20T11:00:00+08:00", False),
    ],
)
def test_delivery_requires_explicit_valid_future_window(start, end, resolved):
    result = apply(issue(kind="DELIVERY"), a=answer(window_start=start, window_end=end))
    assert (result.state == "RESOLVED") is resolved


@pytest.mark.parametrize(
    "change",
    [
        {"identity_verified": False},
        {"tenant_id": "b"},
        {"order_id": "other"},
        {"question_id": "q_other"},
        {"issue_id": "other"},
        {"received_at": NOW - timedelta(hours=2)},
        {"received_at": NOW + timedelta(seconds=1)},
    ],
)
def test_unlinked_or_unverified_answers_rejected_without_progress(change):
    from app.core.errors import DomainError

    with pytest.raises(DomainError):
        apply(a=answer(**change))


@pytest.mark.parametrize("state", ["DRAFT", "FAILED", "SUBMITTED", "UNKNOWN"])
def test_failed_or_unconfirmed_send_never_counts_as_answered_attempt(state):
    from app.core.errors import DomainError

    with pytest.raises(DomainError):
        apply(q=question(send_state=state))
    assert issue().consecutive_no_progress == 0


def test_global_budget_and_risk_escalate_even_if_candidates_narrow():
    assert apply(a=answer(candidate_values=["A", "B"]), total_questions=6).state == "HUMAN_REVIEW"
    assert apply(a=answer(risk_flags=["COMMERCIAL_CHANGE"])).state == "HUMAN_REVIEW"
    assert apply(issue(created_at=NOW - timedelta(days=4))).state == "HUMAN_REVIEW"


def test_idle_reminder_has_stable_dedup_key_then_expiry_without_answer_failure():
    current = issue()
    sent = question(sent_at=NOW - timedelta(hours=25))
    due = follow(current, sent, started=NOW - timedelta(hours=26))
    assert due.action == "REMINDER_DUE"
    assert (
        due.idempotency_key
        == follow(current, sent, started=NOW - timedelta(hours=26)).idempotency_key
    )
    reminded = current.model_copy(update={"reminder_sent_at": NOW})
    assert follow(reminded, sent, started=NOW - timedelta(hours=26)).action == "WAIT"
    expired = follow(
        reminded, sent, at=NOW + timedelta(hours=24), started=NOW - timedelta(hours=26)
    )
    assert expired.action == "HUMAN_REVIEW"
    assert current.consecutive_no_progress == 0
    assert follow(issue(state="RESOLVED"), sent, started=NOW - timedelta(hours=26)).action == "NONE"


def test_policy_has_no_fixture_timer_defaults_and_validates_timezone_and_timer_order():
    from app.conversations.clarification import ClarificationPolicy

    with pytest.raises(ValidationError):
        ClarificationPolicy(tenant_id="a", version="1")
    with pytest.raises(ValidationError):
        policy(expire_after_seconds=60)
    with pytest.raises(ValidationError):
        policy(business_timezone="fake")


def test_explicit_singleton_confirmation_resolves_even_without_narrowing():
    result = apply(issue(candidates=["A"]), a=answer(candidate_values=["A"]))
    assert result.state == "RESOLVED"
    assert result.consecutive_no_progress == 0


def test_new_issue_cannot_reset_global_conversation_age():
    result = apply(
        issue(created_at=NOW - timedelta(minutes=5)),
        a=answer(candidate_values=["A"]),
        conversation_started_at=NOW - timedelta(days=4),
    )
    assert result.state == "HUMAN_REVIEW"
    assert result.reason == "GLOBAL_CLARIFICATION_BUDGET"


def test_delivery_outside_trusted_tenant_operating_window_stays_unresolved():
    result = apply(
        issue(kind="DELIVERY"),
        a=answer(window_start="2026-11-01T10:00:00+08:00", window_end="2026-11-01T11:00:00+08:00"),
    )
    assert result.state == "OPEN"
    assert result.consecutive_no_progress == 1


def test_dst_fold_cannot_move_answer_inside_later_operating_window():
    from app.conversations.clarification import apply_answer

    result = apply_answer(
        issue(kind="DELIVERY"),
        question(),
        answer(window_start="2026-11-01T01:45:00-04:00", window_end="2026-11-01T01:50:00-04:00"),
        policy(
            business_timezone="America/New_York",
            delivery_windows=[
                {"start": "2026-11-01T01:30:00-05:00", "end": "2026-11-01T02:00:00-05:00"}
            ],
        ),
        now=NOW,
        total_questions=1,
        conversation_started_at=NOW - timedelta(hours=1),
        trusted_source=source(),
    )
    assert result.state == "OPEN"


def test_zero_length_delivery_window_is_not_resolved():
    result = apply(
        issue(kind="DELIVERY"),
        a=answer(window_start="2026-10-25T10:00:00+08:00", window_end="2026-10-25T10:00:00+08:00"),
    )
    assert result.state == "OPEN" and result.consecutive_no_progress == 1


def test_trusted_customer_source_and_question_version_bind_progress():
    assert apply(a=answer(candidate_values=["A"])).state == "RESOLVED"
    from app.core.errors import DomainError

    for change in (
        {"customer_id": "other"},
        {"tenant_id": "other"},
        {"order_id": "other"},
        {"question_id": "other"},
        {"question_version": 2},
        {"customer_association_version": 1},
        {"answer_id": "other"},
        {"source_message_id": "other"},
        {"evidence_ref": "other"},
        {"send_receipt_ref": "unknown"},
        {"provenance_status": "UNVERIFIED"},
    ):
        with pytest.raises(DomainError):
            apply(a=answer(candidate_values=["A"]), trusted_source=source(**change))


def test_missing_source_or_send_receipt_fails_closed():
    from app.conversations.clarification import apply_answer
    from app.core.errors import DomainError

    with pytest.raises(DomainError, match="Trusted source binding"):
        apply_answer(
            issue(),
            question(),
            answer(),
            policy(),
            now=NOW,
            total_questions=1,
            conversation_started_at=NOW - timedelta(hours=1),
        )
    with pytest.raises(DomainError):
        apply(q=question(send_receipt_ref=None), trusted_source=source())


def test_fulfilment_only_uses_reviewed_policy_and_field_refs():
    from app.conversations.clarification import VerifiedFulfilmentEvidence

    configured = policy(
        supported_fulfilment_methods=["PICKUP", "DELIVERY"],
        verified_pickup_option_refs=["pickup-a"],
        required_delivery_address_fields=["street", "postcode"],
    )

    def evidence(**changes):
        return VerifiedFulfilmentEvidence.model_validate(
            {
                "tenant_id": "a",
                "order_id": "o",
                "customer_id": "customer-a",
                "answer_id": "a1",
                "source_message_id": "msg1",
                "policy_version": "1",
                "verified": True,
            }
            | changes
        )

    pickup = apply(
        issue(kind="FULFILMENT"),
        a=answer(fulfilment_method="PICKUP", pickup_option_ref="pickup-a"),
        policy=configured,
        fulfilment_evidence=evidence(method_ref="PICKUP", pickup_option_ref="pickup-a"),
    )
    assert pickup.state == "RESOLVED" and pickup.pickup_option_ref == "pickup-a"
    unsupported = apply(
        issue(kind="FULFILMENT"),
        a=answer(fulfilment_method="PICKUP", pickup_option_ref="other"),
        policy=configured,
        fulfilment_evidence=evidence(method_ref="PICKUP", pickup_option_ref="other"),
    )
    assert unsupported.state == "OPEN" and unsupported.consecutive_no_progress == 1
    partial = apply(
        issue(kind="FULFILMENT"),
        a=answer(fulfilment_method="DELIVERY", address_field_refs=["street"]),
        policy=configured,
        fulfilment_evidence=evidence(method_ref="DELIVERY", address_field_refs=["street"]),
    )
    assert partial.state == "OPEN" and partial.verified_address_field_refs == ("street",)
    assert partial.consecutive_no_progress == 0
    next_question = question(
        question_id="q2", issue_version=2, question_version=2, send_receipt_ref="p4:receipt:q2"
    )
    next_answer = answer(question_id="q2", answer_id="a2", address_field_refs=["postcode"])
    completed_later = apply(
        partial,
        q=next_question,
        a=next_answer,
        policy=configured,
        fulfilment_evidence=evidence(
            answer_id="a2", method_ref="DELIVERY", address_field_refs=["postcode"]
        ),
    )
    assert completed_later.state == "RESOLVED"
    complete = apply(
        issue(kind="FULFILMENT"),
        a=answer(fulfilment_method="DELIVERY", address_field_refs=["street", "postcode"]),
        policy=configured,
        fulfilment_evidence=evidence(
            method_ref="DELIVERY", address_field_refs=["street", "postcode"]
        ),
    )
    assert complete.state == "RESOLVED"
    unverified = apply(
        issue(kind="FULFILMENT"),
        a=answer(fulfilment_method="DELIVERY", address_field_refs=["street", "postcode"]),
        policy=configured,
        fulfilment_evidence=evidence(
            method_ref="DELIVERY", address_field_refs=["street", "postcode"], verified=False
        ),
    )
    assert unverified.state == "OPEN"
    from app.core.errors import DomainError

    with pytest.raises(DomainError, match="another answer source"):
        apply(
            issue(kind="FULFILMENT"),
            a=answer(fulfilment_method="DELIVERY"),
            policy=configured,
            fulfilment_evidence=evidence(
                method_ref="DELIVERY", source_message_id="unrelated-message"
            ),
        )
    assert (
        apply(
            issue(kind="FULFILMENT"),
            a=answer(fulfilment_method="DELIVERY"),
            fulfilment_evidence=evidence(method_ref="DELIVERY"),
        ).state
        == "OPEN"
    )


def test_conflicting_fulfilment_choice_requires_review():
    configured = policy(supported_fulfilment_methods=["PICKUP", "DELIVERY"])
    result = apply(
        issue(kind="FULFILMENT", fulfilment_method="DELIVERY"),
        a=answer(fulfilment_method="PICKUP"),
        policy=configured,
    )
    assert result.state == "HUMAN_REVIEW" and result.reason == "RISK_REQUIRES_HUMAN_REVIEW"


@pytest.mark.parametrize("outcome", ["DRAFT", "FAILED", "SUBMITTED", "UNKNOWN"])
def test_unconfirmed_send_history_cannot_plan_reminder(outcome):
    sent = question(sent_at=NOW - timedelta(hours=25))
    assert (
        follow(
            q=sent, h=history(sent, send_outcome=outcome), started=NOW - timedelta(hours=26)
        ).action
        == "NONE"
    )


def test_silence_history_and_reminder_planning_leave_counter_unchanged():
    current = issue(consecutive_no_progress=1)
    sent = question(sent_at=NOW - timedelta(hours=25))
    assert follow(current, sent, started=NOW - timedelta(hours=26)).action == "REMINDER_DUE"
    assert current.consecutive_no_progress == 1 and current.state == "OPEN"
    assert (
        follow(current, sent, at=NOW + timedelta(days=3), started=NOW - timedelta(hours=26)).action
        == "HUMAN_REVIEW"
    )
    assert current.consecutive_no_progress == 1
    assert (
        follow(current, sent, started=NOW - timedelta(hours=26), total_questions=6).reason
        == "GLOBAL_CLARIFICATION_BUDGET"
    )


def test_followup_history_reply_dedup_and_missing_authority():
    from app.conversations.clarification import follow_up

    sent = question(sent_at=NOW - timedelta(hours=25))
    start = NOW - timedelta(hours=26)
    due = follow(q=sent, started=start)
    assert due.action == "REMINDER_DUE"
    assert (
        follow(q=sent, h=history(sent, reminder_keys=[due.idempotency_key]), started=start).action
        == "NONE"
    )
    assert follow(q=sent, h=history(sent, reminder_count=1), started=start).action == "WAIT"
    assert (
        follow(q=sent, h=history(sent, reminder_outcome_unknown=True), started=start).action
        == "NONE"
    )
    assert (
        follow(q=sent, h=history(sent, response_history_complete=False), started=start).action
        == "NONE"
    )
    assert (
        follow(
            q=sent,
            h=history(
                sent,
                linked_reply_id="reply-a",
                linked_reply_source_ref="p1:message:reply-a",
                linked_reply_received_at=NOW,
                linked_reply_verified=True,
            ),
            started=start,
        ).reason
        == "LINKED_REPLY_RECEIVED"
    )
    assert (
        follow(
            q=sent,
            h=history(
                sent,
                linked_reply_id="reply-a",
                linked_reply_source_ref="p1:message:reply-a",
                linked_reply_received_at=sent.sent_at - timedelta(seconds=1),
                linked_reply_verified=True,
            ),
            started=start,
        ).reason
        == "REPLY_HISTORY_INCONSISTENT"
    )
    assert (
        follow_up(issue(), sent, policy(), now=NOW, conversation_started_at=start).action == "NONE"
    )
    assert follow(q=sent, c=contact(consent_verified=False), started=start).action == "NONE"


def test_contact_windows_expiry_cross_midnight_and_dst_fold():
    sent = question(sent_at=NOW - timedelta(hours=25))
    start = NOW - timedelta(hours=26)
    assert (
        follow(
            q=sent, c=contact(windows=[{"start": time(12), "end": time(17)}]), started=start
        ).reason
        == "OUTSIDE_CONTACT_WINDOW"
    )
    assert (
        follow(q=sent, c=contact(expires_at=NOW - timedelta(minutes=1)), started=start).reason
        == "CONTACT_POLICY_NOT_CURRENT"
    )
    midnight = datetime(2026, 10, 23, 16, 30, tzinfo=UTC)
    assert (
        follow(
            q=sent,
            at=midnight,
            c=contact(permitted_weekdays=[4], windows=[{"start": time(22), "end": time(2)}]),
            started=start,
        ).action
        == "REMINDER_DUE"
    )
    fold = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    new_issue = issue(created_at=fold - timedelta(hours=26))
    new_question = question(sent_at=fold - timedelta(hours=25))
    ny_policy = policy(business_timezone="America/New_York")
    ny_contact = contact(
        business_timezone="America/New_York",
        effective_at=fold - timedelta(days=1),
        expires_at=fold + timedelta(days=1),
        windows=[{"start": time(1), "end": time(2)}],
    )
    assert (
        follow(
            new_issue,
            new_question,
            at=fold,
            started=fold - timedelta(hours=27),
            p=ny_policy,
            c=ny_contact,
        ).reason
        == "OUTSIDE_CONTACT_WINDOW"
    )


def test_followup_history_scope_and_contact_policy_fail_closed():
    sent = question(sent_at=NOW - timedelta(hours=25))
    start = NOW - timedelta(hours=26)
    for change in (
        {"tenant_id": "other"},
        {"customer_id": "other"},
        {"customer_association_version": 1},
        {"question_id": "old"},
        {"question_version": 2},
        {"sent_receipt_ref": "unknown"},
        {"channel": "OTHER"},
    ):
        assert (
            follow(q=sent, h=history(sent, **change), started=start).reason
            == "HISTORY_OR_POLICY_SCOPE_MISMATCH"
        )
    assert (
        follow(q=sent, h=history(sent, send_history_complete=False), started=start).action == "NONE"
    )
    assert follow(q=sent, c=contact(question_version=2), started=start).action == "NONE"
    assert (
        follow(
            q=sent,
            h=history(
                sent,
                linked_reply_id="reply-a",
                linked_reply_received_at=NOW,
                linked_reply_verified=True,
            ),
            started=start,
        ).reason
        == "REPLY_HISTORY_INCONSISTENT"
    )
    assert follow(q=sent, c=contact(reminder_limit=0), started=start).action == "WAIT"
    with pytest.raises(ValidationError):
        contact(business_timezone="Invalid/Zone")
    with pytest.raises(ValidationError):
        contact(windows=[{"start": time(9), "end": time(9)}])


def test_nonexistent_local_hour_cannot_make_reminder_due():
    # 02:30 never occurs on this New York spring-forward date. The actual
    # instant is 03:30, so a 02:00-03:00 window cannot authorize a reminder.
    instant = datetime(2027, 3, 14, 7, 30, tzinfo=UTC)
    current = issue(created_at=instant - timedelta(hours=26))
    sent = question(sent_at=instant - timedelta(hours=25))
    ny_contact = contact(
        business_timezone="America/New_York",
        effective_at=instant - timedelta(days=1),
        expires_at=instant + timedelta(days=1),
        windows=[{"start": time(2), "end": time(3)}],
    )
    result = follow(
        current,
        sent,
        at=instant,
        started=instant - timedelta(hours=27),
        p=policy(business_timezone="America/New_York"),
        c=ny_contact,
    )
    assert result.reason == "OUTSIDE_CONTACT_WINDOW"


def test_invalid_timestamps_and_source_review_binding():
    with pytest.raises(ValidationError):
        source(received_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        history(linked_reply_received_at=NOW.replace(tzinfo=None))
    from app.core.errors import DomainError

    with pytest.raises(DomainError):
        apply(issue(source_review_ref="p1:review:2"), trusted_source=source())
