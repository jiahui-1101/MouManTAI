import type {
  ApprovalState,
  Commitment,
  DecimalString,
  ExecutionState,
  FeasibilityAssessment,
  FeasibilityState,
  ISO8601,
  PlannedAction,
  RecoveryPlan,
} from "../../shared/types";

export type RecoveryCaseStatus = "OPEN" | "OPTIONS_READY" | "NO_SAFE_PLAN" | "NEEDS_REPLAN";
export type ValidationSource = "REAL_P2_VALIDATED" | "TEST_DOUBLE_VALIDATED";
export type SolverReadiness = "PENDING_EVALUATION" | "VALIDATED" | "CONDITIONAL" | "INFEASIBLE" | "UNKNOWN";
export type RecoveryStrategy = "RESCHEDULE_PARTIAL_FULFILMENT" | "ALTERNATIVE_SUPPLY";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN";

export interface OperationalSnapshotReference {
  snapshot_id: string;
  snapshot_version: number;
  captured_at: ISO8601;
  source: string;
  evidence_refs: string[];
}

export interface BusinessPreferences {
  cost_weight: DecimalString;
  delay_weight: DecimalString;
  risk_weight: DecimalString;
  customer_impact_weight: DecimalString;
  max_extra_cost?: DecimalString | null;
}

export interface PlanEvaluation {
  evaluation_id: string;
  tenant_id: string;
  commitment_id: string;
  plan_id: string;
  plan_version: number;
  commitment_version: number;
  snapshot_version: number;
  feasibility_status: FeasibilityState;
  validation_source: ValidationSource;
  readiness: SolverReadiness;
  solver_status: string;
  constraints: string[];
  evidence_refs: string[];
  assumptions: string[];
  evaluated_at: ISO8601;
}

export interface RecoveryPlanVersion extends RecoveryPlan {
  option_id: string;
  strategy: RecoveryStrategy;
  risk_level: RiskLevel;
  customer_impact: string;
  constraints: string[];
  evidence_refs: string[];
  assumptions: string[];
  ranking_score: DecimalString;
  recommended: boolean;
  recommendation_reason?: string | null;
  evaluation: PlanEvaluation;
}

export interface RecoveryOption {
  option_id: string;
  plan_id: string;
  strategy: RecoveryStrategy;
  label: string;
  estimated_extra_cost: DecimalString;
  currency: string;
  estimated_delay_minutes: number;
  feasibility_status: FeasibilityState;
  validation_source: ValidationSource;
  risk_level: RiskLevel;
  customer_impact: string;
  constraints: string[];
  evidence_refs: string[];
  assumptions: string[];
  ranking_score: DecimalString;
  recommended: boolean;
  recommendation_reason?: string | null;
}

export interface ApprovalDecision {
  approval_id: string;
  tenant_id: string;
  commitment_id: string;
  plan_id: string;
  plan_version: number;
  snapshot_version: number;
  actor_id: string;
  actor_role: string;
  decision: "APPROVED" | "REJECTED" | "PENDING";
  approved_cost_limit?: DecimalString | null;
  reason: string;
  decided_at?: ISO8601 | null;
  expires_at?: ISO8601 | null;
  evidence_refs: string[];
}

export interface ActionAttempt {
  attempt_id: string;
  tenant_id: string;
  commitment_id: string;
  action_id: string;
  idempotency_key: string;
  state: "NOT_STARTED" | "IN_PROGRESS" | "SUCCEEDED" | "FAILED";
  started_at?: ISO8601 | null;
  completed_at?: ISO8601 | null;
  provider_operation_ref?: string | null;
  evidence_refs: string[];
  error_code?: string | null;
  error_message?: string | null;
}

export interface ActionExecution {
  execution_id: string;
  tenant_id: string;
  commitment_id: string;
  plan_id: string;
  action_id: string;
  state: "NOT_STARTED" | "BLOCKED" | "IN_PROGRESS" | "SUCCEEDED" | "FAILED" | "NEEDS_REPLAN";
  idempotency_key: string;
  attempts: ActionAttempt[];
  provider_operation_ref?: string | null;
  evidence_refs: string[];
}

export interface RecoveryCase {
  case_id: string;
  tenant_id: string;
  commitment_id: string;
  case_version: number;
  commitment_version: number;
  status: RecoveryCaseStatus;
  commitment: Commitment;
  trigger_assessment: FeasibilityAssessment;
  operational_snapshot: OperationalSnapshotReference;
  preferences: BusinessPreferences;
  options: RecoveryOption[];
  plans: RecoveryPlanVersion[];
  approval_decisions: ApprovalDecision[];
  customer_confirmation_evidence_refs: string[];
  fulfilment_evidence_refs: string[];
  evidence_refs: string[];
  storage_mode: "IN_MEMORY_SYNTHETIC";
  created_at: ISO8601;
  updated_at: ISO8601;
}

export interface GenerateRecoveryRequest {
  expected_commitment_version: number;
  assessment_id?: string;
  preferences?: BusinessPreferences;
}

export interface RecoveryPlanList {
  tenant_id: string;
  commitment_id: string;
  case_id: string;
  plans: RecoveryPlanVersion[];
}

export type SharedExecutionState = ExecutionState;
export type SharedApprovalState = ApprovalState;
export type SharedAction = PlannedAction;
