import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../shared/auth";
import { ErrorBoundary } from "../shared/ErrorBoundary";
import { ToastProvider } from "../shared/Toast";

const navigation = [
  ["/overview", "Overview"],
  ["/activity", "Activity"],
  ["/inbox", "Order inbox"],
  ["/commitments/demo", "Feasibility"],
  ["/recovery/demo", "Recovery"],
  ["/communications", "Communications"],
] as const;

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
  const sectionDestinations: Record<string, string | undefined> = {
    orders: "/inbox", impact: "/activity", communications: "/communications",
    confirmations: "/communications", recovery: undefined, commitments: undefined,
  };
  const crumbs: { label: string; path: string; isLast: boolean; linkTo?: string }[] = [
    { label: "Overview", path: "/overview", isLast: false, linkTo: "/overview" },
  ];

  let accumulatedPath = "";
  segments.forEach((seg, index) => {
    accumulatedPath += `/${seg}`;
    const isLast = index === segments.length - 1;
    const label = routeLabels[seg] || seg;
    const linkTo = isLast ? undefined : index === 0 ? sectionDestinations[seg] : accumulatedPath;
    crumbs.push({ label, path: accumulatedPath, isLast, linkTo });
  });

  return (
    <nav aria-label="Breadcrumb" className="breadcrumbs" data-testid="shell-breadcrumbs">
      <ol>
        {crumbs.map((crumb, idx) => (
          <li key={crumb.path || idx}>
            {idx > 0 && <span aria-hidden="true" className="breadcrumb-separator"> &gt; </span>}
            {crumb.isLast || !crumb.linkTo ? (
              <span aria-current={crumb.isLast ? "page" : undefined}>{crumb.label}</span>
            ) : (
              <Link to={crumb.linkTo}>{crumb.label}</Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function AppShell() {
  const { tenantId, actorId, setActorId, actorRole } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  const section = location.pathname.split("/")[1] || "overview";
  const sectionTitle = routeLabels[section] || "Workspace";

  return (
    <ToastProvider>
      <div className="app-shell">
        <header className="topbar">
          <div className="brand-lockup">
            <span className="brand-mark" aria-hidden="true">M</span>
            <div>
              <p className="eyebrow">Operations workspace</p>
              <h1>MouManTAI</h1>
            </div>
          </div>
          <div className="topbar-controls">
            <span className="environment-badge">Synthetic integration</span>
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
            <button type="button" className="mobile-menu-toggle" aria-controls="primary-navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(value => !value)}>
              {menuOpen ? "Close menu" : "Menu"}
            </button>
          </div>
        </header>

        <div className="shell-body">
          <nav id="primary-navigation" aria-label="Primary navigation" className={`sidebar${menuOpen ? " sidebar-open" : ""}`}>
            <p className="sidebar-label">WORKSPACE</p>
            {navigation.map(([to, label]) => (
              <NavLink key={to} to={to} onClick={() => setMenuOpen(false)} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
                {label}
              </NavLink>
            ))}
            <div className="sidebar-footnote">Decision support · tenant scoped<br />Demo routes use synthetic data.</div>
          </nav>

          <main className="main-content">
            <div className="workspace-context"><span className="workspace-context-dot" aria-hidden="true" /> {sectionTitle} <span aria-hidden="true">/</span> Tenant workspace</div>
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
