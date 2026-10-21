# P2 Feasibility & Impact Progress

## Current checkpoint

- **Phase:** 5 only — P2 API router and controlled P3/P5 handoff.
- **State:** PARTIAL. P2-owned typed routes and local API boundary tests are implemented. The internal pure evaluator route delegates to the existing `evaluate()` and fails closed unless P5 supplies internal authorization and authoritative input resolution. Assessment persistence/history, supplier-event/outbox processing, impact persistence, and production router registration remain BLOCKED on P5 interfaces. No Phase 6 work has started.
- **Branch:** feat/p2-feasibility-engine.
- **Approved Phase 4 baseline:** user approved correction commit `f6ac87233534f0dc6deef3b5e464e0bd7fd1fd0e`; local and `origin/feat/p2-feasibility-engine` matched, with a clean worktree before Phase 5.
- **Scope:** P2-owned API schemas, dependency ports, locally testable router, focused API tests, and P2 handoff/tracking documentation. `backend/app/main.py`, Core schemas/services/models, DB migrations, and frontend were not edited.
- **Validation:** Phase 5 focused router tests: 16 passed. Combined P2 Phase 1–4 and shared backend regressions: 180 passed with one existing Starlette/httpx deprecation warning. The tests mount the P2 router in a local test app and do not prove P5 app registration or production authorization.
- **Interface:** app.feasibility.service.evaluate(EvaluationSnapshot, ProposedChanges | None, app.core.schemas.Commitment) -> P2-local EvaluationResult. Uses actual Core enums/ConstraintReason; does not fabricate affected IDs or claim to return FeasibilityAssessment. See PHASE3_HANDOFF.md.
- **Impact semantics:** candidate discovery and measured material deterioration do not establish that the triggering event caused an impact. Graph parent-child relationships never substitute for atomic event scope: an undeclared job or lot remains a possible confounder even when it uses a declared resource or SKU, and its evidence ref alone does not expand event scope. A relevant undeclared concurrent dependency change makes adverse attribution UNKNOWN and cannot produce an at-risk intent. Deadline violations use evidence-backed lateness from evaluator finish times plus explicit lead time; improvements and unchanged violations do not become new impact. Allocation-policy-only shortages remain UNKNOWN while `verified_material_deterioration` exposes measured material deltas. Missing/stale evidence remains UNKNOWN. A failed fixed booking does not prove all reschedules impossible.
- **Impact purity:** `evaluate()` remains a version-bound pure calculation; impact processing evaluates every candidate before and after without changing inventory, reservations, jobs, commitment terms, risk or fulfilment state. Resource-keyed paths preserve source evidence, versions and deterministic ordering. Event envelopes are in-memory P2-local intents only; no publish/persist/outbox work.
- **Proposal purity:** version-bound target quantity/deadline/start proposals use a validated private copy and same batch ATP/BOM. Newly displaced competing material demand rejects a proposal. No stock/job/reservation/terms/Core lifecycle writes.
- **P5 contract verification:** fetched `origin/main` at `4ec2ba1ef7ede4a67352631178a73a6882bcd774`; its `FeasibilityAssessment.affected_commitment_ids` still has `min_length=1`. A focused P2 test confirms nonempty serialization succeeds and `[]` is rejected. Do not fabricate IDs, edit P5 schemas, or merge Main. The shared response adapter remains BLOCKED.
- **Assessment boundary:** the assessment route requires P5's current snapshot authority, runs the existing pure `evaluate(snapshot, None, commitment)`, then hands the exact P2 `EvaluationResult` and snapshot to the writer. P2 tests prove the handoff and reject missing/stale current snapshot versions; the writer must recheck versions transactionally. No persistence adapter is configured, so assessment still returns 503.
- **Security limitation:** P5 `get_request_context()` still derives tenant and actor IDs from caller-supplied headers. Public P2 route tests verify scope against the resolved context, but this is demo plumbing, not authenticated identity or production tenant authorization. The internal route returns 503 until P5 supplies an approved caller boundary.
- **Route registration:** P2 router is intentionally not included in P5-owned `backend/app/main.py`. Locally mounted router tests do not prove production route registration, authentication, or E2E integration.
- **P3 handshake:** P2's `evaluate(snapshot, proposed_changes, commitment)` Python signature and `ProposedChanges` fields match the P3 requirements. The P2 HTTP request/response shape is documented as provisional; P3 owner confirmation is still required. No P3 code changed.
- **Environment:** Python 3.14.3, Pydantic 2.13.4, pytest 9.1.1 (outside P5 >=8.3,<9). No dependency changes. Existing seven shared tests use SQLite, not live PostgreSQL.
- **Instructions discrepancy:** requested `docs/AGENTS.md` is missing. The repository root `AGENTS.md` was read, and the current user supplied the MouManTAI instructions in full; the root file itself still uses the old PromiseFlow name. The canonical system requirements, TEAM_LOG ADR-010, and current user instructions identify MouManTAI. No instruction file was guessed or edited.
- **Git:** local commit and feature-only push were explicitly authorized; final SHA/ref/clean-state evidence is in the phase response. No merge, force-push, Main modification, or P5-owned file change.
- **Gate:** STOP for independent Phase 5 external review. Phase 6 is not started.

## Repository baseline

Historical baseline: Phase 0 started on `main` at `aedb152`; Phase 1 started at `5368e0d` without a shared skeleton. Safety sync imports Main `4ec2ba1ef7ede4a67352631178a73a6882bcd774`: P5 FastAPI/Vite foundation, shared schemas/types/fixture, Core registry, SQLAlchemy/Alembic setup and test configuration. Root `AGENTS.md` and `docs/requirements/PERSON_2_FEASIBILITY_REQUIREMENTS.md` are now canonical. P1/P3 business modules remain placeholders. Live PostgreSQL migration smoke remains P5's documented Docker/WSL blocker; no external database was used here.

Local backup ref `backup/p2-before-main-sync-d28b63a` preserves approved P2 HEAD. Nine existing untracked bytecode files were preserved with matching SHA256 hashes; incoming `.gitignore` now ignores them. Only conflicts were feasibility package docstrings and adjacent TEAM_LOG QA rows; both members' records were combined. Shared Core/contracts/DB/migrations and canonical instructions remain identical to incoming Main. Merge SHA and push verification are in the task response.

## P2 phase board

| Phase | Scope | State | Gate / evidence |
|---|---|---|---|
| 0 | Inspect repo, trace requirements, propose contracts and synthetic fixture | PASS — externally reviewed and approved | Trace/report/progress created; shared contract decisions remain unratified and explicitly blocked |
| 1 | Validated operational snapshots and synthetic fixtures | PASS — externally reviewed and approved | Approved SHA `0d990d99bfe973f7b13295d1e005639a0f61adbd`; prior 21 tests preserved |
| 2 | Decimal ATP, time-phased supply, recursive BOM and unit conversion | PASS — externally approved | Approved `d28b63ab5fa82c66633ad18211b9c4fa83ffbbe4`; 66 regressions pass after Main sync |
| 3 | Capacity/deadline checks and pure evaluator | PARTIAL — P2-local Phase 3 correction approved; shared output BLOCKED | User approved local correction at `650b702fbbdef3f2f0160db0bf3dc12cad3d2b2c`; empty Impact Set schema and P3/P5 adapters remain pending |
| 4 | Dependency graph and incremental impact recalculation | PASS — P2-local correction approved; shared integration remains blocked | User approved exact baseline `f6ac87233534f0dc6deef3b5e464e0bd7fd1fd0e`; empty Impact Set and P5 adapters remain open |
| 5 | Five P2 routes and P3/P5 contract handoff | PARTIAL — P2-local routes and focused tests pass | P5 auth, snapshot authority, router registration, empty Impact Set, assessment history, impact persistence, and transactional event/outbox remain blocked |
| 6 | Feasibility and impact frontend views | NOT_STARTED | Requires explicit approval after Phase 5 review and shared frontend skeleton |
| 7 | Mandatory gap closure, integration, metrics, and handoff | NOT_STARTED | Requires explicit approval after Phase 6 review and available P5/P3 integration |

## Historical Phase 0 interface proposal (superseded locally by PHASE3_HANDOFF.md)

This section records a P2 proposal for review; it does not ratify a new global contract.

### Pure evaluator

```text
evaluate(
    snapshot: OperationalSnapshot,
    proposed_changes: ProposedChanges | None,
    commitment: Commitment | BusinessContext,
) -> FeasibilityAssessment
```

The function is deterministic for the same validated input, has no persistence or reservation side effects, and reads the target tenant and versioned confirmed commitments from the supplied snapshot. A hypothetical plan is evaluated by passing `proposed_changes`; impact processing calls the same evaluator separately for each candidate commitment. `BusinessContext`/`Commitment` resolution, the concrete Python import path, and the serialized request schema remain subject to P1/P3/P5 contract confirmation.

### Evaluator input shape proposal

The internal HTTP wrapper follows the canonical system contract's `BusinessContext/Commitment + OperationalSnapshot + proposed_changes?` shape. For P3, the target is an existing confirmed `Commitment`. The candidate snapshot carries `snapshot_id`, `snapshot_version`, `tenant_id`, offset-aware `captured_at`, source references, freshness and validation status, normalized SKU catalog, BOM, usable inventory lots, reservations, confirmed inbound deliveries, capacity calendars, active confirmed commitments, and logistics cutoff. `proposed_changes` is an optional typed set of hypothetical supply/production/resource changes. The server's authenticated tenant remains authoritative; a caller-supplied tenant value must match it before reading data or invoking the evaluator. IDs serialize as strings, quantities as decimal strings, and all timestamps are offset-aware ISO 8601. These are proposed fields derived from the P2 owner inputs; they are not a ratified shared Pydantic model.

Schematic request/response (illustrative contract only, not executed):

```text
POST /internal/feasibility/evaluate
request = {
  subject: exactly one of {
    commitment: {tenant_id, commitment_id, commitment_version, order_id, customer_id,
                 terms: {sku, quantity, unit, deadline}, agreement_state, evidence_refs},
    business_context: {tenant_id, context_id, context_version, order_id, customer_id,
                       requested_items, requested_delivery_at, field_evidence, status}
  },
  snapshot: {snapshot_id, snapshot_version, tenant_id, captured_at, sources,
             freshness_status, validation_status, sku_catalog, bom, inventory_lots,
             reservations, confirmed_deliveries, capacity_calendars,
             active_confirmed_commitments, logistics_cutoff},
  proposed_changes: optional
}
response = {
  assessment_id, tenant_id, commitment_id, commitment_version, snapshot_version,
  status: FEASIBLE | CONDITIONAL | INFEASIBLE | UNKNOWN,
  constraints: [{code, resource_id, required, usable, reserved, confirmed_incoming,
                 shortage, unit, needed_by, evidence_refs}],
  affected_commitment_ids, evidence_refs, solver_status, assessed_at,
  assumptions: []  # P2-required additive field; P5 contract review pending
}
```

The constraint detail above remains a historical proposal, not the shared serialization schema. P5's current `ConstraintReason` uses `deadline` and mandatory `severity`, and omits detailed required/usable/reserved/incoming fields. `FeasibilityAssessment.assumptions` now exists. The final subject/snapshot/ProposedChanges shape and any additional material fields still need P1/P3/P5 review; reuse shared types without silently extending them.

### Assessment shape

Use `app.core.schemas.FeasibilityAssessment` and `ConstraintReason` for the future evaluator. Shared assumptions and typed enums are present. Status, constraint severity/deadline, nonempty affected IDs and solver status must follow these existing types. P2 material-only rows remain local inputs to that future mapping; no shared model was edited in this sync.

### Event envelope

Use the canonical `DomainEvent` envelope: `event_id`, `schema_version`, `event_type`, `tenant_id`, `commitment_id` where applicable, `commitment_version`, `correlation_id`, `causation_id`, offset-aware `occurred_at`, and `payload`. P2's four event types are `commitment.feasibility_assessed`, `commitment.at_risk`, `operational.impact_updated`, and `operational.insufficient_data`; each P2 event must expose `tenant_id`, `commitment_id`, `snapshot_version`, and `correlation_id` as required by the owner spec. P5 owns common event persistence/outbox and Core risk transitions.

### P3 fixture handoff example (illustrative, not executed)

```text
assessment = evaluate(
    snapshot=operational_snapshot_v1,
    proposed_changes={"supplier_deliveries": [hypothetical_delivery]},
    commitment=commitment_com_001,
)
```

P3 must pass the same versioned snapshot and a typed proposed change to the single P2 evaluator for every candidate commitment it compares. An unconfirmed supplier quote must remain conditional or unavailable as trusted supply. The concrete proposed-change schema and module import are pending P3/P5 agreement; P3 must not implement a second ATP/BOM/capacity calculation.

## Provisional synthetic scenario

P5 now supplies `contracts/fixtures/demo_dataset.json`: `tenant_demo_01` / `com_001`, BURGER -> BUN/PATTY/SAUCE/PACKAGING. Existing P2 fixtures remain separate regression data (`tenant-synthetic-p2`, `com-001`, BURGER -> PATTY/BUN/WRAP). Preserve approved tests; align future integration through reviewed source adapters/fixture extensions rather than silently changing shared data. P5's operational snapshot is an untyped summary without P2's full source freshness/lot/reservation/calendar/competing-demand/typed receipt evidence, so missing facts cannot be guessed.

- The buffered scenario has `com-001` require 100 patties at `2026-10-23T09:00:00+08:00` and `com-002` require 20 at `2026-10-24T09:00:00+08:00`. Their customer delivery deadline is separately recorded as `2026-10-24T15:00:00+08:00`.
- The patty lot contains 80 units, with 20 actively reserved to `com-002`. A reservation is part of that lot's quantity, credited only to its named owner, and removed once from the unreserved pool; it is not subtracted a second time from general demand.
- Unreserved supply is allocated by `(material_use_at, commitment_id, commitment_version, line_id)` ascending. Equal material-use times use lexical commitment ID, then version and line ID as stable tie-breaks. Active reservations are honored to their owners before that general allocation. This is a deterministic fixture-label policy, not a business preference or stock-reservation command.
- The confirmed 40-patty delivery changes from `2026-10-23T08:00:00+08:00` to `2026-10-23T11:00:00+08:00`. Hand-labelled expected results are a 40-patty shortage for `com-001` and no impact to buffered `com-002`. A separate 500-patty unconfirmed promise remains present as untrusted input and is never labelled verified supply. The cutoff is `2026-10-24T08:00:00+08:00`.
- The two-affected variant has 30 unreserved patties and 110 confirmed inbound, with `com-001` requiring 100 and `com-002` 40 at `2026-10-23T09:00:00+08:00`; the ETA moves from `08:00` to `11:00`, after the `08:00` logistics cutoff. Under the declared priority, hand-labelled shortages are 70 and 40 (total 110). Without this order, those per-commitment labels would be arbitrary and risk double-counting the 30 units.
- Every timestamp carries its source offset; fixture times use `+08:00` / `Asia/Kuala_Lumpur`. Naive datetimes are rejected and comparison uses UTC instants. `material_use_at` is distinct from the customer-facing delivery deadline. Source/row evidence, tenant scope, snapshot ID/version, freshness bounds, and validation status are preserved.

Phase 2 batch ATP reproduces the material shortage labels in both snapshots. They are material results under the deterministic policy, not full feasibility or observed impact/event results. The P2-local serialization/model remains provisional until shared P5/P1 review.

## Open shared-owner decisions

| Owner | Decision / interface needed | Why it blocks final integration |
|---|---|---|
| P5 | Ratify full `OperationalSnapshot` and fixture adapters with source freshness, IDs, conversion/reservation/confirmed-delivery/calendar/competing-demand semantics | Shared Core schemas/skeleton exist, but operational snapshot remains an untyped summary dict; adapter facts/contract approval still needed |
| P5 | Confirm P2 route registration, API error shape, tenant/auth context and storage/query ownership for the five P2 routes | P2-owned router and local tests exist; P5 owns app mounting, auth, DB, persistence and integration |
| P5 | Provide authenticated RequestContext/internal caller boundary, authoritative snapshot provider/current-version concurrency, assessment-history repository, impact-result storage, transactional supplier-delay processor/outbox, and empty actual Impact Set support | Explicit Phase 5 handoff in `PHASE5_HANDOFF.md`; all remain unimplemented/unverified on current `origin/main` |
| P5 | Review material-detail mapping and event/outbox integration | Shared assessment assumptions, typed constraints and DomainEvent now exist; P2-specific adapter/event/history integration remains pending |
| P5 + P1 | Confirm the canonical synthetic SKU/BOM/unit catalog and normalized BusinessContext-to-Commitment inputs | P1 consumes the approved SKU list; current shared BURGER example is the only available baseline |
| P5 | Supply active confirmed commitments, tenant policy, Core identity/risk badges and the Core operation that records P2 assessment/risk results | P2 cannot update authoritative agreement, risk, or fulfilment state directly |
| P3 | Confirm concrete `ProposedChanges` serialization and import/HTTP usage of the P2 evaluator | P3 explicitly depends on the same pure evaluator and must not duplicate it |
| P5/P3 | Provide the authorized command-side reservation adapter and concurrent allocation integration test | F2-09's command reservation belongs to the executor/Core, never to P2's query evaluator |

## Next action

Review the Phase 5 report and `PHASE5_HANDOFF.md` independently. P5 must implement and verify the requested shared adapters before any blocked route is described as integrated. P3 must confirm the proposed HTTP request/response shape. Stop here; do not begin Phase 6 until independent Phase 5 review returns `APPROVED — CONTINUE P2`.
