import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { FeatureDataError, validateImpact } from "./data";
import { ImpactDetailPage } from "./ImpactDetailPage";
import type { ImpactView } from "./models";
import { createPreviewSource, previewImpact } from "./preview";

afterEach(cleanup);
function malformedPayload(): ImpactView {
  // JSON deliberately crosses the runtime boundary without trusting the TS union.
  const payload = JSON.parse(JSON.stringify(previewImpact));
  payload.impacts[1].classification = "UNSUPPORTED_UPSTREAM_VALUE";
  return payload;
}
// Legacy runtime metadata must not bypass the buffer-evidence gate.
function independentProof(view: ImpactView) {
  const assessment = {
    tenant_id: view.tenant_id, commitment_id: "com-002", status: "FEASIBLE" as const,
    solver_status: "COMPLETED" as const, evidence_complete: true,
    evidence_refs: ["synthetic-independent-full-recalculation"],
  };
  return { basis: "INDEPENDENT_RECALCULATION" as const,
    before: { ...assessment, snapshot_version: view.before_snapshot_version },
    after: { ...assessment, snapshot_version: view.after_snapshot_version },
  };
}
function mount(view: ImpactView) {
  const adapter = { ...createPreviewSource(), mode: "public-api" as const,
    loadImpact: vi.fn(async () => view) };
  render(<MemoryRouter initialEntries={[`/impact/${view.impact_id}`]}>
    <Routes><Route path="/impact/:id" element={<ImpactDetailPage source={adapter} />} /></Routes>
  </MemoryRouter>);
  return adapter;
}

describe("PH6-R1-01 runtime classification", () => {
  it("rejects the entire malformed JSON payload with an explicit contract error without mutation", () => {
    const payload = malformedPayload(), original = JSON.stringify(payload);
    expect(() => validateImpact(payload, payload.impact_id, payload.tenant_id)).toThrowError(FeatureDataError);
    try { validateImpact(payload, payload.impact_id, payload.tenant_id); }
    catch (error) { expect(error).toMatchObject({ status: 502, code: "INVALID_IMPACT_CLASSIFICATION" }); }
    expect(JSON.stringify(payload)).toBe(original);
  });
  it("shows a visible contract error and retry instead of silently omitting the candidate", async () => {
    const payload = malformedPayload(), original = JSON.stringify(payload);
    const adapter = mount(payload);
    expect(await screen.findByRole("alert")).toHaveTextContent("INVALID_IMPACT_CLASSIFICATION");
    expect(screen.queryByRole("region", { name: "Verified unaffected commitments" })).not.toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    await screen.findByRole("alert");
    expect(adapter.loadImpact).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(payload)).toBe(original);
  });
  it.each(["CONFIRMED_IMPACT", "VERIFIED_UNAFFECTED", "UNKNOWN", "PRE_EXISTING_UNCHANGED", "NO_NEW_ADVERSE_DELTA"] as const)("preserves supported classification %s", (classification) => {
    const view = structuredClone(previewImpact); view.impacts[1].classification = classification;
    expect(validateImpact(view, view.impact_id, view.tenant_id)!.impacts[1].classification).toBe(classification);
  });
});

describe("PH6-R1-02 buffer evidence", () => {
  it("labels an evidenced buffer without changing the supported classification or input", async () => {
    const view = structuredClone(previewImpact), original = JSON.stringify(view);
    mount(view);
    const region = await screen.findByRole("region", { name: "Verified unaffected commitments" });
    expect(region).toHaveTextContent("Verified buffer: PATTY · 20 pcs");
    expect(JSON.stringify(view)).toBe(original);
  });
  it.each([{ refs: [] }, { refs: ["   "] }])("downgrades buffer-dependent verification despite unrelated row refs when buffer refs are $refs", async ({ refs }) => {
    const view = structuredClone(previewImpact);
    view.impacts[1].buffers[0].evidence_refs = refs;
    view.impacts[1].evidence_refs = ["synthetic-unrelated-event-reference"];
    const original = JSON.stringify(view);
    const checked = validateImpact(view, view.impact_id, view.tenant_id)!;
    expect(checked.impacts[1].classification).toBe("UNKNOWN");
    expect(checked.impacts[1].reasons).toContain("UNAFFECTED_BUFFER_EVIDENCE_INSUFFICIENT");
    mount(view);
    const unknown = await screen.findByRole("region", { name: "UNKNOWN impact attribution" });
    expect(unknown).toHaveTextContent("com-002");
    expect(unknown).toHaveTextContent("Reported buffer — evidence unavailable: PATTY · 20 pcs");
    expect(within(unknown).queryByText(/Verified buffer:/)).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Verified unaffected commitments" })).toHaveTextContent("None verified");
    expect(JSON.stringify(view)).toBe(original);
  });
  it("does not let complete FEASIBLE/COMPLETED metadata override missing buffer evidence", async () => {
    const view = JSON.parse(JSON.stringify(previewImpact));
    view.impacts[1].buffers[0].evidence_refs = [];
    view.impacts[1].unaffected_proof = independentProof(view);
    const original = JSON.stringify(view);
    expect(validateImpact(view, view.impact_id, view.tenant_id)!.impacts[1].classification).toBe("UNKNOWN");
    mount(view);
    const region = await screen.findByRole("region", { name: "UNKNOWN impact attribution" });
    expect(region).toHaveTextContent("com-002");
    expect(region).toHaveTextContent("Reported buffer — evidence unavailable");
    expect(screen.getByRole("region", { name: "Verified unaffected commitments" })).toHaveTextContent("None verified");
    expect(JSON.stringify(view)).toBe(original);
  });
  it("does not let complete FEASIBLE/COMPLETED metadata override an empty buffer list", () => {
    const payload = JSON.parse(JSON.stringify(previewImpact));
    payload.impacts[1].buffers = [];
    payload.impacts[1].unaffected_proof = independentProof(payload);
    const original = JSON.stringify(payload);
    const result = validateImpact(payload, payload.impact_id, payload.tenant_id)!;
    expect(result.impacts[1].classification).toBe("UNKNOWN");
    expect(result.impacts[1].reasons).toContain("UNAFFECTED_BUFFER_EVIDENCE_INSUFFICIENT");
    expect(JSON.stringify(payload)).toBe(original);
  });
  it.each(["0", "0.000", "0E+30", "-1", "NaN", "Infinity", "invalid"])("does not use buffer value %s as positive proof despite complete metadata", (value) => {
    const payload = JSON.parse(JSON.stringify(previewImpact));
    payload.impacts[1].buffers[0].value = value;
    payload.impacts[1].unaffected_proof = independentProof(payload);
    const original = JSON.stringify(payload);
    expect(validateImpact(payload, payload.impact_id, payload.tenant_id)!.impacts[1].classification).toBe("UNKNOWN");
    expect(JSON.stringify(payload)).toBe(original);
  });
  it.each(["0.001", "1E-1000", "2E+1000"])("preserves positive evidence-backed decimal buffer %s without floating-point arithmetic", (value) => {
    const view = structuredClone(previewImpact); view.impacts[1].buffers[0].value = value;
    const original = JSON.stringify(view);
    expect(validateImpact(view, view.impact_id, view.tenant_id)!.impacts[1].classification).toBe("VERIFIED_UNAFFECTED");
    expect(JSON.stringify(view)).toBe(original);
  });
  it("does not let a supported positive buffer conceal missing evidence for another required buffer", () => {
    const view = structuredClone(previewImpact);
    view.impacts[1].buffers.push({ resource_id: "required-time-buffer", value: "30", unit: "minutes", evidence_refs: [] });
    const original = JSON.stringify(view);
    expect(validateImpact(view, view.impact_id, view.tenant_id)!.impacts[1].classification).toBe("UNKNOWN");
    expect(JSON.stringify(view)).toBe(original);
  });
  it("does not let metadata bypass missing row-level classification evidence", () => {
    const payload = JSON.parse(JSON.stringify(previewImpact));
    payload.impacts[1].evidence_refs = [];
    payload.impacts[1].unaffected_proof = independentProof(payload);
    const original = JSON.stringify(payload);
    expect(validateImpact(payload, payload.impact_id, payload.tenant_id)!.impacts[1].classification).toBe("UNKNOWN");
    expect(JSON.stringify(payload)).toBe(original);
  });
  it("cautiously renders a missing buffer evidence_refs field from runtime JSON", async () => {
    const payload = JSON.parse(JSON.stringify(previewImpact));
    delete payload.impacts[1].buffers[0].evidence_refs;
    const original = JSON.stringify(payload);
    mount(payload);
    const unknown = await screen.findByRole("region", { name: "UNKNOWN impact attribution" });
    expect(unknown).toHaveTextContent("com-002");
    expect(unknown).toHaveTextContent("Reported buffer — evidence unavailable");
    expect(JSON.stringify(payload)).toBe(original);
  });
  it.each(["CONFIRMED_IMPACT", "UNKNOWN", "PRE_EXISTING_UNCHANGED", "NO_NEW_ADVERSE_DELTA"] as const)("does not downgrade unrelated %s proof because a buffer lacks evidence", (classification) => {
    const view = structuredClone(previewImpact);
    view.impacts[1].classification = classification; view.impacts[1].buffers[0].evidence_refs = [];
    const original = JSON.stringify(view);
    expect(validateImpact(view, view.impact_id, view.tenant_id)!.impacts[1].classification).toBe(classification);
    expect(JSON.stringify(view)).toBe(original);
  });
  it.each(["missing evidence", "incomplete", "before incomplete", "wrong snapshot", "wrong tenant", "wrong commitment", "unresolved status", "unresolved solver"])("does not use %s as sufficient independent proof", (kind) => {
    const view = structuredClone(previewImpact); view.impacts[1].buffers[0].evidence_refs = [];
    const proof = independentProof(view);
    if (kind === "missing evidence") proof.after.evidence_refs = [];
    if (kind === "incomplete") proof.after.evidence_complete = false;
    if (kind === "before incomplete") proof.before.evidence_complete = false;
    if (kind === "wrong snapshot") proof.after.snapshot_version = 99;
    if (kind === "wrong tenant") proof.after.tenant_id = "foreign";
    if (kind === "wrong commitment") proof.after.commitment_id = "another-commitment";
    const payload = JSON.parse(JSON.stringify(view));
    payload.impacts[1].unaffected_proof = proof;
    if (kind === "unresolved status") payload.impacts[1].unaffected_proof.after.status = "UNKNOWN";
    if (kind === "unresolved solver") payload.impacts[1].unaffected_proof.after.solver_status = "UNKNOWN";
    const original = JSON.stringify(payload);
    expect(validateImpact(payload, payload.impact_id, payload.tenant_id)!.impacts[1].classification).toBe("UNKNOWN");
    expect(JSON.stringify(payload)).toBe(original);
  });
});
