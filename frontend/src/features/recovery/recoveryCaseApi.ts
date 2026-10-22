import { ApiError, apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import type { RecoveryCaseView } from "./recoveryCaseView";

export class SyntheticRecoveryCaseError extends Error {
  constructor() {
    super("Synthetic recovery records are not available in the live case route.");
    this.name = "SyntheticRecoveryCaseError";
  }
}

export async function getRecoveryCaseView(
  commitmentId: string,
  auth: RequestAuthHeaders,
): Promise<RecoveryCaseView> {
  const casePath = `/v1/recovery/cases/${encodeURIComponent(commitmentId)}`;
  let caseView: RecoveryCaseView;
  try {
    caseView = await apiRequest<RecoveryCaseView>(casePath, { headers: authHeaders(auth) });
  } catch (error) {
    const triggerHistoryAvailable = error instanceof ApiError && (
      error.code === "RECOVERY_EVALUATION_INPUTS_PENDING" || error.code === "RECOVERY_CASE_COMPLETED"
    );
    if (!triggerHistoryAvailable) throw error;
    caseView = await apiRequest<RecoveryCaseView>(`${casePath}/trigger`, { headers: authHeaders(auth) });
  }

  if (caseView.storage_mode !== "DURABLE_DATABASE") {
    throw new SyntheticRecoveryCaseError();
  }

  return caseView;
}
