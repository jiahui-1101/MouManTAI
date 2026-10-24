import { ApiError, apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import type {
  GenerateRecoveryRequest,
  ApprovalDecision,
  DurableActionView,
  PlanEvaluation,
  RecoveryCase,
  RecoveryPlanList,
  RecoveryPlanVersion,
  RecoveryTriggerCaseView,
} from "./types";

// The local isolated E2E proxy adds the server-owned mutation key. No secret is bundled.
const recoveryRequest = <T>(path: string, init?: RequestInit): Promise<T> =>
  apiRequest<T>(path, init, import.meta.env.DEV ? "" : undefined);

export function getRecoveryCase(commitmentId: string, auth: RequestAuthHeaders): Promise<RecoveryCase> {
  return recoveryRequest<RecoveryCase>(`/v1/recovery/cases/${commitmentId}`, { headers: authHeaders(auth) });
}

export async function getRecoveryCaseOrTrigger(
  commitmentId: string, auth: RequestAuthHeaders,
): Promise<RecoveryCase | RecoveryTriggerCaseView> {
  try {
    return await getRecoveryCase(commitmentId, auth);
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "RECOVERY_EVALUATION_INPUTS_PENDING") throw error;
    return recoveryRequest<RecoveryTriggerCaseView>(`/v1/recovery/cases/${commitmentId}/trigger`, {
      headers: authHeaders(auth),
    });
  }
}

export function generateRecoveryPlans(
  commitmentId: string,
  request: GenerateRecoveryRequest,
  auth: RequestAuthHeaders,
): Promise<RecoveryCase> {
  return recoveryRequest<RecoveryCase>(`/v1/recovery/cases/${commitmentId}/generate`, {
    method: "POST",
    headers: authHeaders(auth),
    body: JSON.stringify(request),
  });
}

export function getRecoveryPlans(commitmentId: string, auth: RequestAuthHeaders): Promise<RecoveryPlanList> {
  return recoveryRequest<RecoveryPlanList>(`/v1/recovery/cases/${commitmentId}/plans`, { headers: authHeaders(auth) });
}

export function getRecoveryPlan(planId: string, auth: RequestAuthHeaders): Promise<RecoveryPlanVersion> {
  return recoveryRequest<RecoveryPlanVersion>(`/v1/recovery/plans/${planId}`, { headers: authHeaders(auth) });
}

export function getPlanEvaluation(planId: string, auth: RequestAuthHeaders): Promise<PlanEvaluation> {
  return recoveryRequest<PlanEvaluation>(`/v1/recovery/plans/${planId}/evaluation`, { headers: authHeaders(auth) });
}

export function getApprovalHistory(planId: string, auth: RequestAuthHeaders): Promise<ApprovalDecision[]> {
  return recoveryRequest(`/v1/recovery/plans/${planId}/approvals`, { headers: authHeaders(auth) });
}

export function decideRecoveryPlan(
  plan: RecoveryPlanVersion, decision: "approve" | "reject" | "request-revision", reason: string,
  commitmentVersion: number, auth: RequestAuthHeaders,
): Promise<ApprovalDecision> {
  return recoveryRequest(`/v1/recovery/plans/${plan.plan_id}/${decision}`, {
    method: "POST", headers: authHeaders(auth),
    body: JSON.stringify({ expected_plan_version: plan.plan_version, expected_commitment_version: commitmentVersion,
      expected_snapshot_version: plan.snapshot_version, reason, idempotency_key: crypto.randomUUID(), evidence_refs: plan.evidence_refs }),
  });
}

export function executeRecoveryTask(
  plan: RecoveryPlanVersion,
  commitmentVersion: number,
  auth: RequestAuthHeaders,
  idempotencyKey?: string,
): Promise<DurableActionView> {
  return recoveryRequest(`/v1/recovery/plans/${plan.plan_id}/execute`, {
    method: "POST", headers: authHeaders(auth),
    body: JSON.stringify({ expected_plan_version: plan.plan_version, expected_commitment_version: commitmentVersion,
      expected_snapshot_version: plan.snapshot_version, idempotency_key: idempotencyKey ?? crypto.randomUUID() }),
  });
}

export function getActionHistory(planId: string, auth: RequestAuthHeaders): Promise<DurableActionView[]> {
  return recoveryRequest(`/v1/recovery/plans/${planId}/actions`, { headers: authHeaders(auth) });
}

export interface CommunicationHandoffView {
  proposal_id: string;
  proposal_version: number;
  source_event_id: string;
  commitment_version: number;
  status: string;
  p4_request_status: string;
  blocking_reasons: string[];
}

export async function requestRecoveryCommunication(plan: RecoveryPlanVersion, commitmentVersion: number,
  auth: RequestAuthHeaders): Promise<CommunicationHandoffView> {
  const handoff = await recoveryRequest<Omit<CommunicationHandoffView, "p4_request_status" | "blocking_reasons">>(
    `/v1/recovery/plans/${plan.plan_id}/request-communication`, {
    method: "POST", headers: authHeaders(auth),
    body: JSON.stringify({ expected_plan_version: plan.plan_version,
      expected_commitment_version: commitmentVersion, expected_snapshot_version: plan.snapshot_version }),
  });
  const request = await recoveryRequest<{ request_status: string; blocking_reasons: string[] }>(
    "/v1/communications/requests", {
      method: "POST", headers: authHeaders(auth),
      body: JSON.stringify({ source_event_id: handoff.source_event_id }),
    });
  return { ...handoff, p4_request_status: request.request_status, blocking_reasons: request.blocking_reasons };
}
