import { ApiError, apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import type { ConfirmationState } from "../../shared/types";
import type { ConfirmationAttemptView, ConfirmationView, ResponseIntent } from "./confirmationTypes";
import type { DraftReference } from "./types";

const base = "/v1/confirmations";
export const confirmationKeys = {
  scope: (auth: RequestAuthHeaders) => ["p4-confirmations", auth.tenantId, auth.actorId] as const,
  queue: (auth: RequestAuthHeaders) => [...confirmationKeys.scope(auth), "follow-up-queue"] as const,
  list: (auth: RequestAuthHeaders, id: string) => [...confirmationKeys.scope(auth), "communication", id] as const,
  detail: (auth: RequestAuthHeaders, id: string) => [...confirmationKeys.scope(auth), "detail", id] as const,
  attempts: (auth: RequestAuthHeaders, id: string) => [...confirmationKeys.scope(auth), "attempts", id] as const,
};
const invalid = (): never => { throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Unsupported confirmation response"); };
const mismatch = (): never => { throw new ApiError(409, "RESPONSE_SCOPE_MISMATCH", "Confirmation scope mismatch"); };
const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : invalid();
const text = (value: unknown): string => typeof value === "string" && value.trim().length > 0 ? value : invalid();
const timestamp = (value: unknown): string => typeof value === "string" &&
  /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value)) ? value : invalid();
const nullableTime = (value: unknown) => value === null ? null : timestamp(value);
const strings = (value: unknown): string[] => Array.isArray(value) ? value.map(text) : invalid();
const version = (value: unknown): number => typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : invalid();
const digest = (value: unknown): string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value) ? value : invalid();
const states: readonly ConfirmationState[] = ["AWAITING_RESPONSE", "ACCEPTED", "REJECTED", "COUNTEROFFER_RECEIVED",
  "CLARIFICATION_REQUIRED", "UNRESOLVED", "EXPIRED", "SUPERSEDED"];
const intents: readonly ResponseIntent[] = ["ACCEPT", "REJECT", "COUNTEROFFER", "CLARIFICATION", "UNKNOWN"];

function checkedView(raw: unknown, auth: RequestAuthHeaders, id?: string, communicationId?: string): ConfirmationView {
  const value = record(raw);
  const ref = record(value.reference);
  if (value.tenant_id !== auth.tenantId || ref.tenant_id !== auth.tenantId ||
    (id !== undefined && value.confirmation_id !== id) ||
    (communicationId !== undefined && value.communication_id !== communicationId)) mismatch();
  if (!states.includes(value.state as ConfirmationState) ||
    !["MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"].includes(String(value.channel)) ||
    value.core_transition_applied !== false || value.evidence_scope !== "P4_EVIDENCE_ONLY" ||
    value.integration_mode !== "SYNTHETIC_ONLY") invalid();
  const reference: DraftReference = {
    tenant_id: auth.tenantId, commitment_id: text(ref.commitment_id), commitment_version: version(ref.commitment_version),
    proposal_id: text(ref.proposal_id), proposal_version: version(ref.proposal_version),
    plan_id: text(ref.plan_id), plan_version: version(ref.plan_version), source_event_id: text(ref.source_event_id),
    correlation_id: text(ref.correlation_id), causation_id: ref.causation_id === null ? null : text(ref.causation_id),
    occurred_at: timestamp(ref.occurred_at),
  };
  // Whitelist projection: unexpected token/contact/body/approval flags never enter
  // Query cache or rendering, even if a future server adds sensitive properties.
  return {
    confirmation_id: text(value.confirmation_id), tenant_id: auth.tenantId,
    communication_id: text(value.communication_id), outbound_id: text(value.outbound_id), customer_id: text(value.customer_id),
    channel: value.channel as ConfirmationView["channel"], reference,
    terms_digest: digest(value.terms_digest), content_hash: digest(value.content_hash), state: value.state as ConfirmationState,
    expires_at: timestamp(value.expires_at), created_at: timestamp(value.created_at),
    consumed_at: nullableTime(value.consumed_at), revoked_at: nullableTime(value.revoked_at), blocked_reasons: strings(value.blocked_reasons),
    core_transition_applied: false, evidence_scope: "P4_EVIDENCE_ONLY", integration_mode: "SYNTHETIC_ONLY",
  };
}

export async function getConfirmation(id: string, auth: RequestAuthHeaders, signal?: AbortSignal) {
  return checkedView(await apiRequest<unknown>(`${base}/${encodeURIComponent(id)}`, { headers: authHeaders(auth), signal }), auth, id);
}
export async function listConfirmations(communicationId: string | undefined, auth: RequestAuthHeaders, signal?: AbortSignal) {
  const query = communicationId === undefined ? "" : `?${new URLSearchParams({ communication_id: communicationId })}`;
  const result = await apiRequest<unknown>(`${base}${query}`, {
    headers: authHeaders(auth), signal,
  });
  if (!Array.isArray(result)) return invalid();
  const checked = result.map(raw => checkedView(raw, auth, undefined, communicationId));
  if (new Set(checked.map(value => value.confirmation_id)).size !== checked.length) return invalid();
  return checked;
}
export async function getConfirmationAttempts(id: string, auth: RequestAuthHeaders, signal?: AbortSignal): Promise<ConfirmationAttemptView[]> {
  const result = await apiRequest<unknown>(`${base}/${encodeURIComponent(id)}/attempts`, { headers: authHeaders(auth), signal });
  if (!Array.isArray(result)) return invalid();
  const checked = result.map(raw => {
    const value = record(raw);
    if (value.confirmation_id !== id) mismatch();
    if (!intents.includes(value.intent as ResponseIntent)) invalid();
    const evidence = strings(value.evidence_refs);
    if (!evidence.length) invalid();
    let changes: ConfirmationAttemptView["proposed_changes"] = null;
    if (value.proposed_changes !== null) {
      const source = record(value.proposed_changes);
      changes = {};
      for (const key of ["quantity", "deadline", "special_instructions"] as const) {
        if (source[key] !== undefined && source[key] !== null) changes[key] = text(source[key]);
      }
    }
    return { attempt_id: text(value.attempt_id), confirmation_id: id, inbound_message_id: text(value.inbound_message_id),
      intent: value.intent as ResponseIntent, reason: text(value.reason), evidence_refs: evidence,
      proposed_changes: changes, received_at: timestamp(value.received_at) };
  });
  if (new Set(checked.map(value => value.attempt_id)).size !== checked.length) return invalid();
  return checked;
}
