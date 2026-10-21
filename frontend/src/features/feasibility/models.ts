import type { Commitment, ConstraintReason, DecimalString, FeasibilityAssessment, ISO8601 } from "../../shared/types";

// Feature presentation projections, NOT new shared domain/API contracts.
// P5 must supply approved mappings from EvaluationResult/snapshot/ImpactAssessment.
export interface MaterialRow {
  line_id: string; sku_id: string; required: DecimalString; usable: DecimalString;
  reserved: DecimalString; confirmed_incoming: DecimalString; shortage: DecimalString;
  unit: string; needed_by: ISO8601; evidence_refs: string[];
}
export interface ProductionRow {
  line_id: string; resource_ids: string[]; start_at: ISO8601; finish_at: ISO8601;
  required_minutes: DecimalString; available_minutes: DecimalString | null; evidence_refs: string[];
}
export interface SourceRow {
  source_id: string; source_ref: string; observed_at: ISO8601 | null; valid_through: ISO8601 | null;
  status: "CURRENT" | "STALE" | "UNKNOWN"; evidence_refs: string[];
}
export interface EvaluationDetail {
  commitment_id: string; commitment_version: number; snapshot_version: number;
  evidence_complete: boolean; sources: SourceRow[]; materials: MaterialRow[]; operations: ProductionRow[];
}
export interface FeasibilityView {
  commitment: Commitment;
  assessment: FeasibilityAssessment | null;
  current_snapshot_version: number | null;
  details: EvaluationDetail | null;
}
export type ImpactClassification = "CONFIRMED_IMPACT" | "VERIFIED_UNAFFECTED" | "UNKNOWN"
  | "PRE_EXISTING_UNCHANGED" | "NO_NEW_ADVERSE_DELTA";
export interface ImpactDelta {
  resource_id: string; code?: string | null; before_shortage: DecimalString | null;
  after_shortage: DecimalString | null; unit: string | null; deadline: ISO8601 | null;
  severity_change?: "NEW" | "WORSENED" | "IMPROVED" | "UNCHANGED" | null; evidence_refs: string[];
}
export interface DependencyPath {
  nodes: { kind: string; resource_id: string }[]; relationships: string[]; evidence_refs: string[];
}
export interface CommitmentImpactView {
  commitment_id: string; classification: ImpactClassification; reasons: string[];
  material_deltas: ImpactDelta[]; hard_constraint_deltas: ImpactDelta[];
  buffers: { resource_id: string; value: DecimalString; unit: string; evidence_refs: string[] }[];
  dependency_paths: DependencyPath[]; evidence_refs: string[];
  // Only an approved Core audit/transition adapter may populate this optional presentation field.
  risk_change?: { before: Commitment["risk_state"]; after: Commitment["risk_state"]; evidence_refs: string[] };
}
export interface ImpactView {
  impact_id: string; tenant_id: string; event_id: string; event_type: string;
  before_snapshot_version: number; after_snapshot_version: number; discovery_complete: boolean;
  candidate_commitment_ids: string[]; impacts: CommitmentImpactView[];
  // These fields require OperationalChange + source-row enrichment, not graph inference.
  trigger_evidence_refs: string[];
  changes: { kind: string; resource_id: string; before: string; after: string; evidence_refs: string[] }[];
}
export interface ExpectedVersions { expected_commitment_version: number; expected_snapshot_version: number }
export interface P2DataSource {
  mode: "public-api" | "synthetic-preview";
  tenantId: string;
  loadFeasibility(id: string): Promise<FeasibilityView>;
  loadImpact(id: string): Promise<ImpactView | null>;
  recalculate?(id: string, versions: ExpectedVersions): Promise<FeasibilityView>;
}
export type { Commitment, ConstraintReason };
