import { useState } from "react";
import { ApiError, confirmProposal } from "./api";
import { useAuth } from "./auth";
import { StatusBadge } from "./StatusBadge";
import type { CommitmentTerms } from "./types";

export interface ApprovalActionControlProps {
  commitmentId: string;
  proposalId: string;
  proposalVersion: number;
  expectedCommitmentVersion?: number;
  currentStatus?: string;
  terms?: CommitmentTerms;
  onSuccess?: () => void;
  onError?: (err: unknown) => void;
}

/**
 * Shared Confirmation & Proposal Approval Control (UI-03, FE-01d).
 * Enforces role-based permissions:
 * - OWNER / MANAGER: Can approve proposals.
 * - STAFF: Restricted from high-privilege approval.
 *
 * Invariant: Never optimistically render success.
 * If an unauthorized action is forced, surfaces 403 Forbidden cleanly.
 */
export function ApprovalActionControl({
  commitmentId,
  proposalId,
  proposalVersion,
  expectedCommitmentVersion = 2,
  currentStatus = "PENDING_APPROVAL",
  onSuccess,
  onError,
}: ApprovalActionControlProps) {
  const { actorRole, authHeaders } = useAuth();
  const isStaff = actorRole === "STAFF";

  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const handleExecute = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      await confirmProposal(
        commitmentId,
        {
          proposal_id: proposalId,
          proposal_version: proposalVersion,
          expected_commitment_version: expectedCommitmentVersion,
          decision: "ACCEPT",
          evidence_refs: ["ev_approval_sign"],
          reason: "Proposal terms approved by authorized role",
        },
        authHeaders,
      );

      // Only show success when API actually returns 200 OK
      setSuccessMessage("Proposal approved and committed successfully.");
      if (onSuccess) {
        onSuccess();
      }
    } catch (err: unknown) {
      let msg = "An error occurred during approval.";
      if (err instanceof ApiError) {
        if (err.status === 403) {
          msg = `403 Forbidden: ${err.message || "Staff is not authorized to approve proposals."}`;
        } else {
          msg = `${err.code}: ${err.message}`;
        }
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setErrorMessage(msg);
      if (onError) {
        onError(err);
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="approval-action-card" data-testid="approval-action-control">
      <div className="approval-header">
        <h4>Proposal Approval Action</h4>
        <StatusBadge state={currentStatus} />
      </div>

      <div className="proposal-meta">
        <p>
          Target Commitment: <code>{commitmentId}</code>
        </p>
        <p>
          Proposal ID: <code>{proposalId}</code> (v{proposalVersion})
        </p>
      </div>

      {/* Permission restriction notice for Staff role */}
      {isStaff && (
        <div className="permission-notice" data-testid="permission-restricted-notice">
          <span className="notice-icon">⚠️</span>
          <span>High-privilege approval restricted: Staff role cannot execute proposals (requires Manager or Owner).</span>
        </div>
      )}

      {/* 403 or API Error Banner */}
      {errorMessage && (
        <div role="alert" className="error-banner" data-testid="permission-error-banner">
          <span className="error-icon">🚫</span>
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Success Banner (Never shown optimistically) */}
      {successMessage && (
        <div role="status" className="success-banner" data-testid="approval-success-banner">
          <span className="success-icon">✅</span>
          <span>{successMessage}</span>
        </div>
      )}

      <div className="action-buttons-row">
        {isStaff ? (
          <>
            <button
              type="button"
              disabled
              aria-disabled="true"
              className="btn btn-disabled"
              data-testid="approval-action-btn-disabled"
            >
              Approve Recovery Proposal (Staff Restricted)
            </button>
            <button
              type="button"
              onClick={handleExecute}
              disabled={isLoading}
              className="btn btn-outline-danger btn-sm"
              data-testid="force-unauthorized-action-btn"
              title="Force action to verify backend role guard"
            >
              {isLoading ? "Executing…" : "Force Attempt (Simulate Breach)"}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={handleExecute}
            disabled={isLoading}
            className="btn btn-primary"
            data-testid="approval-action-btn"
          >
            {isLoading ? "Executing…" : "Approve Recovery Proposal"}
          </button>
        )}
      </div>
    </div>
  );
}
