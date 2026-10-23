/** Sidebar destinations describe existing frontend routes only. Future pages stay visible but unavailable. */
export type NavigationIcon = "dashboard" | "calendar" | "inbox" | "review" | "orders" | "pending" | "planning" | "feasibility" | "portfolio" | "forecast" | "supplier" | "compare" | "sourcing" | "recovery" | "plans" | "communication" | "insights" | "performance" | "history" | "activity" | "settings";

export interface NavigationItem {
  id: string;
  label: string;
  icon: NavigationIcon;
  to?: string;
  /** Detail routes stay under their business parent without becoming sidebar destinations. */
  activeFor?: string[];
  children?: NavigationItem[];
}

export const navigation: NavigationItem[] = [
  { id: "dashboard", label: "Dashboard", icon: "dashboard", children: [
    { id: "overview", label: "Overview", icon: "dashboard", to: "/overview", activeFor: ["/"] },
    { id: "calendar", label: "Calendar", icon: "calendar" },
  ] },
  { id: "inbox", label: "Inbox", icon: "inbox", children: [
    { id: "customer-messages", label: "Customer Messages", icon: "inbox", to: "/inbox" },
    { id: "human-review", label: "Human Review", icon: "review" },
  ] },
  { id: "orders", label: "Orders", icon: "orders", activeFor: ["/orders/", "/commitments/", "/impact/"], children: [
    { id: "all-orders", label: "All Orders", icon: "orders" },
    { id: "pending-acceptance", label: "Pending Acceptance", icon: "pending" },
  ] },
  { id: "planning", label: "Planning", icon: "planning", children: [
    { id: "feasibility", label: "Feasibility", icon: "feasibility" },
    { id: "portfolio-comparison", label: "Portfolio Comparison", icon: "portfolio" },
    { id: "forecasts", label: "Forecasts", icon: "forecast" },
  ] },
  { id: "suppliers", label: "Suppliers", icon: "supplier", children: [
    { id: "supplier-directory", label: "Supplier Directory", icon: "supplier" },
    { id: "offer-comparison", label: "Offer Comparison", icon: "compare" },
    { id: "sourcing", label: "Sourcing", icon: "sourcing" },
  ] },
  { id: "recovery", label: "Recovery", icon: "recovery", activeFor: ["/recovery/"], children: [
    { id: "emergency-cases", label: "Emergency Cases", icon: "recovery" },
    { id: "recovery-plans", label: "Recovery Plans", icon: "plans" },
  ] },
  { id: "communications", label: "Communications", icon: "communication", to: "/communications", activeFor: ["/communications/", "/confirmations/"] },
  { id: "insights", label: "Insights", icon: "insights", children: [
    { id: "performance", label: "Performance", icon: "performance" },
    { id: "decision-history", label: "Decision History", icon: "history" },
    { id: "activity", label: "Activity", icon: "activity", to: "/activity" },
  ] },
  { id: "settings", label: "Settings", icon: "settings" },
];

export function isItemActive(item: NavigationItem, pathname: string): boolean {
  if (item.to && (pathname === item.to || (item.to !== "/" && pathname.startsWith(`${item.to}/`)))) return true;
  if (item.activeFor?.some(path => path === pathname || (path.endsWith("/") && pathname.startsWith(path)))) return true;
  return item.children?.some(child => isItemActive(child, pathname)) ?? false;
}

export function activeAncestors(items: NavigationItem[], pathname: string): string[] {
  return items.filter(item => item.children?.some(child => isItemActive(child, pathname)) || (item.children && isItemActive(item, pathname))).map(item => item.id);
}
