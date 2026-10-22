import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../../shared/auth";
import { RecoveryPage } from "../RecoveryPage";
import type { RecoveryCase, RecoveryPlanVersion } from "../types";

function plan(overrides: Partial<RecoveryPlanVersion> = {}): RecoveryPlanVersion {
  return {
    tenant_id: "tenant_demo_01",
    recovery_case_id: "rc_001",
    plan_id: "plan_a",
    plan_version: 1,
    commitment_id: "com_001",
    based_on_assessment_id: "fa_001",
    snapshot_version: 142,
    feasibility_status: "CONDITIONAL",
    estimated_extra_cost: "80.00",
    currency: "MYR",
    estimated_delay_minutes: 0,
    risks: ["ALTERNATIVE_SUPPLY_PENDING"],
    actions: [],
    approval_state: "PENDING",
    execution_state: "NOT_STARTED",
    option_id: "option_a",
    strategy: "ALTERNATIVE_SUPPLY",
    risk_level: "HIGH",
    customer_impact: "LOW",
    affected_commitment_count: 1,
    operational_disruption_level: "1",
    supplier_uncertainty_level: "4",
    customer_confirmation_required: false,
    constraints: ["Supplier availability is not confirmed"],
    evidence_refs: ["ev_supplier_003"],
    assumptions: ["An alternative supplier can offer the shortage before cutoff."],
    ranking_score: "11.60",
    recommended: true,
    recommendation_reason: "Preference-based ranking",
    evaluation: {
      evaluation_id: "eval_plan_a_v1",
      tenant_id: "tenant_demo_01",
      commitment_id: "com_001",
      plan_id: "plan_a",
      plan_version: 1,
      commitment_version: 3,
      snapshot_version: 142,
      feasibility_status: "CONDITIONAL",
      validation_source: "TEST_DOUBLE_VALIDATED",
      readiness: "CONDITIONAL",
      solver_status: "COMPLETED",
      constraints: ["Supplier availability is not confirmed"],
      hard_constraint_reasons: [],
      affected_commitment_ids: ["com_001"],
      evidence_refs: ["ev_supplier_003"],
      assumptions: ["An alternative supplier can offer the shortage before cutoff."],
      evaluated_at: "2026-10-21T10:05:00+08:00",
    },
    ...overrides,
  };
}

function recoveryCase(): RecoveryCase {
  return {
    case_id: "rc_001",
    tenant_id: "tenant_demo_01",
    commitment_id: "com_001",
    case_version: 1,
    commitment_version: 3,
    status: "OPEN",
    commitment: {
      tenant_id: "tenant_demo_01",
      commitment_id: "com_001",
      order_id: "ord_001",
      customer_id: "cust_001",
      terms: { sku: "BURGER", quantity: "100", unit: "pcs", deadline: "2026-10-24T15:00:00+08:00" },
      agreement_state: "CONFIRMED",
      feasibility_state: "CONDITIONAL",
      risk_state: "AT_RISK",
      recovery_state: "COMPLETED",
      fulfilment_state: "NOT_STARTED",
      commitment_version: 3,
      evidence_refs: ["ev_confirm_001"],
      updated_at: "2026-10-21T14:00:00+08:00",
    },
    trigger_assessment: {
      assessment_id: "fa_001",
      tenant_id: "tenant_demo_01",
      commitment_id: "com_001",
      commitment_version: 2,
      snapshot_version: 142,
      status: "INFEASIBLE",
      constraints: [{ code: "MATERIAL_SHORTAGE", resource_id: "PACKAGING", shortage: "20", unit: "pcs", deadline: "2026-10-24T12:00:00+08:00", severity: "HARD", evidence_refs: ["ev_stock_001"] }],
      affected_commitment_ids: ["com_001"],
      evidence_refs: ["ev_stock_001", "ev_supplier_003"],
      solver_status: "COMPLETED",
      assumptions: [],
      assessed_at: "2026-10-21T10:05:00+08:00",
    },
    operational_snapshot: { snapshot_id: "snap_142", snapshot_version: 142, captured_at: "2026-10-21T10:00:00+08:00", source: "SYNTHETIC_ERP", evidence_refs: ["ev_stock_001"] },
    preferences: {
      cost_weight: "2",
      delay_weight: "4",
      affected_commitments_weight: "5",
      operational_disruption_weight: "3",
      supplier_uncertainty_weight: "4",
      customer_confirmation_weight: "3",
    },
    options: [],
    plans: [],
    approval_decisions: [],
    customer_confirmation_evidence_refs: ["ev_customer_accept_001"],
    fulfilment_evidence_refs: ["fev_001"],
    evidence_refs: ["ev_stock_001", "ev_supplier_003"],
    storage_mode: "IN_MEMORY_SYNTHETIC",
    created_at: "2026-10-21T10:00:00+08:00",
    updated_at: "2026-10-21T10:00:00+08:00",
  };
}

function renderPage(path = "/recovery/com_001") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes><Route path="/recovery/:id" element={<RecoveryPage />} /></Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

describe("P3 recovery page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders actual API options, conditional status, evidence, and no fake execution", async () => {
    const caseData = recoveryCase();
    const plans = [
      plan({ recommendation_label: "RECOMMENDED_UNDER_POLICY" }),
      plan({ plan_id: "plan_b", option_id: "option_b", strategy: "RESCHEDULE_PARTIAL_FULFILMENT", feasibility_status: "FEASIBLE", estimated_extra_cost: "0.00", estimated_delay_minutes: 1440, risk_level: "MEDIUM", customer_impact: "MEDIUM", recommended: true, recommendation_label: null }),
    ];
    vi.stubGlobal("fetch", vi.fn((url: string | URL | Request) => {
      const path = url.toString();
      if (path.endsWith("/plans")) return response({ tenant_id: "tenant_demo_01", commitment_id: "com_001", case_id: "rc_001", plans });
      return response(caseData);
    }));

    renderPage();
    expect(await screen.findByRole("heading", { name: /recovery workspace/i })).toBeInTheDocument();
    expect(await screen.findByTestId("recovery-plan-plan_a")).toBeInTheDocument();
    expect(screen.getByText("CONDITIONAL")).toBeInTheDocument();
    expect(screen.getByText("MYR 80.00")).toBeInTheDocument();
    expect(screen.getByText("RECOMMENDED UNDER POLICY")).toBeInTheDocument();
    expect(screen.queryByText("Recommended under current preferences")).not.toBeInTheDocument();
    expect(screen.getAllByText("ev_supplier_003").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId("select-plan_a"));
    expect(screen.getByTestId("execution-gate")).toHaveTextContent(/no approval or execution action is available/i);
    expect(screen.queryByText(/execution succeeded/i)).not.toBeInTheDocument();
  });

  it("shows loading and blocks invalid selection", async () => {
    let resolveCase: ((value: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => { resolveCase = resolve; });
    vi.stubGlobal("fetch", vi.fn(() => pending));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(/loading recovery case/i);
    resolveCase?.(new Response(JSON.stringify(recoveryCase()), { status: 403 }));
    expect(await screen.findByTestId("recovery-permission-error")).toBeInTheDocument();
  });

  it("shows the persisted trigger-only case while trusted planning inputs are pending", async () => {
    const fetchMock = vi.fn((url: string | URL | Request) => {
      if (url.toString().endsWith("/trigger")) return response({
        case_id: "rc_trigger_01", tenant_id: "tenant_demo_01", commitment_id: "com_001",
        case_version: 1, commitment_version: 3, status: "AWAITING_EVALUATION_INPUTS",
        evaluation_readiness: "AWAITING_EVALUATION_INPUTS",
        missing_evaluation_inputs: ["AUTHORITATIVE_OPERATIONAL_SNAPSHOT"],
        trigger_events: [{ event_id: "evt_risk_01", assessment_id: "fa_risk_01" }],
        resolution_events: [], storage_mode: "DURABLE_DATABASE",
        created_at: "2026-10-22T10:00:00Z", updated_at: "2026-10-22T10:00:00Z",
      });
      return response({ code: "RECOVERY_EVALUATION_INPUTS_PENDING", message: "Inputs pending" }, 409);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    expect(await screen.findByText(/Recovery evaluation inputs are pending/i)).toBeInTheDocument();
    expect(screen.getByText(/evt_risk_01/)).toBeInTheDocument();
    expect(screen.getByText(/AUTHORITATIVE_OPERATIONAL_SNAPSHOT/)).toBeInTheDocument();
    expect(screen.queryByText(/execution succeeded/i)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url.toString().endsWith("/plans"))).toBe(false);
  });

  it("marks a stale infeasible option and prevents selecting it", async () => {
    const caseData = recoveryCase();
    const staleInvalid = plan({ plan_id: "plan_bad", option_id: "option_bad", feasibility_status: "INFEASIBLE", snapshot_version: 141 });
    vi.stubGlobal("fetch", vi.fn((url: string | URL | Request) => {
      if (url.toString().endsWith("/plans")) {
        return response({ tenant_id: "tenant_demo_01", commitment_id: "com_001", case_id: "rc_001", plans: [staleInvalid] });
      }
      return response(caseData);
    }));

    renderPage();
    expect(await screen.findByText("STALE EVALUATION")).toBeInTheDocument();
    expect(screen.getByTestId("select-plan_bad")).toBeDisabled();
  });

  it("renders a deterministic supplier-delay walkthrough without calling the API or claiming outcomes", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderPage("/recovery/demo");
    expect(await screen.findByRole("heading", { name: /supplier delay · compare two responses/i })).toBeInTheDocument();
    expect(screen.getByText(/synthetic data only/i)).toBeInTheDocument();
    expect(screen.getByText(/no policy recommendation is calculated/i)).toBeInTheDocument();
    expect(screen.getByText(/request 20 units from an alternative supplier/i)).toBeInTheDocument();
    expect(screen.getByText(/propose delivery one day later/i)).toBeInTheDocument();
    expect(screen.getByText("CONDITIONAL")).toBeInTheDocument();
    expect(screen.getByText(/acceptance is required before terms change/i)).toBeInTheDocument();
    expect(screen.queryByText("APPROVED")).not.toBeInTheDocument();
    expect(screen.queryByText("SUCCEEDED")).not.toBeInTheDocument();
    expect(screen.queryByText(/fulfilled/i)).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getAllByRole("button", { name: /discuss this trade-off/i })[0]);
    expect(screen.getByTestId("recovery-demo-decision-prompt")).toHaveTextContent(/would an authorized manager accept the estimated MYR 80 premium/i);
    expect(screen.getByTestId("recovery-demo-decision-prompt")).toHaveTextContent(/records no manager decision/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("suppresses in-memory seeded approvals and labels test-double validation", async () => {
    const caseData = recoveryCase();
    caseData.approval_decisions = [{
      approval_id: "seed_approval",
      tenant_id: "tenant_demo_01",
      commitment_id: "com_001",
      plan_id: "plan_a",
      plan_version: 1,
      snapshot_version: 142,
      actor_id: "user_manager_01",
      actor_role: "MANAGER",
      action_scope: ["CREATE_PURCHASE_REQUEST"],
      decision: "APPROVED",
      reason: "Synthetic seed row",
      evidence_refs: ["ev_manager_approval_001"],
      audit_refs: [],
      persistence_mode: "IN_MEMORY_NON_DURABLE",
    }];
    vi.stubGlobal("fetch", vi.fn((url: string | URL | Request) => {
      if (url.toString().endsWith("/plans")) return response({ tenant_id: "tenant_demo_01", commitment_id: "com_001", case_id: "rc_001", plans: [plan()] });
      return response(caseData);
    }));

    renderPage();
    expect(await screen.findByText(/in-memory seed decisions are intentionally omitted/i)).toBeInTheDocument();
    expect(screen.queryByText(/APPROVED · plan_a/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/test[- ]double result/i).length).toBeGreaterThan(0);
  });
});
