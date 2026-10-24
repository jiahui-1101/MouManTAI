import { authHeaders, type RequestAuthHeaders } from '../../shared/api';

export interface PlanningInputs {
  tenant_id: string; actor_id: string; snapshot_ref: string; source: string;
  integration_mode: 'SYNTHETIC'; evidence_tier: 'DEMO-ONLY';
  total_orders?: number; eligible_orders?: number;
  excluded_orders?: { id: string; reason_code: string }[];
  planning_horizon?: { from: string; to: string; max_units: string; unit: string; provenance: string } | null;
  orders: { id: string; received_at: string; requested_delivery_at: string; lifecycle_status: string;
    items: { sku: string; quantity: string; unit: string }[]; evidence_refs: string[] }[];
  stocks: { resource_id: string; unit: string; free: string; total: string; reserved: string; snapshot_version: number }[];
  limitations: string[];
}
type Allocation = { order_id: string; membership: 'INCLUDED' | 'EXCLUDED' | 'ALLOCATE' | 'DEFER'; reason_code: string | null;
  requested_delivery_at: string; resource_usage: Record<string, string>; sequence: number; customer_display_name?: string;
  items: {sku:string;quantity:string;unit:string}[] };
type Scenario = { strategy: 'FCFS' | 'PROFIT' | 'EXPIRY_AWARE'; status: 'COMPUTED_SIMULATION' | 'INSUFFICIENT_INPUT';
  reason_codes: string[]; allocations: Allocation[]; allocated_count: number | null; allocation_rate: string | null;
  units_allocated: string | null; remaining_resources: Record<string, string> | null;
  contribution: string | null; candidate_sequence: string[]; schedule_status: string; deferred_count?: number | null;
  resource_consumed?: Record<string,string> | null; capacity_used?: string | null; capacity_total?: string | null;
  near_expiry_consumed?: Record<string,string> | null };
export interface PlanningResult { tenant_id: string; actor_id: string; snapshot_ref: string; source: string;
  assumptions_provenance: 'USER_ENTERED_NOT_PERSISTED' | 'SEEDED_DEMO_ONLY'; validation_status: 'UNVERIFIED_BY_P2';
  read_only: true; orders_considered: string[]; scenarios: Scenario[]; limitations: string[] }

async function readJson(response: Response) {
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body?.message === 'string' ? body.message : `Portfolio request failed (${response.status})`);
  return body;
}
export async function loadPlanningInputs(auth: RequestAuthHeaders, signal?: AbortSignal): Promise<PlanningInputs> {
  const data = await readJson(await fetch('/v1/planning/portfolio/inputs', { headers: authHeaders(auth), signal }));
  if (data.tenant_id !== auth.tenantId || data.actor_id !== auth.actorId || data.integration_mode !== 'SYNTHETIC' ||
    data.evidence_tier !== 'DEMO-ONLY' || !/^[a-f0-9]{64}$/.test(data.snapshot_ref) || !Array.isArray(data.orders) ||
    !Array.isArray(data.stocks) || !data.orders.every((o: PlanningInputs['orders'][number]) => typeof o.id === 'string' && Array.isArray(o.items)) ||
    !data.stocks.every((s: PlanningInputs['stocks'][number]) => typeof s.resource_id === 'string' && /^\d+(\.\d+)?$/.test(s.free)))
    throw new Error('Portfolio input identity or schema mismatch');
  return data;
}
export async function comparePlanning(auth: RequestAuthHeaders, body: object, signal?: AbortSignal): Promise<PlanningResult> {
  const data = await readJson(await fetch('/v1/planning/portfolio/compare', { method: 'POST', headers: { ...authHeaders(auth), 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal }));
  if (data.tenant_id !== auth.tenantId || data.actor_id !== auth.actorId ||
    !['USER_ENTERED_NOT_PERSISTED', 'SEEDED_DEMO_ONLY'].includes(data.assumptions_provenance) || data.read_only !== true ||
    data.validation_status !== 'UNVERIFIED_BY_P2' || !Array.isArray(data.scenarios) || data.scenarios.length !== 3 ||
    !data.scenarios.every((s: Scenario) => ['FCFS','PROFIT','EXPIRY_AWARE'].includes(s.strategy) &&
      ['COMPUTED_SIMULATION','INSUFFICIENT_INPUT'].includes(s.status) && Array.isArray(s.allocations)))
    throw new Error('Portfolio comparison identity or schema mismatch');
  return data;
}
