import { ApiError, apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import type { CommunicationRequestView, DraftReference, MessageDraftView, PrepareDraftRequest } from "./types";

const base = "/v1/communications";
export const communicationKeys = {
  scope: (auth: RequestAuthHeaders) => ["p4-communications", auth.tenantId, auth.actorId] as const,
  list: (auth: RequestAuthHeaders) => [...communicationKeys.scope(auth), "list"] as const,
  detail: (auth: RequestAuthHeaders, id: string) => [...communicationKeys.scope(auth), "detail", id] as const,
  draft: (auth: RequestAuthHeaders, id: string, draftId: string) =>
    [...communicationKeys.scope(auth), "draft", id, draftId] as const,
};
const pathId = (value: string) => encodeURIComponent(value);
const mismatch = () => new ApiError(409, "RESPONSE_SCOPE_MISMATCH", "Response does not match requested scope");

function scopedRequest(value: CommunicationRequestView, auth: RequestAuthHeaders, id?: string) {
  if (!value?.reference || value.reference.tenant_id !== auth.tenantId ||
      !value.communication_id || (id !== undefined && value.communication_id !== id)) throw mismatch();
  if (!["BLOCKED", "READY_FOR_DRAFTING"].includes(value.request_status)) {
    throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Unsupported request response");
  }
  // Today's intake contract has no sending/confirmation result. Do not silently
  // accept a changed response contract as proof that a message was sent.
  if (value.message_status !== "DRAFT" ||
      [value.reference.commitment_id, value.reference.proposal_id, value.reference.plan_id].some(id => typeof id !== "string" || !id.trim()) ||
      [value.reference.commitment_version, value.reference.proposal_version, value.reference.plan_version].some(version => !Number.isInteger(version) || version < 1)) {
    throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Unsupported request response");
  }
  return value;
}

export async function listCommunications(auth: RequestAuthHeaders, signal?: AbortSignal) {
  const values = await apiRequest<CommunicationRequestView[]>(base, { headers: authHeaders(auth), signal });
  if (!Array.isArray(values)) throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Expected request list");
  return values.map(value => scopedRequest(value, auth));
}

export async function getCommunication(id: string, auth: RequestAuthHeaders, signal?: AbortSignal) {
  return scopedRequest(await apiRequest<CommunicationRequestView>(`${base}/${pathId(id)}`,
    { headers: authHeaders(auth), signal }), auth, id);
}

function scopedDraft(value: MessageDraftView, request: CommunicationRequestView, draftId?: string) {
  const fields: (keyof DraftReference)[] = ["tenant_id", "commitment_id", "commitment_version",
    "proposal_id", "proposal_version", "plan_id", "plan_version", "source_event_id", "correlation_id"];
  if (!value?.reference || value.tenant_id !== request.reference.tenant_id ||
      value.communication_id !== request.communication_id || !value.draft_id ||
      (draftId !== undefined && value.draft_id !== draftId) ||
      fields.some(key => value.reference[key] !== request.reference[key])) throw mismatch();
  if (value.status !== "DRAFT" || value.send_authorized !== false || typeof value.body !== "string" ||
      !["en", "ms", "zh"].includes(value.language) || !Number.isFinite(Date.parse(value.expires_at))) {
    throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Unsupported draft response");
  }
  return value;
}

export async function prepareDraft(request: CommunicationRequestView, command: PrepareDraftRequest,
  auth: RequestAuthHeaders, signal?: AbortSignal) {
  const value = await apiRequest<MessageDraftView>(`${base}/${pathId(request.communication_id)}/prepare`, {
    method: "POST", headers: authHeaders(auth), body: JSON.stringify(command), signal,
  });
  return scopedDraft(value, request);
}

export async function getDraft(request: CommunicationRequestView, draftId: string,
  auth: RequestAuthHeaders, signal?: AbortSignal) {
  const value = await apiRequest<MessageDraftView>(
    `${base}/${pathId(request.communication_id)}/drafts/${pathId(draftId)}`,
    { headers: authHeaders(auth), signal });
  return scopedDraft(value, request, draftId);
}
