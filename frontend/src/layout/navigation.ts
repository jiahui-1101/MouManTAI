export interface NavigationItem {
  to: string;
  label: string;
  activePrefixes?: readonly string[];
}

/** Only destinations with a working routed page appear in primary navigation. */
export const navigation: readonly NavigationItem[] = [
  { to: "/overview", label: "Overview" },
  { to: "/activity", label: "Activity" },
  { to: "/inbox", label: "Customer Inbox", activePrefixes: ["/orders/"] },
  { to: "/commitments/demo", label: "Commitment Feasibility", activePrefixes: ["/commitments/", "/impact/"] },
  { to: "/recovery/demo", label: "Recovery Case", activePrefixes: ["/recovery/"] },
  { to: "/communications", label: "Communications", activePrefixes: ["/communications/", "/confirmations/"] },
];

export function isNavigationItemActive(item: NavigationItem, pathname: string): boolean {
  if (pathname === item.to || pathname.startsWith(`${item.to}/`)) return true;
  return item.activePrefixes?.some((prefix) => pathname.startsWith(prefix)) ?? false;
}
