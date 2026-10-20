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

## Phase 2 — Time-Phased ATP, Recursive BOM and Unit Conversion

- **State:** PASS for P2-local Phase 2 material calculations; shared P5/P3 integration BLOCKED. Independent external review PENDING. Overall P2 is not complete.
- **Date:** 2026-10-21 (Asia/Kuala_Lumpur).
- **Branch:** `feat/p2-feasibility-engine`.
- **Approved starting commit:** `0d990d99bfe973f7b13295d1e005639a0f61adbd`. User reported independent approval of Phase 1 and both corrections. Clean working tree, exact HEAD and remote feature ref were verified before changes. Local main remains `aedb152812640d4a825c69de05aef54637068e21`; no merge performed.
- **Master path:** earlier `D:\dunno\0.SDC\P2_CODEX_MASTER.txt` does not exist; user's corrected `D:\dunno\0.SDC\P2_CODEX_MASTER.txt.txt` exists and was read. Actual local owner requirements/canonical docs/progress/trace/reports and existing code/tests were read. No missing source content was invented.
- **Commit SHA:** see phase response (created after this report).
- **Dirty status at preparation:** listed P2 files/P2 TEAM_LOG records and generated untracked bytecode caches. Automatic approval review rejected both recursive and file-limited PowerShell cache deletion as blocked by policy. Caches are left untracked and excluded from staging; final worktree status is in phase response.
- **Push:** explicitly authorized by the user's final instruction to push only `feat/p2-feasibility-engine`; performed/verified after commit, exact result in phase response. No main push, PR or merge authorized/performed.

### Implementation and observable behavior

`bom.explode_bom(snapshot, *, tenant_id)` expands all confirmed commitment lines recursively into purchased leaf materials. It preserves commitment/version/line/SKU, base quantity/unit, need-time, warehouse, SKU paths, component paths and evidence. Shared leaves aggregate exactly. Missing BOM or cycle produces UNKNOWN with no confident requirements. Explicit BOM-kind source-backed SKU/unit conversions map directly to base units, never implicit reverse or chained conversions. BOM quantities are per one parent base unit; `waste_multiplier >= 1` represents extra consumption (1.1 = 10% extra), not division by yield. Every conversion/multiplier/default no-known-loss assumption is visible.

`inventory.calculate_atp(snapshot, *, tenant_id, as_of=None)` allocates all competing confirmed demand in a single pure batch. Priority is material-use instant, commitment ID/version, line ID, SKU. Active reservations are removed once from free lots and credited only to their owner; remaining held quantity is decremented across owner lines and surplus remains held. Released/consumed reservations do not hold stock. Lots and receipts have separate remaining balances; a supply unit cannot serve multiple orders/lines. Free lots use earliest expiry/ID, followed by receipts by ETA/ID.

Lot expiry is checked at each material-use instant, including owned reserved stock. Expiry equality excludes the lot. Only CONFIRMED receipts with validated typed confirmation/ETA links and current relevant source evidence may contribute. ETA equality is eligible at material use and logistics cutoff; one microsecond late is excluded. An outstanding receipt due at/before calculation time yields UNKNOWN pending receipt/on-hand reconciliation, preventing received-goods double counting. Quotes/unconfirmed promises (including fixture quantity 500) never supply stock.

Warehouse-scoped lines use only matching lots/receipts; unknown receipt location cannot satisfy them. Unscoped demand pools warehouses as a disclosed assumption. Missing/stale relevant source categories, incomplete BOM/competing demand, past material demand or arithmetic limits yield UNKNOWN/no confident material rows. Invalid tenant/source/unit/reservation inputs are refused by validation. Both calculation entry points revalidate copied/constructed snapshots rather than trusting Pydantic validator bypasses.

`materials.py` defines frozen P2-local `BomExpansion`, `MaterialRequirement`, `SupplyAllocation`, `MaterialAvailability`, `MaterialATP`. ATP rows expose required, allocated usable/reserved/confirmed incoming, shortage, unit, need-time, allocation IDs and source/raw evidence refs. Tenant, immutable snapshot ID/version and calculation time remain in results. Quantities serialize as decimal strings. `quantities.py` isolates exact addition/subtraction/multiplication from ambient precision/exponent/trap settings; unsupported normalization becomes UNKNOWN or a Pydantic validation error before allocation.

### Scope and contract consistency

- Material statuses are COMPLETE/UNKNOWN (BOM) and COVERED/SHORTAGE/UNKNOWN (ATP), explicitly **not** a new shared FeasibilityAssessment enum. COVERED does not establish full FEASIBLE. SHORTAGE is a material constraint under the documented priority, not universal proof against alternative allocations. Full assessment status/capacity/evaluator orchestration is Phase 3 and was not implemented.
- Thus F2-01's arithmetic/evidence gate passes (100 required, 70 allocated, 30 shortage), but its full `INFEASIBLE` shared assessment remains IN_PROGRESS until Phase 3. F2-02..04 and F2-07 material acceptance is tested. F2-05/06 impact events remain Phase 4 even though material fixture labels now reproduce. F2-09 command concurrency remains P3/P5 BLOCKED; no actual reservation operation exists here.
- Default `as_of` is snapshot capture for reproducible historical replay. Explicit aware `as_of >= captured_at` checks freshness at that instant. No wall-clock dependence, persistence, cache authority/current-version assertion, agreement/risk/fulfilment mutation, inventory write, supplier action, event publication, API or UI.
- All added model/result fields remain P2-local/provisional. External supplier identity/authenticity is P5 adapter work. Structural confirmation links are not proof of real supplier truth or actual goods received.
- Capacity/job resource conflicts are Phase 3; the Phase 2 shared-resource tests cover competing materials only. No P5-owned implementation/shared contracts/migrations or other member-owned code changed.

### Representative actual output

Executed from repository root:

```powershell
python -c "from backend.app.feasibility.fixtures import build_supplier_delay_scenario, build_two_affected_scenario; from backend.app.feasibility.inventory import calculate_atp; scenarios=(build_supplier_delay_scenario(), build_two_affected_scenario()); print([(s.scenario_id, snap.snapshot_version, [(r.commitment_id, str(r.shortage), r.unit) for r in calculate_atp(snap, tenant_id=snap.tenant_id).materials if r.sku_id == 'PATTY']) for s in scenarios for snap in (s.before, s.after)])"
```

Observed patty shortages in commitment order com-001/com-002:

| Scenario | Snapshot v1 | Snapshot v2 |
|---|---|---|
| supplier-delay-buffered-unaffected | 0 / 0 pcs | 40 / 0 pcs |
| supplier-delay-two-affected | 0 / 0 pcs | 70 / 40 pcs |

The recursive conversion test observes 100 parents * 250 g * 1.1 * 0.001 kg/g * 2 pcs/kg = 55 pcs; shared-leaf branching observes 150 pcs. These are synthetic material outputs, not operational risk-event or production-feasibility results.

### Exact validation evidence

All commands ran from `D:\dunno\0.SDC\MouManTAI`.

1. `python -m pytest backend/app/feasibility/tests/test_bom.py backend/app/feasibility/tests/test_inventory.py -q` — initial expected red: **32 failed**, principally absent modules/model extensions; one duplicate-keyword test setup was corrected. Invalid factor tests initially passed because unknown conversion fields were refused; after the model extension the same tests reject actual invalid factors.
2. `python -m pytest backend/app/feasibility/tests/test_bom.py -q` — **9 passed** after BOM implementation.
3. `python -m pytest backend/app/feasibility/tests/test_inventory.py -q` — **23 passed** after ATP implementation.
4. `python -m pytest backend/app/feasibility/tests/test_bom.py::test_bom_revalidates_copied_snapshot_before_calculation backend/app/feasibility/tests/test_inventory.py::test_receipt_overdue_at_calculation_time_requires_reconciliation -q` — **2 failed before fixes, 2 passed after**. The defects were bypassed tenant validation and counting an outstanding receipt already due at explicit calculation time.
5. Combined BOM/inventory command from (1) — **42 passed** after added boundary/warehouse/reservation/immutability cases and those fixes.
6. `python -m pytest backend/app/feasibility/tests/test_inventory.py::test_inventory_conversion_overflow_returns_unknown_instead_of_crashing -q` — **1 failed then 1 passed** after moving free-lot normalization inside the DecimalException handler. Internal read-only review found this defect; independent external Phase 2 approval is still pending.
7. `python -m pytest backend/app/feasibility/tests/test_inventory.py::test_reservation_normalization_limit_is_a_validation_error -q` — **1 failed then 1 passed** after normalizing input arithmetic errors into Pydantic ValidationError.
8. `python -m pytest backend/app/feasibility/tests/test_inventory.py::test_decimal_exponent_and_trap_settings_do_not_change_material_outcome -q` — **1 failed then 1 passed** after isolating Decimal Context settings.
9. Final focused P2 regression: `python -m pytest backend/app/feasibility/tests/test_bom.py backend/app/feasibility/tests/test_inventory.py backend/app/feasibility/tests/test_snapshots.py -q` — **66 passed, 0 failed in 0.42s** (45 Phase 2 tests plus all 21 prior snapshot tests). Test elapsed time is not a product latency metric.
10. Internal read-only reviewer rechecked five localized fixes: **5 passed**, no remaining important issue reported. Earlier reviewer run caught the overflow defect (63 passed / 1 failed at that intermediate state); it was fixed before final (9).
11. API/frontend/typecheck/build/events/E2E/full repository integration/operational metrics — **NOT RUN**: absent shared skeleton and explicitly outside this phase. No passing integration or accuracy claim.

### Exact changed files and why

- `backend/app/feasibility/models.py` — source-backed direct conversions, consumption markup, warehouse scope, normalized reservation bounds, finite/float validation and arithmetic validation errors.
- `backend/app/feasibility/quantities.py` — exact context-isolated Decimal operations.
- `backend/app/feasibility/materials.py` — immutable material-only result/evidence values.
- `backend/app/feasibility/bom.py` — recursive demand expansion and conservative issues.
- `backend/app/feasibility/inventory.py` — batch time-phased ATP with no allocation reuse or operational writes.
- `backend/app/feasibility/tests/test_bom.py` — recursive/cycle/conversion/waste/tenant/precision coverage.
- `backend/app/feasibility/tests/test_inventory.py` — ATP, competing demand, reservations, expiry/timing/warehouse/freshness and arithmetic-limit coverage.
- `backend/app/feasibility/PHASE2_PLAN.md` — scoped plan and decisions based on approved Phase 2 instructions.
- `backend/app/feasibility/FIXTURES.md` — exact material interface, semantics and limits.
- `backend/app/feasibility/P2_REQUIREMENT_TRACE.md` — individual material criteria and PH2 rows with observed evidence; later phases remain open.
- `backend/app/feasibility/P2_PROGRESS.md` — approved Phase 1 baseline and Phase 2 review checkpoint.
- `backend/app/feasibility/P2_PHASE_REPORTS.md` — this appended report; previous phase reports preserved.
- `docs/TEAM_LOG.md` — P2-only status/checkpoint/QA records.

### Blockers, assumptions and compact review assessment

P5 must ratify shared OperationalSnapshot/assessment mappings including the proposed conversion, warehouse, consumption markup, source/assumption and material-constraint fields; supply trusted complete ledgers and supplier authenticity/classification; provide authoritative snapshot versions, persistence/auth/routes/outbox and Core event handling. No shared files were changed to impose these contracts. P1/P5 fixture catalog approval remains pending. P3 must agree proposed-change serialization and reuse the future full evaluator; P3/P5 own authorized transactional reservation concurrency.

Highest-risk assumptions: each present/current source represents the complete relevant ledger, unscoped warehouses are pooled, absent known loss is explicitly multiplier 1, and every recursive material shares the root material-use time (no modeled production lead times). Allocation order is the existing provisional fixture rule, not a ratified business optimization policy. Source evidence refs include whole source observations and are not proof of row-level authenticity.

Known conservative limits: stocked manufactured/intermediate assemblies yield UNKNOWN rather than being ignored or falsely called short; netting such stock is unsupported. Direct SKU-to-base conversions only; no inferred conversion chains. Material results do not establish optimal allocation, available capacity or customer delivery feasibility. Default replay time does not establish current authoritative state. These limits are explicit; there is no confident safe/impossible result from inadequate inputs.

**Next action:** Stop for independent external Phase 2 review. Start Phase 3 only after the user returns `APPROVED — CONTINUE P2` following that review.
