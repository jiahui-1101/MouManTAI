import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { ApiError, getAudit, getCommitments, getCommitmentTimeline } from "../../shared/api";
import { KNOWN_ACTORS, useAuth } from "../../shared/auth";
import { formatKLTimestamp } from "../../shared/date";
import { StatusBadge } from "../../shared/StatusBadge";
import type { AuditEvent, Commitment, SourceFeature, TimelineEntry } from "../../shared/types";

export interface NormalizedTimelineEntry extends TimelineEntry {
  raw_audit_id?: string;
}

function auditToTimelineEntry(audit: AuditEvent): NormalizedTimelineEntry {
  const version =
    typeof audit.new_state?.commitment_version === "number"
      ? (audit.new_state.commitment_version as number)
      : null;

  return {
    entry_id: `entry_audit_${audit.audit_id}`,
    raw_audit_id: audit.audit_id,
    occurred_at: audit.occurred_at,
    actor_id: audit.actor_id,
    actor_role: audit.actor_role,
    source_feature: "CORE" as SourceFeature,
    event_type: audit.event_type,
    action: audit.reason || audit.event_type,
    previous_state: audit.previous_state,
    new_state: audit.new_state,
    commitment_version: version,
    correlation_id: audit.correlation_id,
    causation_id: audit.causation_id,
    approval_reason: audit.reason,
    evidence_refs: audit.evidence_refs || [],
  };
}

export function formatFeatureBadge(feature: SourceFeature | string): { label: string; className: string } {
  switch (feature) {
    case "F1_CONTEXT":
      return { label: "F1 Context", className: "feature-badge feature-f1" };
    case "F2_FEASIBILITY":
      return { label: "F2 Feasibility", className: "feature-badge feature-f2" };
    case "F3_RECOVERY":
      return { label: "F3 Recovery", className: "feature-badge feature-f3" };
    case "F4_COMMUNICATION":
      return { label: "F4 Communication", className: "feature-badge feature-f4" };
    case "CORE":
    default:
      return { label: "Core", className: "feature-badge feature-core" };
  }
}

export function formatRoleBadgeClass(role: string): string {
  const normalized = role?.toUpperCase();
  if (normalized === "OWNER") return "role-badge role-owner";
  if (normalized === "MANAGER") return "role-badge role-manager";
  if (normalized === "STAFF") return "role-badge role-staff";
  return "role-badge role-system";
}

export function hasRedactedData(data: unknown): boolean {
  if (!data) return false;
  if (typeof data === "string") {
    return data.includes("REDACTED") || data.includes("[REDACTED_FOR_STAFF]");
  }
  if (typeof data === "object") {
    return Object.values(data as Record<string, unknown>).some((val) => hasRedactedData(val));
  }
  return false;
}

export function extractStateTransitions(
  previousState: Record<string, unknown> | null,
  newState: Record<string, unknown>,
): Array<{ from: string; to: string; dimension?: string }> {
  const transitions: Array<{ from: string; to: string; dimension?: string }> = [];
  if (!previousState || !newState) {
    return transitions;
  }

  // Check 5 dimensions
  const dims = [
    { key: "agreement_state", label: "agreement" },
    { key: "feasibility_state", label: "feasibility" },
    { key: "risk_state", label: "risk" },
    { key: "recovery_state", label: "recovery" },
    { key: "fulfilment_state", label: "fulfilment" },
  ];

  for (const { key, label } of dims) {
    const prev = previousState[key];
    const next = newState[key];
    if (prev && next && prev !== next) {
      transitions.push({ from: String(prev), to: String(next), dimension: label });
    }
  }

  // Cross-dimensional or direct state transitions (e.g. CONFIRMED -> AT_RISK)
  if (
    previousState.agreement_state === "CONFIRMED" &&
    newState.risk_state === "AT_RISK" &&
    !transitions.some((t) => t.from === "CONFIRMED" && t.to === "AT_RISK")
  ) {
    transitions.push({ from: "CONFIRMED", to: "AT_RISK", dimension: "risk" });
  }

  if (
    previousState.state &&
    newState.state &&
    previousState.state !== newState.state &&
    !transitions.some((t) => t.from === previousState.state && t.to === newState.state)
  ) {
    transitions.push({ from: String(previousState.state), to: String(newState.state) });
  }

  if (
    previousState.status &&
    newState.status &&
    previousState.status !== newState.status &&
    !transitions.some((t) => t.from === previousState.status && t.to === newState.status)
  ) {
    transitions.push({ from: String(previousState.status), to: String(newState.status) });
  }

  return transitions;
}

export function isHumanGovernanceRecord(entry: TimelineEntry): boolean {
  const role = entry.actor_role?.toUpperCase();
  const isHuman = role === "OWNER" || role === "MANAGER";
  const hasReason = Boolean(entry.approval_reason && entry.approval_reason.trim().length > 0);
  const actionLower = (entry.action || "").toLowerCase();
  const isApprovalAction =
    actionLower.includes("approval") ||
    actionLower.includes("approved") ||
    actionLower.includes("reject") ||
    actionLower.includes("confirm") ||
    actionLower.includes("proposal") ||
    actionLower.includes("fulfilment");

  return (isHuman && (hasReason || isApprovalAction)) || hasReason;
}

export function ActivityPage() {
  const { tenantId, actorId, actorRole, setActorId, authHeaders } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const commitmentIdParam = searchParams.get("commitment_id") ?? "";
  const correlationIdParam = searchParams.get("correlation_id") ?? "";

  const [selectedCommitmentId, setSelectedCommitmentId] = useState<string>(commitmentIdParam);
  const [selectedCorrelationId, setSelectedCorrelationId] = useState<string>(correlationIdParam);
  const [viewMode, setViewMode] = useState<"timeline" | "grouped">("timeline");

  // Keep state in sync with URL
  const handleCommitmentChange = (newCommitmentId: string) => {
    setSelectedCommitmentId(newCommitmentId);
    const nextParams = new URLSearchParams(searchParams);
    if (newCommitmentId) {
      nextParams.set("commitment_id", newCommitmentId);
    } else {
      nextParams.delete("commitment_id");
    }
    setSearchParams(nextParams);
  };

  const handleCorrelationFilter = (newCorrelationId: string) => {
    setSelectedCorrelationId(newCorrelationId);
    const nextParams = new URLSearchParams(searchParams);
    if (newCorrelationId) {
      nextParams.set("correlation_id", newCorrelationId);
    } else {
      nextParams.delete("correlation_id");
    }
    setSearchParams(nextParams);
  };

  // Fetch commitment list to populate dropdown selector
  const commitmentsQuery = useQuery({
    queryKey: ["commitments", tenantId, actorId],
    queryFn: () => getCommitments(authHeaders),
    staleTime: 30_000,
  });

  // Effective commitment ID to fetch: user selection or URL param
  const activeCommitmentId = selectedCommitmentId || commitmentIdParam;

  // Timeline query for specific commitment
  const timelineQuery = useQuery({
    queryKey: ["commitment-timeline", tenantId, actorId, activeCommitmentId],
    queryFn: () => getCommitmentTimeline(activeCommitmentId, authHeaders),
    enabled: Boolean(activeCommitmentId),
  });

  // Audit query when "All Tenant Audit" is selected
  const auditQuery = useQuery({
    queryKey: ["tenant-audit", tenantId, actorId],
    queryFn: () => getAudit(authHeaders),
    enabled: !activeCommitmentId,
  });

  // Active query depends on whether a commitment is selected
  const activeQuery = activeCommitmentId ? timelineQuery : auditQuery;
  const { data, error, isLoading, isFetching, refetch } = activeQuery;

  const isForbidden = useMemo(() => {
    if (!error) return false;
    if (error instanceof ApiError && error.status === 403) return true;
    if (error instanceof Error && error.message.includes("403")) return true;
    return false;
  }, [error]);

  // Normalize entries from either timeline or audit API
  const allEntries = useMemo<NormalizedTimelineEntry[]>(() => {
    if (!data) return [];
    if (activeCommitmentId) {
      return (data as TimelineEntry[]).map((entry) => ({ ...entry }));
    } else {
      return (data as AuditEvent[]).map(auditToTimelineEntry);
    }
  }, [data, activeCommitmentId]);

  // Apply correlation_id filter if present
  const filteredEntries = useMemo(() => {
    if (!selectedCorrelationId) return allEntries;
    return allEntries.filter(
      (entry) =>
        entry.correlation_id === selectedCorrelationId ||
        entry.causation_id === selectedCorrelationId,
    );
  }, [allEntries, selectedCorrelationId]);

  // Group entries by correlation_id for grouped correlation chain view
  const correlationGroups = useMemo(() => {
    const map = new Map<string, NormalizedTimelineEntry[]>();
    for (const entry of filteredEntries) {
      const corr = entry.correlation_id || "uncorrelated";
      if (!map.has(corr)) {
        map.set(corr, []);
      }
      map.get(corr)!.push(entry);
    }
    return Array.from(map.entries()).map(([correlation_id, entries]) => ({
      correlation_id,
      entries,
    }));
  }, [filteredEntries]);

  // Role redaction detection
  const isViewingAsStaff = actorRole?.toUpperCase() === "STAFF";
  const hasAnyRedaction = useMemo(() => {
    if (isViewingAsStaff) return true;
    return filteredEntries.some(
      (entry) =>
        hasRedactedData(entry.new_state) ||
        hasRedactedData(entry.previous_state) ||
        hasRedactedData(entry.approval_reason),
    );
  }, [filteredEntries, isViewingAsStaff]);

  return (
    <div className="activity-page" data-testid="activity-page">
      {/* Page Header & Transparency Controls */}
      <header className="page-heading">
        <div>
          <p className="eyebrow">Audit & Event Traceability · FE-03</p>
          <h2>Activity & Audit History</h2>
          <p className="muted">
            Immutable domain events, state transition diffs, human approvals, and end-to-end causal
            tracking for MouManTAI commitments.
          </p>
        </div>

        <div className="header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label="Refresh activity data"
          >
            {isFetching ? "Refreshing..." : "↻ Refresh"}
          </button>
        </div>
      </header>

      {/* Role & Transparency Notice */}
      <div className="activity-transparency-bar">
        <div className="meta-left">
          <span className="tenant-pill">Tenant: {tenantId}</span>
          <span className={`actor-pill ${formatRoleBadgeClass(actorRole)}`}>
            Role: {actorRole} ({actorId})
          </span>
          <span className="mode-pill">Mode: SYNTHETIC</span>
        </div>

        {/* Staff / Sensitive Role Redaction Banner */}
        {(isViewingAsStaff || hasAnyRedaction) && (
          <div className="redacted-banner" data-testid="redacted-indicator">
            <span className="redacted-icon" aria-hidden="true">🔒</span>
            <span className="redacted-text">
              <strong>Redacted for role (Staff):</strong> Financial margins, profit amounts, and
              private contact details are masked.
            </span>
          </div>
        )}
      </div>

      {/* Filtering & Scoping Toolbar */}
      <section className="activity-toolbar" aria-label="Activity filter toolbar">
        <div className="filter-item">
          <label htmlFor="commitment-select">Scoped Commitment:</label>
          <select
            id="commitment-select"
            className="select-control"
            value={activeCommitmentId}
            onChange={(e) => handleCommitmentChange(e.target.value)}
          >
            <option value="">— All Tenant Audit Events —</option>
            {commitmentsQuery.data?.map((c: Commitment) => (
              <option key={c.commitment_id} value={c.commitment_id}>
                {c.commitment_id} ({c.order_id} · {c.terms.sku})
              </option>
            ))}
            {activeCommitmentId &&
              !commitmentsQuery.data?.some((c) => c.commitment_id === activeCommitmentId) && (
                <option value={activeCommitmentId}>{activeCommitmentId} (Custom Filter)</option>
              )}
          </select>
        </div>

        <div className="filter-item">
          <label htmlFor="correlation-input">Filter by Correlation ID:</label>
          <div className="input-with-clear">
            <input
              id="correlation-input"
              type="text"
              className="text-input"
              placeholder="e.g. corr_demo_001"
              value={selectedCorrelationId}
              onChange={(e) => handleCorrelationFilter(e.target.value)}
            />
            {selectedCorrelationId && (
              <button
                type="button"
                className="clear-filter-btn"
                onClick={() => handleCorrelationFilter("")}
                title="Clear correlation filter"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        <div className="view-mode-toggle" role="group" aria-label="View mode">
          <button
            type="button"
            className={`btn btn-sm ${viewMode === "timeline" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setViewMode("timeline")}
          >
            Timeline View
          </button>
          <button
            type="button"
            className={`btn btn-sm ${viewMode === "grouped" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setViewMode("grouped")}
          >
            Group by Correlation ({correlationGroups.length})
          </button>
        </div>
      </section>

      {/* Active Correlation Filter Banner */}
      {selectedCorrelationId && (
        <div className="active-filter-chip">
          <span>
            Filtering causal chain: <code>{selectedCorrelationId}</code>
          </span>
          <button
            type="button"
            className="btn-link"
            onClick={() => handleCorrelationFilter("")}
          >
            Clear Filter (Show All)
          </button>
        </div>
      )}

      {/* 403 Forbidden State */}
      {isForbidden && (
        <div className="error-card permission-denied" data-testid="permission-denied-state">
          <span className="error-badge">403 FORBIDDEN</span>
          <h3>Permission Denied</h3>
          <p className="error-message">
            Your simulated actor <strong>{actorId}</strong> with role <strong>{actorRole}</strong> does
            not have authorized permissions to view this audit stream.
          </p>
          <p className="muted text-sm">
            Switch simulated actor to an authorized role (Manager or Owner) to inspect governance
            records:
          </p>
          <div className="actor-switcher-inline">
            {KNOWN_ACTORS.map((actor) => (
              <button
                key={actor.actorId}
                type="button"
                className={`btn btn-sm ${actor.actorId === actorId ? "btn-primary" : "btn-secondary"}`}
                onClick={() => {
                  setActorId(actor.actorId);
                }}
              >
                {actor.label} ({actor.role})
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Generic Error State */}
      {!isForbidden && error && (
        <div className="error-card" data-testid="error-state">
          <span className="error-badge">AUDIT_FETCH_FAILED</span>
          <h3>Failed to Load Activity</h3>
          <p className="error-message">
            {error instanceof Error ? error.message : "An unexpected API error occurred."}
          </p>
          <button type="button" className="btn btn-primary" onClick={() => refetch()}>
            Retry
          </button>
        </div>
      )}

      {/* Loading Skeleton */}
      {isLoading && !error && (
        <div className="timeline-skeleton" data-testid="loading-skeleton">
          <div className="skeleton-item" />
          <div className="skeleton-item" />
          <div className="skeleton-item" />
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !error && filteredEntries.length === 0 && (
        <div className="empty-state" data-testid="empty-activity">
          <div className="empty-icon">📜</div>
          <h3>No Activity Records Found</h3>
          <p className="muted">
            No audit or timeline events match the current filter criteria{" "}
            {activeCommitmentId ? `for commitment ${activeCommitmentId}` : ""}.
          </p>
          {(activeCommitmentId || selectedCorrelationId) && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                handleCommitmentChange("");
                handleCorrelationFilter("");
              }}
            >
              Reset All Filters
            </button>
          )}
        </div>
      )}

      {/* Main Content: Timeline View or Grouped Correlation View */}
      {!isLoading && !error && filteredEntries.length > 0 && (
        <div className="activity-content">
          {viewMode === "grouped" ? (
            <div className="correlation-groups-container">
              {correlationGroups.map((group) => (
                <div key={group.correlation_id} className="correlation-chain-card">
                  <div className="correlation-chain-header">
                    <div className="chain-title">
                      <span className="chain-icon">🔗</span>
                      <div>
                        <h4>Causal Chain: <code>{group.correlation_id}</code></h4>
                        <span className="chain-subtitle">
                          {group.entries.length} correlated events in trace
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      onClick={() => handleCorrelationFilter(group.correlation_id)}
                    >
                      Filter this Chain
                    </button>
                  </div>

                  <div className="timeline-track">
                    {group.entries.map((entry, index) => (
                      <TimelineEntryCard
                        key={entry.entry_id || index}
                        entry={entry}
                        onSelectCorrelation={handleCorrelationFilter}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="timeline-track" data-testid="timeline-track">
              {filteredEntries.map((entry, index) => (
                <TimelineEntryCard
                  key={entry.entry_id || index}
                  entry={entry}
                  onSelectCorrelation={handleCorrelationFilter}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface TimelineEntryCardProps {
  entry: NormalizedTimelineEntry;
  onSelectCorrelation: (correlationId: string) => void;
}

export function TimelineEntryCard({ entry, onSelectCorrelation }: TimelineEntryCardProps) {
  const { label: featureLabel, className: featureClass } = formatFeatureBadge(entry.source_feature);
  const roleBadgeClass = formatRoleBadgeClass(entry.actor_role);
  const isGovernance = isHumanGovernanceRecord(entry);
  const transitions = extractStateTransitions(entry.previous_state, entry.new_state);

  // Version changes
  const prevVersion =
    typeof entry.previous_state?.commitment_version === "number"
      ? (entry.previous_state.commitment_version as number)
      : null;
  const currentVersion = entry.commitment_version;
  const hasVersionIncrement =
    prevVersion !== null && currentVersion !== null && prevVersion !== currentVersion;

  // Redaction check
  const isRedacted =
    hasRedactedData(entry.new_state) ||
    hasRedactedData(entry.previous_state) ||
    hasRedactedData(entry.approval_reason);

  // Deep links extraction
  const orderId =
    entry.context_id ||
    (entry.new_state?.order_id as string | undefined) ||
    (entry.previous_state?.order_id as string | undefined);
  const assessmentId = entry.assessment_id;
  const recoveryCaseId = entry.recovery_case_id;
  const confirmationId = entry.communication_id || entry.proposal_id;

  return (
    <article
      className={`timeline-entry-card ${isGovernance ? "governance-highlight" : ""}`}
      data-testid="timeline-entry"
    >
      {/* Node Marker & Line Header */}
      <div className="entry-header">
        <div className="entry-badges">
          <span className={featureClass}>{featureLabel}</span>
          <span className="event-type-badge">{entry.event_type}</span>
          {hasVersionIncrement ? (
            <span className="version-pill version-increment">
              v{prevVersion} → v{currentVersion}
            </span>
          ) : currentVersion !== null && currentVersion !== undefined ? (
            <span className="version-pill">v{currentVersion}</span>
          ) : null}
        </div>

        <time className="entry-timestamp" dateTime={entry.occurred_at}>
          {formatKLTimestamp(entry.occurred_at)}
        </time>
      </div>

      {/* Entry Action / Summary */}
      <div className="entry-action-row">
        <h3 className="entry-action-title">{entry.action}</h3>
        <div className="actor-info">
          <span className="actor-id">{entry.actor_id}</span>
          <span className={roleBadgeClass}>{entry.actor_role}</span>
        </div>
      </div>

      {/* State Transitions Diff */}
      {transitions.length > 0 && (
        <div className="state-transitions-container" data-testid="state-transitions">
          <span className="transitions-label">State Transition:</span>
          {transitions.map((t, idx) => (
            <div key={idx} className="transition-diff-pill">
              <StatusBadge state={t.from} className="from-state" />
              <span className="arrow-separator" aria-hidden="true">
                →
              </span>
              <StatusBadge state={t.to} className="to-state" />
              {t.dimension && <span className="dimension-tag">({t.dimension})</span>}
            </div>
          ))}
        </div>
      )}

      {/* Human Governance Highlight (FE-03b) */}
      {isGovernance && (
        <div className="governance-callout" data-testid="governance-highlight">
          <div className="gov-header">
            <span className="gov-badge">🛡️ Human Governance Record</span>
            <span className="gov-actor">
              Approved by: <strong>{entry.actor_id}</strong> ({entry.actor_role})
            </span>
          </div>
          {entry.approval_reason && (
            <div className="gov-reason">
              <span className="gov-reason-label">Recorded Reason:</span>{" "}
              <span className="gov-reason-text">{entry.approval_reason}</span>
            </div>
          )}
          {Boolean(entry.new_state?.proposal_version) && (
            <div className="gov-detail">
              <span>Approved Proposal Version:</span>{" "}
              <strong>v{String(entry.new_state?.proposal_version)}</strong>
            </div>
          )}
          {Boolean(entry.new_state?.plan_version) && (
            <div className="gov-detail">
              <span>Approved Plan Version:</span>{" "}
              <strong>v{String(entry.new_state?.plan_version)}</strong>
            </div>
          )}
        </div>
      )}

      {/* Role Redaction Indicator (FE-03d) */}
      {isRedacted && (
        <div className="redacted-callout" data-testid="redacted-indicator">
          <span className="redacted-badge">🔒 Redacted for role</span>
          <span className="redacted-note">
            Confidential commercial, pricing, and contact fields are masked for this role view.
          </span>
        </div>
      )}

      {/* Causation & Correlation Visualisation (FE-03c) */}
      <div className="correlation-causation-row">
        <div className="correlation-info">
          <span className="corr-label">Correlation ID:</span>
          <button
            type="button"
            className="corr-link-btn"
            onClick={() => onSelectCorrelation(entry.correlation_id)}
            title="Click to filter by this correlation ID"
          >
            <code>{entry.correlation_id}</code>
          </button>
        </div>

        {entry.causation_id && (
          <div className="causation-info">
            <span className="causation-arrow" aria-hidden="true">
              ↳
            </span>
            <span className="causation-label">Triggered by causation:</span>
            <button
              type="button"
              className="corr-link-btn"
              onClick={() => onSelectCorrelation(entry.causation_id!)}
              title="Click to filter by causation trigger"
            >
              <code>{entry.causation_id}</code>
            </button>
          </div>
        )}
      </div>

      {/* Deep Links to F1-F4 & Evidence References (FE-03b) */}
      <div className="deep-links-row" data-testid="deep-links-row">
        <span className="deep-links-label">Module Links:</span>
        <div className="deep-links-list">
          {orderId && (
            <Link to={`/orders/${orderId}`} className="module-deep-link deep-link-f1">
              F1 Order ({orderId})
            </Link>
          )}
          {assessmentId && (
            <span className="module-deep-link deep-link-f2" title="This is an assessment reference; the impact route needs an impact ID.">
              F2 assessment {assessmentId}
            </span>
          )}
          {recoveryCaseId && (
            <Link to={`/recovery/${recoveryCaseId}`} className="module-deep-link deep-link-f3">
              F3 Recovery ({recoveryCaseId})
            </Link>
          )}
          {confirmationId && (
            <Link to={`/confirmations/${confirmationId}`} className="module-deep-link deep-link-f4">
              F4 Confirmation ({confirmationId})
            </Link>
          )}
        </div>
      </div>

      {/* Evidence References List */}
      {entry.evidence_refs && entry.evidence_refs.length > 0 && (
        <div className="evidence-refs-row">
          <span className="evidence-label">Evidence Refs:</span>
          <div className="evidence-chips">
            {entry.evidence_refs.map((ref) => (
              <span key={ref} className="evidence-chip">
                #{ref}
              </span>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}
