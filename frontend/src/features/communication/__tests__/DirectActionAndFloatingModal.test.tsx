import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../../../shared/auth";
import type { CommunicationRequestView, CommunicationSummary, MessageDraftView } from "../types";
import { CommunicationCenterPage } from "../CommunicationCenterPage";

function makeRequest(id = "a", changes: Partial<CommunicationRequestView> = {}): CommunicationRequestView {
  return {
    communication_id: `req-${id}`,
    reference: {
      source_event_id: `evt-${id}`,
      tenant_id: "tenant-test",
      correlation_id: `corr-${id}`,
      causation_id: null,
      occurred_at: "2026-10-22T10:00:00+08:00",
      commitment_id: `commitment-${id}`,
      commitment_version: 2,
      plan_id: `plan-${id}`,
      plan_version: 1,
      proposal_id: `proposal-${id}`,
      proposal_version: 3,
    },
    request_status: "READY_FOR_DRAFTING",
    blocking_reasons: [],
    proposed_terms: {
      sku: "SKU-NUGGETS",
      quantity: "20",
      unit: "boxes",
      deadline: "2030-10-28T10:00:00+08:00",
      special_instructions: "Deliver before 10 AM",
    },
    message_status: "DRAFT",
    approval_evidence_refs: ["approval-ev-1"],
    approval_expires_at: "2030-10-28T10:00:00+08:00",
    proposal_evidence_refs: ["proposal-ev-1"],
    recipient_identity_id: "customer_01",
    recipient_evidence_refs: ["identity-ev-1"],
    channel: "MOCK_WHATSAPP",
    channel_evidence_refs: ["channel-ev-1"],
    expires_at: "2030-10-28T10:00:00+08:00",
    created_by: "manager-test",
    created_at: "2026-10-24T04:01:22+08:00",
    ...changes,
  };
}

function makeDraft(req = makeRequest()): MessageDraftView {
  return {
    draft_id: `draft-${req.communication_id}`,
    tenant_id: req.reference.tenant_id,
    communication_id: req.communication_id,
    reference: req.reference,
    order_id: "order-test",
    template_key: "delivery_change",
    template_version: 1,
    language: "en",
    channel: req.channel ?? "MOCK_WHATSAPP",
    subject: "Order schedule update",
    body: "Hi, I'd like to order 20 boxes of chicken nuggets. Please confirm delivery.",
    approved_terms: req.proposed_terms,
    approval_evidence_refs: ["approval-ev-1"],
    proposal_evidence_refs: ["proposal-ev-1"],
    recipient_identity_id: "customer_01",
    recipient_evidence_refs: ["identity-ev-1"],
    channel_evidence_refs: ["channel-ev-1"],
    content_hash: "a".repeat(64),
    validation_hash: "b".repeat(64),
    status: "DRAFT",
    send_authorized: false,
    expires_at: "2030-10-28T10:00:00+08:00",
    created_at: "2026-10-24T04:02:00+08:00",
  };
}

const auth = { tenantId: "tenant-test", actorId: "user_manager_01" };
const reply = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

let records: CommunicationRequestView[];
let savedDrafts: Record<string, MessageDraftView>;
let approvedDrafts: Set<string>;
let rejectedDrafts: Set<string>;
const fetchMock = vi.fn<typeof fetch>();
const clients: QueryClient[] = [];

beforeEach(() => {
  records = [makeRequest("001"), makeRequest("delay_01")];
  savedDrafts = {};
  approvedDrafts = new Set();
  rejectedDrafts = new Set();
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, _init) => {
    const url = new URL(String(input));
    if (url.pathname === "/v1/confirmations") return reply([]);
    if (url.pathname.endsWith("/runtime-capabilities")) {
      return reply({
        tenant_id: auth.tenantId,
        mode: "SYNTHETIC",
        label: "Synthetic Demo",
        can_record_preferences: true,
        can_revoke_preferences: true,
        integrated_demo_ready: true,
        blockers: [],
      });
    }
    if (url.pathname === "/v1/communications/summary") {
      const summary: CommunicationSummary = {
        tenant_id: auth.tenantId,
        total: records.length,
        drafted: approvedDrafts.size,
        sent: 0,
        needs_attention: 0,
        checked_at: "2026-10-24T04:00:00+08:00",
        unavailable_reasons: {},
      };
      return reply(summary);
    }
    if (url.pathname.endsWith("/outbound")) return reply([]);
    if (url.pathname === "/v1/communications") return reply(records);

    const parts = url.pathname.split("/");
    const commId = decodeURIComponent(parts[3] ?? "");
    const req = records.find(r => r.communication_id === commId);
    if (!req) return reply({ code: "COMMUNICATION_NOT_FOUND" }, 404);

    if (parts[4] === "prepare") {
      const d = makeDraft(req);
      savedDrafts[d.draft_id] = d;
      return reply(d);
    }

    if (parts[4] === "drafts" && parts[6] === "approve") {
      approvedDrafts.add(decodeURIComponent(parts[5]));
      return reply({
        tenant_id: req.reference.tenant_id,
        communication_id: commId,
        draft_id: decodeURIComponent(parts[5]),
        review_state: "APPROVED",
        effective_approval: true,
        send_authorized: false,
        allowed_actions: [],
        decision: {
          review_id: "rev-1",
          tenant_id: req.reference.tenant_id,
          communication_id: commId,
          draft_id: decodeURIComponent(parts[5]),
          reference: req.reference,
          action: "APPROVE_DRAFT",
          reviewer_id: auth.actorId,
          reviewer_role: "MANAGER",
          reviewed_at: "2026-10-24T04:05:00+08:00",
          expires_at: "2030-10-28T10:00:00+08:00",
          content_hash: "a".repeat(64),
          validation_hash: "b".repeat(64),
          language: "en",
          recipient_identity_id: "customer_01",
          channel: req.channel ?? "MOCK_WHATSAPP",
          authorization_evidence_refs: ["auth-ev-1"],
          audit_id: "audit-1",
        },
        checked_at: "2026-10-24T04:05:00+08:00",
      });
    }

    if (parts[4] === "drafts" && parts[6] === "reject") {
      rejectedDrafts.add(decodeURIComponent(parts[5]));
      return reply({
        tenant_id: req.reference.tenant_id,
        communication_id: commId,
        draft_id: decodeURIComponent(parts[5]),
        review_state: "REJECTED",
        effective_approval: false,
        send_authorized: false,
        allowed_actions: [],
        decision: {
          review_id: "rev-2",
          tenant_id: req.reference.tenant_id,
          communication_id: commId,
          draft_id: decodeURIComponent(parts[5]),
          reference: req.reference,
          action: "REJECT_DRAFT",
          reviewer_id: auth.actorId,
          reviewer_role: "MANAGER",
          reviewed_at: "2026-10-24T04:05:00+08:00",
          expires_at: "2030-10-28T10:00:00+08:00",
          content_hash: "a".repeat(64),
          validation_hash: "b".repeat(64),
          language: "en",
          recipient_identity_id: "customer_01",
          channel: req.channel ?? "MOCK_WHATSAPP",
          authorization_evidence_refs: ["auth-ev-1"],
          reason: "Draft rejected by manager",
          audit_id: "audit-2",
        },
        checked_at: "2026-10-24T04:05:00+08:00",
      });
    }

    if (parts[4] === "drafts") {
      const d = savedDrafts[decodeURIComponent(parts[5])];
      return d ? reply(d) : reply({ code: "DRAFT_NOT_FOUND" }, 404);
    }

    return reply(req);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  clients.splice(0).forEach(c => c.clear());
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mountApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false }, mutations: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthProvider initialTenantId={auth.tenantId} initialActorId={auth.actorId}>
        <MemoryRouter>
          <CommunicationCenterPage />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
  return client;
}

describe("Redesigned Communication Center - Floating Modal & Direct Actions", () => {
  it("clicking Preview opens the floating centered modal in read-only preview mode", async () => {
    mountApp();
    const rows = await screen.findAllByRole("row");
    const row1 = rows[1];
    const previewBtn = within(row1).getByRole("button", { name: "Preview" });
    fireEvent.click(previewBtn);

    const modal = await screen.findByTestId("communication-details-modal");
    expect(modal).toBeInTheDocument();
    expect(modal).toHaveClass("ra-dialog", "cc-modal-dialog");

    // Modal Header contains 'Preview Draft' and chips
    expect(await within(modal).findByText("Preview Draft")).toBeInTheDocument();
    expect(within(modal).getByText("PREVIEW")).toBeInTheDocument();

    // 4 Independent Workflow state strip is rendered
    expect(within(modal).getByText("Message sent")).toBeInTheDocument();
    expect(within(modal).getByText("Terms accepted")).toBeInTheDocument();
    expect(within(modal).getByText("Action completed")).toBeInTheDocument();
    expect(within(modal).getByText("Fulfilled")).toBeInTheDocument();

    // Read-only indicator is present
    expect(within(modal).getByText(/You are viewing a read-only preview/i)).toBeInTheDocument();
    expect(within(modal).getByText("Request & Proposal Details")).toBeInTheDocument();
    expect(within(modal).getByText("Draft Message Preview")).toBeInTheDocument();

    // In preview mode: NO prepare draft button, NO approve/reject actions inside
    expect(within(modal).queryByRole("button", { name: "Prepare draft" })).not.toBeInTheDocument();
    expect(within(modal).queryByRole("button", { name: "Approve draft" })).not.toBeInTheDocument();

    // Footer has Close button
    const closeBtn = within(modal).getByRole("button", { name: "Close" });
    fireEvent.click(closeBtn);
    await waitFor(() => {
      expect(screen.queryByTestId("communication-details-modal")).not.toBeInTheDocument();
    });
  });

  it("clicking Edit draft opens the floating centered modal with all 4 stages preserved", async () => {
    mountApp();
    const rows = await screen.findAllByRole("row");
    const row1 = rows[1];
    const editBtn = within(row1).getByRole("button", { name: "Edit draft" });
    fireEvent.click(editBtn);

    const modal = await screen.findByTestId("communication-details-modal");
    expect(modal).toBeInTheDocument();

    // Modal Header contains 'Review & Edit Draft'
    expect(await within(modal).findByText("Review & Edit Draft")).toBeInTheDocument();

    // All 4 workflow tabs / stages are preserved
    expect(within(modal).getByRole("tab", { name: "Request Overview" })).toBeInTheDocument();
    expect(within(modal).getByRole("tab", { name: "Draft Message" })).toBeInTheDocument();
    expect(within(modal).getByRole("tab", { name: "Send / Simulate" })).toBeInTheDocument();
    expect(within(modal).getByRole("tab", { name: "History & Confirmation" })).toBeInTheDocument();

    // Switching to Draft Message tab enables draft preparation
    fireEvent.click(within(modal).getByRole("tab", { name: "Draft Message" }));
    expect(within(modal).getByRole("button", { name: "Prepare draft" })).toBeInTheDocument();
  });

  it("clicking Approve button directly approves the draft without opening the modal", async () => {
    mountApp();
    const rows = await screen.findAllByRole("row");
    const row1 = rows[1];
    const approveBtn = within(row1).getByRole("button", { name: "Approve" });
    expect(approveBtn).toBeInTheDocument();

    fireEvent.click(approveBtn);

    // Modal was NOT opened
    expect(screen.queryByTestId("communication-details-modal")).not.toBeInTheDocument();

    // Success badge appears on row
    await waitFor(() => {
      expect(within(row1).getByText("✓ Approved")).toBeInTheDocument();
    });

    // Check fetch calls to ensure POST approve was sent
    const approveCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/approve"));
    expect(approveCall).toBeDefined();
  });

  it("clicking Reject button directly rejects the draft without opening the modal", async () => {
    mountApp();
    const rows = await screen.findAllByRole("row");
    const row2 = rows[2];
    const rejectBtn = within(row2).getByRole("button", { name: "Reject" });
    expect(rejectBtn).toBeInTheDocument();

    fireEvent.click(rejectBtn);

    // Modal was NOT opened
    expect(screen.queryByTestId("communication-details-modal")).not.toBeInTheDocument();

    // Success badge appears on row
    await waitFor(() => {
      expect(within(row2).getByText("✓ Rejected")).toBeInTheDocument();
    });

    // Check fetch calls to ensure POST reject was sent with reason
    const rejectCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/reject"));
    expect(rejectCall).toBeDefined();
    const body = JSON.parse(rejectCall![1]?.body as string);
    expect(body.reason).toBeTruthy();
  });
});
