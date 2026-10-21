/**
 * Live-API Smoke Test Suite (UI-06, UI-01, UI-02, UI-03).
 *
 * Gated by environment variable LIVE_API=1.
 * When LIVE_API=1 is set, this suite executes real HTTP network calls
 * against the live running FastAPI service (http://localhost:8000)
 * and the seeded synthetic test database.
 *
 * Pre-condition:
 *   Database reset and seeded via:
 *     python scripts/reset_and_seed_test_db.py
 *   FastAPI backend running via:
 *     uvicorn app.main:app --port 8000
 */

import { describe, expect, it } from "vitest";
import {
  confirmProposal,
  getCommitmentTimeline,
  getHealth,
  getOverview,
} from "../../shared/api";
import type { RequestAuthHeaders } from "../../shared/api";

declare const process: { env?: Record<string, string | undefined> };
const isLiveApi = typeof process !== "undefined" && process.env?.LIVE_API === "1";

describe.skipIf(!isLiveApi)("Live-API Smoke Suite (LIVE_API=1, UI-06)", () => {
  const ownerAuth: RequestAuthHeaders = {
    tenantId: "tenant_demo_01",
    actorId: "user_owner_01",
    correlationId: "corr_live_test_owner",
  };

  const staffAuth: RequestAuthHeaders = {
    tenantId: "tenant_demo_01",
    actorId: "user_staff_01",
    correlationId: "corr_live_test_staff",
  };

  it("GET /health returns 200 OK from live FastAPI backend", async () => {
    const health = await getHealth();
    expect(health.status).toBe("ok");
    expect(health.service).toBe("moumantai-api");
  });

  it("GET /v1/overview returns live DB-derived counts matching seeded synthetic state (UI-01)", async () => {
    const overview = await getOverview(ownerAuth);

    expect(overview.tenant_id).toBe("tenant_demo_01");
    expect(overview.actor_role).toBe("OWNER");
    expect(overview.integration_mode).toBe("SYNTHETIC");

    // Authoritative counts from database seed
    expect(overview.counts.requested).toBe(1);
    expect(overview.counts.confirmed).toBe(5);
    expect(overview.counts.at_risk).toBe(2);
    expect(overview.counts.pending_approval).toBe(1);
    expect(overview.counts.execution_in_progress).toBe(1);
    expect(overview.counts.awaiting_confirmation).toBe(1);
    expect(overview.counts.fulfilled).toBe(1);

    // Commitments list returned
    expect(overview.commitments.length).toBeGreaterThanOrEqual(7);
  });

  it("GET /v1/overview as Staff updates actor_role and sends X-Actor-ID correctly (UI-03)", async () => {
    const overview = await getOverview(staffAuth);

    expect(overview.tenant_id).toBe("tenant_demo_01");
    expect(overview.actor_id).toBe("user_staff_01");
    expect(overview.actor_role).toBe("STAFF");
  });

  it("GET /v1/commitments/com_001/timeline returns unbroken causal chain with correlation and causation IDs (UI-02)", async () => {
    const timeline = await getCommitmentTimeline("com_001", ownerAuth);

    expect(timeline.length).toBeGreaterThanOrEqual(5);

    // Causal chain: all entries share corr_hero_001
    const heroEntries = timeline.filter((e) => e.correlation_id === "corr_hero_001");
    expect(heroEntries.length).toBeGreaterThanOrEqual(5);

    // Causation link verified
    const linked = heroEntries.filter((e) => e.causation_id !== null && e.causation_id !== undefined);
    expect(linked.length).toBeGreaterThanOrEqual(4);

    // Version progression 1 to 9 present
    const versions = heroEntries.map((e) => e.commitment_version).filter(Boolean);
    expect(versions).toContain(1);
    expect(versions).toContain(9);
  });

  it("Staff role is strictly forbidden from executing proposal confirmation (403 Forbidden) (UI-03)", async () => {
    let errorCaught: any = null;

    try {
      await confirmProposal(
        "cmt_offered_01",
        {
          proposal_id: "prop_appr_001",
          proposal_version: 1,
          expected_commitment_version: 2,
          decision: "ACCEPT",
          evidence_refs: ["ev_cust_sign_unauthorized"],
          reason: "Staff unauthorized attempt",
        },
        staffAuth,
      );
    } catch (err) {
      errorCaught = err;
    }

    expect(errorCaught).not.toBeNull();
    expect(errorCaught.status).toBe(403);
    expect(errorCaught.code).toBe("APPROVAL_REQUIRED");
    expect(errorCaught.message).toContain("approval is required");
  });
});
