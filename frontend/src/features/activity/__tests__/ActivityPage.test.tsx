import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../../shared/auth";
import type { Commitment, TimelineEntry } from "../../../shared/types";
import { ActivityPage } from "../ActivityPage";

const mockCommitmentsList: Commitment[] = [
  {
    tenant_id: "tenant_demo_01",
    commitment_id: "cmt_risk_01",
    order_id: "ord_101",
    customer_id: "cust_gamma",
    terms: {
      sku: "SKU-PROD-C",
      quantity: "200",
      unit: "units",
      deadline: "2026-10-24T18:00:00Z",
    },
    agreement_state: "CONFIRMED",
    feasibility_state: "INFEASIBLE",
    risk_state: "AT_RISK",
    recovery_state: "PLANNING",
    fulfilment_state: "NOT_STARTED",
    commitment_version: 3,
    evidence_refs: ["doc_risk_01"],
    updated_at: "2026-10-21T01:30:00Z",
  },
];

const mockTimelineData: TimelineEntry[] = [
  {
    entry_id: "entry_01",
    occurred_at: "2026-10-21T01:00:00Z",
    actor_id: "user_staff_01",
    actor_role: "STAFF",
    source_feature: "F1_CONTEXT",
    event_type: "context.message_received",
    action: "Supplier delay notice received via WhatsApp",
    previous_state: null,
    new_state: {
      order_id: "ord_101",
      sku: "SKU-PROD-C",
      margin: "[REDACTED_FOR_STAFF]",
    },
    commitment_version: 1,
    correlation_id: "corr_delay_999",
    causation_id: null,
    context_id: "ord_101",
    evidence_refs: ["msg_wa_001"],
  },
  {
    entry_id: "entry_02",
    occurred_at: "2026-10-21T01:10:00Z",
    actor_id: "system",
    actor_role: "SYSTEM",
    source_feature: "F2_FEASIBILITY",
    event_type: "commitment.at_risk",
    action: "Feasibility engine flagged delivery breach risk",
    previous_state: {
      agreement_state: "CONFIRMED",
      risk_state: "NORMAL",
      commitment_version: 1,
    },
    new_state: {
      agreement_state: "CONFIRMED",
      risk_state: "AT_RISK",
      commitment_version: 2,
    },
    commitment_version: 2,
    correlation_id: "corr_delay_999",
    causation_id: "entry_01",
    assessment_id: "asm_eval_01",
    evidence_refs: ["eval_log_002"],
  },
  {
    entry_id: "entry_03",
    occurred_at: "2026-10-21T01:20:00Z",
    actor_id: "system",
    actor_role: "SYSTEM",
    source_feature: "F3_RECOVERY",
    event_type: "recovery.plan_generated",
    action: "Generated split delivery recovery plan",
    previous_state: {
      recovery_state: "NONE",
      commitment_version: 2,
    },
    new_state: {
      recovery_state: "PLANNING",
      plan_version: 1,
      commitment_version: 2,
    },
    commitment_version: 2,
    correlation_id: "corr_delay_999",
    causation_id: "entry_02",
    recovery_case_id: "rec_case_001",
    evidence_refs: ["plan_doc_003"],
  },
  {
    entry_id: "entry_04",
    occurred_at: "2026-10-21T01:30:00Z",
    actor_id: "user_manager_01",
    actor_role: "MANAGER",
    source_feature: "CORE",
    event_type: "commitment.proposal_offered",
    action: "Manager signed off split delivery recovery terms",
    previous_state: {
      recovery_state: "PLANNING",
      commitment_version: 2,
    },
    new_state: {
      recovery_state: "APPROVED",
      proposal_version: 1,
      commitment_version: 3,
    },
    commitment_version: 3,
    correlation_id: "corr_delay_999",
    causation_id: "entry_03",
    approval_reason: "Approved split shipment within authorized RM500 threshold",
    proposal_id: "prop_rev_001",
    evidence_refs: ["approval_sig_004"],
  },
  {
    entry_id: "entry_05",
    occurred_at: "2026-10-21T01:45:00Z",
    actor_id: "system",
    actor_role: "SYSTEM",
    source_feature: "F4_COMMUNICATION",
    event_type: "commitment.confirmed",
    action: "Customer confirmed revised delivery proposal",
    previous_state: {
      agreement_state: "OFFERED",
      commitment_version: 3,
    },
    new_state: {
      agreement_state: "CONFIRMED",
      commitment_version: 4,
    },
    commitment_version: 4,
    correlation_id: "corr_delay_999",
    causation_id: "entry_04",
    communication_id: "comm_conf_001",
    proposal_id: "prop_rev_001",
    evidence_refs: ["cust_sign_005"],
  },
];

function renderActivity(options: {
  initialUrl?: string;
  initialActorId?: string;
  queryClient?: QueryClient;
} = {}) {
  const client =
    options.queryClient ??
    new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          refetchOnWindowFocus: false,
        },
      },
    });

  const url = options.initialUrl ?? "/activity?commitment_id=cmt_risk_01";

  return render(
    <QueryClientProvider client={client}>
      <AuthProvider
        initialTenantId="tenant_demo_01"
        initialActorId={options.initialActorId ?? "user_owner_01"}
      >
        <MemoryRouter initialEntries={[url]}>
          <ActivityPage />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("ActivityPage (FE-03a–d, UI-02)", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url.includes("/v1/commitments") && !url.includes("/timeline")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockCommitmentsList), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        if (url.includes("/timeline") || url.includes("/v1/audit")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockTimelineData), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify({}), {
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

  it("renders chronological timeline entries with state transition badges, version changes, actor role, and approval reason", async () => {
    renderActivity();

    // Verify all 5 timeline entries are displayed
    const entries = await screen.findAllByTestId("timeline-entry");
    expect(entries).toHaveLength(5);

    // Verify feature badges across features
    expect(screen.getByText("F1 Context")).toBeInTheDocument();
    expect(screen.getByText("F2 Feasibility")).toBeInTheDocument();
    expect(screen.getByText("F3 Recovery")).toBeInTheDocument();
    expect(screen.getByText("F4 Communication")).toBeInTheDocument();
    expect(screen.getByText("Core")).toBeInTheDocument();

    // Verify state transition diff: CONFIRMED -> AT_RISK
    const transitionContainers = screen.getAllByTestId("state-transitions");
    expect(transitionContainers.length).toBeGreaterThan(0);
    const atRiskTransition = transitionContainers.find(
      (c) => c.textContent?.includes("CONFIRMED") && c.textContent?.includes("AT RISK"),
    );
    expect(atRiskTransition).toBeDefined();

    // Verify version change badge
    expect(screen.getByText("v1 → v2")).toBeInTheDocument();

    // Verify actor roles displayed
    expect(screen.getAllByText("MANAGER").length).toBeGreaterThan(0);
    expect(screen.getAllByText("STAFF").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SYSTEM").length).toBeGreaterThan(0);

    // Verify human approval reason and governance callout
    const governanceHighlight = screen.getByTestId("governance-highlight");
    expect(governanceHighlight).toBeInTheDocument();
    expect(governanceHighlight).toHaveTextContent(
      "Approved split shipment within authorized RM500 threshold",
    );
    expect(governanceHighlight).toHaveTextContent("user_manager_01");
  });

  it("renders correlation chain grouping and deep links to /orders/:id, /impact/:id, /recovery/:id, and /confirmations/:id", async () => {
    renderActivity();

    // Wait for entries to render
    await screen.findAllByTestId("timeline-entry");

    // Verify correlation ID is visible and rendered
    const corrCodes = screen.getAllByText("corr_delay_999");
    expect(corrCodes.length).toBeGreaterThan(0);

    // Verify causation chain link
    expect(screen.getByText("entry_01")).toBeInTheDocument();
    expect(screen.getByText("entry_02")).toBeInTheDocument();

    // Verify deep links to F1-F4
    const deepLinksContainer = screen.getAllByTestId("deep-links-row");
    expect(deepLinksContainer.length).toBeGreaterThan(0);

    const f1Link = screen.getByRole("link", { name: /F1 Order \(ord_101\)/i });
    expect(f1Link).toHaveAttribute("href", "/orders/ord_101");

    const f2Link = screen.getByRole("link", { name: /F2 Feasibility \(asm_eval_01\)/i });
    expect(f2Link).toHaveAttribute("href", "/impact/asm_eval_01");

    const f3Link = screen.getByRole("link", { name: /F3 Recovery \(rec_case_001\)/i });
    expect(f3Link).toHaveAttribute("href", "/recovery/rec_case_001");

    const f4Link = screen.getByRole("link", { name: /F4 Confirmation \(comm_conf_001\)/i });
    expect(f4Link).toHaveAttribute("href", "/confirmations/comm_conf_001");

    // Verify evidence refs are rendered
    expect(screen.getByText("#msg_wa_001")).toBeInTheDocument();
    expect(screen.getByText("#eval_log_002")).toBeInTheDocument();
    expect(screen.getByText("#approval_sig_004")).toBeInTheDocument();
    expect(screen.getByText("#cust_sign_005")).toBeInTheDocument();

    // Switch to Group by Correlation view
    const groupToggleBtn = screen.getByRole("button", { name: /Group by Correlation/i });
    fireEvent.click(groupToggleBtn);

    expect(screen.getByText(/Causal Chain:/i)).toBeInTheDocument();
    expect(screen.getByText(/5 correlated events in trace/i)).toBeInTheDocument();
  });

  it("shows role-redacted summary indicator when viewing as Staff", async () => {
    renderActivity({ initialActorId: "user_staff_01" });

    // Wait for load
    await screen.findAllByTestId("timeline-entry");

    // Verify role-redacted indicators are visible
    const redactedIndicators = screen.getAllByTestId("redacted-indicator");
    expect(redactedIndicators.length).toBeGreaterThan(0);

    // Verify banner explains redactions for Staff role
    expect(screen.getByText(/Redacted for role \(Staff\):/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Redacted for role/i).length).toBeGreaterThan(0);
  });

  it("handles Loading, Empty, Error + Retry, and 403 states properly", async () => {
    // 1. Loading state
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(new Promise(() => {})),
    );

    const { unmount } = renderActivity();
    expect(screen.getByTestId("loading-skeleton")).toBeInTheDocument();
    unmount();

    // 2. Empty state
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url.includes("/v1/commitments") && !url.includes("/timeline")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockCommitmentsList), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );

    const emptyRender = renderActivity();
    expect(await emptyRender.findByTestId("empty-activity")).toHaveTextContent(
      "No Activity Records Found",
    );
    emptyRender.unmount();

    // 3. Error + Retry state
    let callCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        callCount++;
        if (callCount <= 2) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ code: "AUDIT_FETCH_FAILED", message: "Audit backend timeout" }),
              {
                status: 500,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        if (url.includes("/timeline")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockTimelineData), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );

    const errorRender = renderActivity();
    expect(await errorRender.findByTestId("error-state")).toHaveTextContent("Audit backend timeout");

    // Click Retry
    const retryBtn = errorRender.getByRole("button", { name: /Retry/i });
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(errorRender.getAllByTestId("timeline-entry").length).toBe(5);
    });
    errorRender.unmount();

    // 4. 403 Permission Denied state
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ code: "FORBIDDEN", message: "Actor has insufficient role permissions" }),
            {
              status: 403,
              headers: { "Content-Type": "application/json" },
            },
          ),
        ),
      ),
    );

    const forbiddenRender = renderActivity();
    expect(await forbiddenRender.findByTestId("permission-denied-state")).toHaveTextContent(
      "403 FORBIDDEN",
    );
    expect(forbiddenRender.getByText("Permission Denied")).toBeInTheDocument();
    expect(
      forbiddenRender.getByRole("button", { name: /Manager \(MANAGER\)/i }),
    ).toBeInTheDocument();
  });
});
