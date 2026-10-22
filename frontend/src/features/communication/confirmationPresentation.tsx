import { ApiError } from "../../shared/api";
import { StatusBadge } from "../../shared/StatusBadge";
import type { ConfirmationState } from "../../shared/types";
import type { ConfirmationView, ResponseIntent } from "./confirmationTypes";

const labels: Record<ConfirmationState, string> = {
  AWAITING_RESPONSE: "Awaiting response", ACCEPTED: "Acceptance recorded", REJECTED: "Rejection recorded",
  COUNTEROFFER_RECEIVED: "Counteroffer received", CLARIFICATION_REQUIRED: "Clarification required",
  UNRESOLVED: "Unresolved", EXPIRED: "Expired", SUPERSEDED: "Superseded",
};
export const responseLabels: Record<ResponseIntent, string> = {
  ACCEPT: "Explicit acceptance", REJECT: "Explicit rejection", COUNTEROFFER: "Counteroffer",
  CLARIFICATION: "Clarification", UNKNOWN: "Unresolved reply",
};
export function ConfirmationBadge({ value }: { value: ConfirmationView }) {
  const revoked = value.revoked_at !== null || value.blocked_reasons.includes("CONFIRMATION_REVOKED");
  return <StatusBadge state={revoked ? "REVOKED" : value.state} label={revoked ? "Revoked" : labels[value.state]}
    className="cw-badge" />;
}
export function currentnessText(value: ConfirmationView) {
  if (value.state === "SUPERSEDED") return "Superseded — reported by backend";
  if (value.blocked_reasons.some(code => /STALE|SUPERSEDED|PROPOSAL_CHANGED/.test(code))) return "Stale or superseded — reported by backend";
  return "Unavailable — current proposal verification is not returned by this API.";
}
export function confirmationErrorText(error: unknown) {
  if (!(error instanceof ApiError)) return "Cannot reach the confirmation service. Check your connection and retry.";
  if (["CONFIRMATION_PROCESSOR_AUTH_UNAVAILABLE", "VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE"].includes(error.code)) {
    return "Verified customer-response processing is not yet connected.";
  }
  if (["CONFIRMATION_IDENTITY_UNVERIFIED", "UNVERIFIED_IDENTITY", "CONTACT_UNVERIFIED", "VERIFIED_RECIPIENT_REQUIRED"].includes(error.code)) {
    return "Customer identity has not been verified for this recipient and channel. No acceptance can be established.";
  }
  if (error.code === "CONFIRMATION_IDENTITY_MISMATCH") return "The verified sender does not match this confirmation's customer or channel. No acceptance can be established.";
  if (error.code === "PRODUCTION_AUTH_UNAVAILABLE") return "Trusted authentication is unavailable. This demo requires an explicitly configured synthetic scope.";
  if (error.code === "CONFIRMATION_DISPOSABLE_SCOPE_REQUIRED") return "Confirmation access requires the configured disposable synthetic environment. Contact the integration owner.";
  if (error.code === "RESPONSE_SCOPE_MISMATCH") return "The response does not match this tenant or confirmation. No record is displayed.";
  if (error.code === "UNSUPPORTED_RESPONSE") return "The confirmation response could not be validated. No record is displayed.";
  if (/STALE|SUPERSEDED|PROPOSAL_CHANGED|VERSION_MISMATCH|TERMS_MISMATCH/.test(error.code)) {
    return "The backend reports changed or stale proposal information. Review the exact proposal version before continuing.";
  }
  if (error.code === "CONFIRMATION_REVOKED") return "This confirmation was revoked. No customer acceptance action is available.";
  if (error.code === "CONFIRMATION_EXPIRED") return "This confirmation expired. Review a current approved proposal with the integration owner.";
  if (error.status === 401) return "Your session is not authorized. Sign in again.";
  if (error.status === 403) return "You do not have permission to view this confirmation.";
  if (error.status === 404) return "Confirmation not found, or the confirmation route is unavailable. Check the ID and retry.";
  if (error.status === 409) return "Confirmation information conflicts with the requested record. Refresh to check the backend result.";
  if (error.status === 503) return "Confirmation authority or storage is unavailable. Contact the integration owner and retry.";
  return "Confirmation service is unavailable. Please retry.";
}
export function ConfirmationError({ error, retry, busy = false }: { error: unknown; retry: () => void; busy?: boolean }) {
  return <div className="cc-error" role="alert"><p>{confirmationErrorText(error)}</p>
    {error instanceof ApiError && <p className="text-sm">Reference: <code>{error.code}</code>
      {error.correlationId && <> · Correlation: <code>{error.correlationId}</code></>}</p>}
    <button className="btn btn-secondary" disabled={busy} onClick={retry}>Retry</button>
  </div>;
}
