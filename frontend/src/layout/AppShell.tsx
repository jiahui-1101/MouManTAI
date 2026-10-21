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
  const { tenantId, actorId, setActorId, actorRole } = useAuth();

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Synthetic integration mode</p>
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
