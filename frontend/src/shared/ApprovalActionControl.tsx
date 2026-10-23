import { useState } from "react";
import { ApiError, confirmProposal } from "./api";
import { useAuth } from "./auth";
import { StatusBadge } from "./StatusBadge";
import { useToast } from "./Toast";
import { MutationStateView, type MutationState } from "./mutationState";
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
  const toast = useToast();

  const [isLoading, setIsLoading] = useState(false);
  const [mutationState, setMutationState] = useState<MutationState>({ status: "idle" });

  const handleExecute = async () => {
    setIsLoading(true);
    setMutationState({ status: "pending" });

    try {
      const result = await confirmProposal(
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

      const agreementState = result?.commitment?.agreement_state;
      if (!agreementState) {
        setMutationState({
          status: "failure",
          error: new TypeError("The response did not include an authoritative commitment state."),
          operationMayHaveApplied: true,
        });
      } else if (agreementState !== "CONFIRMED") {
        const pendingText = `Decision received; current agreement state is ${agreementState}. Terms are not confirmed.`;
        setMutationState({ status: "pending", message: pendingText });
        toast.info(pendingText);
      } else {
        const successText = "Proposal decision recorded.";
        setMutationState({ status: "success", message: successText, authoritativeState: agreementState });
        toast.success(successText);
        onSuccess?.();
      }
    } catch (err: unknown) {
      setMutationState({
        status: "failure",
        error: err,
        operationMayHaveApplied: !(err instanceof ApiError) || err.status >= 500,
      });
      onError?.(err);
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

      {mutationState.status !== "idle" && (
        <div data-testid="approval-mutation-feedback">
          <MutationStateView state={mutationState} />
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
