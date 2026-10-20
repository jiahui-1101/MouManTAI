import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../shared/auth";

const navigation = [
  ["/overview", "Overview"],
  ["/activity", "Activity"],
  ["/inbox", "Inbox · P1"],
  ["/commitments/demo", "Commitment · P2"],
  ["/recovery/demo", "Recovery · P3"],
  ["/communications", "Communications · P4"],
] as const;

export function AppShell() {
  const { tenantId, actorRole } = useAuth();

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Synthetic integration mode</p>
          <h1>MouManTAI</h1>
        </div>
        <span className="tenant-badge">
          {tenantId} · {actorRole}
        </span>
      </header>

      <div className="shell-body">
        <nav aria-label="Primary navigation" className="sidebar">
          {navigation.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              {label}
            </NavLink>
          ))}
        </nav>

        <main className="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
