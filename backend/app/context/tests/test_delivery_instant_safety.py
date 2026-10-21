from datetime import datetime, timezone

import pytest

from app.context.tests.test_delivery_context_safety import extract
from app.context.tests.test_deterministic_extraction import stored


@pytest.mark.parametrize("day,clock,reason", [
    ("2026-03-08", "02:30", "nonexistent"),
    ("2026-11-01", "01:30", "ambiguous"),
])
def test_dst_gap_and_fold_are_not_exact_instants(day, clock, reason):
    message = stored(f"Deliver on {day} at {clock}", tz="America/New_York",
                     received_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    field = extract(message)
    assert field.validation_status == "UNRESOLVED" and field.value is None
    assert reason in field.metadata["reason"].lower()


@pytest.mark.parametrize("day,clock,offset", [
    ("2026-03-08", "01:30", "-05:00"), ("2026-03-08", "03:30", "-04:00"),
    ("2026-11-01", "00:30", "-04:00"), ("2026-11-01", "02:30", "-05:00"),
])
def test_real_times_on_both_sides_of_dst_transition_stay_supported(day, clock, offset):
    field = extract(stored(f"Deliver on {day} at {clock}", tz="America/New_York",
                           received_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    assert field.validation_status == "VALID" and field.value == f"{day}T{clock}:00{offset}"


@pytest.mark.parametrize("text", ["Deliver on 2026-10-19", "Deliver today at 9am", "Deliver on 2020-01-01 at 3pm"])
def test_past_deliveries_are_reviewed_without_rolling_forward(text):
    field = extract(stored(text))
    assert field.validation_status == "UNRESOLVED" and field.value is None
    assert "past" in field.metadata["reason"].lower()
    assert field.metadata["candidate_delivery_value"]


def test_delayed_ingestion_does_not_rebase_expired_relative_request():
    message = stored("Deliver tomorrow at 3pm", received_at=datetime(2026, 10, 23, 2, tzinfo=timezone.utc))
    raw = message.raw.model_copy(update={"message_at": datetime(2026, 10, 20, 2, tzinfo=timezone.utc)})
    field = extract(message.model_copy(update={"raw": raw}))
    assert field.validation_status == "UNRESOLVED" and field.value is None
    assert field.metadata["candidate_delivery_value"] == "2026-10-21T15:00:00+08:00"
    assert field.metadata["source_timestamp_source"] == "message_at"


def test_date_only_today_is_a_date_not_an_instant_or_expired_midnight():
    field = extract(stored("Deliver today"))
    assert field.validation_status == "VALID" and field.qualifier == "DATE_ONLY"
    assert field.value == "2026-10-20" and "T" not in field.value


def test_receipt_exact_boundary_is_allowed_for_literal_exact_request():
    field = extract(stored("Deliver today at 10am"))
    assert field.validation_status == "VALID"
    assert field.value == "2026-10-20T10:00:00+08:00"
