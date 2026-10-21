# Phase 7A early integration handoff

Baseline: Main `ee4dfc73deb998a5af902422220cb1a34e0182cc`, P3 read-only ref
`ca7517c` (`origin/feat/p3-recovery`). No P3 code merged or available at runtime
on this P2 branch. This document supersedes historical missing-schema/P3-placeholder
blockers in prior handoffs; it does not erase their original evidence.

## P3: single official evaluator

```python
from app.feasibility.service import evaluate, EvaluationResult
from app.feasibility.production import EvaluationSnapshot, ProposedChanges
from app.feasibility.production_fixtures import build_production_example

snapshot, commitment = build_production_example()  # SYNTHETIC HISTORICAL DATA
result = evaluate(snapshot, None, commitment)
print(result.status.value, result.solver_status.value)  # observed: FEASIBLE COMPLETED
```

Run from `backend/` with `python -B -c` or the demo below. Exact signature:
`evaluate(snapshot: EvaluationSnapshot, proposed_changes: ProposedChanges | None,
commitment: app.core.schemas.Commitment) -> EvaluationResult`.
Output retains assessment/tenant/commitment ID+version, snapshot ID+version,
assessed_at, status, solver_status, constraints, assumptions, evidence_refs,
materials/capacity and evidence_complete/allocation_dependent. UNKNOWN cannot be
treated as safe or proved infeasible. CONDITIONAL proposals still require approval.
Fixed-booking failure does not prove all possible schedules impossible.

`EvaluationSnapshot` requires a typed OperationalSnapshot (catalog/conversions,
BOM/loss, lots/expiry/location, owned reservations, confirmed receipts and ETA
claims, all competing confirmed commitments, calendar and cutoff, source bounds)
plus ProductionData (resources, rates/setup/lead, plans, complete job ledger and
coverage horizon with typed source evidence). A metadata-only reference is insufficient.
No naive timestamps. Tenant, target/version and complete Core terms must match.
The current version is separate from the captured historical version.

Supported ProposedChanges: quantity, deadline, production_start_at, with tenant,
commitment ID, expected commitment/snapshot versions and nonempty evidence_refs.
Unknown fields reject. No supply creation, supplier substitution, reservation,
job deletion or capacity invention. P3 must propose typed extensions for review.

P3's `integrations.P2FeasibilityEvaluatorAdapter(evaluate)` already accepts the
module function and checks envelope/result binding. It rejects synthetic inputs
for live plans. P3 must resolve a real complete snapshot, then construct typed
ProposedChanges. Its older `feasibility.P2FeasibilityAdapter` expects an object
method and metadata-only snapshot/dictionary: do not pass that directly to P2.
No production P3 call has been tested here. P2 synthetic tests exercise real math.

## P5: exact dependencies and priorities

| Priority / owner | Required interface, inputs → outputs | Existing reuse / missing work | Joint verification |
|---|---|---|---|
| P0 P5 source authority + P2 assembly | Resolve tenant/commitment version → complete EvaluationSnapshot + Core Commitment; resource-version vector/read token | `get_resource_snapshot` exposes totals/unit/resource version/timestamp only; missing BOM/catalog/conversions/lots/reservation owners/receipts/production/cutoff/provenance/completeness and atomic read contract | Wrong tenant, source stale/missing, missing ledger, changed resource during compute; never promote totals to full snapshot |
| P0 P5 auth | Verified requester → approved internal SERVICE principal and retained requester audit identity | `CommitmentService.assess` requires SERVICE/SYSTEM; demo headers are untrusted | User cannot self-declare SERVICE; caller/tenant/term/version mismatches fail before writes |
| P0 P5 transaction + P2 domain | Exact P2 result + snapshot + commitment → append history, internal Core writer, audit/outbox in ONE transaction | Pure P2 mapping/history supplied; shared DB tables, locks/version recheck and transaction adapter absent | Rollback all on failure, no stale safe writes, duplicate identity no second transition |
| P0 P5 supplier source + P2 calculation | Verified supplier event + immutable before/after + typed claim → `recalculate_supplier_delay` → actual ImpactAssessment | P2 orchestration verifies row/claim linkage; P5 must establish source authenticity, capture/version authority, replay uniqueness and atomic result/outbox | Repeated event once; same event different payload rejected; out-of-order event rejected; unrelated stock change UNKNOWN |
| P0 P5 app | Include P2 router, preserve five existing paths | Public POST `/v1/commitments/{commitment_id}/assess` exclusively P2; Core writer stays internal | Combined routers unique; production mounted paths and error bodies checked |
| P0 P5 frontend transport + P2 projections | Auth transport + Core/history/detail/impact reads → stable P2DataSource | Existing feature pages/data checks and PHASE6_HANDOFF field map; public detail envelope and status-preserving transport need approval | 403 permission, 409 conflict/reload, 503 retry; retain prior result during recalculation; no fixture fallback |

The supplier processor route port commits durable work; the new pure function is
NOT that adapter. Local event intents do not publish events or mutate risk.
Production defaults remain 503. P2 assembles supported fields; P5 coordinates
source contracts, auth, DB and transaction infrastructure, not P2 calculation.

### Proposed persistence contract for P5 review (no migration authored here)

- Assessment history: tenant_id + assessment_id unique; commitment_id/version,
  snapshot_id/version, immutable result and source snapshot payload/hash,
  assessed_at, requester/service identities, audit/correlation refs. Index
  `(tenant_id, commitment_id, assessed_at, assessment_id)` and snapshot bindings.
- Impact history: `(tenant_id, impact_id)` unique; event_id, before/after IDs and
  versions, complete candidate results, causal reasons/evidence, actual impacted
  IDs and snapshot payload/hash. `(tenant_id, event_id)` unique payload binding;
  same cause with different payload is 409, not successful replay.
- Consumer inbox: unique `(tenant_id, event_id)` and immutable input hash; outbox
  unique `(tenant_id, event_id)` for each emitted intent. Detection dedup keys
  supplement event identity; distinct causes retain distinct event IDs.
- Queries: tenant-scoped history with stable ordering/pagination; history is not
  current by insertion order. Currentness must compare authoritative input versions
  transactionally (and freshness), not just a global tenant counter invented by P2.
- Writer preserves status/solver/constraints/assumptions/evidence and actual Impact
  Set. Approval, reservations, inventory/jobs, fulfilment and terms remain unchanged
  by the P2 query. Core guards and audit/outbox behavior remain P5-owned.

### Frontend integration sequence

P5 approve public detail contract and structured HTTP errors; wire stable
authenticated P2DataSource, then mount CommitmentFeasibilityPage and ImpactDetailPage
in the existing shell. Map material quantities/units/need times, capacity operations,
source freshness and evidence exactly as PHASE6_HANDOFF specifies. Map changed
ETA rows from immutable pipeline input; derive risk_change only from Core audit.
Recalculate body remains `{expected_commitment_version}`; do not silently add a
snapshot field. P5 rechecks resource/commitment versions at persistence. A queued
response must not become a completed view. Run real API/browser tests after wiring.


### Observed Phase 7A boundary validation

`SupplierDelayInputs` / `recalculate_supplier_delay(inputs, tenant_id=...)` is a
pure P2 historical calculation API. Resolve actual before/after source states
first; it does not implement the committing SupplierDelayProcessor route port.
`history.to_core_assessment(result, impact=...)` maps exact status/solver/constraints,
assumptions/evidence/version/time and verified actual impacted IDs; without impact,
IDs are empty. Snapshot ID/full source contents stay in AssessmentRecord because
canonical FeasibilityAssessment has only snapshot_version. All nested outputs must
bind their complete input identities. Additive local calculation_input_digest
covers missing-Core UNKNOWN results too; existing impact/event IDs are unchanged.
Legacy results without this digest require reviewed historical migration/replay,
not silent acceptance into this reference repository. Digests are content binding,
not proof of authenticity. See final Phase 7A report and 131-row current audit.


### Post-review correction: first-insert integrity and production writer trust

The reference repository now rejects first-insert result tampering by recomputing
through the existing `evaluate` or `recalculate_supplier_delay` and comparing the
complete expected result, including nested calculations, classifications, evidence
and all event intents/payloads. No fields are ignored; current timestamps and IDs
are deterministic from recorded inputs. Input IDs/digests alone never establish
result authenticity. This is synthetic reference/test verification only, not
production source authenticity or a production writer design.

P5's authoritative writer must receive the exact P2-produced result through a
trusted server-side execution boundary, retain requester and internal SERVICE
identity, transactionally recheck authoritative input versions and commit
history/Core/audit/outbox atomically. Do not accept arbitrary caller-authored
assessment objects or matching hashes as evidence of a genuine result. Do not
independently recalculate/change the result in the writer. If versions changed,
reject and ask the P2 execution flow to evaluate new trusted inputs. That adapter
remains a P5 dependency; no P5/P3 implementation was edited in this correction.
