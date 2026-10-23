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

function readable(value: string): string {
  return value.replaceAll("_", " ");
}

function CaseStatus({ status }: { status: string }) {
  const normalized = status.toUpperCase();
  const tone = normalized === "COMPLETED"
    ? "is-success"
    : normalized === "NEEDS_REPLAN"
      ? "is-danger"
      : normalized.includes("AWAITING") || normalized === "NEEDS_EVALUATION"
        ? "is-pending"
        : "is-neutral";
  return <span className={`recovery-case-status ${tone}`}>{readable(status)}</span>;
}

function CaseFact({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="recovery-case-fact">
      <dt>{label}</dt>
      <dd>{value || "Not available"}</dd>
      {detail && <span>{detail}</span>}
    </div>
  );
}

function TriggerHistory({ triggers }: { triggers: RecoveryTriggerView[] }) {
  if (!triggers.length) {
    return <p className="recovery-case-empty">No persisted trigger details were returned.</p>;
  }

  return (
    <ol className="recovery-case-event-list">
      {triggers.map((trigger) => (
        <li key={trigger.event_id}>
          <span className="recovery-case-event-marker" aria-hidden="true">!</span>
          <div className="recovery-case-event-body">
            <div className="recovery-case-event-heading">
              <strong>{trigger.event_id}</strong>
              <time dateTime={trigger.occurred_at}>{new Date(trigger.occurred_at).toLocaleString()}</time>
            </div>
            <p>Assessment {trigger.assessment_id}</p>
            <p>
              Evaluated commitment v{trigger.assessment_commitment_version ?? "unknown"};
              resulting event v{trigger.commitment_version}
            </p>
            <p>Snapshot {trigger.snapshot_id ?? "unavailable"} · v{trigger.snapshot_version}</p>
            {trigger.assessment_provenance_status && (
              <span className="recovery-case-provenance">
                Provenance: {readable(trigger.assessment_provenance_status)}
              </span>
            )}
            {!!trigger.evidence_refs.length && (
              <ul className="recovery-case-evidence-inline">
                {trigger.evidence_refs.map((ref) => <li key={ref}><code>{ref}</code></li>)}
              </ul>
            )}
          </div>
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
  const evaluationReadiness = caseView.evaluation_readiness ?? "AWAITING_EVALUATION_INPUTS";

  return (
    <main className="recovery-case-page" data-testid="recovery-case-page">
      <header className="recovery-case-header">
        <div className="recovery-case-title-block">
          <p className="recovery-case-eyebrow"><span aria-hidden="true">P3</span> Recovery workspace</p>
          <h1>Recovery case</h1>
          <p className="recovery-case-subtitle">
            Risk history and decision evidence for commitment <code>{caseView.commitment_id}</code>.
          </p>
        </div>
        <div className="recovery-case-header-actions">
          <CaseStatus status={caseView.status} />
          <Link className="recovery-case-primary-link" to={`/recovery/${encodeURIComponent(caseView.commitment_id)}/plans`}>
            Open planning workspace <span aria-hidden="true">→</span>
          </Link>
        </div>
      </header>

      <nav className="recovery-case-context-links" aria-label="Related commitment pages">
        <Link to={`/commitments/${encodeURIComponent(caseView.commitment_id)}`}>Commitment context</Link>
        <span className="recovery-case-context-unavailable" role="note">
          Impact detail unavailable — the case API does not return an impact ID
        </span>
        <Link to="/communications">Communication center</Link>
      </nav>

      <section className="recovery-case-summary" aria-label="Current recovery record">
        <div className="recovery-case-summary-item">
          <span>Recovery case</span>
          <strong><code>{caseView.case_id}</code></strong>
          <small>Case version {caseView.case_version}</small>
        </div>
        <div className="recovery-case-summary-item">
          <span>Commitment</span>
          <strong><code>{caseView.commitment_id}</code></strong>
          <small>Core version {caseView.commitment_version}</small>
        </div>
        <div className="recovery-case-summary-item">
          <span>Evaluation readiness</span>
          <strong className={evaluationReadiness === "CASE_COMPLETED" ? "is-ready" : "is-waiting"}>
            {readable(evaluationReadiness)}
          </strong>
          <small>{caseView.storage_mode === "DURABLE_DATABASE" ? "Persisted record" : "Synthetic storage"}</small>
        </div>
      </section>

      {!!caseView.missing_evaluation_inputs?.length && (
        <section className="recovery-case-notice" role="status" aria-label="Evaluation inputs pending">
          <span className="recovery-case-notice-icon" aria-hidden="true">i</span>
          <div>
            <strong>Planning is waiting for trusted evaluation inputs</strong>
            <p>
              Waiting for: {caseView.missing_evaluation_inputs.join(", ").replaceAll("_", " ")}.
              The case is readable, but plans cannot be generated from missing evidence.
            </p>
          </div>
        </section>
      )}

      <div className="recovery-case-content-grid">
        <section className="recovery-case-panel" aria-label="Recovery case details">
          <div className="recovery-case-panel-heading">
            <div>
              <p className="recovery-case-section-kicker">Record identity</p>
              <h2>Case details</h2>
            </div>
            <span className="recovery-case-panel-index">01</span>
          </div>
          <dl className="recovery-case-facts">
            <CaseFact label="Tenant" value={caseView.tenant_id} />
            <CaseFact label="Created" value={new Date(caseView.created_at).toLocaleString()} />
            <CaseFact label="Last updated" value={new Date(caseView.updated_at).toLocaleString()} />
            <CaseFact
              label="Assessment"
              value={assessment
                ? `${assessment.assessment_id} · commitment v${assessment.commitment_version}`
                : latestTrigger
                  ? `${latestTrigger.assessment_id} · commitment v${latestTrigger.assessment_commitment_version ?? "unknown"}`
                  : "Not available"}
              detail={assessment ? `Assessed ${assessment.assessed_at ? new Date(assessment.assessed_at).toLocaleString() : "time not recorded"}` : undefined}
            />
            <CaseFact
              label="Operational snapshot"
              value={snapshot
                ? `${snapshot.snapshot_id} · v${snapshot.snapshot_version}`
                : latestTrigger
                  ? `${latestTrigger.snapshot_id ?? "Snapshot unavailable"} · v${latestTrigger.snapshot_version}`
                  : "Not available"}
              detail={snapshot?.captured_at ? `Captured ${new Date(snapshot.captured_at).toLocaleString()}` : undefined}
            />
          </dl>
        </section>

        <section className="recovery-case-panel" aria-label="Recovery trigger history">
          <div className="recovery-case-panel-heading">
            <div>
              <p className="recovery-case-section-kicker">Source event history</p>
              <h2>Risk triggers</h2>
            </div>
            <span className="recovery-case-count">{caseView.trigger_events?.length ?? 0}</span>
          </div>
          <TriggerHistory triggers={caseView.trigger_events ?? []} />
        </section>
      </div>

      <section className="recovery-case-panel" aria-label="Customer response history">
        <div className="recovery-case-panel-heading">
          <div>
            <p className="recovery-case-section-kicker">Version-bound response evidence</p>
            <h2>Customer responses</h2>
          </div>
          <span className="recovery-case-count">{caseView.customer_response_events?.length ?? 0}</span>
        </div>
        {caseView.customer_response_events?.length ? (
          <ol className="recovery-case-response-list">
            {caseView.customer_response_events.map((response) => (
              <li key={response.event_id}>
                <div className="recovery-case-response-topline">
                  <strong>{response.intent.replaceAll("_", " ")} · {response.outcome.replaceAll("_", " ")}</strong>
                  <time dateTime={response.received_at}>{new Date(response.received_at).toLocaleString()}</time>
                </div>
                <p>Proposal {response.proposal_id} · v{response.proposal_version}</p>
                <p>Confirmation <code>{response.confirmation_id}</code> · event <code>{response.event_id}</code></p>
                {response.proposed_terms && Object.keys(response.proposed_terms).length > 0 && (
                  <p>Customer-proposed terms: {Object.entries(response.proposed_terms)
                    .map(([name, value]) => `${readable(name)}: ${value}`).join(" · ")}</p>
                )}
                <div className="recovery-case-evidence-inline" aria-label="Response evidence">
                  {response.evidence_refs.map((ref) => <code key={ref}>{ref}</code>)}
                </div>
              </li>
            ))}
          </ol>
        ) : <p className="recovery-case-empty">No persisted rejection or counteroffer evidence was returned.</p>}
      </section>

      <section className="recovery-case-panel" aria-label="Recovery source evidence">
        <div className="recovery-case-panel-heading">
          <div>
            <p className="recovery-case-section-kicker">Traceable source references</p>
            <h2>Evidence</h2>
          </div>
          <span className="recovery-case-count">{evidence.length}</span>
        </div>
        {evidence.length ? (
          <ul className="recovery-case-evidence-list">
            {evidence.map((ref) => <li key={ref}><code>{ref}</code></li>)}
          </ul>
        ) : <p className="recovery-case-empty">No evidence references were returned.</p>}
      </section>

      <p className="recovery-case-readonly" role="note">
        Read-only case view. This view does not approve plans or execute recovery actions, send customer messages, or mark fulfilment.
      </p>
    </main>
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
    return <main className="recovery-case-page"><section className="recovery-case-error" role="alert"><h1>Recovery case not found</h1></section></main>;
  }

  if (caseQuery.isLoading) {
    return (
      <main className="recovery-case-page">
        <header className="recovery-case-header"><div><p className="recovery-case-eyebrow">P3 · Recovery workspace</p><h1>Recovery case</h1></div></header>
        <section className="recovery-case-loading" role="status" aria-live="polite">
          <span className="recovery-case-loading-mark" aria-hidden="true" />
          <div><strong>Loading recovery case</strong><p>Checking the persisted case and its evidence history.</p></div>
        </section>
      </main>
    );
  }

  if (caseQuery.isError) {
    return (
      <main className="recovery-case-page">
        <section className="recovery-case-error" role="alert">
          <p className="recovery-case-section-kicker">Recovery data request</p>
          <h1>{errorTitle(caseQuery.error)}</h1>
          <p>{errorMessage(caseQuery.error)}</p>
          <p className="recovery-case-muted">No approval or recovery action was performed.</p>
          <button type="button" className="recovery-case-button" onClick={() => void caseQuery.refetch()}>
            Retry loading
          </button>
        </section>
      </main>
    );
  }

  return caseQuery.data ? <LoadedCase caseView={caseQuery.data} /> : null;
}
