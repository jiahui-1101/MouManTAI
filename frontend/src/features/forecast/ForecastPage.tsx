import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../shared/auth";
import { fetchForecasts } from "./api";
import { ForecastChart } from "./ForecastChart";
import { AdvisoryRiskCards } from "./AdvisoryRiskCards";
import { ModelBacktestTable } from "./ModelBacktestTable";
import type { ForecastFilterParams, ForecastResponse } from "./types";
import "./forecast.css";

export const ForecastPage: React.FC = () => {
  const { authHeaders: auth } = useAuth();

  const [skuId, setSkuId] = useState<string>("SKU-PROD-A");
  const [horizon, setHorizon] = useState<number>(7);
  const [model, setModel] = useState<"moving_average" | "seasonal_naive" | "naive">("moving_average");
  const [mode, setMode] = useState<"auto" | "synthetic" | "db">("auto");

  const queryParams: ForecastFilterParams = {
    skuId,
    horizon,
    model,
    mode,
  };

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery<ForecastResponse>({
    queryKey: ["forecasts", auth.tenantId, skuId, horizon, model, mode],
    queryFn: () => fetchForecasts(auth, queryParams),
    staleTime: 30000,
  });

  // KPI calculations
  const totalForecastDemand = (data?.forecast_points ?? []).reduce(
    (sum, p) => sum + (typeof p.quantity === "number" ? p.quantity : parseFloat(String(p.quantity)) || 0),
    0
  );
  const dailyRunRate = data?.horizon ? (totalForecastDemand / data.horizon).toFixed(1) : "—";
  const activeAdvisoriesCount = data?.advisories?.length ?? 0;
  const bestMae = data?.backtest_metrics?.[0]?.mae?.value;
  const maeDisplay = bestMae !== null && bestMae !== undefined ? Number(bestMae).toFixed(2) : "—";

  return (
    <div className="forecast-page">
      {/* Page Header */}
      <div className="forecast-header">
        <div className="forecast-title-group">
          <div className="forecast-heading-row">
            <h1 className="forecast-title">Forecast & Planning</h1>
            {data?.demo_badge ? (
              <span className="badge-demo">Demo-Only • Synthetic</span>
            ) : data?.status === "INSUFFICIENT_HISTORY" ? (
              <span className="badge-demo" style={{ background: "#FEE2E2", color: "#DC2626", borderColor: "#FCA5A5" }}>
                Insufficient History
              </span>
            ) : (
              <span className="badge-live">Live Baseline • Target</span>
            )}
          </div>
          <p className="forecast-subtitle">
            Evidence-gated baseline demand projections, stockout exposure, and human-advisory risk scenarios.
          </p>
        </div>

        <div className="forecast-header-actions">
          <button
            className="btn-forecast-secondary"
            onClick={() => void refetch()}
            disabled={isFetching}
            title="Refresh latest forecast"
          >
            <span>🔄</span> {isFetching ? "Calculating..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Prominent Evidence / Uncertainty Disclaimer Banner */}
      {data && (
        <div className={`forecast-disclaimer-banner ${data.is_synthetic ? "" : "live-mode"}`}>
          <div className="banner-icon">{data.is_synthetic ? "⚠️" : "ℹ️"}</div>
          <div className="banner-content">
            <strong>
              {data.is_synthetic
                ? "SYNTHETIC DEMO BASELINE — Mechanics Demonstration Only"
                : "AUTHORITATIVE SME BASELINE — Pure Derived Guidance"}
            </strong>
            <p>{data.disclaimer}</p>
          </div>
        </div>
      )}

      {/* Control Filter Bar */}
      <div className="forecast-controls-card">
        <div className="forecast-filter-group">
          <div className="forecast-field">
            <label htmlFor="forecast-sku-select">Target SKU</label>
            <select
              id="forecast-sku-select"
              className="forecast-select"
              value={skuId}
              onChange={(e) => setSkuId(e.target.value)}
            >
              {(data?.available_skus ?? [
                { sku_id: "SKU-PROD-A", name: "Custom Artisan Pastry Box", category: "Bakery", unit: "boxes" },
                { sku_id: "SKU-PROD-B", name: "Specialty Sourdough Loaf", category: "Bakery", unit: "loaves" },
                { sku_id: "SKU-PACK-01", name: "Eco Gift Packaging 250g", category: "Packaging", unit: "packs" },
                { sku_id: "SKU-RAW-FLOUR", name: "Organic Stoneground Wheat Flour", category: "Raw Material", unit: "kg" },
              ]).map((sku) => (
                <option key={sku.sku_id} value={sku.sku_id}>
                  {sku.sku_id} — {sku.name}
                </option>
              ))}
            </select>
          </div>

          <div className="forecast-field">
            <label htmlFor="forecast-horizon-select">Planning Horizon</label>
            <select
              id="forecast-horizon-select"
              className="forecast-select"
              style={{ minWidth: 120 }}
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
            >
              <option value={7}>7 Days Ahead</option>
              <option value={14}>14 Days Ahead</option>
              <option value={21}>21 Days Ahead</option>
              <option value={30}>30 Days Ahead</option>
            </select>
          </div>

          <div className="forecast-field">
            <label htmlFor="forecast-model-select">Baseline Algorithm</label>
            <select
              id="forecast-model-select"
              className="forecast-select"
              value={model}
              onChange={(e) =>
                setModel(e.target.value as "moving_average" | "seasonal_naive" | "naive")
              }
            >
              <option value="moving_average">Moving Average (7-Day Window)</option>
              <option value="seasonal_naive">Seasonal Naive (7-Day Seasonality)</option>
              <option value="naive">Last Known Value (Naive)</option>
            </select>
          </div>

          <div className="forecast-field">
            <label htmlFor="forecast-mode-select">Data Source Mode</label>
            <select
              id="forecast-mode-select"
              className="forecast-select"
              style={{ minWidth: 150 }}
              value={mode}
              onChange={(e) => setMode(e.target.value as "auto" | "synthetic" | "db")}
            >
              <option value="auto">Auto (DB with Demo Fallback)</option>
              <option value="synthetic">Synthetic Fixture (Demo-Only)</option>
              <option value="db">Database Commitments (Strict)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Loading & Error States */}
      {isLoading && (
        <div style={{ padding: 40, textAlign: "center", color: "var(--ui-muted)" }}>
          <p style={{ fontSize: 16, fontWeight: 600 }}>Loading forecast models and scenario data...</p>
        </div>
      )}

      {isError && (
        <div
          style={{
            padding: 24,
            background: "#FFF2F2",
            border: "1px solid #FFD0D0",
            borderRadius: 8,
            color: "#D32F2F",
          }}
        >
          <h4 style={{ margin: "0 0 6px 0" }}>Failed to load forecast data</h4>
          <p style={{ margin: 0, fontSize: 13 }}>
            {error instanceof Error ? error.message : "Network error contacting backend forecast API."}
          </p>
        </div>
      )}

      {data && (
        <>
          {/* KPI Stat Cards (4-column row) */}
          <div className="forecast-kpi-grid">
            <div className="forecast-kpi-card">
              <span className="forecast-kpi-label">Projected Horizon Demand</span>
              <div className="forecast-kpi-value">
                {totalForecastDemand.toLocaleString()} {data.unit}
              </div>
              <div className="forecast-kpi-sub">
                <span className="sub-tag">{data.horizon} Days</span>
                <span>Cumulative forecast</span>
              </div>
            </div>

            <div className="forecast-kpi-card">
              <span className="forecast-kpi-label">Average Daily Run-Rate</span>
              <div className="forecast-kpi-value">
                {dailyRunRate} {data.unit}/d
              </div>
              <div className="forecast-kpi-sub">
                <span className="sub-tag">Daily Pace</span>
                <span>Based on {data.model_name}</span>
              </div>
            </div>

            <div className="forecast-kpi-card">
              <span className="forecast-kpi-label">Forward Risk Advisories</span>
              <div className="forecast-kpi-value" style={{ color: "#0767E8" }}>
                {activeAdvisoriesCount} Active
              </div>
              <div className="forecast-kpi-sub">
                <span className="sub-tag" style={{ background: "#EAF2FD" }}>
                  Advisory
                </span>
                <span>Requires human SME review</span>
              </div>
            </div>

            <div className="forecast-kpi-card">
              <span className="forecast-kpi-label">Model Retrospective MAE</span>
              <div className="forecast-kpi-value">{maeDisplay}</div>
              <div className="forecast-kpi-sub">
                <span className="sub-tag">Holdout MAE</span>
                <span>{data.is_synthetic ? "Synthetic backtest" : "Empirical holdout"}</span>
              </div>
            </div>
          </div>

          {/* Forecast Visual Chart Card */}
          <div className="forecast-chart-card">
            <div className="forecast-chart-header">
              <div className="chart-title-block">
                <h3>Demand Projection & Historical Actuals</h3>
                <p>
                  Target: <strong>{data.target_definition}</strong> ({data.sku_id}) • Unit:{" "}
                  <strong>{data.unit}</strong>
                </p>
              </div>

              <div className="forecast-legend">
                <div className="legend-item">
                  <span className="legend-dot-actual" />
                  <span>Historical Accepted</span>
                </div>
                <div className="legend-item">
                  <span className="legend-line-forecast" />
                  <span>Projected ({data.model_name})</span>
                </div>
                <div className="legend-item">
                  <span className="legend-line-cutoff" />
                  <span>Cutoff Date</span>
                </div>
              </div>
            </div>

            <ForecastChart
              historical={data.historical_points}
              forecast={data.forecast_points}
              cutoffDate={data.training_cutoff}
              unit={data.unit}
              isSynthetic={data.is_synthetic}
            />
          </div>

          {/* 4 Proactive Risk Family Cards */}
          <AdvisoryRiskCards advisories={data.advisories} unit={data.unit} />

          {/* Model Backtest & Detailed Inspection */}
          <ModelBacktestTable data={data} />
        </>
      )}
    </div>
  );
};
