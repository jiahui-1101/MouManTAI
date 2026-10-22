import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RecipientPreferences, type RecipientPreference, type RuntimeCapabilities } from "./RecipientPreferences";

const auth = { tenantId: "synthetic_tenant_a", actorId: "user_manager_01" };
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "Content-Type": "application/json" },
});
let caps: RuntimeCapabilities, rows: RecipientPreference[], fail: boolean;
const fetchMock = vi.fn<typeof fetch>();
const clients: QueryClient[] = [];
const saved = (): RecipientPreference => ({ tenant_id: auth.tenantId, customer_id: "cust_bk", channel: "MOCK_EMAIL",
  consent_status: "OPTED_IN", consent_purpose: "TRANSACTIONAL_REVISED_TERMS", recipient_identity_id: "fixture_contact",
  consent_evidence_ref: "synthetic:consent:original_fixture", source: "SYNTHETIC_FIXTURE",
  consent_expires_at: "2026-10-23T10:00:00Z", version: 1, updated_at: "2026-10-22T10:00:00Z",
  updated_by_actor_id: auth.actorId, allowed_contact_hours: { start_hour: 0, end_hour: 24 }, timezone: "Asia/Kuala_Lumpur" });
beforeEach(() => {
  caps = { tenant_id: auth.tenantId, mode: "SYNTHETIC", label: "Synthetic Demo — No Real Messages Sent",
    can_record_preferences: true, can_revoke_preferences: true, integrated_demo_ready: false,
    blockers: ["CORE_APPROVAL_PRODUCER_UNAVAILABLE", "CORE_ACTION_POLICY_UNAVAILABLE"] };
  rows = []; fail = false;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, init) => {
    if (String(input).endsWith("/runtime-capabilities")) return reply(caps);
    if (init?.method === "POST") {
      if (fail) return reply({ code: "CONSENT_VERSION_CONFLICT", message: "internal details" }, 409);
      const body = JSON.parse(String(init.body));
      const value = { ...saved(), ...body, tenant_id: auth.tenantId, version: body.expected_version + 1 };
      rows = [value]; return reply(value);
    }
    return reply(rows);
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", { randomUUID: () => "stable_preference_request_key" });
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals(); });
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><RecipientPreferences auth={auth} /></QueryClientProvider>);
}
async function open() {
  await screen.findByText("Synthetic Demo — No Real Messages Sent");
  fireEvent.click(screen.getByRole("button", { name: "Recipient preferences" }));
  await waitFor(() => expect(screen.queryByText("Loading recipient preferences…")).not.toBeInTheDocument());
}
function fields() {
  fireEvent.change(screen.getByLabelText("Customer ID"), { target: { value: "cust_bk" } });
  fireEvent.change(screen.getByLabelText("Synthetic consent evidence reference"), { target: { value: "synthetic:consent:user_entered_fixture" } });
  fireEvent.change(screen.getByLabelText("Permission expiry (your local time)"), { target: { value: "2026-10-23T10:00" } });
}
const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");

describe("Recipient preference policy UI", () => {
  it("labels synthetic mode, explains actual blockers, and never automatically opts in", async () => {
    mount(); await open();
    expect(screen.getByText(/Current durable recovery plan approval and expiry cannot be verified/)).toBeInTheDocument();
    expect(screen.getByText(/Missing permission never means opt-in/)).toBeInTheDocument();
    expect(posts()).toHaveLength(0);
  });
  it("takes edit permissions from backend and disables staff writes", async () => {
    caps.can_record_preferences = false; caps.can_revoke_preferences = false; rows = [saved()];
    mount(); await open(); fields();
    expect(screen.getByRole("button", { name: "Record synthetic permission" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Revoke cust_bk/ })).toBeDisabled();
    expect(posts()).toHaveLength(0);
  });
  it("requires explicit confirmation and sends no role, tenant or approval claims", async () => {
    mount(); await open(); fields();
    fireEvent.click(screen.getByRole("button", { name: "Record synthetic permission" }));
    expect(posts()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirm preference change" }));
    await screen.findByText(/Preference change persisted/);
    expect(posts()).toHaveLength(1);
    const body = JSON.parse(String(posts()[0][1]?.body));
    expect(body).toMatchObject({ source: "SYNTHETIC_FIXTURE", consent_purpose: "TRANSACTIONAL_REVISED_TERMS",
      consent_evidence_ref: "synthetic:consent:user_entered_fixture", expected_version: 0 });
    for (const key of ["tenant_id", "actor_role", "approved", "send_authorized"]) expect(body).not.toHaveProperty(key);
    expect(posts()[0][1]?.headers).toMatchObject({ "X-Tenant-ID": auth.tenantId, "X-Actor-ID": auth.actorId });
  });
  it("shows history fields and revokes using the current backend version", async () => {
    rows = [saved()]; mount(); await open();
    expect(await screen.findByText(/Evidence: synthetic:consent:original_fixture/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Synthetic consent evidence reference"), { target: { value: "synthetic:consent:revoke_fixture" } });
    fireEvent.click(screen.getByRole("button", { name: /Revoke cust_bk/ }));
    expect(posts()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirm preference change" }));
    await screen.findByText(/Preference change persisted/);
    expect(JSON.parse(String(posts()[0][1]?.body))).toMatchObject({ expected_version: 1, consent_status: "OPTED_OUT" });
  });
  it("keeps the request key on an ambiguous retry and never claims save success on conflict", async () => {
    fail = true; mount(); await open(); fields();
    fireEvent.click(screen.getByRole("button", { name: "Record synthetic permission" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm preference change" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Recipient preferences changed/);
    expect(screen.queryByText(/Preference change persisted/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm preference change" }));
    await waitFor(() => expect(posts()).toHaveLength(2));
    expect(posts()[0][1]?.body).toBe(posts()[1][1]?.body);
  });
  it("blocks preference reads and writes in closed production mode", async () => {
    caps.mode = "CLOSED"; caps.can_record_preferences = false; caps.can_revoke_preferences = false;
    mount(); await screen.findByText(/Production authority unavailable/);
    fireEvent.click(screen.getByRole("button", { name: "Recipient preferences" }));
    expect(screen.getByText(/Explicit synthetic scope/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record synthetic permission" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(1);
  });
  it("allows revocation even while P1 contact resolution is unavailable", async () => {
    caps.can_record_preferences = false; rows = [saved()]; mount(); await open();
    fireEvent.change(screen.getByLabelText("Synthetic consent evidence reference"), { target: { value: "synthetic:consent:revoke_offline" } });
    expect(screen.getByRole("button", { name: /Revoke cust_bk/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Record synthetic permission" })).toBeDisabled();
  });
  it("rejects cross-tenant preference data without rendering it", async () => {
    rows = [{ ...saved(), tenant_id: "other_tenant", customer_id: "private_customer" }]; mount(); await open();
    expect(await screen.findByRole("alert")).toHaveTextContent(/response does not match/);
    expect(screen.queryByText("private_customer")).not.toBeInTheDocument();
  });
  it("rejects unsupported capability flags without enabling a permission control", async () => {
    caps.can_record_preferences = "true" as unknown as boolean;
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(/server response is not supported/);
    fireEvent.click(screen.getByRole("button", { name: "Recipient preferences" }));
    expect(screen.queryByRole("button", { name: "Record synthetic permission" })).not.toBeInTheDocument();
    expect(posts()).toHaveLength(0);
  });
});
