import { cleanup, fireEvent, render, screen, waitFor, within, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "../../shared/auth";
import { ApiError } from "../../shared/api";
import type { CommunicationRequestView, CommunicationSummary, MessageDraftView, MessageStatus } from "./types";
import { CommunicationCenterPage } from "./CommunicationCenterPage";
import {
  communicationKeys,
  getCommunication,
  getCommunicationSummary,
  getDraft,
  listCommunications,
} from "./api";

import {
  communicationLabel,
  errorText,
} from "./presentation";


// Synthetic API fixtures exist only in this test file. Production has no demo data.
function request(id = "a", changes: Partial<CommunicationRequestView> = {}): CommunicationRequestView {
  return {
    communication_id: `req-${id}`,
    reference: { source_event_id: `evt-${id}`, tenant_id: "tenant-test", correlation_id: `corr-${id}`,
      causation_id: null, occurred_at: "2026-10-22T10:00:00+08:00", commitment_id: `commitment-${id}`,
      commitment_version: 2, plan_id: `plan-${id}`, plan_version: 1, proposal_id: `proposal-${id}`, proposal_version: 3 },
    request_status: "READY_FOR_DRAFTING", blocking_reasons: [],
    proposed_terms: { sku: "SKU-TEST", quantity: "10.250", unit: "pcs", deadline: "2030-10-25T15:00:00+08:00", special_instructions: "Keep upright" },
    message_status: "DRAFT", approval_evidence_refs: ["approval-evidence-test"], approval_expires_at: "2030-10-24T10:00:00+08:00",
    proposal_evidence_refs: ["proposal-evidence-test"], recipient_identity_id: "identity-test", recipient_evidence_refs: ["identity-evidence-test"],
    channel: "MOCK_TELEGRAM", channel_evidence_refs: ["channel-evidence-test"], expires_at: "2030-10-24T10:00:00+08:00",
    created_by: "manager-test", created_at: "2026-10-22T10:00:00+08:00", ...changes,
  };
}
function draft(req = request(), changes: Partial<MessageDraftView> = {}): MessageDraftView {
  return { draft_id: `draft-${req.communication_id}`, tenant_id: req.reference.tenant_id, communication_id: req.communication_id,
    reference: req.reference, order_id: "order-test", template_key: "delivery_change", template_version: 1, language: "en",
    channel: "MOCK_TELEGRAM", subject: null, body: "Backend text: 10.250 pcs. Please review the proposed terms.",
    approved_terms: req.proposed_terms, approval_evidence_refs: ["approval-evidence-test"], proposal_evidence_refs: ["proposal-evidence-test"],
    recipient_identity_id: "identity-test", recipient_evidence_refs: ["identity-evidence-test"], channel_evidence_refs: ["channel-evidence-test"],
    content_hash: "a".repeat(64), validation_hash: "b".repeat(64), status: "DRAFT", send_authorized: false,
    expires_at: "2030-10-24T10:00:00+08:00", created_at: "2026-10-22T10:01:00+08:00", ...changes };
}
const auth = { tenantId: "tenant-test", actorId: "user_manager_01" };
const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const failure = (code: string, status: number) => reply({ code, message: "INTERNAL SECRET STACK TRACE", correlation_id: "test-correlation" }, status);
let records: CommunicationRequestView[];
let saved: Record<string, MessageDraftView>;
let intercept: ((url: string, init?: RequestInit) => Response | Promise<Response> | undefined) | undefined;
let summaryData: CommunicationSummary;
let summaryIntercept: ((init?: RequestInit) => Response | Promise<Response>) | undefined;
const fetchMock = vi.fn<typeof fetch>();
const clients: QueryClient[] = [];

beforeEach(() => {
  records = [request(), request("b", { request_status: "BLOCKED", blocking_reasons: ["VERIFIED_RECIPIENT_REQUIRED"],
    recipient_identity_id: null, recipient_evidence_refs: [], channel: null, channel_evidence_refs: [] })];
  saved = {}; intercept = undefined;
  summaryData = { tenant_id: auth.tenantId, total: 12, drafted: 4, sent: null, needs_attention: 2,
    checked_at: "2026-10-22T10:00:00+08:00", unavailable_reasons: { sent: "SENDING_RECORDS_UNAVAILABLE" } };
  summaryIntercept = undefined;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, init) => {
    const url = new URL(String(input));
    if (url.pathname === "/v1/communications/summary") return summaryIntercept ? summaryIntercept(init) : reply(summaryData);
    const override = intercept?.(url.pathname, init);
    if (override) return override;
    if (url.pathname === "/v1/communications") return reply(records);
    const parts = url.pathname.split("/");
    const req = records.find(value => value.communication_id === decodeURIComponent(parts[3] ?? ""));
    if (!req) return failure("COMMUNICATION_NOT_FOUND", 404);
    if (parts[4] === "prepare") {
      const body = JSON.parse(init!.body as string);
      const value = draft(req, { draft_id: `draft-${req.communication_id}-${body.language}`, language: body.language });
      saved[value.draft_id] = value;
      return reply(value);
    }
    if (parts[4] === "drafts" && parts[6] === "review") return reply({ tenant_id: req.reference.tenant_id,
      communication_id: req.communication_id, draft_id: decodeURIComponent(parts[5]), review_state: "PENDING",
      effective_approval: false, send_authorized: false, allowed_actions: [], decision: null,
      invalidated_at: null, invalidation_code: null, invalidation_audit_id: null, checked_at: "2026-10-22T10:00:00+08:00" });
    if (parts[4] === "drafts") return saved[decodeURIComponent(parts[5])] ? reply(saved[decodeURIComponent(parts[5])]) : failure("DRAFT_NOT_FOUND", 404);
    return reply(req);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function ScopeControls() {
  const context = useAuth();
  return <><button onClick={() => context.setTenantId("tenant-other")}>Switch tenant</button>
    <button onClick={() => context.setActorId("user_staff_01")}>Switch actor</button></>;
}
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><AuthProvider initialTenantId={auth.tenantId} initialActorId={auth.actorId}>
    <ScopeControls /><CommunicationCenterPage /></AuthProvider></QueryClientProvider>);
  return client;
}
const listRegion = () => screen.getByRole("region", { name: "Communication requests" });
const details = () => screen.getByRole("region", { name: "Communication details" });
async function select(id = "a") {
  const button = await within(await screen.findByRole("region", { name: "Communication requests" })).findByRole("button", { name: new RegExp(`commitment-${id}`) });
  fireEvent.click(button);
  await within(details()).findByText(`proposal-${id} · v3`);
}
async function prepare() {
  fireEvent.click(screen.getByRole("button", { name: "Prepare draft" }));
  return screen.findByRole("article", { name: "Message draft preview" });
}
const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");

describe("Communication Center", () => {
  it("loads real API response with shared auth, four server metrics and Pending instead of fabricated Drafted", async () => {
    mount();
    expect(screen.getByText("Loading communication requests…")).toBeInTheDocument();
    await screen.findByText("Select a request");
    expect(within(listRegion()).getByText("Pending")).toBeInTheDocument();
    const summary = screen.getByLabelText("Communication summary");
    expect(summary.children).toHaveLength(4);
    await waitFor(() => expect(within(summary).getByText("Total").nextSibling).toHaveTextContent("12"));
    expect(within(summary).getByText("Drafted").nextSibling).toHaveTextContent("4");
    expect(within(summary).getByText("Sent").nextSibling).toHaveTextContent("—");
    expect(within(summary).getByText("Needs Attention").nextSibling).toHaveTextContent("2");
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({ "X-Tenant-ID": auth.tenantId, "X-Actor-ID": auth.actorId });
    expect(posts()).toHaveLength(0);
  });

  it("shows an honest empty state without synthetic fallback", async () => {
    records = []; mount();
    expect(await screen.findByText("No communication requests")).toBeInTheDocument();
    expect(screen.queryByText("commitment-a")).not.toBeInTheDocument();
  });

  it("filters loaded references, display status and actual channel, and clears filters", async () => {
    mount(); await screen.findByText("Select a request");
    fireEvent.change(screen.getByLabelText("Search references"), { target: { value: "proposal-b" } });
    expect(within(listRegion()).queryByText("commitment-a")).not.toBeInTheDocument();
    expect(within(listRegion()).getByText("commitment-b")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "Drafted" } });
    expect(screen.getByText(/No search results/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "MOCK_TELEGRAM" } });
    expect(within(listRegion()).getByText("commitment-a")).toBeInTheDocument();
    expect(within(listRegion()).queryByText("commitment-b")).not.toBeInTheDocument();
    expect(screen.getByText(/filters apply to the 2 loaded requests/)).toBeInTheDocument();
  });

  it("fetches details, renders exact snapshots/evidence and explains BLOCKED without enabling prepare", async () => {
    mount(); await select("b");
    expect(screen.getByText("Recipient identity has not been verified yet.")).toBeInTheDocument();
    expect(screen.getByText("VERIFIED_RECIPIENT_REQUIRED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare draft" })).toBeDisabled();
    expect(screen.getByText("10.250 pcs")).toBeInTheDocument();
    expect(screen.getByText("Keep upright")).toBeInTheDocument();
    expect(screen.getByText("Proposed terms snapshot")).toBeInTheDocument();
    expect(screen.getByText("approval-evidence-test")).toBeInTheDocument();
    expect(screen.queryByText("Customer Accepted")).not.toBeInTheDocument();
  });

  it("tolerates missing optional fields and absent snapshot terms without crashing", async () => {
    records = [request("a", { proposed_terms: undefined, recipient_evidence_refs: undefined, channel: null,
      approval_evidence_refs: undefined, proposal_evidence_refs: undefined } as unknown as Partial<CommunicationRequestView>)];
    mount(); await select();
    expect(screen.getByText("Terms were not provided.")).toBeInTheDocument();
    expect(screen.getAllByText("Not recorded").length).toBeGreaterThan(0);
  });

  it.each(["en", "ms", "zh"] as const)("prepares %s using exact permitted body and shows backend content only after retrieval", async language => {
    mount(); await select();
    fireEvent.change(screen.getByLabelText("Draft language"), { target: { value: language } });
    const preview = await prepare();
    expect(posts()).toHaveLength(1);
    expect(posts()[0][0]).toContain("/v1/communications/req-a/prepare");
    expect(JSON.parse(posts()[0][1]!.body as string)).toEqual({ language, template_key: "delivery_change" });
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith(`/req-a/drafts/draft-req-a-${language}`))).toBe(true);
    expect(preview).toHaveTextContent("Backend text: 10.250 pcs. Please review the proposed terms.");
    expect(preview).toHaveTextContent("Draft Only — Not Sent");
    expect(preview).toHaveTextContent("DRAFT");
    expect(await screen.findByRole("region", { name: "Manager Review" })).toBeInTheDocument();
    expect(within(preview).queryByRole("button", { name: /send|approve/i })).not.toBeInTheDocument();
    expect(within(listRegion()).getByText("Drafted")).toBeInTheDocument();
  });

  it("shows email subject and renders backend HTML as literal text", async () => {
    intercept = (url) => url.endsWith("/drafts/draft-req-a-en") ? reply(draft(request(), {
      draft_id: "draft-req-a-en", channel: "MOCK_EMAIL", subject: "Backend email subject", body: "<script>unsafe()</script>" })) : undefined;
    mount(); await select(); const preview = await prepare();
    expect(preview).toHaveTextContent("Backend email subject");
    expect(preview).toHaveTextContent("<script>unsafe()</script>");
    expect(preview.querySelector("script")).toBeNull();
  });

  it("guards duplicate clicks while prepare is pending", async () => {
    let finish!: (value: Response) => void;
    intercept = (url) => url.endsWith("/prepare") ? new Promise(resolve => { finish = resolve; }) : undefined;
    mount(); await select(); const button = screen.getByRole("button", { name: "Prepare draft" });
    fireEvent.click(button); fireEvent.click(button); fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Preparing draft…" })).toBeDisabled();
    await waitFor(() => expect(posts()).toHaveLength(1));
    const value = draft(); saved[value.draft_id] = value;
    await act(async () => finish(reply(value)));
    await screen.findByRole("article", { name: "Message draft preview" });
  });

  it("does not display a prepared body when READ_DRAFT revalidation fails", async () => {
    intercept = url => url.includes("/drafts/") ? failure("APPROVAL_REVOKED", 403) : undefined;
    mount(); await select(); fireEvent.click(screen.getByRole("button", { name: "Prepare draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A current trusted approval is required");
    expect(screen.queryByRole("article", { name: "Message draft preview" })).not.toBeInTheDocument();
    expect(within(listRegion()).queryByText("Drafted")).not.toBeInTheDocument();
  });

  it.each([
    [409, "STALE_PROPOSAL_VERSION", "proposal version is no longer current"],
    [503, "DRAFT_REVALIDATION_UNAVAILABLE", "Draft validation is not connected yet"],
    [403, "FORBIDDEN", "do not have permission"],
    [401, "UNAUTHORIZED", "session is not authorized"],
    [503, "DRAFT_PERSISTENCE_UNAVAILABLE", "Draft storage is unavailable"],
  ])("handles preparation HTTP %s / %s without fake success", async (status, code, expected) => {
    intercept = url => url.endsWith("/prepare") ? failure(String(code), Number(status)) : undefined;
    mount(); await select(); fireEvent.click(screen.getByRole("button", { name: "Prepare draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(String(expected));
    expect(screen.queryByText(/INTERNAL SECRET/)).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Message draft preview" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry preparation" })).toBeInTheDocument();
  });

  it("recovers after a failed preparation without bypassing the API", async () => {
    intercept = url => url.endsWith("/prepare") ? failure("DRAFT_REVALIDATION_UNAVAILABLE", 503) : undefined;
    mount(); await select(); fireEvent.click(screen.getByRole("button", { name: "Prepare draft" }));
    await screen.findByRole("alert"); intercept = undefined;
    fireEvent.click(screen.getByRole("button", { name: "Retry preparation" }));
    await screen.findByRole("article", { name: "Message draft preview" });
    expect(posts()).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reopens known drafts via GET, switches languages and never prepares on selection", async () => {
    mount(); await select(); await prepare();
    fireEvent.change(screen.getByLabelText("Draft language"), { target: { value: "zh" } });
    await prepare();
    fireEvent.change(screen.getByLabelText("Known drafts"), { target: { value: "draft-req-a-en" } });
    expect(await screen.findByRole("article", { name: "Message draft preview" })).toHaveTextContent("English");
    await select("b");
    expect(screen.queryByText(/Backend text/)).not.toBeInTheDocument();
    await select("a");
    await screen.findByRole("article", { name: "Message draft preview" });
    expect(posts()).toHaveLength(2);
  });

  it("loads an existing draft by ID without inventing a list/latest endpoint", async () => {
    saved["external-draft-id"] = draft(request(), { draft_id: "external-draft-id" });
    mount(); await select();
    fireEvent.change(screen.getByLabelText("Draft ID"), { target: { value: "external-draft-id" } });
    fireEvent.click(screen.getByRole("button", { name: "Load draft" }));
    await screen.findByRole("article", { name: "Message draft preview" });
    expect(posts()).toHaveLength(0);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/latest"))).toBe(false);
    expect(screen.getByText(/Full draft history is not available yet/)).toBeInTheDocument();
  });

  it("hides a previously visible draft when revalidation fails", async () => {
    mount(); await select(); await prepare();
    intercept = url => url.includes("/drafts/") ? failure("STALE_PROPOSAL_VERSION", 409) : undefined;
    fireEvent.click(screen.getByRole("button", { name: "Recheck draft" }));
    expect(screen.queryByText(/Backend text/)).not.toBeInTheDocument();
    await screen.findByRole("alert");
    expect(screen.queryByRole("article", { name: "Message draft preview" })).not.toBeInTheDocument();
    expect(within(listRegion()).getAllByText("Blocked").length).toBe(2);
  });

  it("does not show an already expired saved draft as Drafted", async () => {
    saved.expired = draft(request(), { draft_id: "expired", expires_at: "2020-01-01T00:00:00Z" });
    mount(); await select();
    fireEvent.change(screen.getByLabelText("Draft ID"), { target: { value: "expired" } });
    fireEvent.click(screen.getByRole("button", { name: "Load draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This draft has expired");
    expect(screen.queryByText(/Backend text/)).not.toBeInTheDocument();
  });

  it("hides a draft when its expiry is reached while the page remains open", async () => {
    mount(); await select(); await prepare();
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2031-01-01T00:00:00Z"));
    await waitFor(() => expect(screen.queryByText(/Backend text/)).not.toBeInTheDocument(), { timeout: 2000 });
    expect(await screen.findByRole("alert")).toHaveTextContent("This draft has expired");
    expect(within(listRegion()).getAllByText("Blocked")).toHaveLength(2);
  });

  it("hides cached preview while a reopened draft is being revalidated", async () => {
    mount(); await select(); await prepare(); await select("b");
    let finish!: (value: Response) => void;
    intercept = url => url.includes("/drafts/") ? new Promise(resolve => { finish = resolve; }) : undefined;
    await select("a");
    expect(await screen.findByText("Checking saved draft…")).toBeInTheDocument();
    expect(screen.queryByText(/Backend text/)).not.toBeInTheDocument();
    await act(async () => finish(failure("APPROVAL_REVOKED", 403)));
    expect(await screen.findByRole("alert")).toHaveTextContent("current trusted approval");
  });

  it("does not show late Prepare results after switching requests", async () => {
    let finish!: (value: Response) => void;
    let signal: AbortSignal | null | undefined;
    intercept = (url, init) => url.endsWith("/prepare") ? new Promise(resolve => { finish = resolve; signal = init?.signal; }) : undefined;
    mount(); await select(); fireEvent.click(screen.getByRole("button", { name: "Prepare draft" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    await select("b"); expect(signal?.aborted).toBe(true);
    await act(async () => finish(reply(draft())));
    expect(screen.queryByText(/Backend text/)).not.toBeInTheDocument();
    expect(within(details()).getByText("proposal-b · v3")).toBeInTheDocument();
  });

  it("ignores a slow detail result after a faster new selection", async () => {
    let finish!: (value: Response) => void;
    intercept = url => url === "/v1/communications/req-a" ? new Promise(resolve => { finish = resolve; }) : undefined;
    mount(); await screen.findByText("Select a request");
    fireEvent.click(within(listRegion()).getByRole("button", { name: /commitment-a/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Loading communication details");
    await select("b"); await act(async () => finish(reply(request())));
    expect(within(details()).queryByText("proposal-a · v3")).not.toBeInTheDocument();
    expect(within(details()).getByText("proposal-b · v3")).toBeInTheDocument();
  });

  it.each(["Switch tenant", "Switch actor"])("isolates selection, known drafts and cache on %s", async button => {
    mount(); await select(); await prepare();
    intercept = url => url === "/v1/communications" ? reply([]) : undefined;
    fireEvent.click(screen.getByRole("button", { name: button }));
    await screen.findByText("No communication requests");
    expect(screen.queryByText(/Backend text/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Known drafts")).not.toBeInTheDocument();
    const last = fetchMock.mock.calls.at(-1)![1]?.headers;
    expect(last).toMatchObject(button === "Switch tenant" ? { "X-Tenant-ID": "tenant-other" } : { "X-Actor-ID": "user_staff_01" });
  });

  it.each([401, 403, 404, 503, 500])("shows list HTTP %s errors and Retry without exposing internals", async status => {
    intercept = () => failure("TEST_ERROR", status);
    mount(); expect(await screen.findByRole("alert")).not.toHaveTextContent("INTERNAL SECRET");
    intercept = undefined; fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Select a request");
  });

  it("shows a network error and recovers on Retry", async () => {
    intercept = () => Promise.reject(new TypeError("fetch failed with private hostname"));
    mount(); expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the server");
    intercept = undefined; fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Select a request");
  });

  it("shows detail not found without displaying cached data", async () => {
    intercept = url => url.endsWith("/req-a") ? failure("COMMUNICATION_NOT_FOUND", 404) : undefined;
    mount(); await screen.findByText("Select a request");
    fireEvent.click(within(listRegion()).getByRole("button", { name: /commitment-a/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Communication request not found");
    expect(screen.queryByRole("button", { name: "Prepare draft" })).not.toBeInTheDocument();
  });

  it("retains semantic labels and button selection at a narrow viewport", async () => {
    vi.stubGlobal("innerWidth", 375); mount(); await select();
    expect(within(listRegion()).getByRole("button", { name: /commitment-a/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Draft language")).toBeInTheDocument();
    // jsdom verifies accessible interaction only; it cannot measure CSS layout.
    expect(screen.getByRole("button", { name: "Prepare draft" })).toHaveAttribute("class", "btn btn-primary");
  });
});

describe("Display labels preserve backend meaning", () => {
  it.each([
    ["DRAFT", false, "Pending"], ["DRAFT", true, "Drafted"], ["VALIDATED", false, "Pending"],
    ["PENDING_APPROVAL", false, "Pending"], ["QUEUED", false, "Sending"], ["SUBMITTED", false, "Sending"],
    ["SENT", false, "Sent"], ["DELIVERED", false, "Sent"], ["DELIVERY_UNKNOWN", false, "Blocked"], ["FAILED", false, "Blocked"],
  ])("maps %s with verified draft %s to %s", (state, verified, expected) => {
    expect(communicationLabel("READY_FOR_DRAFTING", state as MessageStatus, Boolean(verified))).toBe(expected);
  });
  it("does not override BLOCKED with a draft", () => {
    expect(communicationLabel("BLOCKED", "DRAFT", true)).toBe("Blocked");
  });
  it("keeps unknown delivery distinct from delivered, and errors exclude raw server messages", () => {
    expect(errorText(new ApiError(409, "STALE_PROPOSAL_VERSION", "secret"), "draft")).not.toContain("secret");
    expect(communicationLabel("READY_FOR_DRAFTING", "DELIVERY_UNKNOWN")).not.toBe("Sent");
  });
});

describe("API boundaries", () => {
  it.each(["SENT", "ACCEPTED", "FULFILLED"])("rejects %s in today's DRAFT-only intake contract rather than asserting a new lifecycle fact", async state => {
    intercept = () => reply({ ...request(), message_status: state });
    await expect(getCommunication("req-a", auth)).rejects.toMatchObject({ code: "UNSUPPORTED_RESPONSE" });
  });
  it.each([{}, { items: [] }])("rejects unsupported list/pagination envelopes instead of assuming a total", async payload => {
    intercept = () => reply(payload);
    await expect(listCommunications(auth)).rejects.toMatchObject({ code: "UNSUPPORTED_RESPONSE" });
  });
  it("rejects cross-tenant list responses", async () => {
    records = [request("a", { reference: { ...request().reference, tenant_id: "tenant-wrong" } })];
    await expect(listCommunications(auth)).rejects.toMatchObject({ code: "RESPONSE_SCOPE_MISMATCH" });
  });
  it("rejects a detail for another request", async () => {
    intercept = () => reply(request("b"));
    await expect(getCommunication("req-a", auth)).rejects.toMatchObject({ code: "RESPONSE_SCOPE_MISMATCH" });
  });
  it.each(["tenant", "request", "version", "draftId", "sendFlag"])("rejects a draft with mismatched %s", async field => {
    const value = draft();
    if (field === "tenant") value.tenant_id = "other";
    if (field === "request") value.communication_id = "req-b";
    if (field === "version") value.reference = { ...value.reference, proposal_version: 99 };
    if (field === "draftId") value.draft_id = "other";
    if (field === "sendFlag") (value as unknown as { send_authorized: boolean }).send_authorized = true;
    intercept = () => reply(value);
    await expect(getDraft(request(), "draft-req-a", auth)).rejects.toBeInstanceOf(ApiError);
  });
  it("scopes every query key by tenant AND actor", () => {
    expect(communicationKeys.draft(auth, "req-a", "draft-a")).not.toEqual(communicationKeys.draft({ ...auth, tenantId: "other" }, "req-a", "draft-a"));
    expect(communicationKeys.detail(auth, "req-a")).not.toEqual(communicationKeys.detail({ ...auth, actorId: "other" }, "req-a"));
  });
  it("encodes draft IDs as a single path segment", async () => {
    const value = draft(request(), { draft_id: "draft/id?test" }); intercept = () => reply(value);
    await getDraft(request(), value.draft_id, auth);
    expect(fetchMock.mock.calls.at(-1)![0]).toContain("/drafts/draft%2Fid%3Ftest");
  });
});

const metric = (title: string) => within(screen.getByLabelText("Communication summary")).getByText(title).nextSibling;
const statistics = () => screen.getByRole("region", { name: "Dashboard statistics" });

describe("Database dashboard summary", () => {
  it("uses tenant-wide database numbers before any draft is opened and ignores filters/session cache", async () => {
    mount(); await screen.findByText("Select a request");
    await waitFor(() => expect(metric("Drafted")).toHaveTextContent("4"));
    expect(metric("Total")).toHaveTextContent("12");
    fireEvent.change(screen.getByLabelText("Search references"), { target: { value: "not-a-reference" } });
    expect(screen.getByText(/No search results/)).toBeInTheDocument();
    expect(metric("Drafted")).toHaveTextContent("4");
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await select(); await prepare();
    await waitFor(() => expect(screen.getByLabelText("Communication summary")).toHaveAttribute("aria-busy", "false"));
    expect(metric("Drafted")).toHaveTextContent("4"); // no optimistic session-derived +1
  });

  it("shows actual zero counts and unavailable counts differently", async () => {
    summaryData = { ...summaryData, total: 0, drafted: null, sent: null, needs_attention: 0,
      unavailable_reasons: { drafted: "DRAFT_REVALIDATION_UNAVAILABLE", sent: "SENDING_RECORDS_UNAVAILABLE" } };
    mount(); await screen.findByText("Select a request");
    await waitFor(() => expect(metric("Total")).toHaveTextContent("0"));
    expect(metric("Needs Attention")).toHaveTextContent("0");
    expect(metric("Drafted")).toHaveTextContent("—"); expect(metric("Sent")).toHaveTextContent("—");
    expect(within(statistics()).getByText(/current drafts could not be reliably verified/)).toBeInTheDocument();
    expect(within(statistics()).getByText(/verified sending records are not connected/)).toBeInTheDocument();
  });

  it("displays a reliable Drafted zero when the backend actually returns zero", async () => {
    summaryData.drafted = 0; mount();
    await waitFor(() => expect(metric("Drafted")).toHaveTextContent("0"));
    expect(within(statistics()).queryByText(/current drafts could not/)).not.toBeInTheDocument();
  });

  it("loads statistics independently without blocking the list", async () => {
    let finish!: (value: Response) => void;
    summaryIntercept = () => new Promise(resolve => { finish = resolve; });
    mount(); await screen.findByText("Select a request");
    expect(within(statistics()).getByRole("status")).toHaveTextContent("Loading dashboard statistics");
    for (const title of ["Total", "Drafted", "Sent", "Needs Attention"]) expect(metric(title)).toHaveTextContent("—");
    expect(within(listRegion()).getByText("commitment-a")).toBeInTheDocument();
    await act(async () => finish(reply(summaryData)));
    await waitFor(() => expect(metric("Total")).toHaveTextContent("12"));
  });

  it.each([401, 403, 404, 503, 500])("handles summary HTTP %s alone and retries only statistics", async status => {
    summaryIntercept = () => failure("COMMUNICATION_SUMMARY_UNAVAILABLE", status);
    mount(); await screen.findByText("Select a request");
    expect(await within(statistics()).findByRole("alert")).not.toHaveTextContent("INTERNAL SECRET");
    expect(metric("Total")).toHaveTextContent("—");
    const listCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/v1/communications")).length;
    summaryIntercept = undefined;
    fireEvent.click(within(statistics()).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(metric("Total")).toHaveTextContent("12"));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/v1/communications"))).toHaveLength(listCalls);
  });

  it("keeps a verified preview available when only statistics fail, hiding cached numbers", async () => {
    const client = mount(); await select(); await prepare();
    summaryIntercept = () => Promise.reject(new TypeError("private DNS error"));
    await act(async () => { await client.invalidateQueries({ queryKey: communicationKeys.summary(auth) }); });
    expect(await within(statistics()).findByRole("alert")).toHaveTextContent("Cannot reach the server");
    expect(metric("Drafted")).toHaveTextContent("—");
    expect(screen.getByRole("article", { name: "Message draft preview" })).toHaveTextContent("Backend text");
    expect(within(listRegion()).getByText("commitment-a")).toBeInTheDocument();
  });

  it("refetches server statistics after Prepare without incrementing locally", async () => {
    mount(); await select();
    const before = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/summary")).length;
    summaryData = { ...summaryData, drafted: 5 };
    await prepare();
    await waitFor(() => expect(metric("Drafted")).toHaveTextContent("5"));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/summary")).length).toBeGreaterThan(before);
  });

  it.each(["Switch tenant", "Switch actor"])("hides previous summary immediately during %s", async action => {
    mount(); await waitFor(() => expect(metric("Drafted")).toHaveTextContent("4"));
    let finish!: (value: Response) => void;
    summaryIntercept = () => new Promise(resolve => { finish = resolve; });
    intercept = url => url === "/v1/communications" ? reply([]) : undefined;
    fireEvent.click(screen.getByRole("button", { name: action }));
    await screen.findByText("No communication requests");
    expect(metric("Drafted")).toHaveTextContent("—");
    const tenant = action === "Switch tenant" ? "tenant-other" : auth.tenantId;
    await act(async () => finish(reply({ ...summaryData, tenant_id: tenant, total: 0, drafted: 0, needs_attention: 0 })));
    await waitFor(() => expect(metric("Drafted")).toHaveTextContent("0"));
  });

  it("rejects summary responses for another tenant", async () => {
    summaryData.tenant_id = "wrong-tenant";
    await expect(getCommunicationSummary(auth)).rejects.toMatchObject({ code: "RESPONSE_SCOPE_MISMATCH" });
  });

  it.each([{ total: -1 }, { drafted: 99 }, { drafted: undefined }, { needs_attention: -1 }, { sent: "2" }])(
    "rejects malformed summary counts %s", async change => {
      summaryIntercept = () => reply({ ...summaryData, ...change });
      await expect(getCommunicationSummary(auth)).rejects.toMatchObject({ code: "UNSUPPORTED_RESPONSE" });
    });

  it("isolates summary query keys by tenant and actor", () => {
    expect(communicationKeys.summary(auth)).not.toEqual(communicationKeys.summary({ ...auth, tenantId: "other" }));
    expect(communicationKeys.summary(auth)).not.toEqual(communicationKeys.summary({ ...auth, actorId: "other" }));
  });
});
