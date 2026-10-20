# P2 Feasibility & Impact Progress

## Current checkpoint

- **Phase:** 0 — Inspect + Contract Trace
- **State:** PARTIAL; documentation checkpoint is prepared, while P5 contract decisions listed below remain unratified.
- **Branch:** `feat/p2-feasibility-engine`
- **Workspace:** `D:\dunno\0.SDC\MouManTAI`
- **Gate:** Do not start Phase 1 until the user sends `APPROVED — CONTINUE P2` after external review.
- **Tests:** Not run. Phase 0 explicitly prohibits tests.
- **Implementation:** No P2 runtime code exists yet; this phase creates only P2-owned planning, trace, and review artifacts.

## Repository baseline

The designated clone was clean on `main` at `aedb152` (`origin/main`) before the P2 branch was created. The tracked project files were `README.md`, `docs/AGENTS.md`, `docs/REQUIREMENTS_SYSTEM.md`, and `docs/TEAM_LOG.md`. No backend, frontend, shared contracts, test suite, P1/P3/P5 modules, or shared application skeleton is present. The only configured remote is `origin` at the repository URL identified in the user's master prompt. The actual P2, P1, P3, and P5 owner requirement files were readable from the authorized parent workspace; they remain outside the repository and are not copied here.

## P2 phase board

| Phase | Scope | State | Gate / evidence |
|---|---|---|---|
| 0 | Inspect repo, trace requirements, propose contracts and synthetic fixture | PARTIAL | Trace/report/progress created; P5 contract review is open; no tests by instruction |
| 1 | Validated operational snapshots and synthetic fixtures | NOT_STARTED | Requires explicit approval of Phase 0 |
| 2 | Decimal ATP, time-phased supply, recursive BOM and unit conversion | NOT_STARTED | Requires explicit approval after Phase 1 review |
| 3 | Capacity/deadline checks and pure shared evaluator | NOT_STARTED | Requires explicit approval after Phase 2 review |
| 4 | Dependency graph and incremental impact recalculation | NOT_STARTED | Requires explicit approval after Phase 3 review |
| 5 | Five P2 routes and P3/P5 contract handoff | NOT_STARTED | Requires explicit approval after Phase 4 review and shared API decisions |
| 6 | Feasibility and impact frontend views | NOT_STARTED | Requires explicit approval after Phase 5 review and shared frontend skeleton |
| 7 | Mandatory gap closure, integration, metrics, and handoff | NOT_STARTED | Requires explicit approval after Phase 6 review and available P5/P3 integration |

## Provisional shared interface proposal

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

The constraint detail above is a proposal to make P2's shortage evidence inspectable. The HTTP `subject` union follows the canonical system contract; its exact serialization still needs P1/P5 approval. P5 must approve additive assessment/constraint fields and the final error shape before HTTP integration; the canonical shared assessment fields listed below remain unchanged.

### Assessment shape

Retain the canonical `FeasibilityAssessment` fields from `docs/REQUIREMENTS_SYSTEM.md`: `assessment_id`, `tenant_id`, `commitment_id`, `commitment_version`, `snapshot_version`, `status`, `constraints`, `affected_commitment_ids`, `evidence_refs`, `solver_status`, and offset-aware `assessed_at`. P2 additionally requires visible assumptions and source-grounded constraint detail; adding `assumptions` or changing the constraint object requires P5 review because the shared contract is not present in code. Status values remain exactly `FEASIBLE`, `CONDITIONAL`, `INFEASIBLE`, or `UNKNOWN`; none implies agreement or fulfilment.

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

No P5-approved fixture exists. This proposal reuses the shared contract's example SKU `BURGER` and remains temporary pending P1/P5 confirmation of SKU IDs, units, BOM, fixture ownership, and commitment references. All quantities are synthetic and use exact `pcs`; timestamps are offset-aware Malaysia time (`+08:00`).

- BOM proposal: each `BURGER` needs 1 `PATTY`, 1 `BUN`, and 1 `WRAP`; buns and wraps have enough fresh stock for both commitments.
- `com_001`: confirmed 100 `BURGER`, material-use time `2026-10-23T09:00:00+08:00`, customer deadline `2026-10-24T15:00:00+08:00`.
- `com_002`: confirmed 20 `BURGER`, with 20 `PATTY` already reserved from on-hand stock; material-use time `2026-10-24T09:00:00+08:00`.
- Snapshot: 80 usable `PATTY` on hand, 20 reserved for `com_002` (so 60 unreserved for `com_001`), plus 40 confirmed incoming `PATTY` originally due `2026-10-23T08:00:00+08:00`. Baseline supply is 120 for total demand 120.
- Supplier change: ETA moves to `2026-10-23T11:00:00+08:00`. For `com_001`, only 60 unreserved patties are usable by need time, so the expected shortage is 40. `com_002` remains covered by its 20-unit reservation; the later inbound delivery still arrives before its need time, so it is the buffered unaffected case.
- F2-06 variant: two commitments of 100 and 40 `BURGER` both need patties before `09:00`; 30 patties are on hand and 110 confirmed incoming are originally due before need. Delaying that delivery to `11:00` leaves both commitments short (70 and 40 under the stated deterministic allocation), exercising two affected IDs.

These are expected examples for Phase 1/2 fixtures and later tests, not observed evaluator output. They must be checked against the approved P1/P5 data model before implementation.

## Open shared-owner decisions

| Owner | Decision / interface needed | Why it blocks final integration |
|---|---|---|
| P5 | Ratify `OperationalSnapshot` and fixture types, including source freshness, status/validation, IDs, unit conversions, reservations, confirmed deliveries, capacity and active commitments | No shared schema, database, or app skeleton exists; P2 must not create competing global contracts or migrations |
| P5 | Confirm P2 route registration, API error shape, tenant/auth context and storage/query ownership for the five P2 routes | P2 owner routes are specified, while P5 owns API contracts, auth, database and integration |
| P5 | Ratify additive assessment fields/constraint evidence and the event envelope/outbox mapping for the four P2 events | System contract has the assessment base fields and common event envelope; P2 adds assumptions and detailed evidence |
| P5 + P1 | Confirm the canonical synthetic SKU/BOM/unit catalog and normalized BusinessContext-to-Commitment inputs | P1 consumes the approved SKU list; current shared BURGER example is the only available baseline |
| P5 | Supply active confirmed commitments, tenant policy, Core identity/risk badges and the Core operation that records P2 assessment/risk results | P2 cannot update authoritative agreement, risk, or fulfilment state directly |
| P3 | Confirm concrete `ProposedChanges` serialization and import/HTTP usage of the P2 evaluator | P3 explicitly depends on the same pure evaluator and must not duplicate it |
| P5/P3 | Provide the authorized command-side reservation adapter and concurrent allocation integration test | F2-09's command reservation belongs to the executor/Core, never to P2's query evaluator |

## Next action

Submit the Phase 0 report and trace for external review. On `APPROVED — CONTINUE P2`, start Phase 1 only, implement P2-owned snapshot validation/fixtures, and run only the focused model/fixture tests required by that phase.
