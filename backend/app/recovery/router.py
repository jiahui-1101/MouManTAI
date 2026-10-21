from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import RequestContext, get_request_context

from .models import (
    GenerateRecoveryRequest,
    PlanEvaluation,
    RecoveryCase,
    RecoveryPlanList,
    RecoveryPlanVersion,
)
from .service import default_recovery_planner


router = APIRouter(prefix="/v1/recovery", tags=["recovery"])
Context = Annotated[RequestContext, Depends(get_request_context)]


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
