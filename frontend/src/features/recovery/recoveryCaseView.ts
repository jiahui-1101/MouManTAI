import type { ISO8601 } from "../../shared/types";

export interface RecoveryTriggerView {
  event_id: string;
  commitment_version: number;
  assessment_id: string;
  assessment_commitment_version?: number | null;
  assessment_provenance_status?: string;
  snapshot_id?: string | null;
  snapshot_version: number;
  evidence_refs: string[];
  occurred_at: ISO8601;
}

export interface RecoveryAssessmentView {
  assessment_id: string;
  commitment_version: number;
  snapshot_version: number;
  evidence_refs: string[];
  assessed_at?: ISO8601;
}

export interface RecoverySnapshotView {
  snapshot_id: string;
  snapshot_version: number;
  captured_at?: ISO8601;
  evidence_refs?: string[];
}

export interface CustomerResponseView {
  event_id: string;
  confirmation_id: string;
  proposal_id: string;
  proposal_version: number;
  intent: "REJECT" | "COUNTEROFFER";
  outcome: "REPLAN_REQUIRED" | "REPLANNED" | "STALE_IGNORED";
  proposed_terms?: Record<string, string> | null;
  evidence_refs: string[];
  received_at: ISO8601;
}

/** Read-only subset of the canonical P3 Recovery Case response. */
export interface RecoveryCaseView {
  case_id: string;
  tenant_id: string;
  commitment_id: string;
  case_version: number;
  commitment_version: number;
  status: string;
  storage_mode: "DURABLE_DATABASE" | "IN_MEMORY_SYNTHETIC";
  created_at: ISO8601;
  updated_at: ISO8601;
  evaluation_readiness?: "AWAITING_EVALUATION_INPUTS" | "CASE_COMPLETED";
  missing_evaluation_inputs?: string[];
  trigger_assessment?: RecoveryAssessmentView | null;
  operational_snapshot?: RecoverySnapshotView | null;
  trigger_events?: RecoveryTriggerView[];
  customer_response_events?: CustomerResponseView[];
  evidence_refs?: string[];
}
