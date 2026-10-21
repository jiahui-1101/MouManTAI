# Phase 2 implementation plan

Approved scope: the user's 2026-10-21 Phase 2 instruction and approved Phase 1
baseline `0d990d99bfe973f7b13295d1e005639a0f61adbd`. Work stays on the existing
feature branch. One phase commit follows tests and reports; no later phase work.

## Design and contract decisions

Use the existing frozen Pydantic snapshot, with P2-local additive conversion,
waste, and warehouse fields. A source-backed conversion maps one SKU/unit
directly to its catalog base unit; no inferred reverse or chained conversions.
BOM quantities are per one parent base unit, with an explicit consumption
multiplier (1 means no known loss). Recursive expansion reports leaf materials,
paths, evidence, and assumptions; cycles or missing data yield UNKNOWN.

`explode_bom(snapshot, *, tenant_id)` expands all confirmed demand.
`calculate_atp(snapshot, *, tenant_id, as_of=None)` allocates all expanded demand
in one immutable calculation. Default as_of is capture time, not wall-clock time.
Material-only COVERED/SHORTAGE/UNKNOWN results are not full feasibility claims.
Phase 3 will map these into the shared FeasibilityAssessment after capacity checks.

Active reservations are removed once from free lots, held for their owners,
then credited across that owner's matching lines without reuse. Free supply is
allocated by material-use time / commitment ID / version / line / SKU; lots use
earliest expiry then ID, followed by receipts ordered by ETA/ID. Expiry is
exclusive at material use; confirmed ETA is inclusive at both material-use and
logistics cutoff. Warehouse-specific demand cannot use another warehouse or an
unlocated receipt. A past-due outstanding receipt is insufficient evidence, not
additional stock. Relevant stale/missing evidence makes the batch UNKNOWN to
avoid a confident result based on incomplete competing demand or supply.

## Tasks

- [x] Add failing BOM/conversion tests: recursive propagation, branches, cycles,
  missing BOM, waste, explicit/missing/conflicting conversion, tenant, precision.
- [x] Implement source-backed model extensions and `bom.py`; run those tests.
- [x] Add failing ATP tests: F2-01..04/07 material outcomes, reservation owners,
  shared stock/receipts, multiple lines, expiry, cutoff equality, warehouse,
  stale/missing data, supplier evidence, non-mutation and deterministic ordering.
- [x] Implement `inventory.py` and immutable material result types; run ATP tests.
- [x] Review implementation against Phase 2 requirements and run focused P2
  regression once stable. F2-01..04 evidence is material-only at this phase;
  overall INFEASIBLE/FEASIBLE assessment orchestration remains Phase 3.
- [x] Update trace, progress, phase report, fixture policy and P2-only team log;
  inspect staged diff, commit locally, push only the feature branch as expressly
  requested in the user's final completion instruction, verify SHA, then stop.

All implementation/test/document preparation tasks are complete. Commit/push
verification is recorded in the phase response after the report commit exists.

No P5-owned code, migrations, auth, capacity scheduling, evaluator, event engine,
API or UI changes. Shared contracts and external source authenticity remain
P5 dependencies. Authorized execution/reservation concurrency remains P3/P5.
