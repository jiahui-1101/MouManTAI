import { describe, expect, it, vi } from "vitest";
import type { Commitment, FeasibilityAssessment } from "../../shared/types";
import { FeatureDataError } from "./data";
import type { P2DataSource } from "./models";
import { previewFeasibility } from "./preview";

type P2Request = <T>(path: string, init?: RequestInit) => Promise<T>;
type ApiSourceModule = {
  createP2PublicApiSource: (tenantId: string, request: P2Request) => P2DataSource;
};

async function loadApiSource(): Promise<ApiSourceModule | undefined> {
  const modulePath = "./apiSource";
  try {
    return await import(modulePath) as ApiSourceModule;
  } catch {
    return undefined;
  }
}

const commitment = structuredClone(previewFeasibility.commitment) as Commitment;
const assessment = structuredClone(previewFeasibility.assessment) as FeasibilityAssessment;

function requestFor(responses: Record<string, unknown>) {
  const request = vi.fn(async <T,>(path: string, _init?: RequestInit) => {
    if (!(path in responses)) throw new Error(`Unexpected request: ${path}`);
    return responses[path] as T;
  });
  return request as unknown as P2Request & typeof request;
}

function minimalImpactResponse() {
  return {
    impact_id: "impact-1", tenant_id: commitment.tenant_id, event_id: "evt-1",
    correlation_id: "corr-1", event_type: "supplier.delivery_changed",
    before_snapshot_id: "snapshot-1", before_snapshot_version: 1,
    after_snapshot_id: "snapshot-2", after_snapshot_version: 2,
    discovery_complete: true, candidate_commitment_ids: ["com-001"],
    impacts: [{
      tenant_id: commitment.tenant_id, commitment_id: "com-001",
      before_commitment_version: 1, after_commitment_version: 1,
      before_snapshot_id: "snapshot-1", before_snapshot_version: 1,
      after_snapshot_id: "snapshot-2", after_snapshot_version: 2,
      classification: "UNKNOWN", verified_material_deterioration: false,
      before_assessment: null, after_assessment: null, material_deltas: [], hard_constraint_deltas: [],
      buffers: [], dependency_paths: [], evidence_refs: [], reasons: ["Source evidence unavailable."], event_intents: [],
    }],
    event_intents: [], calculation_input_digest: null,
    shared_assessment_status: "P2_LOCAL_ONLY_P5_FEASIBILITY_ASSESSMENT_ADAPTER_PENDING",
  };
}

describe("P2 public API source contract", () => {
  it("loads Core commitment and the latest assessment as historical when currentness is unavailable", async () => {
    const api = await loadApiSource();
    expect(api).toBeDefined();
    if (!api) return;

    const older = { ...assessment, assessment_id: "fa_older", assessed_at: "2026-10-20T10:00:00Z" };
    const newer = { ...assessment, assessment_id: "fa_newer", assessed_at: "2026-10-21T10:00:00Z" };
    const request = requestFor({
      "/v1/commitments/com-001": commitment,
      "/v1/commitments/com-001/assessments": [older, newer],
    });
    const source = api.createP2PublicApiSource(commitment.tenant_id, request);
    const view = await source.loadFeasibility(commitment.commitment_id);

    expect(view).toEqual({ commitment, assessment: newer, current_snapshot_version: null, details: null });
    expect(request.mock.calls.map(([path]) => path)).toEqual([
      "/v1/commitments/com-001",
      "/v1/commitments/com-001/assessments",
    ]);
    expect(request.mock.calls.every(([, init]) => init === undefined)).toBe(true);
    expect(source.recalculate).toBeUndefined();
  });

  it("maps canonical impact rows without inventing trigger values or Core risk changes", async () => {
    const api = await loadApiSource();
    expect(api).toBeDefined();
    if (!api) return;

    const response = {
      impact_id: "impact-1", tenant_id: commitment.tenant_id, event_id: "evt-1",
      correlation_id: "corr-1", event_type: "supplier.delivery_changed",
      before_snapshot_id: "snapshot-1", before_snapshot_version: 1,
      after_snapshot_id: "snapshot-2", after_snapshot_version: 2,
      discovery_complete: true, candidate_commitment_ids: ["com-001", "com-002"],
      impacts: [{
        tenant_id: commitment.tenant_id, commitment_id: "com-001",
        before_commitment_version: 1, after_commitment_version: 1,
        before_snapshot_id: "snapshot-1", before_snapshot_version: 1,
        after_snapshot_id: "snapshot-2", after_snapshot_version: 2,
        classification: "CONFIRMED_IMPACT", verified_material_deterioration: true,
        before_assessment: null, after_assessment: null,
        material_deltas: [{ kind: "MATERIAL_SHORTAGE", resource_id: "PATTY", line_id: "line-1",
          code: "MATERIAL_SHORTAGE", before_shortage: "0", after_shortage: "40", delta: "40",
          unit: "pcs", deadline: "2026-10-23T09:00:00+08:00", is_new: true,
          severity_change: "NEW", evidence_refs: ["ev-stock", "ev-eta"] }],
        hard_constraint_deltas: [], buffers: [],
        dependency_paths: [{ resource_key: { kind: "SUPPLIER_DELIVERY", resource_id: "delivery-1" },
          nodes: [{ kind: "SUPPLIER_DELIVERY", resource_id: "delivery-1" },
            { kind: "SKU", resource_id: "PATTY" }, { kind: "COMMITMENT", resource_id: "com-001" }],
          relationships: ["supplies", "required_by"], evidence_refs: ["ev-eta"] }],
        evidence_refs: ["ev-stock", "ev-eta"], reasons: ["Supplier ETA is after material need time."], event_intents: [],
      }],
      event_intents: [], calculation_input_digest: "digest-1",
      shared_assessment_status: "P2_LOCAL_ONLY_P5_FEASIBILITY_ASSESSMENT_ADAPTER_PENDING",
    };
    const request = requestFor({ "/v1/impacts/impact-1": response });
    const source = api.createP2PublicApiSource(commitment.tenant_id, request);
    const view = await source.loadImpact("impact-1");

    expect(view).toMatchObject({
      impact_id: "impact-1", tenant_id: commitment.tenant_id, before_snapshot_version: 1,
      after_snapshot_version: 2, candidate_commitment_ids: ["com-001", "com-002"],
      trigger_evidence_refs: [], changes: [],
    });
    expect(view?.impacts[0]).toMatchObject({
      commitment_id: "com-001", classification: "CONFIRMED_IMPACT",
      reasons: ["Supplier ETA is after material need time."],
      material_deltas: [{ resource_id: "PATTY", before_shortage: "0", after_shortage: "40",
        unit: "pcs", deadline: "2026-10-23T09:00:00+08:00", severity_change: "NEW", evidence_refs: ["ev-stock", "ev-eta"] }],
      dependency_paths: [{ nodes: [{ kind: "SUPPLIER_DELIVERY", resource_id: "delivery-1" },
        { kind: "SKU", resource_id: "PATTY" }, { kind: "COMMITMENT", resource_id: "com-001" }],
        relationships: ["supplies", "required_by"], evidence_refs: ["ev-eta"] }],
    });
    expect(view?.impacts[0].risk_change).toBeUndefined();
    expect(request).toHaveBeenCalledWith("/v1/impacts/impact-1");
  });

  it.each([
    ["tenant_id", "tenant-foreign", 403, "TENANT_MISMATCH"],
    ["after_snapshot_version", 3, 409, "IMPACT_BINDING_MISMATCH"],
  ])("rejects impact rows with conflicting %s", async (field, value, status, code) => {
    const api = await loadApiSource();
    expect(api).toBeDefined();
    if (!api) return;
    const response = minimalImpactResponse();
    Object.assign(response.impacts[0], { [field]: value });
    const source = api.createP2PublicApiSource(commitment.tenant_id, requestFor({
      "/v1/impacts/impact-1": response,
    }));

    await expect(source.loadImpact("impact-1")).rejects.toMatchObject({ status, code });
  });

  it.each([
    [403, "FORBIDDEN"], [409, "COMMITMENT_VERSION_CONFLICT"], [503, "P2_IMPACT_PERSISTENCE_NOT_CONFIGURED"],
  ])("preserves upstream status %i and code %s", async (status, code) => {
    const api = await loadApiSource();
    expect(api).toBeDefined();
    if (!api) return;
    const failure = Object.assign(new Error("Upstream request failed"), { status, code });
    const request = vi.fn(async () => { throw failure; }) as unknown as P2Request;
    const source = api.createP2PublicApiSource(commitment.tenant_id, request);

    await expect(source.loadImpact("impact-1")).rejects.toMatchObject({
      status, code, message: "Upstream request failed",
    } satisfies Partial<FeatureDataError>);
  });

  it("rejects cross-tenant impact and malformed history bindings", async () => {
    const api = await loadApiSource();
    expect(api).toBeDefined();
    if (!api) return;
    const foreign = { ...commitment, tenant_id: "tenant-foreign" };
    const source = api.createP2PublicApiSource(commitment.tenant_id, requestFor({
      "/v1/commitments/com-001": foreign,
      "/v1/commitments/com-001/assessments": [],
    }));
    await expect(source.loadFeasibility("com-001")).rejects.toBeInstanceOf(FeatureDataError);
  });
});
