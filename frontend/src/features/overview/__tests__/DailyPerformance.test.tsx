import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../../shared/auth";
import type { OverviewResponse } from "../../../shared/types";
import { DailyPerformancePage } from "../DailyPerformance";

const mockOverviewData: OverviewResponse = {
  tenant_id: "tenant_alpha",
  actor_id: "user_owner_01",
  actor_role: "OWNER",
  integration_mode: "SYNTHETIC",
  last_updated_at: "2026-10-24T08:00:00Z",
  counts: {
    requested: 1,
    confirmed: 2,
    at_risk: 1,
    pending_approval: 0,
    execution_in_progress: 0,
    awaiting_confirmation: 0,
    fulfilled: 1,
  },
  attention_queue: [],
  commitments: [
    {
      commitment_id: "cmt_due_01",
      order_id: "ord_101",
      customer_id: "cust_bk",
      terms: {
        sku: "BURGER_BOX_M",
        quantity: "5000",
        unit: "PIECES",
        deadline: "2026-10-24T18:00:00Z",
      },
      agreement_state: "CONFIRMED",
      feasibility_state: "FEASIBLE",
      risk_state: "NORMAL",
      recovery_state: "NONE",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 1,
      evidence_refs: [],
      updated_at: "2026-10-24T08:00:00Z",
    },
    {
      commitment_id: "cmt_fulfilled_02",
      order_id: "ord_102",
      customer_id: "cust_mcd",
      terms: {
        sku: "FRY_CUP_L",
        quantity: "2000",
        unit: "PIECES",
        deadline: "2026-10-24T12:00:00Z",
      },
      agreement_state: "CONFIRMED",
      feasibility_state: "FEASIBLE",
      risk_state: "NORMAL",
      recovery_state: "NONE",
      fulfilment_state: "FULFILLED",
      commitment_version: 2,
      evidence_refs: ["ev_delivery_proof_102"],
      updated_at: "2026-10-24T12:00:00Z",
    },
    {
      commitment_id: "cmt_risk_03",
      order_id: "ord_103",
      customer_id: "cust_kfc",
      terms: {
        sku: "BUCKET_REG",
        quantity: "1500",
        unit: "PIECES",
        deadline: "2026-10-25T14:00:00Z",
      },
      agreement_state: "CONFIRMED",
      feasibility_state: "FEASIBLE",
      risk_state: "AT_RISK",
      recovery_state: "NONE",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 1,
      evidence_refs: [],
      updated_at: "2026-10-24T08:00:00Z",
    },
  ],
};

function renderDailyPerformance(initialActorId = "user_owner_01") {
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
      <AuthProvider initialTenantId="tenant_alpha" initialActorId={initialActorId}>
        <BrowserRouter>
          <DailyPerformancePage />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("FE-FB-02: DailyPerformancePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders transparency header, DEMO-ONLY / SYNTHETIC badge, and R-08 coverage gap notice", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockOverviewData), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    renderDailyPerformance();

    // Await active tenant to ensure page loaded
    const activeTenant = await screen.findByTestId("active-tenant");
    expect(activeTenant).toHaveTextContent("tenant_alpha");
    expect(screen.getByTestId("active-role")).toHaveTextContent("OWNER");

    // Verify synthetic badge
    const badge = screen.getByTestId("synthetic-badge");
    expect(badge).toHaveTextContent("DEMO-ONLY / SYNTHETIC");

    // Verify R-08 Missing Coverage Gap Banner
    const coverageBanner = screen.getByTestId("coverage-gap-banner");
    expect(coverageBanner).toBeInTheDocument();
    expect(coverageBanner).toHaveTextContent("Coverage Gap (R-08 MISSING)");
    expect(coverageBanner).toHaveTextContent("Authoritative Daily Workload Summary Not Measured");
    expect(screen.getByTestId("not-measured-badge")).toHaveTextContent("NOT MEASURED");
  });

  it("derives orders due, completed on-time, and incomplete from authoritative commitments", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockOverviewData), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    renderDailyPerformance();

    await screen.findByTestId("milestone-metrics-grid");

    // Total orders due: 3 commitments
    expect(screen.getByTestId("metric-orders-due")).toHaveTextContent("3");
    // Completed on-time: 1 (cmt_fulfilled_02)
    expect(screen.getByTestId("metric-completed-on-time")).toHaveTextContent("1");
    // Incomplete: 2 (cmt_due_01 and cmt_risk_03)
    expect(screen.getByTestId("metric-incomplete")).toHaveTextContent("2");

    // Evidenced fulfilment rate: 1 of 3 = 33%
    expect(screen.getByTestId("metric-completion-rate")).toHaveTextContent("33%");

    // Verify table renders all rows
    expect(screen.getByTestId("performance-row-cmt_due_01")).toBeInTheDocument();
    expect(screen.getByTestId("performance-row-cmt_fulfilled_02")).toBeInTheDocument();
    expect(screen.getByTestId("performance-row-cmt_risk_03")).toBeInTheDocument();

    // Verify planned vs unmeasured workload tag
    expect(screen.getAllByText(/Unmeasured/).length).toBeGreaterThan(0);
  });

  it("toggles between Day View and Week View", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockOverviewData), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    renderDailyPerformance();

    const dayBtn = await screen.findByTestId("view-mode-day");
    const weekBtn = screen.getByTestId("view-mode-week");

    expect(dayBtn).toHaveClass("active");
    expect(weekBtn).not.toHaveClass("active");

    fireEvent.click(weekBtn);
    expect(weekBtn).toHaveClass("active");
    expect(dayBtn).not.toHaveClass("active");
  });

  it("executes one-click Report Completed: asserts COMPLETION_REPORTED != FULFILLED invariant", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockOverviewData), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    renderDailyPerformance("user_staff_01");

    await screen.findByTestId("performance-row-cmt_due_01");

    // Click Report Completed on cmt_due_01
    const reportBtn = screen.getByTestId("report-completed-cmt_due_01");
    fireEvent.click(reportBtn);

    // Modal opens
    const modal = screen.getByTestId("report-completed-modal");
    expect(modal).toBeInTheDocument();

    // Verify non-negotiable guardrail disclaimer
    const disclaimer = screen.getByTestId("invariant-disclaimer");
    expect(disclaimer).toHaveTextContent("COMPLETION_REPORTED ≠ FULFILLED");
    expect(disclaimer).toHaveTextContent("does not verify customer fulfilment or release escrow/funds");

    // Submit report notice
    const submitBtn = screen.getByTestId("submit-report-completed");
    fireEvent.click(submitBtn);

    // Modal closes and row reflects COMPLETION_REPORTED status badge
    await waitFor(() => {
      expect(screen.queryByTestId("report-completed-modal")).not.toBeInTheDocument();
    });

    const statusBadge = screen.getByTestId("status-reported");
    expect(statusBadge).toHaveTextContent("COMPLETION_REPORTED");

    // Crucial: fulfilment verification still says "Awaiting Logistics Proof", NOT verified
    expect(screen.getByText("⚠️ Awaiting Logistics Proof")).toBeInTheDocument();
    expect(screen.getByTestId("reported-badge-cmt_due_01")).toBeInTheDocument();
  });

  it("handles loading skeleton state", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    renderDailyPerformance();

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByTestId("loading-skeleton")).toBeInTheDocument();
  });

  it("handles empty state when no commitments are registered", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ...mockOverviewData,
            counts: { ...mockOverviewData.counts, requested: 0, confirmed: 0, at_risk: 0, fulfilled: 0 },
            commitments: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    renderDailyPerformance();

    expect(await screen.findByTestId("empty-performance-state")).toBeInTheDocument();
    expect(screen.getByText("No Orders Due in Period")).toBeInTheDocument();
    // Does NOT display fake 0% completion rate
    expect(screen.getByTestId("metric-completion-rate")).toHaveTextContent("Rate unmeasured");
  });

  it("handles API error with retry", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => {
        calls++;
        if (calls === 1) {
          return Promise.resolve(
            new Response(JSON.stringify({ message: "Network failure" }), {
              status: 500,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify(mockOverviewData), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );

    renderDailyPerformance();

    expect(await screen.findByTestId("error-state")).toBeInTheDocument();
    const retryBtn = screen.getByTestId("retry-button");
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByTestId("metric-orders-due")).toHaveTextContent("3");
    });
  });

  it("handles 403 Forbidden state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ code: "FORBIDDEN", message: "Actor has insufficient role permissions" }),
          { status: 403, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    renderDailyPerformance();

    expect(await screen.findByTestId("permission-denied-state")).toHaveTextContent(
      "403 FORBIDDEN",
    );
    expect(screen.getByText("403 FORBIDDEN")).toBeInTheDocument();
  });
});
