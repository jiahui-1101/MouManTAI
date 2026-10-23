import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../shared/auth";
import { ErrorBoundary } from "../shared/ErrorBoundary";
import { ToastProvider } from "../shared/Toast";
import { EvidenceTierBadge } from "../shared/EvidenceTierBadge";
import { isNavigationItemActive, navigation } from "./navigation";

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
  const { tenantId, actorId, setActorId, actorRole } = useAuth();
  const location = useLocation();

  return (
    <ToastProvider>
      <div className="app-shell">
        <header className="topbar">
          <div>
            <EvidenceTierBadge evidenceTier="DEMO-ONLY" integrationMode="SYNTHETIC" />
            <h1>MouManTAI</h1>
          </div>
          <div className="topbar-controls">
            <div className="role-simulator">
              <label htmlFor="shell-role-select" className="role-label">
                Simulated Role:
              </label>
              <select
                id="shell-role-select"
                aria-label="Demo role selector"
                value={actorId}
                onChange={(e) => setActorId(e.target.value)}
                className="role-selector"
                data-testid="shell-role-selector"
              >
                <option value="user_owner_01">Owner (user_owner_01)</option>
                <option value="user_manager_01">Manager (user_manager_01)</option>
                <option value="user_staff_01">Staff (user_staff_01)</option>
              </select>
            </div>
            <span className="tenant-badge" data-testid="shell-tenant-badge">
              {tenantId} · {actorRole}
            </span>
          </div>
        </header>

        <div className="shell-body">
          <nav aria-label="Primary navigation" className="sidebar">
            {navigation.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => (isActive || isNavigationItemActive(item, location.pathname) ? "nav-link active" : "nav-link")}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <main className="main-content">
            <Breadcrumbs />
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
