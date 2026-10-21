import pytest

from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, extract_explicit_fields
from app.context.schemas import NormalizedMessage
from app.context.tests.test_deterministic_extraction import stored, named


def delivery(text):
    message = stored(text)
    result = extract_explicit_fields(message, catalog=PROVISIONAL_PRODUCTS)
    NormalizedMessage(message_id=message.message_id, raw=message.raw,
                      content_sha256=message.content_sha256, processing_status="RECEIVED", fields=result.fields)
    return named(result, "requested_delivery_at")[0]


@pytest.mark.parametrize("text", [
    "Deliver tomorrow after 3pm", "Deliver tomorrow not before 3pm",
    "明天下午3点之后送", "Deliver tomorrow around 3pm",
    "Deliver tomorrow between 3pm and 4pm", "Deliver tomorrow at 3pm UTC",
    "Deliver on 2026-10-24 at 15:00 -0500", "Deliver tomorrow at 3pm Asia/Tokyo",
    "Deliver tomorrow maybe at 3pm", "Deliver tomorrow at least 3pm",
])
def test_unsupported_bound_range_or_time_zone_is_not_exact(text):
    field = delivery(text)
    assert field.validation_status == "UNRESOLVED"
    assert field.value is None and field.qualifier is None


@pytest.mark.parametrize("text", [
    "Deliver tomorrow at 3pm; deliver on 2026-10-24 at 4pm",
    "Deliver tomorrow at 3pm. Deliver on 2026-10-24 at 4pm.",
    "Tomorrow at 3pm; 4pm", "Tomorrow. 2026-10-24", "Tomorrow at 3pm\n2026-10-24 at 4pm",
    "Deliver tomorrow; call at 3pm", "Deliver tomorrow. Pickup at 3pm",
])
def test_independent_expressions_never_silently_choose_first(text):
    field = delivery(text)
    assert field.validation_status == "UNRESOLVED" and field.value is None
    assert "conflict" in field.metadata["reason"].lower()
    assert len(field.evidence) >= 1


@pytest.mark.parametrize("token", [
    "25点", "下午25点", "下午3点70分", "3:99pm", "13pm", "25:00", "15:99",
    "15:000", "3:30:00pm", "15:00:00", "3点", "中午3点", "0pm", "003pm",
    "晚上12点", "下午3点30分5秒",
    "3pmx", "15:00foo", "3:30pmx", "3pm30",
])
def test_bad_or_ambiguous_time_cannot_fall_back_to_partial_or_date_only(token):
    field = delivery(f"Deliver on 2026-10-24 at {token}")
    assert field.validation_status in {"INVALID", "UNRESOLVED"}
    assert field.value is None


@pytest.mark.parametrize("text,expected", [
    ("Deliver on 2026-10-24 at 3:30pm", "2026-10-24T15:30:00+08:00"),
    ("Deliver on 2026年10月24日 at 15:30", "2026-10-24T15:30:00+08:00"),
])
def test_overlapping_regex_matches_are_one_expression(text, expected):
    field = delivery(text)
    assert field.validation_status == "VALID" and field.value == expected


def test_unicode_semantic_cue_is_part_of_source_evidence():
    text = "🍔 明天下午3点之后送"
    field = delivery(text)
    assert field.validation_status == "UNRESOLVED"
    assert any("之后" in evidence.quote for evidence in field.evidence)
    assert all(text[e.start:e.end] == e.quote for e in field.evidence)


def test_date_only_deadline_keeps_relation_without_inventing_midnight():
    field = delivery("Deliver before 2026-10-24")
    assert field.value == "2026-10-24" and field.qualifier == "DATE_ONLY"
    assert field.metadata["date_relation"] == "DEADLINE"
