from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.schemas import ApprovalState
from app.recovery.integrations import ActorContext
from app.recovery.models import (
    ApprovalDecisionInput,
    ApprovalDecisionState,
    ApprovalRequestInput,
    ValidationSource,
)
from app.recovery.router import get_approval_actor
from app.recovery.service import RecoveryPlanner, RecoveryRepository


def setup_plan():
    planner = RecoveryPlanner(repository=RecoveryRepository())
    inputs = planner.inputs
    case = planner.generate(
        inputs.commitment.tenant_id,
        inputs.commitment.commitment_id,
        expected_commitment_version=inputs.commitment.commitment_version,
    )
    return planner, case, case.plans[0]


def actor(role="MANAGER", actor_id="user_manager_01", *, verified=True):
    return ActorContext("tenant_demo_01", actor_id, role, "corr-approval-1", "cause-1", verified)


def request_for(plan, *, key="approval-key-1", expiry=None, max_amount=None, scope=None, **changes):
    data = {
        "expected_commitment_version": plan.evaluation.commitment_version,
        "expected_plan_version": plan.plan_version,
        "expected_snapshot_version": plan.snapshot_version,
        "action_scope": scope if scope is not None else sorted({a.type for a in plan.actions}),
        "maximum_approved_amount": max_amount if max_amount is not None else plan.estimated_extra_cost,
        "reason": "Request review for this recovery plan",
        "expires_at": expiry or (datetime.now(UTC) + timedelta(hours=1)),
        "idempotency_key": key,
        "evidence_refs": ["ev_approval_request_001"],
    }
    data.update(changes)
    return ApprovalRequestInput.model_validate(data)


def decision_for(plan):
    return ApprovalDecisionInput(
        expected_commitment_version=plan.evaluation.commitment_version,
        expected_plan_version=plan.plan_version,
        expected_snapshot_version=plan.snapshot_version,
        reason="Reviewed and decided by manager",
        evidence_refs=["ev_approval_decision_001"],
    )


def test_expired_approved_record_is_invalidated_when_checked_for_use():
    planner, case, plan = setup_plan()
    plan.evaluation.validation_source = ValidationSource.REAL_P2_VALIDATED
    planner.repository.save_case(case)
    planner.request_approval(actor(), plan.plan_id, request_for(plan))
    planner.approve_plan(actor(), plan.plan_id, decision_for(plan))
    stored = planner.get_case(case.tenant_id, case.commitment_id)
    for index, record in enumerate(stored.approval_decisions):
        if record.decision == ApprovalDecisionState.APPROVED:
            stored.approval_decisions[index] = record.model_copy(
                update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            )
    planner.repository.save_case(stored)
    with pytest.raises(DomainError, match="Approval has expired"):
        planner.get_active_approval(actor(), plan.plan_id, decision_for(plan))
    refreshed = planner.get_case(case.tenant_id, case.commitment_id)
    assert refreshed.plans[0].approval_state == ApprovalState.EXPIRED
    assert refreshed.approval_decisions[-1].decision == ApprovalDecisionState.EXPIRED


def test_expired_approval_request_is_rejected_and_recorded():
    planner, case, plan = setup_plan()
    planner.request_approval(actor(), plan.plan_id, request_for(plan))
    stored = planner.get_case(case.tenant_id, case.commitment_id)
    for index, record in enumerate(stored.approval_decisions):
        if record.decision == ApprovalDecisionState.REQUESTED:
            stored.approval_decisions[index] = record.model_copy(
                update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            )
    planner.repository.save_case(stored)
    with pytest.raises(DomainError, match="Approval request has expired"):
        planner.approve_plan(actor(), plan.plan_id, decision_for(plan))
    assert planner.get_case(case.tenant_id, case.commitment_id).approval_decisions[-1].decision == ApprovalDecisionState.EXPIRED


def test_approval_request_is_version_bound_and_idempotent():
    planner, case, plan = setup_plan()
    request = request_for(plan)
    first = planner.request_approval(actor(), plan.plan_id, request)
    second = planner.request_approval(actor(), plan.plan_id, request)
    assert first == second
    updated = planner.get_case(case.tenant_id, case.commitment_id)
    assert len([d for d in updated.approval_decisions if d.idempotency_key == request.idempotency_key]) == 1
    assert first.recovery_case_id == case.case_id
    assert first.commitment_version == case.commitment_version
    assert first.action_scope == sorted({a.type for a in plan.actions})
    assert first.decision == ApprovalDecisionState.REQUESTED
    assert plan.execution_state == "NOT_STARTED"


def test_staff_cannot_approve_and_test_double_cannot_authorize_plan():
    planner, _, plan = setup_plan()
    planner.request_approval(actor(), plan.plan_id, request_for(plan))
    with pytest.raises(DomainError, match="not authorized to execute consequential action"):
        planner.approve_plan(actor("STAFF", "user_staff_01"), plan.plan_id, decision_for(plan))
    with pytest.raises(DomainError, match="Synthetic feasibility"):
        planner.approve_plan(actor(), plan.plan_id, decision_for(plan))
    assert planner.get_plan("tenant_demo_01", plan.plan_id).approval_state == ApprovalState.PENDING


def test_authoritative_approval_does_not_execute_plan_and_is_immutable():
    planner, case, plan = setup_plan()
    plan.evaluation.validation_source = ValidationSource.REAL_P2_VALIDATED
    planner.repository.save_case(case)
    approval_request = request_for(plan)
    requested = planner.request_approval(actor(), plan.plan_id, approval_request)
    approved = planner.approve_plan(actor(), plan.plan_id, decision_for(plan))
    assert planner.request_approval(actor(), plan.plan_id, approval_request) == requested
    current = planner.get_plan("tenant_demo_01", plan.plan_id)
    assert approved.decision == ApprovalDecisionState.APPROVED
    assert approved.approved_at is not None
    assert approved.actor_id == "user_manager_01"
    assert approved.approved_cost_limit == plan.estimated_extra_cost
    assert approved.evidence_refs == ["ev_approval_decision_001"]
    assert approved.audit_refs
    assert approved.persistence_mode == "IN_MEMORY_NON_DURABLE"
    assert current.approval_state == ApprovalState.APPROVED
    assert current.execution_state == "NOT_STARTED"
    with pytest.raises(ValidationError):
        approved.reason = "mutated"


def test_stale_versions_scope_cost_and_expired_request_are_rejected():
    planner, _, plan = setup_plan()
    with pytest.raises(DomainError, match="version is stale"):
        planner.request_approval(actor(), plan.plan_id,
                                 request_for(plan, expected_commitment_version=plan.evaluation.commitment_version + 1))
    with pytest.raises(DomainError, match="version is stale"):
        planner.request_approval(actor(), plan.plan_id, request_for(plan, key="stale-current"),
                                 current_commitment_version=plan.evaluation.commitment_version + 1)
    with pytest.raises(DomainError, match="plan version is stale"):
        planner.request_approval(actor(), plan.plan_id,
                                 request_for(plan, key="stale-plan", expected_plan_version=plan.plan_version + 1))
    with pytest.raises(DomainError, match="exactly cover"):
        planner.request_approval(actor(), plan.plan_id, request_for(plan, scope=["UNRELATED_ACTION"]))
    with pytest.raises(DomainError, match="below plan cost"):
        planner.request_approval(actor(), plan.plan_id,
                                 request_for(plan, max_amount=Decimal(0), key="low-cost"))
    with pytest.raises(DomainError, match="expiry must be in the future"):
        planner.request_approval(actor(), plan.plan_id,
                                 request_for(plan, key="expired", expiry=datetime.now(UTC) - timedelta(seconds=1)))


@pytest.mark.parametrize("violation", ["cost", "scope"])
def test_approved_plan_is_rechecked_for_cost_and_action_scope(violation):
    planner, case, plan = setup_plan()
    plan.evaluation.validation_source = ValidationSource.REAL_P2_VALIDATED
    planner.repository.save_case(case)
    planner.request_approval(actor(), plan.plan_id, request_for(plan))
    planner.approve_plan(actor(), plan.plan_id, decision_for(plan))
    current = planner.get_case(case.tenant_id, case.commitment_id)
    current_plan = current.plans[0]
    if violation == "cost":
        current_plan.estimated_extra_cost += Decimal("1.00")
    else:
        current_plan.actions[0].type = "UNAPPROVED_ACTION"
    planner.repository.save_case(current)
    expected_error = "cost exceeds" if violation == "cost" else "scope does not match"
    with pytest.raises(DomainError, match=expected_error):
        planner.get_active_approval(actor(), plan.plan_id, decision_for(current_plan))


@pytest.mark.parametrize("decision", ["reject", "revision"])
def test_rejection_and_revision_are_audited_without_execution(decision):
    planner, case, plan = setup_plan()
    planner.request_approval(actor(), plan.plan_id, request_for(plan))
    if decision == "reject":
        record = planner.reject_plan(actor(), plan.plan_id, decision_for(plan))
        assert record.decision == ApprovalDecisionState.REJECTED
        assert planner.get_plan(case.tenant_id, plan.plan_id).approval_state == ApprovalState.REJECTED
    else:
        record = planner.request_plan_revision(actor(), plan.plan_id, decision_for(plan))
        assert record.decision == ApprovalDecisionState.REVISION_REQUESTED
        refreshed = planner.get_case(case.tenant_id, case.commitment_id)
        assert refreshed.status.value == "NEEDS_REPLAN"
        assert refreshed.plans[0].approval_state == ApprovalState.INVALIDATED
    assert record.audit_refs
    assert planner.get_plan(case.tenant_id, plan.plan_id).execution_state == "NOT_STARTED"


def test_client_cannot_supply_role_or_approval_truth():
    with pytest.raises(ValidationError):
        ApprovalDecisionInput.model_validate({
            "expected_commitment_version": 3,
            "expected_plan_version": 1,
            "expected_snapshot_version": 7,
            "reason": "approve",
            "actor_role": "OWNER",
            "approved": True,
        })


def test_material_replan_versions_plan_and_appends_invalidation():
    planner, case, plan = setup_plan()
    plan.evaluation.validation_source = ValidationSource.REAL_P2_VALIDATED
    planner.repository.save_case(case)
    planner.request_approval(actor(), plan.plan_id, request_for(plan))
    planner.approve_plan(actor(), plan.plan_id, decision_for(plan))
    updated_assessment = planner.inputs.assessment.model_copy(update={"assessment_id": "fev_new_002"})
    planner.inputs = replace(planner.inputs, assessment=updated_assessment)
    revised = planner.generate(
        case.tenant_id,
        case.commitment_id,
        expected_commitment_version=case.commitment_version,
        assessment_id="fev_new_002",
    )
    current_plan = next(p for p in revised.plans if p.plan_id == plan.plan_id)
    assert current_plan.plan_version == plan.plan_version + 1
    assert current_plan.evaluation.plan_version == current_plan.plan_version
    assert any(d.decision == ApprovalDecisionState.INVALIDATED for d in revised.approval_decisions)
    assert current_plan.approval_state == ApprovalState.PENDING
    assert current_plan.execution_state == "NOT_STARTED"


def test_other_tenant_cannot_read_or_approve_tenant_plan():
    planner, _, plan = setup_plan()
    with pytest.raises(DomainError, match="not found"):
        planner.request_approval(
            ActorContext("tenant_other", "user_manager_01", "MANAGER", "corr-other", None, True),
            plan.plan_id,
            request_for(plan),
        )


def test_unverified_p5_header_context_fails_closed_for_api_approval():
    with pytest.raises(DomainError, match="verified P5 actor"):
        get_approval_actor(RequestContext("tenant_demo", "user_manager_01", "MANAGER", "corr-1"))
