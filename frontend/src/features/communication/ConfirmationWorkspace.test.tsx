import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import { AuthProvider, useAuth } from "../../shared/auth";
import { ConfirmationWorkspacePage } from "./ConfirmationWorkspacePage";
import { LinkedConfirmations } from "./LinkedConfirmations";
import { confirmationKeys, getConfirmation, getConfirmationAttempts, listConfirmations } from "./confirmationApi";
import type { ConfirmationAttemptView, ConfirmationView } from "./confirmationTypes";
import type { CommunicationRequestView } from "./types";

// Synthetic transport fixtures ONLY. No production fixture or authority override.
const auth = { tenantId: "tenant-workspace-test", actorId: "user_manager_01", correlationId: "test-correlation" };
function confirmation(changes: Partial<ConfirmationView> = {}): ConfirmationView {
  return { confirmation_id: "conf-exact", tenant_id: auth.tenantId, communication_id: "comm-exact", outbound_id: "outbound-exact",
    customer_id: "customer-ref", channel: "MOCK_TELEGRAM", reference: {
      tenant_id: auth.tenantId, commitment_id: "commitment-exact", commitment_version: 2, proposal_id: "proposal-v2",
      proposal_version: 2, plan_id: "plan-exact", plan_version: 1, source_event_id: "source-exact", correlation_id: "correlation-exact",
      causation_id: null, occurred_at: "2026-10-22T10:00:00+08:00" },
    terms_digest: "a".repeat(64), content_hash: "b".repeat(64), state: "AWAITING_RESPONSE",
    created_at: "2026-10-22T10:05:00+08:00", expires_at: "2030-10-23T10:00:00+08:00", consumed_at: null, revoked_at: null,
    blocked_reasons: [], core_transition_applied: false, evidence_scope: "P4_EVIDENCE_ONLY", integration_mode: "SYNTHETIC_ONLY", ...changes };
}
function attempt(changes: Partial<ConfirmationAttemptView> = {}): ConfirmationAttemptView {
  return { attempt_id: "attempt-one", confirmation_id: "conf-exact", inbound_message_id: "p1-message-ref",
    intent: "UNKNOWN", reason: "AMBIGUOUS_OR_UNBOUND_RESPONSE", evidence_refs: ["p1:evidence:one"],
    proposed_changes: null, received_at: "2026-10-22T11:00:00+08:00", ...changes };
}
function communication(): CommunicationRequestView {
  const value = confirmation();
  return { communication_id: value.communication_id, reference: value.reference, request_status: "READY_FOR_DRAFTING",
    blocking_reasons: [], proposed_terms: { sku: "SKU-TEST", quantity: "10", unit: "pcs", deadline: "2030-10-25T10:00:00+08:00", special_instructions: null },
    message_status: "DRAFT", approval_evidence_refs: ["approval-ref"], approval_expires_at: value.expires_at,
    proposal_evidence_refs: ["proposal-ref"], recipient_identity_id: "redacted-contact-ref", recipient_evidence_refs: ["identity-ref"],
    channel: value.channel, channel_evidence_refs: ["channel-ref"], expires_at: value.expires_at,
    created_by: "manager-ref", created_at: value.created_at, outbound_status: "SENT" };
}
const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const failure = (status: number, code: string) => reply({ code, message: "PRIVATE SERVER DETAIL AND TOKEN", correlation_id: "test-error-ref" }, status);
const fetchMock = vi.fn<typeof fetch>();
const clients: QueryClient[] = [];
let detail: unknown;
let attempts: unknown;
let linked: unknown;
let intercept: ((url: URL, init?: RequestInit) => Response | Promise<Response> | undefined) | undefined;
beforeEach(() => {
  detail = confirmation(); attempts = []; linked = [confirmation()]; intercept = undefined;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const overridden = intercept?.(url, init);
    if (overridden) return overridden;
    if (url.pathname === "/v1/confirmations") return reply(linked);
    if (url.pathname === "/v1/confirmations/conf-exact") return reply(detail);
    if (url.pathname === "/v1/confirmations/conf-exact/attempts") return reply(attempts);
    if (url.pathname.endsWith("/runtime-capabilities")) return reply({ tenant_id: auth.tenantId, mode: "CLOSED",
      label: "Trusted authority unavailable", can_record_preferences: false, can_revoke_preferences: false,
      integrated_demo_ready: false, blockers: ["PRODUCTION_AUTH_UNAVAILABLE"] });
    if (url.pathname === "/v1/communications/summary") return reply({ tenant_id: auth.tenantId, total: 1, drafted: 0, sent: 1,
      needs_attention: 0, checked_at: confirmation().created_at, unavailable_reasons: {} });
    if (url.pathname === "/v1/communications") return reply([communication()]);
    if (url.pathname === "/v1/communications/comm-exact") return reply(communication());
    if (url.pathname === "/v1/communications/comm-exact/outbound") return reply([]);
    return failure(404, "NOT_FOUND");
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals();
  vi.restoreAllMocks(); window.history.replaceState({}, "", "/");
});
function newClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false } } });
  clients.push(client); return client;
}
function Controls() {
  const context = useAuth(); const navigate = useNavigate();
  return <><button onClick={() => context.setTenantId("tenant-other")}>Switch tenant</button>
    <button onClick={() => context.setActorId("user_staff_01")}>Switch actor</button>
    <button onClick={() => navigate("/confirmations/conf-other")}>Switch confirmation</button></>;
}
function mount() {
  const client = newClient();
  render(<QueryClientProvider client={client}><AuthProvider initialTenantId={auth.tenantId} initialActorId={auth.actorId}>
    <MemoryRouter initialEntries={["/confirmations/conf-exact"]}><Controls /><Routes>
      <Route path="/confirmations/:id" element={<ConfirmationWorkspacePage />} />
    </Routes></MemoryRouter></AuthProvider></QueryClientProvider>);
  return client;
}
function mountApp(path = "/confirmations/conf-exact") {
  window.history.replaceState({}, "", path);
  const client = newClient();
  render(<App queryClient={client} initialTenantId={auth.tenantId} initialActorId={auth.actorId} />);
  return client;
}
const proposal = () => screen.getByRole("region", { name: "Proposal and version details" });
const history = () => screen.getByRole("region", { name: "Customer response history" });
const loaded = () => screen.findByRole("region", { name: "Confirmation overview" });

describe("Confirmation workspace", () => {
  it("mounts the actual App page with exact backend proposal version and preserved shared providers", async () => {
    mountApp(); await loaded();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "MouManTAI" })).toBeInTheDocument();
    expect(screen.queryByText(/owner module pending/i)).not.toBeInTheDocument();
    expect(within(proposal()).getByText("Version 2")).toBeInTheDocument();
    expect(proposal()).toHaveTextContent("proposal-v2"); expect(proposal()).toHaveTextContent("commitment-exact");
    expect(proposal()).toHaveTextContent("Unavailable — current proposal verification");
    expect(proposal()).toHaveTextContent("only the exact terms digest");
    expect(screen.getByRole("region", { name: "Evidence and verification" })).toHaveTextContent("Updated atUnavailable");
    await within(history()).findByText(/No customer responses recorded/);
    for (const [url, init] of fetchMock.mock.calls) {
      expect(new URL(String(url)).pathname).toMatch(/^\/v1\/confirmations\//);
      expect(init?.headers).toMatchObject({ "X-Tenant-ID": auth.tenantId, "X-Actor-ID": auth.actorId });
      expect(init?.method ?? "GET").toBe("GET");
    }
    expect(screen.queryByRole("button", { name: /accept|reject|confirm|send/i })).not.toBeInTheDocument();
  });

  it("shows loading until the real request resolves, without fabricated acceptance", async () => {
    let release!: (value: Response) => void;
    intercept = url => url.pathname === "/v1/confirmations/conf-exact" ? new Promise(resolve => { release = resolve; }) : undefined;
    mount(); expect(screen.getByRole("status")).toHaveTextContent("Loading confirmation details");
    expect(screen.queryByText("Acceptance recorded")).not.toBeInTheDocument();
    await act(async () => release(reply(confirmation()))); await loaded();
  });

  it("keeps SENT separate from acceptance and never makes an acceptance or fulfilment mutation", async () => {
    mountApp("/communications");
    fireEvent.click(await screen.findByRole("button", { name: /commitment-exact/ }));
    const links = await screen.findByRole("region", { name: "Linked confirmations" });
    expect(within(screen.getByRole("region", { name: "Communication details" })).getByText("Sent")).toBeInTheDocument();
    const link = await within(links).findByRole("link", { name: "Open confirmation conf-exact" });
    expect(link).toHaveAttribute("href", "/confirmations/conf-exact"); fireEvent.click(link);
    await loaded(); expect(window.location.pathname).toBe("/confirmations/conf-exact");
    expect(screen.getAllByText("Awaiting response").length).toBeGreaterThan(0);
    expect(screen.queryByText("Acceptance recorded")).not.toBeInTheDocument();
    const status = screen.getByRole("region", { name: "Confirmation status" });
    expect(status).toHaveTextContent("no Core fulfilment evidence");
    expect(status).not.toHaveTextContent("FULFILLED");
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("renders earlier-version acceptance only as evidence for that exact version, without confirming a newer one", async () => {
    detail = confirmation({ state: "ACCEPTED", consumed_at: "2026-10-22T11:00:00+08:00" });
    attempts = [attempt({ intent: "ACCEPT", reason: "EXPLICIT_BOUND_RESPONSE" })];
    mount(); await loaded();
    expect(within(proposal()).getByText("Version 2")).toBeInTheDocument();
    expect(screen.getAllByText("Acceptance recorded")).toHaveLength(2);
    expect(await within(history()).findByText("Explicit acceptance")).toBeInTheDocument();
    expect(history()).toHaveTextContent("Applies to proposal-v2 · v2");
    expect(screen.queryByText("Version 3")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Confirmation status" })).toHaveTextContent("Not applied by this workflow");
    expect(screen.getByRole("region", { name: "Confirmation status" })).not.toHaveTextContent("FULFILLED");
  });

  it.each([
    ["EXPIRED", "Expired"], ["SUPERSEDED", "Superseded"], ["REJECTED", "Rejection recorded"],
    ["COUNTEROFFER_RECEIVED", "Counteroffer received"], ["CLARIFICATION_REQUIRED", "Clarification required"],
    ["UNRESOLVED", "Unresolved"],
  ] as const)("uses backend %s without inventing active status", async (state, label) => {
    detail = confirmation({ state }); mount(); await loaded();
    expect(within(screen.getByRole("region", { name: "Confirmation status" })).getByText(label)).toBeInTheDocument();
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Accept$/ })).not.toBeInTheDocument();
  });

  it("reports revocation independently of recorded response state", async () => {
    detail = confirmation({ revoked_at: "2026-10-22T10:30:00+08:00", blocked_reasons: ["CONFIRMATION_REVOKED"] });
    mount(); await loaded();
    const status = screen.getByRole("region", { name: "Confirmation status" });
    expect(status).toHaveTextContent("Revoked"); expect(status).toHaveTextContent("AWAITING_RESPONSE");
    expect(status).toHaveTextContent("CONFIRMATION_REVOKED");
  });

  it("uses backend-reported stale reasons and does not derive expiry/currentness from the browser clock", async () => {
    detail = confirmation({ expires_at: "2026-10-22T10:06:00+08:00", blocked_reasons: ["CONFIRMATION_PROPOSAL_CHANGED"] });
    mount(); await loaded();
    expect(proposal()).toHaveTextContent("Stale or superseded — reported by backend");
    expect(screen.getAllByText("Awaiting response")).toHaveLength(2);
    expect(screen.queryByText("Expired")).not.toBeInTheDocument();
  });

  it("renders persisted evidence, ambiguity and counteroffer changes without raw bodies or invented audits", async () => {
    attempts = [attempt(), attempt({ attempt_id: "attempt-two", intent: "COUNTEROFFER", reason: "EXPLICIT_BOUND_COUNTEROFFER",
      proposed_changes: { quantity: "12", special_instructions: "<script>customer text</script>" }, evidence_refs: ["p1:evidence:two"] })];
    mount(); await loaded();
    expect(await within(history()).findByText("Unresolved reply")).toBeInTheDocument();
    expect(history()).toHaveTextContent("Counteroffer"); expect(history()).toHaveTextContent("p1:evidence:one");
    expect(history()).toHaveTextContent("p1-message-ref"); expect(history()).toHaveTextContent("AMBIGUOUS_OR_UNBOUND_RESPONSE");
    expect(history()).toHaveTextContent("Original approved terms remain unchanged");
    expect(history()).toHaveTextContent("<script>customer text</script>"); expect(document.querySelector("script")).toBeNull();
    expect(history()).toHaveTextContent("Current identity verification is unavailable");
    expect(history()).toHaveTextContent("Rejected API calls, full audit records");
  });

  it.each([
    [403, "FORBIDDEN", "do not have permission"], [404, "CONFIRMATION_NOT_FOUND", "Confirmation not found"],
    [409, "CONFLICT", "conflicts with the requested record"], [409, "CONFIRMATION_PROPOSAL_CHANGED", "changed or stale proposal"],
    [503, "CONFIRMATION_AUTHORITY_UNAVAILABLE", "authority or storage is unavailable"],
    [503, "CONFIRMATION_PROCESSOR_AUTH_UNAVAILABLE", "Verified customer-response processing is not yet connected."],
    [503, "VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE", "Verified customer-response processing is not yet connected."],
    [503, "CONFIRMATION_DISPOSABLE_SCOPE_REQUIRED", "disposable synthetic environment"],
    [503, "PRODUCTION_AUTH_UNAVAILABLE", "Trusted authentication is unavailable"],
    [403, "CONFIRMATION_IDENTITY_UNVERIFIED", "Customer identity has not been verified"],
    [403, "CONFIRMATION_IDENTITY_MISMATCH", "verified sender does not match"],
  ])("handles %s %s with retry and no private error or success disclosure", async (status, code, message) => {
    intercept = url => url.pathname === "/v1/confirmations/conf-exact" ? failure(Number(status), String(code)) : undefined;
    mount(); const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent(String(message)); expect(error).not.toHaveTextContent("PRIVATE SERVER");
    expect(screen.queryByRole("region", { name: "Confirmation overview" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/attempts"))).toBe(false);
    intercept = undefined; fireEvent.click(within(error).getByRole("button", { name: "Retry" }));
    await loaded(); expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Acceptance recorded")).not.toBeInTheDocument();
  });

  it("hides previously accepted content when refresh fails rather than retaining a misleading success", async () => {
    detail = confirmation({ state: "ACCEPTED", consumed_at: "2026-10-22T11:00:00+08:00" }); mount(); await loaded();
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh workspace" })).toBeEnabled());
    intercept = url => url.pathname === "/v1/confirmations/conf-exact" ? failure(409, "CONFIRMATION_PROPOSAL_CHANGED") : undefined;
    fireEvent.click(screen.getByRole("button", { name: "Refresh workspace" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("changed or stale");
    expect(screen.queryByText("Acceptance recorded")).not.toBeInTheDocument();
  });

  it("keeps history failures independent from valid details and retries history only", async () => {
    intercept = url => url.pathname.endsWith("/attempts") ? failure(503, "VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE") : undefined;
    mount(); await loaded(); const error = await within(history()).findByRole("alert");
    expect(error).toHaveTextContent("Verified customer-response processing is not yet connected.");
    intercept = undefined; attempts = [attempt()]; fireEvent.click(within(error).getByRole("button", { name: "Retry" }));
    expect(await within(history()).findByText("Unresolved reply")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/conf-exact"))).toHaveLength(1);
  });

  it.each(["tenant", "actor", "confirmation"])("isolates cache and removes old evidence when switching %s", async scope => {
    const client = mount(); await loaded();
    intercept = (url, init) => {
      const headers = init?.headers as Record<string, string>;
      return url.pathname.startsWith("/v1/confirmations/") &&
        (headers["X-Tenant-ID"] === "tenant-other" || headers["X-Actor-ID"] === "user_staff_01" || url.pathname.includes("conf-other"))
        ? failure(403, "FORBIDDEN") : undefined;
    };
    fireEvent.click(screen.getByRole("button", { name: `Switch ${scope}` }));
    await screen.findByRole("alert"); expect(screen.queryByRole("region", { name: "Confirmation overview" })).not.toBeInTheDocument();
    expect(screen.queryByText("customer-ref")).not.toBeInTheDocument();
    if (scope === "tenant") expect(client.getQueryData(confirmationKeys.detail({ ...auth, tenantId: "tenant-other" }, "conf-exact"))).toBeUndefined();
  });

  it("renders connection failure honestly and does not invent an empty confirmation", async () => {
    fetchMock.mockRejectedValue(new TypeError("network down")); mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the confirmation service");
    expect(screen.queryByText(/No customer responses recorded/)).not.toBeInTheDocument();
  });
});

describe("Linked confirmations and safe read client", () => {
  function mountLinks() { render(<QueryClientProvider client={newClient()}><MemoryRouter>
    <LinkedConfirmations communicationId="comm-exact" auth={auth} />
  </MemoryRouter></QueryClientProvider>); }
  it("shows empty state only for a successful empty response", async () => {
    linked = []; mountLinks(); expect(await screen.findByText(/No linked confirmations/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).searchParams.get("communication_id")).toBe("comm-exact");
    expect(init?.headers).toMatchObject({ "X-Tenant-ID": auth.tenantId, "X-Actor-ID": auth.actorId, "X-Correlation-ID": auth.correlationId });
  });
  it("does not label inaccessible records as empty and does not leak another communication", async () => {
    linked = [confirmation({ communication_id: "comm-other" })]; mountLinks();
    expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText(/No linked confirmations/)).not.toBeInTheDocument();
  });
  it("shows both exact proposal versions rather than assigning older acceptance to a newer proposal", async () => {
    linked = [confirmation({ state: "ACCEPTED", consumed_at: "2026-10-22T11:00:00+08:00" }), confirmation({ confirmation_id: "conf-v3",
      reference: { ...confirmation().reference, proposal_id: "proposal-v3", proposal_version: 3 } })];
    mountLinks(); await screen.findByRole("link", { name: "Open confirmation conf-v3" });
    const list = screen.getByRole("list"); const records = within(list).getAllByRole("listitem");
    expect(records[0]).toHaveTextContent("proposal-v2 · v2"); expect(records[0]).toHaveTextContent("Acceptance recorded");
    expect(records[1]).toHaveTextContent("proposal-v3 · v3"); expect(records[1]).toHaveTextContent("Awaiting response");
    expect(records[1]).not.toHaveTextContent("Acceptance recorded");
  });

  it.each([
    ["tenant", { tenant_id: "other" }], ["id", { confirmation_id: "other" }],
    ["reference tenant", { reference: { ...confirmation().reference, tenant_id: "other" } }],
    ["unknown state", { state: "CUSTOMER_ACCEPTED" }], ["invalid version", { reference: { ...confirmation().reference, proposal_version: 0 } }],
    ["unverified state outside current schema", { state: "UNVERIFIED" }],
    ["wrong digest", { terms_digest: "approved=true" }], ["production claim", { integration_mode: "PRODUCTION" }],
    ["core transition claim", { core_transition_applied: true }], ["bad date", { expires_at: "tomorrow" }],
  ])("rejects unsupported or mismatched %s rather than displaying success", async (_, changes) => {
    detail = { ...confirmation(), ...changes };
    await expect(getConfirmation("conf-exact", auth)).rejects.toMatchObject({ status: 409 });
  });

  it("whitelists API fields so tokens, raw contacts, bodies and client approval flags are never cached", async () => {
    detail = { ...confirmation(), confirmation_token: "SECRET_TOKEN", token_digest: "SECRET_HASH", approved: true,
      raw_body: "SECRET_BODY", recipient_identity_id: "SECRET_PHONE", agreement_state: "CONFIRMED", fulfilment_state: "FULFILLED" };
    const client = mount(); await loaded();
    const cached = JSON.stringify(client.getQueryData(confirmationKeys.detail(auth, "conf-exact")));
    expect(cached).not.toMatch(/SECRET_|approved|agreement_state|fulfilment_state/);
    expect(document.body.textContent).not.toMatch(/SECRET_|FULFILLED|CONFIRMED/);
    expect(screen.getAllByText("Awaiting response")).toHaveLength(2);
  });
  it.each(["AWAITING_RESPONSE", "UNRESOLVED", "CLARIFICATION_REQUIRED"] as const)("never renders %s as a green success badge", async state => {
    detail = confirmation({ state }); mount(); await loaded();
    const region = screen.getByRole("region", { name: "Confirmation status" });
    expect(region.querySelector(".status-badge")).not.toHaveClass("badge-success");
    expect(region.querySelector(".status-badge")).toHaveClass("badge-neutral");
    expect(region).not.toHaveTextContent("FULFILLED");
  });
  it("validates response history bindings and intent before displaying evidence", async () => {
    attempts = [attempt({ confirmation_id: "other" })];
    await expect(getConfirmationAttempts("conf-exact", auth)).rejects.toMatchObject({ code: "RESPONSE_SCOPE_MISMATCH" });
    attempts = [{ ...attempt(), intent: "FULFILLED" }];
    await expect(getConfirmationAttempts("conf-exact", auth)).rejects.toMatchObject({ code: "UNSUPPORTED_RESPONSE" });
    attempts = [attempt({ evidence_refs: [] })];
    await expect(getConfirmationAttempts("conf-exact", auth)).rejects.toMatchObject({ code: "UNSUPPORTED_RESPONSE" });
    attempts = [attempt(), attempt()];
    await expect(getConfirmationAttempts("conf-exact", auth)).rejects.toMatchObject({ code: "UNSUPPORTED_RESPONSE" });
  });
  it("encodes actual IDs and uses only the documented GET endpoints with abort support", async () => {
    const controller = new AbortController();
    intercept = url => url.pathname === "/v1/confirmations/conf%2Fencoded" ? reply(confirmation({ confirmation_id: "conf/encoded" })) : undefined;
    await getConfirmation("conf/encoded", auth, controller.signal);
    expect(fetchMock.mock.calls[0][0]).toContain("/v1/confirmations/conf%2Fencoded");
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal);
    linked = [confirmation(), confirmation()];
    await expect(listConfirmations("comm-exact", auth)).rejects.toMatchObject({ code: "UNSUPPORTED_RESPONSE" });
  });
});
