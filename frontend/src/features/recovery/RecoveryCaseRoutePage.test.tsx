import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AuthProvider } from "../../shared/auth";
import { RecoveryCaseRoutePage } from "./RecoveryCaseRoutePage";
import type { RecoveryCaseView } from "./recoveryCaseView";

function persistedCase(): RecoveryCaseView {
  return {
    case_id: "rc_100",
    tenant_id: "tenant_route_test",
    commitment_id: "com_100",
    case_version: 2,
    commitment_version: 7,
    status: "AWAITING_EVALUATION_INPUTS",
    storage_mode: "DURABLE_DATABASE",
    created_at: "2026-10-22T09:00:00+08:00",
    updated_at: "2026-10-22T09:10:00+08:00",
    trigger_events: [{
      event_id: "evt_risk_100",
      commitment_version: 7,
      assessment_id: "assess_100",
      assessment_commitment_version: 6,
      assessment_provenance_status: "VERIFIED_AUTHORITATIVE",
      snapshot_id: "snapshot_42",
      snapshot_version: 42,
      evidence_refs: ["evidence_stock_100"],
      occurred_at: "2026-10-22T09:05:00+08:00",
    }],
    evidence_refs: ["evidence_supplier_100"],
  };
}

function renderRoute(path = "/recovery/com_100") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider initialTenantId="tenant_route_test" initialActorId="user_manager_01">
        <MemoryRouter initialEntries={[path]}>
          <Routes><Route path="/recovery/:id" element={<RecoveryCaseRoutePage />} /></Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

describe("RecoveryCaseRoutePage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads and displays a persisted case and its provenance as read-only", async () => {
    const fetchMock = vi.fn((_url: string | URL | Request, _init?: RequestInit) => response(persistedCase()));
    vi.stubGlobal("fetch", fetchMock);
    renderRoute();

    expect(await screen.findByText("rc_100")).toBeInTheDocument();
    expect(screen.getByText("evt_risk_100")).toBeInTheDocument();
    expect(screen.getByText(/Assessment assess_100/)).toBeInTheDocument();
    expect(screen.getByText(/Snapshot snapshot_42 · v42/)).toBeInTheDocument();
    expect(screen.getAllByText("evidence_stock_100")).toHaveLength(2);
    expect(screen.getByText(/Read-only case view\. This view does not approve plans or execute/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open planning workspace" })).toHaveAttribute("href", "/recovery/com_100/plans");
    expect(screen.getByRole("link", { name: "Commitment context" })).toHaveAttribute("href", "/commitments/com_100");
    expect(screen.getByText(/Impact detail unavailable — the case API does not return an impact ID/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Impact assessment/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Communication center" })).toHaveAttribute("href", "/communications");
    expect(screen.queryByRole("button", { name: /approve|execute|run recovery/i })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/recovery/cases/com_100"),
      expect.objectContaining({
        headers: expect.objectContaining({ "X-Tenant-ID": "tenant_route_test", "X-Actor-ID": "user_manager_01" }),
      }),
    );
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("shows persisted rejection and counteroffer outcomes with exact evidence without action controls", async () => {
    const caseData = {
      ...persistedCase(),
      status: "NEEDS_REPLAN",
      customer_response_events: [{
        event_id: "evt_response_1",
        confirmation_id: "cnf_1",
        proposal_id: "prop_2",
        proposal_version: 3,
        intent: "COUNTEROFFER" as const,
        outcome: "REPLANNED" as const,
        proposed_terms: { quantity: "12", deadline: "2026-11-02T17:00:00+08:00" },
        evidence_refs: ["inbound:msg_55", "confirmation:cnf_1"],
        received_at: "2026-10-22T10:00:00+08:00",
      }],
    };
    vi.stubGlobal("fetch", vi.fn(() => response(caseData)));
    renderRoute();

    expect(await screen.findByText("COUNTEROFFER · REPLANNED")).toBeInTheDocument();
    expect(screen.getByText("Proposal prop_2 · v3")).toBeInTheDocument();
    expect(screen.getByText(/quantity: 12/)).toBeInTheDocument();
    expect(screen.getByText(/inbound:msg_55/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve|execute|run recovery/i })).not.toBeInTheDocument();
  });

  it("shows a loading state while the authoritative case request is pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    renderRoute();
    expect(screen.getByRole("status")).toHaveTextContent(/loading recovery case/i);
  });

  it("loads the persisted trigger view when the server reports evaluation inputs are pending", async () => {
    const triggerView = {
      ...persistedCase(),
      evaluation_readiness: "AWAITING_EVALUATION_INPUTS" as const,
      missing_evaluation_inputs: ["P2_FEASIBILITY_ASSESSMENT"],
      trigger_assessment: null,
      operational_snapshot: null,
    };
    const fetchMock = vi.fn((url: string | URL | Request, _init?: RequestInit) =>
      String(url).endsWith("/trigger")
        ? response(triggerView)
        : response({
            code: "RECOVERY_EVALUATION_INPUTS_PENDING",
            message: "Planning inputs are pending",
            details: { trigger_case_path: "/v1/recovery/cases/com_100/trigger" },
          }, 409),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderRoute();

    expect(await screen.findByText("rc_100")).toBeInTheDocument();
    expect(screen.getAllByText("AWAITING EVALUATION INPUTS")).toHaveLength(2);
    expect(screen.getByText(/Waiting for: P2 FEASIBILITY ASSESSMENT/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("shows an explicit not-found state without substituting demo data", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({ code: "NOT_FOUND", message: "Recovery case was not found" }, 404)));
    renderRoute();
    expect(await screen.findByRole("heading", { name: "Recovery case not found" })).toBeInTheDocument();
    expect(screen.queryByText("rc_100")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry loading" })).toBeInTheDocument();
  });

  it("keeps tenant authorization failures explicit", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({ code: "FORBIDDEN", message: "Tenant access denied" }, 403)));
    renderRoute();
    expect(await screen.findByRole("heading", { name: "Recovery case unavailable" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/Tenant access denied/);
  });

  it("rejects synthetic storage responses instead of rendering them as real cases", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({ ...persistedCase(), storage_mode: "IN_MEMORY_SYNTHETIC" })));
    renderRoute();
    expect(await screen.findByRole("heading", { name: "Durable recovery data required" })).toBeInTheDocument();
    expect(screen.queryByText("rc_100")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/Synthetic recovery records/);
  });

  it("retries failed reads on demand", async () => {
    const fetchMock = vi.fn((_url: string | URL | Request, _init?: RequestInit) => response({}));
    fetchMock
      .mockImplementationOnce(() => response({ code: "SERVICE_UNAVAILABLE", message: "Reader unavailable" }, 503))
      .mockImplementationOnce(() => response(persistedCase()));
    vi.stubGlobal("fetch", fetchMock);
    renderRoute();
    expect(await screen.findByRole("heading", { name: "Recovery data unavailable" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    await waitFor(() => expect(screen.getByText("rc_100")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
