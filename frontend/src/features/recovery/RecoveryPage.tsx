import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../../shared/api";
import { useAuth } from "../../shared/auth";
import { ConfirmationDialog } from "../../shared/ConfirmationDialog";
import { decideRecoveryPlan, executeRecoveryTask, generateRecoveryPlans, getActionHistory, getApprovalHistory, getRecoveryCaseOrTrigger, getRecoveryPlans, requestRecoveryCommunication } from "./api";
import type { ApprovalDecision, DurableActionView, RecoveryCase, RecoveryPlanVersion } from "./types";
import { SyntheticRecoveryDemo } from "./SyntheticRecoveryDemo";
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

function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const permission = isPermissionError(error);
  return (
    <section className="recovery-error" data-testid={permission ? "recovery-permission-error" : "recovery-error"}>
      <span className="recovery-status-badge">{permission ? "PERMISSION DENIED" : "RECOVERY API ERROR"}</span>
      <h2>{permission ? "This tenant cannot view the recovery case" : "Recovery data is unavailable"}</h2>
      <p>{errorMessage(error)}</p>
      <p className="muted text-sm">No plan was approved or executed by this screen.</p>
      {onRetry && <button className="btn btn-outline btn-sm" type="button" onClick={onRetry}>Retry loading</button>}
    </section>
  );
}

function PlanCard({
  plan,
  selected,
  onSelect,
  currentSnapshotVersion,
  currentCommitmentVersion,
  showWorkflowStatus,
}: {
  plan: RecoveryPlanVersion;
  selected: boolean;
  onSelect: () => void;
  currentSnapshotVersion: number;
  currentCommitmentVersion: number;
  showWorkflowStatus: boolean;
}) {
  const invalid = plan.feasibility_status === "INFEASIBLE" || plan.feasibility_status === "UNKNOWN";
  const policyRecommended =
    plan.recommended && plan.recommendation_label === "RECOMMENDED_UNDER_POLICY";
  const stale =
    plan.snapshot_version !== currentSnapshotVersion ||
    (plan.core_commitment_version ?? plan.evaluation.commitment_version) !== currentCommitmentVersion;
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
      {policyRecommended && <span className="recovery-recommended">RECOMMENDED UNDER POLICY</span>}
      {policyRecommended && plan.recommendation_reason && <p className="recovery-policy-reason">Policy reason: {plan.recommendation_reason}</p>}
      {policyRecommended && plan.recommendation_qualification && <p className="muted text-sm">{plan.recommendation_qualification}</p>}
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
        <span>Validation: {plan.evaluation.validation_source === "REAL_P2_VALIDATED" ? "P2 evaluator" : "test double only"}</span>
        <span>Readiness: {plan.evaluation.readiness.replaceAll("_", " ")}</span>
        <span>Solver: {plan.evaluation.solver_status.replaceAll("_", " ")}</span>
        <span>Policy score: {plan.ranking_score ?? "Not ranked"}{plan.rank ? ` · rank ${plan.rank}` : ""}</span>
        {stale && <span className="recovery-stale">STALE EVALUATION</span>}
      </div>
      {plan.score_breakdown && (
        <p className="muted text-sm">
          Score components: cost {plan.score_breakdown.cost_score}, delay {plan.score_breakdown.delay_score},
          affected commitments {plan.score_breakdown.affected_commitments_score}, disruption {plan.score_breakdown.operational_disruption_score},
          supplier uncertainty {plan.score_breakdown.supplier_uncertainty_score}, customer confirmation {plan.score_breakdown.customer_confirmation_score}.
        </p>
      )}
      <div>
        <strong className="muted text-sm">Validation explanation</strong>
        {plan.evaluation.validation_source === "TEST_DOUBLE_VALIDATED" && (
          <p className="recovery-inline-error">Test-double result; this is not proof of a P2 assessment.</p>
        )}
        {(plan.evaluation.hard_constraint_reasons.length || plan.constraints.length) ? (
          <ul className="recovery-constraint-explanations">
            {[...new Set([...plan.evaluation.hard_constraint_reasons, ...plan.constraints])].map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        ) : (
          <p className="muted text-sm">No constraint explanation was returned with this plan.</p>
        )}
      </div>
      <div className="recovery-option-meta">
        <span>Affected commitments: {plan.evaluation.affected_commitment_ids.length ? plan.evaluation.affected_commitment_ids.join(", ") : "None reported by evaluator"}</span>
        {showWorkflowStatus && <span>Manager review: {plan.approval_state} · execution: {plan.execution_state}</span>}
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

function PlanDetail({ plan, stale }: { plan: RecoveryPlanVersion; stale: boolean }) {
  const invalid = plan.feasibility_status === "INFEASIBLE" || plan.feasibility_status === "UNKNOWN";
  return (
    <section className="recovery-detail-card" data-testid="recovery-plan-detail">
      <div className="section-header">
        <div>
          <p className="eyebrow">Selected option</p>
          <h2>{plan.plan_id} · {plan.strategy.replaceAll("_", " ")}</h2>
        </div>
        <span className="status-pill warning">Manager review</span>
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
      <section aria-label="Action preview">
        <h3>Action preview and gates</h3>
        <ul className="recovery-action-list">
          {plan.actions.map((action) => (
            <li key={action.action_id}>
              <strong>{action.type.replaceAll("_", " ")}</strong>
              <span> · {action.requires_approval ? "Manager approval required" : "No manager approval flag returned"}</span>
              <ul>{action.preconditions.map((precondition) => <li key={precondition}>{precondition}</li>)}</ul>
            </li>
          ))}
        </ul>
        {plan.customer_confirmation_required && <p className="recovery-inline-error">Customer confirmation is a separate dependency; approval does not change the customer commitment.</p>}
      </section>
      <div className="recovery-execution-gate" data-testid="execution-gate">
        <strong>{invalid ? "This option is infeasible or unknown and cannot proceed." : stale ? "This option is stale; it cannot proceed without revalidation." : "Manager approval and internal action are separate steps."}</strong>
        <span>Execution creates only an internal review task. Customer terms remain unchanged.</span>
      </div>
    </section>
  );
}

function ManagerReviewPanel({ decisions, actorRole }: { decisions: ApprovalDecision[]; actorRole: string }) {
  const durableDecisions = decisions.filter((decision) => decision.persistence_mode === "DURABLE_DATABASE");

  return (
    <section className="recovery-panel" aria-labelledby="recovery-manager-review-title">
      <div className="section-header">
        <div><p className="eyebrow">Durable decision history</p><h2 id="recovery-manager-review-title">Manager review</h2></div>
        <span className="recovery-status-pill">Workspace role: {actorRole}</span>
      </div>
      <p className="muted text-sm">The role shown is a UI context. The server remains the authority for approval permission.</p>
      {durableDecisions.length ? (
        <div className="recovery-timeline">
          {durableDecisions.map((decision) => (
            <article className="recovery-review-record" key={decision.approval_id}>
              <strong>{decision.decision} · {decision.plan_id} v{decision.plan_version}</strong>
              <span>{decision.actor_id} ({decision.actor_role}) · {decision.decided_at ? new Date(decision.decided_at).toLocaleString() : "Decision time not recorded"}</span>
              <span>Snapshot v{decision.snapshot_version} · {decision.reason}</span>
              <EvidenceList refs={[...decision.evidence_refs, ...decision.audit_refs]} />
            </article>
          ))}
        </div>
      ) : (
        <div className="recovery-execution-gate">
          <strong>No durable manager decision is available.</strong>
          <span>No durable approval decision was returned for the selected plan.</span>
        </div>
      )}
    </section>
  );
}

interface RecoveryActivityItem {
  key: string;
  occurredAt: string;
  title: string;
  detail: string;
  refs: string[];
}

function activityItems(caseData: RecoveryCase, plans: RecoveryPlanVersion[]): RecoveryActivityItem[] {
  const assessmentItem: RecoveryActivityItem[] = caseData.trigger_assessment ? [{
    key: `assessment-${caseData.trigger_assessment.assessment_id}`,
    occurredAt: caseData.trigger_assessment.assessed_at,
    title: `${caseData.storage_mode === "IN_MEMORY_SYNTHETIC" ? "Sample assessment reference" : "Assessment returned"} · ${caseData.trigger_assessment.assessment_id}`,
    detail: `${caseData.trigger_assessment.status} · commitment v${caseData.trigger_assessment.commitment_version} · snapshot v${caseData.trigger_assessment.snapshot_version}${caseData.storage_mode === "IN_MEMORY_SYNTHETIC" ? " · synthetic, not authoritative P2 provenance" : ""}.`,
    refs: caseData.trigger_assessment.evidence_refs,
  }] : [];
  const triggers: RecoveryActivityItem[] = (caseData.trigger_events ?? []).map((event) => ({
    key: `trigger-${event.event_id}`,
    occurredAt: event.occurred_at,
    title: `Risk trigger · ${event.event_id}`,
    detail: `Assessment reference ${event.assessment_id}; provenance ${event.assessment_provenance_status.replaceAll("_", " ")}.`,
    refs: event.evidence_refs,
  }));
  const resolutions: RecoveryActivityItem[] = (caseData.resolution_events ?? []).map((event) => ({
    key: `resolution-${event.event_id}`,
    occurredAt: event.occurred_at,
    title: `Resolution event · ${event.event_id}`,
    detail: `Commitment v${event.commitment_version}${event.assessment_id ? ` · assessment ${event.assessment_id}` : ""}.`,
    refs: event.causation_id ? [event.causation_id] : [],
  }));
  const evaluations: RecoveryActivityItem[] = plans.map((plan) => ({
    key: `evaluation-${plan.plan_id}-${plan.plan_version}`,
    occurredAt: plan.evaluation.evaluated_at,
    title: `Plan evaluated · ${plan.plan_id} v${plan.plan_version}`,
    detail: `${plan.feasibility_status} · ${plan.evaluation.validation_source === "REAL_P2_VALIDATED" ? "P2 evaluator result" : "test double result; not P2 proof"} · snapshot v${plan.snapshot_version}.`,
    refs: plan.evaluation.evidence_refs,
  }));
  const durableApprovals: RecoveryActivityItem[] = caseData.storage_mode === "DURABLE_DATABASE"
    ? caseData.approval_decisions
      .filter((decision) => decision.persistence_mode !== "IN_MEMORY_NON_DURABLE")
      .flatMap((decision) => {
        const occurredAt = decision.decided_at ?? decision.approved_at;
        if (!occurredAt) return [];
        return [{
          key: `approval-${decision.approval_id}`,
          occurredAt,
          title: `Manager decision · ${decision.decision} · ${decision.plan_id} v${decision.plan_version}`,
          detail: `${decision.actor_id} (${decision.actor_role}) · ${decision.reason}`,
          refs: [...decision.evidence_refs, ...decision.audit_refs],
        }];
      })
    : [];

  return [...triggers, ...assessmentItem, ...resolutions, ...evaluations, ...durableApprovals]
    .sort((left, right) => Date.parse(left.occurredAt) - Date.parse(right.occurredAt));
}

function RecoveryActivityTimeline({ caseData, plans }: { caseData: RecoveryCase; plans: RecoveryPlanVersion[] }) {
  const items = activityItems(caseData, plans);
  return (
    <section className="recovery-panel" aria-labelledby="recovery-activity-title">
      <div className="section-header">
        <div><p className="eyebrow">Source-backed timestamps</p><h2 id="recovery-activity-title">Recovery activity</h2></div>
        <span className="recovery-status-pill">{caseData.storage_mode.replaceAll("_", " ")}</span>
      </div>
      {items.length ? (
        <div className="recovery-timeline">
          {items.map((item) => (
            <article className="recovery-timeline-item" key={item.key}>
              <time dateTime={item.occurredAt}>{new Date(item.occurredAt).toLocaleString()}</time>
              <div>
                <strong>{item.title}</strong>
                <p>{item.detail}</p>
                {item.refs.length > 0 && <EvidenceList refs={item.refs} />}
              </div>
            </article>
          ))}
        </div>
      ) : <p className="muted text-sm">No timestamped trigger, evaluation, or durable decision records were returned.</p>}
      <p className="muted text-sm">Select a plan to load its durable manager and internal action history.</p>
    </section>
  );
}

export function RecoveryPage() {
  const { id } = useParams<{ id: string }>();
  if (id === "demo") return <SyntheticRecoveryDemo />;
  return <LiveRecoveryPage commitmentId={id ?? ""} />;
}

function LiveRecoveryPage({ commitmentId }: { commitmentId: string }) {
  const { authHeaders, actorRole } = useAuth();
  const queryClient = useQueryClient();
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [executeIdempotencyKey, setExecuteIdempotencyKey] = useState<string | null>(null);
  const [pendingDecision, setPendingDecision] = useState<{
    decision: "approve" | "reject" | "request-revision";
    plan: RecoveryPlanVersion;
    version: number;
  } | null>(null);
  const [decisionReason, setDecisionReason] = useState("");

  const caseQuery = useQuery({
    queryKey: ["recovery-case", commitmentId, authHeaders.tenantId],
    queryFn: () => getRecoveryCaseOrTrigger(commitmentId, authHeaders),
  });
  const plansQuery = useQuery({
    queryKey: ["recovery-plans", commitmentId, authHeaders.tenantId],
    queryFn: () => getRecoveryPlans(commitmentId, authHeaders),
    enabled: caseQuery.isSuccess && !!caseQuery.data && "trigger_assessment" in caseQuery.data
      && !!caseQuery.data.trigger_assessment && !!caseQuery.data.operational_snapshot,
  });
  const generateMutation = useMutation({
    mutationFn: (caseData: RecoveryCase) =>
      generateRecoveryPlans(
        commitmentId,
        {
          expected_commitment_version: caseData.commitment_version,
          assessment_id: caseData.trigger_assessment?.assessment_id,
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
  const fullCase = caseData && "trigger_assessment" in caseData ? caseData : undefined;
  const plans = plansQuery.data?.plans ?? fullCase?.plans ?? [];
  const selectedPlan = useMemo(() => plans.find((plan) => plan.plan_id === selectedPlanId), [plans, selectedPlanId]);
  const approvalsQuery = useQuery({
    queryKey: ["recovery-approvals", selectedPlanId, authHeaders.tenantId],
    queryFn: () => getApprovalHistory(selectedPlanId!, authHeaders),
    enabled: !!selectedPlanId && fullCase?.storage_mode === "DURABLE_DATABASE",
    retry: false,
  });
  const actionsQuery = useQuery({
    queryKey: ["recovery-actions", selectedPlanId, authHeaders.tenantId],
    queryFn: () => getActionHistory(selectedPlanId!, authHeaders),
    enabled: !!selectedPlanId && fullCase?.storage_mode === "DURABLE_DATABASE",
    retry: false,
  });
  const refreshWorkflow = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["recovery-case", commitmentId, authHeaders.tenantId] }),
      queryClient.invalidateQueries({ queryKey: ["recovery-plans", commitmentId, authHeaders.tenantId] }),
      queryClient.invalidateQueries({ queryKey: ["recovery-approvals", selectedPlanId, authHeaders.tenantId] }),
      queryClient.invalidateQueries({ queryKey: ["recovery-actions", selectedPlanId, authHeaders.tenantId] }),
    ]);
  };
  const decisionMutation = useMutation({
    mutationFn: ({ plan, decision, reason, version }: { plan: RecoveryPlanVersion; decision: "approve" | "reject" | "request-revision"; reason: string; version: number }) =>
      decideRecoveryPlan(plan, decision, reason, version, authHeaders),
    onSuccess: refreshWorkflow,
  });
  const executeMutation = useMutation({
    mutationFn: ({ plan, version, idempotencyKey }: { plan: RecoveryPlanVersion; version: number; idempotencyKey?: string }) =>
      executeRecoveryTask(plan, version, authHeaders, idempotencyKey),
    onSuccess: async () => {
      setExecuteIdempotencyKey(null);
      await refreshWorkflow();
    },
  });
  const handoffMutation = useMutation({
    mutationFn: ({ plan, version }: { plan: RecoveryPlanVersion; version: number }) =>
      requestRecoveryCommunication(plan, version, authHeaders),
    onSuccess: refreshWorkflow,
  });

  useEffect(() => {
    if (selectedPlanId && !plans.some((plan) => plan.plan_id === selectedPlanId)) setSelectedPlanId(null);
    setExecuteIdempotencyKey(null);
  }, [plans, selectedPlanId]);

  if (caseQuery.isLoading) {
    return <section className="recovery-loading" role="status">Loading recovery case…</section>;
  }
  if (caseQuery.isError) return <ErrorState error={caseQuery.error} onRetry={() => { void caseQuery.refetch(); }} />;
  if (!caseData) return <section className="empty-state-card"><h2>Recovery case not found</h2></section>;
  if ("evaluation_readiness" in caseData) {
    return (
      <section className="recovery-panel" role="status">
        <h2>Recovery evaluation inputs are pending</h2>
        <p>Case {caseData.case_id} · Commitment {caseData.commitment_id} · version {caseData.commitment_version}</p>
        <p>Missing: {caseData.missing_evaluation_inputs.join(", ") || "current evaluation inputs"}.</p>
        <p>Risk event: {caseData.trigger_events.map((event) => event.event_id).join(", ") || "none recorded"}</p>
        <p>Assessment: {caseData.trigger_events.map((event) => event.assessment_id).join(", ") || "not verified"}</p>
        <p>Plans and consequential actions remain unavailable until trusted inputs are present.</p>
        <button className="btn btn-outline btn-sm" type="button" onClick={() => { void caseQuery.refetch(); }}>Retry loading case</button>
      </section>
    );
  }
  if (!caseData.trigger_assessment || !caseData.operational_snapshot) {
    return (
      <section className="recovery-panel" role="status">
        <h2>Recovery evaluation inputs are pending</h2>
        <p className="muted">This case has no complete assessment and operational snapshot, so P3 cannot compare or generate plans.</p>
        <p>Case status: {caseData.status.replaceAll("_", " ")} · missing: {[!caseData.trigger_assessment && "P2 assessment", !caseData.operational_snapshot && "current operational snapshot"].filter(Boolean).join(" and ")}.</p>
        <button className="btn btn-outline btn-sm" type="button" onClick={() => { void caseQuery.refetch(); }}>Retry loading case</button>
      </section>
    );
  }
  if (plansQuery.isError) return <ErrorState error={plansQuery.error} onRetry={() => { void plansQuery.refetch(); }} />;
  if (plansQuery.isLoading) return <section className="recovery-loading" role="status">Loading recovery options…</section>;

  const assessment = caseData.trigger_assessment;
  const snapshot = caseData.operational_snapshot;
  const deadline = caseData.commitment.terms.deadline;
  const synthetic = caseData.storage_mode === "IN_MEMORY_SYNTHETIC";
  const feasibleOptions = plans.filter((plan) => plan.feasibility_status === "FEASIBLE" || plan.feasibility_status === "CONDITIONAL");

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

      {synthetic && (
        <section className="recovery-demo-notice" role="note">
          <strong>Synthetic in-memory inputs.</strong>
          <span>Assessment and decision seed records on this case are not authoritative P2 evidence or durable audit history. The view suppresses seeded approval, customer-response, and fulfilment references.</span>
        </section>
      )}
      {caseData.status === "NEEDS_REPLAN" && <div className="recovery-execution-gate"><strong>This case needs a new plan.</strong><span>Existing plans and approvals must not be treated as current.</span></div>}

      <section className="recovery-incident-grid">
        <article className="recovery-panel">
          <div className="section-header"><h2>Incident</h2><span className={`recovery-status-pill status-${assessment.status.toLowerCase()}`}>{synthetic ? `SAMPLE ${assessment.status}` : assessment.status}</span></div>
          <p className="muted">{synthetic ? "Synthetic assessment reference; not an authoritative P2 result." : "Assessment returned for the current recovery case."}</p>
          <dl className="recovery-facts">
            <div><dt>Assessment reference</dt><dd>{assessment.assessment_id} · commitment v{assessment.commitment_version} · {new Date(assessment.assessed_at).toLocaleString()}</dd></div>
            <div><dt>Risk trigger</dt><dd>{caseData.trigger_events?.map((event) => event.event_id).join(", ") || "No trigger event reference returned"}</dd></div>
            <div><dt>Operational snapshot</dt><dd>{snapshot.snapshot_id} · v{snapshot.snapshot_version} · {snapshot.source} · captured {new Date(snapshot.captured_at).toLocaleString()}</dd></div>
            <div><dt>Evidence</dt><dd><EvidenceList refs={assessment.evidence_refs} /></dd></div>
            <div><dt>Affected commitments</dt><dd>{assessment.affected_commitment_ids.length ? assessment.affected_commitment_ids.join(", ") : "None reported"}</dd></div>
          </dl>
          <ul className="recovery-constraint-list">
            {assessment.constraints.map((constraint) => (
              <li key={`${constraint.code}-${constraint.resource_id}`}>
                {constraint.code} · {constraint.resource_id} · shortage {constraint.shortage ?? "unknown"} {constraint.unit ?? ""}
              </li>
            ))}
          </ul>
          {assessment.assumptions.length > 0 && <p className="muted text-sm">Assessment assumptions: {assessment.assumptions.join("; ")}</p>}
        </article>
        <article className="recovery-panel">
          <div className="section-header"><div><h2>Commitment context</h2><p className="muted text-sm">{caseData.commitment.risk_state} · {caseData.commitment.agreement_state} · {caseData.commitment.fulfilment_state}</p></div><span className="status-pill">v{caseData.commitment.commitment_version}</span></div>
          <dl className="recovery-facts">
            <div><dt>Customer</dt><dd>{caseData.commitment.customer_id}</dd></div>
            <div><dt>Order</dt><dd>{caseData.commitment.order_id}</dd></div>
            <div><dt>Terms</dt><dd>{caseData.commitment.terms.quantity} {caseData.commitment.terms.unit} {caseData.commitment.terms.sku}</dd></div>
            <div><dt>Deadline</dt><dd>{deadline ? new Date(deadline).toLocaleString() : "Not provided"}</dd></div>
            <div><dt>Agreement state</dt><dd>{caseData.commitment.agreement_state} · confirmation is separate from fulfilment</dd></div>
            <div><dt>Customer response refs</dt><dd><EvidenceList refs={synthetic ? [] : caseData.customer_confirmation_evidence_refs} /></dd></div>
            <div><dt>Fulfilment refs</dt><dd><EvidenceList refs={synthetic ? [] : caseData.fulfilment_evidence_refs} /></dd></div>
          </dl>
        </article>
      </section>

      <section className="recovery-panel">
        <div className="section-header">
          <div><p className="eyebrow">Preference-based comparison</p><h2>Recovery options</h2></div>
          {!plans.length && (caseData.status === "OPEN" || caseData.status === "NEEDS_REPLAN") && (
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
          Policy weights: cost {caseData.preferences.cost_weight}, delay {caseData.preferences.delay_weight}, affected commitments {caseData.preferences.affected_commitments_weight}, operational disruption {caseData.preferences.operational_disruption_weight}, supplier uncertainty {caseData.preferences.supplier_uncertainty_weight}, customer confirmation {caseData.preferences.customer_confirmation_weight}. Lower score ranks first; any recommendation is conditional on these visible preferences.
        </p>
        {generateMutation.isError && <p className="recovery-inline-error">{errorMessage(generateMutation.error)}</p>}
        {!plans.length && caseData.status === "NO_SAFE_PLAN" && <div className="recovery-execution-gate"><strong>No safe plan is available.</strong><span>Escalate for human review; do not invent an action from missing or infeasible inputs.</span></div>}
        {!plans.length && caseData.status !== "NO_SAFE_PLAN" && <div className="empty-state-card"><h3>{caseData.status === "NEEDS_REPLAN" ? "A replacement plan is needed" : "No generated options yet"}</h3><p className="muted">Generate a review-only comparison from the current commitment and assessment snapshot.</p></div>}
        {!!plans.length && !feasibleOptions.length && <div className="recovery-execution-gate"><strong>No feasible or conditional option is available.</strong><span>Infeasible and unknown plans remain visible with their explanation and cannot be selected.</span></div>}
        {!!plans.length && (
          <div className="recovery-options-grid">
            {plans.map((plan) => (
              <PlanCard
                key={plan.plan_id}
                plan={plan}
                selected={selectedPlanId === plan.plan_id}
                onSelect={() => setSelectedPlanId(plan.plan_id)}
                currentSnapshotVersion={snapshot.snapshot_version}
                currentCommitmentVersion={caseData.commitment_version}
                showWorkflowStatus={!synthetic}
              />
            ))}
          </div>
        )}
      </section>

      {selectedPlan && <PlanDetail
        plan={selectedPlan}
        stale={selectedPlan.snapshot_version !== snapshot.snapshot_version || (selectedPlan.core_commitment_version ?? selectedPlan.evaluation.commitment_version) !== caseData.commitment_version}
      />}
      {selectedPlan && !synthetic && <section className="recovery-panel" aria-label="Manager decisions and internal action">
        <h2>Manager decision and internal task</h2>
        <p className="muted text-sm">Plan {selectedPlan.plan_id} v{selectedPlan.plan_version} · assessment {selectedPlan.based_on_assessment_id} · snapshot {selectedPlan.snapshot_id ?? "not recorded"} v{selectedPlan.snapshot_version} · Core v{selectedPlan.core_commitment_version ?? "not recorded"}</p>
        <p>Only a verified Manager can decide or create the synthetic internal review task. Approval does not change customer terms.</p>
        {(approvalsQuery.isError || actionsQuery.isError) && <p className="recovery-inline-error" role="alert">{errorMessage(approvalsQuery.error ?? actionsQuery.error)} <button type="button" className="btn btn-outline btn-sm" onClick={() => { void approvalsQuery.refetch(); void actionsQuery.refetch(); }}>Retry history</button></p>}
        <div className="recovery-option-meta">
          {(["approve", "reject", "request-revision"] as const).map((decision) => (
            <button
              key={decision}
              type="button"
              className="btn btn-outline btn-sm"
              disabled={
                actorRole !== "MANAGER" ||
                decisionMutation.isPending ||
                executeMutation.isPending ||
                selectedPlan.feasibility_status === "INFEASIBLE" ||
                selectedPlan.feasibility_status === "UNKNOWN" ||
                selectedPlan.snapshot_version !== snapshot.snapshot_version ||
                (selectedPlan.core_commitment_version ?? selectedPlan.evaluation.commitment_version) !== caseData.commitment_version
              }
              onClick={() => {
                setDecisionReason("");
                setPendingDecision({ decision, plan: selectedPlan, version: caseData.commitment_version });
              }}
            >
              {decision === "request-revision" ? "Request revision" : decision === "approve" ? "Manager approve" : "Reject"}
            </button>
          ))}
        </div>
        {decisionMutation.isError && (
          <p className="recovery-inline-error" role="alert">
            {errorMessage(decisionMutation.error)}{" "}
            <button type="button" className="btn btn-outline btn-sm" onClick={() => decisionMutation.reset()}>
              Dismiss
            </button>
          </p>
        )}
        <ManagerReviewPanel decisions={approvalsQuery.data ?? []} actorRole={actorRole} />
        <p>Verified internal review task: {actionsQuery.data?.find((action) => action.status === "SUCCEEDED")?.task_id ?? "none"}</p>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={
            actorRole !== "MANAGER" ||
            executeMutation.isPending ||
            decisionMutation.isPending ||
            approvalsQuery.data?.at(-1)?.decision !== "APPROVED" ||
            (approvalsQuery.data?.at(-1)?.expires_at ? Date.parse(approvalsQuery.data.at(-1)!.expires_at!) <= Date.now() : true) ||
            selectedPlan.snapshot_version !== snapshot.snapshot_version ||
            (selectedPlan.core_commitment_version ?? selectedPlan.evaluation.commitment_version) !== caseData.commitment_version
          }
          onClick={() => {
            if (window.confirm("Create a synthetic internal review task for this approved plan? Customer terms will not change.")) {
              const key = executeIdempotencyKey ?? crypto.randomUUID();
              if (!executeIdempotencyKey) setExecuteIdempotencyKey(key);
              executeMutation.mutate({ plan: selectedPlan, version: caseData.commitment_version, idempotencyKey: key });
            }
          }}
        >
          {executeMutation.isPending ? "Creating and verifying task…" : "Create internal review task"}
        </button>
        {executeMutation.isError && (
          <p className="recovery-inline-error" role="alert">
            {errorMessage(executeMutation.error)}{" "}
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={() => {
                const key = executeIdempotencyKey ?? crypto.randomUUID();
                if (!executeIdempotencyKey) setExecuteIdempotencyKey(key);
                executeMutation.mutate({ plan: selectedPlan, version: caseData.commitment_version, idempotencyKey: key });
              }}
            >
              Retry task
            </button>{" "}
            <button type="button" className="btn btn-outline btn-sm" onClick={() => executeMutation.reset()}>
              Dismiss
            </button>
          </p>
        )}
        {selectedPlan.option_id === "revised_schedule" && <div className="recovery-option-meta">
          <button type="button" className="btn btn-outline btn-sm"
            disabled={actorRole !== "MANAGER" || handoffMutation.isPending || approvalsQuery.data?.at(-1)?.decision !== "APPROVED" ||
              selectedPlan.snapshot_version !== snapshot.snapshot_version ||
              !((selectedPlan.core_commitment_version ?? selectedPlan.evaluation.commitment_version) === caseData.commitment_version ||
                (caseData.commitment.agreement_state === "OFFERED" &&
                  (selectedPlan.core_commitment_version ?? selectedPlan.evaluation.commitment_version) + 1 === caseData.commitment_version))}
            onClick={() => {
              if (window.confirm("Offer the approved revised terms to the communication workflow? Customer acceptance remains pending."))
                handoffMutation.mutate({ plan: selectedPlan, version: caseData.commitment_version });
            }}>{handoffMutation.isPending ? "Requesting communication…" : caseData.commitment.agreement_state === "OFFERED" ? "Resume communication request" : "Request customer communication"}</button>
          {handoffMutation.isSuccess && <p role="status">Proposal {handoffMutation.data.proposal_id} v{handoffMutation.data.proposal_version} offered. Communication request {handoffMutation.data.source_event_id}: {handoffMutation.data.p4_request_status}. {handoffMutation.data.blocking_reasons.join(", ") || "Awaiting verified customer response"}. <Link to="/communications">View Communication Center</Link>.</p>}
          {handoffMutation.isError && <p className="recovery-inline-error" role="alert">{errorMessage(handoffMutation.error)} <button type="button" className="btn btn-outline btn-sm" onClick={() => handoffMutation.reset()}>Dismiss</button></p>}
        </div>}
        <h3>Action history</h3>
        {(actionsQuery.data ?? []).map((action: DurableActionView) => <p key={action.execution_id}>{action.status} · attempts {action.attempts} · task {action.task_id ?? "none"} · receipt {action.receipt_ref ?? "none"}{action.last_error ? ` · ${action.last_error}` : ""}</p>)}
      </section>}
      {!selectedPlan && <ManagerReviewPanel decisions={[]} actorRole={actorRole} />}
      <RecoveryActivityTimeline caseData={caseData} plans={plans} />
      <section className="recovery-audit-note">
        <strong>Evidence and assumptions stay visible.</strong>
        <span>Approval decisions are version- and snapshot-scoped. The internal task does not communicate externally or mutate the authoritative Core commitment.</span>
      </section>
      {pendingDecision && (
        <ConfirmationDialog
          open={!!pendingDecision}
          title={
            pendingDecision.decision === "approve"
              ? "Manager Approval"
              : pendingDecision.decision === "reject"
              ? "Reject Recovery Plan"
              : "Request Plan Revision"
          }
          description={`Record manager decision for plan ${pendingDecision.plan.plan_id} v${pendingDecision.plan.plan_version}. Approval does not change customer terms.`}
          confirmLabel={
            pendingDecision.decision === "approve"
              ? "Confirm Approval"
              : pendingDecision.decision === "reject"
              ? "Confirm Rejection"
              : "Submit Revision Request"
          }
          cancelLabel="Cancel"
          confirmDisabled={decisionReason.trim().length < 5}
          pending={decisionMutation.isPending}
          onConfirm={() => {
            if (decisionReason.trim().length < 5) return;
            decisionMutation.mutate({
              plan: pendingDecision.plan,
              decision: pendingDecision.decision,
              reason: decisionReason.trim(),
              version: pendingDecision.version,
            });
          }}
          onOpenChange={(open) => {
            if (!open) {
              setPendingDecision(null);
              setDecisionReason("");
            }
          }}
        >
          <div style={{ marginTop: "1rem" }}>
            <label htmlFor="decision-reason-input" style={{ display: "block", marginBottom: "0.4rem", fontWeight: 600 }}>
              Decision reason <span style={{ fontWeight: "normal", color: "var(--orbyte-text-muted)" }}>(required, min 5 characters)</span>
            </label>
            <textarea
              id="decision-reason-input"
              rows={3}
              style={{
                width: "100%",
                padding: "0.5rem",
                borderRadius: "var(--orbyte-radius)",
                border: "1px solid var(--orbyte-border)",
                background: "var(--orbyte-surface)",
                color: "var(--orbyte-text)",
                boxSizing: "border-box",
              }}
              placeholder={`Provide rationale for ${pendingDecision.decision.replaceAll("-", " ")} (min. 5 characters)...`}
              value={decisionReason}
              onChange={(e) => setDecisionReason(e.target.value)}
              aria-describedby="decision-reason-hint"
              autoFocus
            />
            <p id="decision-reason-hint" className="text-sm muted" style={{ marginTop: "0.25rem", fontSize: "0.85rem" }}>
              {decisionReason.trim().length < 5
                ? `${5 - decisionReason.trim().length} more character(s) required to enable confirmation`
                : "✓ Reason meets requirement"}
            </p>
          </div>
        </ConfirmationDialog>
      )}
    </div>
  );
}
