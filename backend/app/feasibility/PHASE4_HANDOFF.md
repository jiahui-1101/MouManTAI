# P2 Phase 4 — Dependency Graph and Impact Handoff

**State:** Targeted external-review corrections are implemented and locally tested; stop for independent external Phase 4 review. Phase 4 remains PARTIAL. P5 shared assessment/event integration remains blocked. Phase 5 has not started.

## Local interface

```python
from app.feasibility.impact import OperationalChange, assess_impact, build_dependency_graph

graph = build_dependency_graph(snapshot, core_commitments)
result = assess_impact(
    before_snapshot,
    after_snapshot,
    change,
    before_commitments=before_core_commitments,
    after_commitments=after_core_commitments,
)
```

`OperationalChange` binds one canonical `DomainEvent` identity, tenant, event type, capture interval, before/after snapshot versions, one or more typed resource keys, and evidence refs. Supported changes are supplier ETA, inventory lot/SKU, capacity job/production resource, and order/commitment changes. Each declared resource must have a supported before/after change and linked event evidence; every supplied ref must be accounted for across the changed resources collectively. Supplier ETA changes additionally require the delivery-linked typed `ETA_CHANGE` claim.

`assess_impact()` validates immutable copies, builds before/after resource indexes, and re-evaluates each discovered same-tenant candidate with the same P2 `service.evaluate()` used in Phase 3. It does not duplicate ATP/BOM/capacity logic. Incomplete dependency evidence expands discovery only within the tenant and classifies the results UNKNOWN. Resource keys can identify SKU, lot, supplier delivery, production job/resource, order, or commitment paths; only path candidates are evaluated when required graph evidence is complete.

## Results and conservative semantics

`ImpactAssessment` includes the triggering event/correlation IDs, both snapshot IDs/versions, deterministic candidate IDs, discovery completeness, each commitment's before/after versioned evaluator result, actual material shortage and HARD-constraint deltas, positive buffers, evidence refs, dependency paths, reasons, and local event intents. The convenience ID lists mean:

- `candidate_commitment_ids`: resource-graph scope only.
- `confirmed_impacted_commitment_ids`: actual complete-evidence adverse before/after deltas only.
- `verified_unaffected_commitment_ids`: both calculations are FEASIBLE and a positive measured buffer exists.
- `unknown_commitment_ids`: evidence/graph or allocation uncertainty prevents a safe classification.
- `pre_existing_unchanged_commitment_ids`: the same infeasible state exists before and after without a new adverse delta.

`CommitmentImpact.verified_material_deterioration` is separate from the full feasibility and causal classifications. A measured before/after adverse delta is not automatically caused by the triggering event. A relevant changed resource omitted from the event's declared resource set makes adverse attribution UNKNOWN and suppresses `commitment.at_risk`. Multi-resource events can retain confirmed impact when each relevant changed resource and evidence ref is included. `UNKNOWN` is neither safe nor confirmed disrupted. An independently demonstrated HARD delta can remain actionable through allocation-policy uncertainty only when both calculations report complete evidence; stale/missing evidence still dominates. A fixed-booking failure does not prove all possible reschedules are impossible.

Deadline HARD severity uses the existing evaluator's calculated production finish, the explicit process delivery lead, and the customer deadline from each snapshot. Constraints are matched without using the changing deadline as identity. The local delta identifies NEW, WORSENED, IMPROVED, or UNCHANGED lateness in minutes; insufficient timing/evidence remains UNKNOWN.

## Observed synthetic results

| Scenario | Candidate/material result | Full classification |
|---|---|---|
| Buffered supplier ETA, material-only | `com-001`: PATTY `0→40` (`+40` pcs); `com-002`: `0→0` | Both UNKNOWN; actual Impact Set empty |
| Two-affected supplier fixture, material-only | `com-001`: `0→70` (`+70` pcs); `com-002`: `0→40` (`+40` pcs) | Both UNKNOWN; actual Impact Set empty |
| Same buffered supplier case with complete synthetic production evidence | `com-001` fixed booking becomes INFEASIBLE; `com-002` retains positive buffer | `com-001` CONFIRMED_IMPACT; `com-002` VERIFIED_UNAFFECTED; only `com-001` gets an at-risk intent |
| Capacity job/resource change with overlap | `JOB_CONFLICT` after only for `com-001` | `com-001` confirmed; buffered `com-002` verified unaffected |
| Capacity calendar window reduction | New `CAPACITY_WINDOW_VIOLATION` on `com-001` booking; later `com-002` booking remains feasible | `com-001` confirmed; `com-002` verified unaffected |
| Confounded capacity event plus supplier delay | Non-overlapping declared job; unreported receipt delay causes `com-001` PATTY shortage `0→40` | `com-001` UNKNOWN with measured material deterioration and no at-risk intent; `com-002` verified unaffected |
| Multi-resource capacity event with both jobs declared | Overlapping and non-overlapping jobs each have distinct event evidence | `com-001` confirmed from the overlap; `com-002` verified unaffected |
| Two inventory lots in one event | Each changed lot has a different linked evidence ref | Accepted; unaccounted evidence and unchanged declared resources reject |
| Deadline extension | Expected delivery stays 11:10; customer deadline changes 11:00→11:05 | Lateness 10→5 minutes, IMPROVED; both evaluator results remain INFEASIBLE and no new impact is claimed |
| Deadline worsening | Customer deadline stays 12:30; expected delivery changes 12:50→13:00 on a declared process-resource change | Lateness 20→30 minutes, WORSENED and CONFIRMED_IMPACT |
| Order request change | Only the changed order is a candidate; PATTY shortage delta `0→20` | UNKNOWN because production evidence is absent |
| Stale production source after supplier delay | Material delta remains visible; complete production proof is stale | UNKNOWN and `operational.insufficient_data` intent |
| Stale inventory source after supplier delay | Inventory source expires before after-snapshot capture | UNKNOWN; no verified material deterioration is claimed |
| Unchanged pre-existing shortage | Same shortage and same hard failure before/after | PRE_EXISTING_UNCHANGED; no at-risk intent |

All records are team-generated synthetic data. These results do not establish external source authenticity or live business accuracy.

## Event boundary

P2 creates local, canonical-envelope `DomainEvent` intents for `commitment.feasibility_assessed`, `operational.impact_updated`, `commitment.at_risk`, and `operational.insufficient_data`. Intents carry event/schema/type/tenant/commitment/version/correlation/causation/time fields and evidence/snapshot details in the payload. Replaying the same cause yields deterministic output and keys; identical detection state retains its deduplication key, while a distinct causal event gets a distinct event ID. **Nothing is published, persisted, inserted into an outbox, or applied to Core in Phase 4.** P5 owns durable deduplication, event ordering, outbox, and authoritative risk transitions.

P5 confirmed that shared `FeasibilityAssessment.affected_commitment_ids` means the actual Impact Set. The current P5 field still rejects an empty list (`min_length=1`). The final adapter must not use candidate IDs as affected IDs or invent a target ID; empty-set schema support must be merged and verified by P5 before P2 completes that mapping.

## Remaining integration work

- **P5:** merge/verify empty actual Impact Set support; review the final P2-local impact result to `FeasibilityAssessment` adapter and event payload details; provide authenticated tenant, authoritative snapshot version/current-version race check, complete source/catalog adapter, persistence/audit/outbox and Core risk transition.
- **P3:** confirm `ProposedChanges` serialization and use the same `evaluate()` function for alternatives; no P3 code or private evaluator was changed.
- **P1/P5:** align `tenant_demo_01/com_001` and the shared SKU/BOM catalog with the P2 operational snapshot only through reviewed source evidence and an approved adapter. Current shared summary omits required lot/reservation/receipt/process/job/calendar evidence.
- **Later API/UI/E2E/metrics:** Phase 5+ only, after the independent Phase 4 review gate. No frontend or API behavior is claimed.

## Validation

From `backend/`:

```text
python -B -m pytest -o 'addopts=' app/feasibility/tests/test_impact.py -q -p no:cacheprovider
22 passed in 0.75s

python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider
162 passed, 1 existing Starlette/httpx deprecation warning in 2.46s
```

The regression tests were first run against the reviewed baseline and reproduced the confounded causal confirmation, valid multi-lot evidence rejection, false new deadline violation on extension, and missed worsening-lateness delta.
