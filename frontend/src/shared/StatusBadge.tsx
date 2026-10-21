import type { ReactNode } from "react";

export type StatusDimension = "agreement" | "feasibility" | "risk" | "recovery" | "fulfilment" | "attention";

export interface StatusBadgeProps {
  dimension?: StatusDimension;
  state: string;
  label?: string;
  children?: ReactNode;
  className?: string;
}

/**
 * Enforces FE-01d status color rules:
 * NEVER show green/success for:
 * - Pending Approval (recovery or agreement)
 * - Awaiting Confirmation (OFFERED)
 * - Unknown (UNKNOWN feasibility or identity)
 */
export function getStatusBadgeClass(_dimension: StatusDimension | undefined, state: string): string {
  const normalized = state.toUpperCase();

  // Strict non-green checks first
  if (
    normalized === "PENDING_APPROVAL" ||
    normalized === "AMENDMENT_REQUESTED" ||
    normalized === "PLANNING"
  ) {
    return "status-badge badge-warning";
  }
  if (normalized === "OFFERED" || normalized === "AWAITING_CONFIRMATION" || normalized === "UNRESOLVED_CONFIRMATION") {
    return "status-badge badge-purple";
  }
  if (normalized === "UNKNOWN" || normalized === "UNKNOWN_FEASIBILITY" || normalized === "NOT_ASSESSED") {
    return "status-badge badge-unknown";
  }
  if (
    normalized === "AT_RISK" ||
    normalized === "BREACHED" ||
    normalized === "INFEASIBLE" ||
    normalized === "FAILED" ||
    normalized === "FAILED_EXECUTION" ||
    normalized === "REJECTED" ||
    normalized === "CRITICAL"
  ) {
    return "status-badge badge-danger";
  }
  if (normalized === "CONDITIONAL" || normalized === "MANUAL_REVIEW" || normalized === "STALE_PLAN" || normalized === "HIGH") {
    return "status-badge badge-amber";
  }
  if (normalized === "EXECUTING" || normalized === "APPROVED" || normalized === "MEDIUM" || normalized === "IN_PROGRESS") {
    return "status-badge badge-info";
  }
  if (normalized === "CONFIRMED" || normalized === "FEASIBLE" || normalized === "FULFILLED" || normalized === "COMPLETED" || normalized === "RESOLVED") {
    return "status-badge badge-success";
  }
  if (normalized === "REQUESTED" || normalized === "NORMAL" || normalized === "NOT_STARTED" || normalized === "NONE") {
    return "status-badge badge-neutral";
  }

  return "status-badge badge-neutral";
}

export function StatusBadge({ dimension, state, label, children, className = "" }: StatusBadgeProps) {
  const badgeClass = getStatusBadgeClass(dimension, state);
  const displayLabel = label ?? children ?? state.replace(/_/g, " ");

  return <span className={`${badgeClass} ${className}`.trim()}>{displayLabel}</span>;
}
