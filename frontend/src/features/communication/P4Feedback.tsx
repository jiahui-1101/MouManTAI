import type { ReactNode } from "react";
import { ApiError } from "../../shared/api";

export function ApiErrorReference({ error }: { error: unknown }) {
  return error instanceof ApiError ? <p className="p4-error-reference text-sm">Reference: <code>{error.code}</code>
    {error.correlationId && <> · Correlation: <code>{error.correlationId}</code></>}</p> : null;
}
export function P4ErrorPanel({ error, message, retry, busy = false }: {
  error: unknown; message: string; retry: () => void; busy?: boolean;
}) {
  const unavailable = error instanceof ApiError && /AUTH|UNVERIFIED|UNAVAILABLE|FORBIDDEN|SCOPE_DENIED/.test(error.code);
  return <div className={`cc-error p4-error-panel${unavailable ? " p4-authority-notice" : ""}`} role="alert">
    <p>{message}</p><ApiErrorReference error={error} />
    <button className="btn btn-secondary" disabled={busy} onClick={retry}>Retry</button>
  </div>;
}
export function P4Loading({ children }: { children: ReactNode }) {
  return <div className="p4-loading cc-state" role="status" aria-live="polite">
    <span className="p4-loading-mark" aria-hidden="true" /><span>{children}</span>
  </div>;
}
