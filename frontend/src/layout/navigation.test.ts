import { describe, expect, it } from "vitest";
import { isNavigationItemActive, navigation } from "./navigation";

describe("business navigation", () => {
  it("uses business labels and only links to existing destinations", () => {
    expect(navigation.map((item) => item.label)).toEqual([
      "Overview", "Activity", "Customer Inbox", "Commitment Feasibility", "Recovery Case", "Communications",
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
});
