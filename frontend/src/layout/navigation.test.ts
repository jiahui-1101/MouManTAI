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
});
