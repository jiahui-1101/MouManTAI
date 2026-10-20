# Phase 3 provisional P3/P5 handoff

**PARTIAL: local calculations tested; shared assessment integration BLOCKED.**
No persistence, reservation, lifecycle mutation, events, routes or UI in this phase.

## Exact Python interface

From `backend/`, use the canonical `app` package:

```python
from app.feasibility.production_fixtures import build_production_example
from app.feasibility.production import ProposedChanges
from app.feasibility.service import evaluate

snapshot, commitment = build_production_example()
baseline = evaluate(snapshot, None, commitment)
proposal = ProposedChanges(
    tenant_id=commitment.tenant_id,
    commitment_id=commitment.commitment_id,
    expected_commitment_version=commitment.commitment_version,
    expected_snapshot_version=snapshot.operational.snapshot_version,
    quantity="60",
    evidence_refs=("synthetic-p3-partial-delivery-proposal",),
)
candidate = evaluate(snapshot, proposal, commitment)
assert baseline.status.value == "FEASIBLE"
assert candidate.status.value == "CONDITIONAL"
```

Signature: `evaluate(snapshot: EvaluationSnapshot, proposed_changes:
ProposedChanges | None, commitment: app.core.schemas.Commitment) -> EvaluationResult`.
P3 serialization agreement remains provisional; P3's current module is a placeholder.
No owner approval is inferred. HTTP wrapper belongs to the later approved API phase.

`EvaluationSnapshot` wraps existing immutable OperationalSnapshot, optional
ProductionData, explicit `as_of`, and optional `current_snapshot_version`.
Missing production data is UNKNOWN. Current-version authority must come from P5;
historical replay does not establish current database truth.

## Required production evidence

- Exclusive resources and SKU/base-unit processes with positive minutes per
  unit, explicit setup time and delivery lead time. None for rate/lead means
  UNKNOWN. No inference from daily totals, SKU name or an LLM.
- Fixed production plans for every manufactured commitment line, including
  version, start, dispatch cutoff and optional SOFT preferred finish. Start must
  match material-use time. Setup/processing occupies all resources simultaneously.
- Complete existing-job ledger for all declared resources across explicit
  coverage bounds. `jobs=None` means missing; `jobs=()` means a current,
  evidence-backed complete empty ledger. Jobs exclude commitment plans already
  represented in `plans`; source adapters must reconcile duplicate representations.
- Exact offset-aware working windows with breaks as gaps. Window minutes must
  equal elapsed duration. The older 480-minute total inside a 600-minute span
  cannot locate breaks: UNKNOWN. Adjacent windows join; job intervals are half-open.

Production sources have resources/processes/jobs/plans roles, references,
freshness and raw evidence. This validates structural provenance; P5 owns source
authenticity, external identity and ledger completeness. All new parameters are
explicit synthetic fixture facts, not inferred production data or P5-approved rates.

Supported model: fixed non-preemptible bookings. INFEASIBLE means that supplied
booking violates known constraints, not that every possible reschedule fails.
P3 may propose another start through the same evaluator. Manufactured intermediate
routing, purchased-finished-goods logistics, sub-microsecond durations and
unrepresentable times/durations are UNKNOWN rather than guessed.

`available_minutes` is continuous free time from start, bounded by work, dispatch,
customer deadline minus transit, ledger horizon and all other bookings. It is
None when incomplete evidence prevents a trustworthy number. Status checks use
exact integer microseconds. Diagnostic minutes use an explicit 40-digit Decimal
context; nonterminating minute values are diagnostic approximations. Numeric
shortage is omitted when it cannot be represented exactly.

## Status, purity and candidate validation

Missing/stale/unsupported inputs or stale declared current version -> UNKNOWN.
Otherwise target HARD violations/shared resource conflicts -> INFEASIBLE.
Otherwise an explicit hypothesis -> CONDITIONAL pending required authorization
or customer agreement. Otherwise -> FEASIBLE for this snapshot/time/fixed booking.
SOFT preferences do not make hard-feasible schedules infeasible. Material COVERED
alone cannot establish overall FEASIBLE.

Proposals change only target quantity/deadline/start in a private validated copy.
They preserve original commitment/snapshot versions and retain evidence. Existing
batch ATP/BOM is reused unchanged with every competing commitment. New/increased
material shortages for competitors reject the candidate through before/after
calls to that same ATP. This is pure candidate validation, not Phase 4 graph,
events or risk propagation. Proposals cannot insert stock, promote quotes, delete
jobs or update lifecycle state. P3/P5 command-side locking and execution-time
revalidation remain mandatory; query calls never reserve stock across plans.

## Core constraints and blocked output adapter

All constraints are actual `app.core.schemas.ConstraintReason` objects, with
Core FeasibilityState and SolverStatus. No P5 schema is modified.

| Local result | Shared mapping |
|---|---|
| Target material shortage | MATERIAL_SHORTAGE, SKU resource, exact shortage/base unit, material-need deadline, HARD, row evidence |
| New competitor shortage under proposal | HYPOTHETICAL_COMPETING_MATERIAL_SHORTAGE, SKU resource, candidate shortage/base unit, competitor material deadline, HARD, row evidence |
| Work/resource/job constraint | specific code/resource, exact missing minutes if representable, minutes unit when numeric, deadline where applicable, HARD, relevant evidence |
| Missing/stale/unsupported data | specific code/resource, no invented shortage/unit, INFORMATIONAL, available evidence |
| Finish preference | PREFERRED_FINISH_MISSED, SKU, preferred deadline, SOFT, plan/process evidence |
| Hypothesis approval | HYPOTHETICAL_CHANGE_PENDING_APPROVAL, target ID, INFORMATIONAL, proposal evidence |

Detailed required/usable/reserved/incoming quantities, allocations, times and
resource sharing stay in local materials/capacity results. Core constraint
objects follow Core's mutable contract, but each evaluation creates fresh output:
mutating an output cannot affect inputs or subsequent evaluations.

**BLOCK-P2-P3-001 / P5:** FeasibilityAssessment requires nonempty
affected_commitment_ids but no verified decision defines its meaning for ordinary
single-commitment FEASIBLE/UNKNOWN/CONDITIONAL/INFEASIBLE results. User explicitly
confirmed the ambiguity and forbade inserting the target by default. Therefore
EvaluationResult has no affected IDs and carries
`shared_output_blocker=P5_AFFECTED_COMMITMENT_IDS_SEMANTICS`; it is not a
FeasibilityAssessment. P5 must define assessed-vs-impacted semantics for all four
statuses, including safe/unknown cases. Only then can P2 implement the adapter.

**BLOCK-P2-P3-002 / P3:** confirm ProposedChanges serialization and fixed-booking
query usage. Supply substitution needs reviewed provenance/conditional types;
arbitrary JSON additions are rejected. No P3 code changed or agreement claimed.

**BLOCK-P2-P3-003 / P2+P5:** shared demo uses tenant_demo_01/com_001 and BURGER ->
BUN/PATTY/SAUCE/PACKAGING; existing P2 fixtures use tenant-synthetic-p2/com-001
and WRAP. Shared snapshot summary lacks full source freshness, lots, reservation
owners, typed supplier evidence, competing demand, exact calendars, processes,
jobs and transport evidence. Review data adapter and fixture/catalog extensions
together. Keep missing data UNKNOWN; do not replace shared fixtures or invent facts.

Host pytest 9.1.1 is outside P5's declared >=8.3,<9 range; dependencies unchanged.
Validation is in P2_PHASE_REPORTS.md. Stop for external review; Phase 4 is gated.
