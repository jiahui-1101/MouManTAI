import type { Commitment, DecimalString, FeasibilityAssessment, ISO8601 } from "../../shared/types";
import { FeatureDataError, validateFeasibility, validateImpact } from "./data";
import type { FeasibilityView, ImpactClassification, ImpactView, P2DataSource } from "./models";

/**
 * P5 supplies the approved authenticated transport when the feature is mounted.
 * This adapter deliberately adds no tenant, actor, role, or service headers.
 */
export type P2PublicApiRequest = <T>(path: string, init?: RequestInit) => Promise<T>;

type ImpactApiDelta = {
  resource_id: string;
  code: string | null;
  before_shortage: DecimalString | null;
  after_shortage: DecimalString | null;
  unit: string | null;
  deadline: ISO8601 | null;
  severity_change: "NEW" | "WORSENED" | "IMPROVED" | "UNCHANGED" | null;
  evidence_refs: string[];
};

type ImpactApiPath = {
  nodes: { kind: string; resource_id: string }[];
  relationships: string[];
  evidence_refs: string[];
};

/** Fields consumed from the P2 router's canonical ImpactAssessment response. */
export interface P2ImpactAssessmentResponse {
  impact_id: string;
  tenant_id: string;
  event_id: string;
  event_type: string;
  before_snapshot_id: string;
  before_snapshot_version: number;
  after_snapshot_id: string;
  after_snapshot_version: number;
  discovery_complete: boolean;
  candidate_commitment_ids: string[];
  impacts: {
    tenant_id: string;
    commitment_id: string;
    before_commitment_version: number | null;
    after_commitment_version: number | null;
    before_snapshot_id: string;
    before_snapshot_version: number;
    after_snapshot_id: string;
    after_snapshot_version: number;
    classification: ImpactClassification;
    reasons: string[];
    material_deltas: ImpactApiDelta[];
    hard_constraint_deltas: ImpactApiDelta[];
    buffers: { resource_id: string; value: DecimalString; unit: string; evidence_refs: string[] }[];
    dependency_paths: ImpactApiPath[];
    evidence_refs: string[];
  }[];
}

function asFeatureError(error: unknown): unknown {
  if (error instanceof FeatureDataError) return error;
  if (error && typeof error === "object") {
    const value = error as { status?: unknown; code?: unknown; message?: unknown };
    if (typeof value.status === "number" && typeof value.code === "string") {
      return new FeatureDataError(
        value.status,
        value.code,
        typeof value.message === "string" ? value.message : "The public API request failed.",
      );
    }
  }
  return error;
}

async function read<T>(request: P2PublicApiRequest, path: string): Promise<T> {
  try {
    return await request<T>(path);
  } catch (error) {
    throw asFeatureError(error);
  }
}

function latestAssessment(rows: FeasibilityAssessment[]): FeasibilityAssessment | null {
  if (!Array.isArray(rows)) {
    throw new FeatureDataError(502, "INVALID_ASSESSMENT_HISTORY", "Assessment history response must be a list.");
  }
  return [...rows].sort((left, right) => {
    const timeOrder = Date.parse(right.assessed_at) - Date.parse(left.assessed_at);
    if (timeOrder !== 0) return timeOrder;
    return left.assessment_id === right.assessment_id ? 0 : left.assessment_id < right.assessment_id ? 1 : -1;
  })[0] ?? null;
}

function mapImpact(response: P2ImpactAssessmentResponse, impactId: string, tenantId: string): ImpactView {
  if (response.tenant_id !== tenantId) {
    throw new FeatureDataError(403, "TENANT_MISMATCH", "Impact does not belong to the active scope.");
  }
  if (response.impact_id !== impactId || response.after_snapshot_version <= response.before_snapshot_version ||
      !Array.isArray(response.candidate_commitment_ids) ||
      new Set(response.candidate_commitment_ids).size !== response.candidate_commitment_ids.length ||
      !Array.isArray(response.impacts)) {
    throw new FeatureDataError(409, "IMPACT_BINDING_MISMATCH", "Impact response identity or version binding conflicts.");
  }
  for (const row of response.impacts) {
    if (row.tenant_id !== response.tenant_id) {
      throw new FeatureDataError(403, "TENANT_MISMATCH", "Impact result does not belong to the active scope.");
    }
    if (!response.candidate_commitment_ids.includes(row.commitment_id) ||
        row.before_snapshot_id !== response.before_snapshot_id ||
        row.before_snapshot_version !== response.before_snapshot_version ||
        row.after_snapshot_id !== response.after_snapshot_id ||
        row.after_snapshot_version !== response.after_snapshot_version) {
      throw new FeatureDataError(409, "IMPACT_BINDING_MISMATCH", "Impact row does not match its event snapshots or candidate set.");
    }
  }
  return {
    impact_id: response.impact_id,
    tenant_id: response.tenant_id,
    event_id: response.event_id,
    event_type: response.event_type,
    before_snapshot_version: response.before_snapshot_version,
    after_snapshot_version: response.after_snapshot_version,
    discovery_complete: response.discovery_complete,
    candidate_commitment_ids: [...response.candidate_commitment_ids],
    impacts: response.impacts.map((row) => ({
      commitment_id: row.commitment_id,
      classification: row.classification,
      reasons: [...row.reasons],
      material_deltas: row.material_deltas.map((delta) => ({
        resource_id: delta.resource_id,
        code: delta.code,
        before_shortage: delta.before_shortage,
        after_shortage: delta.after_shortage,
        unit: delta.unit,
        deadline: delta.deadline,
        severity_change: delta.severity_change,
        evidence_refs: [...delta.evidence_refs],
      })),
      hard_constraint_deltas: row.hard_constraint_deltas.map((delta) => ({
        resource_id: delta.resource_id,
        code: delta.code,
        before_shortage: delta.before_shortage,
        after_shortage: delta.after_shortage,
        unit: delta.unit,
        deadline: delta.deadline,
        severity_change: delta.severity_change,
        evidence_refs: [...delta.evidence_refs],
      })),
      buffers: row.buffers.map((buffer) => ({ ...buffer, evidence_refs: [...buffer.evidence_refs] })),
      dependency_paths: row.dependency_paths.map((path) => ({
        nodes: path.nodes.map((node) => ({ ...node })),
        relationships: [...path.relationships],
        evidence_refs: [...path.evidence_refs],
      })),
      evidence_refs: [...row.evidence_refs],
      // Core risk transitions require a committed Core transition/audit read.
    })),
    // ImpactAssessment does not contain the source change's before/after values.
    // Empty arrays are rendered as unavailable by the P2 page; never infer them.
    trigger_evidence_refs: [],
    changes: [],
  };
}

/**
 * Map approved GET contracts to P2 page projections. Currentness, detailed
 * source rows and recalculation remain unavailable until P5 returns authority.
 */
export function createP2PublicApiSource(tenantId: string, request: P2PublicApiRequest): P2DataSource {
  const commitmentPath = (id: string) => `/v1/commitments/${encodeURIComponent(id)}`;
  return {
    mode: "public-api",
    tenantId,
    async loadFeasibility(id: string): Promise<FeasibilityView> {
      const path = commitmentPath(id);
      const [commitment, history] = await Promise.all([
        read<Commitment>(request, path),
        read<FeasibilityAssessment[]>(request, `${path}/assessments`),
      ]);
      if (!Array.isArray(history)) {
        throw new FeatureDataError(502, "INVALID_ASSESSMENT_HISTORY", "Assessment history response must be a list.");
      }
      const assessments = history.map((assessment) => validateFeasibility({
        commitment,
        assessment,
        details: null,
        current_snapshot_version: null,
      }, id, tenantId).assessment!);
      const latest = latestAssessment(assessments);
      return validateFeasibility({
        commitment,
        assessment: latest,
        current_snapshot_version: null,
        details: null,
      }, id, tenantId);
    },
    async loadImpact(id: string): Promise<ImpactView> {
      const response = await read<P2ImpactAssessmentResponse>(
        request,
        `/v1/impacts/${encodeURIComponent(id)}`,
      );
      return validateImpact(mapImpact(response, id, tenantId), id, tenantId)!;
    },
  };
}
