import { apiRequest } from '../../shared/api';

export interface DemoSession {
  tenant_id: string;
  actor_id: string;
  csrf_token: string;
  expires_at: string;
  integration_mode: 'MOCK';
}
export interface OrderRequest {
  tenant_id: string; order_request_id: string; customer_id: string;
  source_id: string; source_version: number; source_evidence_refs: string[];
  source_observed_at: string; source_valid_through: string;
  terms: {
    order_request_id: string; customer_id: string; terms_revision: number;
    items: { sku: string; variant: string | null; quantity: string; unit: string; unit_price: string }[];
    window_start: string; window_end: string; fulfilment_method: string;
    location_ref: string; currency: string; total: string; evidence_refs: string[];
    price_source: { source_type: string; source_id: string; source_version: string; evidence_refs: string[] };
  };
  terms_hash: string; request_version: number;
  decision_status: 'PENDING' | 'REVIEWED' | 'RESERVATION_UNKNOWN' | 'REJECTED' | 'ACCEPTED';
  review_actor_id: string | null; review_reason: string | null; commitment_id: string | null;
  created_at: string; updated_at: string; integration_mode: 'MOCK'; evidence_tier: 'DEMO-ONLY';
}
export interface FeasibilityPreview {
  order_request_id: string; request_version: number; terms_hash: string;
  assessment: { assessment_id: string; commitment_id: string; snapshot_id: string; snapshot_version: number;
    status: string; solver_status: string; evidence_complete: boolean; evidence_refs: string[]; assumptions: string[] };
  integration_mode: 'MOCK'; evidence_tier: 'DEMO-ONLY';
}
export interface AcceptanceResult {
  order_request: OrderRequest;
  reservation: { operation_id: string; status: string; evidence_refs: string[] };
  commitment: { commitment_id: string; commitment_version: number } | null;
  operational_projection?: { status: string; reason_codes?: string[] } | null;
  integration_mode: 'MOCK'; evidence_tier: 'DEMO-ONLY';
}
export interface OrderRequestEvent {
  event_type: string; actor_id: string; occurred_at: string; evidence_refs: string[];
  source: 'ORDER_REQUEST' | 'CORE'; integration_mode: 'MOCK';
}
export interface CommitmentEvent {
  event_id: string; event_type: string; status: string; commitment_id: string;
  occurred_at: string; evidence_refs: string[]; source_provenance: Record<string, unknown>;
}
export interface NotificationIntent {
  intent_id: string; commitment_id: string; order_request_id: string | null;
  status: 'UNRESOLVED_ORDER_ACCEPTANCE' | 'PENDING_P4_REVIEW';
  delivery_status: 'NOT_SENT'; blocker_codes: string[]; evidence_refs: string[];
  created_at: string;
}

const base = '/demo-bff';
const id = (value: string) => encodeURIComponent(value);
export const getDemoSession = () => apiRequest<DemoSession>(`${base}/session`);
export const openDemoSession = (bootstrap_token: string) => apiRequest<DemoSession>(`${base}/session`, {
  method: 'POST', body: JSON.stringify({ bootstrap_token }),
});
export const openDemoAdminSession = (username: string, password: string) => apiRequest<DemoSession>(`${base}/session`, {
  method: 'POST', body: JSON.stringify({ username, password }),
});
export const closeDemoSession = (session: DemoSession) => apiRequest<{ revoked: true }>(`${base}/session`, {
  method: 'DELETE', headers: { 'X-CSRF-Token': session.csrf_token },
});
export const listOrderRequests = () => apiRequest<OrderRequest[]>(`${base}/order-requests`);
export const getOrderRequest = (requestId: string) => apiRequest<OrderRequest>(`${base}/order-requests/${id(requestId)}`);
export const getOrderRequestFeasibility = (requestId: string) =>
  apiRequest<FeasibilityPreview>(`${base}/order-requests/${id(requestId)}/feasibility`);
export const getOrderRequestTimeline = (requestId: string) =>
  apiRequest<OrderRequestEvent[]>(`${base}/order-requests/${id(requestId)}/timeline`);
export const getCommitmentEvidenceTimeline = (commitmentId: string) =>
  apiRequest<{ tenant_id: string; commitment_id: string; entries: CommitmentEvent[] }>(`${base}/commitments/${id(commitmentId)}/timeline`);
export const getNotificationIntents = (commitmentId: string) =>
  apiRequest<NotificationIntent[]>(`${base}/commitments/${id(commitmentId)}/notification-intents`);
export const getReservationReceipt = (operationId: string) =>
  apiRequest<AcceptanceResult['reservation']>(`${base}/reservations/${id(operationId)}`);
export const reviewOrderRequest = (requestId: string, session: DemoSession, expected_request_version: number,
  decision: 'REVIEWED' | 'REJECTED', reason: string) =>
  apiRequest<OrderRequest>(`${base}/order-requests/${id(requestId)}/review`, {
    method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token },
    body: JSON.stringify({ expected_request_version, decision, reason }),
  });
export const acceptOrderRequest = (request: OrderRequest, preview: FeasibilityPreview, session: DemoSession,
  reason: string, idempotency_key: string) =>
  apiRequest<AcceptanceResult>(`${base}/order-requests/${id(request.order_request_id)}/accept-mock`, {
    method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token },
    body: JSON.stringify({ expected_request_version: request.request_version,
      expected_terms_hash: request.terms_hash, expected_snapshot_version: preview.assessment.snapshot_version,
      idempotency_key, reason }),
  });
