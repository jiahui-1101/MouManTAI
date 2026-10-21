# Phase 4 — Dependency Graph and Incremental Impact Plan

**Goal:** Discover only same-tenant commitments dependent on changed operational resources, re-evaluate them with the existing pure P2 evaluator, and classify proven adverse deltas conservatively.

**Architecture:** A P2-local immutable dependency graph links evidence-backed supplier deliveries, material SKUs, production resources and bookings, orders, and commitments. A typed change request selects candidates by resource key; each candidate is evaluated against the before and after snapshots through `app.feasibility.service.evaluate`. Results and canonical-envelope event intents remain in memory and are never published or persisted in this phase.

**Tech stack:** Existing Python 3.14 runtime, Pydantic v2, pytest, P2 snapshot/BOM/ATP/capacity models, P5 `Commitment`, `ConstraintReason`, `DomainEvent`, and enums. No dependency or shared-contract change.

## Global constraints

- Work only on `feat/p2-feasibility-engine`; do not modify P5 schemas, migrations, routes, UI, or authoritative Core state.
- Reuse `evaluate()` for every candidate and preserve its Phase 3 evidence-versus-allocation precedence.
- `UNKNOWN` is not unaffected or impacted; fixed-booking failure does not prove every reschedule impossible.
- An unchanged pre-existing shortage is not a new impact. Material-only supplier fixtures report their measured shortage deltas separately from full-feasibility classification.
- Keep tenant, snapshot, commitment, evidence, dependency path, deterministic order, and input immutability visible in local results.
- Event values are future intents only; P5 still owns event persistence, deduplication, and Core transitions.

## Task 1 — Lock observable impact behavior with tests

**Files:** create `tests/test_impact.py`; extend `production_fixtures.py` only with independently evidenced synthetic fixtures needed for complete feasibility.

- Test buffered supplier change candidate discovery and the actual 40/0 pcs material shortage delta; because those snapshots lack production evidence, both candidate classifications remain UNKNOWN.
- Test the two-affected material fixture's 70/40 pcs deltas separately from its UNKNOWN full-feasibility classifications.
- Test a complete-production buffered scenario where the delayed supplier makes the first commitment INFEASIBLE and the later commitment remains FEASIBLE with evidence-backed time/capacity buffer.
- Test a resource-keyed capacity/job change, candidate exclusion for unrelated commitments/tenants, stale or missing evidence, allocation uncertainty, an unchanged pre-existing shortage, version rejection, deterministic replay, and snapshot/Core input non-mutation.

**RED command:** from `backend/`, run `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_impact.py -q -p no:cacheprovider`; new behavior must fail because `app.feasibility.impact` does not exist yet.

## Task 2 — Implement P2-local graph, impact comparison, and event intents

**File:** create `backend/app/feasibility/impact.py`.

- Define validated tenant-bound resource keys, evidence-bearing dependency nodes/edges, a deterministic graph, typed change requests, material/constraint deltas, impact classifications, result objects, and `DomainEvent` intent objects.
- Build dependencies from the supplied snapshot, recursive BOM, production process/resource/plan/job evidence, and supplied Core commitment/order identities. Index traversals by changed resource; use a same-tenant conservative fallback only when required graph evidence is incomplete and mark those results UNKNOWN.
- Validate before/after tenant and snapshot versions, event type/resource-kind pairing, actual changed rows, and event evidence references. Reject stale or fabricated change notifications.
- Evaluate every discovered candidate before and after with the same P2 `evaluate()` function. Compute shortage and HARD-constraint deltas from those results; classify only fully evidenced adverse deltas as confirmed impact, preserve unchanged pre-existing failures separately, require positive measured buffer for verified-unaffected, and retain UNKNOWN for incomplete or allocation-ambiguous cases.
- Emit deterministic, idempotency-keyed P2-local intents for `commitment.feasibility_assessed`, `commitment.at_risk` only on a known transition into infeasibility, `operational.impact_updated`, and `operational.insufficient_data`; do not publish them.

## Task 3 — Verify, document, and checkpoint

**Files:** update `P2_PROGRESS.md`, `P2_REQUIREMENT_TRACE.md`, `P2_PHASE_REPORTS.md`, `PHASE4_HANDOFF.md`, and only the P2 entries in `docs/TEAM_LOG.md`.

- Run the focused Phase 4 tests and the combined existing Phase 1–3 plus shared backend regression set.
- Record actual output classifications, measured material deltas, exact commands/counts, and limitations; keep P5 adapter and empty Impact Set support blocked.
- Inspect `git diff --check`, staged paths, and final branch/ref state. Create one local Phase 4 commit and stop for independent review before Phase 5.

## Acceptance boundary

This phase can prove local candidate discovery, before/after calculation deltas, and conservative P2-local classifications for the supplied snapshots. It cannot prove external source authenticity, durable idempotency, a current database snapshot race check, P5 shared assessment serialization, event publication, or authoritative risk-state transitions.
