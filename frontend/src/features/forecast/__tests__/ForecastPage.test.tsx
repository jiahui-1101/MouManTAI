import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../../../shared/auth";
import { ForecastPage } from "../ForecastPage";
import * as forecastApi from "../api";
import type { ForecastResponse } from "../types";

const mockForecastResponse: ForecastResponse = {
  tenant_id: "demo-tenant",
  sku_id: "SKU-PROD-A",
  available_skus: [
    { sku_id: "SKU-PROD-A", name: "Custom Artisan Pastry Box", category: "Bakery", unit: "boxes" },
    { sku_id: "SKU-PROD-B", name: "Specialty Sourdough Loaf", category: "Bakery", unit: "loaves" },
  ],
  unit: "boxes",
  target_definition: "accepted-order quantity by SKU and business day",
  status: "FORECAST_AVAILABLE",
  evidence_tier: "DEMO-ONLY",
  integration_mode: "SYNTHETIC",
  is_synthetic: true,
  demo_badge: true,
  training_cutoff: "2026-10-24",
  horizon: 7,
  model_name: "MOVING_AVERAGE",
  model_version: "1",
  run_id: "forecast-v2:mock-digest",
  generated_at: "2026-10-24T12:00:00Z",
  historical_points: [
    { period: "2026-10-18", quantity: 15, unit: "boxes", kind: "ACCEPTED", evidence_ref: "ev-1" },
    { period: "2026-10-19", quantity: 20, unit: "boxes", kind: "ACCEPTED", evidence_ref: "ev-2" },
    { period: "2026-10-20", quantity: 25, unit: "boxes", kind: "ACCEPTED", evidence_ref: "ev-3" },
    { period: "2026-10-21", quantity: 30, unit: "boxes", kind: "ACCEPTED", evidence_ref: "ev-4" },
    { period: "2026-10-22", quantity: 28, unit: "boxes", kind: "ACCEPTED", evidence_ref: "ev-5" },
    { period: "2026-10-23", quantity: 22, unit: "boxes", kind: "ACCEPTED", evidence_ref: "ev-6" },
    { period: "2026-10-24", quantity: 18, unit: "boxes", kind: "ACCEPTED", evidence_ref: "ev-7" },
  ],
  forecast_points: [
    { period: "2026-10-25", quantity: 22, unit: "boxes" },
    { period: "2026-10-26", quantity: 22, unit: "boxes" },
    { period: "2026-10-27", quantity: 22, unit: "boxes" },
    { period: "2026-10-28", quantity: 22, unit: "boxes" },
    { period: "2026-10-29", quantity: 22, unit: "boxes" },
    { period: "2026-10-30", quantity: 22, unit: "boxes" },
    { period: "2026-10-31", quantity: 22, unit: "boxes" },
  ],
  backtest_metrics: [
    {
      model_name: "MOVING_AVERAGE",
      model_version: "1",
      mae: { value: 1.714 },
      wape: { value: 0.428 },
      mase: { value: 1.238 },
      signed_bias: { value: 0 },
      evidence_coverage: 1,
      eligible_actuals: 7,
    },
    {
      model_name: "SEASONAL_NAIVE",
      model_version: "1",
      mae: { value: 2.142 },
      wape: { value: 0.535 },
      mase: { value: 1.547 },
      signed_bias: { value: 0.5 },
      evidence_coverage: 1,
      eligible_actuals: 7,
    },
  ],
  advisories: [
    {
      alert_id: "alert-1",
      family: "DEMAND",
      target_id: "SKU-PROD-A",
      period: "2026-10-25",
      status: "FUTURE_RISK_ADVISORY",
      exposure: "Baseline estimate of future accepted demand; not a confirmed order",
      unit: "boxes",
      evidence_tier: "DEMO-ONLY",
      integration_mode: "SYNTHETIC",
      uncertainty: "Uncalibrated baseline",
      missing_data: [],
      explanation_codes: ["BASELINE_DEMAND"],
      preparation_options: ["Review upcoming SKU pipeline"],
      required_human_review: true,
      operational_action_authorized: false,
    },
    {
      alert_id: "alert-2",
      family: "STOCKOUT_OR_EXPIRY",
      target_id: "SKU-PROD-A",
      period: "2026-10-25",
      status: "FUTURE_RISK_ADVISORY",
      exposure: "Inventory safety stock covers 14 days; lot #L-409 expires within 21 days",
      unit: "boxes",
      evidence_tier: "DEMO-ONLY",
      integration_mode: "SYNTHETIC",
      uncertainty: "Uncalibrated baseline",
      missing_data: [],
      explanation_codes: ["EXPIRY_WINDOW_APPROACHING"],
      preparation_options: ["Verify lot batches and reorder timing"],
      required_human_review: true,
      operational_action_authorized: false,
    },
    {
      alert_id: "alert-3",
      family: "SUPPLIER_DELAY",
      target_id: "SKU-PROD-A",
      period: "2026-10-25",
      status: "CONDITIONAL",
      exposure: "Supplier history and ETA require human review",
      unit: "boxes",
      evidence_tier: "DEMO-ONLY",
      integration_mode: "SYNTHETIC",
      uncertainty: "Descriptive history only",
      missing_data: [],
      explanation_codes: ["SUPPLIER_HISTORY_DESCRIPTIVE"],
      preparation_options: ["Request supplier ETA confirmation"],
      required_human_review: true,
      operational_action_authorized: false,
    },
    {
      alert_id: "alert-4",
      family: "CAPACITY_OR_DEADLINE",
      target_id: "SKU-PROD-A",
      period: "2026-10-25",
      status: "FUTURE_RISK_ADVISORY",
      exposure: "Capacity utilization projected at 78% on peak production days",
      unit: "boxes",
      evidence_tier: "DEMO-ONLY",
      integration_mode: "SYNTHETIC",
      uncertainty: "Uncalibrated baseline",
      missing_data: [],
      explanation_codes: ["CAPACITY_NORMAL"],
      preparation_options: ["Check line scheduling and buffer"],
      required_human_review: true,
      operational_action_authorized: false,
    },
  ],
  diagnostics: [],
  assumptions: ["MOVING_AVERAGE algorithm; observed accepted daily demand only"],
  limitations: ["Planning guidance only; not a confirmed booking or reservation."],
  disclaimer:
    "DEMO-ONLY: This forecast is derived from synthetic baseline mechanics. It does not demonstrate real-world predictive accuracy. Forecast advisories NEVER mutate authoritative inventory or trigger automated recovery actions.",
};

describe("ForecastPage Component", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
    vi.spyOn(forecastApi, "fetchForecasts").mockResolvedValue(mockForecastResponse);
  });

  const renderComponent = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider initialTenantId="demo-tenant" initialActorId="user_manager_01">
          <ForecastPage />
        </AuthProvider>
      </QueryClientProvider>
    );

  it("renders page header, title, and demo-only badge", async () => {
    renderComponent();

    expect(await screen.findByRole("heading", { name: "Forecast & Planning", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText(/Demo-Only • Synthetic/i)).toBeInTheDocument();
  });

  it("renders the clean Refresh action button", async () => {
    renderComponent();

    const refreshBtn = await screen.findByRole("button", { name: "Refresh" });
    expect(refreshBtn).toBeInTheDocument();
    expect(refreshBtn).toHaveClass("btn-forecast-refresh");
  });

  it("renders the 4 KPI stat cards correctly", async () => {
    renderComponent();

    // 7 days * 22 = 154 boxes projected demand
    expect(await screen.findByText("Projected Horizon Demand")).toBeInTheDocument();
    expect(screen.getByText("154 boxes")).toBeInTheDocument();

    expect(screen.getByText("Average Daily Run-Rate")).toBeInTheDocument();
    expect(screen.getByText("22.0 boxes/d")).toBeInTheDocument();

    expect(screen.getByText("Forward Risk Advisories")).toBeInTheDocument();
    expect(screen.getByText("4 Active")).toBeInTheDocument();

    expect(screen.getByText("Model Retrospective MAE")).toBeInTheDocument();
    expect(screen.getByText("1.71")).toBeInTheDocument();
  });

  it("renders all 4 Proactive Risk Family Cards", async () => {
    renderComponent();

    expect(await screen.findByText("Demand Volatility & Trend")).toBeInTheDocument();
    expect(screen.getByText("Stockout & Expiry Exposure")).toBeInTheDocument();
    expect(screen.getByText("Supplier Lead-Time Risk")).toBeInTheDocument();
    expect(screen.getByText("Capacity & Workload Bottleneck")).toBeInTheDocument();

    // Verify non-operational guardrail notes are visible
    const notices = screen.getAllByText(/Does not modify inventory or auto-approve actions/i);
    expect(notices.length).toBe(4);
  });

  it("renders the visual demand chart with cutoff and legend", async () => {
    renderComponent();

    expect(await screen.findByText("Demand Projection & Historical Actuals")).toBeInTheDocument();
    expect(screen.getByText("Historical Accepted")).toBeInTheDocument();
    expect(screen.getByText(/Cutoff \(2026-10-24\)/i)).toBeInTheDocument();
  });

  it("allows switching tabs to view Backtest Comparison, History Log, and Provenance", async () => {
    renderComponent();

    // Initial tab: Backtest
    expect(await screen.findByText(/Retrospective Holdout Performance/i)).toBeInTheDocument();
    expect(screen.getByText("MOVING_AVERAGE")).toBeInTheDocument();
    expect(screen.getByText("SEASONAL_NAIVE")).toBeInTheDocument();

    // Switch to History tab
    fireEvent.click(screen.getByRole("button", { name: /Observed Demand History/i }));
    expect(screen.getByText(/Accepted Order History by Business Day/i)).toBeInTheDocument();
    expect(screen.getByText("2026-10-18")).toBeInTheDocument();
    expect(screen.getByText("15 boxes")).toBeInTheDocument();

    // Switch to Provenance tab
    fireEvent.click(screen.getByRole("button", { name: /Audit, Assumptions & Provenance/i }));
    expect(screen.getByText("Run Identifier")).toBeInTheDocument();
    expect(screen.getByText("forecast-v2:mock-digest")).toBeInTheDocument();
  });

  it("triggers refetch when changing SKU or Planning Horizon", async () => {
    renderComponent();

    await screen.findByText("Forecast & Planning");

    const horizonSelect = screen.getByLabelText("Planning Horizon");
    fireEvent.change(horizonSelect, { target: { value: "14" } });

    await waitFor(() => {
      expect(forecastApi.fetchForecasts).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ horizon: 14 })
      );
    });
  });
});
