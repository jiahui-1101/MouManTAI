# P2 Phase 7B-1 — Integration Readiness

**Date:** 2026-10-21
**State:** P2-local readiness work validated; production integration remains blocked on P5 and P3 contracts.
**Approved Main:** `03d5928e060271585a617afb3733b83732e6d4cd` (PR #5 merge; approved Phase 7A and post-review history-integrity implementation included).
**P2 branch:** `feat/p2-phase7b-integration`, created from that exact Main SHA.
**Read-only refs inspected:** P3 `ca7517c7c09390f0926d01825e689dbf1a8c8ca6`; P5 `5823db8c89d509243f904d988f865a6777ea6c4a`.
**Validated checkpoint:** `1507b5918b8ea9200aba4edca9b618929386e1fd`, pushed only to `origin/feat/p2-phase7b-integration`; remote ref matched at push time.

No feasibility or impact calculation engine was rewritten. This report records local adapters and test doubles separately from real authenticated/database/API integration.

## P2-owned changes

- Added `createP2PublicApiSource` in `frontend/src/features/feasibility/apiSource.ts`. It reads the existing Core commitment, P2 assessment-history, and P2 impact endpoints through an injected request function. It adds no identity headers and is not wired into the P5 application shell.
- The feasibility projection selects the latest returned assessment by `assessed_at`, validates tenant/commitment binding, and sets `current_snapshot_version` and detailed operational rows to unavailable. It does not treat an assessment's own snapshot version as current authority; recalculation remains unavailable.
- The impact projection maps P2 classifications, deltas, buffers, evidence, and dependency paths. It checks tenant and before/after snapshot bindings. It leaves trigger evidence/value changes empty because the current P2 `ImpactAssessment` response does not include the original change values; the page presents those fields as unavailable. It does not infer Core risk transitions from P2 event intents.
- API errors carrying an HTTP status and domain code are converted to P2 `FeatureDataError` so 403, 409, and 503 remain visible to page error handling.
- Added a `SERVICE`/`SYSTEM` role gate to `/internal/feasibility/evaluate` before authority resolution. An ordinary caller now receives 403. The injectable dependency still defaults to `None` and returns 503; the role check does not authenticate a context. P5 must create the context server-side and must not derive it from client headers.
- Added focused frontend contract tests and a router regression using separate requester and internal-service contexts. No synthetic preview is wired as a production fallback.

The TypeScript impact response projection is local to P2 and mirrors the fields consumed from P2's current Pydantic `ImpactAssessment`. P5 still needs to approve the mounted public response and supply the app's authenticated transport. Main has no checked-in P2 OpenAPI-derived TypeScript contract.

## Dependency matrix

| Classification | Surface | Current Main evidence | Remaining work |
|---|---|---|---|
| Already implemented and reusable | Feasibility calculation | `evaluate(EvaluationSnapshot, ProposedChanges \| None, Commitment) -> EvaluationResult`; deterministic ATP/BOM/capacity and evidence precedence | Reuse unchanged for assessment and P3 proposals. |
| Already implemented and reusable | Supplier impact calculation | `recalculate_supplier_delay` validates complete before/after inputs and delegates candidate calculations to the existing evaluator; complete synthetic case distinguishes `com-001` impacted from buffered `com-002` | P5 must provide trusted before/after source snapshots and execute this P2 flow in its processor. |
| Already implemented and reusable | Canonical assessment mapping/history reference | `history.to_core_assessment` preserves P2 result fields and the actual Impact Set, including an empty list; `SyntheticHistoryRepository` verifies complete calculations and replay | The repository is process-local reference behavior, not durable history or production authority. |
| Already implemented and reusable | Supported P5 stock read | `get_resource_snapshot` and `read_resource_summary` preserve exact totals, reservations, availability, unit, per-resource version, and timestamp; missing rows/fields remain `INCOMPLETE` or `UNAVAILABLE` | It cannot produce an `EvaluationSnapshot`: no lots/owners, BOM, confirmed receipt provenance, competing demand, production ledger/calendar, source freshness or atomic global read token. No safe P2 snapshot assembly is possible from this interface alone. |
| P2-owned and implementable now | P2 response mapping and contract validation | `apiSource.ts`, `test_apiSource` cases, existing shared Core types and P2 projection models | Ready for P5 transport/mount review. Current-version/detail and impact trigger fields still need an approved API response. |
| P2-owned and implementable now | Internal route role check | `router.py`; `test_internal_evaluate_rejects_untrusted_requester_before_authority_or_solver` | P5 must supply an authenticated server-created SERVICE/SYSTEM context; a role string alone is not proof of identity. |
| Requires P5 interface confirmation/implementation | Production router | P2 router defines the five P2 endpoints; `backend/app/main.py` includes Core only | P5 mounts P2 routes and verifies no method/path collision and shared error handling. |
| Requires P5 interface confirmation/implementation | Requester and SERVICE identity | Core `RequestContext` on Main is demo header-derived; P2 internal context provider defaults to `None`; Core internal writer accepts `SERVICE`/`SYSTEM` | Server-authenticate requester and tenant; separately create a trusted SERVICE identity; preserve requester and service identities in audit. Never trust a client-supplied role header. |
| Requires P5 interface confirmation/implementation | Authoritative snapshot/version | `get_resource_snapshot` returns per-resource versions only; P2 `EvaluationInputAuthority` is unconfigured | Resolve current tenant/commitment terms and complete trusted `EvaluationSnapshot`; return or verify an atomic current-version token and freshness/evidence bounds. Incomplete/stale data must remain UNKNOWN or fail closed. |
| Requires P5 interface confirmation/implementation | Assessment writer/history | P2 `AssessmentWriter` and `AssessmentHistoryReader` are ports with `None` defaults. Core `CommitmentService.assess` has tenant/version/idempotency/state guards and an atomic Core audit/outbox operation for a supplied shared assessment. | Implement the P5 transaction adapter around the exact P2-produced `EvaluationResult`: recheck commitment and snapshot versions, map via the approved P2 mapper, persist immutable history, transition Core, and commit audit/outbox together. Do not independently recalculate or alter P2 output. Implement tenant-scoped durable history reads. |
| Requires P5 interface confirmation/implementation | Supplier delay / impact persistence | P2 `SupplierDelayProcessor` and `ImpactReader` are unconfigured. The pure P2 pipeline does not commit source state or publish events. | Verify supplier/source evidence; resolve current before-state; create the authoritative after-state; run P2's existing impact function; atomically persist impact/history, permitted Core risk transitions, audit and outbox. Same event and payload must be idempotent; changed payload or stale/out-of-order source version must conflict. |
| Requires P5 interface confirmation/implementation | Frontend transport/details/routes | P2 pages exist; P5 `frontend/src/App.tsx` still mounts placeholders. The shared request helper uses demo identity headers and is not approved authenticated transport. | Provide approved authenticated request function and mount P2 pages. Supply current snapshot version and detailed source/material/operation projections for feasibility currentness; supply original trigger change values/evidence for impact. The new P2 source remains injectable and does not set headers. |
| Requires P3 confirmation | Hypothetical evaluator handoff | Main has the P2 pure `evaluate` function and typed `EvaluationSnapshot` / `ProposedChanges`; no P3 implementation is merged. Read-only P3 `ca7517c` adds `P2FeasibilityEvaluatorAdapter` that accepts the evaluator function and requires an authoritative `VersionedSnapshot`. Its older `P2FeasibilityAdapter` expects an object method plus metadata reference/dictionary input and is not compatible with the P2 production signature. | P3 owner confirms which adapter is used, authoritative snapshot construction, typed proposal serialization, and result/version binding. No P3 runtime call was tested from Main. |
| Requires joint E2E | Supplier delay → Core risk → Dashboard | P5 overview reads Core state; no production P2 writer/processor is configured and P2 routes/pages are not mounted. | Run the joint sequence below against authenticated app routes and a persistent isolated DB, then use the real P2 impact page and P5 dashboard. |

Unmerged branch comparison: P3 `ca7517c` is not in Main. The P5 branch tip inspected at `5823db8` has unmerged CI/DevEx, Docker/seed, and documentation changes; no additional P2 writer, source-authority, supplier processor, or authenticated P2 UI adapter was found there. No branch code was treated as Main implementation, and no P3/P5 owner response is recorded by this audit.

## Exact P5 inputs and outputs to approve

1. **Mounting:** include the P2 router in `backend/app/main.py`; retain P2 ownership of `POST /v1/commitments/{id}/assess`; verify combined route uniqueness and the `DomainError`/validation response envelope.
2. **Trusted identity:** `get_request_context` supplies the authenticated requester/tenant. A separate P5-controlled `get_internal_request_context` supplies SERVICE/SYSTEM to internal evaluation. The requester cannot self-select SERVICE, SYSTEM, `actor_role`, or `tenant_id`.
3. **Authoritative input:** `EvaluationInputAuthority.resolve_current(context, commitment_id, expected_commitment_version) -> (EvaluationSnapshot, Commitment)` returns only current, complete, tenant-bound input. It verifies canonical Core terms/version, operational snapshot current version, source trust/freshness and evidence bindings. It does not promote the aggregate stock summary to a complete snapshot.
4. **Assessment writer:** `AssessmentWriter.assess(db, requester_context, commitment, request, snapshot=snapshot, result=result) -> FeasibilityAssessment` receives the exact P2 result. Within one transaction it rechecks source and commitment versions, maps the result without recalculation or semantic changes, appends immutable assessment history, applies the allowed Core transition, and writes audit/outbox. Any failure rolls back all of those writes.
5. **Supplier processor:** `SupplierDelayProcessor.process(db, requester_or_verified_event_context, request) -> ImpactAssessment` validates event identity, tenant, delivery/source evidence and before version; resolves complete before/after snapshots and commitment sets; calls the existing P2 supplier recalculation; stores the result and emits only supported intents in the same transaction as source version, Core risk, audit and outbox changes. Exact caller identity and event-processor auth need P5 agreement.
6. **Durable reads:** `AssessmentHistoryReader.list_for_commitment(db, context, commitment_id) -> list[FeasibilityAssessment]` and `ImpactReader.get(db, context, impact_id) -> ImpactAssessment` are tenant-scoped and stably ordered/bound. P2's API source also needs an approved feasibility-detail response carrying current snapshot authority and optional detail rows; historical assessment version alone is insufficient.
7. **Frontend:** P5 supplies the approved authenticated request transport to `createP2PublicApiSource`, mounts `CommitmentFeasibilityPage` and `ImpactDetailPage`, and preserves 403/409/503. The impact API needs the original source change/evidence if the UI is to show before/after values. Core risk-change display must come from a persisted Core transition/audit read.

## Integration test preparation and coverage

| Scenario | Existing or new executable evidence | Evidence boundary |
|---|---|---|
| Valid recalculation | `test_supplier_pipeline.py`, `test_impact.py`, `test_router.py` | Pure engine and injected authority/writer tests; no persistent production writer. |
| Impacted plus buffered-unaffected commitments | `test_supplier_pipeline.py::test_complete_buffered_pipeline_replays_without_mutation`, `test_impact.py::test_complete_supplier_recalculation_confirms_new_shortage_and_buffered_commitment` | Synthetic complete snapshots; confirms one impacted and one buffered case without a second calculator. |
| Missing/stale evidence; no false safe result | `test_supplier_pipeline.py`, `test_impact.py`, `test_service.py`, frontend `data.test.ts` / `impact-safety.test.tsx` | Synthetic/stale inputs remain UNKNOWN; no real source evidence. |
| Tenant/version conflicts | `test_router.py`, `test_supplier_pipeline.py`, P5 `test_assess_identity_guards.py` | Isolated SQLite and injected contexts/providers. |
| Untrusted caller | New P2 `test_internal_evaluate_rejects_untrusted_requester_before_authority_or_solver`; P5 `test_normal_users_cannot_invoke_internal_writer` | Verifies role rejection; authenticated identity still requires P5. |
| Idempotent supplier event | `test_supplier_pipeline.py`, `test_history.py`, `test_impact.py` replay/conflict cases | Process-local reference replay only; durable inbox/outbox remains P5. |
| Failed writer/outbox behavior | P2 `test_assess_passes_authoritative_p2_result_to_writer_without_claiming_persistence`; P5 `test_outbox_failure_rolls_back_state_and_audit` | P2 surfaces writer failure; P5 Core rollback is tested directly. Their joint transaction is not implemented/tested. |
| No fixture fallback in production UI | New `data.test.ts` check for `requireSource(undefined)`; current App routes remain P5 placeholders | Missing source fails closed. No production P2 page is mounted. |

P2/P5 local doubles use an in-memory SQLite Core DB, explicit FastAPI dependency overrides, a deterministic P2 synthetic snapshot, and injected writers/readers. They do not establish authentication, PostgreSQL durability/migrations, P5 transaction composition, live HTTP, browser routing, or P3 execution.

## Recommended joint E2E execution order

1. P5 supplies an isolated persistent test DB and server-authenticated requester/service contexts; seed the agreed synthetic tenant with two confirmed commitments, full source evidence, material/BOM/production data, and the initially confirmed supplier delivery.
2. Through the production-mounted P2 supplier-delay endpoint, submit one verified ETA-change event. Assert the event input and after-snapshot are authoritative and version-bound; P2 returns `com-001` as confirmed impacted and `com-002` as verified buffered-unaffected.
3. In the same transaction, P5 persists the exact P2 impact/history, transitions only the confirmed impacted commitment to `AT_RISK`, writes immutable audit and outbox, and advances the source version. Read back the impact and assessment history using tenant-scoped P2 APIs.
4. Assert an identical event replay does not repeat the Core transition or outbox event; altered payload, wrong tenant, stale before-version, missing evidence and a normal user attempting the internal evaluator are rejected with the agreed 403/404/409/422 responses.
5. Inject writer/audit/outbox failure and verify source version, P2 history, Core risk, audit, and outbox all roll back. Confirm buffered commitment stays `NORMAL` and no UNKNOWN/missing/stale result is promoted to FEASIBLE or VERIFIED_UNAFFECTED.
6. Open the mounted P2 impact and commitment pages through the authenticated frontend transport, then the real P5 `/overview` dashboard. Verify loading/permission/conflict/unavailable states, exact evidence, no fixture fallback, and the Core risk update.

The repo's open `BLOCK-20261021-001` says live PostgreSQL migration/smoke validation is unavailable while Docker exposes WSL1. Use a P5-approved isolated test DB or resolve that environment blocker before calling this real DB/API E2E.

## Validation actually run

- `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_router.py -q -p no:cacheprovider` (from `backend/`) — **25 passed**, one existing Starlette/httpx deprecation warning.
- `python -B -m pytest -o 'addopts=' app/feasibility/tests -q -p no:cacheprovider` — **229 passed**, one same warning.
- `python -B -m pytest -o 'addopts=' tests -q -p no:cacheprovider` — **79 passed**, one same warning.
- `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — **308 passed**, one same warning.
- `python -B -m app.feasibility.demo` — **exit 0**; output labels itself `SYNTHETIC_P2_PIPELINE` and `process-local reference only; nothing published`.
- `npm.cmd test -- --run src/features/feasibility/apiSource.test.ts src/features/feasibility/data.test.ts` — **18 passed**.
- `npm.cmd test` — **118 passed, 5 skipped**; one gated live-API test file remains skipped; Vitest also emitted its jsdom worker performance advisory.
- `npm.cmd run typecheck` — **exit 0**.
- `npm.cmd run build` — **exit 0**, Vite transformed 94 modules and generated production assets.

No live PostgreSQL, migration, authenticated API, production P2 route/page, browser UI, durable P2 writer, or joint P2/P5/P3 E2E was run. These results are local regression/contract evidence only.

## Remaining Phase 7B-2 and review gate

- Get P5 approval/implementation for the exact interfaces above, then mount routes and wire the approved authenticated transport/details.
- Get P3 confirmation for the typed authoritative evaluator call; do not adapt to its legacy metadata-only interface.
- Prepare an isolated DB-backed test harness and execute the ordered joint journey plus rollback/replay/tenant/version negatives.
- Stop here for independent review. Do not begin 7B-2 or shared production wiring until separately approved.
