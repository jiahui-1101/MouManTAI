import { describe, expect, it } from "vitest";
import { activeAncestors, isItemActive, isNavigationItemActive, navigation } from "./navigation";

describe("business navigation", () => {
  it("uses business labels and only links to existing destinations", () => {
    expect(navigation.map((item) => item.label)).toEqual([
      "Dashboard", "Inbox", "Orders", "Planning", "Suppliers", "Recovery", "Communications", "Insights", "Settings",
    ]);
    expect(navigation.every((item) => !/\bP[1-5]\b/.test(item.label))).toBe(true);
  });

  it("keeps parent destinations active for existing deep links", () => {
    const orders = navigation.find((item) => item.id === "orders")!;
    const communications = navigation.find((item) => item.id === "communications")!;
    expect(isItemActive(orders, "/impact/fa_001")).toBe(true);
    expect(isItemActive(communications, "/confirmations/conf_001")).toBe(true);
    expect(isItemActive(communications, "/communications/follow-ups")).toBe(true);
  });

  it("keeps Orders active for order detail while planning pages use their own destinations", () => {
    const orders = navigation.find((item) => item.id === "orders");
    const inbox = navigation.find((item) => item.id === "inbox");

    expect(orders).toBeDefined();
    expect(inbox).toBeDefined();

    expect(isItemActive(orders!, "/orders/123")).toBe(true);
    expect(isItemActive(orders!, "/orders/pending")).toBe(true);
    expect(isItemActive(orders!, "/orders/portfolio")).toBe(false);
    expect(isItemActive(orders!, "/orders/calendar")).toBe(false);

    expect(isItemActive(inbox!, "/orders/123")).toBe(false);
  });

  it.each([
    ['/orders', 'all-orders', 'orders'], ['/orders/order-123', 'all-orders', 'orders'],
    ['/orders/pending', 'all-orders', 'orders'],
    ['/orders/portfolio', 'portfolio-comparison', 'planning'],
    ['/planning/portfolio', 'portfolio-comparison', 'planning'],
    ['/orders/calendar', 'calendar', 'dashboard'], ['/calendar', 'calendar', 'dashboard'],
  ])('selects exactly the intended destination for %s', (path, itemId, groupId) => {
    const items = navigation.flatMap(group => group.children ?? [group]);
    expect(items.filter(item => isItemActive(item, path)).map(item => item.id)).toEqual([itemId]);
    expect(items.filter(item => isNavigationItemActive(item, path)).map(item => item.id)).toEqual([itemId]);
    expect(activeAncestors(navigation, path)).toEqual([groupId]);
  });
});
