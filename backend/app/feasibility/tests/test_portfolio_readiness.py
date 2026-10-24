from datetime import timedelta

import pytest
from app.core.schemas import FeasibilityState
from app.feasibility.capacity import CapacityResult
from app.feasibility.inventory import calculate_atp
from app.feasibility.materials import MaterialATP
from app.feasibility.portfolio_readiness import inspect_portfolio_inputs
from app.feasibility.tests.test_service import changed, competing_snapshot, fixture


def inspect(snapshot=None, *, at=None, tenant_id=None, pending=()):
    original, commitment = fixture()
    snapshot = original if snapshot is None else snapshot
    return inspect_portfolio_inputs(
        tenant_id=commitment.tenant_id if tenant_id is None else tenant_id,
        snapshot=snapshot,
        checked_at=snapshot.as_of if at is None else at,
        pending_order_request_ids=pending,
    )


def test_complete_confirmed_baseline_is_read_only_and_not_optimization_approval():
    snapshot, _ = fixture()
    before = snapshot.model_dump_json()
    result = inspect(snapshot)
    assert result.status == "BASELINE_COMPLETE"
    assert result.material_status == "COVERED"
    assert result.capacity_status == "FEASIBLE"
    assert result.evidence_refs
    assert (
        result.profit_strategy_available,
        result.expiry_strategy_available,
        result.allocation_authorized,
    ) == (False, False, False)
    assert inspect(snapshot) == result
    assert snapshot.model_dump_json() == before


@pytest.mark.parametrize(
    "capacity_state", [FeasibilityState.CONDITIONAL, FeasibilityState.NOT_ASSESSED]
)
def test_nonterminal_capacity_without_constraints_never_completes_baseline(
    monkeypatch, capacity_state
):
    snapshot, _ = fixture()
    before = snapshot.model_dump_json()
    capacity = CapacityResult(status=capacity_state, constraints=())
    monkeypatch.setattr(
        "app.feasibility.portfolio_readiness.check_capacity", lambda *a, **k: capacity
    )

    result = inspect(snapshot)

    assert result.material_status == "COVERED"
    assert result.capacity_status is capacity_state
    assert result.status == "UNKNOWN"
    assert "CAPACITY_BASELINE_NOT_PROVEN" in result.blocker_codes
    assert result.allocation_authorized is False
    assert result.profit_strategy_available is False
    assert result.expiry_strategy_available is False
    assert inspect(snapshot) == result
    assert snapshot.model_dump_json() == before


@pytest.mark.parametrize(
    "capacity_state,expected",
    [
        (FeasibilityState.UNKNOWN, "UNKNOWN"),
        (FeasibilityState.INFEASIBLE, "BASELINE_BLOCKED"),
    ],
)
def test_noneligible_capacity_without_constraints_has_diagnostic(
    monkeypatch, capacity_state, expected
):
    snapshot, _ = fixture()
    capacity = CapacityResult(status=capacity_state, constraints=())
    monkeypatch.setattr(
        "app.feasibility.portfolio_readiness.check_capacity", lambda *a, **k: capacity
    )

    result = inspect(snapshot)

    assert result.status == expected
    assert result.blocker_codes == ("CAPACITY_BASELINE_NOT_PROVEN",)
    assert result.allocation_authorized is False


def test_missing_capacity_evidence_fails_closed(monkeypatch):
    snapshot, _ = fixture()
    monkeypatch.setattr("app.feasibility.portfolio_readiness.check_capacity", lambda *a, **k: None)

    result = inspect(snapshot)

    assert result.status == "UNKNOWN"
    assert result.capacity_status is None
    assert result.blocker_codes == ("CAPACITY_BASELINE_NOT_PROVEN",)
    assert result.allocation_authorized is False


@pytest.mark.parametrize(
    "material_state,expected", [("UNKNOWN", "UNKNOWN"), ("SHORTAGE", "BASELINE_BLOCKED")]
)
def test_noncovered_material_without_issues_has_diagnostic(monkeypatch, material_state, expected):
    snapshot, commitment = fixture()
    original = calculate_atp(
        snapshot.operational, tenant_id=commitment.tenant_id, as_of=snapshot.as_of
    )
    materials = MaterialATP.model_validate(
        {**original.model_dump(), "status": material_state, "issues": ()}
    )
    monkeypatch.setattr(
        "app.feasibility.portfolio_readiness.calculate_atp", lambda *a, **k: materials
    )

    result = inspect(snapshot)

    assert result.capacity_status is FeasibilityState.FEASIBLE
    assert result.status == expected
    assert result.blocker_codes == ("MATERIAL_BASELINE_NOT_PROVEN",)
    assert result.allocation_authorized is False


def test_missing_material_evidence_fails_closed(monkeypatch):
    snapshot, _ = fixture()
    monkeypatch.setattr("app.feasibility.portfolio_readiness.calculate_atp", lambda *a, **k: None)

    result = inspect(snapshot)

    assert result.status == "UNKNOWN"
    assert result.material_status is None
    assert result.blocker_codes == ("MATERIAL_BASELINE_NOT_PROVEN",)
    assert result.allocation_authorized is False


def test_pending_target_precedence_over_unproven_capacity(monkeypatch):
    snapshot, _ = fixture()
    capacity = CapacityResult(status=FeasibilityState.CONDITIONAL, constraints=())
    monkeypatch.setattr(
        "app.feasibility.portfolio_readiness.check_capacity", lambda *a, **k: capacity
    )

    result = inspect(snapshot, pending=("request-1",))

    assert result.status == "PENDING_TARGET_UNSUPPORTED"
    assert result.blocker_codes == ("PENDING_TARGET_UNSUPPORTED", "CAPACITY_BASELINE_NOT_PROVEN")
    assert result.allocation_authorized is False


@pytest.mark.parametrize(
    "kind,code",
    [
        ("missing", "SNAPSHOT_UNAVAILABLE"),
        ("tenant", "TENANT_MISMATCH"),
        ("version", "SNAPSHOT_VERSION_CONFLICT"),
        ("token", "CURRENT_VERSION_UNAVAILABLE"),
        ("future", "SNAPSHOT_FROM_FUTURE"),
        ("provenance", "SOURCE_PROVENANCE_INCOMPLETE"),
    ],
)
def test_snapshot_boundaries_fail_closed(kind, code):
    snapshot, commitment = fixture()
    if kind == "missing":
        result = inspect_portfolio_inputs(
            tenant_id=commitment.tenant_id, snapshot=None, checked_at=snapshot.as_of
        )
    else:
        if kind == "version":
            snapshot = changed(snapshot, lambda d: d.update(current_snapshot_version=2))
        elif kind == "token":
            snapshot = changed(snapshot, lambda d: d.update(current_snapshot_version=None))
        elif kind == "provenance":
            snapshot = changed(
                snapshot, lambda d: d["operational"]["sources"][0].update(evidence_refs=())
            )
        result = inspect(
            snapshot,
            tenant_id="other" if kind == "tenant" else None,
            at=snapshot.operational.captured_at - timedelta(seconds=1)
            if kind == "future"
            else None,
        )
    assert result.status == "UNKNOWN"
    assert result.blocker_codes == (code,)
    assert not result.allocation_authorized


def test_stale_unknown_and_shortage_use_p2_outcomes():
    snapshot, _ = fixture()
    assert inspect(snapshot, at=snapshot.as_of + timedelta(days=5)).status == "UNKNOWN"
    assert (
        inspect(changed(snapshot, lambda d: d["production"].update(jobs=None))).status == "UNKNOWN"
    )
    shortage = changed(
        snapshot, lambda d: d["operational"]["inventory_lots"][0].update(quantity="70")
    )
    assert inspect(shortage).status == "BASELINE_BLOCKED"


def test_capacity_conflict_and_competing_material_are_joint_baseline_findings():
    from app.feasibility.tests.test_capacity import dt

    snapshot, _ = fixture()
    conflict = changed(
        snapshot,
        lambda d: d["production"].update(
            jobs=(
                {
                    "job_id": "blocking",
                    "tenant_id": d["operational"]["tenant_id"],
                    "resource_ids": ("kitchen-line-1",),
                    "start_at": dt("10:00:00"),
                    "end_at": dt("11:00:00"),
                    "source_refs": ("production-jobs",),
                },
            )
        ),
    )
    assert inspect(conflict).status == "BASELINE_BLOCKED"
    competing, _ = competing_snapshot()
    assert inspect(competing).status == "BASELINE_BLOCKED"


def test_pending_orders_never_become_feasible_by_omission():
    snapshot, _ = fixture()
    result = inspect(snapshot, pending=("request-1", "request-2"))
    assert result.status == "PENDING_TARGET_UNSUPPORTED"
    assert result.material_status == "COVERED"
    assert not result.allocation_authorized
    with pytest.raises(ValueError, match="unique and nonblank"):
        inspect(snapshot, pending=("request-1", "request-1"))


def test_missing_lot_expiry_and_profit_inputs_cannot_enable_strategies():
    snapshot, _ = fixture()
    no_expiry = changed(
        snapshot, lambda d: d["operational"]["inventory_lots"][0].update(expires_at=None)
    )
    result = inspect(no_expiry)
    assert (
        result.status == "BASELINE_COMPLETE"
    )  # P2 baseline policy, not expiry optimization proof.
    assert result.expiry_strategy_available is False
    assert result.profit_strategy_available is False
    no_lots = changed(snapshot, lambda d: d["operational"].update(inventory_lots=()))
    assert inspect(no_lots).status in {"BASELINE_BLOCKED", "UNKNOWN"}


def test_pending_multiline_request_cannot_be_approximated_as_two_feasible_singles():
    snapshot, _ = fixture()
    result = inspect(snapshot, pending=("multi-line-request",))
    assert result.status == "PENDING_TARGET_UNSUPPORTED"
    assert result.allocation_authorized is False
