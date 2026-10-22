import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { ApiError } from "../../shared/api";
import { useAuth } from "../../shared/auth";
import { generateRecoveryPlans, getRecoveryCase, getRecoveryPlans } from "./api";
import type { RecoveryCase, RecoveryPlanVersion } from "./types";
import "./recovery.css";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The recovery service could not be reached. Check the API and try again.";
}

function isPermissionError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

function statusLabel(status: RecoveryPlanVersion["feasibility_status"]): string {
  return status.replaceAll("_", " ");
}

function formatCost(value: string, currency: string): string {
  return `${currency} ${Number(value).toFixed(2)}`;
}

function formatDelay(minutes: number): string {
  if (minutes === 0) return "No additional delay";
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const parts = [];
  if (days) parts.push(`${days}d`);
  if (hours) parts.push(`${hours}h`);
  return `${parts.join(" ")} delay`;
}

function EvidenceList({ refs }: { refs: string[] }) {
  if (!refs.length) return <span className="muted text-sm">None recorded</span>;
  return (
    <div className="recovery-evidence-list">
      {refs.map((ref) => (
        <span className="recovery-evidence-chip" key={ref}>
          {ref}
        </span>
      ))}
    </div>
  );
}

function ErrorState({ error }: { error: unknown }) {
  const permission = isPermissionError(error);
  return (
    <section className="recovery-error" data-testid={permission ? "recovery-permission-error" : "recovery-error"}>
      <span className="recovery-status-badge">{permission ? "PERMISSION DENIED" : "RECOVERY API ERROR"}</span>
      <h2>{permission ? "This tenant cannot view the recovery case" : "Recovery data is unavailable"}</h2>
      <p>{errorMessage(error)}</p>
      <p className="muted text-sm">No plan was approved or executed by this screen.</p>
    </section>
  );
}

function PlanCard({
  plan,
  selected,
  onSelect,
  currentSnapshotVersion,
  currentCommitmentVersion,
}: {
  plan: RecoveryPlanVersion;
  selected: boolean;
  onSelect: () => void;
  currentSnapshotVersion: number;
  currentCommitmentVersion: number;
}) {
  const invalid = plan.feasibility_status === "INFEASIBLE" || plan.feasibility_status === "UNKNOWN";
  const stale =
    plan.snapshot_version !== currentSnapshotVersion ||
    plan.evaluation.commitment_version !== currentCommitmentVersion;
  return (
    <article className={`recovery-option-card ${selected ? "selected" : ""}`} data-testid={`recovery-plan-${plan.plan_id}`}>
      <div className="recovery-option-header">
        <div>
          <p className="recovery-option-kicker">{plan.strategy.replaceAll("_", " ")}</p>
          <h3>{plan.plan_id}</h3>
        </div>
        <span className={`recovery-status-pill status-${plan.feasibility_status.toLowerCase()}`}>
          {statusLabel(plan.feasibility_status)}
        </span>
      </div>
      <p className="recovery-option-label">
        {plan.strategy === "ALTERNATIVE_SUPPLY"
          ? "Alternative supply for packaging shortage"
          : "Reschedule with partial fulfilment proposal"}
      </p>
      {plan.recommended && <span className="recovery-recommended">Recommended under current preferences</span>}
      <div className="recovery-metric-grid">
        <div>
          <span>Estimated cost</span>
          <strong>{formatCost(plan.estimated_extra_cost, plan.currency)}</strong>
        </div>
        <div>
          <span>Customer impact</span>
          <strong>{plan.customer_impact}</strong>
        </div>
        <div>
          <span>Delay</span>
          <strong>{formatDelay(plan.estimated_delay_minutes)}</strong>
        </div>
        <div>
          <span>Risk</span>
          <strong>{plan.risk_level}</strong>
        </div>
      </div>
      <div className="recovery-option-meta">
        <span>Validation: {plan.evaluation.validation_source.replaceAll("_", " ")}</span>
        <span>Score: {plan.ranking_score}</span>
        {stale && <span className="recovery-stale">STALE EVALUATION</span>}
      </div>
      <button
        className="btn btn-outline btn-sm"
        type="button"
        disabled={invalid}
        onClick={onSelect}
        aria-pressed={selected}
        data-testid={`select-${plan.plan_id}`}
      >
        {invalid ? "Unavailable for review" : selected ? "Selected for review" : "Review option"}
      </button>
    </article>
  );
}

function PlanDetail({ plan }: { plan: RecoveryPlanVersion }) {
  const invalid = plan.feasibility_status === "INFEASIBLE" || plan.feasibility_status === "UNKNOWN";
  return (
    <section className="recovery-detail-card" data-testid="recovery-plan-detail">
      <div className="section-header">
        <div>
          <p className="eyebrow">Selected option</p>
          <h2>{plan.plan_id} · {plan.strategy.replaceAll("_", " ")}</h2>
        </div>
        <span className="status-pill warning">Review only</span>
      </div>
      <div className="recovery-detail-grid">
        <div>
          <h3>Constraints</h3>
          <ul>{plan.constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}</ul>
        </div>
        <div>
          <h3>Assumptions</h3>
          <ul>{plan.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
        </div>
        <div>
          <h3>Evidence</h3>
          <EvidenceList refs={plan.evidence_refs} />
        </div>
      </div>
      <div className="recovery-execution-gate" data-testid="execution-gate">
        <strong>{invalid ? "This option cannot be selected for execution." : "Approval and provider execution are not available yet."}</strong>
        <span>No action has been executed. A future approval flow must revalidate commitment version, snapshot version, and all listed preconditions.</span>
      </div>
    </section>
  );
}

export function RecoveryPage() {
  const { id = "demo" } = useParams<{ id: string }>();
  const { authHeaders } = useAuth();
  const queryClient = useQueryClient();
  const commitmentId = id === "demo" ? "com_001" : id;
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);

  const caseQuery = useQuery({
    queryKey: ["recovery-case", commitmentId, authHeaders.tenantId],
    queryFn: () => getRecoveryCase(commitmentId, authHeaders),
  });
  const plansQuery = useQuery({
    queryKey: ["recovery-plans", commitmentId, authHeaders.tenantId],
    queryFn: () => getRecoveryPlans(commitmentId, authHeaders),
    enabled: caseQuery.isSuccess,
  });
  const generateMutation = useMutation({
    mutationFn: (caseData: RecoveryCase) =>
      generateRecoveryPlans(
        commitmentId,
        {
          expected_commitment_version: caseData.commitment_version,
          assessment_id: caseData.trigger_assessment.assessment_id,
        },
        authHeaders,
      ),
    onSuccess: (nextCase) => {
      queryClient.setQueryData(["recovery-case", commitmentId, authHeaders.tenantId], nextCase);
      queryClient.invalidateQueries({ queryKey: ["recovery-plans", commitmentId, authHeaders.tenantId] });
      setSelectedPlanId(null);
    },
  });

  const caseData = caseQuery.data;
  const plans = plansQuery.data?.plans ?? caseData?.plans ?? [];
  const selectedPlan = useMemo(() => plans.find((plan) => plan.plan_id === selectedPlanId), [plans, selectedPlanId]);

  useEffect(() => {
    if (selectedPlanId && !plans.some((plan) => plan.plan_id === selectedPlanId)) setSelectedPlanId(null);
  }, [plans, selectedPlanId]);

  if (caseQuery.isLoading) {
    return <section className="recovery-loading" role="status">Loading recovery case…</section>;
  }
  if (caseQuery.isError) return <ErrorState error={caseQuery.error} />;
  if (!caseData) return <section className="empty-state-card"><h2>Recovery case not found</h2></section>;
  if (plansQuery.isError) return <ErrorState error={plansQuery.error} />;

  return (
    <div className="recovery-page" data-testid="recovery-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">P3 · Recovery planning</p>
          <h2>Recovery workspace</h2>
          <p className="muted">Compare typed, evidence-linked options for commitment {caseData.commitment_id}.</p>
        </div>
        <span className="status-pill warning">{caseData.storage_mode.replaceAll("_", " ")}</span>
      </header>

      <section className="recovery-incident-grid">
        <article className="recovery-panel">
          <div className="section-header"><h2>Incident</h2><span className="recovery-status-pill status-infeasible">{caseData.trigger_assessment.status}</span></div>
          <p className="muted">Material shortage detected for the confirmed customer commitment.</p>
          <dl className="recovery-facts">
            <div><dt>Assessment</dt><dd>{caseData.trigger_assessment.assessment_id} · v{caseData.trigger_assessment.commitment_version}</dd></div>
            <div><dt>Snapshot</dt><dd>{caseData.operational_snapshot.snapshot_id} · v{caseData.operational_snapshot.snapshot_version}</dd></div>
            <div><dt>Evidence</dt><dd><EvidenceList refs={caseData.evidence_refs} /></dd></div>
          </dl>
          <ul className="recovery-constraint-list">
            {caseData.trigger_assessment.constraints.map((constraint) => (
              <li key={`${constraint.code}-${constraint.resource_id}`}>
                {constraint.code} · {constraint.resource_id} · shortage {constraint.shortage ?? "unknown"} {constraint.unit ?? ""}
              </li>
            ))}
          </ul>
        </article>
        <article className="recovery-panel">
          <div className="section-header"><h2>Confirmed commitment</h2><span className="status-pill">v{caseData.commitment.commitment_version}</span></div>
          <dl className="recovery-facts">
            <div><dt>Customer</dt><dd>{caseData.commitment.customer_id}</dd></div>
            <div><dt>Order</dt><dd>{caseData.commitment.order_id}</dd></div>
            <div><dt>Terms</dt><dd>{caseData.commitment.terms.quantity} {caseData.commitment.terms.unit} {caseData.commitment.terms.sku}</dd></div>
            <div><dt>Deadline</dt><dd>{new Date(caseData.commitment.terms.deadline).toLocaleString()}</dd></div>
            <div><dt>Recorded confirmation</dt><dd><EvidenceList refs={caseData.customer_confirmation_evidence_refs} /></dd></div>
            <div><dt>Fulfilment proof</dt><dd><EvidenceList refs={caseData.fulfilment_evidence_refs} /></dd></div>
          </dl>
        </article>
      </section>

      <section className="recovery-panel">
        <div className="section-header">
          <div><p className="eyebrow">Preference-based comparison</p><h2>Recovery options</h2></div>
          {!plans.length && (
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => generateMutation.mutate(caseData)}
              disabled={generateMutation.isPending}
              data-testid="generate-recovery"
            >
              {generateMutation.isPending ? "Generating…" : "Generate plans"}
            </button>
          )}
        </div>
        <p className="muted text-sm">
          Weights: cost {caseData.preferences.cost_weight}, delay {caseData.preferences.delay_weight}, risk {caseData.preferences.risk_weight}, customer impact {caseData.preferences.customer_impact_weight}. Lower score ranks first; there is no universal BEST option.
        </p>
        {generateMutation.isError && <p className="recovery-inline-error">{errorMessage(generateMutation.error)}</p>}
        {!plans.length && <div className="empty-state-card"><h3>No generated options yet</h3><p className="muted">Generate a review-only comparison from the current commitment and assessment snapshot.</p></div>}
        {!!plans.length && (
          <div className="recovery-options-grid">
            {plans.map((plan) => (
              <PlanCard
                key={plan.plan_id}
                plan={plan}
                selected={selectedPlanId === plan.plan_id}
                onSelect={() => setSelectedPlanId(plan.plan_id)}
                currentSnapshotVersion={caseData.operational_snapshot.snapshot_version}
                currentCommitmentVersion={caseData.commitment_version}
              />
            ))}
          </div>
        )}
      </section>

      {selectedPlan && <PlanDetail plan={selectedPlan} />}
      <section className="recovery-audit-note">
        <strong>Evidence and assumptions stay visible.</strong>
        <span>Approval decisions are version- and snapshot-scoped. This first P3 slice does not approve, execute, communicate, or mutate the authoritative Core commitment.</span>
      </section>
    </div>
  );
}
