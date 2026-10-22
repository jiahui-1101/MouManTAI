import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import { AuthProvider, useAuth } from "../../shared/auth";
import { FollowUpQueuePage } from "./FollowUpQueuePage";
import { confirmationKeys, listConfirmations } from "./confirmationApi";
import type { ConfirmationAttemptView, ConfirmationView } from "./confirmationTypes";
import { classifyFollowUp, defaultQueueFilters, EXPIRING_WINDOW_MS, followUpCounts, visibleFollowUps } from "./followUp";

// Test-only transport records. Production uses the existing GET API, no demo feed.
const auth = { tenantId: "tenant-follow-up-test", actorId: "user_manager_01" };
const NOW = Date.parse("2026-10-22T12:00:00Z");
const hours = (value: number) => new Date(NOW + value * 3600_000).toISOString();
function confirmation(id = "a", changes: Partial<ConfirmationView> = {}): ConfirmationView {
  return { confirmation_id: `conf-${id}`, tenant_id: auth.tenantId, communication_id: `comm-${id}`,
    outbound_id: `outbound-${id}`, customer_id: `customer-${id}`, channel: "MOCK_TELEGRAM",
    reference: { tenant_id: auth.tenantId, commitment_id: `commitment-${id}`, commitment_version: 1,
      proposal_id: `proposal-${id}`, proposal_version: 2, plan_id: `plan-${id}`, plan_version: 1,
      source_event_id: `event-${id}`, correlation_id: `corr-${id}`, causation_id: null, occurred_at: hours(-4) },
    terms_digest: "a".repeat(64), content_hash: "b".repeat(64), state: "AWAITING_RESPONSE", expires_at: hours(48),
    created_at: hours(-2), consumed_at: null, revoked_at: null, blocked_reasons: [], core_transition_applied: false,
    evidence_scope: "P4_EVIDENCE_ONLY", integration_mode: "SYNTHETIC_ONLY", ...changes };
}
function attempt(id = "a", changes: Partial<ConfirmationAttemptView> = {}): ConfirmationAttemptView {
  return { attempt_id: `attempt-${id}`, confirmation_id: `conf-${id}`, inbound_message_id: `p1-message-${id}`,
    intent: "UNKNOWN", reason: "AMBIGUOUS_OR_UNBOUND_RESPONSE", evidence_refs: [`p1:evidence:${id}`],
    proposed_changes: null, received_at: hours(-1), ...changes };
}
const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const failure = (status: number, code: string) => reply({ code, message: "PRIVATE ERROR TOKEN AND STACK", correlation_id: "test-error-ref" }, status);
const fetchMock = vi.fn<typeof fetch>();
const clients: QueryClient[] = [];
let records: unknown;
let history: Record<string, unknown>;
let intercept: ((url: URL, init?: RequestInit) => Response | Promise<Response> | undefined) | undefined;
beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(NOW);
  records = [confirmation()]; history = {}; intercept = undefined;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const override = intercept?.(url, init); if (override) return override;
    if (url.pathname === "/v1/confirmations") return reply(records);
    if (url.pathname.endsWith("/attempts")) return reply(history[decodeURIComponent(url.pathname.split("/")[3])] ?? []);
    if (url.pathname === "/v1/confirmations/conf-a") return reply(confirmation());
    if (url.pathname.endsWith("/runtime-capabilities")) return reply({ tenant_id: auth.tenantId, mode: "CLOSED",
      label: "Trusted authority unavailable", can_record_preferences: false, can_revoke_preferences: false,
      integrated_demo_ready: false, blockers: ["PRODUCTION_AUTH_UNAVAILABLE"] });
    if (url.pathname === "/v1/communications") return reply([]);
    if (url.pathname === "/v1/communications/summary") return reply({ tenant_id: auth.tenantId, total: 0,
      drafted: 0, sent: 0, needs_attention: 0, checked_at: hours(0), unavailable_reasons: {} });
    return failure(404, "NOT_FOUND");
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals(); vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});
function client() { const value = new QueryClient({ defaultOptions: {
  queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false }, mutations: { retry: false },
} }); clients.push(value); return value; }
function mountApp(path = "/communications/follow-ups") {
  window.history.replaceState({}, "", path);
  const queryClient = client(); render(<App queryClient={queryClient} initialTenantId={auth.tenantId} initialActorId={auth.actorId} />);
  return queryClient;
}
function ScopeControls() {
  const context = useAuth(); const navigate = useNavigate();
  return <><button onClick={() => context.setTenantId("tenant-other")}>Switch tenant</button>
    <button onClick={() => context.setActorId("user_staff_01")}>Switch actor</button>
    <button onClick={() => navigate("/elsewhere")}>Leave queue</button></>;
}
function mountScope() {
  const queryClient = client();
  render(<QueryClientProvider client={queryClient}><AuthProvider initialTenantId={auth.tenantId} initialActorId={auth.actorId}>
    <MemoryRouter initialEntries={["/communications/follow-ups"]}><ScopeControls /><Routes>
      <Route path="/communications/follow-ups" element={<FollowUpQueuePage />} /><Route path="/elsewhere" element={<p>Elsewhere</p>} />
    </Routes></MemoryRouter></AuthProvider></QueryClientProvider>);
  return queryClient;
}
const items = () => screen.getByRole("list", { name: "Confirmation follow-ups" });
const item = (id = "a") => screen.getByRole("article", { name: `Confirmation conf-${id}` });
const loaded = () => screen.findByRole("list", { name: "Confirmation follow-ups" });
const ids = () => within(items()).getAllByRole("article").filter(value => value.hasAttribute("aria-label"))
  .map(value => value.getAttribute("aria-label"));
const listCalls = () => fetchMock.mock.calls.filter(([url]) => new URL(String(url)).pathname === "/v1/confirmations");

describe("Non-authoritative follow-up classification", () => {
  it.each([
    ["AWAITING_RESPONSE", 48, "awaiting"], ["AWAITING_RESPONSE", 24, "expiring"], ["AWAITING_RESPONSE", .1, "expiring"],
    ["AWAITING_RESPONSE", 0, "expired"], ["AWAITING_RESPONSE", -1, "expired"], ["EXPIRED", 48, "expired"],
    ["CLARIFICATION_REQUIRED", 48, "clarification"], ["UNRESOLVED", 48, "unresolved"], ["UNRESOLVED", -1, "expired"],
    ["SUPERSEDED", 48, "manual"],
  ] as const)("classifies %s expiring in %s hours as UI %s without changing backend state", (state, remaining, expected) => {
    const value = confirmation("a", { state, expires_at: hours(remaining) }); const before = JSON.stringify(value);
    expect(classifyFollowUp(value, NOW)).toBe(expected); expect(JSON.stringify(value)).toBe(before);
  });
  it.each(["ACCEPTED", "REJECTED", "COUNTEROFFER_RECEIVED"] as const)("does not reopen historical terminal %s just because expiry passed", state => {
    expect(classifyFollowUp(confirmation("a", { state, consumed_at: hours(-1), expires_at: hours(-.5) }), NOW)).toBe("terminal");
    expect(classifyFollowUp(confirmation("a", { state, consumed_at: null }), NOW)).toBe("unknown");
  });
  it("gives reported revocation/staleness priority and fails closed on unknown restrictions", () => {
    expect(classifyFollowUp(confirmation("a", { revoked_at: hours(-1) }), NOW)).toBe("manual");
    expect(classifyFollowUp(confirmation("a", { blocked_reasons: ["CONFIRMATION_PROPOSAL_CHANGED"] }), NOW)).toBe("manual");
    expect(classifyFollowUp(confirmation("a", { blocked_reasons: ["UNRECOGNIZED_RESTRICTION"] }), NOW)).toBe("unknown");
    expect(classifyFollowUp(confirmation("a", { state: "UNKNOWN_BACKEND_STATE" as ConfirmationView["state"] }), NOW)).toBe("unknown");
    expect(classifyFollowUp(confirmation("a", { expires_at: "invalid" }), NOW)).toBe("unknown");
    expect(classifyFollowUp({ ...confirmation(), revoked_at: undefined } as unknown as ConfirmationView, NOW)).toBe("unknown");
    expect(classifyFollowUp({ ...confirmation(), state: "ACCEPTED", consumed_at: undefined } as unknown as ConfirmationView, NOW)).toBe("unknown");
  });
  it("uses an explicit 24 hour boundary and does not infer a real escalation", () => {
    expect(EXPIRING_WINDOW_MS).toBe(86400_000);
    expect(classifyFollowUp(confirmation("a", { expires_at: new Date(NOW + EXPIRING_WINDOW_MS + 1).toISOString() }), NOW)).toBe("awaiting");
  });
  it("computes loaded UI statistics independently of filters and without conflating reply with fulfilment", () => {
    const data = [confirmation(), confirmation("b", { expires_at: hours(2) }),
      confirmation("c", { state: "ACCEPTED", consumed_at: hours(-1), expires_at: hours(-.5) })];
    expect(followUpCounts(data, NOW)).toEqual({ total: 3, awaiting: 2, attention: 1, expiring: 1, terminal: 1 });
  });
  it("sorts stably without mutating the input and handles missing numeric sort keys safely", () => {
    const data = [confirmation("b"), confirmation("a"), confirmation("invalid", { expires_at: "invalid" })];
    expect(visibleFollowUps(data, defaultQueueFilters, NOW).map(value => value.confirmation_id)).toEqual(["conf-a", "conf-b", "conf-invalid"]);
    expect(data.map(value => value.confirmation_id)).toEqual(["conf-b", "conf-a", "conf-invalid"]);
  });
});

describe("Real App follow-up queue", () => {
  it("loads the actual list once with existing headers, real IDs/version and no history fan-out", async () => {
    mountApp(); await loaded();
    expect(screen.getByRole("heading", { name: "Follow-Up Queue" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(item()).toHaveTextContent("proposal-a"); expect(item()).toHaveTextContent("Proposal version2");
    expect(item()).toHaveTextContent("AWAITING_RESPONSE"); expect(item()).toHaveTextContent("Awaiting Response");
    expect(item()).toHaveTextContent("customer-a"); expect(item()).toHaveTextContent("Mock TELEGRAM");
    expect(screen.getByText(/P4 Evidence Only/)).toBeInTheDocument();
    expect(screen.getByText(/browser display hints/)).toBeInTheDocument();
    expect(screen.getByText(/browser receipt time/)).toBeInTheDocument();
    expect(listCalls()).toHaveLength(1); expect(String(listCalls()[0][0])).toMatch(/\/v1\/confirmations$/);
    expect(listCalls()[0][1]?.headers).toMatchObject({ "X-Tenant-ID": auth.tenantId, "X-Actor-ID": auth.actorId });
    expect(fetchMock.mock.calls.every(([url, init]) => !String(url).includes("/attempts") && (!init?.method || init.method === "GET"))).toBe(true);
    expect(screen.queryByRole("button", { name: /^accept|^reject|send reminder|escalate/i })).not.toBeInTheDocument();
  });
  it("shows loading without stale metrics, then an honest API empty state", async () => {
    let release!: (value: Response) => void;
    intercept = url => url.pathname === "/v1/confirmations" ? new Promise(resolve => { release = resolve; }) : undefined;
    mountApp(); expect(screen.getByText("Loading confirmation queue…")).toBeInTheDocument();
    expect(screen.getByLabelText("Loaded confirmation statistics")).toHaveTextContent("—");
    expect(screen.getByText("Last refreshed: Unavailable")).toBeInTheDocument();
    await act(async () => release(reply([])));
    expect(await screen.findByRole("heading", { name: "No confirmations available" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Confirmation follow-ups" })).not.toBeInTheDocument();
  });
  it("filters by real backend state and attention, searches IDs, resets and never filters on the server", async () => {
    records = [confirmation(), confirmation("b", { state: "UNRESOLVED" }), confirmation("c", { expires_at: hours(2) })];
    mountApp(); await loaded();
    fireEvent.change(screen.getByLabelText("Backend state"), { target: { value: "UNRESOLVED" } });
    expect(ids()).toEqual(["Confirmation conf-b"]);
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    fireEvent.change(screen.getByLabelText("Attention category"), { target: { value: "expiring" } });
    expect(ids()).toEqual(["Confirmation conf-c"]);
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    fireEvent.change(screen.getByLabelText("Search IDs"), { target: { value: " COMM-B " } });
    expect(ids()).toEqual(["Confirmation conf-b"]);
    fireEvent.change(screen.getByLabelText("Search IDs"), { target: { value: "no-matching-id" } });
    expect(screen.getByRole("heading", { name: "No filter results" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(within(items()).getAllByRole("link", { name: "View Confirmation" })).toHaveLength(3);
    expect(listCalls()).toHaveLength(1);
    expect(within(screen.getByLabelText("Loaded confirmation statistics")).getByText("Total Confirmations").nextSibling).toHaveTextContent("3");
  });
  it("sorts expiration, creation and numerical proposal version in both directions", async () => {
    records = [confirmation("a", { expires_at: hours(5), created_at: hours(-4), reference: { ...confirmation().reference, proposal_version: 2 } }),
      confirmation("b", { expires_at: hours(3), created_at: hours(-2), reference: { ...confirmation("b").reference, proposal_version: 10 } })];
    mountApp(); await loaded(); expect(ids()).toEqual(["Confirmation conf-b", "Confirmation conf-a"]);
    fireEvent.change(screen.getByLabelText("Sort direction"), { target: { value: "desc" } }); expect(ids()).toEqual(["Confirmation conf-a", "Confirmation conf-b"]);
    fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "created" } }); expect(ids()).toEqual(["Confirmation conf-b", "Confirmation conf-a"]);
    fireEvent.change(screen.getByLabelText("Sort direction"), { target: { value: "asc" } }); expect(ids()).toEqual(["Confirmation conf-a", "Confirmation conf-b"]);
    fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "proposal" } }); expect(ids()).toEqual(["Confirmation conf-a", "Confirmation conf-b"]);
    fireEvent.change(screen.getByLabelText("Sort direction"), { target: { value: "desc" } }); expect(ids()).toEqual(["Confirmation conf-b", "Confirmation conf-a"]);
  });
  it("keeps D-037 old acceptance separate from a newer awaiting version and fulfilment", async () => {
    records = [confirmation("old", { state: "ACCEPTED", consumed_at: hours(-1), expires_at: hours(-.5), reference: { ...confirmation().reference, proposal_id: "proposal-v2", proposal_version: 2 } }),
      confirmation("new", { reference: { ...confirmation().reference, proposal_id: "proposal-v3", proposal_version: 3 } })];
    mountApp(); await loaded();
    expect(item("old")).toHaveTextContent("Acceptance recorded"); expect(item("old")).toHaveTextContent("Terminal — No Pending Follow-Up");
    expect(item("new")).toHaveTextContent("AWAITING_RESPONSE"); expect(item("new")).not.toHaveTextContent("Acceptance recorded");
    expect(item("old")).toHaveTextContent("Core fulfilmentUnavailable"); expect(item("old")).not.toHaveTextContent("FULFILLED");
    expect(item("new").querySelector(".status-badge")).not.toHaveClass("badge-success");
  });
  it("shows revoked, stale, clarification and unknown restrictions without authoritatively changing state", async () => {
    records = [confirmation("revoked", { revoked_at: hours(-1), blocked_reasons: ["CONFIRMATION_REVOKED"] }),
      confirmation("stale", { blocked_reasons: ["CONFIRMATION_PROPOSAL_CHANGED"] }),
      confirmation("clarification", { state: "CLARIFICATION_REQUIRED" }),
      confirmation("unknown", { blocked_reasons: ["NEW_RESTRICTION"] })];
    mountApp(); await loaded();
    expect(item("revoked")).toHaveTextContent("Revoked / Stale — Manual Review"); expect(item("stale")).toHaveTextContent("CONFIRMATION_PROPOSAL_CHANGED");
    expect(item("clarification")).toHaveTextContent("Clarification Required"); expect(item("unknown")).toHaveTextContent("Needs Review / Unknown");
    expect(item("revoked")).toHaveTextContent("AWAITING_RESPONSE");
  });

  it.each([
    [400, "BAD_REQUEST", "request was rejected"], [403, "FORBIDDEN", "do not have permission"],
    [404, "NOT_FOUND", "confirmation list or its route is unavailable"], [409, "CONFLICT", "conflicts with the requested record"],
    [409, "STALE_PROPOSAL_VERSION", "changed or stale proposal"], [503, "CONFIRMATION_AUTHORITY_UNAVAILABLE", "authority or storage is unavailable"],
    [503, "CONFIRMATION_PROCESSOR_AUTH_UNAVAILABLE", "Verified customer-response processing is not yet connected."],
  ])("handles %s %s with no fake success and a real retry", async (status, code, message) => {
    intercept = url => url.pathname === "/v1/confirmations" ? failure(Number(status), String(code)) : undefined;
    mountApp(); const error = await screen.findByRole("alert"); expect(error).toHaveTextContent(String(message));
    expect(error).not.toHaveTextContent("PRIVATE ERROR"); expect(screen.queryByRole("list", { name: "Confirmation follow-ups" })).not.toBeInTheDocument();
    expect(screen.queryByText("No confirmations available")).not.toBeInTheDocument();
    intercept = undefined; fireEvent.click(within(error).getByRole("button", { name: "Retry" })); await loaded();
    expect(listCalls()).toHaveLength(2); expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("handles network errors and hides records, metrics and last-success timestamp after failed refresh", async () => {
    mountApp(); await loaded();
    fetchMock.mockRejectedValue(new TypeError("network down")); fireEvent.click(screen.getByRole("button", { name: "Refresh queue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the confirmation service");
    expect(screen.queryByRole("article", { name: "Confirmation conf-a" })).not.toBeInTheDocument();
    expect(screen.getByText("Last refreshed: Unavailable")).toBeInTheDocument();
    expect(screen.getByLabelText("Loaded confirmation statistics")).not.toHaveTextContent("1");
  });
  it("loads latest response only on demand, preserves ties, and reuses Commit 08 history navigation", async () => {
    records = [confirmation(), confirmation("b")];
    history["conf-a"] = [attempt("a", { attempt_id: "earlier", received_at: hours(-3) }), attempt("a"),
      attempt("a", { attempt_id: "tied-latest", intent: "CLARIFICATION", reason: "EXPLICIT_BOUND_RESPONSE" })];
    mountApp(); await loaded(); expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/attempts"))).toBe(false);
    fireEvent.click(within(item()).getByRole("button", { name: "Load latest response" }));
    const response = await screen.findByRole("region", { name: "Latest response for conf-a" });
    expect(await within(response).findByText("Unresolved reply")).toBeInTheDocument();
    expect(response).toHaveTextContent("Clarification"); expect(response).not.toHaveTextContent("earlier");
    expect(response).toHaveTextContent("p1:evidence:a");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/attempts"))).toHaveLength(1);
    fireEvent.click(within(item()).getByRole("link", { name: "View Confirmation" }));
    expect(await screen.findByRole("heading", { name: "Confirmation workspace" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/confirmations/conf-a");
    expect(await screen.findByRole("region", { name: "Customer response history" })).toBeInTheDocument();
  });
  it("keeps an on-demand history error local, with retry and no fabricated reply", async () => {
    intercept = url => url.pathname.endsWith("/attempts") ? failure(503, "VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE") : undefined;
    mountApp(); await loaded(); fireEvent.click(within(item()).getByRole("button", { name: "Load latest response" }));
    const error = await screen.findByRole("alert"); expect(error).toHaveTextContent("Verified customer-response processing is not yet connected.");
    expect(item()).toHaveTextContent("AWAITING_RESPONSE"); expect(item()).not.toHaveTextContent("Explicit acceptance");
    intercept = undefined; fireEvent.click(within(error).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No response attempts recorded.")).toBeInTheDocument();
    expect(listCalls()).toHaveLength(1);
  });
  it("provides a real Communication Center entry without altering the shell navigation", async () => {
    mountApp("/communications"); await screen.findByText("No communication requests");
    const link = screen.getByRole("link", { name: "Follow-Up Queue" }); expect(link).toHaveAttribute("href", "/communications/follow-ups");
    fireEvent.click(link); await loaded(); expect(window.location.pathname).toBe("/communications/follow-ups");
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
  });
  it.each(["tenant", "actor"])("isolates cached records and expanded history when switching %s", async scope => {
    const queryClient = mountScope(); await loaded();
    intercept = (_url, init) => (init?.headers as Record<string, string>)[scope === "tenant" ? "X-Tenant-ID" : "X-Actor-ID"] ===
      (scope === "tenant" ? "tenant-other" : "user_staff_01") ? failure(403, "FORBIDDEN") : undefined;
    fireEvent.click(screen.getByRole("button", { name: `Switch ${scope}` })); await screen.findByRole("alert");
    expect(screen.queryByRole("list", { name: "Confirmation follow-ups" })).not.toBeInTheDocument();
    expect(screen.queryByText("customer-a")).not.toBeInTheDocument();
    const next = scope === "tenant" ? { ...auth, tenantId: "tenant-other" } : { ...auth, actorId: "user_staff_01" };
    expect(queryClient.getQueryData(confirmationKeys.queue(next))).toBeUndefined();
  });
  it("cancels a late old-scope request so its data cannot overwrite the new tenant view", async () => {
    let release!: (value: Response) => void; let signal: AbortSignal | null | undefined;
    intercept = (_url, init) => {
      if ((init?.headers as Record<string, string>)["X-Tenant-ID"] === auth.tenantId) {
        signal = init?.signal; return new Promise(resolve => { release = resolve; });
      }
      return failure(403, "FORBIDDEN");
    };
    mountScope(); await waitFor(() => expect(signal).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "Switch tenant" })); await screen.findByRole("alert");
    expect(signal?.aborted).toBe(true); await act(async () => release(reply([confirmation()])));
    expect(screen.queryByText("customer-a")).not.toBeInTheDocument();
  });
  it.each([
    ["missing expiry", { expires_at: undefined }], ["unknown backend state", { state: "SENT" }],
    ["wrong tenant", { tenant_id: "other" }], ["unverified state", { state: "UNVERIFIED" }],
  ])("fails closed on %s without inventing success or incomplete metrics", async (_, changes) => {
    records = [{ ...confirmation(), ...changes }]; mountApp();
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be validated|does not match/);
    expect(screen.queryByRole("list", { name: "Confirmation follow-ups" })).not.toBeInTheDocument();
    expect(screen.queryByText("Acceptance recorded")).not.toBeInTheDocument();
  });
  it("keeps the read client whitelist and duplicate detection for unfiltered list queries", async () => {
    records = [{ ...confirmation(), token: "SECRET_TOKEN", approved: true, fulfilment_state: "FULFILLED", recipient_identity_id: "PRIVATE_CONTACT" }];
    const queryClient = mountApp(); await loaded();
    expect(JSON.stringify(queryClient.getQueryData(confirmationKeys.queue(auth)))).not.toMatch(/SECRET_TOKEN|PRIVATE_CONTACT|FULFILLED|approved/);
    records = [confirmation(), confirmation()];
    await expect(listConfirmations(undefined, auth)).rejects.toMatchObject({ code: "UNSUPPORTED_RESPONSE" });
  });
});
