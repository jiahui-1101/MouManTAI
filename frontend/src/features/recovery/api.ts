import { ApiError, apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import type {
  GenerateRecoveryRequest,
  PlanEvaluation,
  RecoveryCase,
  RecoveryPlanList,
  RecoveryPlanVersion,
  RecoveryTriggerCaseView,
} from "./types";

export function getRecoveryCase(commitmentId: string, auth: RequestAuthHeaders): Promise<RecoveryCase> {
  return apiRequest<RecoveryCase>(`/v1/recovery/cases/${commitmentId}`, { headers: authHeaders(auth) });
}

export async function getRecoveryCaseOrTrigger(
  commitmentId: string, auth: RequestAuthHeaders,
): Promise<RecoveryCase | RecoveryTriggerCaseView> {
  try {
    return await getRecoveryCase(commitmentId, auth);
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "RECOVERY_EVALUATION_INPUTS_PENDING") throw error;
    return apiRequest<RecoveryTriggerCaseView>(`/v1/recovery/cases/${commitmentId}/trigger`, {
      headers: authHeaders(auth),
    });
  }
}

export function generateRecoveryPlans(
  commitmentId: string,
  request: GenerateRecoveryRequest,
  auth: RequestAuthHeaders,
): Promise<RecoveryCase> {
  return apiRequest<RecoveryCase>(`/v1/recovery/cases/${commitmentId}/generate`, {
    method: "POST",
    headers: authHeaders(auth),
    body: JSON.stringify(request),
  });
}

export function getRecoveryPlans(commitmentId: string, auth: RequestAuthHeaders): Promise<RecoveryPlanList> {
  return apiRequest<RecoveryPlanList>(`/v1/recovery/cases/${commitmentId}/plans`, { headers: authHeaders(auth) });
}

export function getRecoveryPlan(planId: string, auth: RequestAuthHeaders): Promise<RecoveryPlanVersion> {
  return apiRequest<RecoveryPlanVersion>(`/v1/recovery/plans/${planId}`, { headers: authHeaders(auth) });
}

export function getPlanEvaluation(planId: string, auth: RequestAuthHeaders): Promise<PlanEvaluation> {
  return apiRequest<PlanEvaluation>(`/v1/recovery/plans/${planId}/evaluation`, { headers: authHeaders(auth) });
}
