# Person 2 — Commitment Feasibility & Impact Intelligence

> **Owner**: P2 · **Type**: Full-Stack + Deterministic Algorithms + tests
> **Dependencies**: P1 `BusinessContext`, P5 Commitment and snapshot contracts. P3 **must reuse your computation**.
> **Goal**: Prevent unsafe customer promises and detect cascading impact when operational conditions change. Not a purchasing tool, not an autonomous promise maker.

## 1. User Outcome / Acceptance

SME user can open a Commitment, see available and reserved materials, deadline/resource constraints and a defensible `FEASIBLE`, `CONDITIONAL`, `INFEASIBLE`, or `UNKNOWN` result. Supplier-delay event updates a reliable snapshot, recalculates **affected** commitments, surfaces reasons, and emits risk events. Prior evaluation remains auditable by version.

**P0**: One synthetic inventory/BOM/capacity model with ≥2 commitments and a supplier ETA change; accurately identify shortage, affected commitments and unaffected ones. Return a `FeasibilityAssessment` whose `snapshot_version` and constraint evidence are inspectable. F3 must be able to ask whether a hypothetical replacement plan is feasible.

## 2. Frontend Ownership

**Routes**: `/commitments/:id` (Feasibility tab/view), `/impact/:id`.

### FE-01 Feasibility Detail
- [ ] Commitment identity, promised/proposed terms, agreement/risk badges (from Core, not locally invented).
- [ ] Feasibility summary + last assessment timestamp, operational snapshot version, source freshness, solver status.
- [ ] Materials view: required, usable, reserved, confirmed incoming, shortage; clearly show units.
- [ ] Production/capacity view: required processing time, available hours, conflicts, deadline constraints.
- [ ] Clear `UNKNOWN` UI when missing data / stale snapshot / solver timeout; never display a green “safe” status in this case.
- [ ] 'Recalculate' operation asynchronous loading/disabled submit, preserve prior result while computing, server error retry.
- [ ] Evidence panel displays exactly which stock/supplier rows underpin result.

### FE-02 Impact Detail
- [ ] List of changed resources/supplier ETAs and recalculation trigger.
- [ ] Affected Commitment cards: `commitment_id`, risk change, constraint, deadline, severity/known impact.
- [ ] **Unaffected** cases where buffer was sufficient must not be shown as risk by default.
- [ ] Before/after snapshot comparison, traceable impacted chain (Supplier → Material → Job → Order → Commitment).
- [ ] Text-based dependency table acceptable at P0; React Flow is optional enhancement.
- [ ] Loading/empty/error/permission/unknown states and consistent shared styles.

## 3. Backend Ownership

**Suggested module**: `backend/app/feasibility/`: `schemas.py`, `inventory.py`, `bom.py`, `capacity.py`, `solver.py`, `impact.py`, `service.py`, `router.py`, `tests/`.

### BE-01 Operational Snapshot Builder
- [ ] Input: normalized SKU catalog, BOM, usable on-hand lots, reservations, confirmed incoming purchase deliveries, capacity calendar, existing confirmed commitments, logistics cutoff.
- [ ] Each snapshot has `snapshot_id`, `snapshot_version`, `captured_at`, tenant scope, sources, freshness/validation status.
- [ ] Never silently treat unconfirmed purchase promises or ML predictions as verified supply.
- [ ] Preserve immutable snapshot for audit; source data ownership remains with external stock/ERP adapter or synthetic fixture.
- [ ] Validate impossible/duplicate input, unit mismatch, expired lots, missing BOM, overlapping reservations and source staleness.

### BE-02 Inventory Availability (ATP)
- [ ] Time-phased availability: usable stock + confirmed receipts accessible before need-time - existing committed/reserved demand; avoid double-subtracting reservations.
- [ ] Respect batch, expiry, unit conversion, warehouse/location when modeled; use `Decimal` for quantity or precise integer subunits, not floating inventory arithmetic.
- [ ] Explain shortages as resource-specific constraints, with quantity/unit and deadline, and source refs.
- [ ] For two competing orders, cannot allocate same units twice.
- [ ] `UNKNOWN` if trusted stock data missing; no optimistic default assumption.

### BE-03 BOM and Capacity
- [ ] Recursive BOM explosion and unit conversions; detect cycles/invalid material references.
- [ ] Account for known production loss/waste assumptions explicitly; display assumptions in assessment.
- [ ] Evaluate process duration vs start/finish deadline, working hours, line availability, pre-existing production jobs.
- [ ] Basic checks first, OR-Tools CP-SAT for multi-job/resource conflicts if meaningful. Solver outcome `UNKNOWN` ≠ proof of infeasibility.
- [ ] Separate `HARD` feasibility conditions from `SOFT` preferences; F2 does not optimize owner's business trade-off.

### BE-04 Dependency and Impact Recalculation
- [ ] Build dependency edges `supplier → incoming material → production job → order → commitment` (where applicable).
- [ ] On `supplier.delivery_changed`, `inventory.changed`, `capacity.changed`, `order.request_changed`, enumerate candidate impacted commitment IDs.
- [ ] **Recompute** actual feasibility for candidate IDs; existence of edge alone is not proof of risk.
- [ ] Only emit `commitment.at_risk` if known feasibility/risk changed to at risk per deterministic rule; avoid repeated identical alerts.
- [ ] Incremental invalidation keyed by affected resource; no need for Neo4j in P0.
- [ ] Version results; if input becomes stale during compute, abort/retry or tag stale, not record safe result.

### BE-05 Shared Planner Reuse
- [ ] Provide **pure or side-effect-free** `evaluate(snapshot, proposed_changes, commitment)` service; F3 uses it for candidate plan validation.
- [ ] Separate **query-mode** hypothetical plan check from **command-mode** inventory reservation. F2 **never** commits actual stock changes.
- [ ] Return constraint reasons, `status`, `solver_status`, `assumptions`, `evidence_refs`, optional feasible-by-deadline quantities if rigorously computed.
- [ ] Document reproducible fixtures so P3 can generate plans on Day 1 without waiting for finished service.

## 4. Contracts and APIs

**Must implement shared** `FeasibilityAssessment` from `REQUIREMENTS_SYSTEM.md`.

```text
POST /internal/feasibility/evaluate              # pure; P3 calls same engine
POST /v1/commitments/{id}/assess
GET  /v1/commitments/{id}/assessments
POST /v1/operations/events/supplier-delay       # synthetic event, scoped
GET  /v1/impacts/{impact_id}
```

**Events**: `commitment.feasibility_assessed`, `commitment.at_risk`, `operational.impact_updated`, `operational.insufficient_data`. All include `tenant_id`, `commitment_id`, `snapshot_version`, `correlation_id`.

**Incoming from P1**: requested SKU, quantity, unit, delivery time, context/version/evidence. **Incoming from P5**: active confirmed commitments, tenant policy. **To P3**: validated constraints and same evaluation service. **To P5**: risk assessment event; P5 updates risk status, not direct P2 DB hacks.

**Contract lock**: coordinate SKU IDs, units, resource calendar and deadline timezone on 20 Oct. No API accepts local naive datetime.

## 5. Data Entities

`inventory_items`, `inventory_lots`, `inventory_movements`, `inventory_reservations`, `bom_components`, `supplier_orders`, `supplier_deliveries`, `production_resources`, `capacity_calendars`, `production_jobs`, `operational_snapshots`, `dependency_edges`, `feasibility_assessments`, `impact_assessments`.

Use tenant scope, version and source evidence. P5 coordinates migrations and common Commitment references. No P2 model writes to `agreement_state` or `fulfilment_state`.

## 6. Test Cases (must implement)

| ID | Scenario | Expected |
|---|---|---|
| F2-01 | Required 100; only 70 usable; no receipts | `INFEASIBLE` with shortage 30 |
| F2-02 | 100 on-hand but 60 reserved elsewhere | Cannot promise 100 |
| F2-03 | Supplier delivers before required material-use time | Feasibility considers confirmed receipt timing |
| F2-04 | Supplier delivers **after** needed time | Shortage/time constraint flagged |
| F2-05 | Supplier delay, but enough buffer | Remains feasible; no false at-risk event |
| F2-06 | Supplier delay genuinely disrupts two orders | Both affected IDs, correct evidence |
| F2-07 | BOM cycle / missing stock snapshot | `UNKNOWN` or validation error; no confident safe claim |
| F2-08 | CP-SAT timeout with no proof | `UNKNOWN`, not `INFEASIBLE` |
| F2-09 | Two simultaneous reservation requests | Only authorized executor reserves, no double allocation |
| F2-10 | Hypothetical F3 plan | Same engine validates proposal, no database stock mutation |
| F2-11 | Old snapshot result after stock update | Not reused as current authoritative feasibility |
| F2-12 | Wrong tenant data | Refused, not loaded into solver or view |

**FE tests**: status/reasons visible; `UNKNOWN` displayed cautiously; before/after correctness; API failure remains recoverable.

**Metrics**: false-feasible rate, impacted-commitment recall, false-alert rate, computation latency, stale result rate, dataset size. Use an independently labelled synthetic test fixture; do not state unsupported ML forecast reliability.

## 7. Timeline

| Date | P2 deliverable |
|---|---|
| 20 Oct | Shared OperationalSnapshot + sample BOM/stock fixture; UI wireup; pure evaluator signature to P3 |
| 21 Oct | ATP/BOM/basic capacity checks, `/commitments/:id` API/UI, initial tests |
| 22 Oct | Supplier delay propagation, `/impact/:id` UI/API; integration with P5, P3 evaluator |
| 23 Oct | Full recovery path + edge/failure tests |
| 24 Oct | Metrics, performance regression, freeze |
| 25 Oct | Release support only |

## 8. Scope Exclusions / Dependencies

**P0**: deterministic ATP/BOM, basic resource constraints, impacted IDs re-evaluation, reusable pure feasibility API, UI/evidence/tests.
**Optional**: OR-Tools complex schedules if rules insufficient; React Flow visualization.
**Production later**: Chronos-2 demand prediction, LightGBM supplier delay risk, large-scale multi-site warehouse, ERP integrations.
**Forbidden**: AI-generated stock arithmetic, treating predicted shipment as confirmed stock, automatically changing confirmed customer commitment, independent F3 duplicate feasibility calculation.

## 9. Handoff Checklist

- [ ] P3 can call evaluator from exact agreed interface with fixture snapshot.
- [ ] F2 emits risk only when recalculation confirms risk.
- [ ] All states distinguish `UNKNOWN` from `INFEASIBLE`; no hallucinated ETA.
- [ ] P5 receives versioned event and updates shared Commitment Registry.
- [ ] Page uses real API and renders constraints, evidence and latest assessment.
- [ ] Unit, API, FE, event and E2E tests included; progress recorded in `TEAM_LOG.md`.
