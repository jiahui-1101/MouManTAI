# P3 Final E2E evidence report — 2026-10-22

**Verdict: P3 PARTIAL / BLOCKED.** This is a record of executed checks, not a claim that the required live journey passed. Candidate branch: `integration/p3-live-e2e-candidate`, based on `origin/main` `7baffd551f7d01fcbddcbc7ca175aa5547ded03a`. Integrated checkpoints: Core `53c213f` (candidate `624967f`), P3 foundation `ae0e4db5` (merge `c4f6a62`), demo `08591cad` (merge `a27b0f5`). Final local checkpoint SHA is supplied with the handoff after commit.

| Requested evidence | Observed result |
|---|---|
| Environment and database | Windows / PowerShell. `TEST_DATABASE_URL` and `TEST_DATABASE_APPROVED` absent. Docker CLI installed, but `docker info` cannot reach `npipe:////./pipe/dockerDesktopLinuxEngine`; `docker desktop start` did not make the engine usable. No database contacted or created. PostgreSQL dialect and applied revision **NOT VERIFIED**. |
| Migration lineage | `python -m alembic heads` reports one code head: `0007_recovery_case_constraints_alignment`. This is graph inspection, not applied-database evidence. P4's proposed 0008 is not on main. |
| Service/container start commands | `docker desktop start` attempted; `docker info --format '{{.ServerVersion}}'` failed. No container, backend server, worker, or frontend server was started for live E2E. |
| Synthetic seed and initial Commitment | Portable P3 test uses `contracts/fixtures/demo_dataset.json` to construct an assessment, then inserts a synthetic `tenant_p3_source / com_p3_source` CONFIRMED v1 Core record and calls real `CommitmentService.assess()`. This does **not** establish a persisted P2 operational source or initial FEASIBLE evaluation. |
| Supplier change and assessment | Test causation ID `evt_supplier_change_source` and assessment ID `fa_p3_source` are synthetic test inputs; no persisted BEFORE/AFTER supplier fact or P2 recomputation ran. |
| Core risk and outbox | Portable test verifies real Core `NORMAL → AT_RISK` v1→v2, durable SQLite audit/outbox, exact assessment ID, snapshot ID `snap_p3_source`, evaluated version and evidence. Generated event ID is asserted through the persisted row; no fixed ID or PostgreSQL proof claimed. |
| P3 Case, Trigger, processed event | In explicitly registered isolated SQLite dispatcher test, P3 resolves exact persisted Core audit/outbox provenance, persists Case and Trigger, and the dispatcher commits `p3.recovery_trigger.v1` processed marker. Duplicate dispatch creates no second trigger. Missing audit fails with no Case/Trigger/Processed row; injected consumer failure rolls all three back, then retry succeeds. Production subscriber is not registered. |
| Plans and recommendation | Existing P3 synthetic planner/component tests pass. No plans were generated from current persisted P2 operational inputs; no two-option live validation or policy recommendation is claimed. Plan IDs/statuses for live E2E: **NOT RUN**. |
| Manager Approval | Durable P5 approval producer/lookup and trusted actor context absent. Approval evidence ID: **NONE**. Public Core legacy execution remains fail-closed. |
| P4 communication and confirmation | P4 migration 0008/routes are not on main or approved into this candidate. Request and confirmation IDs: **NONE**. SENT/ACCEPTED/FULFILLED live chain: **NOT RUN**. |
| Synthetic action and receipt | No live action was executed. Action ID and receipt: **NONE**. Existing synthetic fixture tests do not establish durable authority or live outcome. |
| Final business state | No PostgreSQL hero scenario was seeded. SQLite provenance tests end with Core AT_RISK and a P3 Case/Trigger; fulfilment is not asserted or changed. |
| UI | `/recovery/:id` component now requests trigger-only data when full case lookup reports pending trusted inputs and keeps plans/actions unavailable. `/recovery/demo` remains an explicitly synthetic read-only walkthrough. Component tests ran; no browser or real API/UI E2E was performed. |

## Executed checks

- From candidate `backend`: `python -m pytest tests app/feasibility/tests -q -p no:cacheprovider` exited **0** after P3 trigger work; the two opt-in PostgreSQL tests skipped. `python -m pytest tests/test_recovery_persisted_provenance.py -q -p no:cacheprovider` returned **7 passed**. P3 source and test files passed scoped Ruff `--select F,E4,E7,E9` and `compileall`.
- From candidate `frontend` after the three checkpoint merges: `npm test -- --run` returned **223 passed, 5 skipped**. After the trigger-only UI change, its focused component file returned **6 passed**. A full run then had one unchanged P2 recalculation test time out (**1 failed, 223 passed, 5 skipped**); that test passed in isolation and the next full run returned **224 passed, 5 skipped**. `npm run typecheck` and `npm run build` passed. No P2-owned file was changed.
- PostgreSQL migration suite, real backend HTTP, outbox worker restart, frontend browser journey, and negative live E2E cases N1–N15: **NOT RUN**. Portable tests cover selected analogous boundaries only; they are not counted as live negative E2E results.

## Blocking handoffs

1. **BLOCK-P3-E2E-001 — P2/P5:** P2 public dependencies return `None` for trusted source/assessment/processor services, and the router is unmounted. Supply persisted synthetic operational BEFORE/AFTER snapshots and exact source assessment path; do not use `build_production_example()` as authority.
2. **BLOCK-P3-E2E-002 — P5:** Approve and implement durable Manager Approval, trusted test-mode actor registry and current read-only authority lookup. Coordinate an additive migration for durable P3 plans/decisions/actions. Do not remove Core's execute guard.
3. **BLOCK-P3-E2E-003 — P4/P5:** Review and integrate P4 0008 lineage/routes and exact versioned communication/confirmation contracts. No P4-owned module was changed in this candidate.
4. **BLOCK-P3-E2E-004 — environment:** Provide an approved isolated PostgreSQL test URL or a working disposable local Docker engine. Then run Alembic, migration constraints, live HTTP/worker/UI hero and N1–N15 negatives with sanitized persisted IDs.

P5 should review Core candidate commit `624967f`, the merge routing and TEAM_LOG conflict resolution, and the P3 persisted proof/trigger status before any subscriber activation or shared merge. No P5 sign-off, push, PR #10 synchronization, or main merge is claimed.
