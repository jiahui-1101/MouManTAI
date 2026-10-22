import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ManagerReview } from "./ManagerReview";
import { DraftPreview } from "./DraftPreview";
import type { DraftReviewDecision, DraftReviewView, MessageDraftView } from "./types";
import type { RequestAuthHeaders } from "../../shared/api";

const auth = { tenantId: "tenant-test", actorId: "user_manager_01" };
function draft(id = "a"): MessageDraftView {
  return { draft_id: `draft-${id}`, tenant_id: auth.tenantId, communication_id: `request-${id}`,
    reference: { source_event_id: `event-${id}`, tenant_id: auth.tenantId, correlation_id: "correlation-test", causation_id: null,
      occurred_at: "2026-10-22T10:00:00Z", commitment_id: `commitment-${id}`, commitment_version: 2,
      plan_id: "plan-test", plan_version: 1, proposal_id: `proposal-${id}`, proposal_version: 3 },
    order_id: "order-test", template_key: "delivery_change", template_version: 1, language: "en", channel: "MOCK_TELEGRAM",
    subject: null, body: `Backend message ${id}`, approved_terms: { sku: "SKU", quantity: "10.25", unit: "pcs", deadline: "2030-10-25T15:00:00+08:00" },
    approval_evidence_refs: ["ev_core"], proposal_evidence_refs: ["ev_proposal"], recipient_identity_id: "identity-test",
    recipient_evidence_refs: ["ev_identity"], channel_evidence_refs: ["ev_channel"], content_hash: (id === "a" ? "a" : "b").repeat(64),
    validation_hash: "c".repeat(64), status: "DRAFT", send_authorized: false, expires_at: "2030-10-24T10:00:00Z", created_at: "2026-10-22T10:00:00Z" };
}
function pending(value = draft()): DraftReviewView {
  return { tenant_id: value.tenant_id, communication_id: value.communication_id, draft_id: value.draft_id,
    review_state: "PENDING", effective_approval: false, send_authorized: false, allowed_actions: ["APPROVE_DRAFT", "REJECT_DRAFT"],
    decision: null, invalidated_at: null, invalidation_code: null, invalidation_audit_id: null, checked_at: "2026-10-22T10:01:00Z" };
}
function decided(value: MessageDraftView, action: "APPROVE_DRAFT" | "REJECT_DRAFT", reason: string | null = null): DraftReviewView {
  const decision: DraftReviewDecision = { ...value, review_id: `review-${value.draft_id}`, request_key: "request_key_test",
    action, reviewer_id: auth.actorId, reviewer_role: "MANAGER", reviewed_at: "2026-10-22T10:01:00Z",
    core_approval_evidence_refs: value.approval_evidence_refs, authorization_evidence_refs: ["ev_policy"], reason,
    audit_id: "audit-test", correlation_id: "corr-test" };
  return { ...pending(value), review_state: action === "APPROVE_DRAFT" ? "APPROVED" : "REJECTED",
    effective_approval: action === "APPROVE_DRAFT", allowed_actions: [], decision };
}
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const failed = (code: string, status: number) => reply({ code, message: "SECRET STACK TRACE" }, status);
let stored: Record<string, DraftReviewView>;
let readonly: boolean;
let override: ((path: string, init?: RequestInit) => Response | Promise<Response> | undefined) | undefined;
const fetchMock = vi.fn<typeof fetch>();
const clients: QueryClient[] = [];
beforeEach(() => {
  stored = {}; readonly = false; override = undefined;
  let uuid = 0;
  vi.stubGlobal("crypto", { randomUUID: () => `review_request_key_${++uuid}` });
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, init) => {
    const path = new URL(String(input)).pathname;
    const custom = override?.(path, init); if (custom) return custom;
    const parts = path.split("/"); const value = draft(parts[5]?.endsWith("b") ? "b" : "a");
    if (parts[6] === "review") return reply(stored[value.draft_id] ?? { ...pending(value), allowed_actions: readonly ? [] : pending(value).allowed_actions });
    const command = JSON.parse(init!.body as string);
    const result = decided(value, parts[6] === "approve" ? "APPROVE_DRAFT" : "REJECT_DRAFT", command.reason ?? null);
    stored[value.draft_id] = result; return reply(result);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals(); });
function mount(value = draft(), scope: RequestAuthHeaders = auth) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  clients.push(client);
  const content = (next: MessageDraftView, headers: RequestAuthHeaders) => <QueryClientProvider client={client}>
    <DraftPreview draft={next} onReload={() => {}} />
    <ManagerReview key={`${headers.tenantId}:${headers.actorId}:${next.communication_id}:${next.draft_id}:${next.content_hash}`} draft={next} auth={headers} now={Date.now()} />
  </QueryClientProvider>;
  const view = render(content(value, scope));
  return { client, switchTo: (next: MessageDraftView, headers = scope) => view.rerender(content(next, headers)) };
}
const region = () => screen.getByRole("region", { name: "Manager Review" });
const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
async function confirmApproval() {
  fireEvent.click(await screen.findByRole("button", { name: "Approve Draft" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm Approve Draft" }));
}

describe("Manager Review", () => {
  it("appears for the loaded preview and uses backend-granted actions", async () => {
    mount(); expect(screen.getByRole("article", { name: "Message draft preview" })).toHaveTextContent("Backend message a");
    expect(await screen.findByText("Pending Review")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve Draft" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject Draft" })).toBeDisabled();
    expect(screen.getByText("identity-test")).toBeInTheDocument();
  });

  it("requires explicit confirmation, permits cancel, then submits only hash/key with no message terms", async () => {
    mount(); fireEvent.click(await screen.findByRole("button", { name: "Approve Draft" }));
    expect(posts()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Cancel approval" })); expect(posts()).toHaveLength(0);
    await confirmApproval();
    expect(await screen.findByText("Draft approved. The message has not been sent.")).toBeInTheDocument();
    expect(posts()).toHaveLength(1);
    expect(posts()[0][0]).toContain("/v1/communications/request-a/drafts/draft-a/approve");
    expect(JSON.parse(posts()[0][1]!.body as string)).toEqual({ request_key: expect.any(String), expected_content_hash: "a".repeat(64) });
    expect(posts()[0][1]?.headers).toMatchObject({ "X-Tenant-ID": auth.tenantId, "X-Actor-ID": auth.actorId });
    expect(screen.queryByRole("button", { name: /^send/i })).not.toBeInTheDocument();
  });

  it("shows loading and blocks duplicate approve clicks", async () => {
    let finish!: (value: Response) => void;
    override = (_path, init) => init?.method === "POST" ? new Promise(resolve => { finish = resolve; }) : undefined;
    mount(); await confirmApproval();
    const confirm = screen.getByRole("button", { name: "Confirm Approve Draft" }); fireEvent.click(confirm); fireEvent.click(confirm);
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(screen.getByText("Saving draft review…")).toBeInTheDocument(); expect(confirm).toBeDisabled();
    const result = decided(draft(), "APPROVE_DRAFT"); stored["draft-a"] = result;
    await act(async () => finish(reply(result)));
    await screen.findByText("Draft approved. The message has not been sent.");
  });

  it.each([[403, "REVIEW_FORBIDDEN"], [503, "REVIEW_AUTHORITY_UNAVAILABLE"], [409, "STALE_PROPOSAL_VERSION"]])(
    "shows approve HTTP %s errors without success or internal diagnostics", async (status, code) => {
      override = (_path, init) => init?.method === "POST" ? failed(String(code), Number(status)) : undefined;
      mount(); await confirmApproval();
      expect(await screen.findByRole("alert")).not.toHaveTextContent("SECRET STACK TRACE");
      expect(screen.queryByText("Draft approved. The message has not been sent.")).not.toBeInTheDocument();
    });

  it("reuses the same request key for the same failed operation retry", async () => {
    override = (_path, init) => init?.method === "POST" ? failed("REVIEW_STORAGE_UNAVAILABLE", 503) : undefined;
    mount(); await confirmApproval(); await screen.findByRole("alert");
    const first = JSON.parse(posts()[0][1]!.body as string).request_key;
    override = undefined;
    fireEvent.click(await screen.findByRole("button", { name: "Confirm Approve Draft" }));
    await screen.findByText("Draft approved. The message has not been sent.");
    expect(JSON.parse(posts()[1][1]!.body as string).request_key).toBe(first);
  });

  it("requires nonblank rejection reason and records the server's rejection result", async () => {
    mount(); await screen.findByText("Pending Review");
    const button = screen.getByRole("button", { name: "Reject Draft" }); expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Rejection reason"), { target: { value: "  " } }); expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Rejection reason"), { target: { value: "Please revise the wording" } }); fireEvent.click(button);
    await screen.findByText("Draft rejected. No message was sent.");
    expect(screen.getByText("Rejection reason: Please revise the wording")).toBeInTheDocument();
    expect(JSON.parse(posts()[0][1]!.body as string).reason).toBe("Please revise the wording");
    expect(screen.queryByRole("button", { name: "Approve Draft" })).not.toBeInTheDocument();
  });

  it("shows a rejection error without inventing REJECTED", async () => {
    override = (path, init) => path.endsWith("/reject") && init?.method === "POST" ? failed("REVIEW_FORBIDDEN", 403) : undefined;
    mount(); await screen.findByText("Pending Review");
    fireEvent.change(screen.getByLabelText("Rejection reason"), { target: { value: "Revise" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject Draft" }));
    await screen.findByRole("alert"); expect(screen.queryByText("Draft rejected. No message was sent.")).not.toBeInTheDocument();
  });

  it("shows read-only when backend grants no actions, regardless of the simulated manager ID", async () => {
    readonly = true; mount();
    expect(await screen.findByText(/Read-only: no manager review permission/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve Draft" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject Draft" })).not.toBeInTheDocument();
  });

  it.each([403, 503])("makes unavailable/unauthorized review HTTP %s read-only while preserving preview", async status => {
    override = () => failed(status === 503 ? "REVIEW_AUTHORITY_UNAVAILABLE" : "REVIEW_FORBIDDEN", status);
    mount(); await screen.findByRole("alert");
    expect(screen.getByRole("article", { name: "Message draft preview" })).toHaveTextContent("Backend message a");
    expect(screen.queryByRole("button", { name: "Approve Draft" })).not.toBeInTheDocument();
  });

  it("rechecks via GET after mutation and hides success when the authoritative read fails", async () => {
    let postsComplete = false;
    override = (path, init) => {
      if (init?.method === "POST") { postsComplete = true; return reply(decided(draft(), "APPROVE_DRAFT")); }
      if (postsComplete && path.endsWith("/review")) return failed("REVIEW_VALIDATION_UNAVAILABLE", 503);
      return undefined;
    };
    mount(); await confirmApproval();
    expect(await screen.findByRole("alert")).toHaveTextContent("cannot currently be verified");
    expect(screen.queryByText("Draft approved. The message has not been sent.")).not.toBeInTheDocument();
  });

  it("clears confirmation, reason and previous result on draft/request switch", async () => {
    const view = mount(); await screen.findByText("Pending Review");
    fireEvent.change(screen.getByLabelText("Rejection reason"), { target: { value: "private reason for a" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve Draft" }));
    view.switchTo(draft("b")); await screen.findByText("Pending Review");
    expect(screen.queryByText("Confirm draft approval")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Rejection reason")).toHaveValue("");
    expect(screen.queryByText("private reason for a")).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Message draft preview" })).toHaveTextContent("Backend message b");
  });

  it("does not leak a late approval response after request switch", async () => {
    let finish!: (value: Response) => void;
    let signal: AbortSignal | null | undefined;
    override = (_path, init) => init?.method === "POST" ? new Promise(resolve => { finish = resolve; signal = init.signal; }) : undefined;
    const view = mount(); await confirmApproval(); await waitFor(() => expect(posts()).toHaveLength(1));
    view.switchTo(draft("b")); await screen.findByText("Pending Review"); expect(signal?.aborted).toBe(true);
    await act(async () => finish(reply(decided(draft(), "APPROVE_DRAFT"))));
    expect(within(region()).queryByText("Draft approved. The message has not been sent.")).not.toBeInTheDocument();
  });

  it("does not optimistically increment the cached Sent statistic", async () => {
    const { client } = mount();
    const key = ["p4-communications", auth.tenantId, auth.actorId, "summary"];
    client.setQueryDefaults(key, { gcTime: Infinity });
    client.setQueryData(key, { total: 1, drafted: 1, sent: null, needs_attention: 0 });
    await confirmApproval(); await screen.findByText("Draft approved. The message has not been sent.");
    expect(client.getQueryData(key)).toMatchObject({ sent: null });
    expect(fetchMock.mock.calls.every(([path]) => !String(path).endsWith("/send"))).toBe(true);
  });

  it("displays invalidation with original history and no approval controls", async () => {
    stored["draft-a"] = { ...decided(draft(), "APPROVE_DRAFT"), review_state: "INVALIDATED", effective_approval: false,
      invalidated_at: "2026-10-22T11:00:00Z", invalidation_code: "APPROVAL_EXPIRED", invalidation_audit_id: "audit-invalidated" };
    mount(); await screen.findByText(/This review is invalidated/);
    expect(screen.getByText("APPROVE_DRAFT")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve Draft" })).not.toBeInTheDocument();
  });

  it("rejects an approved response with another content hash instead of showing success", async () => {
    const value = decided(draft(), "APPROVE_DRAFT"); value.decision!.content_hash = "f".repeat(64);
    override = () => reply(value); mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
    expect(screen.queryByText("APPROVED")).not.toBeInTheDocument();
  });

  it("retains labeled confirmation/rejection controls at narrow viewport", async () => {
    vi.stubGlobal("innerWidth", 375); mount(); await screen.findByText("Pending Review");
    expect(screen.getByLabelText("Rejection reason")).toHaveAttribute("maxlength", "1000");
    fireEvent.click(screen.getByRole("button", { name: "Approve Draft" }));
    expect(screen.getByRole("group", { name: "Confirm draft approval" })).toBeInTheDocument();
    // Semantic interaction only; jsdom does not measure actual CSS geometry.
  });
});
