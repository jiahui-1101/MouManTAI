import { describe, expect, it } from "vitest";
import { isItemActive, navigation } from "./navigation";

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

  it("keeps Orders active for order detail, portfolio and calendar routes", () => {
    const orders = navigation.find((item) => item.id === "orders");
    const inbox = navigation.find((item) => item.id === "inbox");

    expect(orders).toBeDefined();
    expect(inbox).toBeDefined();

    expect(isItemActive(orders!, "/orders/123")).toBe(true);
    expect(isItemActive(orders!, "/orders/portfolio")).toBe(true);
    expect(isItemActive(orders!, "/orders/calendar")).toBe(true);

    expect(isItemActive(inbox!, "/orders/123")).toBe(false);
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
