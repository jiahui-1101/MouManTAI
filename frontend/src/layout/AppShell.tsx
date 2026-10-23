import { Link, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../shared/auth";
import { getOverview } from "../shared/api";
import { formatKLTimestamp } from "../shared/date";
import { ErrorBoundary } from "../shared/ErrorBoundary";
import { ToastProvider } from "../shared/Toast";
import { Sidebar } from "./Sidebar";

const routeLabels: Record<string, string> = {
  overview: "Overview",
  activity: "Activity",
  inbox: "Inbox",
  orders: "Orders",
  commitments: "Commitments",
  impact: "Impact",
  recovery: "Recovery",
  communications: "Communications",
  confirmations: "Confirmations",
};

export function Breadcrumbs() {
  const location = useLocation();
  const segments = location.pathname.split("/").filter(Boolean);

  if (segments.length === 0 || (segments.length === 1 && segments[0] === "overview")) {
    return (
      <nav aria-label="Breadcrumb" className="breadcrumbs" data-testid="shell-breadcrumbs">
        <ol>
          <li>
            <span aria-current="page">Overview</span>
          </li>
        </ol>
      </nav>
    );
  }

  // Hierarchy: Overview > Section > ID
  const crumbs: { label: string; path: string; isLast: boolean }[] = [
    { label: "Overview", path: "/overview", isLast: false },
  ];

  let accumulatedPath = "";
  segments.forEach((seg, index) => {
    accumulatedPath += `/${seg}`;
    const isLast = index === segments.length - 1;
    const label = routeLabels[seg] || seg;
    crumbs.push({ label, path: accumulatedPath, isLast });
  });

  return (
    <nav aria-label="Breadcrumb" className="breadcrumbs" data-testid="shell-breadcrumbs">
      <ol>
        {crumbs.map((crumb, idx) => (
          <li key={crumb.path || idx}>
            {idx > 0 && <span aria-hidden="true" className="breadcrumb-separator"> &gt; </span>}
            {crumb.isLast ? (
              <span aria-current="page">{crumb.label}</span>
            ) : (
              <Link to={crumb.path}>{crumb.label}</Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function AppShell() {
  const { tenantId, actorId, authHeaders } = useAuth();
  const location = useLocation();
  const { data: overview } = useQuery({
    queryKey: ["overview", tenantId, actorId],
    queryFn: () => getOverview(authHeaders),
    enabled: location.pathname === "/" || location.pathname === "/overview",
  });

  return (
    <ToastProvider>
      <div className="app-shell">
        <Sidebar />

        <div className="shell-workspace">
          <header className="topbar sr-only">
            <div>
              <p className="eyebrow">Business command center</p>
              <h1>MouManTAI</h1>
            </div>
            <div className="topbar-controls">
              <span className="shell-connection" aria-label="Integration mode and last updated">
                <strong>{overview?.integration_mode ?? "Mode unknown"}</strong>
                <small>{overview?.last_updated_at ? `Updated ${formatKLTimestamp(overview.last_updated_at)}` : "Update time unavailable"}</small>
              </span>
            </div>
          </header>
          <main className="main-content">
            <Breadcrumbs />
            <ErrorBoundary><Outlet /></ErrorBoundary>
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
