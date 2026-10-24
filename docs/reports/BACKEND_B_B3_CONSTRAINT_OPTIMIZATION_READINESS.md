# Backend B B3 — shared constraint and optimization readiness

**2026-10-24 SGT. Outcome:** A pure confirmed-portfolio **baseline precondition** was added. It reuses P2's own ATP and capacity functions and exposes blockers. It does not evaluate pending orders, jointly select orders, allocate stock, optimize, reserve, or accept. With any pending request IDs the result is `PENDING_TARGET_UNSUPPORTED`, regardless of a covered confirmed baseline.

## 1. Git and source baseline

Existing worktree `C:/Users/User/OneDrive/Documents/sdc hackathon 2026/MouManTAI-backend-b-b1-readiness`, branch `feat/backend-b-b1-readiness`, HEAD and latest fetched `origin/main` both `3efa7f23fc2842664f1164cc1dce363f7371bdd3`. PR #48 HEAD `741976d3cdd59352d66a30c5712ce9eca5d3bc16`; stacked PR #49 HEAD `62040da02b4ec3532ea02d734567e0913996ec2b`; neither changed on this fetch. No other relevant changed main file appeared. No merge/cherry-pick, reset, stash, clean, commit or push. Original P3, Phase 0/0.1 and PR #48 review worktrees, three interrupted untracked Phase 1A files, and B1/B2 code/reports remain preserved. The six v2.2 pack documents are the product target; prior [B1](BACKEND_B_FEASIBILITY_RESERVATION_READINESS.md), [B2](BACKEND_B_B2_PENDING_ORDER_FEASIBILITY.md), [A/B handoff](BACKEND_AB_CONTRACT_HANDOFF.md) and [PR #48 reconciliation](../../../MouManTAI-phase1a-pr48-reconciliation/docs/reports/PHASE_1A_PR48_RECONCILIATION.md) provide the preceding evidence.

## 2. Exact P2 reuse map

| Source | Canonical semantics and B3 decision |
|---|---|
| `feasibility/models.py:119-169,210-235,327-~555`; `production.py:38-150` | Tenant-scoped source observations/freshness, lot/expiry, reservation ownership, BOM, calendars, confirmed demand, production sources/jobs/plans, snapshot/current version. Reuse immutable typed snapshot. Reader/provider authenticity still requires P5. |
| `feasibility/bom.py:~40-102` | Exact per-line BOM expansion across **confirmed** commitments, unit conversions, purchased leaves and source refs. Reuse in P2; no pending target input. Unknown SKU/unsupported routing must not be omitted. |
| `feasibility/inventory.py:19-~210`, `materials.py` | Time-phased batch ATP, lot eligibility/expiry, reservation protection, verified incoming evidence, deterministic allocation order and UNKNOWN/SHORTAGE/COVERED. B3 calls `calculate_atp` unchanged; it does not implement stock arithmetic. ATP allocation order is a current P2 calculation policy, **not** an approved FCFS order-decision policy. |
| `feasibility/capacity.py:62-~300` | Fixed non-preemptible jobs, explicit working windows, process/setup/lead times, deadlines and shared resource overlap. B3 calls `check_capacity` unchanged. INFEASIBLE for a supplied fixed plan does not prove every alternative schedule impossible. |
| `feasibility/service.py:101-~258` | Target-specific merged feasibility and allocation-dependence uses one confirmed Core commitment with matching single line; rejects unconfirmed/multi-line mapping. Future provisional/portfolio target needs P2-reviewed extension, never fake `CONFIRMED`. B3 does not alter it. |
| `feasibility/persisted_sources.py:123-163`, `currentness.py:11-25` | Tenant-scoped persisted current reader and version token. B3 pure function receives a snapshot; caller must use trusted reader and recheck at decision. |
| `core/models.py:113-146`, `core/reservations.py:226-355` | Local P3 resource stock/reservation rows, conditional update and tenant/key idempotency. They are separate from P2 lot/BOM/production evidence and not an order/portfolio reservation port. B3 does not call them. |

## 3. Implemented precondition and coverage

Added `backend/app/feasibility/portfolio_readiness.py`: `inspect_portfolio_inputs` takes tenant, optional P2 `EvaluationSnapshot`, aware check time and zero or more **lookup-only** pending request IDs. It rejects missing/current-version-conflicting/cross-tenant/future/provenance-incomplete snapshots. It revalidates a copied snapshot at the check time, then calls unchanged `calculate_atp` and `check_capacity` over **existing confirmed demand**. It reports `BASELINE_COMPLETE`, `BASELINE_BLOCKED`, `UNKNOWN` or `PENDING_TARGET_UNSUPPORTED`, P2 issue/constraint codes and evidence refs. It does not call `evaluate` with a synthetic Commitment. Its structural output fixes `profit_strategy_available`, `expiry_strategy_available` and `allocation_authorized` to false; no candidate details, price/cost evidence or approved expiry objective enter this function.

`BASELINE_COMPLETE` means only that the **supplied confirmed baseline** is covered under these P2 checks. It says nothing about an unaccepted order. `BASELINE_BLOCKED` means P2 sees shortage or hard fixed-capacity failure in that baseline. `UNKNOWN` keeps missing/stale source, untrusted snapshot token or incomplete P2 evidence unresolved. P2-reported resource conflicts are diagnostic; no new overlap formula exists. Missing/invalid lot expiry can prevent a future expiry strategy even if current P2 ATP deems a lot usable under its existing policy. Profit additionally needs approved selling price **and complete scoped cost** (material, labour, delivery and joint costs), not a quoted amount alone. The P2 snapshot contains no vetted margin model, so Profit is unavailable.

Positive/negative tests in `backend/app/feasibility/tests/test_portfolio_readiness.py` cover a complete confirmed baseline, absent/wrong tenant/missing or stale version/future/provenance input, stale sources, unknown job ledger, material shortage, fixed capacity conflict, two competing confirmed commitments, absent lot and lot-expiry evidence, unavailable Profit/Expiry strategies, pending IDs never gaining a portfolio feasibility result, and immutable inputs. The P2 existing tests cover BOM, expiry, unit, reservation and source cases independently. B3 tests do **not** claim pending-order material/plan mapping, valid multi-line candidate handling, profit optimization, or an authorized live inventory source. Those remain unsupported and documented, not silently simulated.

The module imports only P2 models and pure P2 calculators plus a Core enum. It takes no DB session/provider/actor, returns no command/receipt and has no writer. Tests compare the original snapshot JSON before/after evaluation. This supports a no-write claim for this function, not for a future optimizer or acceptance endpoint.

## 4. Constraint coverage and future shared ConstraintSpec

A future **versioned P2-owned `ConstraintSpec`** should reference the trusted snapshot ID/version/time, tenant, fixed confirmed commitments and authoritative reservations; candidate request/terms IDs and versions; each line's SKU/variant/unit/quantity/BOM path/material-use time/warehouse; eligible lots with expiry, provenance and reservation owner; confirmed incoming receipts/cutoff; production process/resources/job horizon/calendars/transport lead; required evidence refs and known/unknown flags. It should carry exact Decimal/integer scaling rules and deterministic constraint IDs. Backend A provides verified candidate/terms and customer agreement lineage; P2 maps operational facts; P5 owns authenticated readers, version locks and write authority. This is a **proposal**, not a new shared DTO or implemented solver. Multi-line, missing BOM, unknown lot expiry, unknown stock/capacity or unsupported routing must produce an explicit blocker instead of dropping a line.

Proposed advisory pipeline:

```text
Frozen, version-bound pending-order portfolio + fixed accepted demand
  → trusted current operational snapshot and evidence
  → one P2 ConstraintSpec/semantic mapping
  → FCFS / Profit / Expiry-aware search strategies
  → whole projected portfolio and each selected order revalidated by P2
  → ranked advisory options with exclusions, evidence and solver status
  → explicit authorized SME selection (later command)
```

FCFS needs an agreed request-time/priority basis and deterministic sequential admission using P2; it is not the current ATP allocation order. Profit needs approved, versioned unit prices and complete incremental cost. Expiry-aware needs verified lot expiry, FEFO-compatible allocation and an agreed objective. Any CP-SAT candidate must be translated back into the **same P2 lot/time/resource semantics**, checked jointly against fixed accepted demand and then checked per selected order in that joint projection. Separate FEASIBLE calculations can double-spend the same lot or machine. A mismatch yields `VALIDATION_MISMATCH` and suppresses the recommendation. No strategy may call reservation or acceptance. No OR-Tools dependency or solver was added because the shared spec and source authority are not approved.

| Future condition | Advisory outcome |
|---|---|
| Missing approved price or scoped cost | `PROFIT_COMPARISON_UNAVAILABLE`; other strategies only if their own facts are complete. |
| Multi-line mapping absent; unknown BOM/stock/expiry/capacity | `UNSUPPORTED_MULTI_LINE` or `UNKNOWN_INPUT`; never zero demand or unlimited supply. |
| Snapshot/current terms changed during computation | `STALE_SNAPSHOT`/`STALE_TERMS`; discard result and reload. |
| Solver timeout or no feasible portfolio | `TIMEOUT/UNKNOWN` or `INFEASIBLE`, with no implied order rejection. |
| Solver allocation conflicts with P2 projected validation | `VALIDATION_MISMATCH`; suppress ranked choice. |
| Two orders compete for one lot or resource | Joint P2 check must select a compatible subset or return contention/exclusions; no double allocation. |

## 5. Test results and limits

Local Windows Python 3.14, `PYTHONDONTWRITEBYTECODE=1`, `DATABASE_URL=sqlite+pysqlite:///:memory:`, `MOUMANTAI_SYNTHETIC_MODE=1`, `REQUIRE_POSTGRES=0`. From `backend/`, commands used `-p no:cacheprovider -q -o addopts= --disable-warnings --tb=short` and unique `--basetemp` paths under `C:\Users\User\.codex\tmp`.

| Run | Result |
|---|---|
| `python -m pytest ... app/feasibility/tests/test_portfolio_readiness.py` | **12 passed**, 0 failed/errors/skipped. |
| `python -m pytest ... app/feasibility/tests tests/test_resource_reservations.py tests/test_p5_integration_recovery.py tests/test_outbox_events.py` | **356 passed**, 0 failed/errors/skipped, 4 warnings. Includes B1/B2/B3, P2, local reservations and relevant P5/outbox tests. |

This is fixture-based deterministic validation, not proof of real business inventory accuracy or PR #48/#49 CI. No PostgreSQL integration (no explicitly authorized disposable DB), full backend, frontend, live provider/Orbyte, solver, pending-order happy path or browser E2E was run. No shared DB/schema, API, Core/Auth/Outbox or source-of-truth implementation was changed.

## 6. Owner decisions and smallest B4 slice

The [handoff §7](BACKEND_AB_CONTRACT_HANDOFF.md) gives Meishuet a concise review request: exact persisted candidate/evidence fields, version/identity re-reads and distinct OrderDecision states. Backend A/P1/P4 must settle the persisted candidate, mapper, material-use/delivery interpretation, price/disclosure/assent and PR #48 fixes. P2 owner must approve a provisional target and multi-line/BOM/capacity semantics; P5 must approve authenticated operational reader, reservation owner, version lock, Core/outbox and any shared contract. Product/owners must settle FCFS time basis, complete Profit cost and Expiry objective/evidence. S1 approval from this chat is recorded in prior reports; S2–S5 are not assumed approved. The A/B ownership agreement does not grant shared-schema or live-operation authority.

**Smallest B4 slice:** after A/P2/P5 agree a pure provisional-target shape and evidence mapping, extend P2's existing calculators through **one reviewed read-only projected-portfolio input** with fixed confirmed demand, initially a single validated pending line. Test omission, expiry, stock, capacity, contention, stale versions and no writes; jointly revalidate the projected batch. Continue to return unsupported for multi-line until its semantics are reviewed. No optimizer, acceptance or reservation in that slice. If the candidate/operational mapping remains unfinished, first complete its contract review rather than fabricate a positive projection.
