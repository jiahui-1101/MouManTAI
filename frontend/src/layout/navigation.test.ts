import { describe, expect, it } from "vitest";
import { activeAncestors, isItemActive, isNavigationItemActive, navigation } from "./navigation";

describe("navigation active state", () => {
  it("keeps Orders active for order detail while planning pages use their own destinations", () => {
    const orders = navigation.find((item) => item.id === "orders");
    expect(orders).toBeDefined();

    expect(isItemActive(orders!, "/orders")).toBe(true);
    expect(isItemActive(orders!, "/orders/com_123")).toBe(true);
    expect(isItemActive(orders!, "/orders/pending")).toBe(true);
    expect(isItemActive(orders!, "/orders/portfolio")).toBe(false);
    expect(isItemActive(orders!, "/orders/calendar")).toBe(false);
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

  it("prevents simultaneous active state on parent and sibling routes for suppliers and recovery", () => {
    const suppliers = navigation.find((item) => item.id === "suppliers")!;
    const supplierDirectory = suppliers.children!.find((c) => c.id === "supplier-directory")!;
    const offerComparison = suppliers.children!.find((c) => c.id === "offer-comparison")!;

    expect(isItemActive(offerComparison, "/suppliers/compare")).toBe(true);
    expect(isItemActive(supplierDirectory, "/suppliers/compare")).toBe(false);
    expect(isItemActive(suppliers, "/suppliers/compare")).toBe(true);

    expect(isItemActive(supplierDirectory, "/suppliers")).toBe(true);
    expect(isItemActive(offerComparison, "/suppliers")).toBe(false);
    expect(isItemActive(suppliers, "/suppliers")).toBe(true);

    expect(isItemActive(supplierDirectory, "/suppliers/sup_123")).toBe(true);
    expect(isItemActive(offerComparison, "/suppliers/sup_123")).toBe(false);

    const recovery = navigation.find((item) => item.id === "recovery")!;
    const emergencyCases = recovery.children!.find((c) => c.id === "emergency-cases")!;
    const recoveryPlans = recovery.children!.find((c) => c.id === "recovery-plans")!;

    expect(isItemActive(recoveryPlans, "/recovery/plans")).toBe(true);
    expect(isItemActive(emergencyCases, "/recovery/plans")).toBe(false);
    expect(isItemActive(recovery, "/recovery/plans")).toBe(true);

    expect(isItemActive(emergencyCases, "/recovery")).toBe(true);
    expect(isItemActive(recoveryPlans, "/recovery")).toBe(false);
    expect(isItemActive(recovery, "/recovery")).toBe(true);

    expect(isItemActive(recoveryPlans, "/recovery/REC-101/plans")).toBe(true);
    expect(isItemActive(emergencyCases, "/recovery/REC-101/plans")).toBe(false);
  });
});
