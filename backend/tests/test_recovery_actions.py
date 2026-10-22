from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.errors import DomainError
from app.core.schemas import PlannedAction
from app.recovery.actions import (
    ActionStatus,
    FailureMode,
    ProductionTaskParameters,
    PurchaseRequestParameters,
    RecoveryActionType,
    SyntheticActionAdapter,
    SyntheticActionCommand,
)
from app.recovery.integrations import ActorContext
from app.recovery.models import ApprovalDecisionInput, ApprovalRequestInput, ValidationSource
from app.recovery.service import RecoveryPlanner, RecoveryRepository


def setup_adapter(action_type=RecoveryActionType.CREATE_PURCHASE_REQUEST, parameters=None):
    parameters = parameters or {
        "action_type": action_type,
        "resource_id": "PACKAGING",
        "supplier_id": "SUPPLIER_1",
        "quantity": "2.5",
        "unit": "box",
        "estimated_cost_myr": "10.05",
    }
    planner = RecoveryPlanner(repository=RecoveryRepository())
    inputs = planner.inputs
    case = planner.generate(
        inputs.commitment.tenant_id, inputs.commitment.commitment_id,
        expected_commitment_version=inputs.commitment.commitment_version,
    )
    plan = case.plans[0]
    plan.evaluation.validation_source = ValidationSource.REAL_P2_VALIDATED
    plan.actions = [PlannedAction(
        action_id="act_1", type=action_type.value, requires_approval=True,
        idempotency_key="idem_1", parameters=parameters,
    )]
    planner.repository.save_case(case)
    actor = ActorContext(case.tenant_id, "manager_1", "MANAGER", "corr_1", None, True)
    request = ApprovalRequestInput(
        expected_commitment_version=plan.evaluation.commitment_version,
        expected_plan_version=plan.plan_version,
        expected_snapshot_version=plan.snapshot_version,
        action_scope=[action_type.value], maximum_approved_amount=Decimal("80.00"),
        reason="Synthetic adapter test approval", expires_at=datetime.now(UTC) + timedelta(hours=1),
        idempotency_key="approval_1",
    )
    planner.request_approval(actor, plan.plan_id, request)
    check = ApprovalDecisionInput(
        expected_commitment_version=plan.evaluation.commitment_version,
        expected_plan_version=plan.plan_version,
        expected_snapshot_version=plan.snapshot_version,
        reason="Approved for isolated adapter test",
    )
    planner.approve_plan(actor, plan.plan_id, check)
    command = SyntheticActionCommand(
        action_id="act_1", tenant_id=plan.tenant_id, commitment_id=plan.commitment_id,
        plan_id=plan.plan_id, plan_version=plan.plan_version, action_type=action_type,
        parameters=parameters, idempotency_key="action_key_1", evidence_refs=("ev_plan_1",),
    )
    return planner, case, plan, actor, check, command, SyntheticActionAdapter(planner)


def test_allowlisted_purchase_request_creates_and_reads_back_synthetic_record():
    planner, _, plan, actor, check, command, adapter = setup_adapter()
    result = adapter.execute(actor, command, check)
    assert result.status == ActionStatus.SUCCEEDED
    record = adapter.repository.get_record(command.tenant_id, result.operation_ref)
    assert record is not None
    assert record.parameters.estimated_cost_myr == Decimal("10.05")
    assert result.evidence_refs[-1] == f"synthetic_record:{result.operation_ref}"
    assert planner.get_plan(command.tenant_id, plan.plan_id).execution_state == "NOT_STARTED"


@pytest.mark.parametrize(
    ("action_type", "params"),
    [
        (RecoveryActionType.CREATE_PRODUCTION_TASK, {
            "action_type": RecoveryActionType.CREATE_PRODUCTION_TASK,
            "resource_id": "SKU_1", "quantity": "4", "unit": "pcs",
            "due_at": "2026-10-22T10:00:00Z",
        }),
        (RecoveryActionType.CREATE_FOLLOWUP_TASK, {
            "action_type": RecoveryActionType.CREATE_FOLLOWUP_TASK,
            "task_code": "CHECK_SUPPLIER", "owner_team": "OPS",
            "due_at": "2026-10-22T10:00:00Z",
        }),
    ],
)
def test_remaining_allowlisted_actions_create_records(action_type, params):
    _, _, _, actor, check, command, adapter = setup_adapter(action_type, params)
    assert adapter.execute(actor, command, check).status == ActionStatus.SUCCEEDED


def test_unknown_or_unsafe_action_parameters_are_rejected():
    with pytest.raises(ValidationError):
        SyntheticActionCommand(
            action_id="act_1", tenant_id="tenant_1", commitment_id="com_1", plan_id="plan_1",
            plan_version=1, action_type="DELETE_PAYMENT", parameters={}, idempotency_key="key_1",
        )
    with pytest.raises(ValidationError):
        PurchaseRequestParameters(
            resource_id="R1", supplier_id="S1", quantity=1, unit="box",
            estimated_cost_myr=Decimal("1.00"), approved=True,
        )
    with pytest.raises(ValidationError):
        PurchaseRequestParameters(
            resource_id="R1", supplier_id="S1", quantity=Decimal("-0.1"), unit="box",
            estimated_cost_myr=Decimal("1.00"),
        )
    with pytest.raises(ValidationError):
        ProductionTaskParameters(
            resource_id="SKU_1", quantity="1", unit="pcs", due_at="2026-10-22T10:00:00",
        )


def test_duplicate_execution_is_idempotent_and_key_reuse_is_rejected():
    _, _, _, actor, check, command, adapter = setup_adapter()
    first = adapter.execute(actor, command, check)
    second = adapter.execute(actor, command, check)
    assert first == second
    assert len(adapter.repository._records) == 1
    changed = command.model_copy(update={"action_id": "act_other"})
    with pytest.raises(DomainError, match="Idempotency key"):
        adapter.execute(actor, changed, check)


def test_failure_and_ambiguous_timeout_require_readback_reconciliation():
    _, _, _, actor, check, command, adapter = setup_adapter()
    failed = adapter.execute(actor, command, check, failure_mode=FailureMode.BEFORE_WRITE)
    assert failed.status == ActionStatus.FAILED
    assert adapter.repository._records == {}
    ambiguous = adapter.execute(actor, command, check, failure_mode=FailureMode.TIMEOUT_AFTER_WRITE)
    assert ambiguous.status == ActionStatus.NEEDS_RECONCILIATION
    assert adapter.repository.get_record(command.tenant_id, ambiguous.operation_ref) is not None
    reconciled = adapter.reconcile(command.tenant_id, command.idempotency_key)
    assert reconciled.status == ActionStatus.SUCCEEDED
    assert len(adapter.repository._records) == 1
    assert len(reconciled.attempts) == 3


def test_unverified_or_wrong_tenant_actor_cannot_execute():
    _, _, _, actor, check, command, adapter = setup_adapter()
    with pytest.raises(DomainError, match="verified P5 actor context"):
        adapter.execute(replace(actor, verified=False), command, check)
    with pytest.raises(DomainError, match="outside the verified tenant"):
        adapter.execute(replace(actor, tenant_id="tenant_other"), command, check)
    with pytest.raises(DomainError, match="verified owner or manager"):
        adapter.execute(replace(actor, actor_role="STAFF"), command, check)


def test_default_test_double_plan_cannot_be_authorized_by_adapter():
    planner, case, plan, actor, check, command, adapter = setup_adapter()
    plan.evaluation.validation_source = ValidationSource.TEST_DOUBLE_VALIDATED
    case.plans = [plan]
    planner.repository.save_case(case)
    with pytest.raises(DomainError, match="Synthetic P2 results"):
        adapter.execute(actor, command, check)

from dataclasses import replace
