import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../../shared/auth";
import type { OverviewResponse } from "../../../shared/types";
import { OverviewPage } from "../OverviewPage";

const mockOverviewData: OverviewResponse = {
  tenant_id: "tenant_demo_01",
  actor_id: "user_owner_01",
  actor_role: "OWNER",
  integration_mode: "SYNTHETIC",
  last_updated_at: "2026-10-21T02:00:00Z",
  counts: {
    requested: 3,
    confirmed: 5,
    at_risk: 2,
    pending_approval: 1,
    execution_in_progress: 1,
    awaiting_confirmation: 2,
    fulfilled: 4,
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
    {
      commitment_id: "cmt_exec_02",
      order_id: "system",
      category: "FAILED_EXECUTION",
      severity: "HIGH",
      summary: "Event evt_99 failed: dispatch retry timeout",
      deep_link_path: "/activity?commitment_id=cmt_exec_02",
      updated_at: "2026-10-21T01:45:00Z",
    },
  ],
  commitments: [
    {
      commitment_id: "cmt_req_01",
      order_id: "ord_001",
      customer_id: "cust_alpha",
      agreement_state: "REQUESTED",
      feasibility_state: "UNKNOWN",
      risk_state: "NORMAL",
      recovery_state: "NONE",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 1,
      terms: {
        sku: "SKU-PROD-A",
        quantity: "100",
        unit: "units",
        deadline: "2026-10-25T10:00:00Z",
        special_instructions: "Urgent delivery",
      },
      evidence_refs: ["doc_req_01"],
      updated_at: "2026-10-21T01:00:00Z",
    },
    {
      commitment_id: "cmt_conf_01",
      order_id: "ord_002",
      customer_id: "cust_beta",
      agreement_state: "CONFIRMED",
      feasibility_state: "FEASIBLE",
      risk_state: "NORMAL",
      recovery_state: "NONE",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 2,
      terms: {
        sku: "SKU-PROD-B",
        quantity: "50",
        unit: "boxes",
        deadline: "2026-10-26T12:00:00Z",
      },
      evidence_refs: ["doc_conf_01"],
      updated_at: "2026-10-21T01:10:00Z",
    },
    {
      commitment_id: "cmt_risk_01",
      order_id: "ord_101",
      customer_id: "cust_gamma",
      agreement_state: "CONFIRMED",
      feasibility_state: "INFEASIBLE",
      risk_state: "AT_RISK",
      recovery_state: "PLANNING",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 3,
      terms: {
        sku: "SKU-PROD-C",
        quantity: "200",
        unit: "units",
        deadline: "2026-10-24T18:00:00Z",
      },
      evidence_refs: ["doc_risk_01"],
      updated_at: "2026-10-21T01:20:00Z",
    },
    {
      commitment_id: "cmt_appr_01",
      order_id: "ord_102",
      customer_id: "cust_delta",
      agreement_state: "CONFIRMED",
      feasibility_state: "CONDITIONAL",
      risk_state: "AT_RISK",
      recovery_state: "PENDING_APPROVAL",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 2,
      terms: {
        sku: "SKU-PROD-D",
        quantity: "75",
        unit: "packs",
        deadline: "2026-10-25T15:00:00Z",
      },
      evidence_refs: ["doc_appr_01"],
      updated_at: "2026-10-21T01:25:00Z",
    },
    {
      commitment_id: "cmt_offered_01",
      order_id: "ord_103",
      customer_id: "cust_epsilon",
      agreement_state: "OFFERED",
      feasibility_state: "FEASIBLE",
      risk_state: "NORMAL",
      recovery_state: "NONE",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 2,
      terms: {
        sku: "SKU-PROD-E",
        quantity: "120",
        unit: "units",
        deadline: "2026-10-27T09:00:00Z",
      },
      evidence_refs: ["doc_prop_01"],
      updated_at: "2026-10-21T01:30:00Z",
    },
    {
      commitment_id: "cmt_fulf_01",
      order_id: "ord_104",
      customer_id: "cust_zeta",
      agreement_state: "CONFIRMED",
      feasibility_state: "FEASIBLE",
      risk_state: "NORMAL",
      recovery_state: "COMPLETED",
      fulfilment_state: "FULFILLED",
      commitment_version: 4,
      terms: {
        sku: "SKU-PROD-F",
        quantity: "300",
        unit: "pieces",
        deadline: "2026-10-22T17:00:00Z",
      },
      evidence_refs: ["doc_deliv_01"],
      updated_at: "2026-10-21T01:35:00Z",
    },
  ],
};

function renderOverview(queryClient?: QueryClient) {
  const client =
    queryClient ??
    new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          refetchOnWindowFocus: false,
        },
      },
    });

  return render(
    <QueryClientProvider client={client}>
      <AuthProvider initialTenantId="tenant_demo_01" initialActorId="user_owner_01">
        <MemoryRouter>
          <OverviewPage />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("OverviewPage (FE-02a–e, UI-01)", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockOverviewData), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders all 7 state bucket counts and attention queue items from GET /v1/overview response", async () => {
    renderOverview();

    // Verify 7 authoritative state counts
    expect(await screen.findByTestId("count-requested")).toHaveTextContent("3");
    expect(screen.getByTestId("count-confirmed")).toHaveTextContent("5");
    expect(screen.getByTestId("count-at_risk")).toHaveTextContent("2");
    expect(screen.getByTestId("count-pending_approval")).toHaveTextContent("1");
    expect(screen.getByTestId("count-execution_in_progress")).toHaveTextContent("1");
    expect(screen.getByTestId("count-awaiting_confirmation")).toHaveTextContent("2");
    expect(screen.getByTestId("count-fulfilled")).toHaveTextContent("4");

    // Verify attention queue items
    const attentionItems = screen.getAllByTestId("attention-item");
    expect(attentionItems).toHaveLength(2);

    expect(
      screen.getByText(/Commitment cmt_risk_01 is BREACHED; supplier delayed raw material/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Event evt_99 failed: dispatch retry timeout/)).toBeInTheDocument();

    // Verify KL timestamps on attention items (contains MYT)
    const timeElements = document.querySelectorAll(".attention-time");
    expect(timeElements.length).toBeGreaterThanOrEqual(2);
    expect(timeElements[0]?.textContent).toContain("(MYT)");

    // Verify deep links in attention queue
    const links = screen.getAllByTestId("attention-deep-link");
    expect(links[0]).toHaveAttribute("href", "/commitments/cmt_risk_01");
    expect(links[1]).toHaveAttribute("href", "/activity?commitment_id=cmt_exec_02");
  });

  it("displays SYNTHETIC badge, active tenant, and actor role", async () => {
    renderOverview();

    expect(await screen.findByTestId("synthetic-badge")).toHaveTextContent("SYNTHETIC");
    expect(screen.getByTestId("active-tenant")).toHaveTextContent("tenant_demo_01");
    expect(screen.getByTestId("active-role")).toHaveTextContent("OWNER");

    // Actor select allows switching simulated role
    const actorSelect = screen.getByTestId("actor-select") as HTMLSelectElement;
    expect(actorSelect.value).toBe("user_owner_01");

    fireEvent.change(actorSelect, { target: { value: "user_staff_01" } });
    expect(actorSelect.value).toBe("user_staff_01");
  });

  it("filtering by state bucket updates visible commitments and deep links point to valid routes", async () => {
    renderOverview();

    // Initially all 6 commitments are visible in table
    expect(await screen.findByTestId("commitment-row-cmt_req_01")).toBeInTheDocument();
    expect(screen.getByTestId("commitment-row-cmt_conf_01")).toBeInTheDocument();
    expect(screen.getByTestId("commitment-row-cmt_risk_01")).toBeInTheDocument();
    expect(screen.getByTestId("commitment-row-cmt_appr_01")).toBeInTheDocument();
    expect(screen.getByTestId("commitment-row-cmt_offered_01")).toBeInTheDocument();
    expect(screen.getByTestId("commitment-row-cmt_fulf_01")).toBeInTheDocument();

    // Click on "At Risk" card
    fireEvent.click(screen.getByTestId("card-at_risk"));

    // Only at-risk commitment should be visible
    expect(screen.getByTestId("commitment-row-cmt_risk_01")).toBeInTheDocument();
    expect(screen.queryByTestId("commitment-row-cmt_req_01")).not.toBeInTheDocument();
    expect(screen.queryByTestId("commitment-row-cmt_conf_01")).not.toBeInTheDocument();

    // Check deep links
    const inspectLink = screen.getByTestId("inspect-link-cmt_risk_01");
    expect(inspectLink).toHaveAttribute("href", "/commitments/cmt_risk_01");

    const activityLink = screen.getByTestId("activity-link-cmt_risk_01");
    expect(activityLink).toHaveAttribute("href", "/activity?commitment_id=cmt_risk_01");

    // Filter by search query
    fireEvent.change(screen.getByTestId("commitment-search-input"), {
      target: { value: "SKU-PROD-C" },
    });
    expect(screen.getByTestId("commitment-row-cmt_risk_01")).toBeInTheDocument();

    // Search for non-existent item shows empty state
    fireEvent.change(screen.getByTestId("commitment-search-input"), {
      target: { value: "NONEXISTENT-SKU" },
    });
    expect(screen.queryByTestId("commitment-row-cmt_risk_01")).not.toBeInTheDocument();
    expect(screen.getByTestId("empty-commitments-state")).toBeInTheDocument();
  });

  it("renders loading skeleton while query is resolving", () => {
    // Unresolved promise simulates in-flight request
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    renderOverview();

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByTestId("loading-skeleton")).toBeInTheDocument();
  });

  it("renders empty state when tenant has zero commitments", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ...mockOverviewData,
            counts: {
              requested: 0,
              confirmed: 0,
              at_risk: 0,
              pending_approval: 0,
              execution_in_progress: 0,
              awaiting_confirmation: 0,
              fulfilled: 0,
            },
            attention_queue: [],
            commitments: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    renderOverview();

    expect(await screen.findByTestId("attention-queue-empty")).toBeInTheDocument();
    expect(screen.getByTestId("empty-commitments-state")).toBeInTheDocument();
    expect(screen.getByText(/zero commitments registered/i)).toBeInTheDocument();
  });

  it("renders API error state with a working retry callback", async () => {
    let callCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => {
        callCount++;
        if (callCount === 1) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ code: "SERVICE_UNAVAILABLE", message: "Database connection failed" }),
              { status: 500, headers: { "Content-Type": "application/json" } },
            ),
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

    renderOverview();

    // Verify error state is shown
    expect(await screen.findByTestId("error-state")).toBeInTheDocument();
    expect(screen.getByText(/Database connection failed/)).toBeInTheDocument();

    // Click retry
    const retryBtn = screen.getByTestId("retry-button");
    fireEvent.click(retryBtn);

    // Verify data loads after successful retry
    await waitFor(() => {
      expect(screen.getByTestId("count-requested")).toHaveTextContent("3");
    });
  });

  it("renders 403 Permission Denied state accurately", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: "FORBIDDEN",
            message: "Role is not authorized to inspect tenant overview",
          }),
          { status: 403, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    renderOverview();

    expect(await screen.findByTestId("permission-denied-state")).toBeInTheDocument();
    expect(screen.getByText("403 FORBIDDEN")).toBeInTheDocument();
    expect(screen.getByText("Access Denied")).toBeInTheDocument();
    expect(screen.getByText(/is not permitted to access this tenant/)).toBeInTheDocument();
  });

  it("overview refresh after lifecycle mutations updates bucket counts and attention queue (UI-01)", async () => {
    // Stage 1: Initial Confirmed state
    const stage1Data: OverviewResponse = {
      ...mockOverviewData,
      counts: {
        requested: 1,
        confirmed: 5,
        at_risk: 0,
        pending_approval: 0,
        execution_in_progress: 0,
        awaiting_confirmation: 0,
        fulfilled: 0,
      },
      attention_queue: [],
    };

    // Stage 2: After disruption mutation (confirmed -> at_risk + pending_approval)
    const stage2Data: OverviewResponse = {
      ...mockOverviewData,
      counts: {
        requested: 1,
        confirmed: 4,
        at_risk: 1,
        pending_approval: 1,
        execution_in_progress: 0,
        awaiting_confirmation: 0,
        fulfilled: 0,
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
    };

    // Stage 3: After operational delivery verified (fulfilled: 1)
    const stage3Data: OverviewResponse = {
      ...mockOverviewData,
      counts: {
        requested: 1,
        confirmed: 4,
        at_risk: 0,
        pending_approval: 0,
        execution_in_progress: 0,
        awaiting_confirmation: 0,
        fulfilled: 1,
      },
      attention_queue: [],
    };

    let currentStage = 1;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => {
        const payload = currentStage === 1 ? stage1Data : currentStage === 2 ? stage2Data : stage3Data;
        return Promise.resolve(
          new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );

    renderOverview();

    // Verify Stage 1 initial counts
    expect(await screen.findByTestId("count-confirmed")).toHaveTextContent("5");
    expect(screen.getByTestId("count-at_risk")).toHaveTextContent("0");
    expect(screen.getByTestId("count-fulfilled")).toHaveTextContent("0");
    expect(screen.getByTestId("attention-queue-empty")).toBeInTheDocument();

    // Trigger Stage 2 lifecycle mutation and manual refresh
    currentStage = 2;
    const refreshBtn = screen.getByTestId("refresh-button");
    fireEvent.click(refreshBtn);

    // Verify Stage 2 counts updated dynamically
    await waitFor(() => {
      expect(screen.getByTestId("count-confirmed")).toHaveTextContent("4");
      expect(screen.getByTestId("count-at_risk")).toHaveTextContent("1");
      expect(screen.getByTestId("count-pending_approval")).toHaveTextContent("1");
    });
    expect(
      screen.getByText(/Commitment cmt_risk_01 is BREACHED; supplier delayed raw material/),
    ).toBeInTheDocument();

    // Trigger Stage 3 fulfilment mutation and manual refresh
    currentStage = 3;
    fireEvent.click(refreshBtn);

    // Verify Stage 3 counts updated
    await waitFor(() => {
      expect(screen.getByTestId("count-at_risk")).toHaveTextContent("0");
      expect(screen.getByTestId("count-fulfilled")).toHaveTextContent("1");
    });

    // Verify role switch refetches and reflects active role
    const actorSelect = screen.getByTestId("actor-select");
    fireEvent.change(actorSelect, { target: { value: "user_staff_01" } });
    await waitFor(() => {
      expect(screen.getByTestId("active-role")).toHaveTextContent("OWNER"); // mock returns OWNER
    });
  });

  it("renders calibrated DEMO-ONLY / SYNTHETIC badge and subnav links to Daily Performance and Activity (FE-FOUND-01)", async () => {
    renderOverview();

    // Verify badge
    const badge = await screen.findByTestId("synthetic-badge");
    expect(badge).toHaveTextContent("DEMO-ONLY / SYNTHETIC");

    // Verify subnav links
    const perfLink = screen.getByTestId("daily-performance-link");
    expect(perfLink).toBeInTheDocument();
    expect(perfLink).toHaveAttribute("href", "/insights/performance");

    const actLink = screen.getByTestId("activity-history-link");
    expect(actLink).toBeInTheDocument();
    expect(actLink).toHaveAttribute("href", "/activity");
  });
});
