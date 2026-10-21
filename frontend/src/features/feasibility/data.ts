import { IMPACT_CLASSIFICATIONS } from "./models";
import type { Commitment, FeasibilityView, ImpactView, P2DataSource } from "./models";

export class FeatureDataError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) { super(message); }
}
export function errorText(error: unknown): string {
  if (error instanceof FeatureDataError) {
    const label = error.status === 403 ? "Permission denied" : error.status === 409 ? "Version conflict" : "Request failed";
    return `${label} (${error.status}, ${error.code}): ${error.message}`;
  }
  return error instanceof Error ? error.message : "Request failed. Retry when the data source is available.";
}
export function requireSource(source?: P2DataSource): P2DataSource {
  if (!source) throw new FeatureDataError(503, "PUBLIC_ADAPTER_UNAVAILABLE", "P5 public adapter is unavailable. No synthetic data was substituted.");
  return source;
}
export function validateFeasibility(view: FeasibilityView, id: string, tenant: string): FeasibilityView {
  const { commitment: c, assessment: a, details: d } = view;
  if (c.tenant_id !== tenant || (a && a.tenant_id !== tenant)) throw new FeatureDataError(403, "TENANT_MISMATCH", "Returned data does not belong to the active scope.");
  if (c.commitment_id !== id || (a && a.commitment_id !== id) ||
      (d && (!a || d.commitment_id !== id || d.commitment_version !== a.commitment_version || d.snapshot_version !== a.snapshot_version))) {
    throw new FeatureDataError(409, "IDENTITY_MISMATCH", "Assessment/detail binding does not match the requested commitment.");
  }
  if (a && (!Number.isInteger(a.snapshot_version) || a.snapshot_version < 1 || !Number.isFinite(Date.parse(a.assessed_at)))) {
    throw new FeatureDataError(503, "INVALID_ASSESSMENT", "The adapter returned invalid assessment metadata.");
  }
  return view;
}
export function assessmentCaution(view: FeasibilityView, displayTime = Date.now()): string | null {
  const a = view.assessment, d = view.details;
  if (!a) return "No assessment available. Core feasibility state alone is not a detailed assessment.";
  if (a.commitment_version !== view.commitment.commitment_version || a.snapshot_version !== view.current_snapshot_version) return "Stale or conflicting version. Historical assessment only; current feasibility is UNKNOWN.";
  if (a.solver_status !== "COMPLETED") return `Solver ${a.solver_status}; current feasibility is UNKNOWN.`;
  const assessed = Date.parse(a.assessed_at);
  if (!d?.evidence_complete || !d.sources.length || d.sources.some((s) => {
    const observed = s.observed_at === null ? NaN : Date.parse(s.observed_at);
    const valid = s.valid_through === null ? NaN : Date.parse(s.valid_through);
    return s.status !== "CURRENT" || !Number.isFinite(observed) || !Number.isFinite(valid) ||
      observed > assessed || valid < assessed || observed > displayTime || assessed > displayTime || valid < displayTime;
  })) return "Source freshness or evidence completeness is unverified; current feasibility is UNKNOWN.";
  return null;
}
export function validateRecalculation(next: FeasibilityView, previous: FeasibilityView, tenant: string): FeasibilityView {
  validateFeasibility(next, previous.commitment.commitment_id, tenant);
  const a = next.assessment, old = previous.assessment;
  const c = next.commitment, baseline = previous.commitment;
  const sameTerms = c.terms.sku === baseline.terms.sku && c.terms.quantity === baseline.terms.quantity &&
    c.terms.unit === baseline.terms.unit && c.terms.deadline === baseline.terms.deadline &&
    c.terms.special_instructions === baseline.terms.special_instructions;
  if (!a || !a.assessment_id.trim() || c.commitment_version !== baseline.commitment_version ||
      c.order_id !== baseline.order_id || c.customer_id !== baseline.customer_id || !sameTerms ||
      a.commitment_version !== c.commitment_version || a.snapshot_version !== next.current_snapshot_version ||
      a.snapshot_version < (previous.current_snapshot_version ?? 0) ||
      (old && Date.parse(a.assessed_at) < Date.parse(old.assessed_at))) {
    throw new FeatureDataError(409, "RECALCULATION_CONFLICT", "A valid version-bound assessment response was not received. Previous assessment retained; reload current data before retrying a version conflict.");
  }
  return next;
}
export function validateImpact(view: ImpactView | null, id: string, tenant: string): ImpactView | null {
  if (!view) return null;
  if (view.tenant_id !== tenant) throw new FeatureDataError(403, "TENANT_MISMATCH", "Impact does not belong to the active scope.");
  if (view.impact_id !== id || view.after_snapshot_version <= view.before_snapshot_version) throw new FeatureDataError(409, "IMPACT_BINDING_MISMATCH", "Impact identity or snapshot versions conflict.");
  const ids = view.impacts.map((r) => r.commitment_id);
  if (new Set(ids).size !== ids.length || ids.some((key) => !view.candidate_commitment_ids.includes(key))) throw new FeatureDataError(409, "IMPACT_BINDING_MISMATCH", "Impact candidate/result binding conflicts.");
  if (view.impacts.some((row) => !IMPACT_CLASSIFICATIONS.includes(row.classification))) {
    throw new FeatureDataError(502, "INVALID_IMPACT_CLASSIFICATION", "Impact response contains an unsupported classification. No impact results can be displayed until the data contract is corrected.");
  }
  return { ...view, impacts: view.impacts.map((row) => {
    if (row.classification === "VERIFIED_UNAFFECTED" &&
        (!row.buffers.some((buffer) => hasPositiveBufferValue(buffer.value) && hasEvidenceReferences(buffer.evidence_refs)) ||
         row.buffers.some((buffer) => !hasEvidenceReferences(buffer.evidence_refs)))) {
      return { ...row, classification: "UNKNOWN", reasons: [...row.reasons, "UNAFFECTED_BUFFER_EVIDENCE_INSUFFICIENT"] };
    }
    if ((row.classification === "CONFIRMED_IMPACT" || row.classification === "VERIFIED_UNAFFECTED") &&
        !hasEvidenceReferences(row.evidence_refs)) {
      return { ...row, classification: "UNKNOWN", reasons: [...row.reasons, "Classification evidence unavailable"] };
    }
    return row;
  }),
  };
}
export function hasEvidenceReferences(refs: unknown): refs is string[] {
  return Array.isArray(refs) && refs.length > 0 && refs.every((ref) => typeof ref === "string" && ref.trim().length > 0);
}
function hasPositiveBufferValue(value: unknown): boolean {
  // Structural positivity gate only, without rounding/underflow or recalculating impact.
  return typeof value === "string" && /^\+?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) &&
    /[1-9]/.test(value.split(/[eE]/, 1)[0]);
}
// Reuses P5's injected Core reader, not a second HTTP/auth implementation.
// P5 can wire this to its existing apiRequest<Commitment> once session context is approved.
export function createCoreOnlySource(tenantId: string, read: (id: string) => Promise<Commitment>): P2DataSource {
  return { mode: "public-api", tenantId,
    loadFeasibility: async (id) => validateFeasibility({ commitment: await read(id), assessment: null, details: null, current_snapshot_version: null }, id, tenantId),
    loadImpact: async () => { throw new FeatureDataError(503, "IMPACT_ADAPTER_UNAVAILABLE", "P5 public adapter for persisted impact detail is unavailable."); },
  };
}
