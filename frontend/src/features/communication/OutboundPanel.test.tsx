import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OutboundPanel } from "./OutboundPanel";
import { communicationKeys, getCommunicationSummary } from "./api";
import type { MessageDraftView, OutboundMessageView, OutboundStatus } from "./types";

const auth = { tenantId: "tenant_send_test", actorId: "user_manager_01" };
function draft(id = "a"): MessageDraftView {
  return { tenant_id: auth.tenantId, communication_id: `request-${id}`, draft_id: `draft-${id}`,
    reference: { source_event_id: "event-test", tenant_id: auth.tenantId, correlation_id: "corr-test", causation_id: null,
      occurred_at: "2026-10-22T10:00:00Z", commitment_id: "commitment-test", commitment_version: 2,
      plan_id: "plan-test", plan_version: 1, proposal_id: "proposal-test", proposal_version: 3 },
    order_id: "order-test", template_key: "delivery_change", template_version: 1, language: "en", channel: "MOCK_EMAIL",
    subject: "Test", body: "Exact approved test terms", approved_terms: { sku: "SKU", quantity: "1", unit: "pcs", deadline: "2030-10-26T00:00:00Z" },
    approval_evidence_refs: ["ev_core"], proposal_evidence_refs: ["ev_proposal"], recipient_identity_id: "identity-test",
    recipient_evidence_refs: ["ev_identity"], channel_evidence_refs: ["ev_consent"], content_hash: (id === "a" ? "a" : "b").repeat(64),
    validation_hash: "c".repeat(64), status: "DRAFT", send_authorized: false,
    created_at: "2026-10-22T10:00:00Z", expires_at: "2030-10-25T00:00:00Z" };
}
function outbound(value = draft(), status: OutboundStatus = "SENT"): OutboundMessageView {
  return { tenant_id: auth.tenantId, communication_id: value.communication_id, draft_id: value.draft_id,
    outbound_id: `outbound-${value.draft_id}`, approved_review_id: "review-test", content_hash: value.content_hash,
    channel: value.channel, status, provider_reference: status === "SENT" ? "mock_provider_test" : null,
    provider_confirmed: status === "SENT", created_at: "2026-10-22T10:00:00Z", updated_at: "2026-10-22T10:01:00Z",
    sent_at: status === "SENT" ? "2026-10-22T10:01:00Z" : null, failed_at: status === "FAILED" ? "2026-10-22T10:01:00Z" : null,
    last_error_code: status === "FAILED" ? "MOCK_PROVIDER_REJECTED" : status === "DELIVERY_UNKNOWN" ? "PROVIDER_TIMEOUT" : null,
    retry_allowed: false, reconciliation_required: status === "DELIVERY_UNKNOWN" || status === "QUEUED",
    attempts: [{ attempt_number: 1, status, provider_reference: null, error_code: null,
      started_at: "2026-10-22T10:00:00Z", finished_at: "2026-10-22T10:01:00Z" }] };
}
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
let history: OutboundMessageView[], allowed: boolean, outcome: OutboundStatus;
let intercept: ((path: string, init?: RequestInit) => Response | Promise<Response> | undefined) | undefined;
const fetchMock = vi.fn<typeof fetch>();
const clients: QueryClient[] = [];
beforeEach(() => {
  history = []; allowed = true; outcome = "SENT"; intercept = undefined;
  let sequence = 0;
  vi.stubGlobal("crypto", { randomUUID: () => `send_request_key_${++sequence}` });
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, init) => {
    const path = new URL(String(input)).pathname;
    const overridden = intercept?.(path, init); if (overridden) return overridden;
    const value = draft(path.includes("request-b") ? "b" : "a");
    if (path.endsWith("/summary")) return reply({ tenant_id: auth.tenantId, total: 1, drafted: 1,
      sent: history.some(row => row.status === "SENT") ? 1 : 0, needs_attention: 0,
      checked_at: "2026-10-22T10:00:00Z", unavailable_reasons: {} });
    if (path.endsWith("/outbound")) return reply(history.filter(row => row.communication_id === value.communication_id));
    if (path.endsWith("/send-eligibility")) return reply({ tenant_id: auth.tenantId, communication_id: value.communication_id,
      draft_id: value.draft_id, can_send: allowed, content_hash: allowed ? value.content_hash : null,
      approved_review_id: allowed ? "review-test" : null, expires_at: allowed ? value.expires_at : null,
      blocked_reason: allowed ? null : "SEND_AUTHORITY_UNAVAILABLE", checked_at: "2026-10-22T10:00:00Z" });
    if (path.endsWith("/send")) { const result = outbound(value, outcome); history = [result]; return reply(result); }
    throw new Error("Unexpected transport fixture endpoint");
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals(); });
function Stats() {
  const summary = useQuery({ queryKey: communicationKeys.summary(auth), queryFn: () => getCommunicationSummary(auth), retry: false });
  return <p data-testid="sent-summary">{summary.data?.sent ?? "unavailable"}</p>;
}
function mount(value: MessageDraftView | undefined = draft(), now = Date.now()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false } } });
  clients.push(client);
  const element = (next?: MessageDraftView) => <QueryClientProvider client={client}><Stats />
    <OutboundPanel key={next?.draft_id ?? "no-draft"} communicationId={next?.communication_id ?? "request-a"} draft={next} auth={auth} now={now} />
  </QueryClientProvider>;
  const view = render(element(value));
  return { switchTo: (next: MessageDraftView) => view.rerender(element(next)) };
}
const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
async function confirm() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Send Message" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Send Message" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm Send Message" }));
}
describe("Mock outbound UI", () => {
  it("requires explicit backend sending eligibility even with a prepared draft", async () => {
    allowed = false; mount(); await screen.findByText("No outbound messages.");
    expect(screen.getByRole("button", { name: "Send Message" })).toBeDisabled();
    expect(posts()).toHaveLength(0);
    expect(screen.getByTestId("sent-summary")).toHaveTextContent("0");
  });
  it("requires confirmation and supports cancel without submission", async () => {
    mount(); await waitFor(() => expect(screen.getByRole("button", { name: "Send Message" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send Message" }));
    expect(posts()).toHaveLength(0); fireEvent.click(screen.getByRole("button", { name: "Cancel send" }));
    expect(screen.queryByRole("group", { name: "Confirm mock send" })).not.toBeInTheDocument();
  });
  it("displays persisted SENT and refreshes authoritative server summary", async () => {
    mount(); await confirm();
    await screen.findByText("Mock message sent successfully.");
    expect(screen.getByText(/mock_provider_test/)).toBeInTheDocument();
    expect(screen.getByTestId("sent-summary")).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: "Send Message" })).toBeDisabled();
    expect(posts()).toHaveLength(1);
    expect(JSON.parse(posts()[0][1]!.body as string)).toEqual({ request_key: "send_request_key_1", expected_content_hash: draft().content_hash });
  });
  it.each(["FAILED", "DELIVERY_UNKNOWN", "QUEUED"] as const)("shows %s without claiming success or enabling resend", async status => {
    outcome = status; mount(); await confirm();
    await screen.findByText(status === "QUEUED" ? /MOCK_EMAIL · Sending/ : new RegExp(`MOCK_EMAIL · ${status}`));
    expect(screen.queryByText("Mock message sent successfully.")).not.toBeInTheDocument();
    expect(screen.getByTestId("sent-summary")).toHaveTextContent("0");
    expect(screen.getByRole("button", { name: "Send Message" })).toBeDisabled();
    expect(screen.getByText("Attempt history")).toBeInTheDocument();
  });
  it("guards double click and shows loading until the response arrives", async () => {
    let resolve!: (response: Response) => void;
    intercept = path => path.endsWith("/send") ? new Promise<Response>(done => { resolve = done; }) : undefined;
    mount(); await confirm();
    expect(await screen.findByText("Sending mock message…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm Send Message" }));
    expect(posts()).toHaveLength(1);
    history = [outbound()]; await act(async () => resolve(reply(history[0])));
    await screen.findByText("Mock message sent successfully.");
  });
  it("keeps the idempotency key on an explicit retry after a transport error", async () => {
    intercept = path => path.endsWith("/send") ? reply({ code: "SEND_STORAGE_UNAVAILABLE", message: "secret" }, 503) : undefined;
    mount(); await confirm(); await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Confirm Send Message" }));
    await waitFor(() => expect(posts()).toHaveLength(2));
    expect(JSON.parse(posts()[0][1]!.body as string).request_key).toBe(JSON.parse(posts()[1][1]!.body as string).request_key);
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });
  it("refuses expired backend eligibility", async () => {
    mount(draft(), Date.parse("2031-01-01T00:00:00Z")); await screen.findByText("No outbound messages.");
    expect(screen.getByRole("button", { name: "Send Message" })).toBeDisabled();
  });
  it("refuses an eligibility response bound to another tenant", async () => {
    intercept = path => path.endsWith("/send-eligibility") ? reply({ tenant_id: "other", can_send: true }) : undefined;
    mount(); await screen.findByRole("alert"); expect(screen.getByRole("button", { name: "Send Message" })).toBeDisabled();
  });
  it("does not accept an unconfirmed SENT response", async () => {
    intercept = path => path.endsWith("/send") ? reply({ ...outbound(), provider_confirmed: false }) : undefined;
    mount(); await confirm(); await screen.findByRole("alert");
    expect(screen.queryByText("Mock message sent successfully.")).not.toBeInTheDocument();
  });
  it("clears stale mutation state when switching requests during submission", async () => {
    let resolve!: (response: Response) => void;
    intercept = path => path.endsWith("/send") ? new Promise<Response>(done => { resolve = done; }) : undefined;
    const view = mount(); await confirm(); view.switchTo(draft("b"));
    await screen.findByText("No outbound messages.");
    await act(async () => resolve(reply(outbound())));
    expect(screen.queryByText("Mock message sent successfully.")).not.toBeInTheDocument();
    expect(screen.queryByText(/outbound-draft-a/)).not.toBeInTheDocument();
  });
  it("keeps historical records readable without an active preview at a narrow viewport", async () => {
    vi.stubGlobal("innerWidth", 375); history = [outbound()];
    const client = new QueryClient(); clients.push(client);
    render(<QueryClientProvider client={client}><OutboundPanel communicationId="request-a" auth={auth} now={Date.now()} /></QueryClientProvider>);
    await screen.findByText("Mock message sent successfully.");
    expect(screen.queryByRole("button", { name: "Send Message" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh sending history" })).toBeEnabled();
  });
});
