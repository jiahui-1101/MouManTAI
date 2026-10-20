import { useEffect, useState } from "react";

import { getHealth, type HealthResponse } from "../shared/api";

export function OverviewPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getHealth()
      .then((result) => {
        if (active) setHealth(result);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Backend health check failed");
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <section aria-labelledby="overview-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Shared core</p>
          <h2 id="overview-title">Commitment overview</h2>
          <p className="muted">Phase 0 foundation is ready for independently owned feature slices.</p>
        </div>
        <span className="status-pill">SYNTHETIC</span>
      </div>

      <div className="metric-grid">
        <article className="metric-card">
          <span className="muted">Commitment registry</span>
          <strong>Contract-ready</strong>
          <small>Agreement, feasibility, risk, recovery and fulfilment remain separate.</small>
        </article>
        <article className="metric-card">
          <span className="muted">Tenant scope</span>
          <strong>tenant_demo_01</strong>
          <small>All Phase 0 fixture records share one explicit tenant.</small>
        </article>
        <article className="metric-card">
          <span className="muted">API health</span>
          <strong>{health ? "Connected" : error ? "Unavailable" : "Checking…"}</strong>
          <small>{error ?? (health ? `${health.service} ${health.version}` : "Waiting for /health")}</small>
        </article>
      </div>

      <div className="notice-card">
        <h3>Parallel development boundaries</h3>
        <p>
          P1–P4 routes are intentionally placeholders. Feature owners can add their vertical slices without
          changing the shared contract, tenant, version or evidence semantics.
        </p>
      </div>
    </section>
  );
}
