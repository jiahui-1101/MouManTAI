import { ApiError } from "../../shared/api";
import { StatusBadge } from "../../shared/StatusBadge";
import type { CommunicationRequestView, MessageStatus } from "./types";

// Display labels only. A Request's default DRAFT is NOT evidence of a saved draft.
export function communicationLabel(requestStatus: CommunicationRequestView["request_status"],
  messageStatus: MessageStatus, hasVerifiedDraft = false) {
  if (requestStatus === "BLOCKED" || messageStatus === "FAILED") return "Blocked";
  if (messageStatus === "QUEUED" || messageStatus === "SUBMITTED") return "Sending";
  if (messageStatus === "SENT" || messageStatus === "DELIVERED") return "Sent";
  if (messageStatus === "DELIVERY_UNKNOWN") return "Blocked";
  return hasVerifiedDraft ? "Drafted" : "Pending";
}

const reasons: Record<string, string> = {
  CORE_PLAN_BINDING_UNAVAILABLE: "Core has not persisted the exact recovery plan and proposal binding.",
  CORE_APPROVAL_PRODUCER_UNAVAILABLE: "Current durable recovery plan approval and expiry cannot be verified. Integrated demo is blocked.",
  CORE_ACTION_POLICY_UNAVAILABLE: "Core has not declared the required draft review or send action policy.",
  P1_CONTACT_CONTRACT_UNAVAILABLE: "P1's typed channel contact contract is unavailable. No recipient is assumed verified.",
  PRODUCTION_AUTH_UNAVAILABLE: "Trusted production authentication is unavailable. Explicit synthetic scope is required for this demo.",
  SYNTHETIC_SCOPE_DENIED: "This tenant is outside the configured synthetic demo scope.",
  SYNTHETIC_ACTOR_INVALID: "The current synthetic actor role mapping is invalid.",
  MANAGER_PERMISSION_DENIED: "Only an authorized manager or owner may perform this action.",
  CONSENT_REQUIRED: "Permission required: explicit transactional consent has not been recorded.",
  CONSENT_REVOKED: "Recipient consent was revoked. Sending is blocked.",
  CONSENT_EXPIRED: "Recipient consent expired. Record new permission evidence before continuing.",
  CONSENT_EVIDENCE_INVALID: "Consent evidence or its durable audit history could not be verified.",
  CONSENT_EVIDENCE_REUSED: "A new permission decision requires a new evidence reference.",
  CONSENT_EXPIRY_INVALID: "Synthetic permission must expire within the next 30 days.",
  CONSENT_VERSION_CONFLICT: "Recipient preferences changed. Reload before applying another change.",
  CONSENT_IDEMPOTENCY_CONFLICT: "This request key belongs to a different preference change.",
  CONSENT_STORAGE_UNAVAILABLE: "Recipient preference storage is unavailable. Apply the P4 migration and retry.",
  CONSENT_NOT_FOUND: "No stored recipient permission was found to revoke.",
  CONSENT_RECIPIENT_CHANGED: "Consent belongs to an older recipient contact. New permission is required.",
  CONTACT_CHANGED: "P1's recipient contact changed. Prepare and review a new draft.",
  CONTACT_UNVERIFIED: "P1 has not verified this recipient on the selected channel.",
  CONTACT_CUSTOMER_NOT_FOUND: "The customer is not available in this tenant.",
  CONTACT_CUSTOMER_INACTIVE: "This customer is inactive. Sending is blocked.",
  CONTACT_CHANNEL_UNSUPPORTED: "The selected channel is not an allowed synthetic channel.",
  CONTACT_HOURS_RESTRICTED: "Current time is outside the recipient's allowed contact hours.",
  CONSENT_TIMEZONE_UNAVAILABLE: "The recipient's contact timezone cannot be resolved.",
  VERIFIED_RECIPIENT_REQUIRED: "Recipient identity has not been verified yet.",
  AUTHORIZED_CHANNEL_REQUIRED: "A verified, authorized communication channel is required.",
  DRAFT_REVALIDATION_UNAVAILABLE: "Draft validation is not connected yet. Please contact the integration owner.",
  COMMUNICATION_AUTHORITY_UNAVAILABLE: "Trusted approval validation is not connected yet.",
  AUTHORITY_UNAVAILABLE: "Trusted approval validation is not connected yet.",
  DRAFT_PERSISTENCE_UNAVAILABLE: "Draft storage is unavailable. Please contact the integration owner.",
  COMMUNICATION_PERSISTENCE_UNAVAILABLE: "Communication storage is unavailable. Please contact the integration owner.",
  COMMUNICATION_SUMMARY_UNAVAILABLE: "Dashboard statistics are unavailable. The request list can still be used.",
  DRAFT_REVALIDATION_REQUIRED: "The approval, channel or template changed. Prepare a new draft after review.",
  APPROVED_TERMS_MISMATCH: "The proposal terms changed. Review the current proposal before preparing a draft.",
  RESPONSE_SCOPE_MISMATCH: "The response does not match this tenant, request or proposal. Nothing was displayed.",
  UNSUPPORTED_RESPONSE: "The server response is not supported. Refresh or contact the integration owner.",
  DRAFT_INTEGRITY_ERROR: "The saved draft could not be verified. Review the source proposal.",
  PROPOSAL_NOT_ELIGIBLE: "The proposal is no longer active or eligible for drafting. Review the current proposal.",
  PROPOSED_DEADLINE_PASSED: "The proposed delivery deadline has passed. Review the current proposal.",
  APPROVED_TERMS_REQUIRED: "Explicit approved proposal terms are required before drafting.",
  APPROVAL_EVIDENCE_REQUIRED: "Trusted approval evidence is required before drafting.",
  REVIEW_AUTHORITY_UNAVAILABLE: "Manager review is unavailable until trusted review authorization is connected.",
  REVIEW_VALIDATION_UNAVAILABLE: "The original reviewer's authorization cannot currently be verified. This approval cannot be used.",
  REVIEW_STORAGE_UNAVAILABLE: "Review storage is unavailable. Please contact the integration owner.",
  REVIEW_FORBIDDEN: "You are not authorized to review this draft.",
  REVIEW_ALREADY_DECIDED: "This exact draft already has a decision. Reload its review history.",
  REVIEW_INVALIDATED: "This review has been invalidated and cannot be restored by retrying.",
  REVIEW_CONTENT_CHANGED: "The draft changed after preview. Reload and inspect it before reviewing.",
  REVIEW_IDEMPOTENCY_CONFLICT: "This review request conflicts with a previously saved operation. Reload the review.",
  REVIEW_INTEGRITY_ERROR: "The saved review could not be verified. No approval can be used.",
  REVIEW_REQUEST_BLOCKED: "This request is blocked and cannot be reviewed.",
};

export function reasonText(code: string) {
  if (reasons[code]) return reasons[code];
  if (/STALE|SUPERSEDED|VERSION/.test(code)) return "The proposal version is no longer current. Review the latest proposal.";
  if (/EXPIRED/.test(code)) return "The proposal or approval has expired. Obtain a current approval.";
  if (/REVOKED|APPROVAL_REQUIRED|APPROVAL_MISSING/.test(code)) return "A current trusted approval is required.";
  return "This request needs review before drafting can continue.";
}

export function errorText(error: unknown, resource: "list" | "detail" | "draft" | "summary" | "review" | "send") {
  if (!(error instanceof ApiError)) return "Cannot reach the server. Check your connection and try again.";
  if (reasons[error.code] || /STALE|SUPERSEDED|VERSION|EXPIRED|REVOKED/.test(error.code)) return reasonText(error.code);
  if (error.status === 401) return "Your session is not authorized. Sign in again.";
  if (error.status === 403) return "You do not have permission for this action.";
  if (error.status === 404 && resource === "summary") return "Dashboard statistics are not available. The summary route may still be awaiting integration.";
  if (error.status === 404 && resource === "review") return "The draft or its review route is unavailable. Refresh and check the selected draft.";
  if (error.status === 404) return resource === "list"
    ? "Communication service is not available. The route may still be awaiting integration."
    : resource === "draft" ? "Draft not found, or the draft route is unavailable. Check the ID and retry."
      : "Communication request not found, or the detail route is unavailable.";
  if (error.status === 409) return "The proposal or approval changed. Refresh and review the current version.";
  if (error.status === 503) return "Communication service is not ready. Approval validation or storage may still be awaiting integration.";
  if (error.status === 422) return "The request could not be validated. Check your selection and retry.";
  return "Communication service is unavailable. Please try again later.";
}

export const languages = { en: "English", ms: "Bahasa Melayu", zh: "Chinese" } as const;
export function channelText(channel: string | null | undefined) {
  if (!channel || channel === "UNKNOWN") return "Not resolved";
  return channel.replace("MOCK_", "Mock ").replace(/_/g, " ");
}

export function DisplayBadge({ label }: { label: string }) {
  return <StatusBadge state={label} label={label} className={`cc-status cc-status-${label.toLowerCase()}`} />;
}
export function ErrorNotice({ error, resource, onRetry }: {
  error: unknown; resource: "list" | "detail" | "draft" | "summary" | "review"; onRetry: () => void;
}) {
  return <div className="cc-error" role="alert"><p>{errorText(error, resource)}</p>
    <button className="btn btn-secondary" onClick={onRetry}>Retry</button></div>;
}
