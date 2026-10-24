"""Characterize why current P2 cannot evaluate an unaccepted OrderRequest.

These are regression guards for the legacy evaluator, not a pending-order
adapter. The shared candidate persistence and target mapping are not agreed.
"""

import pytest
from app.core.schemas import AgreementState
from app.feasibility.service import evaluate
from app.feasibility.tests.test_service import changed, fixture


@pytest.mark.parametrize("state", [AgreementState.REQUESTED, AgreementState.OFFERED])
def test_unaccepted_core_state_is_rejected_before_p2_calculation(monkeypatch, state):
    snapshot, commitment = fixture()
    pending = commitment.model_copy(update={"agreement_state": state})

    def unexpected(*args, **kwargs):
        raise AssertionError("P2 calculator must not run for unaccepted Core state")

    monkeypatch.setattr("app.feasibility.service.calculate_atp", unexpected)
    monkeypatch.setattr("app.feasibility.service.check_capacity", unexpected)
    with pytest.raises(ValueError, match="confirmed operational target required"):
        evaluate(snapshot, None, pending)


def test_order_absent_from_confirmed_snapshot_is_not_evaluated(monkeypatch):
    snapshot, commitment = fixture()
    snapshot = changed(snapshot, lambda data: data["operational"].update(confirmed_commitments=()))

    def unexpected(*args, **kwargs):
        raise AssertionError("P2 calculator must not run for absent target")

    monkeypatch.setattr("app.feasibility.service.calculate_atp", unexpected)
    monkeypatch.setattr("app.feasibility.service.check_capacity", unexpected)
    with pytest.raises(ValueError, match="target commitment/version not in snapshot"):
        evaluate(snapshot, None, commitment)
