import { useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../shared/auth";
import { activeAncestors, isItemActive, navigation, type NavigationIcon, type NavigationItem } from "./navigation";

const COLLAPSE_KEY = "moumantai.sidebar.collapsed";
const fullLogo = "/images/MouManTAI%20%C3%97%20Orbyte%20Logo.png";
const iconLogo = "/images/Interconnected%20Blue%20Logo.png";

const iconPaths: Record<NavigationIcon, string> = {
  dashboard: "M3 10.5 12 3l9 7.5M5 9v11h14V9M9 20v-7h6v7",
  calendar: "M4 5h16v16H4zM8 3v4m8-4v4M4 10h16m-12 4h2m4 0h2",
  inbox: "M3 4h18v16H3zM3 15h5l2 3h4l2-3h5M7 8h10m-10 3h7",
  review: "M5 3h14v18H5zM8 8h8m-8 4h5m-5 4 2 2 4-4",
  orders: "M4 4h16v16H4zM8 8h8m-8 4h8m-8 4h5",
  pending: "M12 3a9 9 0 1 0 9 9 9 9 0 0 0-9-9Zm0 4v5l3 2",
  planning: "M3 19h18M5 16l4-5 4 3 6-8M16 6h3v3",
  feasibility: "M4 12h4l3 4 8-9M3 3h18v18H3z",
  portfolio: "M4 5h7v7H4zM13 5h7v7h-7zM4 14h7v6H4zM13 14h7v6h-7z",
  forecast: "M3 20h18M5 17l4-5 4 2 6-8M16 6h3v3",
  supplier: "M3 20h18M5 20V7l7-4 7 4v13M9 10h2m2 0h2m-6 4h2m2 0h2",
  compare: "M3 7h18M7 3v4m10-4v4M5 11l-2 5h4l-2-5Zm14 0-2 5h4l-2-5ZM12 7v13m-4 0h8",
  sourcing: "M3 7h18v13H3zM8 7V4h8v3M3 12h18",
  recovery: "M4 12a8 8 0 1 1 2 5M4 18v-6h6M12 8v5l3 2",
  plans: "M5 3h14v18H5zM8 8h8m-8 4h8m-8 4h5",
  communication: "M3 5h18v14H3zM3 6l9 7 9-7",
  insights: "M4 20V12m5 8V7m5 13v-5m5 5V4",
  performance: "M3 20h18M5 16l4-4 4 2 6-8",
  history: "M3 12a9 9 0 1 0 3-7M3 4v5h5m4-2v5l4 2",
  activity: "M3 12h4l3-6 4 12 3-6h4",
  settings: "M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
};

function Icon({ name }: { name: NavigationIcon }) {
  return <svg className="sidebar-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={iconPaths[name]} /></svg>;
}

function filterItems(items: NavigationItem[], query: string): NavigationItem[] {
  if (!query) return items;
  return items.flatMap(item => {
    if (item.label.toLowerCase().includes(query)) return [item];
    const children = item.children && filterItems(item.children, query);
    return children?.length ? [{ ...item, children }] : [];
  });
}

export function Sidebar() {
  const { tenantId, actorId, actorRole, setActorId } = useAuth();
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState(() => {
    try { return window.localStorage.getItem(COLLAPSE_KEY) === "true"; } catch { return false; }
  });
  const [expanded, setExpanded] = useState<string[]>(() => activeAncestors(navigation, pathname));
  const [search, setSearch] = useState("");
  const [organizationOpen, setOrganizationOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const organizationRef = useRef<HTMLDivElement>(null);
  const organizationTriggerRef = useRef<HTMLButtonElement>(null);
  const organizationOptionRef = useRef<HTMLButtonElement>(null);
  const accountRef = useRef<HTMLDivElement>(null);
  const filtered = useMemo(() => filterItems(navigation, search.trim().toLowerCase()), [search]);

  useEffect(() => {
    setExpanded(current => [...new Set([...current, ...activeAncestors(navigation, pathname)])]);
  }, [pathname]);

  useEffect(() => {
    try { window.localStorage.setItem(COLLAPSE_KEY, String(collapsed)); } catch { /* Storage can be unavailable. */ }
  }, [collapsed]);

  useEffect(() => {
    if (!organizationOpen) return;
    organizationOptionRef.current?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (!organizationRef.current?.contains(event.target as Node)) setOrganizationOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOrganizationOpen(false); organizationTriggerRef.current?.focus(); }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("pointerdown", onPointerDown); document.removeEventListener("keydown", onKeyDown); };
  }, [organizationOpen]);

  useEffect(() => {
    if (!accountOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!accountRef.current?.contains(event.target as Node)) setAccountOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [accountOpen]);

  const toggleGroup = (id: string) => setExpanded(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  const renderItem = (item: NavigationItem, depth = 0) => {
    const active = isItemActive(item, pathname);
    const open = Boolean(search) || expanded.includes(item.id);
    const className = `sidebar-item${active ? " is-active" : ""}${depth ? " is-child" : ""}${!item.to && !item.children ? " is-unavailable" : ""}`;
    const itemContent = <><Icon name={item.icon} /><span className="sidebar-item-label">{item.label}</span>{item.children && <span className={`sidebar-chevron${open ? " is-open" : ""}`} aria-hidden="true">⌄</span>}</>;
    return <div key={item.id} className="sidebar-item-wrap">
      {item.children ? <button type="button" className={className} aria-expanded={open} aria-controls={`sidebar-group-${item.id}`} aria-label={collapsed ? item.label : undefined} title={item.label} onClick={() => { if (collapsed) setCollapsed(false); setExpanded(current => current.includes(item.id) ? current : [...current, item.id]); if (!collapsed) toggleGroup(item.id); }}>{itemContent}</button>
        : item.to ? <NavLink to={item.to} className={className} title={item.label} aria-label={collapsed ? item.label : undefined}>{itemContent}</NavLink>
        : <span className={className} aria-disabled="true" title={`${item.label} — unavailable`}><span className="sidebar-unavailable-content">{itemContent}</span><span className="sidebar-soon">Unavailable</span></span>}
      {item.children && <div id={`sidebar-group-${item.id}`} className="sidebar-submenu" hidden={!open}>{item.children.map(child => renderItem(child, depth + 1))}</div>}
    </div>;
  };

  return <nav aria-label="Primary navigation" className={`sidebar${collapsed ? " is-collapsed" : ""}`}>
    <div className="sidebar-header">
      <Link to="/overview" className="sidebar-logo" aria-label="MouManTAI overview" title="MouManTAI overview">
        <img className="sidebar-logo-full" src={fullLogo} alt="MouManTAI × Orbyte" />
        <img className="sidebar-logo-icon" src={iconLogo} alt="" />
      </Link>
      <button type="button" className="sidebar-toggle" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed} onClick={() => { setCollapsed(value => !value); setSearch(""); setAccountOpen(false); setOrganizationOpen(false); }} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d={collapsed ? "M10 4v16m3-12 4 4-4 4" : "M10 4v16m7-12-4 4 4 4"}/></svg>
      </button>
    </div>

    <div className="sidebar-organization" ref={organizationRef}>
      <button ref={organizationTriggerRef} type="button" className="sidebar-org-trigger" aria-label={`Current organization: ${tenantId}`} aria-haspopup="listbox" aria-expanded={organizationOpen} title={`Current organization: ${tenantId}`} onClick={() => setOrganizationOpen(value => !value)} onKeyDown={event => { if (event.key === "ArrowDown") { event.preventDefault(); setOrganizationOpen(true); } }}>
        <span className="sidebar-org-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M5 21V4h14v17M3 21h18M9 8h2m2 0h2M9 12h2m2 0h2M9 16h2m2 0h2" /></svg></span>
        <span className="sidebar-org-copy"><small>Current organization</small><strong>{tenantId}</strong></span>
        <span className="sidebar-org-chevron" aria-hidden="true">⌄</span>
      </button>
      {organizationOpen && <div className="sidebar-org-dropdown" role="listbox" aria-label="Available organizations" onKeyDown={event => {
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) { event.preventDefault(); organizationOptionRef.current?.focus(); }
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setOrganizationOpen(false); organizationTriggerRef.current?.focus(); }
      }}>
        <button ref={organizationOptionRef} type="button" role="option" aria-selected="true" className="sidebar-org-option is-selected" onClick={() => { setOrganizationOpen(false); organizationTriggerRef.current?.focus(); }}>
          <span className="sidebar-org-icon" aria-hidden="true">▦</span><span><strong>{tenantId}</strong><small>Current tenant</small></span><span className="sidebar-org-check" aria-hidden="true">✓</span>
        </button>
      </div>}
    </div>

    <label className="sidebar-search"><span className="sr-only">Search menu</span><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg><input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search menu…" aria-label="Search menu" /></label>
    <p className="sidebar-caption">Navigation</p>
    <div className="sidebar-links">{filtered.length ? filtered.map(item => renderItem(item)) : <p className="sidebar-no-results" role="status">No matching navigation items</p>}</div>

    <div className="sidebar-footer" ref={accountRef}>
      <button type="button" className="sidebar-account-toggle" aria-label={collapsed ? `Account: ${actorRole}. ${accountOpen ? "Close" : "Open"} role controls` : `Account: ${actorRole}`} aria-expanded={collapsed ? accountOpen : true} title={`${actorRole} · development role controls`} onClick={() => { if (collapsed) setAccountOpen(value => !value); }}><span className="sidebar-avatar" aria-hidden="true">{actorRole.slice(0, 1)}</span><span className="sidebar-account-copy"><strong>{actorRole}</strong><small>Development identity</small></span></button>
      <div className={`sidebar-account-panel${accountOpen ? " is-open" : ""}`}>
        <span className="tenant-badge" data-testid="shell-tenant-badge">{tenantId} · {actorRole}</span>
        <label htmlFor="shell-role-select" className="role-label">Development role switcher</label>
        <select id="shell-role-select" aria-label="Demo role selector" value={actorId} onChange={event => setActorId(event.target.value)} className="role-selector" data-testid="shell-role-selector">
          <option value="user_owner_01">Owner (user_owner_01)</option>
          <option value="user_manager_01">Manager (user_manager_01)</option>
          <option value="user_staff_01">Staff (user_staff_01)</option>
        </select>
      </div>
    </div>
  </nav>;
}
