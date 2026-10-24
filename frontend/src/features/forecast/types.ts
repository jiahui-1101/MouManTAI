export type RiskFamily =
  | "DEMAND"
  | "STOCKOUT_OR_EXPIRY"
  | "SUPPLIER_DELAY"
  | "CAPACITY_OR_DEADLINE";

export interface HistoricalPoint {
  period: string;
  quantity: number | string;
  unit: string;
  kind: string;
  evidence_ref: string;
}

export interface ForecastPoint {
  period: string;
  quantity: number | string;
  unit: string;
}

export interface MetricValue {
  value: number | string | null;
  unavailable_reason?: string | null;
}

export interface BacktestSummary {
  model_name: string;
  model_version: string;
  mae: MetricValue;
  wape: MetricValue;
  mase: MetricValue;
  signed_bias: MetricValue;
  evidence_coverage: number | string;
  eligible_actuals: number;
}

export interface ForecastAlert {
  alert_id: string;
  family: RiskFamily;
  target_id: string;
  period: string;
  status: string;
  exposure: string;
  unit?: string | null;
  magnitude?: number | string | null;
  evidence_tier: string;
  integration_mode: string;
  uncertainty: string;
  missing_data: string[];
  explanation_codes: string[];
  preparation_options: string[];
  required_human_review: boolean;
  operational_action_authorized: boolean;
}

export interface SkuOption {
  sku_id: string;
  name: string;
  category: string;
  unit: string;
}

export interface ForecastResponse {
  tenant_id: string;
  sku_id: string;
  available_skus: SkuOption[];
  unit: string;
  target_definition: string;
  status: string;
  evidence_tier: string;
  integration_mode: string;
  is_synthetic: boolean;
  demo_badge: boolean;
  training_cutoff: string;
  horizon: number;
  model_name: string;
  model_version: string;
  run_id: string;
  generated_at: string;
  historical_points: HistoricalPoint[];
  forecast_points: ForecastPoint[];
  backtest_metrics: BacktestSummary[];
  advisories: ForecastAlert[];
  diagnostics: string[];
  assumptions: string[];
  limitations: string[];
  disclaimer: string;
}

export interface ForecastFilterParams {
  skuId?: string;
  horizon?: number;
  model?: "moving_average" | "seasonal_naive" | "naive";
  mode?: "auto" | "synthetic" | "db";
}
