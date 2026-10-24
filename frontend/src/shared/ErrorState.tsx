import { useMemo } from "react";
import { ApiError } from "./api";

export type UiErrorKind = "authentication" | "permission" | "conflict" | "validation" | "domain" | "network" | "server" | "unknown-outcome" | "unknown";

export interface ErrorStateProps {
  kind?: UiErrorKind;
  error?: unknown;
  title?: string;
  description?: string;
  correlationId?: string;
  onRetry?: () => void;
  retrySafe?: boolean;
  operationMayHaveApplied?: boolean;
  className?: string;
}

export function classifyUiError(error: unknown, options: { retrySafe?: boolean; operationMayHaveApplied?: boolean } = {}): UiErrorKind {
  if (error instanceof ApiError) {
    if (error.status === 401) return "authentication";
    if (error.status === 403) return "permission";
    if (error.status === 409) return "conflict";
    if (error.status === 422) return "validation";
    if (error.status >= 400 && error.status < 500) return "domain";
    if (error.status >= 500 && options.operationMayHaveApplied) return "unknown-outcome";
    if (error.status >= 500) return "server";
  }

  if (error instanceof TypeError || (error instanceof Error && (error.name === "AbortError" || /network|fetch/i.test(error.message)))) {
    if (options.operationMayHaveApplied) return "unknown-outcome";
    return options.retrySafe ? "network" : "server";
  }
  return "unknown";
}

const COPY: Record<UiErrorKind, { title: string; description: string }> = {
  authentication: { title: "Sign-in required", description: "Your identity could not be verified. Sign in again before continuing." },
  permission: { title: "Access denied", description: "Your account does not have permission to complete this request." },
  conflict: { title: "The record has changed", description: "Refresh the latest server state and review it before trying again." },
  validation: { title: "Check the information", description: "Some submitted fields need correction before this request can continue." },
  domain: { title: "Request not accepted", description: "The server rejected this request under the current business rules." },
  network: { title: "Connection problem", description: "The service could not be reached. You can retry this read safely." },
  server: { title: "Request failed", description: "The service could not complete the request. Check the current record state before continuing." },
  "unknown-outcome": { title: "Outcome not confirmed", description: "The request may have reached the service, but its result is unknown. Check the current record or operation status before taking another action." },
  unknown: { title: "Something went wrong", description: "The request could not be completed. Check the current state before continuing." },
};

export function ErrorState({
  kind,
  error,
  title,
  description,
  correlationId,
  onRetry,
  retrySafe = false,
  operationMayHaveApplied = false,
  className = "",
}: ErrorStateProps) {
  const resolvedKind = useMemo(
    () => kind ?? classifyUiError(error, { retrySafe, operationMayHaveApplied }),
    [kind, error, retrySafe, operationMayHaveApplied],
  );
  const copy = COPY[resolvedKind];
  const resolvedCorrelationId = correlationId ?? (error instanceof ApiError ? error.correlationId : undefined);

  return (
    <section className={`foundation-error ${className}`.trim()} role="alert" aria-live="assertive">
      <h3>{title ?? copy.title}</h3>
      <p>{description ?? copy.description}</p>
      {resolvedCorrelationId && <p className="foundation-error-correlation">Reference: <code>{resolvedCorrelationId}</code></p>}
      {onRetry && retrySafe && resolvedKind !== "unknown-outcome" && (
        <button className="foundation-button foundation-button-secondary" type="button" onClick={onRetry}>Retry</button>
      )}
    </section>
  );
}
