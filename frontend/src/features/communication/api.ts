import { ApiError, apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import type { CommunicationRequestView, CommunicationSummary, DraftReference, DraftReviewCommand, DraftReviewView, MessageDraftView, PrepareDraftRequest } from "./types";
import type { OutboundMessageView, SendEligibility } from "./types";

const base = "/v1/communications";
export const communicationKeys = {
  outbound: (auth: RequestAuthHeaders, id: string) => [...communicationKeys.scope(auth), "outbound", id] as const,
  eligibility: (auth: RequestAuthHeaders, draft: MessageDraftView) =>
    [...communicationKeys.scope(auth), "send-eligibility", draft.communication_id, draft.draft_id, draft.content_hash, draft.validation_hash] as const,
  scope: (auth: RequestAuthHeaders) => ["p4-communications", auth.tenantId, auth.actorId] as const,
  list: (auth: RequestAuthHeaders) => [...communicationKeys.scope(auth), "list"] as const,
  summary: (auth: RequestAuthHeaders) => [...communicationKeys.scope(auth), "summary"] as const,
  detail: (auth: RequestAuthHeaders, id: string) => [...communicationKeys.scope(auth), "detail", id] as const,
  draft: (auth: RequestAuthHeaders, id: string, draftId: string) =>
    [...communicationKeys.scope(auth), "draft", id, draftId] as const,
  review: (auth: RequestAuthHeaders, draft: MessageDraftView) =>
    [...communicationKeys.scope(auth), "review", draft.communication_id, draft.draft_id, draft.content_hash, draft.validation_hash] as const,
};
const pathId = (value: string) => encodeURIComponent(value);
const mismatch = () => new ApiError(409, "RESPONSE_SCOPE_MISMATCH", "Response does not match requested scope");

export async function getCommunicationSummary(auth: RequestAuthHeaders, signal?: AbortSignal) {
  const value = await apiRequest<CommunicationSummary>(`${base}/summary`, { headers: authHeaders(auth), signal });
  if (value?.tenant_id !== auth.tenantId) throw mismatch();
  const count = (number: unknown): number is number => typeof number === "number" && Number.isSafeInteger(number) && number >= 0;
  if (!count(value.total) || !count(value.needs_attention) || value.needs_attention > value.total ||
      [value.drafted, value.sent].some(number => number !== null && (!count(number) || number > value.total)) ||
      !Number.isFinite(Date.parse(value.checked_at))) {
    throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Invalid summary response");
  }
  return value;
}

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

function checkedReview(value: DraftReviewView, draft: MessageDraftView) {
  if (value?.tenant_id !== draft.tenant_id || value.communication_id !== draft.communication_id || value.draft_id !== draft.draft_id) throw mismatch();
  const decision = value.decision;
  if (!["PENDING", "APPROVED", "REJECTED", "INVALIDATED", "EXPIRED"].includes(value.review_state) ||
      value.send_authorized !== false || value.effective_approval !== (value.review_state === "APPROVED") ||
      !Array.isArray(value.allowed_actions) || value.allowed_actions.some(action => !["APPROVE_DRAFT", "REJECT_DRAFT"].includes(action)) ||
      (value.review_state !== "PENDING" && !decision)) throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Invalid review response");
  if (decision && (decision.tenant_id !== draft.tenant_id || decision.communication_id !== draft.communication_id || decision.draft_id !== draft.draft_id)) throw mismatch();
  if (value.effective_approval && (!decision || decision.action !== "APPROVE_DRAFT" ||
      decision.content_hash !== draft.content_hash || decision.validation_hash !== draft.validation_hash ||
      decision.recipient_identity_id !== draft.recipient_identity_id || decision.channel !== draft.channel || decision.language !== draft.language ||
      decision.reference.proposal_id !== draft.reference.proposal_id || decision.reference.proposal_version !== draft.reference.proposal_version)) throw mismatch();
  return value;
}
function reviewPath(draft: MessageDraftView) {
  return `${base}/${pathId(draft.communication_id)}/drafts/${pathId(draft.draft_id)}`;
}
export async function getDraftReview(draft: MessageDraftView, auth: RequestAuthHeaders, signal?: AbortSignal) {
  return checkedReview(await apiRequest<DraftReviewView>(`${reviewPath(draft)}/review`, { headers: authHeaders(auth), signal }), draft);
}
export async function submitDraftReview(draft: MessageDraftView, action: "approve" | "reject", command: DraftReviewCommand,
  auth: RequestAuthHeaders, signal?: AbortSignal) {
  return checkedReview(await apiRequest<DraftReviewView>(`${reviewPath(draft)}/${action}`, {
    method: "POST", headers: authHeaders(auth), body: JSON.stringify(command), signal,
  }), draft);
}

export async function getSendEligibility(draft: MessageDraftView, auth: RequestAuthHeaders, signal?: AbortSignal) {
  if (draft.tenant_id !== auth.tenantId) throw mismatch();
  const value = await apiRequest<SendEligibility>(`${reviewPath(draft)}/send-eligibility`, { headers: authHeaders(auth), signal });
  if (value?.tenant_id !== auth.tenantId || value.communication_id !== draft.communication_id || value.draft_id !== draft.draft_id) throw mismatch();
  if (typeof value.can_send !== "boolean" || !Number.isFinite(Date.parse(value.checked_at)) ||
      (value.can_send && (value.content_hash !== draft.content_hash || !value.approved_review_id || !value.expires_at ||
        !Number.isFinite(Date.parse(value.expires_at)) || value.blocked_reason !== null))) throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Invalid send eligibility");
  return value;
}
function checkedOutbound(value: OutboundMessageView, id: string, auth: RequestAuthHeaders) {
  if (value?.tenant_id !== auth.tenantId || value.communication_id !== id) throw mismatch();
  if (!["QUEUED", "SENT", "FAILED", "DELIVERY_UNKNOWN"].includes(value.status) || value.retry_allowed !== false ||
      !Array.isArray(value.attempts) || typeof value.provider_confirmed !== "boolean" ||
      (value.status === "SENT" && (!value.provider_confirmed || !value.provider_reference || !value.sent_at || !Number.isFinite(Date.parse(value.sent_at)))) ||
      (value.status !== "SENT" && (value.provider_confirmed || value.sent_at !== null))) throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Invalid outbound result");
  return value;
}
export async function getOutboundHistory(id: string, auth: RequestAuthHeaders, signal?: AbortSignal) {
  const values = await apiRequest<OutboundMessageView[]>(`${base}/${pathId(id)}/outbound`, { headers: authHeaders(auth), signal });
  if (!Array.isArray(values)) throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Invalid sending history");
  return values.map(value => checkedOutbound(value, id, auth));
}
export async function sendMessage(draft: MessageDraftView, requestKey: string, auth: RequestAuthHeaders, signal?: AbortSignal) {
  const value = checkedOutbound(await apiRequest<OutboundMessageView>(`${reviewPath(draft)}/send`, {
    method: "POST", headers: authHeaders(auth), signal,
    body: JSON.stringify({ request_key: requestKey, expected_content_hash: draft.content_hash }),
  }), draft.communication_id, auth);
  if (value.draft_id !== draft.draft_id || value.content_hash !== draft.content_hash || value.channel !== draft.channel) throw mismatch();
  return value;
}
