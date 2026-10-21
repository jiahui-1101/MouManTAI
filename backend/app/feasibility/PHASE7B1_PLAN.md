# P2 Phase 7B-1 Integration Readiness Plan

> **For agentic workers:** Execute inline in the current approved feature branch. Use test-first cycles for every behavior change.

**Goal:** Adapt the existing P2 detail pages to the approved public GET contracts while preserving UNKNOWN currentness and missing trigger evidence until P5 supplies those fields.

**Architecture:** Add a P2-owned frontend data source that receives an application-supplied request transport, reads Core commitment and P2 assessment history/impact endpoints, and maps only response fields present in the canonical contracts. It will not create identity headers, synthesize operational facts, enable recalculation without a current-version response, or infer Core risk changes.

**Tech Stack:** React + TypeScript + Vitest; existing P2 Python/Pydantic API contracts; pytest for backend regression.

## Global Constraints

- Keep code changes under `backend/app/feasibility/` and `frontend/src/features/feasibility/`; update only P2-owned Phase 7 documents and the P2 log entry.
- Do not edit Core, auth, DB, shared contracts, application routes, P3, migrations, or P5-owned tests.
- Preserve `UNKNOWN` vs `INFEASIBLE`, exact P2 calculation results, tenant/version checks, and fail-closed production dependencies.
- Test doubles remain local to tests; no synthetic fixture fallback is wired to production.
- Do not claim authenticated API, durable writer, Core risk update, or E2E completion.

---

### Task 1: Add public response mapping tests

**Files:**
- Create: `frontend/src/features/feasibility/apiSource.test.ts`
- Modify: `frontend/src/features/feasibility/data.test.ts`

**Interfaces:**
- Consumes: shared `Commitment` and `FeasibilityAssessment` types plus the P2 Python `ImpactAssessment` response fields.
- Produces: expected mapping into `P2DataSource` presentation models with `current_snapshot_version: null`, `details: null`, and unavailable impact trigger values preserved as unavailable.

- [x] Test Core commitment plus historical assessment reads and select the latest assessed timestamp deterministically.
- [x] Test currentness remains unknown when no authoritative current snapshot version is supplied.
- [x] Test impact classifications, deltas, buffers and dependency paths map exactly, with no inferred trigger values or risk transition.
- [x] Test tenant/binding errors and upstream permission/conflict/unavailable errors retain their meaning.
- [x] Run the focused Vitest files and confirm the new cases fail because the adapter is absent.

### Task 2: Implement the P2 public data source

**Files:**
- Create: `frontend/src/features/feasibility/apiSource.ts`
- Modify: `frontend/src/features/feasibility/data.ts`

**Interfaces:**
- Consumes: an injected generic request function supplied later by P5's approved authenticated transport.
- Produces: `createP2PublicApiSource(tenantId, request): P2DataSource`; read routes are `GET /v1/commitments/{id}`, `GET /v1/commitments/{id}/assessments`, and `GET /v1/impacts/{id}`.

- [x] Map Core commitment and the latest version-bound historical assessment without promoting snapshot version to current authority.
- [x] Map only fields present in P2 `ImpactAssessment`; leave trigger source values and Core risk change unavailable.
- [x] Preserve HTTP status and domain error code as `FeatureDataError` for page-level permission/conflict/retry handling.
- [x] Do not attach headers, use preview fixtures, or expose `recalculate` until the approved response includes authoritative current version and detail.
- [x] Run focused Vitest files and confirm the new cases pass.

### Task 3: Validate and document Phase 7B-1 readiness

**Files:**
- Modify: `backend/app/feasibility/P2_REQUIREMENT_TRACE.md`
- Modify: `backend/app/feasibility/P2_PROGRESS.md`
- Modify: `backend/app/feasibility/P2_PHASE_REPORTS.md`
- Create: `backend/app/feasibility/PHASE7B1_INTEGRATION_READINESS.md`
- Modify: `docs/TEAM_LOG.md` (append P2-only entry)

**Interfaces:**
- Consumes: current Main/P3/P5 branch audit, existing focused tests, and final regression results.
- Produces: exact dependency matrix, P5/P3 contract requests, validation evidence, remaining 7B-2 work, and joint E2E order.

- [x] Run combined backend P2/P5 regressions and frontend tests, typecheck, and production build.
- [x] Record failures, warnings, skips and live DB/API/E2E tests that were not run without upgrading isolated evidence into production claims.
- [ ] Review changed paths and ownership; commit validated checkpoints and push only `origin/feat/p2-phase7b-integration`.
- [ ] Stop for independent review before joint production wiring or Phase 7B-2.
