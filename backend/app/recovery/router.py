from __future__ import annotations

from typing import Annotated
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.dependencies import RequestContext as CoreRequestContext
from app.core.errors import DomainError
from app.core.service import CommitmentService
from app.feasibility.api_dependencies import require_isolated_e2e_key

from .integrations import (
    ActorContext,
    P5CommitmentReader,
    UnverifiedP5ContextAdapter,
    VerifiedActorContextProvider,
    require_verified_actor,
)
from .models import (
    ApprovalDecision,
    ApprovalDecisionInput,
    ApprovalRequestInput,
    GenerateRecoveryRequest,
    PlanEvaluation,
    RecoveryCase,
    RecoveryCaseStatus,
    RecoveryPlanList,
    RecoveryPlanVersion,
    RecoveryTriggerCaseView,
    ExecuteRecoveryTaskRequest,
    DurableActionView,
)
from .service import default_recovery_planner, demo_recovery_planner
from .durable_plans import DurablePlanService
from .persistence import SqlAlchemyRecoveryRepository
from app.core.manager_approval import ManagerApprovalRecord, ManagerApprovalService, trusted_isolated_manager
from .durable_actions import DurableActionService, RecoveryActionExecutionRecord
from .durable_communication import (
    CommunicationHandoffView, DurableCommunicationHandoff, RequestCommunicationInput,
)

router = APIRouter(prefix="/v1/recovery", tags=["recovery"])
Context = Annotated[RequestContext, Depends(get_request_context)]
Db = Annotated[Session, Depends(get_db)]

# Fail closed until P5 supplies a server-authenticated actor-context provider.
approval_actor_provider: VerifiedActorContextProvider = UnverifiedP5ContextAdapter()


def get_approval_actor(
    context: Context, x_isolated_e2e_key: str | None = Header(default=None),
) -> ActorContext:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1":
        manager_id = trusted_isolated_manager(context, x_isolated_e2e_key)
        return ActorContext(
            context.tenant_id, manager_id, "MANAGER", context.correlation_id,
            context.causation_id, verified=True,
        )
    actor = approval_actor_provider.get_verified_context(context)
    require_verified_actor(actor)
    return actor


ApprovalActor = Annotated[ActorContext, Depends(get_approval_actor)]


def _stored_utc(value: datetime | None) -> datetime | None:
    # The service writes UTC; SQLite drops tzinfo when it reloads DateTime rows.
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _approval_response(row: ManagerApprovalRecord) -> ApprovalDecision:
    return ApprovalDecision(
        approval_id=row.approval_id, tenant_id=row.tenant_id,
        recovery_case_id=row.case_id, commitment_id=row.commitment_id,
        commitment_version=row.commitment_version,
        plan_id=row.plan_id, plan_version=row.plan_version,
        proposal_id=row.proposal_id, proposal_version=row.proposal_version,
        snapshot_id=row.snapshot_id, snapshot_version=row.snapshot_version,
        action_scope=row.action_scope, actor_id=row.actor_id, actor_role=row.actor_role,
        decision=row.decision, approved_cost_limit=row.approved_amount,
        reason=row.reason, decided_at=_stored_utc(row.decided_at),
        approved_at=_stored_utc(row.decided_at) if row.decision == "APPROVED" else None,
        expires_at=_stored_utc(row.expires_at), evidence_refs=[row.snapshot_id], audit_refs=[row.audit_id],
        idempotency_key=row.idempotency_key, persistence_mode="DURABLE_DATABASE",
    )


def _action_response(row: RecoveryActionExecutionRecord) -> DurableActionView:
    return DurableActionView.model_validate({
        "execution_id": row.execution_id, "tenant_id": row.tenant_id,
        "commitment_id": row.commitment_id, "plan_id": row.plan_id,
        "plan_version": row.plan_version, "approval_id": row.approval_id,
        "status": row.status, "attempts": row.attempts, "task_id": row.task_id,
        "receipt_ref": row.receipt_ref, "audit_id": row.audit_id,
        "last_error": row.last_error, "created_at": _stored_utc(row.created_at),
        "updated_at": _stored_utc(row.updated_at),
    })


def _isolated_decision(
    db: Session, actor: ActorContext, key: str | None, plan_id: str,
    request: ApprovalDecisionInput, decision: str,
) -> ApprovalDecision:
    context = CoreRequestContext(
        tenant_id=actor.tenant_id, actor_id=actor.actor_id, actor_role=actor.actor_role,
        correlation_id=actor.correlation_id, causation_id=actor.causation_id,
    )
    row = ManagerApprovalService().decide(
        db, context, key, plan_id, decision=decision,
        expected_plan_version=request.expected_plan_version,
        expected_commitment_version=request.expected_commitment_version,
        expected_snapshot_version=request.expected_snapshot_version,
        idempotency_key=request.idempotency_key or "", reason=request.reason,
    )
    return _approval_response(row)


def _current_commitment_version(db: Session, actor: ActorContext, commitment_id: str) -> int:
    context = CoreRequestContext(
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        actor_role=actor.actor_role,
        correlation_id=actor.correlation_id,
        causation_id=actor.causation_id,
    )
    commitment = P5CommitmentReader().get_commitment(db, context, commitment_id)
    return commitment.commitment_version


def _planner_for_commitment(commitment_id: str):
    # /demo has separate fixture storage; ordinary IDs never fall back to it.
    if commitment_id == "demo":
        return demo_recovery_planner, demo_recovery_planner.inputs.commitment.commitment_id
    return default_recovery_planner, commitment_id


def _planner_for_plan(tenant_id: str, plan_id: str):
    if default_recovery_planner.repository.get_plan(tenant_id, plan_id) is not None:
        return default_recovery_planner
    if demo_recovery_planner.repository.get_plan(tenant_id, plan_id) is not None:
        return demo_recovery_planner
    return default_recovery_planner


@router.get("/cases/{commitment_id}", response_model=RecoveryCase)
def get_recovery_case(commitment_id: str, context: Context, db: Db) -> RecoveryCase:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1" and commitment_id != "demo":
        case = SqlAlchemyRecoveryRepository().get_active_case(db, context.tenant_id, commitment_id)
        if case is None:
            raise DomainError("RECOVERY_CASE_NOT_FOUND", "Recovery case was not found", status_code=404)
        if case.trigger_assessment is None or case.operational_snapshot is None:
            raise DomainError(
                "RECOVERY_EVALUATION_INPUTS_PENDING", "Recovery planning inputs are pending",
                status_code=409,
                details={"recovery_case_id": case.case_id,
                         "trigger_case_path": f"/v1/recovery/cases/{commitment_id}/trigger"},
            )
        current = CommitmentService().get(db, context, commitment_id)
        return case.model_copy(update={"commitment": current,
                                       "commitment_version": current.commitment_version})
    planner, requested_id = _planner_for_commitment(commitment_id)
    case = planner.get_case(context.tenant_id, requested_id, db=db, request_context=context)
    if case.status == RecoveryCaseStatus.COMPLETED:
        raise DomainError(
            "RECOVERY_CASE_COMPLETED",
            "This recovery case is complete; its read-only trigger history is available from the trigger view",
            status_code=409,
            details={"recovery_case_id": case.case_id,
                     "trigger_case_path": f"/v1/recovery/cases/{commitment_id}/trigger"},
        )
    if case.trigger_assessment is None or case.operational_snapshot is None:
        raise DomainError(
            "RECOVERY_EVALUATION_INPUTS_PENDING",
            "The recovery case exists, but planning inputs are still pending; read the trigger-only case view",
            status_code=409,
            details={
                "recovery_case_id": case.case_id,
                "evaluation_readiness": "AWAITING_EVALUATION_INPUTS",
                "trigger_case_path": f"/v1/recovery/cases/{commitment_id}/trigger",
            },
        )
    return case


@router.get("/cases/{commitment_id}/trigger", response_model=RecoveryTriggerCaseView)
def get_trigger_only_recovery_case(commitment_id: str, context: Context, db: Db) -> RecoveryTriggerCaseView:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1" and commitment_id != "demo":
        case = SqlAlchemyRecoveryRepository().get_active_case(db, context.tenant_id, commitment_id)
        if case is None:
            raise DomainError("RECOVERY_CASE_NOT_FOUND", "Recovery case was not found", status_code=404)
        if case.trigger_assessment is not None and case.operational_snapshot is not None:
            raise DomainError("TRIGGER_ONLY_RECOVERY_CASE_NOT_FOUND", "Case has planning inputs", status_code=404)
        return RecoveryTriggerCaseView(
            case_id=case.case_id, tenant_id=case.tenant_id, commitment_id=case.commitment_id,
            case_version=case.case_version, commitment_version=case.commitment_version,
            status=case.status, evaluation_readiness="AWAITING_EVALUATION_INPUTS",
            missing_evaluation_inputs=["P2_FEASIBILITY_ASSESSMENT", "AUTHORITATIVE_OPERATIONAL_SNAPSHOT"],
            trigger_events=case.trigger_events, resolution_events=case.resolution_events,
            storage_mode=case.storage_mode, created_at=case.created_at, updated_at=case.updated_at,
        )
    planner, requested_id = _planner_for_commitment(commitment_id)
    case = planner.get_case(context.tenant_id, requested_id, db=db, request_context=context)
    if not case.trigger_events or (
        case.trigger_assessment is not None and case.operational_snapshot is not None
    ):
        raise DomainError(
            "TRIGGER_ONLY_RECOVERY_CASE_NOT_FOUND",
            "No trigger-only recovery case is available for this commitment",
            status_code=404,
        )
    missing_inputs = []
    if case.status != RecoveryCaseStatus.COMPLETED and case.trigger_assessment is None:
        missing_inputs.append("P2_FEASIBILITY_ASSESSMENT")
    if case.status != RecoveryCaseStatus.COMPLETED and case.operational_snapshot is None:
        missing_inputs.append("AUTHORITATIVE_OPERATIONAL_SNAPSHOT")
    return RecoveryTriggerCaseView(
        case_id=case.case_id,
        tenant_id=case.tenant_id,
        commitment_id=case.commitment_id,
        case_version=case.case_version,
        commitment_version=case.commitment_version,
        status=case.status,
        evaluation_readiness=(
            "CASE_COMPLETED" if case.status == RecoveryCaseStatus.COMPLETED else "AWAITING_EVALUATION_INPUTS"
        ),
        missing_evaluation_inputs=missing_inputs,
        trigger_events=case.trigger_events,
        resolution_events=case.resolution_events,
        storage_mode=case.storage_mode,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


@router.post("/cases/{commitment_id}/generate", response_model=RecoveryCase)
def generate_recovery_plans(
    commitment_id: str,
    request: GenerateRecoveryRequest,
    context: Context,
    db: Db,
    x_isolated_e2e_key: str | None = Header(default=None),
) -> RecoveryCase:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1" and commitment_id != "demo":
        require_isolated_e2e_key(x_isolated_e2e_key)
        DurablePlanService().generate(
            db, context, commitment_id,
            expected_commitment_version=request.expected_commitment_version,
            assessment_id=request.assessment_id, preferences=request.preferences,
        )
        return get_recovery_case(commitment_id, context, db)
    planner, requested_id = _planner_for_commitment(commitment_id)
    return planner.generate(
        context.tenant_id,
        requested_id,
        expected_commitment_version=request.expected_commitment_version,
        assessment_id=request.assessment_id,
        preferences=request.preferences,
        correlation_id=context.correlation_id,
        causation_id=request.causation_id or context.causation_id,
        request_context=context,
        db=db,
    )


@router.get("/cases/{commitment_id}/plans", response_model=RecoveryPlanList)
def list_recovery_plans(commitment_id: str, context: Context, db: Db) -> RecoveryPlanList:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1" and commitment_id != "demo":
        case = get_recovery_case(commitment_id, context, db)
        return RecoveryPlanList(
            tenant_id=context.tenant_id, commitment_id=commitment_id,
            case_id=case.case_id, plans=DurablePlanService().list(db, context, commitment_id),
        )
    planner, requested_id = _planner_for_commitment(commitment_id)
    return planner.list_plans(context.tenant_id, requested_id, db=db, request_context=context)


@router.get("/plans/{plan_id}/evaluation", response_model=PlanEvaluation)
def get_plan_evaluation(plan_id: str, context: Context, db: Db) -> PlanEvaluation:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1":
        return DurablePlanService().get_plan(db, context, plan_id).evaluation
    return _planner_for_plan(context.tenant_id, plan_id).get_plan(
        context.tenant_id, plan_id, db=db, request_context=context
    ).evaluation


@router.get("/plans/{plan_id}", response_model=RecoveryPlanVersion)
def get_recovery_plan(plan_id: str, context: Context, db: Db) -> RecoveryPlanVersion:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1":
        return DurablePlanService().get_plan(db, context, plan_id)
    return _planner_for_plan(context.tenant_id, plan_id).get_plan(
        context.tenant_id, plan_id, db=db, request_context=context
    )


@router.post("/plans/{plan_id}/approval-requests", response_model=ApprovalDecision)
def request_plan_approval(plan_id: str, request: ApprovalRequestInput, actor: ApprovalActor,
                          db: Db) -> ApprovalDecision:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1":
        raise DomainError(
            "DURABLE_APPROVAL_REQUEST_UNAVAILABLE",
            "Use a direct durable Manager decision for the exact isolated plan version",
            status_code=503,
        )
    plan = default_recovery_planner.get_plan(actor.tenant_id, plan_id)
    current_version = _current_commitment_version(db, actor, plan.commitment_id)
    return default_recovery_planner.request_approval(
        actor, plan_id, request, current_commitment_version=current_version,
        db=db,
        request_context=CoreRequestContext(
            tenant_id=actor.tenant_id, actor_id=actor.actor_id, actor_role=actor.actor_role,
            correlation_id=actor.correlation_id, causation_id=actor.causation_id,
        ),
    )


@router.post("/plans/{plan_id}/approve", response_model=ApprovalDecision)
def approve_recovery_plan(plan_id: str, request: ApprovalDecisionInput, actor: ApprovalActor,
                          db: Db, x_isolated_e2e_key: str | None = Header(default=None)) -> ApprovalDecision:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1":
        return _isolated_decision(db, actor, x_isolated_e2e_key, plan_id, request, "APPROVED")
    plan = default_recovery_planner.get_plan(actor.tenant_id, plan_id)
    current_version = _current_commitment_version(db, actor, plan.commitment_id)
    return default_recovery_planner.approve_plan(
        actor, plan_id, request, current_commitment_version=current_version
    )


@router.post("/plans/{plan_id}/reject", response_model=ApprovalDecision)
def reject_recovery_plan(plan_id: str, request: ApprovalDecisionInput, actor: ApprovalActor,
                         db: Db, x_isolated_e2e_key: str | None = Header(default=None)) -> ApprovalDecision:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1":
        return _isolated_decision(db, actor, x_isolated_e2e_key, plan_id, request, "REJECTED")
    plan = default_recovery_planner.get_plan(actor.tenant_id, plan_id)
    current_version = _current_commitment_version(db, actor, plan.commitment_id)
    return default_recovery_planner.reject_plan(
        actor, plan_id, request, current_commitment_version=current_version
    )


@router.post("/plans/{plan_id}/request-revision", response_model=ApprovalDecision)
def request_recovery_plan_revision(plan_id: str, request: ApprovalDecisionInput, actor: ApprovalActor,
                                   db: Db, x_isolated_e2e_key: str | None = Header(default=None)) -> ApprovalDecision:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1":
        return _isolated_decision(db, actor, x_isolated_e2e_key, plan_id, request, "REVISION_REQUESTED")
    plan = default_recovery_planner.get_plan(actor.tenant_id, plan_id)
    current_version = _current_commitment_version(db, actor, plan.commitment_id)
    return default_recovery_planner.request_plan_revision(
        actor, plan_id, request, current_commitment_version=current_version
    )


@router.post("/plans/{plan_id}/revoke", response_model=ApprovalDecision)
def revoke_recovery_plan_approval(
    plan_id: str, request: ApprovalDecisionInput, actor: ApprovalActor, db: Db,
    x_isolated_e2e_key: str | None = Header(default=None),
) -> ApprovalDecision:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        raise DomainError("APPROVAL_AUTHORITY_UNAVAILABLE", "Durable approval authority is unavailable", status_code=503)
    return _isolated_decision(db, actor, x_isolated_e2e_key, plan_id, request, "REVOKED")


@router.get("/plans/{plan_id}/approvals", response_model=list[ApprovalDecision])
def get_recovery_plan_approval_history(plan_id: str, actor: ApprovalActor, db: Db) -> list[ApprovalDecision]:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        raise DomainError("APPROVAL_AUTHORITY_UNAVAILABLE", "Durable approval history is unavailable", status_code=503)
    context = CoreRequestContext(
        tenant_id=actor.tenant_id, actor_id=actor.actor_id, actor_role=actor.actor_role,
        correlation_id=actor.correlation_id, causation_id=actor.causation_id,
    )
    return [_approval_response(row) for row in ManagerApprovalService().history(db, context, plan_id)]


@router.post("/plans/{plan_id}/execute", response_model=DurableActionView)
def execute_recovery_internal_task(
    plan_id: str, request: ExecuteRecoveryTaskRequest, actor: ApprovalActor, db: Db,
    x_isolated_e2e_key: str | None = Header(default=None),
) -> DurableActionView:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        raise DomainError("ACTION_AUTHORITY_UNAVAILABLE", "Synthetic action authority is unavailable", status_code=503)
    context = CoreRequestContext(
        tenant_id=actor.tenant_id, actor_id=actor.actor_id, actor_role=actor.actor_role,
        correlation_id=actor.correlation_id, causation_id=actor.causation_id,
    )
    row = DurableActionService().execute(
        db, context, x_isolated_e2e_key, plan_id,
        expected_plan_version=request.expected_plan_version,
        expected_commitment_version=request.expected_commitment_version,
        expected_snapshot_version=request.expected_snapshot_version,
        idempotency_key=request.idempotency_key,
    )
    return _action_response(row)


@router.get("/plans/{plan_id}/actions", response_model=list[DurableActionView])
def get_recovery_action_history(plan_id: str, actor: ApprovalActor, db: Db) -> list[DurableActionView]:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        raise DomainError("ACTION_AUTHORITY_UNAVAILABLE", "Synthetic action history is unavailable", status_code=503)
    context = CoreRequestContext(
        tenant_id=actor.tenant_id, actor_id=actor.actor_id, actor_role=actor.actor_role,
        correlation_id=actor.correlation_id, causation_id=actor.causation_id,
    )
    return [_action_response(row) for row in DurableActionService().history(db, context, plan_id)]


@router.post("/plans/{plan_id}/request-communication", response_model=CommunicationHandoffView)
def request_recovery_communication(
    plan_id: str, request: RequestCommunicationInput, actor: ApprovalActor, db: Db,
    x_isolated_e2e_key: str | None = Header(default=None),
) -> CommunicationHandoffView:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        raise DomainError("COMMUNICATION_AUTHORITY_UNAVAILABLE", "Proposal handoff authority is unavailable", status_code=503)
    context = CoreRequestContext(
        tenant_id=actor.tenant_id, actor_id=actor.actor_id, actor_role=actor.actor_role,
        correlation_id=actor.correlation_id, causation_id=actor.causation_id,
    )
    return DurableCommunicationHandoff().request(db, context, x_isolated_e2e_key, plan_id, request)
