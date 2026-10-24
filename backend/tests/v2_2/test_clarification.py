from datetime import datetime, timedelta, UTC

import pytest
from pydantic import ValidationError


NOW = datetime(2026, 10, 23, 3, tzinfo=UTC)


def issue(**changes):
    from app.conversations.clarification import UnresolvedIssue
    return UnresolvedIssue.model_validate(dict(
        tenant_id="a", order_id="o", issue_id="sku", version=1, kind="SKU",
        candidates=["A", "B", "C"], created_at=NOW - timedelta(hours=1),
    ) | changes)


def question(**changes):
    from app.conversations.clarification import ClarificationQuestion
    return ClarificationQuestion.model_validate(dict(
        tenant_id="a", order_id="o", issue_id="sku", question_id="q1",
        issue_version=1, sent_at=NOW - timedelta(minutes=10), send_state="SENT",
    ) | changes)


def answer(**changes):
    from app.conversations.clarification import LinkedAnswer
    return LinkedAnswer.model_validate(dict(
        tenant_id="a", order_id="o", issue_id="sku", question_id="q1", answer_id="a1",
        identity_verified=True, received_at=NOW, evidence_refs=["msg1"],
    ) | changes)


def policy(**changes):
    from app.conversations.clarification import ClarificationPolicy
    return ClarificationPolicy.model_validate(dict(
        tenant_id="a", version="1", business_timezone="Asia/Kuala_Lumpur",
        catalog_skus=["A", "B", "C"], allowed_units=["pcs"], max_quantity="1000",
        max_questions=6, max_age_seconds=259200, reminder_after_seconds=86400,
        expire_after_seconds=172800,
        delivery_windows=[{"start": NOW + timedelta(days=1), "end": NOW + timedelta(days=5)}],
    ) | changes)


def apply(current=None, q=None, a=None, **kwargs):
    from app.conversations.clarification import apply_answer
    return apply_answer(current or issue(), q or question(), a or answer(), policy(),
                        now=NOW, total_questions=kwargs.get("total_questions", 1),
                        conversation_started_at=kwargs.get("conversation_started_at", (current or issue()).created_at))


def test_two_consecutive_answered_no_progress_escalate_and_deduplicate():
    first = apply()
    assert first.consecutive_no_progress == 1
    assert first.state == "OPEN"
    assert apply(first, a=answer()) == first  # same response replay
    second = apply(first, q=question(question_id="q2", issue_version=2),
                   a=answer(question_id="q2", answer_id="a2"))
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


@pytest.mark.parametrize("quantity,unit,resolved", [("10", "pcs", True), ("0", "pcs", False),
    ("1001", "pcs", False), ("10", "kg", False), ("many", "pcs", False), ("NaN", "pcs", False)])
def test_quantity_progress_uses_positive_bounded_decimal_and_explicit_unit(quantity, unit, resolved):
    result = apply(issue(kind="QUANTITY"), a=answer(quantity=quantity, unit=unit))
    assert (result.state == "RESOLVED") is resolved


@pytest.mark.parametrize("start,end,resolved", [
    ("2026-10-25T10:00:00+08:00", "2026-10-25T11:00:00+08:00", True),
    ("soon", None, False), ("2026-10-25T10:00:00", "2026-10-25T11:00:00", False),
    ("2026-10-20T10:00:00+08:00", "2026-10-20T11:00:00+08:00", False),
])
def test_delivery_requires_explicit_valid_future_window(start, end, resolved):
    result = apply(issue(kind="DELIVERY"), a=answer(window_start=start, window_end=end))
    assert (result.state == "RESOLVED") is resolved


@pytest.mark.parametrize("change", [
    {"identity_verified": False}, {"tenant_id": "b"}, {"order_id": "other"},
    {"question_id": "q_other"}, {"issue_id": "other"},
    {"received_at": NOW - timedelta(hours=2)}, {"received_at": NOW + timedelta(seconds=1)},
])
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
    from app.conversations.clarification import follow_up
    current = issue()
    sent = question(sent_at=NOW - timedelta(hours=25))
    due = follow_up(current, sent, policy(), now=NOW, conversation_started_at=NOW - timedelta(hours=26))
    assert due.action == "REMINDER_DUE"
    assert due.idempotency_key == follow_up(current, sent, policy(), now=NOW,
                                           conversation_started_at=NOW - timedelta(hours=26)).idempotency_key
    reminded = current.model_copy(update={"reminder_sent_at": NOW})
    assert follow_up(reminded, sent, policy(), now=NOW,
                     conversation_started_at=NOW - timedelta(hours=26)).action == "WAIT"
    expired = follow_up(reminded, sent, policy(), now=NOW + timedelta(hours=24),
                        conversation_started_at=NOW - timedelta(hours=26))
    assert expired.action == "HUMAN_REVIEW"
    assert current.consecutive_no_progress == 0
    assert follow_up(issue(state="RESOLVED"), sent, policy(), now=NOW,
                     conversation_started_at=NOW - timedelta(hours=26)).action == "NONE"


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
    result = apply(issue(created_at=NOW - timedelta(minutes=5)),
                   a=answer(candidate_values=["A"]),
                   conversation_started_at=NOW - timedelta(days=4))
    assert result.state == "HUMAN_REVIEW"
    assert result.reason == "GLOBAL_CLARIFICATION_BUDGET"


def test_delivery_outside_trusted_tenant_operating_window_stays_unresolved():
    result = apply(issue(kind="DELIVERY"), a=answer(
        window_start="2026-11-01T10:00:00+08:00", window_end="2026-11-01T11:00:00+08:00"))
    assert result.state == "OPEN"
    assert result.consecutive_no_progress == 1


def test_dst_fold_cannot_move_answer_inside_later_operating_window():
    from app.conversations.clarification import apply_answer
    result = apply_answer(issue(kind="DELIVERY"), question(), answer(
        window_start="2026-11-01T01:45:00-04:00", window_end="2026-11-01T01:50:00-04:00"),
        policy(business_timezone="America/New_York", delivery_windows=[{
            "start": "2026-11-01T01:30:00-05:00", "end": "2026-11-01T02:00:00-05:00"}]),
        now=NOW, total_questions=1, conversation_started_at=NOW - timedelta(hours=1))
    assert result.state == "OPEN"
