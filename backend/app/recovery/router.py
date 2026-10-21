from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.dependencies import RequestContext as CoreRequestContext
from app.core.errors import DomainError

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
)
from .service import default_recovery_planner

router = APIRouter(prefix="/v1/recovery", tags=["recovery"])
Context = Annotated[RequestContext, Depends(get_request_context)]
Db = Annotated[Session, Depends(get_db)]

# Fail closed until P5 supplies a server-authenticated actor-context provider.
approval_actor_provider: VerifiedActorContextProvider = UnverifiedP5ContextAdapter()


def get_approval_actor(context: Context) -> ActorContext:
    actor = approval_actor_provider.get_verified_context(context)
    require_verified_actor(actor)
    return actor


ApprovalActor = Annotated[ActorContext, Depends(get_approval_actor)]


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


def _canonical_commitment_id(commitment_id: str) -> str:
    return "com_001" if commitment_id == "demo" else commitment_id


@router.get("/cases/{commitment_id}", response_model=RecoveryCase)
def get_recovery_case(commitment_id: str, context: Context) -> RecoveryCase:
    case = default_recovery_planner.get_case(context.tenant_id, _canonical_commitment_id(commitment_id))
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
def get_trigger_only_recovery_case(commitment_id: str, context: Context) -> RecoveryTriggerCaseView:
    case = default_recovery_planner.get_case(context.tenant_id, _canonical_commitment_id(commitment_id))
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
) -> RecoveryCase:
    return default_recovery_planner.generate(
        context.tenant_id,
        _canonical_commitment_id(commitment_id),
        expected_commitment_version=request.expected_commitment_version,
        assessment_id=request.assessment_id,
        preferences=request.preferences,
        correlation_id=context.correlation_id,
        causation_id=request.causation_id or context.causation_id,
        request_context=context,
    )


@router.get("/cases/{commitment_id}/plans", response_model=RecoveryPlanList)
def list_recovery_plans(commitment_id: str, context: Context) -> RecoveryPlanList:
    return default_recovery_planner.list_plans(context.tenant_id, _canonical_commitment_id(commitment_id))


@router.get("/plans/{plan_id}/evaluation", response_model=PlanEvaluation)
def get_plan_evaluation(plan_id: str, context: Context) -> PlanEvaluation:
    return default_recovery_planner.get_plan(context.tenant_id, plan_id).evaluation


@router.get("/plans/{plan_id}", response_model=RecoveryPlanVersion)
def get_recovery_plan(plan_id: str, context: Context) -> RecoveryPlanVersion:
    return default_recovery_planner.get_plan(context.tenant_id, plan_id)


@router.post("/plans/{plan_id}/approval-requests", response_model=ApprovalDecision)
def request_plan_approval(plan_id: str, request: ApprovalRequestInput, actor: ApprovalActor,
                          db: Db) -> ApprovalDecision:
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
                          db: Db) -> ApprovalDecision:
    plan = default_recovery_planner.get_plan(actor.tenant_id, plan_id)
    current_version = _current_commitment_version(db, actor, plan.commitment_id)
    return default_recovery_planner.approve_plan(
        actor, plan_id, request, current_commitment_version=current_version
    )


@router.post("/plans/{plan_id}/reject", response_model=ApprovalDecision)
def reject_recovery_plan(plan_id: str, request: ApprovalDecisionInput, actor: ApprovalActor,
                         db: Db) -> ApprovalDecision:
    plan = default_recovery_planner.get_plan(actor.tenant_id, plan_id)
    current_version = _current_commitment_version(db, actor, plan.commitment_id)
    return default_recovery_planner.reject_plan(
        actor, plan_id, request, current_commitment_version=current_version
    )


@router.post("/plans/{plan_id}/request-revision", response_model=ApprovalDecision)
def request_recovery_plan_revision(plan_id: str, request: ApprovalDecisionInput, actor: ApprovalActor,
                                   db: Db) -> ApprovalDecision:
    plan = default_recovery_planner.get_plan(actor.tenant_id, plan_id)
    current_version = _current_commitment_version(db, actor, plan.commitment_id)
    return default_recovery_planner.request_plan_revision(
        actor, plan_id, request, current_commitment_version=current_version
    )
