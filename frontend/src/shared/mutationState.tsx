import { ErrorState, classifyUiError } from "./ErrorState";

export type MutationState =
  | { status: "idle" }
  | { status: "queued"; message?: string }
  | { status: "pending"; message?: string }
  | { status: "success"; message: string; authoritativeState: string }
  | { status: "failure"; error: unknown; retrySafe?: boolean; operationMayHaveApplied?: boolean; onRetry?: () => void };

export interface MutationStateViewProps {
  state: MutationState;
}

export function MutationStateView({ state }: MutationStateViewProps) {
  if (state.status === "idle") return null;
  if (state.status === "queued") {
    return <p className="foundation-mutation foundation-mutation-pending" role="status">{state.message ?? "Request submitted. Completion is not yet confirmed."}</p>;
  }
  if (state.status === "pending") {
    return <p className="foundation-mutation foundation-mutation-pending" role="status" aria-busy="true">{state.message ?? "Request in progress…"}</p>;
  }
  if (state.status === "success") {
    return <p className="foundation-mutation foundation-mutation-success" role="status">{state.message} <span>Server state: {state.authoritativeState}</span></p>;
  }
  const kind = classifyUiError(state.error, { retrySafe: state.retrySafe, operationMayHaveApplied: state.operationMayHaveApplied });
  return <ErrorState kind={kind} error={state.error} retrySafe={state.retrySafe} onRetry={state.onRetry} />;
}
