import React from "react";
import type { ForecastAlert, RiskFamily } from "./types";

interface AdvisoryRiskCardsProps {
  advisories: ForecastAlert[];
  unit?: string;
}

const FAMILY_CONFIG: Record<
  RiskFamily,
  {
    title: string;
    icon: string;
    bubbleClass: string;
    defaultSuggestion: string;
  }
> = {
  DEMAND: {
    title: "Demand Volatility & Trend",
    icon: "📈",
    bubbleClass: "demand",
    defaultSuggestion: "Review upcoming SKU pipeline",
  },
  STOCKOUT_OR_EXPIRY: {
    title: "Stockout & Expiry Exposure",
    icon: "📦",
    bubbleClass: "stock",
    defaultSuggestion: "Verify lot batches and reorder timing",
  },
  SUPPLIER_DELAY: {
    title: "Supplier Lead-Time Risk",
    icon: "🚚",
    bubbleClass: "supplier",
    defaultSuggestion: "Request supplier ETA confirmation",
  },
  CAPACITY_OR_DEADLINE: {
    title: "Capacity & Workload Bottleneck",
    icon: "🏭",
    bubbleClass: "capacity",
    defaultSuggestion: "Check line scheduling and buffer",
  },
};

export const AdvisoryRiskCards: React.FC<AdvisoryRiskCardsProps> = ({ advisories }) => {
  // Map alerts by family so each of the 4 cards is always represented cleanly
  const alertsByFamily = advisories.reduce<Record<string, ForecastAlert>>((acc, alert) => {
    acc[alert.family] = alert;
    return acc;
  }, {});

  const families: RiskFamily[] = [
    "DEMAND",
    "STOCKOUT_OR_EXPIRY",
    "SUPPLIER_DELAY",
    "CAPACITY_OR_DEADLINE",
  ];

  return (
    <div className="risk-cards-section">
      <div className="section-title-row">
        <h3 className="section-title">Forward-Looking Risk Advisories</h3>
        <span style={{ fontSize: "12px", color: "var(--ui-muted)" }}>
          4 Proactive Families • Human SME Review Required
        </span>
      </div>

      <div className="risk-cards-grid">
        {families.map((family) => {
          const alert = alertsByFamily[family];
          const config = FAMILY_CONFIG[family];

          const status = alert?.status ?? "UNKNOWN";
          const exposure =
            alert?.exposure ?? "Operational assessment unavailable for this planning window.";
          const codes = alert?.explanation_codes ?? [];
          const suggestion =
            alert?.preparation_options?.[0] ?? config.defaultSuggestion;

          let statusClass = "unknown";
          if (status === "FUTURE_RISK_ADVISORY") statusClass = "advisory";
          else if (status === "CONDITIONAL") statusClass = "conditional";
          else if (status === "INSUFFICIENT_HISTORY" || status === "HIGH_RISK")
            statusClass = "warning";

          return (
            <div key={family} className="risk-advisory-card">
              <div className="risk-card-top">
                <div className="risk-card-icon-title">
                  <div className={`risk-icon-bubble ${config.bubbleClass}`}>
                    {config.icon}
                  </div>
                  <div>
                    <h4 className="risk-family-name">{config.title}</h4>
                    <span className="risk-target-sub">{family}</span>
                  </div>
                </div>
                <span className={`risk-status-pill ${statusClass}`}>{status}</span>
              </div>

              <p className="risk-exposure-text">{exposure}</p>

              {codes.length > 0 && (
                <div className="risk-tag-list">
                  {codes.slice(0, 3).map((code, idx) => (
                    <span key={idx} className="risk-tag">
                      {code}
                    </span>
                  ))}
                </div>
              )}

              <div className="risk-card-footer">
                <div className="risk-suggestion">
                  <span>💡</span> {suggestion}
                </div>
                <div className="risk-guardrail-notice">
                  Advisory only • Does not modify inventory or auto-approve actions
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
