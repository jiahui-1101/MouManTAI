import type { FeasibilityView, ImpactView, P2DataSource } from "./models";

// Authored synthetic presentation examples based on the existing buffered P2 fixture.
// They are NOT persisted assessments, measured production data, or a public response contract.
const deadline = "2026-10-24T15:00:00+08:00";
const refs = ["synthetic-stock-patty-row", "synthetic-supplier-eta-row"];
export const previewFeasibility: FeasibilityView = {
  commitment: {
    tenant_id: "tenant-synthetic-p2", commitment_id: "com-001", commitment_version: 1,
    order_id: "order-com-001", customer_id: "customer-com-001",
    terms: { sku: "BURGER", quantity: "100", unit: "pcs", deadline },
    agreement_state: "CONFIRMED", feasibility_state: "NOT_ASSESSED", risk_state: "NORMAL",
    recovery_state: "NONE", fulfilment_state: "NOT_STARTED", evidence_refs: ["synthetic-confirmation-row"], updated_at: "2026-10-22T12:00:00+08:00",
  },
  assessment: {
    tenant_id: "tenant-synthetic-p2", commitment_id: "com-001", commitment_version: 1,
    assessment_id: "synthetic-preview-assessment-2", snapshot_version: 2,
    status: "INFEASIBLE", solver_status: "COMPLETED", assessed_at: "2026-10-22T12:30:00+08:00",
    affected_commitment_ids: ["com-001"], evidence_refs: refs,
    constraints: [{ code: "MATERIAL_SHORTAGE", resource_id: "PATTY", shortage: "40", unit: "pcs", deadline: "2026-10-23T09:00:00+08:00", severity: "HARD", evidence_refs: refs }],
    assumptions: ["Supplied fixed bookings only; INFEASIBLE does not prove all reschedules impossible.", "Synthetic receipt remains confirmed incoming, not goods received."],
  },
  current_snapshot_version: 2,
  details: {
    commitment_id: "com-001", commitment_version: 1, snapshot_version: 2, evidence_complete: true,
    sources: [{ source_id: "synthetic-inventory", source_ref: "synthetic://p2/inventory/patty-row", observed_at: "2026-10-22T12:30:00+08:00", valid_through: "2026-10-26T00:00:00+08:00", status: "CURRENT", evidence_refs: refs }],
    materials: [{ line_id: "line-001", sku_id: "PATTY", required: "100", usable: "60", reserved: "0", confirmed_incoming: "0", shortage: "40", unit: "pcs", needed_by: "2026-10-23T09:00:00+08:00", evidence_refs: refs }],
    operations: [{ line_id: "line-001", resource_ids: ["synthetic-line-1"], start_at: "2026-10-23T09:00:00+08:00", finish_at: "2026-10-23T10:40:00+08:00", required_minutes: "100", available_minutes: "600", evidence_refs: ["synthetic-calendar-row", "synthetic-fixed-plan-row"] }],
  },
};
export const previewImpact: ImpactView = {
  impact_id: "synthetic-impact-2", tenant_id: "tenant-synthetic-p2", event_id: "synthetic-eta-event",
  event_type: "supplier.delivery_changed", before_snapshot_version: 1, after_snapshot_version: 2,
  discovery_complete: false, // extra presentation-only candidate demonstrates missing evidence
  candidate_commitment_ids: ["com-001", "com-002", "com-missing"], trigger_evidence_refs: [refs[1]],
  changes: [{ kind: "SUPPLIER_DELIVERY", resource_id: "delivery-patty-001", before: "2026-10-23T08:00:00+08:00", after: "2026-10-23T11:00:00+08:00", evidence_refs: [refs[1]] }],
  impacts: [{
    commitment_id: "com-001", classification: "CONFIRMED_IMPACT", reasons: ["Evidence-backed material deterioration in synthetic complete-production example"],
    material_deltas: [{ resource_id: "PATTY", before_shortage: "0", after_shortage: "40", unit: "pcs", deadline: "2026-10-23T09:00:00+08:00", severity_change: "NEW", evidence_refs: refs }],
    hard_constraint_deltas: [], buffers: [], evidence_refs: refs,
    dependency_paths: [{ nodes: [
      { kind: "SUPPLIER_DELIVERY", resource_id: "delivery-patty-001" }, { kind: "SKU", resource_id: "PATTY" },
      { kind: "PRODUCTION_PLAN", resource_id: "synthetic-fixed-plan" }, { kind: "ORDER", resource_id: "order-com-001" }, { kind: "COMMITMENT", resource_id: "com-001" },
    ], relationships: ["supplies", "required_by", "produces_for", "commits"], evidence_refs: refs }],
  }, {
    commitment_id: "com-002", classification: "VERIFIED_UNAFFECTED", reasons: ["Buffered synthetic booking remains feasible"],
    material_deltas: [], hard_constraint_deltas: [], buffers: [{ resource_id: "PATTY", value: "20", unit: "pcs", evidence_refs: refs }], dependency_paths: [], evidence_refs: refs,
  }],
};
export function createPreviewSource(): P2DataSource {
  return { mode: "synthetic-preview", tenantId: "tenant-synthetic-p2",
    loadFeasibility: async () => structuredClone(previewFeasibility),
    loadImpact: async () => structuredClone(previewImpact),
  };
}
