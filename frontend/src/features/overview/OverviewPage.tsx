import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { ApiError, getOverview } from "../../shared/api";
import { KNOWN_ACTORS, useAuth } from "../../shared/auth";
import { formatKLDateOnly, formatKLTimestamp } from "../../shared/date";
import { StatusBadge } from "../../shared/StatusBadge";
import type { AttentionItem, OverviewCommitmentSummary, OverviewCounts } from "../../shared/types";

export type StateBucket =
  | "ALL"
  | "REQUESTED"
  | "CONFIRMED"
  | "AT_RISK"
  | "PENDING_APPROVAL"
  | "EXECUTION_IN_PROGRESS"
  | "AWAITING_CONFIRMATION"
  | "FULFILLED";

interface BucketConfig {
  key: StateBucket;
  countKey: keyof OverviewCounts;
  label: string;
  badgeClass: string;
  description: string;
}

const STATE_BUCKETS: BucketConfig[] = [
  {
    key: "REQUESTED",
    countKey: "requested",
    label: "Requested",
    badgeClass: "badge-neutral",
    description: "Inbound demand awaiting feasibility assessment",
  },
  {
    key: "CONFIRMED",
    countKey: "confirmed",
    label: "Confirmed",
    badgeClass: "badge-success",
    description: "Mutually agreed commitments",
  },
  {
    key: "AT_RISK",
    countKey: "at_risk",
    label: "At Risk",
    badgeClass: "badge-danger",
    description: "Commitments threatened by stock, delay or capacity",
  },
  {
    key: "PENDING_APPROVAL",
    countKey: "pending_approval",
    label: "Pending Approval",
    badgeClass: "badge-warning", // FE-01d: NEVER green
    description: "Recovery proposals requiring manager sign-off",
  },
  {
    key: "EXECUTION_IN_PROGRESS",
    countKey: "execution_in_progress",
    label: "Execution in Progress",
    badgeClass: "badge-info",
    description: "Approved recovery actions currently being executed",
  },
  {
    key: "AWAITING_CONFIRMATION",
    countKey: "awaiting_confirmation",
    label: "Awaiting Confirmation",
    badgeClass: "badge-purple", // FE-01d: NEVER green
    description: "Customer proposals sent, awaiting explicit accept/reject",
  },
  {
    key: "FULFILLED",
    countKey: "fulfilled",
    label: "Fulfilled",
    badgeClass: "badge-success",
    description: "Operational delivery verified with trusted evidence",
  },
];

export function OverviewPage() {
  const { tenantId, actorId, setActorId, authHeaders } = useAuth();
  const [activeBucket, setActiveBucket] = useState<StateBucket>("ALL");
  const [searchQuery, setSearchQuery] = useState("");

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

  const filteredCommitments = useMemo(() => {
    if (!data?.commitments) return [];
    return data.commitments.filter((c: OverviewCommitmentSummary) => {
      // 1. Bucket filter
      if (activeBucket === "REQUESTED" && c.agreement_state !== "REQUESTED") return false;
      if (activeBucket === "CONFIRMED" && c.agreement_state !== "CONFIRMED") return false;
      if (activeBucket === "AT_RISK" && c.risk_state !== "AT_RISK" && c.risk_state !== "BREACHED") return false;
      if (activeBucket === "PENDING_APPROVAL" && c.recovery_state !== "PENDING_APPROVAL") return false;
      if (activeBucket === "EXECUTION_IN_PROGRESS" && c.recovery_state !== "EXECUTING") return false;
      if (activeBucket === "AWAITING_CONFIRMATION" && c.agreement_state !== "OFFERED") return false;
      if (activeBucket === "FULFILLED" && c.fulfilment_state !== "FULFILLED") return false;

      // 2. Search query filter
      if (searchQuery.trim()) {
        const query = searchQuery.trim().toLowerCase();
        const matchesId = c.commitment_id.toLowerCase().includes(query);
        const matchesOrder = c.order_id.toLowerCase().includes(query);
        const matchesCustomer = c.customer_id.toLowerCase().includes(query);
        const matchesSku = c.terms.sku.toLowerCase().includes(query);
        return matchesId || matchesOrder || matchesCustomer || matchesSku;
      }

      return true;
    });
  }, [data?.commitments, activeBucket, searchQuery]);

  // Loading Skeleton State
  if (isLoading) {
    return (
      <section aria-labelledby="overview-title" className="overview-container" role="status" aria-busy="true">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Commitment Assurance Core</p>
            <h2 id="overview-title">Commitment Overview</h2>
          </div>
          <span className="status-pill">SYNTHETIC</span>
        </div>
        <div className="skeleton-grid" data-testid="loading-skeleton">
          <div className="skeleton-card" />
          <div className="skeleton-card" />
          <div className="skeleton-card" />
          <div className="skeleton-card" />
          <div className="skeleton-card" />
          <div className="skeleton-card" />
          <div className="skeleton-card" />
        </div>
        <p className="muted text-center" style={{ marginTop: "2rem" }}>
          Loading authoritative commitment metrics…
        </p>
      </section>
    );
  }

  // 403 Permission Denied State
  if (isForbidden) {
    return (
      <section aria-labelledby="overview-title" className="overview-container">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Commitment Assurance Core</p>
            <h2 id="overview-title">Commitment Overview</h2>
          </div>
          <span className="status-pill warning">RESTRICTED</span>
        </div>

        <div className="error-card permission-denied" role="alert" data-testid="permission-denied-state">
          <div className="error-badge">403 FORBIDDEN</div>
          <h3>Access Denied</h3>
          <p>
            The simulated role <strong>{actorId}</strong> is not permitted to access this tenant’s commitment overview.
          </p>
          <div className="actor-switcher-inline">
            <label htmlFor="forbidden-actor-select">Switch simulated actor:</label>
            <select
              id="forbidden-actor-select"
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
      </section>
    );
  }

  // Generic API Error State with Working Retry Callback
  if (error || !data) {
    return (
      <section aria-labelledby="overview-title" className="overview-container">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Commitment Assurance Core</p>
            <h2 id="overview-title">Commitment Overview</h2>
          </div>
          <span className="status-pill warning">DISCONNECTED</span>
        </div>

        <div className="error-card" role="alert" data-testid="error-state">
          <div className="error-badge">API ERROR</div>
          <h3>Failed to Load Overview Data</h3>
          <p className="error-message">
            {error instanceof Error ? error.message : "Failed to fetch commitment overview from backend service."}
          </p>
          <button type="button" onClick={() => refetch()} className="btn btn-primary" data-testid="retry-button">
            Retry Connection
          </button>
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="overview-title" className="overview-container">
      {/* FE-02d: Transparency Header */}
      <div className="transparency-header">
        <div className="header-titles">
          <p className="eyebrow">Intelligent Commitment Assurance & Recovery</p>
          <h2 id="overview-title">Commitment Overview</h2>
          <div className="transparency-meta">
            <span className="meta-item">
              Tenant: <strong data-testid="active-tenant">{data.tenant_id}</strong>
            </span>
            <span className="meta-separator">•</span>
            <span className="meta-item">
              Active Role: <strong data-testid="active-role">{data.actor_role}</strong>
            </span>
            <span className="meta-separator">•</span>
            <span className="meta-item">
              Last Updated: <span title="Asia/Kuala_Lumpur time">{formatKLTimestamp(data.last_updated_at)}</span>
            </span>
          </div>
        </div>

        <div className="header-actions">
          <span className="status-pill" data-testid="synthetic-badge">
            {data.integration_mode}
          </span>

          <div className="actor-selector-group">
            <label htmlFor="actor-role-select" className="sr-only">
              Simulate Actor
            </label>
            <select
              id="actor-role-select"
              aria-label="Simulated actor role"
              value={actorId}
              onChange={(e) => setActorId(e.target.value)}
              className="actor-select"
              data-testid="actor-select"
            >
              {KNOWN_ACTORS.map((act) => (
                <option key={act.actorId} value={act.actorId}>
                  {act.label} · {act.role}
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="btn btn-secondary refresh-btn"
            data-testid="refresh-button"
            title="Fetch latest aggregate state from backend"
          >
            {isFetching ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {/* FE-02a & FE-02c: 7 Authoritative State Summary Cards */}
      <div className="metric-grid-7" data-testid="state-summary-cards">
        {STATE_BUCKETS.map((bucket) => {
          const count = data.counts[bucket.countKey];
          const isSelected = activeBucket === bucket.key;
          return (
            <button
              type="button"
              key={bucket.key}
              onClick={() => setActiveBucket(isSelected ? "ALL" : bucket.key)}
              className={`metric-card-summary ${bucket.badgeClass} ${isSelected ? "selected" : ""}`}
              data-testid={`card-${bucket.countKey}`}
              aria-pressed={isSelected}
            >
              <div className="card-top">
                <span className="card-label">{bucket.label}</span>
                <span className="card-badge">{isSelected ? "Filtering" : "Filter"}</span>
              </div>
              <strong className="card-count" data-testid={`count-${bucket.countKey}`}>
                {count}
              </strong>
              <small className="card-desc">{bucket.description}</small>
            </button>
          );
        })}
      </div>

      {/* FE-02b: Attention Queue */}
      <div className="section-card attention-section" data-testid="attention-queue-section">
        <div className="section-header">
          <div className="section-header-left">
            <h3 className="section-title">Attention Queue</h3>
            <span className="count-pill">{data.attention_queue.length}</span>
          </div>
          <span className="muted text-sm">
            High-priority operational items requiring immediate SME staff or manager action
          </span>
        </div>

        {data.attention_queue.length === 0 ? (
          <div className="empty-notice" data-testid="attention-queue-empty">
            <p>✓ No urgent attention items detected. All commitments and plans are operating normally.</p>
          </div>
        ) : (
          <div className="attention-list">
            {data.attention_queue.map((item: AttentionItem, idx: number) => (
              <div
                key={`${item.commitment_id}-${item.category}-${idx}`}
                className={`attention-item severity-${item.severity.toLowerCase()}`}
                data-testid="attention-item"
              >
                <div className="attention-item-header">
                  <div className="attention-badges">
                    <StatusBadge state={item.severity} className="badge-severity" />
                    <StatusBadge state={item.category} className="badge-category" />
                  </div>
                  <time className="attention-time" dateTime={item.updated_at}>
                    {formatKLTimestamp(item.updated_at)}
                  </time>
                </div>

                <div className="attention-body">
                  <p className="attention-summary">{item.summary}</p>
                  <div className="attention-meta">
                    <span>
                      Commitment: <code>{item.commitment_id}</code>
                    </span>
                    <span className="meta-separator">•</span>
                    <span>
                      Order: <code>{item.order_id}</code>
                    </span>
                  </div>
                </div>

                <div className="attention-action">
                  <Link
                    to={item.deep_link_path}
                    className="btn btn-outline btn-sm"
                    data-testid="attention-deep-link"
                  >
                    Resolve in Feature Route &rarr;
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* FE-02e: Commitments Registry Explorer & Filtering */}
      <div className="section-card commitments-section" data-testid="commitments-explorer-section">
        <div className="section-header">
          <div className="section-header-left">
            <h3 className="section-title">Commitment Registry Explorer</h3>
            <span className="count-pill">{filteredCommitments.length}</span>
          </div>

          <div className="filter-controls">
            <input
              type="search"
              placeholder="Search by ID, Order, Customer, or SKU…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="search-input"
              data-testid="commitment-search-input"
              aria-label="Search commitments"
            />
            {activeBucket !== "ALL" && (
              <button
                type="button"
                onClick={() => setActiveBucket("ALL")}
                className="btn btn-ghost btn-sm"
                data-testid="clear-bucket-filter"
              >
                Clear Bucket Filter ({activeBucket}) ×
              </button>
            )}
          </div>
        </div>

        {/* Filter Chips */}
        <div className="filter-chips-bar" role="tablist" aria-label="Commitment state filter tabs">
          <button
            type="button"
            role="tab"
            aria-selected={activeBucket === "ALL"}
            className={`filter-chip ${activeBucket === "ALL" ? "active" : ""}`}
            onClick={() => setActiveBucket("ALL")}
            data-testid="filter-chip-all"
          >
            All Commitments ({data.commitments.length})
          </button>
          {STATE_BUCKETS.map((b) => (
            <button
              type="button"
              role="tab"
              key={b.key}
              aria-selected={activeBucket === b.key}
              className={`filter-chip ${activeBucket === b.key ? "active" : ""}`}
              onClick={() => setActiveBucket(b.key)}
              data-testid={`filter-chip-${b.countKey}`}
            >
              {b.label} ({data.counts[b.countKey]})
            </button>
          ))}
        </div>

        {/* Mandatory Empty State (FE-02e) */}
        {filteredCommitments.length === 0 ? (
          <div className="empty-state-card" data-testid="empty-commitments-state">
            <h4>No Commitments Found</h4>
            <p className="muted">
              {data.commitments.length === 0
                ? "There are currently zero commitments registered for this tenant."
                : `No commitments match the active filter "${activeBucket}" and search query "${searchQuery}".`}
            </p>
            {(activeBucket !== "ALL" || searchQuery) && (
              <button
                type="button"
                onClick={() => {
                  setActiveBucket("ALL");
                  setSearchQuery("");
                }}
                className="btn btn-secondary btn-sm"
                data-testid="reset-filters-button"
              >
                Reset All Filters
              </button>
            )}
          </div>
        ) : (
          <div className="table-responsive">
            <table className="commitments-table" data-testid="commitments-table">
              <thead>
                <tr>
                  <th>Commitment ID / Order</th>
                  <th>Customer</th>
                  <th>Terms (SKU / Qty / Due)</th>
                  <th>5 Authoritative Lifecycle States</th>
                  <th>Ver</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredCommitments.map((c: OverviewCommitmentSummary) => (
                  <tr key={c.commitment_id} data-testid={`commitment-row-${c.commitment_id}`}>
                    <td>
                      <div className="id-cell">
                        <Link
                          to={`/commitments/${c.commitment_id}`}
                          className="primary-id-link"
                          title="View Feasibility Assessment (P2)"
                        >
                          {c.commitment_id}
                        </Link>
                        <span className="secondary-id">
                          Order: <Link to={`/orders/${c.order_id}`}>{c.order_id}</Link>
                        </span>
                      </div>
                    </td>
                    <td>
                      <span className="customer-cell">{c.customer_id}</span>
                    </td>
                    <td>
                      <div className="terms-cell">
                        <strong>{c.terms.sku}</strong>
                        <span className="qty-tag">
                          {c.terms.quantity} {c.terms.unit}
                        </span>
                        <span className="deadline-tag">
                          Due: {formatKLDateOnly(c.terms.deadline)}
                        </span>
                      </div>
                    </td>
                    <td>
                      <div className="states-grid">
                        <div className="state-row">
                          <span className="dim-label">Agreement:</span>
                          <StatusBadge dimension="agreement" state={c.agreement_state} />
                        </div>
                        <div className="state-row">
                          <span className="dim-label">Feasibility:</span>
                          <StatusBadge dimension="feasibility" state={c.feasibility_state} />
                        </div>
                        <div className="state-row">
                          <span className="dim-label">Risk:</span>
                          <StatusBadge dimension="risk" state={c.risk_state} />
                        </div>
                        <div className="state-row">
                          <span className="dim-label">Recovery:</span>
                          <StatusBadge dimension="recovery" state={c.recovery_state} />
                        </div>
                        <div className="state-row">
                          <span className="dim-label">Fulfilment:</span>
                          <StatusBadge dimension="fulfilment" state={c.fulfilment_state} />
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className="version-pill">v{c.commitment_version}</span>
                    </td>
                    <td>
                      <div className="action-links">
                        <Link
                          to={`/commitments/${c.commitment_id}`}
                          className="table-action-link"
                          data-testid={`inspect-link-${c.commitment_id}`}
                        >
                          Feasibility
                        </Link>
                        <Link
                          to={`/activity?commitment_id=${encodeURIComponent(c.commitment_id)}`}
                          className="table-action-link secondary"
                          data-testid={`activity-link-${c.commitment_id}`}
                        >
                          Audit & Timeline
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
