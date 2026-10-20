# P2 Phase Review Reports

## Phase 0 — Inspect + Contract Trace

- **State:** PARTIAL (Phase 0 artifacts are prepared; P5-owned contract decisions remain open.)
- **Date:** 2026-10-21
- **Branch:** `feat/p2-feasibility-engine`
- **Commit SHA:** see phase response.
- **Initial Git state:** clean `main` at `aedb152`, matching `origin/main`; new P2 branch created from that commit. No unrelated edits were present.
- **Dirty status at report preparation:** expected changes are this report, progress, trace and P2-only team-log rows; final post-commit status will be recorded in the phase response.

### Inspection findings

- The designated clone at `D:\dunno\0.SDC\MouManTAI` was the Git root. `origin` is `https://github.com/jiahui-1101/MouManTAI.git`; local/remote branch inventory contained only `main`/`origin/main` before creating the requested branch.
- Actual tracked project files before this phase were `README.md`, `docs/AGENTS.md`, `docs/REQUIREMENTS_SYSTEM.md`, and `docs/TEAM_LOG.md`. There is no backend/frontend skeleton, P2 module, shared `contracts/`, or test suite. No assumption was made that the skeleton exists.
- The actual local P2 requirements file and P1/P3/P5 owner requirements were read from the authorized parent workspace. They remain outside the Git repository and were not copied or modified.
- The P2 reference copy in Appendix A was normalized for its closing separator and compared line-by-line with the actual local P2 file; they match. The trace follows the actual local source.
- `docs/REQUIREMENTS_SYSTEM.md` supplies the canonical assessment base shape, the pure internal route, event envelope, lifecycle invariants, and P2→P3/P5 handshake. P3 explicitly requires reuse of `POST /internal/feasibility/evaluate` or the same pure library. P5 owns contracts, authentication, shared database, outbox, and authoritative state transitions. No P5 implementation is present to finalize additive fields or public route wiring.

### Changes and trace evidence

- Created `backend/app/feasibility/P2_REQUIREMENT_TRACE.md` with individual P2 requirement rows, applicable shared-system requirements, implementation/test paths, truthful status, and explicit P3/P5 ownership/blockers.
- Created `backend/app/feasibility/P2_PROGRESS.md` with the branch/repo baseline, gated phase board, provisional pure evaluator and event contract, P3 handoff example, synthetic scenario, and exact open decisions.
- Appended this Phase 0 checkpoint to `backend/app/feasibility/P2_PHASE_REPORTS.md`.
- Updated only the P2 rows in `docs/TEAM_LOG.md`; P1/P3/P4/P5 entries and shared decision history were left untouched.
- The provisional scenario uses the shared example `BURGER` SKU: `com_001` needs 100 patties by `09:00`, with 60 unreserved on hand and 40 confirmed inbound originally due `08:00`; `com_002` has 20 units reserved from the 80 on-hand, and needs them the following day. Moving the delivery ETA to `11:00` makes the expected `com_001` shortage 40 while `com_002` remains buffered. A separate 100+40 demand / 30 on-hand / 110 inbound fixture is proposed for two affected commitments. These are hand-calculated fixture expectations only; no evaluator exists and no runtime output was observed.

### Validation and tests

- **Tests:** NOT RUN, as explicitly required for Phase 0. No test command was invoked.
- **Inspection commands:** `git status --porcelain=v1`, `git remote -v`, `git branch --list`, `git branch -r`, `git log --oneline --decorate -n 12`, `git rev-parse --show-toplevel`, `rg --files -g '!\.git'`. Observed a clean initial tree, the stated Git root/remote, and only the four documentation/project files listed above.
- **Runtime/API/UI behavior:** NOT RUN / NOT IMPLEMENTED. The input/output and fixture examples in the report are contract proposals, not observed results.

### Trace status and remaining deficiencies

- Phase 0 inspection/contract mapping is recorded. Runtime acceptance criteria remain `NOT_STARTED` or `BLOCKED` in the trace; no P2 implementation criterion is marked PASS from documentation alone.
- P5 must confirm OperationalSnapshot and assessment extensions, tenant/auth/API integration, storage/outbox/events, canonical fixture types, and Core state update operations. P1/P5 must confirm SKU/BOM/units and normalized context inputs. P3 must confirm proposed-change serialization and import usage. P3/P5 own command-side reservations and concurrency proof.
- Highest-risk assumptions: the temporary shared example SKU can become the approved synthetic fixture; the hand-calculated 40-unit shortage depends on the reservation being counted exactly once and the material-use deadlines being adopted; the P2 additions to shared assessment/event payloads are not yet ratified.
- **Next phase:** Phase 1 operational snapshots and synthetic fixtures, only after the user returns `APPROVED — CONTINUE P2` following external review.

### Phase 0 external review update

- **Review result:** The user reported external approval of Phase 0 and authorized Phase 1.
- **Accepted scope:** The Phase 0 requirement trace and P2 Git scope were accepted. The reviewer requested that all P5 snapshot/assessment extensions remain provisional until P5/P3 approval, that P5 integration dependencies stay explicitly `BLOCKED` without stopping independent P2 work, that `P2-FE` be `NOT_STARTED` while no UI exists, and that the synthetic allocation/reservation/time rules be explicit.
- **Applied in Phase 1:** P2-FE is corrected to `NOT_STARTED`; fixture policy and evidence are documented; no shared contract, P5-owned file, route, migration, app skeleton, or P3 code was changed.

## Phase 1 — Operational Snapshots + Synthetic Data

- **State:** PASS for the P2-local Phase 1 deliverable. P5/P3 shared-contract and integration work remains explicitly BLOCKED.
- **Date:** 2026-10-21
- **Branch:** `feat/p2-feasibility-engine`
- **Starting commit:** `5368e0d docs(p2): trace feasibility phase 0 requirements`
- **Commit SHA:** see phase response.
- **Post-commit dirty status:** see phase response.

### Changes

- Added `backend/app/feasibility/models.py`: P2-local, frozen Pydantic v2 value objects for sources, normalized SKU/BOM, inventory lots, reservation ownership, incoming delivery confirmation state, capacity calendars, confirmed commitments/material-use times, and `OperationalSnapshot` identity/version/tenant/capture/cutoff fields. Snapshot validation checks duplicate IDs, tenant mismatch, source references/kinds, impossible relationships and quantities, unit mismatch, active reservations exceeding their lot, invalid capacity windows, freshness bounds, and impossible future source/confirmation timestamps. Expired lots remain auditable but are marked unusable; missing BOM/source and stale source evidence are preserved as structured incomplete status. All datetimes reject naive input; UTC instants are compared without inheriting the machine timezone. Models and nested collections are immutable.
- Added `backend/app/feasibility/fixtures.py`: two immutable before/after supplier ETA scenarios. One has `com-001` affected with a labelled 40 `pcs` shortage and buffered `com-002` unaffected; the F2-06 variant has both commitments affected. Labels are hand-calculated ground truth for future evaluator tests, not output from a Phase 1 engine.
- Added `backend/app/feasibility/FIXTURES.md`: explicit allocation priority `(material_use_at, commitment_id, commitment_version, line_id)`, active-reservation ownership/subtract-once semantics, cutoff/confirmed-receipt eligibility, material-use vs customer deadline, and offset-aware `+08:00`/UTC comparison rules. It identifies the rule and SKU/BOM fixture as provisional, not an approved business preference or global contract.
- Added `backend/app/feasibility/tests/test_snapshots.py` with 13 focused tests for versioning/immutability, tenant and source evidence, duplicates, exact quantity input, unit and reservation validation, expiry, missing/stale data, unconfirmed supply preservation, fixture labels, and offset-aware input/serialization.
- Updated `P2_REQUIREMENT_TRACE.md` with observed Phase 1 evidence and explicit pending integration statuses.
- Updated `P2_PROGRESS.md` with the approved Phase 0 gate, Phase 1 checkpoint/results, fixture policy, and the Phase 2 stop gate.
- Updated only P2 entries and the P2 QA record in `docs/TEAM_LOG.md`; set P2-FE to `NOT_STARTED` because no UI was implemented.

### Representative observed fixture/model output

- `build_supplier_delay_scenario()` returns a valid version 1 snapshot and a new valid version 2 snapshot under the same synthetic tenant. The confirmed patty delivery ETA changes from `2026-10-23T08:00:00+08:00` to `2026-10-23T11:00:00+08:00`; `com-001` needs material at `09:00`, while `com-002` needs it the following day at `09:00` and owns the 20-unit reservation from the 80-unit lot.
- The hand-labelled fixture result is `com-001`: shortage `40 pcs`; `com-002`: buffered/unaffected. The separate two-affected fixture labels `70 pcs` and `40 pcs`, totaling `110 pcs`, under its documented stable allocation order. These expected labels are fixture data only; no allocation/evaluation code ran.
- Model serialization retained `captured_at` as `2026-10-22T12:00:00+08:00` and inventory `Decimal('80')` as the decimal string `"80"`. A missing source/BOM yields `INCOMPLETE` with `MISSING_SOURCE`/`MISSING_BOM`; stale evidence yields `STALE` and `INCOMPLETE`; neither is translated to FEASIBLE/INFEASIBLE in this phase.

### Validation and tests

- `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q` — **PASS, 13 passed** (final focused run).
- The first test-first run of `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q` failed collection because `fixtures.py` had not yet been implemented; this was the expected red state. No repository tests existed before Phase 1.
- `python -m pytest backend/app/feasibility/tests/test_snapshots.py::test_snapshot_rejects_confirmation_evidence_from_after_capture -q` — first **FAIL as expected** before the capture-time check; after the check, **PASS, 1 passed**.
- `python -m pytest backend/app/feasibility/tests/test_snapshots.py::test_snapshot_retains_expired_lots_but_marks_them_unusable -q` — **PASS, 1 passed** after correcting the test to expire an unreserved lot; the validator correctly rejects an active reservation on an expired lot.
- `python -m pytest backend/app/feasibility/tests/test_snapshots.py::test_snapshot_rejects_naive_datetimes_and_compares_offset_aware_instants -q` — **PASS, 1 passed**.
- `python -m pytest backend/app/feasibility/tests/test_snapshots.py::test_snapshot_rejects_floating_point_inventory_quantities -q` — first **FAIL as expected** before exact-quantity validation; after the check, **PASS, 1 passed**.
- The first full focused run found 10 passed / 1 test-fixture failure (the expiry example also had an active reservation); this was corrected in test setup. The subsequent focused run passed all 11 then-present tests; after capture-time and float-input checks were added, the final run passed all 13.
- Full repository suite, API, UI, evaluator, P3/P5 integration, and E2E tests — **NOT RUN / NOT IMPLEMENTED**; the repository has no shared runtime/test skeleton and Phase 1 is limited to snapshots and fixtures.

### Requirement trace and safety

- Phase 1 P2-local evidence covers snapshot input shape, tenant/source provenance, freshness/validation state, immutable versioning, explicit receipt confirmation status, reservation ownership, lot expiry handling, deterministic fixture policy, and offset-aware time handling. Refer to trace rows `P2-BE01-01` through `P2-BE01-05`, `P2-DATA-02`, `P2-DATA-04`, `P2-DATA-05`, `P2-DATA-07`, `P2-DATA-09`, `P2-DATA-11`, `P2-HC-06`, and new `PH1-*` rows.
- The shared contract remains unchanged. The P2-local snapshot serialization and any future assessment/constraint/ProposedChanges additions remain provisional pending P5/P3 review. No actual stock reservation, supplier action, commitment agreement/risk/fulfilment write, persistence, event publication, or UI/API integration exists in this phase.
- P5 must still provide/ratify shared types, authentication/tenant context, source-of-truth adapters, persistence/version authority, outbox, route registration, and the Core operation for assessment/risk events. P1/P5 must approve SKU/BOM/unit fixture ownership. P3/P5 must confirm the hypothetical-change serialization/import and authorized command-side reservation integration.
- **Highest-risk open assumption:** the BURGER fixture and the deterministic allocation order are reproducibility rules for synthetic expected labels only; they must not silently become a shared contract or business trade-off.
- **Compact review assessment:** Snapshot objects are in-memory Pydantic v2 models, not durable operational snapshots. The tests verify P2-local validation and evidence retention; they do not prove ATP, feasibility, impact, persistence, authorization, or cross-feature behavior.

### Exact changed files

- `backend/app/feasibility/__init__.py`
- `backend/app/feasibility/models.py`
- `backend/app/feasibility/fixtures.py`
- `backend/app/feasibility/FIXTURES.md`
- `backend/app/feasibility/tests/test_snapshots.py`
- `backend/app/feasibility/P2_REQUIREMENT_TRACE.md`
- `backend/app/feasibility/P2_PROGRESS.md`
- `backend/app/feasibility/P2_PHASE_REPORTS.md`
- `docs/TEAM_LOG.md` (P2 rows/QA entry only)

**Next action:** Stop for external review. Phase 2 requires a later explicit `APPROVED — CONTINUE P2`.

## Phase 1 targeted review corrections

- **State:** PASS for the three requested P2-local corrections; Phase 1 remains stopped for external review. Phase 2 has not started.
- **Date:** 2026-10-21
- **Branch:** `feat/p2-feasibility-engine`
- **Starting commit:** `c3183b6 feat(p2): add validated operational snapshots and fixtures`
- **Correction commit SHA:** see phase response.
- **Post-commit worktree status:** see phase response.

### Review findings and changes

- **Capacity window bound:** `CapacityWindow` now rejects `available_minutes` greater than the elapsed window duration. The duration is measured between UTC-normalized instants using integer microseconds and compared as `Decimal`; the single-resource input does not assume unmodelled parallel capacity. A 60-minute window with 61 available minutes is rejected.
- **Commitment deadline consistency:** snapshot validation now rejects a commitment line whose `material_use_at` is after its parent `delivery_deadline`. The test moves `com-001`'s deadline to `08:59` while its material-use time is `09:00` on Oct 23, 2026 (+08:00), and receives a Pydantic validation error.
- **Buffered fixture calendar:** `build_supplier_delay_scenario()` now carries an Oct 24, 2026 07:00–17:00 (+08:00) window with 480 available minutes, alongside the existing Oct 23 window. A focused test checks every line's material-use instant for both commitments in both before/after snapshots. This verifies calendar coverage only; it does not claim full production feasibility or alter the expected supplier-delay/shortage labels.
- No shared contract, migration, route, app skeleton, or P5-owned code was modified. Existing P5/P3 contract and integration dependencies remain explicitly BLOCKED and do not prevent this independent P2 correction.

### Test-first evidence

- **Expected red run:** `python -m pytest backend/app/feasibility/tests/test_snapshots.py::test_buffered_fixture_has_capacity_calendar_coverage_for_both_material_use_times backend/app/feasibility/tests/test_snapshots.py::test_capacity_window_rejects_available_minutes_above_elapsed_duration backend/app/feasibility/tests/test_snapshots.py::test_snapshot_rejects_material_use_after_commitment_delivery_deadline -q` — **FAIL as expected, 3 failed**: `com-002` had no window coverage, excessive available minutes raised no error, and late material use raised no error.
- **Focused green rerun:** the same command — **PASS, 3 passed**.
- **Snapshot regression:** `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q` — **PASS, 16 passed**.
- No unrelated repository suite was run.

### Requirement trace, boundaries, and open concerns

- Correction evidence updates `P2-BE01-05`, `P2-DATA-09`, `P2-HC-06`, and `PH1-02` through `PH1-05` in `P2_REQUIREMENT_TRACE.md`. The P2 progress checkpoint and P2-only TEAM_LOG/QA evidence were also updated.
- Snapshot validation now proves capacity inputs do not exceed their elapsed calendar windows and that material-use deadlines are consistent. The fixture coverage assertion only establishes that each material-use instant falls inside a declared window; capacity scheduling, overlapping production jobs, and end-to-end promise feasibility are not implemented in Phase 1.
- P5 still owns shared snapshot/assessment contracts, persistence, authentication, routes, events/outbox, and authoritative Core transitions. P1/P5 fixture/SKU approval and P3/P5 ProposedChanges/evaluator integration remain pending. Phase 2 ATP/BOM work remains gated on external review.
- **Compact review assessment:** The requested defects have focused regression evidence. The P2 snapshot model remains provisional and in-memory; no evaluator or complete production-capacity calculation exists, and calendar coverage must not be read as a feasibility result.

### Exact correction files

- `backend/app/feasibility/models.py`
- `backend/app/feasibility/fixtures.py`
- `backend/app/feasibility/FIXTURES.md`
- `backend/app/feasibility/tests/test_snapshots.py`
- `backend/app/feasibility/P2_REQUIREMENT_TRACE.md`
- `backend/app/feasibility/P2_PROGRESS.md`
- `backend/app/feasibility/P2_PHASE_REPORTS.md`
- `docs/TEAM_LOG.md` (P2 status and QA evidence only)

**Next action:** Stop for external review. Do not begin Phase 2 until a later `APPROVED — CONTINUE P2`.

## Phase 1 confirmation-provenance review correction #2

- **State:** PASS for the requested P2-local evidence-provenance correction; Phase 1 remains stopped for external review. Phase 2 has not started.
- **Date:** 2026-10-21
- **Branch:** `feat/p2-feasibility-engine`
- **Starting commit:** `98ea9882a4cb27951ce78d14a19538cc162b8d58` (prior Phase 1 correction).
- **Correction commit SHA:** see phase response.
- **Push status:** pushed to `origin/feat/p2-feasibility-engine`; remote branch ref was verified to match local HEAD after push (exact SHA in phase response).
- **Post-push worktree:** verified clean on the feature branch.

### Evidence model and observed behavior

- Added P2-local `SupplierDeliveryEvidence` claims nested in the relevant `SourceEvidence` row. Each claim has a stable evidence ID, tenant ID, supplier ID, delivery ID, typed purpose (`CONFIRMATION`, `ETA_CHANGE`, or `QUOTE`), raw evidence reference, and observation timestamp. The containing source must be an incoming-deliveries source; the evidence ref must occur in its source row, and its observation cannot postdate the source observation.
- `IncomingDelivery.confirmation_evidence_id` is mandatory when the delivery is `CONFIRMED`; unconfirmed deliveries cannot claim it. Snapshot validation resolves the ID to a typed confirmation claim and checks tenant/supplier/delivery identity, source-row linkage, source ref, and timestamp against `confirmed_at`. A quote claim or ETA-change claim cannot satisfy the initial confirmation link.
- On the synthetic supplier ETA change, the `delivery-patty-001` record preserves its initial confirmation evidence ID and `source-deliveries-001` link. It separately links a typed ETA-change evidence ID in `source-deliveries-002`; the new notice does not replace the original confirmation. The before and after snapshots validate as `VALID` in the focused fixture test.
- The new fields and association structure are P2-local and provisional. No shared P5 contract, migration, route, or P5-owned code was modified.
- **Evidence guarantee:** the P2 model proves that a typed evidence claim is present in the snapshot, references an evidence item in a specific source row, and is bound to the matching tenant/supplier/delivery. It does not prove the external supplier's identity, document authenticity, or truth. P5 must decide and implement source-adapter verification/trust before real source data is treated as authenticated.

### Test-first validation

- **Expected red run:** `python -m pytest backend/app/feasibility/tests/test_snapshots.py::test_confirmed_delivery_without_confirmation_provenance_is_rejected backend/app/feasibility/tests/test_snapshots.py::test_generic_quote_only_evidence_cannot_prove_a_confirmed_delivery backend/app/feasibility/tests/test_snapshots.py::test_eta_update_cannot_disconnect_original_confirmation_provenance backend/app/feasibility/tests/test_snapshots.py::test_eta_update_preserves_confirmation_provenance_and_links_eta_notice -q` — **FAIL as expected, 4 failed**. The pre-correction model accepted missing/quote-only/disconnected provenance and exposed no explicit provenance association.
- **Focused provenance tests:** `python -m pytest backend/app/feasibility/tests/test_snapshots.py::test_confirmed_delivery_without_confirmation_provenance_is_rejected backend/app/feasibility/tests/test_snapshots.py::test_generic_quote_only_evidence_cannot_prove_a_confirmed_delivery backend/app/feasibility/tests/test_snapshots.py::test_eta_update_cannot_disconnect_original_confirmation_provenance backend/app/feasibility/tests/test_snapshots.py::test_eta_change_notice_cannot_substitute_for_initial_confirmation backend/app/feasibility/tests/test_snapshots.py::test_eta_update_preserves_confirmation_provenance_and_links_eta_notice -q` — **PASS, 5 passed**.
- **Snapshot regression:** `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q` — **PASS, 21 passed**, preserving the prior 16 tests.
- No unrelated repository suite was run.

### Requirement trace, safety, and blockers

- Updated `P2-BE01-03`, `P2-BE01-05`, `P2-DATA-07`, `P2-HC-06`, `SYS-BE-04`, and Phase 1 rows `PH1-02`, `PH1-03`, and `PH1-05` in `P2_REQUIREMENT_TRACE.md`; fixture provenance limits are documented in `FIXTURES.md`.
- P5's external source authenticity/identity trust remains BLOCKED for integration. P5's shared snapshot/assessment contract, persistence, authentication/routes/outbox, and Core lifecycle remain unchanged and pending. P1/P5 fixture approval and P3/P5 evaluator/ProposedChanges integration also remain pending. These dependencies do not prevent this P2-local evidence-model correction.
- **Compact review assessment:** Tests establish typed and delivery-specific provenance inside synthetic snapshots. They cannot establish supplier authenticity, real adapter correctness, durable audit storage, ATP eligibility, or feasibility. The evidence types remain provisional until P5 approves any shared handoff.

### Exact files changed

- `backend/app/feasibility/models.py`
- `backend/app/feasibility/fixtures.py`
- `backend/app/feasibility/tests/test_snapshots.py`
- `backend/app/feasibility/FIXTURES.md`
- `backend/app/feasibility/P2_REQUIREMENT_TRACE.md`
- `backend/app/feasibility/P2_PROGRESS.md`
- `backend/app/feasibility/P2_PHASE_REPORTS.md`
- `docs/TEAM_LOG.md` (P2 entries only)

**Next action:** Stop for external review. Do not begin Phase 2 without a later `APPROVED — CONTINUE P2`.
