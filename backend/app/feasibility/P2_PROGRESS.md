# P2 Feasibility & Impact Progress

## Current checkpoint

- **Phase:** 1 — Operational Snapshots + Synthetic Data
- **State:** Phase 1 targeted review corrections PASS; external review is pending. Shared P5/P3 integration decisions remain explicitly BLOCKED.
- **Branch:** `feat/p2-feasibility-engine`
- **Remote branch status:** `origin/feat/p2-feasibility-engine` pushed and verified to match local HEAD after this checkpoint commit; exact SHA is in the phase response.
- **Workspace:** `D:\dunno\0.SDC\MouManTAI`
- **Phase 0 review:** Approved by the user after external review. The Master Prompt was available as `D:\dunno\0.SDC\P2_CODEX_MASTER.txt.txt` (the supplied path omitted the final `.txt`).
- **Gate:** Stop for external review; do not start Phase 2 without a later `APPROVED — CONTINUE P2`.
- **Tests:** Four provenance-focused test nodes failed before implementation; five focused provenance tests pass. `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q` — 21 passed.
- **Implementation:** P2-local immutable snapshots now validate typed supplier confirmation associations bound to tenant, supplier, delivery, source row and evidence reference; ETA changes preserve that confirmation and link a distinct ETA-change claim. Capacity-window upper bounds, commitment material-use/deadline consistency, and Oct 24 buffered-fixture calendar coverage are also validated. Calendar coverage does not establish production feasibility. No P2 UI/API/evaluator or P5-owned code was changed.
- **Evidence trust boundary:** The model guarantees structural source provenance within a snapshot; external authenticity and supplier identity verification remain P5 source-adapter responsibilities. All new model fields remain P2-local and provisional.
- **P5/P3 blockers:** Shared snapshot/assessment/ProposedChanges contracts, persistence, routes/auth/outbox, and P3 import/serialization remain provisional and unratified; they did not block independent P2-local Phase 1 work.

## Repository baseline

At the Phase 0 baseline the designated clone was clean on `main` at `aedb152` (`origin/main`); the P2 branch is `feat/p2-feasibility-engine`. Before Phase 1, HEAD was `5368e0d` and the working tree was clean. The repository still has no P5 backend/frontend skeleton, shared contracts, persistence, P1/P3 modules, or repository test configuration. The actual P2 owner requirements remain outside the repository and were not copied here. Phase 1 uses the installed Pydantic v2 runtime without changing P5-owned root dependency/configuration files.

## P2 phase board

| Phase | Scope | State | Gate / evidence |
|---|---|---|---|
| 0 | Inspect repo, trace requirements, propose contracts and synthetic fixture | PASS — externally reviewed and approved | Trace/report/progress created; shared contract decisions remain unratified and explicitly blocked |
| 1 | Validated operational snapshots and synthetic fixtures | P2-local implementation and targeted corrections PASS; external review pending | 21 focused tests pass; P5/P3 integration remains blocked; stop before Phase 2 |
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

No P5-approved fixture exists. The executable fixtures remain temporary and reuse the shared example SKU `BURGER`, pending P1/P5 approval of SKU IDs, units, BOM, fixture ownership, and commitment references. Each burger needs one `PATTY`, `BUN`, and `WRAP`; all quantities are synthetic `Decimal` values in `pcs`.

- The buffered scenario has `com-001` require 100 patties at `2026-10-23T09:00:00+08:00` and `com-002` require 20 at `2026-10-24T09:00:00+08:00`. Their customer delivery deadline is separately recorded as `2026-10-24T15:00:00+08:00`.
- The patty lot contains 80 units, with 20 actively reserved to `com-002`. A reservation is part of that lot's quantity, credited only to its named owner, and removed once from the unreserved pool; it is not subtracted a second time from general demand.
- Unreserved supply is allocated by `(material_use_at, commitment_id, commitment_version, line_id)` ascending. Equal material-use times use lexical commitment ID, then version and line ID as stable tie-breaks. Active reservations are honored to their owners before that general allocation. This is a deterministic fixture-label policy, not a business preference or stock-reservation command.
- The confirmed 40-patty delivery changes from `2026-10-23T08:00:00+08:00` to `2026-10-23T11:00:00+08:00`. Hand-labelled expected results are a 40-patty shortage for `com-001` and no impact to buffered `com-002`. A separate 500-patty unconfirmed promise remains present as untrusted input and is never labelled verified supply. The cutoff is `2026-10-24T08:00:00+08:00`.
- The two-affected variant has 30 unreserved patties and 110 confirmed inbound, with `com-001` requiring 100 and `com-002` 40 at `2026-10-23T09:00:00+08:00`; the ETA moves from `08:00` to `11:00`, after the `08:00` logistics cutoff. Under the declared priority, hand-labelled shortages are 70 and 40 (total 110). Without this order, those per-commitment labels would be arbitrary and risk double-counting the 30 units.
- Every timestamp carries its source offset; fixture times use `+08:00` / `Asia/Kuala_Lumpur`. Naive datetimes are rejected and comparison uses UTC instants. `material_use_at` is distinct from the customer-facing delivery deadline. Source/row evidence, tenant scope, snapshot ID/version, freshness bounds, and validation status are preserved.

Expected shortage/impact labels are synthetic ground truth only. Phase 1 tests snapshot construction and labels; no feasibility calculation or observed impact engine exists yet. The P2-local serialization/model remains provisional until shared P5/P1 review.

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

Submit the Phase 1 report and trace for external review. Do not start Phase 2 until the user returns `APPROVED — CONTINUE P2`.
