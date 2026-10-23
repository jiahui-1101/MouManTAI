import type { CommunicationRequestView, DraftReviewView, MessageDraftView, OutboundMessageView } from "../types";
import type { ConfirmationAttemptView, ConfirmationView } from "../confirmationTypes";

// Explicit QA/test transport only. No production module imports this file.
export const QA_AUTH = { tenantId: "synthetic_tenant_a", actorId: "user_manager_01" };
export const QA_CONFIRMATION_ID = "conf_demo_proposal_v3";
export const QA_DRAFT_ID = "draft_demo_preview_v3";
export const QA_LONG_ID = "comm_demo_" + "0123456789abcdef".repeat(7);
export const QA_LONG_EVIDENCE = "p1:evidence:qa_" + "0123456789abcdef".repeat(7);
export type QAScenario = "ready" | "send" | "empty" | "loading" | "403" | "409" | "503";

export function createPolishFixtures(now = Date.now()) {
  const time = (hours: number) => new Date(now + hours * 3600_000).toISOString();
  const reference = { tenant_id: QA_AUTH.tenantId, commitment_id: "com_demo_order_42", commitment_version: 2,
    proposal_id: "proposal_delivery_change", proposal_version: 3, plan_id: "plan_demo_recovery", plan_version: 1,
    source_event_id: "evt_demo_communication", correlation_id: "corr_demo_trace", causation_id: null, occurred_at: time(-4) };
  const terms = { sku: "SKU-DEMO", quantity: "100", unit: "pcs", deadline: time(72), special_instructions: "Keep upright. Proposed revised delivery remains subject to verified customer agreement." };
  const request: CommunicationRequestView = { communication_id: QA_LONG_ID, reference,
    request_status: "READY_FOR_DRAFTING", blocking_reasons: [], proposed_terms: terms, message_status: "DRAFT",
    approval_evidence_refs: ["qa:approval:plan"], approval_expires_at: time(24), proposal_evidence_refs: ["qa:proposal:v3"],
    recipient_identity_id: "qa:identity:customer", recipient_evidence_refs: ["qa:recipient"], channel: "MOCK_TELEGRAM",
    channel_evidence_refs: ["qa:channel"], expires_at: time(24), created_by: QA_AUTH.actorId, created_at: time(-4) };
  const draft: MessageDraftView = { draft_id: QA_DRAFT_ID, tenant_id: QA_AUTH.tenantId, communication_id: QA_LONG_ID,
    reference, order_id: "order_demo_42", template_key: "delivery_change", template_version: 1, language: "en", channel: "MOCK_TELEGRAM",
    subject: null, body: "Dear customer, please review proposal_delivery_change v3 for 100 pcs.\n\n" +
      "This is an explicitly labelled QA preview, not a customer message. Revised terms require verified agreement.\n".repeat(16) + QA_LONG_EVIDENCE,
    approved_terms: terms, approval_evidence_refs: request.approval_evidence_refs, proposal_evidence_refs: request.proposal_evidence_refs,
    recipient_identity_id: "qa:identity:customer", recipient_evidence_refs: ["qa:recipient"], channel_evidence_refs: ["qa:channel"],
    content_hash: "a".repeat(64), validation_hash: "b".repeat(64), status: "DRAFT", send_authorized: false, expires_at: time(24), created_at: time(-2) };
  const review: DraftReviewView = { tenant_id: QA_AUTH.tenantId, communication_id: QA_LONG_ID, draft_id: QA_DRAFT_ID,
    review_state: "PENDING", effective_approval: false, send_authorized: false, allowed_actions: ["APPROVE_DRAFT", "REJECT_DRAFT"],
    decision: null, invalidated_at: null, invalidation_code: null, invalidation_audit_id: null, checked_at: time(0) };
  const confirmation: ConfirmationView = { confirmation_id: QA_CONFIRMATION_ID, tenant_id: QA_AUTH.tenantId,
    communication_id: QA_LONG_ID, outbound_id: "outbound_demo_v3", customer_id: "customer_demo_42", channel: "MOCK_TELEGRAM",
    reference, terms_digest: "c".repeat(64), content_hash: "a".repeat(64), state: "AWAITING_RESPONSE",
    created_at: time(-3), expires_at: time(2), consumed_at: null, revoked_at: null, blocked_reasons: [],
    core_transition_applied: false, evidence_scope: "P4_EVIDENCE_ONLY", integration_mode: "SYNTHETIC_ONLY" };
  const confirmations: ConfirmationView[] = [confirmation,
    { ...confirmation, confirmation_id: "conf_demo_v2_accepted", communication_id: "comm_demo_previous_v2", outbound_id: "outbound_demo_v2",
      reference: { ...reference, proposal_version: 2 }, state: "ACCEPTED", consumed_at: time(-1), expires_at: time(5) },
    { ...confirmation, confirmation_id: "conf_demo_" + "a".repeat(110), communication_id: "comm_demo_unresolved", outbound_id: "outbound_demo_unresolved",
      state: "UNRESOLVED", expires_at: time(12) },
    { ...confirmation, confirmation_id: "conf_demo_expired", communication_id: "comm_demo_expired", outbound_id: "outbound_demo_expired",
      state: "EXPIRED", expires_at: time(-1), blocked_reasons: ["CONFIRMATION_EXPIRED"] },
    { ...confirmation, confirmation_id: "conf_demo_superseded", communication_id: "comm_demo_superseded", outbound_id: "outbound_demo_superseded",
      state: "SUPERSEDED", blocked_reasons: ["CONFIRMATION_PROPOSAL_CHANGED"] }];
  const attempts: ConfirmationAttemptView[] = [
    { attempt_id: "response_demo_ambiguous", confirmation_id: QA_CONFIRMATION_ID, inbound_message_id: "p1:message:demo_ambiguous",
      intent: "UNKNOWN", reason: "AMBIGUOUS_OR_UNBOUND_RESPONSE", evidence_refs: [QA_LONG_EVIDENCE], proposed_changes: null, received_at: time(-2) },
    { attempt_id: "response_demo_clarification", confirmation_id: QA_CONFIRMATION_ID, inbound_message_id: "p1:message:demo_clarification",
      intent: "CLARIFICATION", reason: "EXPLICIT_BOUND_RESPONSE", evidence_refs: ["qa:response:clarification"], proposed_changes: null, received_at: time(-1) }];
  const outbound: OutboundMessageView = { tenant_id: QA_AUTH.tenantId, outbound_id: "outbound_demo_prior", communication_id: QA_LONG_ID,
    draft_id: "draft_demo_prior", approved_review_id: "review_demo_prior", content_hash: "d".repeat(64), channel: "MOCK_TELEGRAM",
    status: "SENT", provider_reference: "mock:qa:receipt", provider_confirmed: true, created_at: time(-2), updated_at: time(-1),
    sent_at: time(-1), failed_at: null, last_error_code: null, retry_allowed: false, reconciliation_required: false, attempts: [] };
  return { request, draft, review, confirmation, confirmations, attempts, outbound, time };
}

export function createPolishTransport(scenario: QAScenario = "ready", now = Date.now()): typeof fetch {
  const data = createPolishFixtures(now);
  const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
  return async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    if (init?.method && init.method !== "GET") return reply({ code: "QA_READ_ONLY", message: "QA fixture never persists mutations" }, 403);
    if (scenario === "loading") return new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    });
    if (["403", "409", "503"].includes(scenario) && !url.pathname.endsWith("runtime-capabilities")) {
      const code = scenario === "409" ? "PROPOSAL_ID_MISMATCH" : scenario === "503" ? "CONFIRMATION_PROCESSOR_AUTH_UNAVAILABLE" : "FORBIDDEN";
      return reply({ code, message: "PRIVATE QA DIAGNOSTICS NOT FOR UI", correlation_id: "corr_demo_error_" + "q".repeat(100) }, Number(scenario));
    }
    if (url.pathname === "/v1/overview") {
      return reply({
        tenant_id: QA_AUTH.tenantId,
        actor_id: QA_AUTH.actorId,
        actor_role: "MANAGER",
        integration_mode: "SYNTHETIC",
        last_updated_at: data.time(0),
        counts: { requested: 0, confirmed: 0, at_risk: 0, pending_approval: 0, execution_in_progress: 0, awaiting_confirmation: 0, fulfilled: 0 },
        attention_queue: [],
        commitments: [],
      });
    }
    if (url.pathname.endsWith("/runtime-capabilities")) return reply({ tenant_id: QA_AUTH.tenantId, mode: "CLOSED",
      label: "Synthetic QA only", can_record_preferences: false, can_revoke_preferences: false, integrated_demo_ready: false,
      blockers: ["CORE_APPROVAL_PRODUCER_UNAVAILABLE"] });
    if (url.pathname === "/v1/communications/summary") return reply({ tenant_id: QA_AUTH.tenantId,
      total: scenario === "empty" ? 0 : 1, drafted: 0, sent: 0, needs_attention: 0, checked_at: data.time(0), unavailable_reasons: {} });
    if (url.pathname === "/v1/communications") return reply(scenario === "empty" ? [] : [data.request]);
    if (url.pathname === `/v1/communications/${QA_LONG_ID}`) return reply(data.request);
    if (url.pathname.endsWith("/outbound")) return reply(scenario === "send" ? [] : [data.outbound]);
    if (url.pathname.endsWith("/send-eligibility")) return reply({ tenant_id: QA_AUTH.tenantId, communication_id: QA_LONG_ID,
      draft_id: QA_DRAFT_ID, can_send: scenario === "send", content_hash: scenario === "send" ? data.draft.content_hash : null,
      approved_review_id: scenario === "send" ? "qa-review" : null, expires_at: scenario === "send" ? data.draft.expires_at : null,
      blocked_reason: scenario === "send" ? null : "SEND_AUTHORITY_UNAVAILABLE", checked_at: data.time(0) });
    if (url.pathname.endsWith("/review")) return reply(data.review);
    if (url.pathname === `/v1/communications/${QA_LONG_ID}/drafts/${QA_DRAFT_ID}`) return reply(data.draft);
    if (url.pathname === "/v1/confirmations") return reply(scenario === "empty" ? [] : data.confirmations.filter(value =>
      !url.searchParams.has("communication_id") || value.communication_id === url.searchParams.get("communication_id")));
    if (url.pathname.endsWith("/attempts")) return reply(scenario === "empty" ? [] : data.attempts);
    if (url.pathname === `/v1/confirmations/${QA_CONFIRMATION_ID}`) return scenario === "empty"
      ? reply({ code: "CONFIRMATION_NOT_FOUND", message: "No QA record exists in the empty scenario" }, 404)
      : reply(data.confirmation);
    return reply({ code: "NOT_FOUND", message: "No test fixture for endpoint" }, 404);
  };
}
