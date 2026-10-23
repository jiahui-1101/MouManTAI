import { describe, expect, it } from "vitest";
import { isNavigationItemActive, navigation } from "./navigation";

describe("business navigation", () => {
  it("uses business labels and only links to existing destinations", () => {
    expect(navigation.map((item) => item.label)).toEqual([
      "Overview", "Activity", "Customer Inbox", "Orders", "Commitment Feasibility", "Recovery Case", "Communications",
    ]);
    expect(navigation.every((item) => !/\bP[1-5]\b/.test(item.label))).toBe(true);
  });

  it("keeps parent destinations active for existing deep links", () => {
    const commitments = navigation.find((item) => item.label === "Commitment Feasibility")!;
    const communications = navigation.find((item) => item.label === "Communications")!;
    expect(isNavigationItemActive(commitments, "/impact/fa_001")).toBe(true);
    expect(isNavigationItemActive(communications, "/confirmations/conf_001")).toBe(true);
    expect(isNavigationItemActive(communications, "/communications/follow-ups")).toBe(true);
  });

  it("keeps Orders active for order detail routes", () => {
    const orders = navigation.find((item) => item.to === "/orders");
    const inbox = navigation.find((item) => item.to === "/inbox");

    expect(orders).toBeDefined();
    expect(inbox).toBeDefined();

    expect(isNavigationItemActive(orders!, "/orders/123")).toBe(true);
    expect(isNavigationItemActive(inbox!, "/orders/123")).toBe(false);
  });
});
