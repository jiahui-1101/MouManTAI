import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CommitmentFeasibilityPage } from "./CommitmentFeasibilityPage";
import { ImpactDetailPage } from "./ImpactDetailPage";
import { createCoreOnlySource, FeatureDataError } from "./data";
import { createPreviewSource, previewFeasibility, previewImpact } from "./preview";
import type { FeasibilityView, P2DataSource } from "./models";

afterEach(cleanup);
beforeEach(() => vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-22T12:30:00+08:00")));
afterEach(() => vi.restoreAllMocks());
const copy = <T,>(value: T): T => structuredClone(value);
function source(view = copy(previewFeasibility)): P2DataSource {
  return { ...createPreviewSource(), mode: "public-api", loadFeasibility: async () => view };
}
function feasibility(adapter?: P2DataSource) {
  return render(<MemoryRouter initialEntries={["/commitments/com-001"]}>
    <Routes><Route path="/commitments/:id" element={<CommitmentFeasibilityPage source={adapter} />} /></Routes>
  </MemoryRouter>);
}
function impact(adapter?: P2DataSource) {
  return render(<MemoryRouter initialEntries={[`/impact/${previewImpact.impact_id}`]}>
    <Routes><Route path="/impact/:id" element={<ImpactDetailPage source={adapter} />} /></Routes>
  </MemoryRouter>);
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((r, fail) => { resolve = r; reject = fail; });
  return { promise, resolve, reject };
}

describe("FE-01", () => {
  it.each(["FEASIBLE", "CONDITIONAL", "INFEASIBLE", "UNKNOWN", "NOT_ASSESSED"] as const)("shows %s without changing Core risk/agreement", async (status) => {
    const view = copy(previewFeasibility);
    view.assessment!.status = status;
    const frozen = JSON.stringify(view);
    feasibility(source(view));
    expect(await screen.findByTestId("feasibility-status")).toHaveTextContent(status);
    expect(screen.getByText("CONFIRMED")).toBeInTheDocument();
    expect(screen.getByText("NORMAL")).toBeInTheDocument();
    expect(screen.getByText(view.commitment.order_id)).toBeInTheDocument();
    expect(screen.getByText(view.commitment.customer_id)).toBeInTheDocument();
    expect(screen.getByTestId("feasibility-status")).not.toHaveClass("status-pill");
    expect(JSON.stringify(view)).toBe(frozen);
  });
  it("shows time, versions, material units, fixed booking and exact evidence", async () => {
    feasibility(source());
    await screen.findByTestId("feasibility-status");
    expect(screen.getByText(previewFeasibility.assessment!.assessed_at)).toBeInTheDocument();
    expect(screen.getByText("Snapshot 2")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Material allocation at need time" });
    expect(within(table).getByText("PATTY")).toBeInTheDocument();
    expect(within(table).getAllByText(/pcs/).length).toBeGreaterThan(0);
    expect(screen.getByRole("table", { name: "Fixed production bookings" })).toHaveTextContent("100");
    expect(screen.getAllByText(/synthetic/).length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Evidence and assumptions" })).toHaveTextContent("synthetic-stock-patty-row");
  });
  it("renders a nullable Core deadline as not provided", async () => {
    const view = copy(previewFeasibility);
    view.commitment.terms.deadline = null;
    feasibility(source(view));
    await screen.findByTestId("feasibility-status");
    expect(screen.getByText("Not provided")).toBeInTheDocument();
  });
  it.each(["version", "stale", "incomplete", "timeout", "unverified freshness"])("keeps %s cautious even with a FEASIBLE historical result", async (kind) => {
    const view = copy(previewFeasibility);
    view.assessment!.status = "FEASIBLE";
    if (kind === "version") view.current_snapshot_version = 3;
    if (kind === "stale") view.details!.sources[0].status = "STALE";
    if (kind === "incomplete") view.details!.evidence_complete = false;
    if (kind === "timeout") view.assessment!.solver_status = "TIMEOUT";
    if (kind === "unverified freshness") view.details = null;
    feasibility(source(view));
    expect(await screen.findByTestId("feasibility-status")).toHaveTextContent("UNKNOWN");
    expect(screen.getByText(/Recorded assessment: FEASIBLE/)).toBeInTheDocument();
  });
  it("distinguishes missing assessment from missing public API", async () => {
    const view = copy(previewFeasibility); view.assessment = null; view.details = null;
    feasibility(source(view));
    expect(await screen.findByTestId("feasibility-status")).toHaveTextContent("NOT_ASSESSED");
    expect(screen.getByText(/No assessment available/)).toBeInTheDocument();
    cleanup(); feasibility();
    expect(await screen.findByRole("alert")).toHaveTextContent("public adapter");
    expect(screen.queryByText("com-001")).not.toBeInTheDocument();
  });
  it("labels preview and disables real recalculation", async () => {
    feasibility(createPreviewSource());
    await screen.findByTestId("feasibility-status");
    expect(screen.getByRole("note")).toHaveTextContent("Synthetic preview");
    expect(screen.getByRole("note")).toHaveTextContent("not persisted");
    expect(screen.getByRole("button", { name: "Recalculate" })).toBeDisabled();
    expect(screen.getByText(/persistence and authorization adapter/i)).toBeInTheDocument();
  });
  it("preserves old result during recalculation and sends expected versions", async () => {
    const pending = deferred<FeasibilityView>();
    const adapter = source(); adapter.recalculate = vi.fn(() => pending.promise);
    await act(async () => { feasibility(adapter); }); await screen.findByTestId("feasibility-status");
    fireEvent.click(screen.getByRole("button", { name: "Recalculate" }));
    expect(screen.getByRole("button", { name: /Recalculating/ })).toBeDisabled();
    expect(screen.getByText(/Previous assessment retained/)).toBeInTheDocument();
    expect(adapter.recalculate).toHaveBeenCalledWith("com-001", { expected_commitment_version: 1, expected_snapshot_version: 2 });
    const next = copy(previewFeasibility); next.assessment!.assessment_id = "new-assessment";
    await act(async () => pending.resolve(next));
    expect(screen.getByText("new-assessment")).toBeInTheDocument();
  });
  it("accepts a deterministic unchanged recalculation response", async () => {
    const adapter = source(); adapter.recalculate = async () => copy(previewFeasibility);
    await act(async () => { feasibility(adapter); }); await screen.findByTestId("feasibility-status");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Recalculate" })); });
    expect(await screen.findByText(/Assessment received/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("uses response receipt time for freshly assessed current evidence", async () => {
    const adapter = source();
    adapter.recalculate = async () => {
      vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-22T12:30:30+08:00"));
      const next = copy(previewFeasibility); next.assessment!.assessed_at = "2026-10-22T12:30:30+08:00";
      return next;
    };
    await act(async () => { feasibility(adapter); }); await screen.findByTestId("feasibility-status");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Recalculate" })); });
    await screen.findByText(/Assessment received/);
    expect(screen.getByTestId("feasibility-status")).toHaveTextContent("INFEASIBLE");
  });
  it("shows missing source timestamp bounds as UNKNOWN", async () => {
    const view = copy(previewFeasibility); view.details!.sources[0].observed_at = null;
    view.details!.sources[0].valid_through = null;
    feasibility(source(view));
    expect(await screen.findByTestId("feasibility-status")).toHaveTextContent("UNKNOWN");
    expect(screen.getByText("Observed UNKNOWN · valid through UNKNOWN")).toBeInTheDocument();
  });
  it.each([403, 409, 503])("retains prior result after HTTP %s and supports safe retry", async (status) => {
    const adapter = source();
    const first = deferred<FeasibilityView>(), retry = deferred<FeasibilityView>();
    adapter.recalculate = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(retry.promise);
    // Settle initial load and its effects before interacting. Control rejection
    // explicitly so both requests exercise pending -> error, including on CI.
    await act(async () => { feasibility(adapter); });
    await screen.findByTestId("feasibility-status");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Recalculate" })); });
    expect(screen.getByRole("button", { name: /Recalculating/ })).toBeDisabled();
    expect(screen.getByText(previewFeasibility.assessment!.assessment_id)).toBeInTheDocument();
    await act(async () => { first.reject(new FeatureDataError(status, "SERVER_REJECTED", "Request rejected")); });
    const message = `${status === 403 ? "Permission denied" : status === 409 ? "Version conflict" : "Request failed"} (${status}, SERVER_REJECTED): Request rejected`;
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByText(previewFeasibility.assessment!.assessment_id)).toBeInTheDocument();
    expect(screen.queryByText(/Assessment received/)).not.toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry recalculation" })); });
    expect(adapter.recalculate).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: /Recalculating/ })).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await act(async () => { retry.reject(new FeatureDataError(status, "SERVER_REJECTED", "Request rejected")); });
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByText(previewFeasibility.assessment!.assessment_id)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry recalculation" })).toBeEnabled();
    expect(screen.queryByText(/Assessment received/)).not.toBeInTheDocument();
    expect(adapter.recalculate).toHaveBeenNthCalledWith(1, "com-001", { expected_commitment_version: 1, expected_snapshot_version: 2 });
    expect(adapter.recalculate).toHaveBeenNthCalledWith(2, "com-001", { expected_commitment_version: 1, expected_snapshot_version: 2 });
  });
  it.each(["stale", "foreign tenant", "changed terms"])("does not replace prior assessment with %s response", async (kind) => {
    const next = copy(previewFeasibility);
    next.assessment!.assessment_id = "invalid-result";
    if (kind === "stale") next.current_snapshot_version = 9;
    if (kind === "foreign tenant") next.commitment.tenant_id = "foreign";
    if (kind === "changed terms") next.commitment.terms.quantity = "999";
    const adapter = source(); adapter.recalculate = async () => next;
    await act(async () => { feasibility(adapter); }); await screen.findByTestId("feasibility-status");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Recalculate" })); });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(previewFeasibility.assessment!.assessment_id)).toBeInTheDocument();
    expect(screen.queryByText("invalid-result")).not.toBeInTheDocument();
  });
  it("does not expose a foreign commitment on initial load", async () => {
    const view = copy(previewFeasibility); view.commitment.tenant_id = "foreign";
    feasibility(source(view));
    expect(await screen.findByRole("alert")).toHaveTextContent("403");
    expect(screen.queryByText(view.commitment.customer_id)).not.toBeInTheDocument();
  });
  it("loads Core through the supplied read port without inventing assessment data or writes", async () => {
    const read = vi.fn(async () => copy(previewFeasibility.commitment));
    feasibility(createCoreOnlySource(previewFeasibility.commitment.tenant_id, read));
    expect(await screen.findByTestId("feasibility-status")).toHaveTextContent("NOT_ASSESSED");
    expect(read).toHaveBeenCalledWith("com-001");
    expect(screen.getByRole("button", { name: "Recalculate" })).toBeDisabled();
  });
  it("shows loading and retries load failures without fixture fallback", async () => {
    const pending = deferred<FeasibilityView>(); const adapter = source();
    adapter.loadFeasibility = vi.fn().mockRejectedValueOnce(new FeatureDataError(503, "UNAVAILABLE", "Data unavailable")).mockReturnValueOnce(pending.promise);
    feasibility(adapter); expect(screen.getByRole("status")).toHaveTextContent("Loading");
    await screen.findByRole("alert"); fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    expect(screen.queryByText(previewFeasibility.commitment.customer_id)).not.toBeInTheDocument();
    await act(async () => pending.resolve(copy(previewFeasibility)));
    expect(screen.getByText(previewFeasibility.commitment.customer_id)).toBeInTheDocument();
  });
  it("ignores late data after switching tenant adapters", async () => {
    const pending = deferred<FeasibilityView>(); const old = source();
    old.loadFeasibility = () => pending.promise;
    const current = source(); current.tenantId = "another-tenant";
    current.loadFeasibility = async () => { throw new FeatureDataError(403, "DENIED", "Access denied"); };
    const result = render(<MemoryRouter><CommitmentFeasibilityPage source={old} /></MemoryRouter>);
    result.rerender(<MemoryRouter><CommitmentFeasibilityPage source={current} /></MemoryRouter>);
    await screen.findByRole("alert");
    await act(async () => pending.resolve(copy(previewFeasibility)));
    expect(screen.queryByText(previewFeasibility.commitment.customer_id)).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("403");
  });
  it("keeps keyboard-accessible scroll regions and semantic table headers", async () => {
    feasibility(source()); await screen.findByTestId("feasibility-status");
    expect(screen.getByRole("region", { name: "Scrollable materials" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("columnheader", { name: "Required" })).toHaveAttribute("scope", "col");
    expect(screen.getByRole("button", { name: "Recalculate" })).toHaveAccessibleName();
  });
});

describe("FE-02", () => {
  it("separates dependency candidates, confirmed impact, buffered unaffected, and missing evidence", async () => {
    impact(createPreviewSource());
    await screen.findByRole("heading", { name: "Operational impact detail" });
    const confirmed = screen.getByRole("region", { name: "Confirmed impacted commitments" });
    expect(confirmed).toHaveTextContent("com-001"); expect(confirmed).not.toHaveTextContent("com-002");
    expect(screen.getByRole("region", { name: "Verified unaffected commitments" })).toHaveTextContent("com-002");
    expect(screen.getByRole("region", { name: "UNKNOWN impact attribution" })).toHaveTextContent("com-missing");
    expect(screen.getByRole("table", { name: "Dependency evidence" })).toHaveTextContent("SUPPLIER_DELIVERY");
    expect(screen.getByText(/Snapshots 1 → 2/)).toBeInTheDocument();
    expect(screen.getByText(/Core risk change: unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Changed resources" })).toHaveTextContent("11:00");
    expect(within(confirmed).getByText(/0 → 40 pcs/)).toBeInTheDocument();
  });
  it("does not turn an empty affected set into verified unaffected candidates", async () => {
    const view = copy(previewImpact); view.impacts = []; // all candidates still need evidence
    const adapter = createPreviewSource(); adapter.loadImpact = async () => view;
    impact(adapter); await screen.findByRole("heading", { name: "Operational impact detail" });
    expect(screen.getByRole("region", { name: "Verified unaffected commitments" })).toHaveTextContent("None verified");
    expect(screen.getByRole("region", { name: "UNKNOWN impact attribution" })).toHaveTextContent("com-001");
  });
  it.each([403, 409, 503])("shows impact HTTP %s with retry and no synthetic fallback", async (status) => {
    const adapter = source(); adapter.loadImpact = vi.fn().mockRejectedValue(new FeatureDataError(status, "REJECTED", "Impact unavailable"));
    impact(adapter); expect(await screen.findByRole("alert")).toHaveTextContent(String(status));
    expect(screen.queryByText("com-002")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    await screen.findByRole("alert"); expect(adapter.loadImpact).toHaveBeenCalledTimes(2);
  });
  it("shows empty, loading and unavailable impact states", async () => {
    const adapter = source(); adapter.loadImpact = async () => null;
    impact(adapter); expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(await screen.findByText("No impact assessment available.")).toBeInTheDocument();
    cleanup(); impact(); expect(await screen.findByRole("alert")).toHaveTextContent("public adapter");
  });
  it("preserves UNKNOWN causal deltas, pre-existing constraints, deadline severity and evidenced Core risk separately", async () => {
    const view = copy(previewImpact);
    const unknown = copy(view.impacts[0]); unknown.classification = "UNKNOWN";
    unknown.reasons = ["UNATTRIBUTED_CONCURRENT_DEPENDENCY_CHANGE"];
    unknown.hard_constraint_deltas = [{ resource_id: "line-1", code: "CUSTOMER_DEADLINE_VIOLATION", before_shortage: "20", after_shortage: "30", unit: "minutes", deadline: "2026-10-23T12:30:00+08:00", severity_change: "WORSENED", evidence_refs: ["synthetic-deadline-row"] }];
    view.impacts[0] = unknown;
    view.impacts[1].classification = "PRE_EXISTING_UNCHANGED";
    view.impacts[1].risk_change = { before: "AT_RISK", after: "AT_RISK", evidence_refs: ["synthetic-core-audit-row"] };
    const adapter = createPreviewSource(); adapter.loadImpact = async () => view;
    impact(adapter); await screen.findByRole("heading", { name: "Operational impact detail" });
    const region = screen.getByRole("region", { name: "UNKNOWN impact attribution" });
    expect(region).toHaveTextContent("UNATTRIBUTED_CONCURRENT_DEPENDENCY_CHANGE");
    expect(region).toHaveTextContent("20 → 30 minutes · WORSENED");
    expect(region).toHaveTextContent("2026-10-23T12:30:00+08:00");
    expect(screen.getByRole("region", { name: "Pre-existing unchanged constraints" })).toHaveTextContent("com-002");
    expect(screen.getByRole("region", { name: "Confirmed impacted commitments" })).toHaveTextContent("None established");
    expect(screen.getByRole("region", { name: "Verified unaffected commitments" })).toHaveTextContent("None verified");
    expect(screen.getByText(/Core risk: AT_RISK → AT_RISK/)).toBeInTheDocument();
  });
});
