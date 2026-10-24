import React, { useState } from "react";
import type { ForecastPoint, HistoricalPoint } from "./types";

interface ForecastChartProps {
  historical: HistoricalPoint[];
  forecast: ForecastPoint[];
  cutoffDate: string;
  unit: string;
  isSynthetic?: boolean;
}

interface HoverData {
  x: number;
  y: number;
  period: string;
  quantity: number;
  type: "Actual" | "Forecast";
}

export const ForecastChart: React.FC<ForecastChartProps> = ({
  historical,
  forecast,
  cutoffDate,
  unit,
}) => {
  const [hovered, setHovered] = useState<HoverData | null>(null);

  const histData = historical.map((p) => ({
    period: p.period,
    qty: typeof p.quantity === "number" ? p.quantity : parseFloat(String(p.quantity)) || 0,
    type: "Actual" as const,
  }));

  const foreData = forecast.map((p) => ({
    period: p.period,
    qty: typeof p.quantity === "number" ? p.quantity : parseFloat(String(p.quantity)) || 0,
    type: "Forecast" as const,
  }));

  const totalPoints = histData.length + foreData.length;
  if (totalPoints === 0) {
    return (
      <div style={{ padding: "40px 20px", textAlign: "center", color: "var(--ui-muted)" }}>
        <p style={{ fontSize: "15px", fontWeight: 600 }}>No Historical Demand Points Available</p>
        <p style={{ fontSize: "13px" }}>
          Insufficient observations recorded for this SKU. Switch to Demo mode to preview baseline mechanics.
        </p>
      </div>
    );
  }

  // Calculate scales
  const width = 860;
  const height = 300;
  const paddingLeft = 55;
  const paddingRight = 35;
  const paddingTop = 30;
  const paddingBottom = 45;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  const allValues = [...histData.map((d) => d.qty), ...foreData.map((d) => d.qty)];
  const maxVal = Math.max(...allValues, 10) * 1.2;

  const combined = [
    ...histData.map((d, i) => ({ ...d, index: i, isForecast: false })),
    ...foreData.map((d, i) => ({ ...d, index: histData.length + i, isForecast: true })),
  ];

  const getX = (idx: number) => paddingLeft + (idx / Math.max(combined.length - 1, 1)) * chartWidth;
  const getY = (val: number) => paddingTop + chartHeight - (val / maxVal) * chartHeight;

  // Build SVG Paths
  let histPath = "";
  let histArea = "";
  if (histData.length > 0) {
    histPath = `M ${getX(0)} ${getY(histData[0].qty)}`;
    histArea = `M ${getX(0)} ${paddingTop + chartHeight} L ${getX(0)} ${getY(histData[0].qty)}`;
    for (let i = 1; i < histData.length; i++) {
      histPath += ` L ${getX(i)} ${getY(histData[i].qty)}`;
      histArea += ` L ${getX(i)} ${getY(histData[i].qty)}`;
    }
    const lastHistIdx = histData.length - 1;
    histArea += ` L ${getX(lastHistIdx)} ${paddingTop + chartHeight} Z`;
  }

  // Forecast path connects from last historical point if available
  let forePath = "";
  let foreArea = "";
  if (foreData.length > 0) {
    const startIdx = histData.length > 0 ? histData.length - 1 : 0;
    const startX = getX(startIdx);
    const startY = histData.length > 0 ? getY(histData[histData.length - 1].qty) : getY(foreData[0].qty);

    forePath = `M ${startX} ${startY}`;
    foreArea = `M ${startX} ${paddingTop + chartHeight} L ${startX} ${startY}`;

    for (let i = 0; i < foreData.length; i++) {
      const idx = histData.length + i;
      forePath += ` L ${getX(idx)} ${getY(foreData[i].qty)}`;
      foreArea += ` L ${getX(idx)} ${getY(foreData[i].qty)}`;
    }
    const lastForeIdx = histData.length + foreData.length - 1;
    foreArea += ` L ${getX(lastForeIdx)} ${paddingTop + chartHeight} Z`;
  }

  // Cutoff line X position
  const cutoffIdx = Math.max(histData.length - 1, 0);
  const cutoffX = getX(cutoffIdx);

  // Grid lines
  const gridCount = 4;
  const gridLines = Array.from({ length: gridCount + 1 }).map((_, i) => {
    const val = Math.round((maxVal / gridCount) * i);
    const y = getY(val);
    return { val, y };
  });

  return (
    <div className="chart-svg-wrapper">
      <svg
        className="chart-svg"
        viewBox={`0 0 ${width} ${height}`}
        onMouseLeave={() => setHovered(null)}
      >
        <defs>
          <linearGradient id="histGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0767E8" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#0767E8" stopOpacity="0.01" />
          </linearGradient>
          <linearGradient id="foreGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3885EC" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#3885EC" stopOpacity="0.01" />
          </linearGradient>
        </defs>

        {/* Horizontal grid lines */}
        {gridLines.map((grid, idx) => (
          <g key={idx}>
            <line
              x1={paddingLeft}
              y1={grid.y}
              x2={width - paddingRight}
              y2={grid.y}
              stroke="rgba(28, 49, 83, 0.08)"
              strokeDasharray="4 4"
            />
            <text
              x={paddingLeft - 10}
              y={grid.y + 4}
              textAnchor="end"
              fontSize="11"
              fill="rgba(28, 49, 83, 0.55)"
              fontWeight="500"
            >
              {grid.val}
            </text>
          </g>
        ))}

        {/* Shaded Areas */}
        {histArea && <path d={histArea} fill="url(#histGradient)" />}
        {foreArea && <path d={foreArea} fill="url(#foreGradient)" />}

        {/* Cutoff vertical line */}
        <line
          x1={cutoffX}
          y1={paddingTop - 10}
          x2={cutoffX}
          y2={paddingTop + chartHeight}
          stroke="#808390"
          strokeWidth="1.5"
          strokeDasharray="4 4"
        />
        <text
          x={cutoffX}
          y={paddingTop - 14}
          textAnchor="middle"
          fontSize="11"
          fontWeight="600"
          fill="#5A607F"
        >
          Cutoff ({cutoffDate})
        </text>

        {/* Lines */}
        {histPath && (
          <path
            d={histPath}
            fill="none"
            stroke="#0767E8"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {forePath && (
          <path
            d={forePath}
            fill="none"
            stroke="#0767E8"
            strokeWidth="2.5"
            strokeDasharray="6 4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {/* Data points */}
        {combined.map((pt, idx) => {
          const cx = getX(idx);
          const cy = getY(pt.qty);
          const isFore = pt.isForecast;

          return (
            <g
              key={idx}
              style={{ cursor: "pointer" }}
              onMouseEnter={() =>
                setHovered({
                  x: cx,
                  y: cy,
                  period: pt.period,
                  quantity: pt.qty,
                  type: isFore ? "Forecast" : "Actual",
                })
              }
            >
              <circle
                cx={cx}
                cy={cy}
                r={isFore ? 5 : 4}
                fill={isFore ? "#FFFFFF" : "#0767E8"}
                stroke="#0767E8"
                strokeWidth={isFore ? "2.5" : "1.5"}
              />
              {/* Invisible larger hit target */}
              <circle cx={cx} cy={cy} r={12} fill="transparent" />
            </g>
          );
        })}

        {/* X Axis bottom labels (sample 6-8 evenly spaced) */}
        {combined
          .filter((_, i) => i % Math.max(Math.floor(combined.length / 7), 1) === 0 || i === combined.length - 1)
          .map((pt, i) => {
            const cx = getX(pt.index);
            const dateStr = pt.period.slice(5); // e.g. "10-24"
            return (
              <text
                key={i}
                x={cx}
                y={paddingTop + chartHeight + 20}
                textAnchor="middle"
                fontSize="11"
                fill="rgba(28, 49, 83, 0.65)"
                fontWeight="500"
              >
                {dateStr}
              </text>
            );
          })}
      </svg>

      {/* Hover Floating Tooltip */}
      {hovered && (
        <div
          className="chart-tooltip-box"
          style={{
            position: "absolute",
            left: `${hovered.x}px`,
            top: `${Math.max(hovered.y - 48, 10)}px`,
            transform: "translate(-50%, -100%)",
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 2 }}>{hovered.period}</div>
          <div>
            <span
              style={{
                display: "inline-block",
                width: 8,
                height: 8,
                borderRadius: 2,
                backgroundColor: hovered.type === "Forecast" ? "#3885EC" : "#0767E8",
                marginRight: 6,
              }}
            />
            {hovered.type === "Forecast" ? "Projected Demand: " : "Observed Accepted: "}
            <strong>
              {hovered.quantity} {unit}
            </strong>
          </div>
        </div>
      )}
    </div>
  );
};
