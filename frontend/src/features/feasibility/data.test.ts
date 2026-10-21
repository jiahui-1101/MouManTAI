import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assessmentCaution, validateFeasibility, validateImpact, validateRecalculation } from "./data";
import { previewFeasibility, previewImpact } from "./preview";
beforeEach(() => vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-22T12:30:00+08:00")));
afterEach(() => vi.restoreAllMocks());

describe("feature adapter boundary", () => {
  it("does not trust a CURRENT label beyond source validity", () => {
    const view = structuredClone(previewFeasibility);
    view.details!.sources[0].valid_through = "2026-10-20T00:00:00Z";
    expect(assessmentCaution(view)).not.toBeNull();
  });
  it("does not expose evidence-free verified unaffected classification", () => {
    const view = structuredClone(previewImpact);
    view.impacts[1].evidence_refs = [];
    const checked = validateImpact(view, view.impact_id, view.tenant_id)!;
    expect(checked.impacts[1].classification).toBe("UNKNOWN");
    expect(view.impacts[1].classification).toBe("VERIFIED_UNAFFECTED");
  });
  it("refuses duplicate or unrelated impact rows", () => {
    const view = structuredClone(previewImpact);
    view.impacts.push(view.impacts[0]);
    expect(() => validateImpact(view, view.impact_id, view.tenant_id)).toThrow(/binding|candidate/i);
  });
  it("rejects foreign tenant impact before display", () => {
    expect(() => validateImpact(previewImpact, previewImpact.impact_id, "foreign")).toThrow(/scope/);
  });
  it("validates assessment date and detail binding", () => {
    const view = structuredClone(previewFeasibility);
    view.assessment!.assessed_at = "bad-date";
    expect(() => validateFeasibility(view, "com-001", view.commitment.tenant_id)).toThrow(/metadata/);
    view.assessment!.assessed_at = previewFeasibility.assessment!.assessed_at;
    view.details!.snapshot_version = 99;
    expect(() => validateFeasibility(view, "com-001", view.commitment.tenant_id)).toThrow(/binding/);
  });
  it("accepts a valid new UNKNOWN response without promoting it to safe", () => {
    const next = structuredClone(previewFeasibility);
    next.assessment!.assessment_id = "new-unknown"; next.assessment!.status = "UNKNOWN";
    next.details!.evidence_complete = false;
    expect(validateRecalculation(next, previewFeasibility, next.commitment.tenant_id).assessment!.status).toBe("UNKNOWN");
    expect(assessmentCaution(next)).not.toBeNull();
  });
  it("accepts a version-bound deterministic repeat without requiring a different assessment ID", () => {
    expect(validateRecalculation(structuredClone(previewFeasibility), previewFeasibility, previewFeasibility.commitment.tenant_id)).toEqual(previewFeasibility);
  });
  it("expires a historical safe result at display time even without a snapshot change", () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-27T00:00:00+08:00"));
    expect(assessmentCaution(previewFeasibility)).not.toBeNull();
  });
});
