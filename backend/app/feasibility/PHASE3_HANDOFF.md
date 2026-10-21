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

Status precedence distinguishes evidence reliability from allocation policy:

1. Missing, stale, incomplete, unsupported or stale-version evidence -> UNKNOWN,
   even if a constraint that would otherwise be HARD is present. The evaluator
   preserves that constraint, but does not treat untrusted data as proof.
2. With complete and trustworthy evidence, an independently proven HARD failure
   -> INFEASIBLE for the evaluated target or supplied fixed booking. This includes
   a proven residual material shortage, capacity/deadline violation or job conflict.
   A capacity/job HARD result says the supplied schedule conflicts; it does not
   establish impossibility under every alternative rescheduling plan.
3. With no independent HARD proof, a shortage that could be covered only by
   changing provisional ATP priority -> UNKNOWN. It neither reprioritizes demand
   nor authorizes displacement.
4. Otherwise an explicit hypothesis -> CONDITIONAL pending identified required
   authorization or customer agreement. Otherwise -> FEASIBLE for this
   snapshot/time/fixed booking.

SOFT preferences do not make hard-feasible schedules infeasible. Material COVERED
alone cannot establish overall FEASIBLE. Independent HARD proof takes precedence
over allocation-policy uncertainty only when the relevant evidence is complete
and trustworthy; evidence/data uncertainty retains conservative UNKNOWN
precedence. When trusted independent HARD proof makes the overall status
INFEASIBLE while allocation policy remains unresolved, `solver_status` remains
UNKNOWN to preserve that unresolved calculation detail.

Proposals change only target quantity/deadline/start in a private validated copy.
They preserve original commitment/snapshot versions and retain evidence. Existing
batch ATP/BOM is reused unchanged with every competing commitment. New/increased
material shortages for competitors reject the candidate through before/after
calls to that same ATP. This is pure candidate validation, not Phase 4 graph,
events or risk propagation. Proposals cannot insert stock, promote quotes, delete
jobs or update lifecycle state. P3/P5 command-side locking and execution-time
revalidation remain mandatory; query calls never reserve stock across plans.

### Allocation-dependent material shortage

A target's provisional ATP shortage is not automatically a HARD target failure.
P2 examines the existing ATP allocations for the same SKU/base unit and counts
only currently allocated LOT/confirmed RECEIPT quantities that are still
eligible for the target's material-use time and warehouse. Active reservations,
expired lots, late receipts and location-ineligible supply remain unavailable.
No supply is reallocated and no confirmed commitment is reprioritized.

If compatible supply already allocated to other demand could cover the target,
the evaluator emits `ALLOCATION_DEPENDENT_MATERIAL_SHORTAGE` as INFORMATIONAL,
reports the current batch aggregate shortage with row evidence. If this is the
only unresolved feasibility issue, the result is UNKNOWN. If complete, trusted
evidence also proves an independent HARD failure, that result is INFEASIBLE while
retaining the allocation-dependency constraint. It does not treat hypothetical
displacement as approval or use CONDITIONAL. If all target-eligible allocated
supply still leaves a positive minimum shortage, `MATERIAL_SHORTAGE` remains
HARD with that proven minimum. ATP's allocation algorithm and its evidence remain
unchanged. A proposal that increases another confirmed commitment's shortage
still receives a HARD `HYPOTHETICAL_COMPETING_MATERIAL_SHORTAGE` from the
baseline/candidate ATP comparison.

## Core constraints and blocked output adapter

All constraints are actual `app.core.schemas.ConstraintReason` objects, with
Core FeasibilityState and SolverStatus. No P5 schema is modified.

| Local result | Shared mapping |
|---|---|
| Proven target-level material shortage after compatible alternate allocations | MATERIAL_SHORTAGE, SKU resource, proven minimum shortage/base unit, material-need deadline, HARD, row evidence |
| Shortage coverable only by supply currently allocated to competing demand | ALLOCATION_DEPENDENT_MATERIAL_SHORTAGE, SKU resource, current ATP batch aggregate shortage/base unit, material-need deadline, INFORMATIONAL, row evidence; overall UNKNOWN |
| New competitor shortage under proposal | HYPOTHETICAL_COMPETING_MATERIAL_SHORTAGE, SKU resource, candidate shortage/base unit, competitor material deadline, HARD, row evidence |
| Work/resource/job constraint | specific code/resource, exact missing minutes if representable, minutes unit when numeric, deadline where applicable, HARD, relevant evidence |
| Missing/stale/unsupported data | specific code/resource, no invented shortage/unit, INFORMATIONAL, available evidence |
| Finish preference | PREFERRED_FINISH_MISSED, SKU, preferred deadline, SOFT, plan/process evidence |
| Hypothesis approval | HYPOTHETICAL_CHANGE_PENDING_APPROVAL, target ID, INFORMATIONAL, proposal evidence |

Detailed required/usable/reserved/incoming quantities, allocations, times and
resource sharing stay in local materials/capacity results. Core constraint
objects follow Core's mutable contract, but each evaluation creates fresh output:
mutating an output cannot affect inputs or subsequent evaluations.

**BLOCK-P2-P3-001 / P5:** P5 confirmed `affected_commitment_ids` is the actual
Impact Set, not assessment scope; this semantic decision is RESOLVED. The current
Core schema still requires at least one ID (`min_length=1`), so an empty actual
Impact Set cannot yet be serialized. P5's schema update to allow `[]` is PENDING
merge and verification. P2 does not fabricate IDs or edit shared schemas;
`EvaluationResult` has no affected IDs and carries
`shared_output_blocker=P5_AFFECTED_COMMITMENT_IDS_EMPTY_SCHEMA_SUPPORT`. The
final shared `FeasibilityAssessment` adapter remains BLOCKED until P5's change is
merged and verified.

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
Validation is in P2_PHASE_REPORTS.md.

## Phase 4 local impact extension

`EvaluationResult` now exposes `evidence_complete` separately from
`allocation_dependent`. These P2-local flags preserve the Phase 3 rule that
missing/stale evidence dominates, while an independently evidenced HARD
constraint is not masked by allocation-policy uncertainty. They are output
metadata from the same `evaluate()` function; P3 should continue to consume the
same evaluator and not implement a separate rule engine. The final shared
assessment mapping is still blocked by P5's empty actual Impact Set support.

Phase 4 candidate discovery, before/after results, impact classifications and
future event intents are documented in `PHASE4_HANDOFF.md`. No route, event
publication, persistence or authoritative Core update was added. Stop for
independent Phase 4 review; Phase 5 is not started.
