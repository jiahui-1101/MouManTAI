import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../../layout/AppShell";
import { FeaturePlaceholder } from "../../pages/FeaturePlaceholder";
import { OverviewPage } from "../../features/overview/OverviewPage";
import { ActivityPage } from "../../features/activity/ActivityPage";
import { DailyPerformancePage } from "../../features/overview/DailyPerformance";
import { SupplierComparisonPage, SupplierDetailPage, SupplierDirectoryPage } from "../../features/suppliers/SupplierWorkspace";
import { RecoveryPage } from "../../features/recovery/RecoveryPage";
import { RecoveryCaseRoutePage } from "../../features/recovery/RecoveryCaseRoutePage";
import { AuthProvider } from "../../shared/auth";
import { ApprovalActionControl } from "../../shared/ApprovalActionControl";
import { StatusBadge } from "../../shared/StatusBadge";
import { EvidenceTierBadge } from "../../shared/EvidenceTierBadge";
import type { OverviewResponse } from "../../shared/types";

const mockOverview: OverviewResponse = {
  tenant_id: "tenant_demo_01",
  actor_id: "user_owner_01",
  actor_role: "OWNER",
  integration_mode: "SYNTHETIC",
  last_updated_at: "2026-10-24T02:00:00Z",
  counts: {
    requested: 1,
    confirmed: 3,
    at_risk: 1,
    pending_approval: 1,
    execution_in_progress: 1,
    awaiting_confirmation: 2,
    fulfilled: 1,
  },
  attention_queue: [
    {
      commitment_id: "cmt_risk_01",
      order_id: "ord_101",
      category: "MANUAL_REVIEW",
      severity: "CRITICAL",
      summary: "Commitment cmt_risk_01 is BREACHED; supplier delayed raw material",
      deep_link_path: "/recovery/cmt_risk_01",
      updated_at: "2026-10-24T01:30:00Z",
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
        sku: "BURGER_BUN",
        quantity: "500",
        unit: "packs",
        deadline: "2026-10-25T12:00:00Z",
      },
      evidence_refs: ["ev_sign_01"],
      updated_at: "2026-10-24T01:00:00Z",
    },
    {
      commitment_id: "cmt_risk_01",
      order_id: "ord_101",
      customer_id: "cust_002",
      agreement_state: "CONFIRMED",
      feasibility_state: "INFEASIBLE",
      risk_state: "BREACHED",
      recovery_state: "PLANNING",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 3,
      terms: {
        sku: "BURGER_PATTY",
        quantity: "1000",
        unit: "boxes",
        deadline: "2026-10-24T18:00:00Z",
      },
      evidence_refs: ["ev_risk_01"],
      updated_at: "2026-10-24T01:30:00Z",
    },
  ],
};

const mockAuditEvents = [
  {
    audit_id: "aud_01",
    event_id: "evt_01",
    event_type: "commitment.confirmed",
    tenant_id: "tenant_demo_01",
    commitment_id: "cmt_conf_01",
    actor_id: "user_manager_01",
    actor_role: "MANAGER",
    dimension: "agreement",
    previous_state: { agreement_state: "OFFERED" },
    new_state: { agreement_state: "CONFIRMED" },
    evidence_refs: ["ev_sign_01"],
    reason: "Proposal accepted by customer",
    correlation_id: "corr_01",
    occurred_at: "2026-10-24T01:00:00Z",
  },
  {
    audit_id: "aud_02",
    event_id: "evt_02",
    event_type: "recovery.plan_approved",
    tenant_id: "tenant_demo_01",
    commitment_id: "cmt_risk_01",
    actor_id: "user_owner_01",
    actor_role: "OWNER",
    dimension: "recovery",
    previous_state: { recovery_state: "PLANNING" },
    new_state: { recovery_state: "APPROVED_AWAITING_EXECUTION" },
    evidence_refs: ["ev_plan_01"],
    reason: "Alternative supplier plan approved",
    correlation_id: null, // missing correlation ID for R-09 test
    occurred_at: "2026-10-24T02:00:00Z",
  },
];

function renderFullHarness(initialRoute = "/overview", initialActorId = "user_owner_01") {
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
              <Route path="/commitments/:id" element={<FeaturePlaceholder owner="P2 · Feasibility" title="Commitment feasibility" />} />
              <Route path="/impact/:id" element={<FeaturePlaceholder owner="P2 · Feasibility" title="Operational impact" />} />
              <Route path="/recovery/:id" element={<RecoveryCaseRoutePage />} />
              <Route path="/recovery/:id/plans" element={<RecoveryPage />} />
              <Route path="/recovery" element={<FeaturePlaceholder owner="Recovery" title="Emergency Cases" />} />
              <Route path="/recovery/plans" element={<FeaturePlaceholder owner="Recovery" title="Recovery Plans" />} />
              <Route path="/suppliers" element={<SupplierDirectoryPage />} />
              <Route path="/suppliers/compare" element={<SupplierComparisonPage />} />
              <Route path="/supplier-comparison" element={<SupplierComparisonPage />} />
              <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
              <Route path="/communications" element={<FeaturePlaceholder owner="P4 · Communication" title="Communication center" />} />
              <Route path="/confirmations/:id" element={<FeaturePlaceholder owner="P4 · Communication" title="Confirmation workspace" />} />
              <Route path="/communications/follow-ups" element={<FeaturePlaceholder owner="P4 · Communication" title="Follow-up queue" />} />
              <Route path="/insights/performance" element={<DailyPerformancePage />} />
              <Route path="/performance" element={<DailyPerformancePage />} />
              <Route path="/insights/history" element={<FeaturePlaceholder owner="Insights" title="Decision History" />} />
              <Route path="/calendar" element={<FeaturePlaceholder owner="Shared shell" title="Calendar" />} />
              <Route path="/orders" element={<FeaturePlaceholder owner="Orders" title="All Orders" />} />
              <Route path="/orders/pending" element={<FeaturePlaceholder owner="Orders" title="Pending Acceptance" />} />
              <Route path="/planning/feasibility" element={<FeaturePlaceholder owner="Planning" title="Feasibility" />} />
              <Route path="/planning/portfolio" element={<FeaturePlaceholder owner="Planning" title="Portfolio Comparison" />} />
              <Route path="/planning/forecasts" element={<FeaturePlaceholder owner="Planning" title="Forecasts" />} />
              <Route path="/settings" element={<FeaturePlaceholder owner="Settings" title="Settings" />} />
              <Route path="*" element={<FeaturePlaceholder owner="Shared shell" title="Page not found" />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("Phase 5 — Full UAT Journey & Integration Harness (FE-UAT-01..15)", () => {
  let capturedHeaders: Record<string, string>[] = [];

  beforeEach(() => {
    capturedHeaders = [];
    window.localStorage.clear();
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

        if (url.includes("/v1/audit")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockAuditEvents), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        if (url.includes("/v1/commitments")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockOverview.commitments), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        if (url.includes("/v1/recovery/cases/")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                case_id: "case_risk_01",
                commitment_id: "cmt_risk_01",
                disruption_type: "SUPPLIER_DELAY",
                severity: "HIGH",
                status: "EVALUATED",
                changed_facts: ["Supplier delayed raw material by 4 days"],
                affected_commitments: ["cmt_risk_01"],
                options: [
                  {
                    plan_id: "plan_alt_01",
                    plan_version: 1,
                    summary: "Engage alternative local supplier",
                    status: "CONDITIONAL",
                    feasible: true,
                    estimated_cost: "RM 2,400.00",
                    side_effects: ["Higher unit cost by 15%"],
                    preconditions: ["Purchase order approved by manager"],
                    evidence_refs: ["ev_alt_quote"],
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
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. Navigation Traversal & Deep Linking Across All Domain Routes
  // =========================================================================
  it("traverses Overview, Daily Performance, Activity, Suppliers, and Recovery without regression", async () => {
    // 1. Overview Page
    renderFullHarness("/overview");
    expect(await screen.findByRole("heading", { name: /commitment overview/i })).toBeInTheDocument();
    expect(await screen.findByTestId("active-tenant")).toHaveTextContent("tenant_demo_01");
    expect(screen.getByTestId("synthetic-badge")).toHaveTextContent(/DEMO-ONLY/i);
    expect(screen.getByTestId("synthetic-badge")).toHaveTextContent(/SYNTHETIC/i);

    // 7 Lifecycle metrics truthfully present
    expect(screen.getByText("Requested")).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText("At Risk")).toBeInTheDocument();
    expect(screen.getByText("Pending Approval")).toBeInTheDocument();
    expect(screen.getByText("Execution in Progress")).toBeInTheDocument();
    expect(screen.getByText("Awaiting Confirmation")).toBeInTheDocument();
    expect(screen.getByText("Fulfilled")).toBeInTheDocument();

    // Verify subnav links exist
    expect(screen.getByTestId("daily-performance-link")).toHaveAttribute("href", "/insights/performance");
    expect(screen.getByTestId("activity-history-link")).toHaveAttribute("href", "/activity");
  });

  it("loads Daily Performance page with Day/Week view and R-08 coverage gap notice", async () => {
    renderFullHarness("/insights/performance");
    expect(await screen.findByRole("heading", { name: /daily performance/i })).toBeInTheDocument();
    expect(await screen.findByTestId("view-mode-day")).toBeInTheDocument();
    expect(screen.getByTestId("view-mode-week")).toBeInTheDocument();

    // R-08 coverage notice
    expect(screen.getByTestId("coverage-gap-banner")).toBeInTheDocument();
    expect(screen.getByTestId("coverage-gap-banner")).toHaveTextContent(/Coverage Gap \(R-08 MISSING\)/i);
    expect(screen.getByTestId("not-measured-badge")).toHaveTextContent(/NOT MEASURED/i);

    // Honest workload cards show Unmeasured
    expect(screen.getByRole("columnheader", { name: "Planned Workload" })).toBeInTheDocument();
    expect(screen.getAllByText(/\[Unmeasured\]/i).length).toBeGreaterThan(0);

    // Report completed button strictly maintains COMPLETION_REPORTED != FULFILLED
    const reportBtn = screen.getByTestId("report-completed-cmt_conf_01");
    expect(reportBtn).toBeInTheDocument();
    fireEvent.click(reportBtn);

    // Modal dialog pops up enforcing the invariant disclaimer
    expect(await screen.findByTestId("report-completed-modal")).toBeInTheDocument();
    expect(screen.getByTestId("invariant-disclaimer")).toHaveTextContent(/COMPLETION_REPORTED ≠ FULFILLED/i);

    // Confirm reporting
    const submitBtn = screen.getByTestId("submit-report-completed");
    fireEvent.click(submitBtn);

    // Row status updates to reported badge
    expect(await screen.findByTestId("reported-badge-cmt_conf_01")).toHaveTextContent(/Notice Recorded/i);
  });

  it("loads Activity & Audit History with causal filters and linear fallback note for R-09", async () => {
    renderFullHarness("/activity");
    expect(await screen.findByRole("heading", { name: /activity & audit history/i })).toBeInTheDocument();

    // Multi-filter controls
    expect(await screen.findByTestId("customer-filter")).toBeInTheDocument();
    expect(screen.getByTestId("supplier-filter")).toBeInTheDocument();
    expect(screen.getByTestId("incident-filter")).toBeInTheDocument();
    expect(screen.getByTestId("date-filter")).toBeInTheDocument();

    // R-09 partial correlation fallback notice
    expect(screen.getByTestId("correlation-fallback-note")).toBeInTheDocument();
    expect(screen.getByTestId("correlation-fallback-note")).toHaveTextContent(/Cross-feature causal correlation unavailable/i);
  });

  it("loads Supplier Workspace and enforces disabled selection under missing R-05 contract", async () => {
    renderFullHarness("/suppliers");
    expect(await screen.findByRole("heading", { name: /supplier directory/i })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Supplier data unavailable");
    expect(screen.queryByText("Example Packaging Co.")).not.toBeInTheDocument();

    cleanup();

    // Navigate to Comparison
    renderFullHarness("/suppliers/compare");
    expect(await screen.findByRole("heading", { name: /offer comparison/i })).toBeInTheDocument();

    // Selection buttons disabled with R-05 pending note
    const disabledButtons = screen.getAllByRole("button", { name: /Select supplier \(unavailable\)/i });
    expect(disabledButtons.length).toBeGreaterThan(0);
    disabledButtons.forEach((btn) => {
      expect(btn).toBeDisabled();
    });
    expect(screen.getByText(/Selection is unavailable: no approved versioned offer-selection command/i)).toBeInTheDocument();
  });

  it("loads placeholder pages with honest status pills and alternative destination links", async () => {
    // Emergency cases placeholder
    renderFullHarness("/recovery");
    expect(await screen.findByRole("heading", { name: /emergency cases/i })).toBeInTheDocument();
    expect(screen.getByTestId("placeholder-status-pill")).toHaveTextContent(/BACKEND CONTRACT PENDING \(R-06\)/i);
    expect(screen.getByRole("link", { name: /View Commitment Recovery Case \(rec_001\)/i })).toHaveAttribute("href", "/recovery/rec_001");

    cleanup();

    // Decision history placeholder
    renderFullHarness("/insights/history");
    expect(await screen.findByRole("heading", { name: /decision history/i })).toBeInTheDocument();
    expect(screen.getByTestId("placeholder-status-pill")).toHaveTextContent(/PROPOSED FEATURE \(FE-MEM-01 \/ R-11\)/i);
    expect(screen.getByRole("link", { name: /View Activity & Audit History/i })).toHaveAttribute("href", "/activity");

    cleanup();

    // 404 Route
    renderFullHarness("/nonexistent-route-for-testing");
    expect(await screen.findByRole("heading", { name: /page not found/i })).toBeInTheDocument();
    expect(screen.getByTestId("placeholder-status-pill")).toHaveTextContent(/404 NOT FOUND/i);
  });

  // =========================================================================
  // 2. Role Simulation & Permission Denial (403) Handling
  // =========================================================================
  it("enforces staff permission restrictions and displays accessible 403 denial alert", async () => {
    let rejectPermission: ((response: Response) => void) | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url.includes("/confirm-proposal")) {
          return new Promise<Response>((resolve) => {
            rejectPermission = resolve;
          });
        }
        return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      }),
    );

    // Render approval action with STAFF role
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

    // Staff sees restricted notice and disabled button
    expect(screen.getByTestId("permission-restricted-notice")).toHaveTextContent(
      /requires Manager or Owner/i,
    );
    const disabledApproveBtn = screen.getByTestId("approval-action-btn-disabled");
    expect(disabledApproveBtn).toBeDisabled();

    // Verify 403 response surfaces clean alert without crashing
    const forceBtn = screen.getByTestId("force-unauthorized-action-btn");
    fireEvent.click(forceBtn);
    expect(screen.getByRole("status")).toHaveTextContent("Request in progress");

    rejectPermission!(
      new Response(
        JSON.stringify({
          code: "APPROVAL_REQUIRED",
          message: "Manager or owner approval is required to confirm proposal",
          correlation_id: "corr_perm_denial_403",
        }),
        {
          status: 403,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const alertBanner = await screen.findByRole("alert");
    expect(alertBanner).toHaveTextContent("Access denied");
  });

  // =========================================================================
  // 3. Truthfulness, Invariants, and Evidence Tiers (FE-01d)
  // =========================================================================
  it("strictly enforces non-green badges for pending/uncertain states and truthfulness tags", () => {
    // Invariant: PENDING_APPROVAL and AWAITING_CONFIRMATION must never be green
    const { container: c1 } = render(<StatusBadge state="PENDING_APPROVAL" />);
    expect(c1.querySelector(".badge-warning")).toBeInTheDocument();
    expect(c1.querySelector(".badge-success")).toBeNull();

    const { container: c2 } = render(<StatusBadge state="AWAITING_CONFIRMATION" />);
    expect(c2.querySelector(".badge-purple")).toBeInTheDocument();
    expect(c2.querySelector(".badge-success")).toBeNull();

    const { container: c3 } = render(<StatusBadge state="UNKNOWN" />);
    expect(c3.querySelector(".badge-unknown")).toBeInTheDocument();
    expect(c3.querySelector(".badge-success")).toBeNull();

    // EvidenceTierBadge renders readable text labels and does not rely on color alone
    const { container: c4 } = render(
      <EvidenceTierBadge evidenceTier="DEMO-ONLY" integrationMode="SYNTHETIC" />,
    );
    expect(within(c4).getByText("DEMO-ONLY")).toBeInTheDocument();
    expect(within(c4).getByText("SYNTHETIC")).toBeInTheDocument();
  });
});
