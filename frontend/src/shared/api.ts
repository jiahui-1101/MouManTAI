import type {
  AuditEvent,
  Commitment,
  CommitmentTransitionResponse,
  DomainEvent,
  ISO8601,
  OverviewResponse,
  ProposalConfirmRequest,
  ProposalCreateRequest,
  RecordFulfilmentRequest,
  TimelineEntry,
} from "./types";

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  checked_at?: ISO8601;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  correlation_id?: string;
  details?: Record<string, unknown>;
}

export interface RequestAuthHeaders {
  tenantId: string;
  actorId: string;
  correlationId?: string;
  causationId?: string;
}

export function authHeaders(auth: RequestAuthHeaders): Record<string, string> {
  return {
    "X-Tenant-ID": auth.tenantId,
    "X-Actor-ID": auth.actorId,
    ...(auth.correlationId ? { "X-Correlation-ID": auth.correlationId } : {}),
    ...(auth.causationId ? { "X-Causation-ID": auth.causationId } : {}),
  };
}

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  (import.meta.env.MODE === "test" ? "http://localhost:8000" : "");

export class ApiError extends Error {
  status: number;
  code: string;
  correlationId?: string;
  details?: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    correlationId?: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
    this.details = details;
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit, baseUrl = API_BASE_URL): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = undefined;
    }
    const code =
      body?.code ??
      (response.status === 403
        ? "FORBIDDEN"
        : response.status === 404
          ? "NOT_FOUND"
          : response.status === 409
            ? "CONFLICT"
            : "API_ERROR");
    const message = body?.message ?? `Request failed with status ${response.status}`;
    throw new ApiError(response.status, code, message, body?.correlation_id, body?.details);
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/health");
}

export function getOverview(auth: RequestAuthHeaders): Promise<OverviewResponse> {
  return apiRequest<OverviewResponse>("/v1/overview", { headers: authHeaders(auth) });
}

export function getCommitments(auth: RequestAuthHeaders): Promise<Commitment[]> {
  return apiRequest<Commitment[]>("/v1/commitments", { headers: authHeaders(auth) });
}

export function getCommitment(commitmentId: string, auth: RequestAuthHeaders): Promise<Commitment> {
  return apiRequest<Commitment>(`/v1/commitments/${commitmentId}`, { headers: authHeaders(auth) });
}

export function getCommitmentTimeline(commitmentId: string, auth: RequestAuthHeaders): Promise<TimelineEntry[]> {
  return apiRequest<TimelineEntry[]>(`/v1/commitments/${commitmentId}/timeline`, { headers: authHeaders(auth) });
}

export function createProposal(
  commitmentId: string,
  request: ProposalCreateRequest,
  auth: RequestAuthHeaders
): Promise<CommitmentTransitionResponse> {
  return apiRequest<CommitmentTransitionResponse>(`/v1/commitments/${commitmentId}/proposals`, {
    method: "POST",
    headers: authHeaders(auth),
    body: JSON.stringify(request),
  });
}

export function confirmProposal(
  commitmentId: string,
  request: ProposalConfirmRequest,
  auth: RequestAuthHeaders
): Promise<CommitmentTransitionResponse> {
  return apiRequest<CommitmentTransitionResponse>(`/v1/commitments/${commitmentId}/confirm-proposal`, {
    method: "POST",
    headers: authHeaders(auth),
    body: JSON.stringify(request),
  });
}

export function recordFulfilment(
  commitmentId: string,
  request: RecordFulfilmentRequest,
  auth: RequestAuthHeaders
): Promise<CommitmentTransitionResponse> {
  return apiRequest<CommitmentTransitionResponse>(`/v1/commitments/${commitmentId}/record-fulfilment`, {
    method: "POST",
    headers: authHeaders(auth),
    body: JSON.stringify(request),
  });
}

export function getAudit(auth: RequestAuthHeaders, commitmentId?: string): Promise<AuditEvent[]> {
  const query = commitmentId ? `?commitment_id=${encodeURIComponent(commitmentId)}` : "";
  return apiRequest<AuditEvent[]>(`/v1/audit${query}`, { headers: authHeaders(auth) });
}

export function getDomainEvent(eventId: string, auth: RequestAuthHeaders): Promise<DomainEvent> {
  return apiRequest<DomainEvent>(`/v1/events/${eventId}`, { headers: authHeaders(auth) });
}

