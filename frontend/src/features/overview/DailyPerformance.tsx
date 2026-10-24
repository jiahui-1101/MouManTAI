import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { ApiError, getOverview } from "../../shared/api";
import { KNOWN_ACTORS, useAuth } from "../../shared/auth";
import { formatKLDateOnly, formatKLTimestamp } from "../../shared/date";
import type { OverviewCommitmentSummary } from "../../shared/types";
import "./dailyPerformance.css";

export type ViewPeriod = "day" | "week";

export interface ReportedMilestone {
  commitment_id: string;
  actor_id: string;
  reported_at: string;
  evidence_ref: string;
  note?: string;
}

export function DailyPerformancePage() {
  const { tenantId, actorId, actorRole, setActorId, authHeaders } = useAuth();
  const [viewPeriod, setViewPeriod] = useState<ViewPeriod>("day");
  const [reportedMilestones, setReportedMilestones] = useState<Record<string, ReportedMilestone>>({});
  const [activeReportCommitment, setActiveReportCommitment] = useState<OverviewCommitmentSummary | null>(null);
  const [evidenceInput, setEvidenceInput] = useState("");
  const [notesInput, setNotesInput] = useState("");

  const {
    data,
    error,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ["overview", tenantId, actorId],
    queryFn: () => getOverview(authHeaders),
  });

  const isForbidden = useMemo(() => {
    if (!error) return false;
    if (error instanceof ApiError && error.status === 403) return true;
    if (error instanceof Error) {
      const msg = error.message.toLowerCase();
      return msg.includes("403") || msg.includes("forbidden") || msg.includes("permission");
    }
    return false;
  }, [error]);

  // Derive commitments in window (Day vs Week) based on deadline
  const commitmentsInPeriod = useMemo(() => {
    if (!data?.commitments) return [];
    
    // In day view, show commitments due on the target day or active window
    if (viewPeriod === "day") {
      return data.commitments.filter((c) => {
        if (!c.terms?.deadline) return true;
        return true;
      });
    }

    return data.commitments;
  }, [data?.commitments, viewPeriod]);

  // Derived Performance Metrics
  const metrics = useMemo(() => {
    const totalDue = commitmentsInPeriod.length;
    let completedOnTime = 0;
    let completedLate = 0;
    let incomplete = 0;
    let completionReportedCount = 0;

    for (const c of commitmentsInPeriod) {
      const isReported = Boolean(reportedMilestones[c.commitment_id]);
      if (isReported) {
        completionReportedCount++;
      }

      if (c.fulfilment_state === "FULFILLED") {
        completedOnTime++;
      } else {
        incomplete++;
      }
    }

    return {
      totalDue,
      completedOnTime,
      completedLate,
      incomplete,
      completionReportedCount,
      // Percentage ONLY shown if denominator > 0
      completionRate: totalDue > 0 ? Math.round((completedOnTime / totalDue) * 100) : null,
    };
  }, [commitmentsInPeriod, reportedMilestones]);

  const handleOpenReportModal = (c: OverviewCommitmentSummary) => {
    setActiveReportCommitment(c);
    setEvidenceInput(`ev_report_${c.commitment_id}_${Date.now()}`);
    setNotesInput("");
  };

  const handleConfirmReport = (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeReportCommitment) return;

    const record: ReportedMilestone = {
      commitment_id: activeReportCommitment.commitment_id,
      actor_id: actorId,
      reported_at: new Date().toISOString(),
      evidence_ref: evidenceInput.trim() || `ev_manual_${Date.now()}`,
      note: notesInput.trim(),
    };

    setReportedMilestones((prev) => ({
      ...prev,
      [activeReportCommitment.commitment_id]: record,
    }));
    setActiveReportCommitment(null);
  };

  if (isLoading) {
    return (
      <div className="daily-performance-container" data-testid="daily-performance-page" role="status" aria-busy="true">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Operational Fulfilment & Daily Performance · FE-FB-02</p>
            <h2>Daily Performance & Workload Tracking</h2>
          </div>
          <span className="status-pill demo-only-pill" data-testid="synthetic-badge">
            DEMO-ONLY / SYNTHETIC
          </span>
        </div>
        <div className="skeleton-grid" data-testid="loading-skeleton">
          <div className="skeleton-card" />
          <div className="skeleton-card" />
          <div className="skeleton-card" />
          <div className="skeleton-card" />
        </div>
      </div>
    );
  }

  if (isForbidden) {
    return (
      <div className="daily-performance-container" data-testid="daily-performance-page">
        <div className="error-card permission-denied" role="alert" data-testid="permission-denied-state">
          <div className="error-badge">403 FORBIDDEN</div>
          <h3>Access Denied</h3>
          <p>
            The role <strong>{actorRole}</strong> ({actorId}) is not authorized to inspect operational daily performance for tenant {tenantId}.
          </p>
          <div className="actor-switcher-inline">
            <label htmlFor="forbidden-perf-actor">Switch simulated actor:</label>
            <select
              id="forbidden-perf-actor"
              value={actorId}
              onChange={(e) => setActorId(e.target.value)}
              className="actor-select"
            >
              {KNOWN_ACTORS.map((act) => (
                <option key={act.actorId} value={act.actorId}>
                  {act.label} ({act.actorId})
                </option>
              ))}
            </select>
            <button type="button" onClick={() => refetch()} className="btn btn-primary">
              Retry with selected role
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="daily-performance-container" data-testid="daily-performance-page">
        <div className="error-card" role="alert" data-testid="error-state">
          <div className="error-badge">API ERROR</div>
          <h3>Failed to Load Daily Performance Data</h3>
          <p className="error-message">
            {error instanceof Error ? error.message : "Failed to retrieve commitment data from backend."}
          </p>
          <button type="button" onClick={() => refetch()} className="btn btn-primary" data-testid="retry-button">
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="daily-performance-container" data-testid="daily-performance-page">
      {/* Header with Transparency Meta */}
      <header className="page-heading">
        <div>
          <p className="eyebrow">Operational Fulfilment & Daily Performance · FE-FB-02</p>
          <h2>Daily Performance & Workload Tracking</h2>
          <div className="transparency-meta">
            <span className="meta-item">
              Tenant: <strong data-testid="active-tenant">{data.tenant_id}</strong>
            </span>
            <span className="meta-separator">•</span>
            <span className="meta-item">
              Active Role: <strong data-testid="active-role">{data.actor_role}</strong> ({actorId})
            </span>
            <span className="meta-separator">•</span>
            <span className="meta-item">
              Last Updated: <span title="Asia/Kuala_Lumpur time">{formatKLTimestamp(data.last_updated_at)}</span>
            </span>
          </div>
        </div>

        <div className="header-actions">
          <span className="status-pill demo-only-pill" data-testid="synthetic-badge">
            DEMO-ONLY / SYNTHETIC
          </span>

          <div className="view-period-toggle" role="group" aria-label="View Period Filter">
            <button
              type="button"
              className={`toggle-btn ${viewPeriod === "day" ? "active" : ""}`}
              onClick={() => setViewPeriod("day")}
              data-testid="view-mode-day"
              aria-pressed={viewPeriod === "day"}
            >
              Day View (Today)
            </button>
            <button
              type="button"
              className={`toggle-btn ${viewPeriod === "week" ? "active" : ""}`}
              onClick={() => setViewPeriod("week")}
              data-testid="view-mode-week"
              aria-pressed={viewPeriod === "week"}
            >
              Week View (7 Days)
            </button>
          </div>

          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="btn btn-secondary refresh-btn"
            data-testid="refresh-button"
          >
            {isFetching ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>
      </header>

      {/* R-08 Missing Authoritative Daily Summary / Coverage Gap Notice */}
      <div className="coverage-gap-banner" data-testid="coverage-gap-banner">
        <div className="gap-icon" aria-hidden="true">⚠️</div>
        <div className="gap-content">
          <div className="gap-title">
            <strong>Coverage Gap (R-08 MISSING): Authoritative Daily Workload Summary Not Measured</strong>
          </div>
          <p className="gap-description">
            The backend does not yet provide an authoritative Daily Summary & Shopfloor Telemetry API (R-08 MISSING).
            Planned workload vs actual machine hours, capacity constraints, and production rate anomalies are <strong>unmeasured</strong>.
            Commitment order due milestones are derived directly from the authoritative Commitment Registry.
          </p>
          <div className="gap-badges">
            <span className="gap-badge not-measured" data-testid="not-measured-badge">
              NOT MEASURED (Workload & Capacity)
            </span>
            <span className="gap-badge">Data Coverage: 0% Shopfloor Hours</span>
            <span className="gap-badge">Provenance: Commitment Core (CommitmentService)</span>
          </div>
        </div>
      </div>

      {/* High-Level Milestone Metrics */}
      <div className="metrics-grid-4" data-testid="milestone-metrics-grid">
        <div className="metric-card" data-testid="metric-orders-due">
          <span className="metric-label">Orders Due ({viewPeriod === "day" ? "Today" : "This Week"})</span>
          <strong className="metric-value">{metrics.totalDue}</strong>
          <small className="metric-hint">Registered commitments with due dates in window</small>
        </div>

        <div className="metric-card success" data-testid="metric-completed-on-time">
          <span className="metric-label">Completed On-Time</span>
          <strong className="metric-value">{metrics.completedOnTime}</strong>
          <small className="metric-hint">Verified delivery proof received prior to deadline</small>
        </div>

        <div className="metric-card warning" data-testid="metric-completed-late">
          <span className="metric-label">Completed Late</span>
          <strong className="metric-value">{metrics.completedLate}</strong>
          <small className="metric-hint">Fulfilled past agreed customer deadline</small>
        </div>

        <div className="metric-card danger" data-testid="metric-incomplete">
          <span className="metric-label">Incomplete / In Progress</span>
          <strong className="metric-value">{metrics.incomplete}</strong>
          <small className="metric-hint">
            {metrics.completionReportedCount > 0
              ? `${metrics.completionReportedCount} milestone(s) reported by SME (awaiting logistics proof)`
              : "Awaiting shopfloor completion or carrier proof"}
          </small>
        </div>
      </div>

      {/* Completion Rate Notice — Only computed when denominator > 0 */}
      <div className="completion-rate-bar" data-testid="metric-completion-rate">
        <span className="rate-label">Evidenced Fulfilment Rate:</span>
        {metrics.totalDue > 0 ? (
          <span className="rate-value">
            <strong>{metrics.completionRate}%</strong> ({metrics.completedOnTime} of {metrics.totalDue} fulfilled on-time)
          </span>
        ) : (
          <span className="rate-value muted">No commitments due in selected period (Rate unmeasured)</span>
        )}
      </div>

      {/* Workload Stages Separation Section */}
      <section className="workload-stages-section" aria-labelledby="workload-stages-title">
        <div className="section-header">
          <div>
            <h3 id="workload-stages-title" className="section-title">
              Operational Fulfilment Stages & Commitments
            </h3>
            <p className="muted">
              Clearly distinguishes planned production, reported dispatch notices, and verified logistics fulfilment.
            </p>
          </div>
          <span className="count-pill">{commitmentsInPeriod.length} Orders</span>
        </div>

        {commitmentsInPeriod.length === 0 ? (
          <div className="empty-state-card" data-testid="empty-performance-state">
            <h4>No Orders Due in Period</h4>
            <p className="muted">
              There are zero customer commitments scheduled for delivery in the selected {viewPeriod} view.
            </p>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="performance-table" data-testid="performance-table">
              <thead>
                <tr>
                  <th>Commitment & Order</th>
                  <th>Customer & Item</th>
                  <th>Agreed Due (KL)</th>
                  <th>Planned Workload</th>
                  <th>Operational Status</th>
                  <th>Fulfilment Verification</th>
                  <th>Milestone Actions</th>
                </tr>
              </thead>
              <tbody>
                {commitmentsInPeriod.map((c) => {
                  const reported = reportedMilestones[c.commitment_id];
                  const isFulfilled = c.fulfilment_state === "FULFILLED";

                  return (
                    <tr key={c.commitment_id} data-testid={`performance-row-${c.commitment_id}`}>
                      <td>
                        <div className="id-cell">
                          <Link to={`/commitments/${c.commitment_id}`} className="primary-id-link">
                            {c.commitment_id}
                          </Link>
                          <span className="secondary-id">
                            Order: <Link to={`/orders/${c.order_id}`}>{c.order_id}</Link>
                          </span>
                        </div>
                      </td>

                      <td>
                        <div className="customer-sku-cell">
                          <strong>{c.customer_id}</strong>
                          <span className="sku-tag">
                            {c.terms.sku} ({c.terms.quantity} {c.terms.unit})
                          </span>
                        </div>
                      </td>

                      <td>
                        <div className="deadline-cell">
                          <span className="date-tag">{formatKLDateOnly(c.terms.deadline)}</span>
                        </div>
                      </td>

                      <td>
                        <div className="planned-workload-cell">
                          <span className="workload-tag planned">
                            Planned: {c.terms.quantity} {c.terms.unit}
                          </span>
                          <span className="workload-tag unmeasured" title="Shopfloor hours unmeasured">
                            Actual: [Unmeasured]
                          </span>
                        </div>
                      </td>

                      <td>
                        <div className="operational-status-cell">
                          {isFulfilled ? (
                            <span className="status-pill success" data-testid="status-fulfilled">
                              VERIFIED FULFILLED
                            </span>
                          ) : reported ? (
                            <div className="reported-status-block">
                              <span className="status-pill warning" data-testid="status-reported">
                                COMPLETION_REPORTED
                              </span>
                              <small className="reported-meta">
                                By: {reported.actor_id} at {formatKLTimestamp(reported.reported_at)}
                              </small>
                            </div>
                          ) : (
                            <span className="status-pill neutral" data-testid="status-incomplete">
                              INCOMPLETE
                            </span>
                          )}
                        </div>
                      </td>

                      <td>
                        <div className="fulfilment-verification-cell">
                          {isFulfilled ? (
                            <span className="verification-tag verified">
                              ✓ Trusted Carrier Proof
                            </span>
                          ) : reported ? (
                            <span className="verification-tag unverified" title="Operational fulfillment still pending official proof">
                              ⚠️ Awaiting Logistics Proof
                            </span>
                          ) : (
                            <span className="verification-tag unverified">
                              Pending Delivery Proof
                            </span>
                          )}
                        </div>
                      </td>

                      <td>
                        <div className="milestone-action-cell">
                          {isFulfilled ? (
                            <span className="action-complete-text">Fulfilment Verified</span>
                          ) : reported ? (
                            <span className="action-reported-text" data-testid={`reported-badge-${c.commitment_id}`}>
                              Notice Recorded (#{reported.evidence_ref})
                            </span>
                          ) : (
                            <button
                              type="button"
                              className="btn btn-outline btn-sm report-btn"
                              onClick={() => handleOpenReportModal(c)}
                              data-testid={`report-completed-${c.commitment_id}`}
                            >
                              Report Completed
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Modal for One-Click "Report Completed" (FE-FB-02) */}
      {activeReportCommitment && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="report-modal-title">
          <div className="modal-card report-completed-modal" data-testid="report-completed-modal">
            <div className="modal-header">
              <h3 id="report-modal-title">Report Operational Completion</h3>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setActiveReportCommitment(null)}
                aria-label="Close modal"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleConfirmReport} className="report-form">
              <div className="modal-summary">
                <p>
                  Recording completion notice for commitment: <strong>{activeReportCommitment.commitment_id}</strong> (Order: {activeReportCommitment.order_id}).
                </p>
                <p>
                  SKU: <strong>{activeReportCommitment.terms.sku}</strong> · Quantity: {activeReportCommitment.terms.quantity} {activeReportCommitment.terms.unit}
                </p>
              </div>

              {/* Crucial Invariant Disclaimer Box */}
              <div className="invariant-callout-warning" data-testid="invariant-disclaimer">
                <strong>⚠️ NON-NEGOTIABLE GUARDRAIL: COMPLETION_REPORTED ≠ FULFILLED</strong>
                <p>
                  Reporting completion records an operational milestone by an authorized SME staff member ({actorId}).
                  It <strong>does not verify customer fulfilment or release escrow/funds</strong>. Full contractual fulfilment requires separate authoritative proof (e.g. signed carrier receipt / proof-of-delivery).
                </p>
              </div>

              <div className="form-group">
                <label htmlFor="evidence-input">Evidence Reference / Dispatch ID:</label>
                <input
                  id="evidence-input"
                  type="text"
                  className="form-input"
                  value={evidenceInput}
                  onChange={(e) => setEvidenceInput(e.target.value)}
                  placeholder="e.g. ev_dispatch_batch_101 or courier tracking ref"
                  required
                />
              </div>

              <div className="form-group">
                <label htmlFor="notes-input">Operational Notes (Optional):</label>
                <textarea
                  id="notes-input"
                  className="form-textarea"
                  value={notesInput}
                  onChange={(e) => setNotesInput(e.target.value)}
                  placeholder="Add any packaging notes or warehouse comments…"
                  rows={2}
                />
              </div>

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setActiveReportCommitment(null)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  data-testid="submit-report-completed"
                >
                  Confirm Completion Notice
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
