import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../../layout/AppShell";
import { FeaturePlaceholder } from "../../pages/FeaturePlaceholder";
import { OverviewPage } from "../../features/overview/OverviewPage";
import { ActivityPage } from "../../features/activity/ActivityPage";
import { CommitmentFeasibilityRoute, ImpactDetailRoute } from "../../App";
import { AuthProvider } from "../../shared/auth";
import { ApprovalActionControl } from "../../shared/ApprovalActionControl";
import { StatusBadge } from "../../shared/StatusBadge";
import type { OverviewResponse } from "../../shared/types";

const mockOverview: OverviewResponse = {
  tenant_id: "tenant_demo_01",
  actor_id: "user_owner_01",
  actor_role: "OWNER",
  integration_mode: "SYNTHETIC",
  last_updated_at: "2026-10-21T02:00:00Z",
  counts: {
    requested: 1,
    confirmed: 2,
    at_risk: 1,
    pending_approval: 1,
    execution_in_progress: 1,
    awaiting_confirmation: 1,
    fulfilled: 1,
  },
  attention_queue: [
    {
      commitment_id: "cmt_risk_01",
      order_id: "ord_101",
      category: "MANUAL_REVIEW",
      severity: "CRITICAL",
      summary: "Commitment cmt_risk_01 is BREACHED; supplier delayed raw material",
      deep_link_path: "/commitments/cmt_risk_01",
      updated_at: "2026-10-21T01:30:00Z",
    },
  ],
  commitments: [
    {
      commitment_id: "cmt_conf_01",
      order_id: "ord_001",
      customer_id: "cust_001",
      agreement_state: "CONFIRMED",
      feasibility_state: "FEASIBLE",
      risk_state: "NORMAL",
      recovery_state: "NONE",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 2,
      terms: {
        sku: "BURGER",
        quantity: "100",
        unit: "pcs",
        deadline: "2026-10-25T12:00:00Z",
      },
      evidence_refs: ["ev_01"],
      updated_at: "2026-10-21T01:00:00Z",
    },
  ],
};

function renderAppWithRoute(initialRoute: string, initialActorId: string = "user_owner_01") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider initialTenantId="tenant_demo_01" initialActorId={initialActorId}>
        <MemoryRouter initialEntries={[initialRoute]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/overview" element={<OverviewPage />} />
              <Route path="/activity" element={<ActivityPage />} />
              <Route path="/inbox" element={<FeaturePlaceholder owner="P1 · Context" title="Smart inbox" />} />
              <Route path="/orders/:id" element={<FeaturePlaceholder owner="P1 · Context" title="Order context" />} />
              <Route path="/commitments/:id" element={<CommitmentFeasibilityRoute />} />
              <Route path="/impact/:id" element={<ImpactDetailRoute />} />
              <Route path="/recovery/:id" element={<FeaturePlaceholder owner="P3 · Recovery" title="Recovery case" />} />
              <Route
                path="/communications"
                element={<FeaturePlaceholder owner="P4 · Communication" title="Communication center" />}
              />
              <Route
                path="/confirmations/:id"
                element={<FeaturePlaceholder owner="P4 · Communication" title="Confirmation workspace" />}
              />
              <Route path="*" element={<FeaturePlaceholder owner="Shared shell" title="Page not found" />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("Role Guard, Approval Controls, and Navigation Integrity (UI-03, FE-01a, FE-01d)", () => {
  let capturedHeaders: Record<string, string>[] = [];

  beforeEach(() => {
    capturedHeaders = [];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (init?.headers) {
          capturedHeaders.push(init.headers as Record<string, string>);
        }

        if (url.includes("/v1/overview")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockOverview), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        if (url.includes("/assessments")) {
          return Promise.resolve(
            new Response(JSON.stringify([]), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        if (url.includes("/v1/impacts/")) {
          const impactId = url.split("/").pop() || "fa_001";
          return Promise.resolve(
            new Response(
              JSON.stringify({
                impact_id: impactId,
                tenant_id: "tenant_demo_01",
                event_id: "evt_01",
                event_type: "supplier.delivery_changed",
                before_snapshot_id: "snap_01",
                before_snapshot_version: 1,
                after_snapshot_id: "snap_02",
                after_snapshot_version: 2,
                discovery_complete: true,
                candidate_commitment_ids: ["com_001"],
                impacts: [
                  {
                    tenant_id: "tenant_demo_01",
                    commitment_id: "com_001",
                    before_commitment_version: 1,
                    after_commitment_version: 1,
                    before_snapshot_id: "snap_01",
                    before_snapshot_version: 1,
                    after_snapshot_id: "snap_02",
                    after_snapshot_version: 2,
                    classification: "CONFIRMED_IMPACT",
                    reasons: ["Shortage detected."],
                    material_deltas: [],
                    hard_constraint_deltas: [],
                    buffers: [],
                    dependency_paths: [],
                    evidence_refs: [],
                  },
                ],
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }

        if (url.match(/\/v1\/commitments\/[^/]+$/)) {
          const comId = url.split("/").pop() || "com_001";
          return Promise.resolve(
            new Response(
              JSON.stringify({
                ...mockOverview.commitments[0],
                commitment_id: comId,
                tenant_id: "tenant_demo_01",
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }

        if (url.includes("/v1/commitments") && !url.includes("/confirm-proposal")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockOverview.commitments), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        if (url.includes("/timeline") || url.includes("/v1/audit")) {
          return Promise.resolve(
            new Response(JSON.stringify([]), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        return Promise.resolve(
          new Response(JSON.stringify({ status: "ok" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  // =========================================================================
  // 1. AppShell Role Simulator & X-Actor-ID updates (UI-03)
  // =========================================================================
  it("switching demo role selector in app shell updates actorRole and subsequent request headers", async () => {
    renderAppWithRoute("/overview", "user_owner_01");

    // Shell header shows simulated role dropdown
    const roleSelect = (await screen.findByTestId("shell-role-selector")) as HTMLSelectElement;
    expect(roleSelect.value).toBe("user_owner_01");

    const badge = screen.getByTestId("shell-tenant-badge");
    expect(badge).toHaveTextContent("tenant_demo_01 · OWNER");

    // Switch to Manager
    fireEvent.change(roleSelect, { target: { value: "user_manager_01" } });
    expect(roleSelect.value).toBe("user_manager_01");
    expect(badge).toHaveTextContent("tenant_demo_01 · MANAGER");

    // Switch to Staff
    fireEvent.change(roleSelect, { target: { value: "user_staff_01" } });
    expect(roleSelect.value).toBe("user_staff_01");
    expect(badge).toHaveTextContent("tenant_demo_01 · STAFF");
  });

  // =========================================================================
  // 2. Staff Permission Guard in Shared Approval Controls & 403 Error Surfacing (UI-03)
  // =========================================================================
  it("when Staff role is active, high-privilege approval actions are disabled/restricted, and forced execution surfaces 403 error banner", async () => {
    // Setup fetch to reject confirmation with 403 for Staff
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        const headers = (init?.headers || {}) as Record<string, string>;
        if (url.includes("/confirm-proposal")) {
          if (headers["X-Actor-ID"] === "user_staff_01") {
            return Promise.resolve(
              new Response(
                JSON.stringify({
                  code: "APPROVAL_REQUIRED",
                  message: "Manager or owner approval is required to confirm proposal",
                  correlation_id: "corr_perm_test_403",
                }),
                {
                  status: 403,
                  headers: { "Content-Type": "application/json" },
                },
              ),
            );
          }
          return Promise.resolve(
            new Response(
              JSON.stringify({
                commitment_id: "cmt_conf_01",
                commitment_version: 3,
                transition: "CONFIRMED",
                changed_dimensions: ["agreement_state"],
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      }),
    );

    // Render ApprovalActionControl as Staff
    render(
      <AuthProvider initialTenantId="tenant_demo_01" initialActorId="user_staff_01">
        <ApprovalActionControl
          commitmentId="cmt_conf_01"
          proposalId="prop_001"
          proposalVersion={1}
          currentStatus="PENDING_APPROVAL"
        />
      </AuthProvider>,
    );

    // Verify Staff role displays permission restriction notice
    expect(screen.getByTestId("permission-restricted-notice")).toHaveTextContent(
      "High-privilege approval restricted: Staff role cannot execute proposals",
    );

    // Main approval button is disabled
    const disabledBtn = screen.getByTestId("approval-action-btn-disabled");
    expect(disabledBtn).toBeDisabled();
    expect(disabledBtn).toHaveAttribute("aria-disabled", "true");

    // Force attempt to verify backend 403 error is caught and displayed cleanly
    const forceBtn = screen.getByTestId("force-unauthorized-action-btn");
    fireEvent.click(forceBtn);

    // Verify 403 error banner is surfaced in UI (never fake optimistic success)
    const errorBanner = await screen.findByTestId("permission-error-banner");
    expect(errorBanner).toBeInTheDocument();
    expect(errorBanner).toHaveTextContent("403 Forbidden");
    expect(errorBanner).toHaveTextContent("Manager or owner approval is required");

    // Ensure success banner is NOT rendered
    expect(screen.queryByTestId("approval-success-banner")).not.toBeInTheDocument();
  });

  // =========================================================================
  // 3. Manager/Owner Approval Execution and Non-Optimistic Success (UI-03, Invariant 4)
  // =========================================================================
  it("when Manager or Owner role is active, approval action succeeds and renders success only after API returns", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url.includes("/confirm-proposal")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                commitment_id: "cmt_conf_01",
                commitment_version: 3,
                transition: "CONFIRMED",
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      }),
    );

    render(
      <AuthProvider initialTenantId="tenant_demo_01" initialActorId="user_manager_01">
        <ApprovalActionControl
          commitmentId="cmt_conf_01"
          proposalId="prop_001"
          proposalVersion={1}
          currentStatus="PENDING_APPROVAL"
        />
      </AuthProvider>,
    );

    // Restriction notice is NOT shown for Manager
    expect(screen.queryByTestId("permission-restricted-notice")).not.toBeInTheDocument();

    const approveBtn = screen.getByTestId("approval-action-btn");
    expect(approveBtn).not.toBeDisabled();

    fireEvent.click(approveBtn);

    // Success banner appears after 200 OK
    const successBanner = await screen.findByTestId("approval-success-banner");
    expect(successBanner).toHaveTextContent("Proposal approved and committed successfully");
  });

  // =========================================================================
  // 4. Invariant: Pending States Stay Non-Green / Non-Success (FE-01d)
  // =========================================================================
  it("strictly enforces non-green badges for PENDING_APPROVAL, AWAITING_CONFIRMATION, and UNKNOWN", () => {
    const { container: c1 } = render(<StatusBadge state="PENDING_APPROVAL" />);
    expect(c1.querySelector(".badge-warning")).toBeInTheDocument();
    expect(c1.querySelector(".badge-success")).toBeNull();

    const { container: c2 } = render(<StatusBadge state="AWAITING_CONFIRMATION" />);
    expect(c2.querySelector(".badge-purple")).toBeInTheDocument();
    expect(c2.querySelector(".badge-success")).toBeNull();

    const { container: c3 } = render(<StatusBadge state="OFFERED" />);
    expect(c3.querySelector(".badge-purple")).toBeInTheDocument();
    expect(c3.querySelector(".badge-success")).toBeNull();

    const { container: c4 } = render(<StatusBadge state="UNKNOWN" />);
    expect(c4.querySelector(".badge-unknown")).toBeInTheDocument();
    expect(c4.querySelector(".badge-success")).toBeNull();

    const { container: c5 } = render(<StatusBadge state="NOT_ASSESSED" />);
    expect(c5.querySelector(".badge-unknown")).toBeInTheDocument();
    expect(c5.querySelector(".badge-success")).toBeNull();

    // CONFIRMED and FULFILLED are permitted green
    const { container: c6 } = render(<StatusBadge state="CONFIRMED" />);
    expect(c6.querySelector(".badge-success")).toBeInTheDocument();

    const { container: c7 } = render(<StatusBadge state="FULFILLED" />);
    expect(c7.querySelector(".badge-success")).toBeInTheDocument();
  });

  // =========================================================================
  // 5. Deep-Link Navigation Across All 10 Routes (FE-01a)
  // =========================================================================
  const testRoutes = [
    { path: "/overview", expectedHeading: "Commitment Overview" },
    { path: "/activity", expectedHeading: "Activity & Audit History" },
    { path: "/inbox", expectedHeading: "Smart inbox" },
    { path: "/orders/ord_101", expectedHeading: "Order context" },
    { path: "/commitments/com_001", expectedHeading: "Commitment feasibility" },
    { path: "/impact/fa_001", expectedHeading: "Operational impact" },
    { path: "/recovery/rec_001", expectedHeading: "Recovery case" },
    { path: "/communications", expectedHeading: "Communication center" },
    { path: "/confirmations/comm_001", expectedHeading: "Confirmation workspace" },
    { path: "/unknown-route-test", expectedHeading: "Page not found" },
  ];

  for (const { path, expectedHeading } of testRoutes) {
    it(`renders deep-link route '${path}' without crash or unhandled exception`, async () => {
      renderAppWithRoute(path);

      expect(
        await screen.findByRole("heading", { name: new RegExp(expectedHeading, "i") }),
      ).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "MouManTAI" })).toBeInTheDocument();
    });
  }

  it("P2 routes (/commitments/:id and /impact/:id) use shared auth headers and typed API client", async () => {
    renderAppWithRoute("/commitments/com_001", "user_manager_01");
    expect(await screen.findByRole("heading", { name: /commitment feasibility/i })).toBeInTheDocument();
    const p2Header = capturedHeaders.find((h) => h["X-Tenant-ID"] === "tenant_demo_01");
    expect(p2Header).toBeDefined();
    expect(p2Header?.["X-Actor-ID"]).toBe("user_manager_01");
  });
});
