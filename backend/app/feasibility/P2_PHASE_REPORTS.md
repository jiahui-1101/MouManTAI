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

## Safety checkpoint — Main synchronization before Phase 3

The user reported Phase 2 approved at `d28b63ab5fa82c66633ad18211b9c4fa83ffbbe4`
and authorized Main -> P2 integration only. Incoming Main is
`4ec2ba1ef7ede4a67352631178a73a6882bcd774`; local backup ref
`backup/p2-before-main-sync-d28b63a` preserves approved HEAD. Only package docstring
and adjacent TEAM_LOG QA rows conflicted; both owners' work was retained. P5
Core/contracts/DB/migrations/current canonical docs are identical to incoming Main.
All nine pre-existing untracked bytecode files are retained with matching hashes.

66 P2 regression tests and 7 focused shared contract/health/SQLite registry tests
PASS. P5 backend-runtime import of P2 ATP FAILS with ModuleNotFoundError for backend;
required P2-local relative-import/test-path adaptation is reported, not implemented.
Shared fixture/source-schema adapters, full evaluator and later integrations remain
pending. No Phase 3 implementation. See `MAIN_SYNC_REPORT.md` for exact commands,
results, shared schema/fixture differences and dependency notes. Merge SHA and
feature-only push/ref verification are in the task response. Stop for user review.

## P2-local runtime import compatibility correction

- **State:** PASS for the requested import correction; external correction review pending. No Phase 3 implementation.
- **Date:** 2026-10-21, Asia/Kuala_Lumpur.
- **Branch / baseline:** `feat/p2-feasibility-engine`, approved Main-sync merge `14e794308d317e744d321f2b26ba4d5af8f677dd`. Confirmed exact HEAD and clean tracked/untracked-visible status before edits. User accepted the merge; no rollback, repeated fetch/pull or additional merge performed.
- **Correction commit / feature push SHA:** see task response, after this report is committed and remote ref verified. No Main modification or push.

### Scope and changes

- Five P2 modules now use package-relative imports: `models.py`, `materials.py`, `bom.py`, `inventory.py`, `fixtures.py` under `backend/app/feasibility/`.
- All imports in existing P2 tests `test_snapshots.py`, `test_bom.py`, `test_inventory.py` now consistently use `app.feasibility.*`. Test working directory is `backend/`; P5's existing backend package/test setup suffices.
- No aliases, sys.path manipulation, shared runtime/config/dependency changes, new schemas/endpoints, modified fixture data, calculation/evidence logic or test expectation changes.
- Current progress/trace, fixture import example and P2-only TEAM_LOG records updated. Prior sync/phase failure evidence remains historical; SYNC-03 is now PASS, SYNC-04 shared fixture/data alignment remains BLOCKED.

### Reproduction and exact verification

Commands below ran from `D:\dunno\0.SDC\MouManTAI\backend`.

```powershell
python -B -c "from app.feasibility.inventory import calculate_atp; from app.feasibility.bom import explode_bom; print('P2 runtime imports OK')"
```

Before edits: exit 1, `ModuleNotFoundError: No module named 'backend'`, inventory.py importing backend.app.feasibility.bom. After the import-only change: exit 0, **`P2 runtime imports OK`**.

```powershell
python -B -m pytest -o 'addopts=' app/feasibility/tests/test_snapshots.py app/feasibility/tests/test_bom.py app/feasibility/tests/test_inventory.py tests/test_contracts.py tests/test_smoke.py tests/test_registry.py -q -p no:cacheprovider
```

**PASS: 73 passed, 1 warning in 1.58s, exit 0.** All existing 66 P2 tests and 7 shared contract/fixture/health/SQLite registry tests ran together. No tests added/deleted/weakened. The existing Starlette TestClient warning about httpx/httpx2 remains; no shared dependency change was made. Pytest elapsed time is not an operational performance metric.

Canonical identity probe (same backend working directory):

```powershell
python -B -c "import sys; from pydantic import BaseModel; from app.core import schemas; from app.feasibility import models, materials, bom, inventory, fixtures; from app.feasibility.tests import test_bom, test_inventory, test_snapshots; assert bom.OperationalSnapshot is inventory.OperationalSnapshot is fixtures.OperationalSnapshot is test_bom.OperationalSnapshot is test_inventory.OperationalSnapshot is test_snapshots.OperationalSnapshot is models.OperationalSnapshot; assert materials.FrozenModel is models.FrozenModel; assert bom.MaterialRequirement is materials.MaterialRequirement; assert inventory.MaterialATP is materials.MaterialATP; assert models.FrozenModel.__bases__[0] is schemas.ContractModel.__bases__[0] is BaseModel; assert not any(name == 'backend' or name.startswith('backend.app') for name in sys.modules); print('P2/P5 class identity OK; canonical app namespace only')"
```

**PASS:** `P2/P5 class identity OK; canonical app namespace only`, exit 0. This verifies each P2 type is the same class across importing modules/tests and both P2/P5 model bases resolve to the same Pydantic BaseModel. It does not equate P2-local operational input types with different P5 domain schemas or claim shared snapshot adapter integration.

Additional scope verification from repository root: parsed all eight changed Python files and their approved HEAD versions as ASTs. Replacing only each old import prefix in the approved source yields an identical AST to each edited file. Observed **`8 Python ASTs match approved HEAD after import-only normalization`**, exit 0. Thus calculations, fixture definitions, evidence checks and test assertions remain unchanged.

Source scan for backend.app, sys.path and sys.modules under P2 Python files returned no matches. Shared Core/DB/migrations/contracts/backend pyproject/root AGENTS/system requirements diff was empty. Final staged-diff/clean-tree/ref evidence is in the task response.

### Exact authored files

- `backend/app/feasibility/models.py`
- `backend/app/feasibility/materials.py`
- `backend/app/feasibility/bom.py`
- `backend/app/feasibility/inventory.py`
- `backend/app/feasibility/fixtures.py`
- `backend/app/feasibility/tests/test_snapshots.py`
- `backend/app/feasibility/tests/test_bom.py`
- `backend/app/feasibility/tests/test_inventory.py`
- `backend/app/feasibility/FIXTURES.md`
- `backend/app/feasibility/P2_PROGRESS.md`
- `backend/app/feasibility/P2_REQUIREMENT_TRACE.md`
- `backend/app/feasibility/P2_PHASE_REPORTS.md`
- `docs/TEAM_LOG.md` (P2 board/checkpoint records only; P5 records preserved).

### Remaining limitations and next action

Host Python 3.14 uses pytest **9.1.1**, outside P5's declared dev constraint **`pytest>=8.3,<9`**. The mismatch is documented without modifying shared dependencies, package installation or runtime configuration. Existing 7 shared tests use SQLite; no live PostgreSQL migrations/DB smoke, frontend build or full cross-feature E2E test was run for this import-only correction.

P5's shared demo snapshot remains an untyped summary and lacks required source freshness/provenance, lot/reservation ownership, full competing demand, calendars/jobs and typed supplier confirmation associations. Shared IDs and BURGER catalog (SAUCE/PACKAGING) differ from the approved P2 regression fixture (WRAP). Keep both fixtures intact; reviewed P2/P5 source/fixture/schema alignment is still required. Shared FeasibilityAssessment/ConstraintReason mapping and all full evaluator, capacity, impact/event/API/UI/P3 integration work remain later phases.

**Stop for external review of this correction. Phase 3 has not started and requires a later explicit authorization.**

## Phase 3 — Production Capacity, Deadlines and Pure Evaluator

- **State: PARTIAL.** Independent P2-local calculations pass focused tests; final shared FeasibilityAssessment output and P3/P5 data integration remain BLOCKED. External review is pending. No Phase 4 work.
- **Date:** 2026-10-21, Asia/Kuala_Lumpur.
- **Branch:** feat/p2-feasibility-engine. Verified clean exact approved baseline `5a1e827b6431d4fddbaf6bf2938865f0bfdef567` before edits; user reported external approval of that import correction.
- **Commit/push SHA and final dirty/ref state:** see phase response; report saved before commit. User explicitly authorized commit/push only this feature branch. No Main push, merge or force-push.
- **Instructions:** read actual current Master/P2 requirements, canonical system/root AGENTS, owner requirements, TEAM_LOG, P2 progress/trace/reports, implementation/tests and actual Core schemas. Old docs/AGENTS.md is absent; TEAM_LOG explicitly establishes root AGENTS.md as canonical, matching current user instruction. No missing content invented or external requirements copied/edited.

### Contract clarification received during this phase

At initial implementation, the user confirmed there was no verified P5 decision
for `affected_commitment_ids`; P2 therefore used a local result without invented
IDs. In the later external-review follow-up, P5 confirmed the field is the actual
Impact Set, not assessment scope. That semantic decision is now RESOLVED. The
current shared schema still requires at least one ID, so an empty actual Impact
Set remains blocked pending P5's schema change, merge and verification. P2 makes
no shared schema edit and still returns a local `EvaluationResult`, not a shared
`FeasibilityAssessment`.

### Changes and precise supported behavior

- `models.py`: one P2-local calendar bound correction compares exact available microseconds with elapsed microseconds instead of dividing under ambient Decimal context. A valid129-minute window at precision1 previously failed validation; new focused test failed before this correction and passes afterward. No shared schema change.
- `production.py`: frozen P2-local EvaluationSnapshot wrapping existing OperationalSnapshot, production evidence roles/freshness, exclusive resources, explicit SKU processing/setup/transit parameters, versioned fixed plans/dispatch/SOFT preference, existing jobs and complete coverage horizon; version-bound ProposedChanges. Missing job ledger differs from complete evidenced empty ledger. Tenant/duplicates/time/decimal/role validation refuses malformed inputs; unresolved evidence is UNKNOWN.
- `capacity.py`: evaluates actual supplied fixed non-preemptible intervals across all confirmed demand. Working windows must locate breaks exactly; daily totals cannot establish interval availability. Checks all simultaneous resources, job/commitment overlaps, half-open edges, window gaps/end boundaries, dispatch and customer deadline including explicit transit. Missing rate/lead/plan/ledger/horizon/source and unsupported intermediate routing/durations -> UNKNOWN. Decimal arithmetic is isolated; timeline comparisons use exact microseconds. Free-time diagnostics are bounded by work/jobs/deadline/dispatch/transit and become None when incomplete evidence prevents trustworthy availability.
- `service.py`: pure evaluate(snapshot, proposed_changes, commitment); actual Core Commitment boundary, Core FeasibilityState/SolverStatus/ConstraintReason, term/tenant/version equality, original metadata/time/evidence/assumptions retained. Reuses existing batch calculate_atp/BOM unchanged. Proposals change target quantity/deadline/start only in a validated private copy; no inventory/job/reservation/Core writes. Other demand remains present. New/increased competitor material shortage rejects a proposal via same baseline/candidate ATP; no dependency graph, event or risk propagation.
- `production_fixtures.py`: explicit synthetic rate/setup/transit/calendar/empty-job-ledger/fixed-booking evidence, separate from existing regression/shared fixtures. No operational rate inferred. This is not the P5-approved shared demo dataset.
- `tests/test_capacity.py`, `tests/test_service.py`: positive/negative production, calendar/job/resource, deadline/transport, source freshness/missingness, precision/unsupported duration, actual Core mapping, all four statuses, proposal purity, tenant/version and competitor safety cases.
- `PHASE3_PLAN.md`, `PHASE3_HANDOFF.md`: approved scope, exact imports/proposals, evidence model, status/mapping table, supported scheduling limits, P3/P5 requests.
- Updated P2_PROGRESS.md, P2_REQUIREMENT_TRACE.md, this report and P2-only TEAM_LOG entries. Existing P2 algorithms/fixtures/tests and P5 Core/schemas/contracts/migrations/dependencies/app shell remain unchanged.

### Actual representative outputs

The executed Python probe called build_production_example and evaluate on its
baseline, a copied 70-patty lot, a quantity60 proposal and a missing-job ledger:

| Input | Local status / solver | Observed constraints |
|---|---|---|
| Required100, stock100, explicit one minute/unit, exact 09:00 booking and trusted complete fixture ledger | FEASIBLE / COMPLETED | none; required100 minutes, finish10:40, available480 minutes |
| Same snapshot with stock70 | INFEASIBLE / COMPLETED | MATERIAL_SHORTAGE, PATTY, shortage30 pcs, HARD, material-use deadline/evidence |
| Stock70, version-bound quantity60 hypothesis | CONDITIONAL / COMPLETED | HYPOTHETICAL_CHANGE_PENDING_APPROVAL, INFORMATIONAL, proposal evidence |
| Complete materials, jobs=None | UNKNOWN / UNKNOWN | MISSING_JOB_LEDGER, INFORMATIONAL; no implied zero jobs |

These are local fixed-booking query results, not affected-ID findings, Core
state transitions, order acceptance, promised future delivery or live integration.
Stale source/current-version examples return UNKNOWN/STALE. Unsupported durations
and routing remain UNKNOWN. A 10:45 dispatch cap reports105 available minutes;
a subsequent 10:40 job reduces that to100; missing competing plan reports None.

### Exact validation evidence

All pytest commands below ran from `D:\dunno\0.SDC\MouManTAI\backend` with
canonical app imports, `python -B`, no path aliases and no shared config changes.

1. Initial test-first command:
   `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_capacity.py app/feasibility/tests/test_service.py -q -p no:cacheprovider`
   — **42 failed as expected**, absent production/evaluator modules (test collection succeeded).
2. First implementation run of the same command — **41 passed, 1 failed**: available-time diagnostic depended on ambient Decimal precision. Fixed isolated diagnostic division; `... test_capacity.py::test_decimal_context_and_input_order_do_not_change_result ...` — **1 passed**.
3. Target-local capacity regression `test_service.py::test_unrelated_commitment_deadline_failure_does_not_make_target_infeasible` — **1 failed before fix, 1 passed after**. Known unrelated hard/soft violations no longer contaminate target status; missing competing inputs remain conservative UNKNOWN.
4. Internal read-only review found candidate displacement and available-time overstatement. Added `test_service.py::test_hypothetical_quantity_cannot_hide_new_shortage_for_competing_commitment` — **1 failed then 1 passed** after same-ATP baseline comparison. Added `test_capacity.py::test_available_minutes_stop_at_dispatch_cutoff_and_existing_job` — **1 failed then 1 passed** after free-interval diagnostic correction.
5. `test_service.py::test_stale_production_and_inventory_sources_preserve_stale_solver_status` — **1 failed then passed** with STALE preserved. Focused command with that node, real existing-unrelated-shortage fixture node and parametrized duration limits — **4 passed**. Corrected the unrelated-shortage test setup to include a real competitor (baseline shortage20, reduced candidate shortage10); this tests unchanged pre-existing harm separately from new displacement.
6. Final localized review found unknown competing plan still left a numeric diagnostic. Added `test_capacity.py::test_missing_competitor_plan_cannot_claim_known_free_minutes` — **1 failed then 1 passed**; free-time is None under insufficient booking evidence.
7. Added `test_capacity.py::test_exact_calendar_validation_ignores_ambient_decimal_precision` — **1 failed then 1 passed** after the existing P2 CapacityWindow validation correction; fresh full regressions required because an existing model changed. Final Phase 3 command from (1) — **54 passed, 0 failed in 0.63s**. Earlier 45/47/52/53 counts are intermediate development/reviewer runs, not final coverage.
8. Existing regression:
   `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_snapshots.py app/feasibility/tests/test_bom.py app/feasibility/tests/test_inventory.py tests/test_contracts.py tests/test_smoke.py tests/test_registry.py -q -p no:cacheprovider`
   — **73 passed, 1 existing Starlette/httpx deprecation warning in 1.64s** (all66 existing P2 plus7 shared tests). Original tests unchanged. Repeated only after the final P2 calendar validation correction; all73 preserved.
9. Executed four-status probe from backend using app.feasibility imports — **exit0**, exact output table above. `git diff --check` — exit0; final staged scope checks recorded in phase response.
10. Frontend typecheck/Vitest/build, HTTP/API/UI, events, metrics, live PostgreSQL, cross-feature E2E and P3 execution/concurrent command reservation — **NOT RUN**, outside Phase 3 scope or pending owner integration. No latency/accuracy claim from pytest timing.

### Safety, assumptions, blockers and handoff

- **BLOCK-P2-P3-001 / P5:** actual-Impact-Set semantics are RESOLVED. The current P5 schema still requires a nonempty list; merged and verified support for an empty set is pending. Final shared serializer remains BLOCKED.
- **BLOCK-P2-P3-002 / P3:** review exact ProposedChanges shape and fixed-booking evaluator import/usage. Current P3 package is a placeholder; no agreement or live P3 parity claim. Arbitrary supply insertion/job deletion is refused; supply substitution needs reviewed typed provenance/conditional semantics.
- **BLOCK-P2-P3-003 / P2+P5:** shared demo summary is not a complete operational snapshot. Shared tenant_demo_01/com_001 and SAUCE/PACKAGING differ from existing P2 IDs/WRAP catalog. Need reviewed operational-data/catalog adapter with trusted full ledgers, freshness, lots/reservation ownership, typed receipts, exact calendars/jobs/processes/transport. No invented stock/rates/evidence to make shared demo FEASIBLE.
- P5 source authenticity/completeness/current-version/persistence/auth/Core audit/outbox and P3/P5 transactional command reservations remain pending integration. Pure proposals cannot allocate stock across concurrent plans.
- Host Python3.14.3/Pydantic2.13.4/pytest9.1.1; pytest exceeds P5 declared >=8.3,<9. Dependencies untouched. Shared regression uses SQLite, not a live PostgreSQL migration.
- Compact review limits: fixed-booking feasibility is not global scheduling optimization; complete existing-job ledger excludes already represented plans; adapters must reconcile identities. Multi-stage production and purchased-finished-goods logistics remain UNKNOWN. Diagnostic minutes may use explicitly documented fixed-precision decimal representation, while proofs use exact microseconds. Core constraint outputs are mutable but freshly allocated per query. Historical replay does not prove current authoritative version.
- Trace: PH3-01..05/08 local evidence PASS; PH3-06/07 shared integration BLOCKED; applicable owner/F2/system rows updated truthfully. Phase3 overall PARTIAL, P2-FE NOT_STARTED, Phases4–7 NOT_STARTED.

**STOP for external Phase 3 review. Do not claim full Phase 3 PASS or start Phase 4.**

## External review #2 correction — evidence-aware status precedence

- **Reviewed baseline:** `40c526a0bf05b215333a0832e13a88c275d61cad`. Before editing, `HEAD`, `origin/feat/p2-feasibility-engine`, and the expected branch were verified to match; the worktree was clean.
- **Finding:** allocation-policy uncertainty was included in the same UNKNOWN gate as data uncertainty, which allowed a provisional ATP allocation shortage to mask a separately evidenced HARD failure.
- **P2-local correction:** `service.py` now classifies evidence uncertainty (stale snapshot/source, UNKNOWN ATP/capacity, or unknown proposal baseline) separately from allocation-dependent shortage. Missing, stale or incomplete evidence still yields UNKNOWN even when a HARD constraint is retained. With complete trusted evidence, an independent HARD failure yields INFEASIBLE; allocation-dependent shortage alone remains UNKNOWN. Existing ATP, BOM, capacity scheduling and P5 contracts are unchanged.
- **Solver metadata:** in mixed trusted-evidence results, `FeasibilityState.INFEASIBLE` records the independent fixed-target/fixed-booking proof while `SolverStatus.UNKNOWN` retains the unresolved ATP allocation-policy detail.
- **Fixed-schedule meaning:** a HARD capacity/deadline/job constraint proves that the supplied fixed booking fails the known schedule constraints. It does not prove that every alternative rescheduling plan is impossible. The capacity result assumption is preserved in the evaluator output and the distinction is covered by regression assertions and PHASE3_HANDOFF.md.
- **Focused regressions:** added target B allocation uncertainty plus overlapping evidenced job; allocation-dependent PATTY plus unavoidable BUN shortage30; and parameterized stale inventory/production evidence with an independent HARD job constraint. Existing tests continue to cover allocation-only UNKNOWN, F2-01 shortage30, protected/ineligible allocations, missing/stale evidence and proposal displacement HARD safeguards. The two mixed trusted-evidence tests failed before the fix (UNKNOWN masked the HARD proof); all four new test cases passed after it.
- **Validation from `backend/`:** `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_capacity.py app/feasibility/tests/test_service.py -q -p no:cacheprovider` — **67 passed in 0.82s**. `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_snapshots.py app/feasibility/tests/test_bom.py app/feasibility/tests/test_inventory.py tests/test_contracts.py tests/test_smoke.py tests/test_registry.py -q -p no:cacheprovider` — **73 passed, 1 existing Starlette/httpx deprecation warning in 1.71s**. Targeted new precedence nodes — **4 passed, 28 deselected**. Initial red run: 2 expected failures and 2 stale-evidence passes.
- **P5 contract:** P5's actual Impact Set semantics remain RESOLVED. Empty-list schema support remains PENDING merge and verification (`min_length=1` observed); final shared FeasibilityAssessment adapter remains BLOCKED. No P5 schema or other-owner code changed.
- **Current P2 board:** the prior reviewed checkpoint had 63 Phase 3 tests; this follow-up adds four parametrized test cases, bringing the current Phase 3 count to **67**. The preserved P2/shared regression remains **73**.
- **Scope and gate:** P2 `service.py`, P2 tests, P2 progress/trace/report/handoff and P2-only TEAM_LOG board/log entry. No Phase 2 calculator/scheduler, P3, P5, Phase 4 or shared contract changed. Phase 3 remains PARTIAL and stops for independent external review.

## External review correction — allocation-dependent material status

- **Reviewed input:** external review of `9ff7535417cf0508d1940775a2530d9353551269` accepted the local capacity/deadline/evaluator work in principle and required correction where provisional ATP priority made a target shortage HARD.
- **P2-local correction:** `service.py` now reads existing ATP allocations to determine whether other confirmed demand currently holds same-SKU supply that is still eligible by lot expiry/receipt ETA and target warehouse. Protected reservation quantities, expired lots, late receipts and location-ineligible supply are excluded. ATP ordering/allocation code is unchanged and no demand is displaced.
- **Status behavior:** if eligible competing allocations could fully cover a target's provisional shortage, output `ALLOCATION_DEPENDENT_MATERIAL_SHORTAGE` with INFORMATIONAL severity, current ATP batch aggregate shortage, and evidence; overall status is UNKNOWN. If compatible reallocation still leaves a positive minimum shortfall, `MATERIAL_SHORTAGE` remains HARD at that proven amount and the result is INFEASIBLE. A proposal that newly shortens another confirmed commitment remains HARD through the existing baseline/candidate ATP comparison. Independent capacity HARD constraints remain unchanged.
- **Focused regressions:** added the 100-stock / 80-plus-100 demand case; F2-01 target100/eligible70; protected reservation and time/location-ineligible supply; proposal displacement; and deadline, job-conflict and working-window capacity failures. The pre-fix test `test_provisional_allocation_shortage_is_unknown_with_aggregate_shortage_evidence` failed because the result was INFEASIBLE; after the correction it passes.
- **Current validation from `backend/`:** `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_capacity.py app/feasibility/tests/test_service.py -q -p no:cacheprovider` — **63 passed in 0.78s**. Existing suite `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_snapshots.py app/feasibility/tests/test_bom.py app/feasibility/tests/test_inventory.py tests/test_contracts.py tests/test_smoke.py tests/test_registry.py -q -p no:cacheprovider` — **73 passed, 1 existing Starlette/httpx deprecation warning in 2.74s**.
- **P5 contract:** actual Impact Set semantics are RESOLVED by P5. Current `FeasibilityAssessment.affected_commitment_ids` still has `min_length=1`; empty-set schema support is PENDING merge/verification. Final shared adapter remains BLOCKED. No P5-owned code changed.
- **Files changed in this review follow-up:** `backend/app/feasibility/service.py`, `backend/app/feasibility/tests/test_service.py`, `backend/app/feasibility/P2_PROGRESS.md`, `backend/app/feasibility/P2_REQUIREMENT_TRACE.md`, `backend/app/feasibility/PHASE3_HANDOFF.md`, `backend/app/feasibility/PHASE3_PLAN.md`, `backend/app/feasibility/P2_PHASE_REPORTS.md`, and the P2-only entry in `docs/TEAM_LOG.md`.
- **Remaining blockers:** P3 ProposedChanges integration/serialization and P2/P5 operational snapshot/catalog adapter remain provisional; the shared demo is not complete operational evidence. Phase 3 remains PARTIAL and STOPPED for independent review. Phase 4 has not started.

## Phase 4 — Dependency graph and incremental impact recalculation

- **State:** PARTIAL. P2-local implementation and required tests pass; stop for independent external Phase 4 review. Shared P5 assessment adapter and event publication remain blocked. Phase 5 is not started.
- **Date / branch:** 2026-10-21 / `feat/p2-feasibility-engine`.
- **Approved starting point:** `650b702fbbdef3f2f0160db0bf3dc12cad3d2b2c`, the user-approved P2-local Phase 3 correction. Before edits, branch and `origin/feat/p2-feasibility-engine` matched that exact SHA and worktree was clean.
- **Scope:** deterministic P2-local dependency graph and resource-keyed invalidation; actual before/after recomputation using the existing pure `evaluate()`; conservative classifications/deltas/buffers; local canonical DomainEvent intents only. No P5 schema, migration, route, UI, DB/outbox/Core state, P3 module, external event or reservation was changed.

### Implementation

- Added `backend/app/feasibility/impact.py` with typed tenant-bound change/resource keys, evidence-bearing dependency graph/path models, material/HARD-constraint deltas, explicit classifications, output metadata and in-memory future event intents. Paths index supplier delivery and lot → SKU → BOM parent → production resource/plan → order/commitment, plus production resource → job → plan.
- Resource keys for supplier ETA, SKU, inventory lot, production job, production resource/capacity calendar, order and commitment changes validate against actual before/after rows and linked source evidence. Traversal and output order are deterministic. Incomplete graph evidence expands only within the tenant and causes UNKNOWN results; candidate discovery alone never confirms an impact.
- Every candidate is passed through the existing `service.evaluate()` against both snapshots. P2 now exposes `EvaluationResult.evidence_complete` and `allocation_dependent` so independent hard proof remains distinguishable from stale/missing data and allocation-policy uncertainty. `CommitmentImpact.verified_material_deterioration` reports material-level evidence separately from full feasibility impact.
- P2 creates canonical-envelope `commitment.feasibility_assessed`, `operational.impact_updated`, `commitment.at_risk`, and `operational.insufficient_data` intents. Event IDs bind the triggering cause; deduplication keys remain stable for identical detection state. No publish, DB write, outbox, or Core transition occurs.

### Observed outcomes

| Case | Before/after evidence | Observed P2-local result |
|---|---|---|
| Buffered supplier material-only fixture | PATTY shortages `com-001: 0→40 pcs`, `com-002: 0→0 pcs`; no production evidence | Both candidates UNKNOWN; empty confirmed Impact Set; measured deterioration is separately exposed for `com-001` |
| Two-affected material-only fixture | PATTY shortages `com-001: 0→70 pcs`, `com-002: 0→40 pcs` | Both candidates UNKNOWN; material deltas are not promoted to full feasibility impact |
| Buffered supplier with complete synthetic production evidence | `com-001`: FEASIBLE→INFEASIBLE; `com-002`: remains FEASIBLE with positive buffer | Only `com-001` CONFIRMED_IMPACT and receives an at-risk intent; `com-002` VERIFIED_UNAFFECTED and receives no risk intent |
| Resource-keyed production job conflict | New overlapping external job on `com-001`'s fixed booking; later `com-002` booking has buffer | `com-001` confirmed; `com-002` verified unaffected |
| Capacity calendar reduction | New `CAPACITY_WINDOW_VIOLATION` on `com-001` booking; later `com-002` booking remains feasible | `com-001` confirmed; `com-002` verified unaffected |
| Inventory lot change | PATTY shortage `0→10 pcs` | Lot key discovers both BOM dependents; no production evidence means UNKNOWN, not a confirmed full-feasibility impact |
| SKU catalog change | PATTY changes to a synthetic manufactured SKU source revision | Both dependent commitments are candidates; unsupported intermediate production evidence keeps both UNKNOWN |
| Order request change | Only `com-001` order version changes; PATTY shortage `0→20 pcs` | Only that order is a candidate; UNKNOWN because production evidence is absent |
| Stale production source after supplier delay | Material delta is present; production process source is stale | UNKNOWN and `operational.insufficient_data`; hard/material evidence cannot override stale evidence |
| Stale inventory source after supplier delay | Inventory source validity ends before the after-snapshot capture | Material determination remains UNKNOWN; no verified material deterioration is claimed |
| Allocation uncertainty / independent hard failure | Allocation-only case remains uncertain; a separate overlapping evidenced job adds a new HARD `JOB_CONFLICT` | Allocation-only case remains UNKNOWN/no risk; complete-evidence hard conflict is confirmed. The evaluator retains the fixed-booking scope limitation. |
| Existing shortage unchanged | Before/after statuses INFEASIBLE with unchanged material shortage | PRE_EXISTING_UNCHANGED; no at-risk intent |

### Tests and validation

Test-first development observed the expected initial red (`app.feasibility.impact` did not exist). New regressions also exposed Decimal subtraction rounded by ambient precision, calendar changes not recognized as actual resource changes, and same-state event IDs ignoring causal event identity. These defects were corrected; fixture setup errors were corrected without changing acceptance criteria.

From `backend/`:

1. `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_impact.py -q -p no:cacheprovider` — **14 passed in 1.55s**.
2. `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — **154 passed, 1 existing Starlette/httpx deprecation warning in 3.89s**. This includes P2 Phase 1–3 feasibility tests and shared backend contract/health/SQLite registry tests.
3. `python -m ruff check app/feasibility/impact.py app/feasibility/service.py app/feasibility/tests/test_impact.py` — **NOT RUN**; Ruff is not installed. No dependency was added.
4. Frontend typecheck/Vitest/build, live API, PostgreSQL migration, event publication, P3/P5 integration, E2E and production latency/accuracy metrics — **NOT RUN**; outside Phase 4 P2-local scope and still owner-blocked.

### Files and handoff

- New: `backend/app/feasibility/impact.py`, `backend/app/feasibility/tests/test_impact.py`, `backend/app/feasibility/PHASE4_PLAN.md`, `backend/app/feasibility/PHASE4_HANDOFF.md`.
- Updated P2 code/docs: `backend/app/feasibility/service.py`, `P2_PROGRESS.md`, `P2_REQUIREMENT_TRACE.md`, `P2_PHASE_REPORTS.md`, `PHASE3_HANDOFF.md`; only P2 status/history rows in `docs/TEAM_LOG.md`.
- P5 contract inspection: `backend/app/core/schemas.py` still rejects empty `affected_commitment_ids` (`min_length=1`). P5 has resolved the meaning as actual Impact Set, but schema support for `[]` and final shared FeasibilityAssessment adapter remain pending. No IDs were fabricated.
- P3 `ProposedChanges` serialization and P2/P5 operational snapshot/catalog/source alignment remain provisional. P5 owns durable event deduplication/outbox/persistence and authoritative risk transitions. External source authenticity and current DB version races are not established by synthetic local snapshots.
- **Commit SHA:** see phase response. **Gate:** stop here for independent external Phase 4 review; do not begin Phase 5.

## Phase 4 targeted external-review corrections — 2026-10-21

- **Reviewed starting commit:** `108565f46bf96b71bda34d47205f9d7301837c39`. External review accepted the graph/evaluator boundary in principle and requested causal attribution, collective multi-resource evidence validation, and deadline-severity corrections. Scope remained P2-owned `impact.py`, impact tests, P2 progress/trace/report/handoff and P2 TEAM_LOG entries. No P3/P5/shared schema, Core, persistence, API, UI, or route code changed.
- **Causal attribution:** dependency candidates and measured material deterioration remain separate from confirmed impact. The recalculation identifies other changed atomic resources and follows their tenant-local dependency paths. If an adverse delta has a relevant changed dependency omitted from the event's accepted resource set, classification is UNKNOWN with `UNATTRIBUTED_CONCURRENT_DEPENDENCY_CHANGE`; no at-risk intent is generated. Declared related job changes with their evidence remain attributable. The complete production fixture with a non-overlapping declared capacity job plus an undeclared supplier delay measures PATTY `0→40`, classifies `com-001` UNKNOWN, produces no at-risk intent, and verifies `com-002` unaffected. An isolated overlapping job remains confirmed.
- **Multi-resource evidence:** each declared resource must have a real before/after change and at least one event evidence ref linked to it. Every supplied event ref must be linked to at least one declared changed resource collectively. Two inventory lot changes with distinct evidence refs are accepted; unaccounted refs and a declared unchanged lot reject. Single-resource supplier ETA still requires the typed, delivery-linked `ETA_CHANGE` claim.
- **Deadline severity:** HARD deadline comparison now measures lateness from each existing evaluator `OperationResult.finish_at`, the explicit process delivery lead, and the snapshot's customer deadline. It matches by constraint/resource rather than changing deadline identity, and records NEW, WORSENED, IMPROVED or UNCHANGED severity. Expected delivery `11:10` with deadline `11:00→11:05` is 10→5 minutes late and IMPROVED, not newly adverse. With deadline `12:30`, expected delivery `12:50→13:00` is 20→30 minutes late and worsened; a declared process-resource change confirms impact. Incomplete deadline evidence remains UNKNOWN.
- **Test-first evidence:** new regressions were run against the reviewed baseline before implementation. They exposed the false confirmation for the confounded supplier/capacity snapshots, rejection of distinct legitimate multi-lot evidence, deadline extension represented as a new constraint, and missing numeric worsening delta. Existing expected rejection of an unchanged resource and typed supplier provenance were retained as guard tests.
- **Focused validation from `backend/`:** `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_impact.py -q -p no:cacheprovider` — **22 passed in 0.75s**.
- **Complete applicable backend validation from `backend/`:** `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — **162 passed, 1 existing Starlette/httpx deprecation warning in 2.46s**. This includes P2 Phase 1–3 and shared backend regressions. Ruff remains unavailable and was not installed.
- **Remaining gate/blockers:** Phase 4 remains PARTIAL pending independent external review. P5 still must merge/verify empty `affected_commitment_ids` support and review the final adapter, event payload, persistence/outbox and Core transitions. P3 proposal serialization and P2/P5 operational snapshot/catalog alignment remain provisional. Do not begin Phase 5.
- **Correction checkpoint SHA:** see current phase response after commit/push verification.

## Phase 4 final causal-provenance correction — 2026-10-21

- **Reviewed starting commit:** `f5d069e9dad2cd7eb33ce3f3e9c094db0c1706af`. External review accepted the earlier concurrent-change, collective evidence and deadline-severity corrections, and found that parent-resource relationships could still attribute changed child resources to an event. This correction is limited to P2-owned impact logic/tests and P2 reports/log. No P3/P5, shared schemas, Core, runtime, routes, database, persistence or UI code changed.
- **Implementation:** `_change_covers_resource()` now requires exact atomic `ResourceKey` membership. Graph edges still discover candidate commitments, but a production resource does not automatically cover a job or plan; a SKU does not cover a lot or delivery; and an order does not cover a commitment. A multi-resource batch remains valid by declaring every changed key with linked evidence. A child's evidence ref included in a parent-only event does not expand its scope. Relevant undeclared child changes preserve measured deltas but force UNKNOWN causal attribution and suppress `commitment.at_risk`.
- **Test-first evidence:** both new regressions failed against the reviewed baseline by incorrectly returning CONFIRMED_IMPACT. After the exact-key change, the resource/job and SKU/lot provenance tests pass. The resource-only capacity case remains UNKNOWN with the `JOB_CONFLICT` visible, including when the job evidence ref is also present but the job key is omitted. Explicitly declaring the resource and overlapping job with their refs confirms `com-001`; buffered `com-002` remains VERIFIED_UNAFFECTED. For the SKU case, PATTY lot stock changes from 80 to 20 while a separate catalog-source change is declared: the measured shortage is `0→60` pcs, but the SKU-only event remains UNKNOWN with no at-risk intent. Declaring both SKU and lot with their linked evidence confirms `com-001`.
- **Compatibility:** isolated capacity/calendar changes, explicitly declared job events, buffered supplier cases, multi-resource/multi-lot evidence, typed supplier ETA provenance, deadline improvement/worsening, pre-existing shortages, allocation-policy ambiguity, idempotency, tenant/version checks and non-mutation remain covered. Two existing job-change fixtures now declare their changed `PRODUCTION_JOB` atomically rather than relying on the resource relationship.
- **Focused validation from `backend/`:** `python -m pytest app/feasibility/tests/test_impact.py -q` — **24 passed**. The initial targeted test-first run against the reviewed baseline failed as expected for both new regressions; the same targeted cases passed after the fix.
- **Complete applicable backend validation from `backend/`:** `python -m pytest tests app/feasibility/tests -q` — **164 passed**, with one existing Starlette/httpx deprecation warning. This explicitly includes all P2 Phase 1–3/Phase 4 tests and shared backend tests. The configured default `testpaths = ["tests"]` means bare `python -m pytest -q` discovers only the 7 shared tests; the explicit two-root command is the full applicable regression. No dependency changes.
- **Scope and gate:** Phase 4 remains PARTIAL pending independent external review. P5 still must merge/verify empty `affected_commitment_ids` support and complete/review the shared adapter, event payload, persistence/outbox and Core transitions. P3 proposal serialization and P2/P5 operational snapshot/catalog alignment remain provisional. No Phase 5 work started. Stop for external review.
- **Correction commit SHA:** see phase response after feature-branch push verification.

## Phase 5 — P2 API and controlled integration checkpoint (PARTIAL) — 2026-10-21

- **Approved starting point and scope:** Phase 4 correction commit `f6ac87233534f0dc6deef3b5e464e0bd7fd1fd0e` was explicitly approved by the user for P2-local Phase 4. Before Phase 5 edits, the local branch and feature remote matched that exact SHA and the worktree was clean. Phase 5 changes are P2-owned schemas, dependency ports, an unmounted P2 `APIRouter`, focused API tests, and P2 tracking/handoff docs. No P5 app/Core/DB/shared-schema/auth/migration or P3 code was edited.
- **Implementation:** added typed definitions for the five required paths: `POST /internal/feasibility/evaluate`, `POST /v1/commitments/{id}/assess`, `GET /v1/commitments/{id}/assessments`, `POST /v1/operations/events/supplier-delay`, and `GET /v1/impacts/{impact_id}`. The internal route calls the existing pure `evaluate()` only after an injectable P5 authority resolves and validates scoped input. The assessment route requires P5 current-input authority, evaluates the trusted current snapshot with existing `evaluate()`, and passes that exact result and snapshot to the P5 writer; the writer contract requires transactional version rechecks. The public routes use Core tenant-scoped commitment lookup and version/agreement checks where applicable. Assessment/history/impact persistence and event processing delegate through explicit P5 ports; absent adapters return 503. Supplier input validation requires typed delivery-linked ETA evidence, tenant match, one delivery resource, and increasing versions. No success is returned for missing persistence or outbox behavior.
- **Local behavior and test-first evidence:** the initial focused test run failed at collection because the new API dependency module did not exist yet. An internal code review then found the assessment writer contract did not require the P2 evaluator; a new test failed because the route passed neither trusted snapshot nor result. After correction, 16 router tests pass. Coverage includes request/schema errors, tenant mismatch, missing/stale versions, confirmed-agreement gating, exact P2 result handoff to the writer, missing/stale current snapshot rejection, unavailable adapter failures, stale evaluation evidence, pure evaluator reuse for hypothetical quantity changes, no input mutation, duplicate retry not falsely acknowledged as processed, and the shared schema accepting a nonempty actual Impact Set while rejecting `[]`.
- **Focused validation from `backend/`:** `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_router.py -q -p no:cacheprovider` — **16 passed**, one existing Starlette/httpx deprecation warning.
- **Complete applicable backend validation from `backend/`:** `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — **180 passed**, one existing Starlette/httpx deprecation warning. This explicitly includes all P2 Phase 1–4 tests and shared backend tests.
- **P5 contract recheck:** fetched `origin/main` at `4ec2ba1ef7ede4a67352631178a73a6882bcd774`; `FeasibilityAssessment.affected_commitment_ids` still specifies `min_length=1`. The actual Impact Set may be empty, so final shared response serialization remains blocked. No IDs/schema changes were used to hide this issue.
- **Security and integration limitations:** existing `RequestContext` still reads caller-supplied headers and is demo plumbing, not authenticated identity or production tenant/RBAC proof. P2's router is not mounted in P5 `backend/app/main.py`. Local tests mount it only in an isolated test app and do not establish production routing/security. No authoritative current snapshot provider, transactionally race-safe version check, assessment/history store, impact reader, source-row verifier, idempotent supplier-event/outbox processor, or Core risk command was available; their routes fail closed with 503 rather than simulate success.
- **P5/P3 handoff:** exact P5 decisions requested for router mounting, authenticated RequestContext/internal authorization, authoritative snapshot/version authority, empty Impact Set schema, durable assessment history, impact persistence/Core state boundary, and transactional supplier event/outbox are recorded in `PHASE5_HANDOFF.md`. The accessible recent and archived Codex thread list had no identifiable P5 owner task; no direct message or reply is claimed. The documented P3 Python contract is the existing pure `evaluate(snapshot, proposed_changes, commitment)` path. ProposedChanges semantics align with P3's written requirements, but HTTP JSON serialization remains provisional and P3 owner confirmation is pending. No P3 code changed.
- **Instruction-file gap:** requested `docs/AGENTS.md` does not exist. Root `AGENTS.md` was read but retains the old PromiseFlow product name; the user's supplied MouManTAI rules, canonical system requirements, and TEAM_LOG ADR-010 were followed. No instruction file was guessed or edited.
- **Not run / blocked:** actual main-app route integration, authenticated production RBAC, live PostgreSQL, persistence/history, real event/outbox transactions, P3 call, frontend, E2E, and production metrics. Host pytest 9.1.1 is outside the declared backend `<9` constraint; no dependency was changed.
- **State and gate:** **PARTIAL** — local P2 API boundary tested, shared P5 integration blocked. Commit and feature-only push evidence will be reported after final review. Stop for independent external Phase 5 review. Do not begin Phase 6.

## Phase 5 external review #1 correction — PH5-R1-01 — 2026-10-21

- **Reviewed commit:** `38f69d8f8fb1cdac132e29a7d072513191654a8c`. External review accepted the P2-local router, typed request models, evaluator reuse, fail-closed ports, and ownership boundaries in principle. It identified that the Core Commitment and independently resolved Commitment were checked for tenant/id/version/agreement but not for order, customer, or complete confirmed terms.
- **Correction:** `router.py` now compares typed Pydantic values for tenant ID, commitment ID/version, order ID, customer ID, agreement state, and every `CommitmentTerms` field (SKU, quantity, unit, deadline, special instructions). `/v1/commitments/{id}/assess` returns `COMMITMENT_BINDING_MISMATCH` (409) before `evaluate()` or the assessment writer when Core and resolver values differ. The internal route performs the same binding check between the requested and trusted resolved baseline Commitment. Proposed quantity/deadline/start changes remain hypothetical and are handled by the existing Phase 3 evaluator; they are not compared as confirmed baseline terms. The evaluator's separate OperationalSnapshot-versus-Core-terms validation remains unchanged. P5 retains authoritative snapshot resolution, transaction-level version checks, authentication, and persistence ownership.
- **Regression coverage:** updated `_assessment_inputs()` to use the actual Core order/customer identity and confirmed terms. Added seven Core/resolver mismatch cases (tenant, order, customer, quantity, deadline, special instructions, agreement state), each asserting 409 and zero evaluator/writer calls; quantity and deadline cases keep resolver Commitment and OperationalSnapshot internally consistent while both differ from Core. Added an internal requested/resolved baseline contradiction test proving no evaluator call. The existing exact P2-result writer handoff and hypothetical proposal tests remain.
- **Test-first evidence:** the initial seven new cases failed before the router correction: internal baseline contradiction reached evaluation, and six assessment mismatches proceeded to a later result/writer path. The resolver-tenant mismatch case was added as a follow-up assertion for the required tenant binding and passes with the correction. After correction, the focused router suite passes.
- **Focused validation from `backend/`:** `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_router.py -q -p no:cacheprovider` — **24 passed**, one existing Starlette/httpx deprecation warning.
- **Complete applicable backend validation from `backend/`:** `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — **188 passed**, one existing Starlette/httpx deprecation warning. This includes all P2 Phase 1–4 and shared backend regressions.
- **Files changed for this correction:** P2-owned `router.py`, `tests/test_router.py`, P2 progress/requirement/report/handoff docs, and P2-only `docs/TEAM_LOG.md` entries. No P5 Core/app/schema/auth/DB/migration, persistence, or P3 files changed.
- **Remaining blockers and gate:** production router mounting/authenticated RequestContext/internal authorization, authoritative snapshot/current-version provider and transaction recheck, empty actual Impact Set schema support, durable assessment/history and impact persistence, transactional supplier event/outbox, and P3 HTTP-shape confirmation remain unimplemented/unverified. No main-app integration, frontend, live PostgreSQL, or E2E was run. Phase 5 remains PARTIAL pending independent external review; stop here and do not begin Phase 6.
- **Correction commit/push:** recorded in the final task response after feature-branch verification.

## Phase 6 — P2-owned frontend checkpoint — 2026-10-21

**PARTIAL.** P2-local views and focused injected-adapter tests pass. Shared production
integration remains blocked. Independent external Phase 6 review is required;
Phase 7 has not started. Commit SHA and final local/remote ref state: see phase response.

### Approved baseline and inspection

- User explicitly approved Phase 5 P2-local correction `85d46b2f48bea9a2e149f6dd70badc7311334061`.
  Initial P2 branch/HEAD and remote feature ref matched; worktree was clean.
- Read actual `D:/dunno/0.SDC/P2_CODEX_MASTER.txt`, actual external P2 requirements,
  canonical system/root AGENTS/TEAM_LOG, progress/trace/reports/Phase 5 handoff,
  shared/frontend/backend contracts, relevant implementation/tests and actual dependency setup.
  `docs/AGENTS.md` is absent; root AGENTS is canonical per TEAM_LOG and current user
  preparation instructions. No missing content guessed; root now names MouManTAI.
- Read-only fetch verified Main `4ec2ba1ef7ede4a67352631178a73a6882bcd774` and P5
  `origin/feat/p5-core-integration` at `a5f99151f2bc88f1c4d2cd530b0243a869a45d9c`.
  Empty Impact Set fix is IMPLEMENTED ON P5 BRANCH, PENDING INTEGRATION. P2's old
  frontend helper, no shared/auth.tsx and no TanStack Query remain factual local
  constraints. No branch synchronization, P5 code copying or shared edits performed.

### Scope, changes and actual observable behavior

- `CommitmentFeasibilityPage` reads existing Router `:id`, accepts a P2 feature source,
  reuses shared Core/assessment types, and shows identity/terms/agreement/risk without
  inventing Core state. Summary, time, versions/solver, material allocation quantities
  and units/need-time, fixed booking times/available minutes, constraints, source
  freshness, evidence and assumptions are readable with explicit unavailable fields.
- Cautious status for stale commitment/snapshot, expired/missing source bounds,
  incomplete evidence or unresolved solver. No green safe styling. Live freshness
  checks display time and refreshes each minute; labeled preview uses historical basis.
- Recalculation exists only through an injected approved public adapter. Default and
  synthetic preview cannot perform it. Injected tests observe expected commitment/
  snapshot versions, pending/disabled submit, previous assessment retained, structured
  403/409/503 errors and retry, invalid replacement rejection and no fixture fallback.
  Correctly bound deterministic repeat is accepted; response receipt refreshes display
  time. Receipt does not claim risk transition, fulfilled commitment or guaranteed delivery.
- `ImpactDetailPage` shows trigger/resources/ETAs/evidence, before/after versions,
  candidates, confirmed impacted, verified unaffected, UNKNOWN causal attribution,
  pre-existing unchanged constraints and NO_NEW_ADVERSE_DELTA separately. Shows
  material/HARD deadline-severity deltas, buffers and dependency table. Missing
  candidate results and evidence-free verified classifications remain UNKNOWN.
  Core risk change requires separate evidenced Core mapping; local intents are not proof.
- No concrete live P2 source is wired. `createCoreOnlySource` accepts P5's reader;
  its tests inject a reader and do not exercise live HTTP. Preview source is explicitly
  opt-in and not imported by production pages. Authored synthetic projections are
  illustrative UI data based on prior P2 examples, not persisted results or metrics.
  Example rendered fixture: PATTY required100 / allocated usable60 / reserved0 /
  eligible incoming0 / shortage40 pcs, snapshot2; com-001 confirmed impact versus
  buffered com-002, plus deliberately missing com-missing UNKNOWN. No engine run
  is claimed for the authored frontend fixture.
- Feature-scoped CSS follows shared dark cards; semantic headings/captions/headers,
  buttons/alerts/status, visible keyboard focus, scrollable tables with keyboard focus,
  wrapping and narrow-screen layout. No new package, auth/client/router/shell or graph stack.

### Validation commands and observed results

From `D:/dunno/0.SDC/MouManTAI/frontend`:

| Command | Observed result |
|---|---|
| `npm ci --no-audit --no-fund` | 148 locked packages installed; no manifest/lockfile change. Existing whatwg-encoding deprecation warning. |
| `npm test -- src/features/feasibility/pages.test.tsx` (initial) | Expected red: missing page module, no tests collected. |
| same command after initial implementation | 26 passed / 4 failed: case-sensitive evidence assertion and three async retry assertions; corrected test assertions/timing, not acceptance criteria. |
| `npm test -- src/features/feasibility/data.test.ts` (hardening red) | 3 failed / 3 passed: expired source, evidence-free unaffected, duplicate impact rows. Focused rerun after fixes: 6 passed. |
| `npm test -- src/features/feasibility/pages.test.tsx -t 'shows time\|shows impact HTTP'` | 4 passed / 26 skipped after test corrections. |
| `npm test -- src/features/feasibility/pages.test.tsx -t 'switching tenant\|keyboard-accessible\|causal deltas'` | 3 passed / 30 skipped. |
| `npm test -- src/features/feasibility/data.test.ts -t 'deterministic repeat\|display time'` | 2 failed before review fixes, then 2 passed / 6 skipped. |
| `npm test -- src/features/feasibility/pages.test.tsx -t 'response receipt time'` | 1 failed before time-refresh fix, then 1 passed / 34 skipped. |
| `npm test -- src/features/feasibility` (final) | **43 passed, 2 files, exit0**, no warnings. |
| `npm run typecheck` (final) | **PASS, exit0**. Root tsconfig has project references only. |
| `npx tsc --noEmit -p tsconfig.app.json` | **PASS, exit0** before final localized fixes; final build below rechecks application types after them. |
| `npm run build` (final) | **PASS, exit0**: `tsc -b && vite build`, 45 modules. Current shell bundle still has P5 placeholders; new unmounted pages are typechecked and Vitest-transformed, not production-mounted. |

Read-only code reviewer independently ran then-current 39 and 42 tests successfully.
It identified historical-only freshness and deterministic-ID incompatibility;
both verified against source and corrected with failing-then-passing regressions.
Follow-up minor receipt-time issue also reproduced red then corrected. This internal
review is not the user-required independent external approval.

NOT RUN: backend regression (no backend behavior changed), actual HTTP/page API
integration, PostgreSQL, supplier-delay/outbox, P3 call, full cross-feature E2E,
browser viewport/screenshot QA or production metrics. Responsive layout is CSS/DOM
coverage only. No broad repeated backend suite or Phase 7 work.

### Exact authored paths

New under `frontend/src/features/feasibility/`:

- `CommitmentFeasibilityPage.tsx` — FE-01.
- `ImpactDetailPage.tsx` — FE-02.
- `presentation.tsx` — lifecycle/loading/evidence/preview presentation.
- `models.ts` — P2 presentation projections/ports using shared Core types.
- `data.ts` — binding/freshness/recalculation/error adapters and Core-only reader seam.
- `preview.ts` — explicitly authored synthetic presentation fixtures/source.
- `feasibility.css` — scoped responsive/accessibility styling.
- `pages.test.tsx`, `data.test.ts` — 43 focused cases.

P2 documentation:

- `backend/app/feasibility/PHASE6_PLAN.md` — pre-implementation field map and scope.
- `backend/app/feasibility/PHASE6_HANDOFF.md` — exact P5 route imports/mounts,
  required public enrichment, field mappings and version/error/source responsibilities.
- `backend/app/feasibility/P2_PROGRESS.md`, `P2_REQUIREMENT_TRACE.md`,
  `P2_PHASE_REPORTS.md` — checkpoint, FE/PH6 evidence and preserved historical reports.
- `docs/TEAM_LOG.md` — P2 status/checkpoint and P2 blocker correction only.

### Handoff, safety and highest-risk open assumptions

P5 must mount pages/routes and supply approved authenticated public adapters,
authoritative operational input/current-version resolution, transactional version
checks, final shared assessment mapping, durable assessment/history/impact storage,
supplier-delay/outbox integration and evidenced Core risk transitions. Exact missing
detail fields and serialization responsibilities are in PHASE6_HANDOFF.md. Existing
caller-header scaffolding is not production authentication. Historical
EvaluationResult.shared_output_blocker is not used to determine current readiness.
Generic P5 outbox does not establish P2 supplier processor integration.

P3 must still confirm pure evaluator reuse/ProposedChanges and the serialized
hypothetical HTTP contract. No backend work reopened. Nonblocking SKU/unit binding
test additions recorded for a later backend checkpoint. Future approved branch sync
must preserve both owners' TEAM_LOG histories.

Highest risks: public detail response remains unapproved; feature ports are typed
seams, not wire validators or authorization; P5 must validate/decode wire responses
and provide complete trustworthy ledgers/currentness. Fixture examples do not prove
end-to-end assessment persistence. Current shared apiRequest loses structured HTTP
status, so an approved P5 error adapter is required for a live source.

**STOP after Phase 6 commit/feature-only ref verification for independent external
review. No Phase 7 or Main merge.**

## Phase 6 external review #1 corrections — PH6-R1-01 / PH6-R1-02

- **Reviewed baseline:** `a377b8bf18f0b38ba619c684d976c5663aeddacd`; clean
  `feat/p2-feasibility-engine` verified before edits. User accepted the frontend
  structure in principle and requested only these presentation-safety corrections.
- **State:** targeted P2-local corrections implemented/tested; independent correction
  review pending. Overall shared integration remains PARTIAL. Phase 7 NOT_STARTED.
  Correction commit and pushed feature ref SHA: see task response after commit.

### PH6-R1-01 — unsupported classification

The existing five P2 classification literals are now a runtime constant with the
TypeScript union derived from it. No backend enum or shared contract changed.
`validateImpact()` rejects the entire malformed impact response with explicit
502 `FeatureDataError`, code `INVALID_IMPACT_CLASSIFICATION`. Existing page loading
logic shows a visible error/retry state. No candidate is silently omitted,
converted into unaffected, dropped or replaced by fixture data. Tests construct
an intentionally malformed JSON.parse payload containing an unsupported runtime
classification, check the explicit error, UI retry/no fallback and non-mutation,
and exercise all five supported classification values.

### PH6-R1-02 — buffer evidence and proof dependencies

Only a nonempty buffer evidence array containing nonblank strings permits the
existing `Verified buffer` label. Empty/blank/missing references receive
`Reported buffer — evidence unavailable`; absent runtime fields do not crash
the evidence component. Input buffers and original classifications are unchanged.

For VERIFIED_UNAFFECTED, missing required buffer evidence (or missing buffers)
defaults to UNKNOWN with `UNAFFECTED_BUFFER_EVIDENCE_INSUFFICIENT`. Unrelated
row-level evidence_refs cannot retain a verified conclusion. An optional P2-local
presentation projection `unaffected_proof` can retain it only when independent,
complete before/after recalculation proof remains: explicit independent basis,
matching tenant/commitment/respective snapshot versions, both FEASIBLE with
COMPLETED solver/evidence_complete=true and nonblank supporting refs. The future
P5 adapter must establish independence, not merely supply arbitrary row refs.
Missing/incomplete/unresolved/mismatched proof cannot override the downgrade.
Other impact classifications are unaffected by unrelated buffer evidence gaps.
P5 still owns authoritative source validation; structural reference presence is
not proof of authenticity. PHASE6_HANDOFF.md documents this additive presentation
mapping; no public API, persistence or shared schema was implemented or changed.

### Validation (from frontend/)

| Command | Observed result |
|---|---|
| `npm test -- src/features/feasibility/impact-safety.test.tsx` (initial red) | 11 failed / 6 passed before fixes, reproducing silent unsupported classification, verified buffer labeling and unsupported unaffected conclusions. Corrected array parameterization in two test setups before green run. |
| same focused command (initial green) | 17 passed. |
| `npm test -- src/features/feasibility/impact-safety.test.tsx -t 'missing buffer evidence_refs'` | Failed before missing-field render guard (TypeError in Evidence); passed after correction, 1 passed / 23 skipped. |
| `npm test -- src/features/feasibility/impact-safety.test.tsx` (final focused) | **24 passed**, exit0, no warnings. |
| `npm test -- src/features/feasibility` | **67 passed, 3 files**, exit0, no warnings; all original 43 tests retained unchanged. |
| `npm run typecheck` | **PASS**, exit0. |
| `npx tsc --noEmit -p tsconfig.app.json` | **PASS**, exit0; checks actual application project. |
| `npm run build` | **PASS**, exit0; `tsc -b && vite build`, 45 shell modules. P2 pages remain unmounted as previously documented. |

Backend tests, live HTTP/auth/database/P3/P5/outbox integration, E2E, browser QA
and metrics NOT RUN: no backend behavior or shared implementation changed.
Injected JSON/adapter/component tests are not production API validation.

### Exact changed files

- `frontend/src/features/feasibility/data.ts` — runtime rejection and proof-aware conservative mapping.
- `frontend/src/features/feasibility/models.ts` — same five runtime literals and narrow optional independent-proof projection.
- `frontend/src/features/feasibility/ImpactDetailPage.tsx` — evidence-aware buffer label/render guard.
- `frontend/src/features/feasibility/impact-safety.test.tsx` — 24 new regression/compatibility tests, including non-mutation.
- `backend/app/feasibility/P2_PROGRESS.md` — correction checkpoint.
- `backend/app/feasibility/P2_REQUIREMENT_TRACE.md` — correction acceptance evidence.
- `backend/app/feasibility/P2_PHASE_REPORTS.md` — this appended correction report; earlier reports preserved.
- `backend/app/feasibility/PHASE6_HANDOFF.md` — classification/error/proof/evidence mapping rules.
- `docs/TEAM_LOG.md` — P2-only appended correction record.

Existing FE-01/FE-02 page structures, states, tenant/identity/version checks,
prior-assessment retention and no-fixture-fallback remain covered by the preserved
suite. No P3/P5-owned implementation, shared client/auth/routing/dependency,
backend enum/calculation, persistence or Phase 7 work.

**STOP after feature-only commit/push verification for independent Phase 6
correction review. P5/P3 integration blockers remain as documented previously.**

## Phase 6 external review #2 — PH6-R2 minimal fail-closed correction

- **Reviewed baseline:** `de8749a06a117c06ec3eede57725749bb8ca4557`; clean
  `feat/p2-feasibility-engine` verified before edits. User requested removal of
  the R1 frontend metadata-proof exception and a minimal buffer support gate.
- **State:** local correction implemented/tested, independent Phase 6 review pending.
  Overall production integration PARTIAL; Phase 7 NOT_STARTED. Commit/pushed feature
  SHA and final clean-state verification: see phase response.

### Changes and presentation rules

Removed `hasIndependentUnaffectedProof()` and its use from `data.ts`, and removed
the unused `unaffected_proof` property/assessment-proof helper type from `models.ts`.
There is no frontend before/after classification algorithm or metadata-proof bypass.

VERIFIED_UNAFFECTED now requires at least one positive evidence-backed supporting
buffer and adequate nonblank refs for every conservatively required buffer. If the
list is empty, no positive supported buffer exists, or required buffer evidence is
missing, the projection becomes UNKNOWN with
`UNAFFECTED_BUFFER_EVIDENCE_INSUFFICIENT`. Row-level classification evidence remains
mandatory. FEASIBLE/COMPLETED/evidence-complete before/after metadata cannot override
either gate, including legacy runtime payloads with the removed proof property.
Decimal-string sign/nonzero validation avoids float rounding/underflow and rejects
zero, negative, nonfinite and malformed values as positive proof. It is a structural
display gate, not an implementation of backend `_classify()` or feasibility arithmetic.

PH6-R1 unsupported runtime classification rejection, all five classifications,
buffer labels, FE-01/FE-02 structures, tenant/version binding, prior-result retention
and no-fixture-fallback are unchanged. Inputs remain unmodified. Independent proof
is documented only as a future P5 authoritative-contract decision, not a frontend
exception. P5 still owns source authenticity and production integration.

### Validation (from frontend/)

| Command | Observed result |
|---|---|
| `npm test -- src/features/feasibility/impact-safety.test.tsx -t 'metadata\|buffer value\|positive decimal\|required buffer'` | Red: **10 failed, 1 passed, 26 skipped** before correction. Same focused rerun: **11 passed, 26 skipped** after correction. |
| `npm test -- src/features/feasibility/impact-safety.test.tsx` | **37 passed**, exit0, no warnings. The former metadata-only preservation test now requires UNKNOWN; new empty-list/zero/invalid value/missing-row-evidence regressions and positive exact-decimal cases included. |
| `npm test -- src/features/feasibility` | **80 passed, 3 files**, exit0, no warnings. |
| `npm run typecheck` | **PASS**, exit0. |
| `npx tsc --noEmit -p tsconfig.app.json` | **PASS**, exit0; actual application project checked. |
| `npm run build` | **PASS**, exit0; `tsc -b && vite build`, 45 shell modules. P2 pages remain unmounted, as previously documented. |

No backend tests, live HTTP/auth/database, P3/P5/outbox integration, E2E, browser QA
or metrics run for this frontend-only correction. No shared dependencies or APIs
changed. Tests use injected synthetic/runtime JSON, not production evidence.

### Exact changed files

- `frontend/src/features/feasibility/data.ts` — remove bypass; minimal positive-buffer/refs gate.
- `frontend/src/features/feasibility/models.ts` — remove unused proof property/type.
- `frontend/src/features/feasibility/impact-safety.test.tsx` — update metadata-only preservation expectation; add fail-closed/positive decimal and input-preservation coverage.
- `backend/app/feasibility/P2_PROGRESS.md` — current correction checkpoint.
- `backend/app/feasibility/P2_REQUIREMENT_TRACE.md` — superseding PH6-R2 evidence.
- `backend/app/feasibility/P2_PHASE_REPORTS.md` — this appended report; R1 report preserved as historical.
- `backend/app/feasibility/PHASE6_HANDOFF.md` — current minimal gate; independent proof deferred to P5.
- `docs/TEAM_LOG.md` — appended P2-only PH6-R2 record.

**STOP after feature-only commit/push verification for independent Phase 6 review.
Do not begin Phase 7. Previously documented P3/P5 integration blockers remain.**


## Phase 7A — Independent implementation ready; production integration BLOCKED — 2026-10-21

### A. Git scope and baseline

- New branch `feat/p2-phase7-integration` created directly from fetched Main
  `ee4dfc73deb998a5af902422220cb1a34e0182cc`; expected PR #4 ancestry passed.
- Initial worktree/index clean; no merge/rebase/cherry-pick/revert state; target
  local/remote branch absent. Old P2 branch stayed `b7b2c60f1859c83b5060ae982caf57d02985858b`.
- Commit/push only this new branch is explicitly authorized. No PR, merge,
  force-push or Main/old-branch push. Final commit/remote verification is recorded
  in the task response after publication (a commit cannot embed its own SHA).

### B. Requirement coverage and gap audit

The current section of `P2_REQUIREMENT_TRACE.md` audits 131 unique owner/system,
API/event/data/test/metric/handoff criteria individually. Historical statuses are
retained below it. The audit preceded implementation; this report records the
final observed results. No required criterion was silently made optional.

Closed independently: P0 complete two-commitment supplier pipeline, complete
F2-06 two-impacted fixture, supplier input/source/ETA binding, canonical assessment
mapping, typed history contracts/reference semantics, available stock read adapter,
all five measured synthetic metrics and accurate early P3/P5 handoffs.

Partial: authoritative snapshot assembly can only consume fields actually exposed
by P5; reference history is not durable; event intents are not publication; frontend
views remain unmounted. Blocked: P5 trusted auth, complete source contracts/version
read token, DB migrations/persistence/transactional writer/outbox, production route
mounting and public UI detail transport; P3 full snapshot and typed recovery adapter
acceptance. Direct P1 requested BusinessContext-to-evaluator mapping remains a joint
P1/P5/P2 contract task; current evaluator requires a confirmed Core target. Optional
CP-SAT, graph library, forecasting and live connectors were not introduced.

### C. Actual implementation and safeguards

- `supplier_pipeline.py`: immutable SupplierDelayInputs binds declared snapshot IDs,
  previous/updated ETA, exact delivery/supplier/SKU/quantity/unit/warehouse/confirmation
  identity, typed source claim and tenant. Existing `assess_impact` validates source
  links, event interval, resource change and version progression, then reuses the
  single `evaluate` for before/after candidate calculations. No operational writes.
- `pipeline_fixtures.py`: explicit synthetic production rates, exclusive line,
  continuous shifts, plans/transit and complete empty job ledger; original
  material-only fixtures and UNKNOWN expectations remain unchanged. The NEW complete
  two-impact fixture explicitly books com-002 at 10:40 after the 09:00–10:40
  first job, before the delayed 11:00 receipt; both baseline assessments are
  FEASIBLE and both after assessments INFEASIBLE, with two at-risk intents.
- `demo.py`: eight runnable synthetic scenarios, showing event, source claim,
  snapshots, candidates, full before/after calculations, classifications/deltas,
  buffer/evidence/reasons and replay result. Process-local repository returns no
  new intents on identical replay. Different causes retain distinct event IDs.
- `history.py`: canonical FeasibilityAssessment mapper, exact impact-to-result
  binding and actual Impact Set (including empty), AssessmentRecord with complete
  snapshot/Core/proposal reproduction, typed repository interface, tenant lookup,
  defensive serialized copies, immutable/idempotent history and cause conflicts.
  SyntheticHistoryRepository is never installed as a public durable adapter.
- `service.py`: extracted existing deterministic evaluation identity without
  changing arithmetic, status, assumptions or hash inputs. History verifies that
  identity so hypothetical results cannot be stored as baseline calculations.
- `impact.py`: additive local calculation_input_digest binds complete snapshots,
  change and before/after Core inputs, including unresolved results. Existing
  impact/event/dedup identities and all five classification semantics unchanged.
  Hashes bind content; they are not signatures or source trust guarantees.
- `resource_adapter.py`: actual P5 get_resource_snapshot read under no_autoflush;
  exact total/reserved/available, units, timestamps and per-resource versions,
  explicit absent resources and INCOMPLETE/UNAVAILABLE diagnostics. No global
  snapshot version, lot provenance, validity interval or reservation owner invented.
- `currentness.py`/`router.py`: extracted existing 503 missing-version / 409 stale
  guard unchanged and reused in benchmark; P5 transaction must still recheck it.
- `benchmark.py`/labels/tests: independent fact-based labels and metric arithmetic;
  deliberate erroneous predictions and disabled-current-guard mutation are caught.
- No P1/P3/P4/P5 implementation, shared schema, migration, package manifest,
  authentication, app shell/router mount or approved original fixture was changed.

### Intermediate 7A-1 / 7A-2 checkpoint

P3 official example: FEASIBLE / COMPLETED. Supplier pipeline 14 passed. Early
`PHASE7A_HANDOFF.md` documented exact P3 and P5 interfaces before optional domain
work. The runnable P0 remained protected throughout; no Phase 7B started.

Internal requesting-code-review review found two gaps: history accepted mixed
calculation/input contents, and stale metric initially used a benchmark-only gate.
Both were reproduced with failing tests and fixed. A follow-up reproduced missing
Core results paired with complete Core input; full impact input binding fixes it
while preserving legitimate missing-Core UNKNOWN. This internal review is not
external independent approval or authorization for Phase 7B.

### D. Commands and observed validation

Backend commands below run from `D:/dunno/0.SDC/MouManTAI/backend`:

| Command | Observed result | Kind / dependency |
|---|---|---|
| `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_supplier_pipeline.py -q -p no:cacheprovider` | 14 passed, 0 failed, 0 skipped | Synthetic pipeline; no DB/network |
| `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_history.py app/feasibility/tests/test_resource_adapter.py -q -p no:cacheprovider` | Initial 11 passed, 0 failed/skipped; later history binding regressions added | Domain + isolated in-memory SQLite actual Core stock query |
| `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_history.py app/feasibility/tests/test_benchmark.py app/feasibility/tests/test_router.py app/feasibility/tests/test_service.py -q -p no:cacheprovider` | 70 passed, 0 failed/skipped, 1 warning | After first review fixes; additional missing-Core regression added afterward |
| `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_history.py app/feasibility/tests/test_impact.py app/feasibility/tests/test_supplier_pipeline.py app/feasibility/tests/test_benchmark.py -q -p no:cacheprovider` | 53 passed, 0 failed/skipped | Final focused content-binding/metric changes |
| `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` | Final 291 passed, 0 failed, 0 skipped; 1 warning | 212 P2 + 79 P5; unit/synthetic/API and isolated SQLite integration, not live E2E |
| `python -B -m app.feasibility.benchmark --iterations 10 > app/feasibility/PHASE7A_METRICS.json` | Exit 0; counts/results below | Synthetic labels and actual shared public current-version guard |
| `python -B -m app.feasibility.demo > $env:TEMP\moumantai-p2-phase7a-demo.json` | Exit 0; 8 scenarios, all replay_new_intent_count=0 | Synthetic calculation and reference history only |

Runtime probe (backend, exit 0):

```powershell
python -B -c "from fastapi import FastAPI; from app.core.router import router as core; from app.feasibility.router import router as p2; from app.core.schemas import FeasibilityAssessment as canonical; from app.feasibility.history import FeasibilityAssessment as mapped; from app.feasibility.service import Commitment as consumed; from app.core.schemas import Commitment; keys=[(m,r.path) for r in [*core.routes,*p2.routes] if hasattr(r,'methods') for m in r.methods]; assert len(keys)==len(set(keys)); assert keys.count(('POST','/v1/commitments/{commitment_id}/assess'))==1; assert canonical is mapped and Commitment is consumed; app=FastAPI(); app.include_router(core); app.include_router(p2); assert 'post' in app.openapi()['paths']['/v1/commitments/{commitment_id}/assess']; print('PASS: canonical class identity; unique combined routes; one P2 assess POST'); from app.feasibility.production_fixtures import build_production_example; from app.feasibility.service import evaluate; s,c=build_production_example(); r=evaluate(s,None,c); print('P3 fixture:',r.status.value,r.solver_status.value)"
```

Frontend commands from `D:/dunno/0.SDC/MouManTAI/frontend`:

| Command | Result | Kind |
|---|---|---|
| `cmd /c npm test` | 108 passed, 0 failed, 5 skipped (7 files passed, 1 skipped) | jsdom/UI tests; live API tests skipped without LIVE_API=1 |
| `cmd /c npm run typecheck` | Exit 0, no errors | TypeScript |
| `cmd /c npm run build` | Exit 0; 94 modules; Vite 7.3.7 | TypeScript application build + production bundle |

Environment: Python 3.14.3, pytest 9.1.1 (outside declared >=8.3,<9), Node
24.14.0, npm 11.9.0. No dependency install/change. Existing Starlette/httpx
TestClient deprecation warning remains. Vitest prints a jsdom pooling performance
suggestion; no frontend failure. No destructive seed/reset, migration, live
PostgreSQL, authenticated production API or actual browser/API E2E was run.

### E. Independent synthetic metrics

Labels: `benchmark_labels.json`, authored from stock/reservation/ETA/production
facts, never copied from evaluator predictions. Six feasibility cases (five
historical status observations plus a missing-current-authority acceptance case),
eight impact scenarios / 16 commitment observations; only six causal labels known.
Ten null causal labels are explicitly excluded from recall/false-alert denominators;
nine actual impact outputs remain UNKNOWN. Unknown on a labelled positive would
count as missed recall; UNKNOWN never counts as FEASIBLE or an alert.

| Metric | Definition / observed numerator and denominator | Result |
|---|---|---|
| False-feasible | FEASIBLE among independently INFEASIBLE cases | 0 / 2 = 0% |
| Impacted recall | Confirmed impact among genuinely impacted labelled commitments | 3 / 3 = 100% |
| False-alert | Confirmed impact among labelled no-new-impact commitments | 0 / 3 = 0% |
| Stale-result | Invalid/missing current version accepted as current FEASIBLE through actual public-route guard | 0 / 2 = 0% |

Missing current authority can still yield historical FEASIBLE in the pure evaluator;
the actual guard rejects it with 503. Stale version rejects with 409. Disabling the
guard in a test changes measured stale rate to 1/2. This is not a DB concurrency,
transaction rollback or stale UI production measurement. Zero denominator returns
null, never invented 0%/100%. Counts describe unique labels, not repetitions.

Latency, 10 repetitions after one untimed warmup: feasibility median 2.2536 ms / p95 3.4925 ms (n=60); impact median 20.3921 ms / p95 28.1276 ms (n=80). Measured with perf_counter_ns; validation/calculation included, fixture creation/network/storage excluded. Small synthetic samples do not establish live SME accuracy or production reliability.

### F. P3 handoff

Exact imports/signature, complete typed Snapshot, validation/version/tenant rules,
supported quantity/deadline/start hypotheses, unsupported strategies and integration
commands are in `PHASE7A_HANDOFF.md`. Official fixture observed FEASIBLE/COMPLETED.
Read-only P3 branch `ca7517c` has an integrations adapter accepting the module
function, while its older adapter expects metadata-only references/dictionaries.
P3 must supply authoritative full snapshot and typed ProposedChanges; no second
ATP/BOM/capacity engine, synthetic-to-authoritative promotion or unmerged import.

### G. P5 handoff

`PHASE7A_HANDOFF.md` specifies priority/owner/input/output/reuse/missing interface
and joint tests for source authority/version vector, safe requester-to-SERVICE
identity, canonical result-to-Core writer, append-only history schema/indexes,
unique cause/payload binding, atomic state/history/audit/outbox, supplier source
verification, five production routes, and public frontend transport/detail mapping.
P2 reference history and input hashes are implemented; shared SQLAlchemy/Alembic
and transaction adapters are proposals awaiting P5 review. No Core guard weakened.

### H. Remaining work / review gate

Independent P2 Phase 7A work is implemented and locally validated; overall P2
production integration remains PARTIAL/BLOCKED. No production durability, external
source authentication, current atomic snapshot, live UI/DB/API or end-to-end
operational correctness is claimed. Public defaults remain unavailable.

Recommended Phase 7B sequence, only after external approval: P5 review source and
version contracts → P2 full source assembly → P5 transaction/history/Core/outbox
adapter → P3 typed authoritative reuse → public API/detail transport and route
mounting → real API/UI joint happy/unsafe/replay/race tests. Stop after the new
feature branch push for independent review; do not create a PR or integrate Main.

### Phase 7A implementation commit evidence

```text
d16aa45c73e7b09dfb00b9036e7c654cdbfa7a1e test(p2): measure independent feasibility and impact metrics
6de2e7b8cdf1450887db282b9dc6094c575d0f7d feat(p2): add bound history and resource readiness adapters
653936ade06a705fa265bbaf711aa79cf79afa78 feat(p2): add validated supplier-delay impact pipeline
```

Final documentation commit and remote SHA: see task response after feature-only push.
