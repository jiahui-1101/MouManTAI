import React, { useState } from "react";
import type { ForecastResponse } from "./types";

interface ModelBacktestTableProps {
  data: ForecastResponse;
}

export const ModelBacktestTable: React.FC<ModelBacktestTableProps> = ({ data }) => {
  const [activeTab, setActiveTab] = useState<"backtest" | "history" | "provenance">("backtest");

  const formatMetric = (val: number | string | null | undefined) => {
    if (val === null || val === undefined) return "—";
    const num = typeof val === "number" ? val : parseFloat(String(val));
    return isNaN(num) ? String(val) : num.toFixed(3);
  };

  return (
    <div className="forecast-tabs-container">
      <div className="forecast-tab-bar">
        <button
          className={`forecast-tab-btn ${activeTab === "backtest" ? "active" : ""}`}
          onClick={() => setActiveTab("backtest")}
        >
          Model Backtest & Accuracy Comparison
        </button>
        <button
          className={`forecast-tab-btn ${activeTab === "history" ? "active" : ""}`}
          onClick={() => setActiveTab("history")}
        >
          Observed Demand History ({data.historical_points.length} Records)
        </button>
        <button
          className={`forecast-tab-btn ${activeTab === "provenance" ? "active" : ""}`}
          onClick={() => setActiveTab("provenance")}
        >
          Audit, Assumptions & Provenance
        </button>
      </div>

      <div className="forecast-tab-content">
        {activeTab === "backtest" && (
          <div>
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--ui-text)" }}>
                Retrospective Holdout Performance (1-Day Step, Expanding Origin)
              </div>
              <div style={{ fontSize: 12, color: "var(--ui-muted)" }}>
                Tested on 7-day chronological holdout. Lower MAE and WAPE indicate closer historical fit.
                {data.is_synthetic && (
                  <strong style={{ color: "#B25E00", marginLeft: 6 }}>
                    [DEMO-ONLY: synthetic series tests mechanics only]
                  </strong>
                )}
              </div>
            </div>

            {data.backtest_metrics.length === 0 ? (
              <p style={{ color: "var(--ui-muted)", fontSize: 13 }}>
                No backtest evaluation available for the current selection.
              </p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="forecast-data-table">
                  <thead>
                    <tr>
                      <th>Baseline Model</th>
                      <th>Version</th>
                      <th>MAE (Mean Abs Error)</th>
                      <th>WAPE</th>
                      <th>MASE</th>
                      <th>Signed Bias</th>
                      <th>Coverage</th>
                      <th>Eligible Actuals</th>
                      <th>Selected</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.backtest_metrics.map((m, idx) => {
                      const isSelected =
                        data.model_name.toUpperCase().includes(m.model_name.toUpperCase()) ||
                        m.model_name.toUpperCase().includes(data.model_name.toUpperCase());
                      return (
                        <tr key={idx}>
                          <td style={{ fontWeight: 600 }}>{m.model_name}</td>
                          <td>v{m.model_version}</td>
                          <td className="table-cell-highlight">{formatMetric(m.mae.value)}</td>
                          <td>{formatMetric(m.wape.value)}</td>
                          <td>{formatMetric(m.mase.value)}</td>
                          <td>{formatMetric(m.signed_bias.value)}</td>
                          <td>{typeof m.evidence_coverage === "number" ? (m.evidence_coverage * 100).toFixed(0) : m.evidence_coverage}%</td>
                          <td>{m.eligible_actuals} days</td>
                          <td>
                            {isSelected ? (
                              <span className="table-badge-active">Active</span>
                            ) : (
                              <span style={{ color: "var(--ui-muted)", fontSize: 11 }}>Candidate</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {activeTab === "history" && (
          <div>
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--ui-text)" }}>
                Accepted Order History by Business Day
              </div>
              <div style={{ fontSize: 12, color: "var(--ui-muted)" }}>
                Target: {data.target_definition}. Mode: {data.integration_mode} • Tier: {data.evidence_tier}
              </div>
            </div>

            <div style={{ maxHeight: 320, overflowY: "auto", overflowX: "auto" }}>
              <table className="forecast-data-table">
                <thead>
                  <tr>
                    <th>Period (Date)</th>
                    <th>Accepted Quantity</th>
                    <th>Unit</th>
                    <th>Status</th>
                    <th>Evidence Reference</th>
                  </tr>
                </thead>
                <tbody>
                  {data.historical_points.map((pt, idx) => (
                    <tr key={idx}>
                      <td style={{ fontWeight: 600 }}>{pt.period}</td>
                      <td className="table-cell-highlight">
                        {pt.quantity} {pt.unit}
                      </td>
                      <td>{pt.unit}</td>
                      <td>
                        <span className="table-badge-active">{pt.kind}</span>
                      </td>
                      <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--ui-muted)" }}>
                        {pt.evidence_ref}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === "provenance" && (
          <div className="provenance-grid">
            <div className="provenance-item">
              <span className="provenance-key">Run Identifier</span>
              <span className="provenance-val">{data.run_id}</span>
            </div>
            <div className="provenance-item">
              <span className="provenance-key">Target Definition</span>
              <span className="provenance-val">{data.target_definition}</span>
            </div>
            <div className="provenance-item">
              <span className="provenance-key">Cutoff / Watermark</span>
              <span className="provenance-val">{data.training_cutoff}</span>
            </div>
            <div className="provenance-item">
              <span className="provenance-key">Generated At</span>
              <span className="provenance-val">{data.generated_at}</span>
            </div>
            <div className="provenance-item">
              <span className="provenance-key">Model & Horizon</span>
              <span className="provenance-val">
                {data.model_name} v{data.model_version} ({data.horizon} days forward)
              </span>
            </div>
            <div className="provenance-item">
              <span className="provenance-key">Evidence Tier & Mode</span>
              <span className="provenance-val">
                Tier: {data.evidence_tier} | Mode: {data.integration_mode}
              </span>
            </div>
            <div className="provenance-item" style={{ gridColumn: "1 / -1" }}>
              <span className="provenance-key">Assumptions & Limitations</span>
              <span className="provenance-val" style={{ fontFamily: "inherit" }}>
                {data.assumptions.join("; ")}. {data.limitations.join("; ")}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
