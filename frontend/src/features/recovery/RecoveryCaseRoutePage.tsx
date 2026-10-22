import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../../shared/api";
import { useAuth } from "../../shared/auth";
import { getRecoveryCaseView, SyntheticRecoveryCaseError } from "./recoveryCaseApi";
import type { RecoveryCaseView, RecoveryTriggerView } from "./recoveryCaseView";
import "./recoveryCaseRoute.css";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.message} (${error.code}).`;
  if (error instanceof SyntheticRecoveryCaseError) return error.message;
  return "Recovery data could not be loaded. Try again.";
}

function errorTitle(error: unknown): string {
  if (error instanceof SyntheticRecoveryCaseError) return "Durable recovery data required";
  if (error instanceof ApiError && error.status === 404) return "Recovery case not found";
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return "Recovery case unavailable";
  if (error instanceof ApiError && error.status === 409) return "Recovery case needs current evaluation data";
  return "Recovery data unavailable";
}

function uniqueEvidence(caseView: RecoveryCaseView): string[] {
  return [...new Set([
    ...(caseView.evidence_refs ?? []),
    ...(caseView.trigger_assessment?.evidence_refs ?? []),
    ...(caseView.operational_snapshot?.evidence_refs ?? []),
    ...(caseView.trigger_events ?? []).flatMap((trigger) => trigger.evidence_refs),
  ])];
}

function TriggerHistory({ triggers }: { triggers: RecoveryTriggerView[] }) {
  if (!triggers.length) {
    return <p className="recovery-case-muted">No persisted trigger details were returned.</p>;
  }

  return (
    <ol className="recovery-case-trigger-list">
      {triggers.map((trigger) => (
        <li key={trigger.event_id}>
          <strong>{trigger.event_id}</strong>
          <span>Assessment {trigger.assessment_id}</span>
          <span>
            Evaluated commitment v{trigger.assessment_commitment_version ?? "unknown"};
            resulting event v{trigger.commitment_version}
          </span>
          <span>Snapshot {trigger.snapshot_id ?? "unavailable"} · v{trigger.snapshot_version}</span>
          {trigger.assessment_provenance_status && (
            <span>Provenance: {trigger.assessment_provenance_status.replaceAll("_", " ")}</span>
          )}
          <time dateTime={trigger.occurred_at}>{new Date(trigger.occurred_at).toLocaleString()}</time>
        </li>
      ))}
    </ol>
  );
}

function LoadedCase({ caseView }: { caseView: RecoveryCaseView }) {
  const evidence = uniqueEvidence(caseView);
  const assessment = caseView.trigger_assessment;
  const snapshot = caseView.operational_snapshot;
  const latestTrigger = caseView.trigger_events?.at(-1);

  return (
    <div className="recovery-case-page">
      <header className="recovery-case-header">
        <div>
          <p className="recovery-case-eyebrow">P3 · Recovery</p>
          <h1>Recovery case</h1>
          <p className="recovery-case-muted">Commitment {caseView.commitment_id}</p>
        </div>
        <div className="recovery-case-header-actions">
          <span className="recovery-case-status">{caseView.status.replaceAll("_", " ")}</span>
          <Link className="btn btn-secondary" to={"/recovery/" + encodeURIComponent(caseView.commitment_id) + "/plans"}>Open planning workspace</Link>
        </div>
      </header>

      <section className="recovery-case-panel" aria-label="Recovery case details">
        <h2>Persisted case</h2>
        <dl className="recovery-case-facts">
          <div><dt>Case ID</dt><dd>{caseView.case_id}</dd></div>
          <div><dt>Tenant</dt><dd>{caseView.tenant_id}</dd></div>
          <div><dt>Case version</dt><dd>{caseView.case_version}</dd></div>
          <div><dt>Commitment version</dt><dd>{caseView.commitment_version}</dd></div>
          <div>
            <dt>Assessment</dt>
            <dd>{assessment
              ? `${assessment.assessment_id} · commitment v${assessment.commitment_version}`
              : latestTrigger
                ? `${latestTrigger.assessment_id} · commitment v${latestTrigger.assessment_commitment_version ?? "unknown"}`
                : "Not available"}</dd>
          </div>
          <div>
            <dt>Snapshot</dt>
            <dd>{snapshot
              ? `${snapshot.snapshot_id} · v${snapshot.snapshot_version}`
              : latestTrigger
                ? `${latestTrigger.snapshot_id ?? "Snapshot"} · v${latestTrigger.snapshot_version}`
                : "Not available"}</dd>
          </div>
          {caseView.evaluation_readiness && (
            <div>
              <dt>Evaluation readiness</dt>
              <dd>{caseView.evaluation_readiness.replaceAll("_", " ")}</dd>
            </div>
          )}
        </dl>
        {!!caseView.missing_evaluation_inputs?.length && (
          <p className="recovery-case-muted">
            Waiting for: {caseView.missing_evaluation_inputs.join(", ").replaceAll("_", " ")}
          </p>
        )}
      </section>

      <section className="recovery-case-panel" aria-label="Recovery trigger history">
        <h2>Trigger history</h2>
        <TriggerHistory triggers={caseView.trigger_events ?? []} />
      </section>

      <section className="recovery-case-panel" aria-label="Recovery source evidence">
        <h2>Source evidence</h2>
        {evidence.length ? (
          <ul className="recovery-case-evidence">
            {evidence.map((ref) => <li key={ref}>{ref}</li>)}
          </ul>
        ) : <p className="recovery-case-muted">No evidence references were returned.</p>}
      </section>

      <p className="recovery-case-readonly" role="note">
        Read-only case view. This route does not approve plans or execute recovery actions.
      </p>
    </div>
  );
}

export function RecoveryCaseRoutePage() {
  const { id } = useParams<{ id: string }>();
  const { authHeaders } = useAuth();
  const caseQuery = useQuery({
    queryKey: ["recovery-case-route", id, authHeaders.tenantId, authHeaders.actorId],
    queryFn: () => getRecoveryCaseView(id ?? "", authHeaders),
    enabled: Boolean(id),
  });

  if (!id) {
    return <section className="recovery-case-error" role="alert"><h1>Recovery case not found</h1></section>;
  }

  if (caseQuery.isLoading) {
    return (
      <section className="recovery-case-page">
        <h1>Recovery case</h1>
        <p className="recovery-case-loading" role="status">Loading recovery case…</p>
      </section>
    );
  }

  if (caseQuery.isError) {
    return (
      <section className="recovery-case-error" role="alert">
        <h1>Recovery case</h1>
        <h2>{errorTitle(caseQuery.error)}</h2>
        <p>{errorMessage(caseQuery.error)}</p>
        <p>No approval or recovery action was performed.</p>
        <button type="button" className="btn btn-secondary" onClick={() => void caseQuery.refetch()}>
          Retry loading
        </button>
      </section>
    );
  }

  return caseQuery.data ? <LoadedCase caseView={caseQuery.data} /> : null;
}
