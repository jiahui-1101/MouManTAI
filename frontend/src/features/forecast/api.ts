import { apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import type { ForecastFilterParams, ForecastResponse } from "./types";

export const DEFAULT_DEMO_SKUS = [
  { sku_id: "SKU-PROD-A", name: "Custom Artisan Pastry Box", category: "Bakery", unit: "boxes" },
  { sku_id: "SKU-PROD-B", name: "Specialty Sourdough Loaf", category: "Bakery", unit: "loaves" },
  { sku_id: "SKU-PACK-01", name: "Eco Gift Packaging 250g", category: "Packaging", unit: "packs" },
  { sku_id: "SKU-RAW-FLOUR", name: "Organic Stoneground Wheat Flour", category: "Raw Material", unit: "kg" },
];

export async function fetchForecasts(
  auth: RequestAuthHeaders,
  params: ForecastFilterParams = {},
): Promise<ForecastResponse> {
  const query = new URLSearchParams();
  if (params.skuId) query.set("sku_id", params.skuId);
  if (params.horizon) query.set("horizon", String(params.horizon));
  if (params.model) query.set("model", params.model);
  if (params.mode) query.set("mode", params.mode);

  const qs = query.toString();
  const endpoint = `/v1/forecasts${qs ? `?${qs}` : ""}`;

  return await apiRequest<ForecastResponse>(endpoint, {
    method: "GET",
    headers: authHeaders(auth),
  });
}
