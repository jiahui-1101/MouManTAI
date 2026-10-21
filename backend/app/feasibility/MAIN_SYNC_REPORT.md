# P2 Main synchronization and compatibility report

## Latest attempt — 2026-10-21 (BLOCKED; merge prepared, not committed)

- **Refs:** P2 pre-sync HEAD `4e04a662eda8c2b96505e27db976727b2f9d336f`; fetched
  `origin/main` `0485d3d3490d9dacb97aedb634e99c6538327bbf`; fetched P5 tip
  `6e09a5584000ed1b93d1f568d56e9675016b2e25`, verified as an ancestor of Main
  through PR #2. Safety ref `backup/p2-pre-sync-4e04a66-20261021` points to the
  exact pre-sync P2 HEAD.
- **Merge/conflicts:** `git merge --no-ff --no-commit origin/main` is in progress.
  The only merge conflict was `docs/TEAM_LOG.md`; it was resolved by retaining
  both P2 history and incoming P5 records/QA rows. No code, contract, auth, Core,
  database, migration, or other-owner implementation merge conflict occurred.
- **Contract compatibility:** P5's shared `FeasibilityAssessment` now accepts
  `affected_commitment_ids: []` and describes the field as the actual Impact Set.
  P2's stale empty-set blocker marker and rejecting test expectation were removed
  in P2-owned code/tests. P2 still returns a detailed local `EvaluationResult`;
  no shared assessment persistence adapter was added.
- **UNKNOWN/version/purity:** P2 evaluator retains `UNKNOWN` for missing/stale or
  uncertain evidence and binds its calculation to commitment and snapshot
  versions. The calculation and impact engine remain pure; only the explicit
  P5 writer/processor ports may persist or publish. Core's `UNKNOWN` branch does
  not set `AT_RISK`. P5's generic `CommitmentService.assess` checks the supplied
  commitment version but does not verify current snapshot authority or persist
  assessment history itself.
- **Route/integration blocker:** P2 and P5 both define
  `POST /v1/commitments/{commitment_id}/assess` with incompatible wire contracts.
  P2 accepts `{expected_commitment_version}` and returns a shared assessment;
  P5 accepts a `FeasibilityAssessment` body and returns a Core `Commitment`.
  The P2 API test app mounts `core_router` first, so P5's route captures the path
  and P2 boundary requests return 422. The P2 backend suite therefore reports
  **169 passed, 12 failed**, all 12 on this route collision. Resolving ownership
  or changing the endpoint requires a P5/API contract decision; no unilateral
  route change was made.
- **Handshake-test scope:** P5's handshake tests submit hand-authored
  `FeasibilityAssessment` JSON directly to the Core endpoint. They verify Core
  state/audit/outbox behavior for supplied statuses, including
  `UNKNOWN != INFEASIBLE`; they do not invoke P2's `evaluate()`, P2 router,
  snapshot authority, writer, assessment history, or frontend.
- **Focused validation:** the two P2 regression tests for removing the stale
  blocker passed after a red run (2 passed); P2's empty Impact Set schema test
  passed (1 passed). P2 full suite command:
  `python -B -m pytest -o 'addopts=' app/feasibility/tests -q -p no:cacheprovider`
  from `backend/` — **169 passed, 12 failed, 1 Starlette/httpx deprecation
  warning**. Failure details are in the compatibility blocker above.
- **Not run after the blocker:** P5 full backend suite, combined backend suite,
  runtime import probe, P2/P5 frontend tests, TypeScript validation, production
  build, database migration/live PostgreSQL, and E2E. The mandated stop rule was
  followed because the failure needs a shared route decision.
- **Current Git state:** merge remains in progress with `MERGE_HEAD` at the new
  Main SHA. There is no merge commit/resulting SHA, no commit was created, and no
  push was made. Main and P5 refs were not modified. Phase 7 was not started.
- **Review required:** P5 must decide the canonical assessment endpoint/route
  ownership and connect P2's actual pure evaluator through authoritative
  snapshot/commitment version checks, assessment history/persistence, and Core
  audit/outbox transition handling. Then rerun the full regression matrix before
  creating or pushing the synchronization checkpoint.

## Historical report — previous synchronization of Main `4ec2ba1`

## Git and preservation evidence

- Working branch: `feat/p2-feasibility-engine`.
- Approved starting HEAD: `d28b63ab5fa82c66633ad18211b9c4fa83ffbbe4`.
- `git fetch origin` advanced Main from aedb152 to
  `4ec2ba1ef7ede4a67352631178a73a6882bcd774` (P5 foundation/registry PR merge).
- Local backup ref `backup/p2-before-main-sync-d28b63a` resolves to approved HEAD.
- Initial tracked worktree/index clean. Nine existing untracked P2 bytecode files
  were SHA256-inventoried before merge and verified unchanged afterward. No stash,
  deletion, reset, cleanup, force-push or modification of local `main` performed.
  Main's `.gitignore` now ignores those retained files.
- Read incoming root `AGENTS.md`, system/owner requirements/team decisions, local
  Master `D:\dunno\0.SDC\P2_CODEX_MASTER.txt.txt`, P2 progress/trace and relevant
  shared schemas/fixtures/tests before integration. Owner requirements are now
  canonical at `docs/requirements/PERSON_2_FEASIBILITY_REQUIREMENTS.md`.
- `git merge-tree --write-tree HEAD origin/main` previewed only two conflicts.
  `git merge --no-ff --no-commit origin/main` reproduced them; no behavioral or
  shared-data/contract conflict arose.
- `backend/app/feasibility/__init__.py`: union of documentation only, retaining
  P5's deterministic-boundary description and P2's provisional-adapter caveat.
- `docs/TEAM_LOG.md`: union of adjacent QA rows (three historical P2 rows and
  P5's ec0458d QA row). Other P5 changes merged automatically. Verification found
  zero incoming non-P2 lines missing; P2-only sync status/records were added.
- `git diff --cached origin/main -- backend/app/core backend/app/db
  backend/migrations contracts AGENTS.md docs/REQUIREMENTS_SYSTEM.md` produced no
  differences. P5-owned implementations, contracts and current canonical docs
  were not modified. `git diff --cached --check` passed.
- Merge commit SHA, exact parents, feature-only push and remote-ref verification
  are recorded in task response after creating the commit. Backup ref stays local.

## Tests actually run

Repository root:

```powershell
python -B -m pytest backend/app/feasibility/tests/test_snapshots.py backend/app/feasibility/tests/test_bom.py backend/app/feasibility/tests/test_inventory.py -q -p no:cacheprovider
```

PASS: all 66 existing P2 tests, exit 0. Main's pytest configuration adds quiet
output, so the observed output is 66 passing dots. No existing tests were changed.

From `D:\dunno\0.SDC\MouManTAI\backend`:

```powershell
python -B -m pytest tests/test_contracts.py tests/test_smoke.py tests/test_registry.py -q -p no:cacheprovider
```

PASS: 7 tests, exit 0: shared fixture/serialization/context/timestamp validation,
health and SQLite registry transitions/version/audit/outbox/tenant scope. One
Starlette TestClient deprecation warning advises httpx2; no shared dependency
changes were made. These SQLite tests do not verify live PostgreSQL migrations.

Same backend directory, runtime import probe:

```powershell
python -B -c "from app.feasibility.inventory import calculate_atp; print(calculate_atp.__module__)"
```

FAIL: exit 1, at inventory.py:10 importing backend.app.feasibility.bom:
`ModuleNotFoundError: No module named 'backend'`.

P5 backend uses `app.*` (uvicorn with `--app-dir backend`, setuptools includes
`app*`, backend pytest pythonpath `.`). P2 internal imports/tests still use
`backend.app.feasibility.*`; root regression success does not establish runtime
compatibility. A root-path workaround can also load duplicated model classes under
both namespaces, so it is not a reliable integration fix.

Required P2-local adaptation, reported for a separate reviewed change: package-
relative imports in models/materials/bom/inventory/fixtures; align test imports to
`app.feasibility.*` with a deliberate test import path. Do not edit shared runtime
configuration or introduce dual-import aliases silently. This task changed no
calculation logic, imports or tests, beyond the mechanical package docstring merge.

Host Python is 3.14 (`C:\Python314\python.exe`); no backend .venv exists. Installed
pytest 9.1.1 exceeds P5's declared `pytest>=8.3,<9` dev range. Installed Pydantic
2.13.4, FastAPI 0.139.2, SQLAlchemy 2.0.51, Alembic 1.20.0 and psycopg 3.3.4 fall
within their declared ranges. No missing dependency blocked the selected tests;
their success is not a pinned-environment validation. No packages were installed.

Frontend/build, DB migration/live PostgreSQL, full E2E and Phase 3 tests NOT RUN:
no frontend change; live DB smoke remains P5's documented Docker/WSL blocker;
P2 evaluator and feature integrations are not implemented. No external DB used.

## Actual shared integration changes and remaining blockers

Now available: FastAPI app/Core registry/router/tenant dependencies, shared
Pydantic/TypeScript schemas, audit/outbox persistence foundation, Alembic/Compose,
Vite frontend shell/routes/fetch client and checked-in owner requirements. P2
progress/trace no longer characterize these as absent.

`app.core.schemas.FeasibilityAssessment` already includes assumptions, typed
FeasibilityState/SolverStatus and ConstraintReason. ConstraintReason uses deadline
and required HARD/SOFT/INFORMATIONAL severity; P2 needed_by/material balance detail
requires deliberate mapping. Shared affected_commitment_ids requires at least one
ID. Reuse these types in the future evaluator without editing P5-owned schemas.

`DemoFixture.operational_snapshot` is a dict summary rather than a typed complete
P2 OperationalSnapshot. It lacks explicit P2 source freshness/validation evidence,
lot/reservation ownership, complete active competing commitments, calendars/jobs,
logistics cutoff and supplier-confirmation associations. Generic synthetic evidence
refs do not meet the typed receipt provenance gate. A reviewed adapter/data extension
is required; do not invent evidence/default safe supply or reinterpret freshness
VALID as P2 CURRENT without an agreed conversion.

Shared fixture IDs/catalog: tenant_demo_01, com_001, BURGER uses BUN/PATTY/SAUCE/
PACKAGING. Existing approved P2 regression fixture uses tenant-synthetic-p2,
com-001 and WRAP. Preserve both until their source adapter/catalog/fixture alignment
is reviewed. The shared fixture's two affected IDs are illustrative assessment
data, not a full set of competing commitment inputs for P2 calculations.

Still pending: P2-specific OperationalSnapshot/ProposedChanges agreements and source
adapters, assessment/impact history storage/version authority, source authenticity,
full capacity/evaluator, P2 events/registration/API/UI and P3 command-side reservation
concurrency. Shared Core foundation is present; these gaps are P2 integration/
cross-owner handoff work rather than a reason to claim the skeleton is absent.

## Authored changes on top of incoming Main

Only mechanical feasibility package docstring and TEAM_LOG merge resolution,
P2-only team status/sync entries, P2_PROGRESS.md, P2_REQUIREMENT_TRACE.md,
P2_PHASE_REPORTS.md checkpoint link and this report. All other shared files are
incoming Main content unchanged. No Phase 3 work, PR or merge into Main.
