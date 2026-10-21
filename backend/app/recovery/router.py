from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.dependencies import RequestContext as CoreRequestContext

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
    RecoveryPlanList,
    RecoveryPlanVersion,
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
    return default_recovery_planner.get_case(context.tenant_id, _canonical_commitment_id(commitment_id))


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
