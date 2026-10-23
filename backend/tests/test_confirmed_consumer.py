"""Worker registration policy for the single canonical P2 confirmed consumer."""

from importlib.util import find_spec

import pytest

from app.core.outbox import OutboxDispatcher
from app.feasibility.consumer import create_p2_confirmed_evaluator
from app.worker import configure_isolated_subscribers


def test_mandatory_consumers_require_explicit_isolated_worker_gate(monkeypatch) -> None:
    assert callable(create_p2_confirmed_evaluator)
    assert find_spec("app.feasibility.confirmed_consumer") is None
    dispatcher = OutboxDispatcher()
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E", raising=False)
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E_KEY", raising=False)
    configure_isolated_subscribers(dispatcher)
    assert dispatcher.get_subscribers("commitment.confirmed") == []
    assert dispatcher.get_subscribers("commitment.at_risk") == []

    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    with pytest.raises(RuntimeError, match="server-owned mutation key"):
        configure_isolated_subscribers(dispatcher)
    assert dispatcher.get_subscribers("commitment.confirmed") == []
    assert dispatcher.get_subscribers("commitment.at_risk") == []

    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", "isolated-key-" + "x" * 32)
    configure_isolated_subscribers(dispatcher)
    assert [name for name, _ in dispatcher.get_subscribers("commitment.confirmed")] == [
        "p2_confirmed_evaluator"
    ]
    assert [name for name, _ in dispatcher.get_subscribers("commitment.at_risk")] == [
        "p3.recovery_trigger.v1"
    ]
    assert [name for name, _ in dispatcher.get_subscribers("confirmation.accepted")] == [
        "p5.confirmation.required"
    ]
    assert {name for name, _ in dispatcher.get_subscribers("confirmation.rejected")} == {
        "p5.confirmation.required",
        "p3.confirmation_response.v1",
    }
