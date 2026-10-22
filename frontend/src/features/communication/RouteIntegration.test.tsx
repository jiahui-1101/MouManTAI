import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import type { OverviewResponse } from "../../shared/types";

// Transport fixtures only: render the real App, its BrowserRouter, AuthProvider,
// QueryClientProvider, AppShell and actual P4 page. No duplicate test route tree.
const overview: OverviewResponse = {
  tenant_id: "tenant_route_test", actor_id: "user_manager_01", actor_role: "MANAGER",
  integration_mode: "SYNTHETIC", last_updated_at: "2026-10-22T10:00:00+08:00",
  counts: { requested: 0, confirmed: 0, at_risk: 0, pending_approval: 0,
    execution_in_progress: 0, awaiting_confirmation: 0, fulfilled: 0 },
  attention_queue: [], commitments: [],
};
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "Content-Type": "application/json" },
});
const fetchMock = vi.fn<typeof fetch>();
let p4Status = 200;
const clients: QueryClient[] = [];
beforeEach(() => {
  p4Status = 200;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async input => {
    // P1's operational API uses relative URLs; P2/P4 use the shared absolute URL.
    const path = new URL(String(input), "http://localhost").pathname;
    if (path.startsWith("/v1/communications")) {
      if (path.endsWith("/runtime-capabilities")) return reply({ tenant_id: "tenant_route_test", mode: "CLOSED",
        label: "Trusted authority unavailable", can_record_preferences: false, can_revoke_preferences: false,
        integrated_demo_ready: false, blockers: ["PRODUCTION_AUTH_UNAVAILABLE"] });
      if (p4Status !== 200) return reply({ code: "COMMUNICATION_SUMMARY_UNAVAILABLE", message: "Internal diagnostics not for UI" }, p4Status);
      if (path.endsWith("/summary")) return reply({ tenant_id: "tenant_route_test", total: 0, drafted: null,
        sent: null, needs_attention: 0, checked_at: "2026-10-22T10:00:00+08:00",
        unavailable_reasons: { drafted: "DRAFT_REVALIDATION_UNAVAILABLE", sent: "SENDING_RECORDS_UNAVAILABLE" } });
      return reply([]);
    }
    if (path === "/v1/overview") return reply(overview);
    if (path === "/health") return reply({ status: "ok", service: "moumantai-api", version: "0.1.0" });
    if (path === "/v1/commitments" || path === "/v1/audit") return reply([]);
    return reply({ code: "NOT_FOUND", message: "Test endpoint not configured" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup(); clients.splice(0).forEach(client => client.clear());
  vi.unstubAllGlobals(); window.history.replaceState({}, "", "/");
});

function mount(path = "/communications", actorId = "user_manager_01") {
  window.history.replaceState({}, "", path);
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false }, mutations: { retry: false },
  } });
  clients.push(client);
  render(<App queryClient={client} initialTenantId="tenant_route_test" initialActorId={actorId} />);
}

describe("Real App communication route", () => {
  it("mounts the actual P4 page with existing shell/providers and correct request headers", async () => {
    mount();
    expect(screen.getByRole("heading", { name: "Communication Center" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "MouManTAI" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(await screen.findByText("No communication requests")).toBeInTheDocument();
    expect(screen.getByLabelText("Communication summary").children).toHaveLength(4);
    expect(screen.queryByText(/owner module pending/i)).not.toBeInTheDocument();
    const calls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/v1/communications"));
    expect(calls.some(([url]) => String(url).endsWith("/summary"))).toBe(true);
    for (const [, init] of calls) expect(init?.headers).toMatchObject({
      "X-Tenant-ID": "tenant_route_test", "X-Actor-ID": "user_manager_01",
    });
  });

  it("navigates to the real page using the existing shell link", async () => {
    mount("/overview");
    await screen.findByRole("heading", { name: "Commitment Overview" });
    fireEvent.click(screen.getByRole("link", { name: "Communications · P4" }));
    await screen.findByText("No communication requests");
    expect(window.location.pathname).toBe("/communications");
    expect(screen.getByRole("heading", { name: "Communication Center" })).toBeInTheDocument();
  });

  it("retains role switching and scopes subsequent P4 queries to the shared actor", async () => {
    mount(); await screen.findByText("No communication requests");
    fireEvent.change(screen.getByLabelText("Demo role selector"), { target: { value: "user_staff_01" } });
    expect(screen.getByTestId("shell-tenant-badge")).toHaveTextContent("STAFF");
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes("/v1/communications") &&
      (init?.headers as Record<string, string>)["X-Actor-ID"] === "user_staff_01")).toBe(true));
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("keeps the actual page mounted and safe when migration/authority integration is unavailable", async () => {
    p4Status = 503; mount();
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.getByRole("heading", { name: "Communication Center" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prepare draft" })).not.toBeInTheDocument();
    expect(screen.queryByText("Internal diagnostics not for UI")).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
  });

  it.each([
    ["/", "Commitment Overview"], ["/overview", "Commitment Overview"],
    ["/activity", "Activity & Audit History"], ["/recovery/recovery", "Recovery case"],
    ["/communications/follow-ups", "Follow-Up Queue"],
    ["/confirmations/confirmation", "Confirmation workspace"], ["/unknown-route", "Page not found"],
  ])("preserves the actual App route %s", async (path, heading) => {
    mount(path);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "MouManTAI" })).toBeInTheDocument();
    if (path === "/communications/follow-ups") {
      expect(await screen.findByRole("alert")).toHaveTextContent("confirmation list or its route is unavailable");
      expect(screen.getByRole("region", { name: "Follow-Up Queue" })).toBeInTheDocument();
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/v1/confirmations"))).toBe(true);
      expect(screen.queryByText(/owner module pending/i)).not.toBeInTheDocument();
    }
    if (path.startsWith("/confirmations/")) {
      expect(await screen.findByRole("alert")).toHaveTextContent("Confirmation not found");
      expect(screen.getByRole("region", { name: "Customer Confirmation Workspace" })).toBeInTheDocument();
      expect(screen.queryByText(/owner module pending/i)).not.toBeInTheDocument();
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/v1/confirmations/confirmation"));
      expect(call?.[1]?.headers).toMatchObject({ "X-Tenant-ID": "tenant_route_test", "X-Actor-ID": "user_manager_01" });
    }
  });

  it.each([
    ["/inbox", "Message Inbox", ".p1-inbox", "Retry Inbox", "/v1/messages"],
    ["/orders/order", "Order Context Unavailable", ".p1-context-error-card", "Retry", "/v1/contexts/by-order/order"],
  ])("preserves the actual App route %s", async (path, heading, pageSelector, retryLabel, apiPath) => {
    mount(path);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Message request failed (404).");
    expect(error.closest(pageSelector)).not.toBeNull();
    expect(screen.getByRole("heading", { name: "MouManTAI" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(screen.queryByText(/owner module pending/i)).not.toBeInTheDocument();
    const calls = () => fetchMock.mock.calls.filter(([url]) =>
      new URL(String(url), "http://localhost").pathname === apiPath);
    expect(calls()).toHaveLength(1);
    fireEvent.click(within(error).getByRole("button", { name: retryLabel }));
    await waitFor(() => expect(calls()).toHaveLength(2));
    expect(await screen.findByRole("alert")).toHaveTextContent("Message request failed (404).");
    expect(screen.getByRole("button", { name: retryLabel })).toBeEnabled();
    expect(window.location.pathname).toBe(path);
  });

  it.each([
    ["/commitments/commitment", ["/v1/commitments/commitment", "/v1/commitments/commitment/assessments"]],
    ["/impact/impact", ["/v1/impacts/impact"]],
  ] as const)("preserves the actual App route %s", async (path, apiPaths) => {
    mount(path);
    // Real P2 pages load through the App's authenticated API source. With no
    // detail fixtures they render LoadFailure, rather than a placeholder heading.
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Request failed (404, NOT_FOUND): Test endpoint not configured");
    expect(error.closest(".p2-feature")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "MouManTAI" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(screen.queryByText(/owner module pending/i)).not.toBeInTheDocument();
    const callsFor = (apiPath: string) => fetchMock.mock.calls.filter(
      ([url]) => new URL(String(url)).pathname === apiPath,
    );
    for (const apiPath of apiPaths) {
      expect(callsFor(apiPath)).toHaveLength(1);
      expect(callsFor(apiPath)[0][1]?.headers).toMatchObject({
        "X-Tenant-ID": "tenant_route_test", "X-Actor-ID": "user_manager_01",
      });
    }
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    await waitFor(() => {
      for (const apiPath of apiPaths) expect(callsFor(apiPath)).toHaveLength(2);
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Request failed (404, NOT_FOUND)");
    expect(screen.getByRole("button", { name: "Retry loading" })).toBeEnabled();
    expect(window.location.pathname).toBe(path);
  });
});
