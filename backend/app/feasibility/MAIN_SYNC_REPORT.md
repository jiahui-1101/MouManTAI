# P2 Main synchronization and compatibility report

## Final Main sync after P5 PR #3 — validated, 2026-10-21

- **Refs and commits:** Approved pre-sync P2 baseline was
  `4e04a662eda8c2b96505e27db976727b2f9d336f`, retained by
  `backup/p2-pre-sync-4e04a66-20261021`. Recovery ref
  `backup/p2-interrupted-merge-0485-before-pr3-20261021` points to snapshot
  `2466c6b049e2da30b538f51cba1e5d3c1b363088` of the previously staged merge
  tree. Intermediate local merge `d242c31788b7d0ee97a6e95278f2e11c7137e7a9`
  preserves P2 and prior Main `0485d3d3490d9dacb97aedb634e99c6538327bbf`.
  Final sync merge `f82f9a4279de6263236bc3d7ec04772441eb2c8b` has parents
  `d242c31788b7d0ee97a6e95278f2e11c7137e7a9` and fetched Main
  `0c082ceb0d1fa926a8b5fdf53b451505d3bd2250`. Main contains P5 PR #3 and D-013
  commit `2f06a6ac7451def712aa080eb6c1189b8d57f216`.
- **Merge and ownership:** The interrupted PR #2 merge matched the preceding
  report, had no unmerged entries, and contained only staged work. It was saved
  under the recovery ref and completed as the intermediate merge. The later merge
  had one conflict, `docs/TEAM_LOG.md`; resolution retained the prior P2 sync
  record and both incoming P5 records (T3.4 and D-013), then appended this P2
  result. No code, schema, authentication, Core, database, migration, or other
  owner implementation conflict required a unilateral resolution.
- **Changed-file ownership:** P5 PR #2/#3 changes are in
  `backend/app/core/**`, `backend/app/db/**`, `backend/migrations/versions/0003*`
  through `0005*`, `backend/tests/**` (Core/API/E2E/handshake suites),
  `contracts/**`, `frontend/src/shared/**`, `frontend/src/layout/**`, P5
  overview/activity pages and tests, `frontend/src/app/**`, `frontend/src/styles.css`,
  and `scripts/reset_and_seed_test_db.py`. P2-owned compatibility edits from the
  PR #2 recovery are limited to `backend/app/feasibility/service.py`,
  `backend/app/feasibility/tests/test_router.py`,
  `backend/app/feasibility/tests/test_service.py`, this report, P2 progress/trace,
  and the P2 TEAM_LOG record. No P2 Phase 6 frontend source or safety test changed.
  `docs/TEAM_LOG.md` is the coordinated history file and contains both owners'
  records.
- **D-013 route and contract:** Core's duplicate public POST assess route is
  removed. The P2 router is the only `/v1/commitments/{id}/assess` registration
  when both routers are mounted. Its request remains
  `{expected_commitment_version}` and its response is the shared
  `FeasibilityAssessment`; P5's Core method remains an internal writer returning
  a Core `Commitment`, so P5 must map that result through the P2 writer adapter.
  A runtime probe mounted both routers in a temporary FastAPI app and found no
  duplicate method/path pairs. The production `app/main.py` still mounts only
  Core, so P2 is not production-mounted.
- **Shared contract and evaluator:** P5's canonical assessment schema accepts
  `affected_commitment_ids: []` as an empty actual Impact Set. P2 uses Core
  assessment/enums and keeps its detailed `EvaluationResult` as a local pure
  calculation result. P2 calculation and impact functions do not write Core
  state. `UNKNOWN` remains distinct from `INFEASIBLE`; missing/stale evidence
  fails closed, and the evaluator result remains bound to the selected
  commitment and operational snapshot versions. D-013 Core guards tenant,
  commitment identity and commitment version; current snapshot authority and
  durable P2 assessment history still require the P5 writer transaction.
- **Service authorization boundary:** The user requesting an assessment and the
  trusted process applying it are separate identities. D-013 permits only
  `SERVICE`/`SYSTEM` in `CommitmentService.assess`; its 16 identity tests reject
  normal user contexts with 403 and accept a directly constructed trusted
  context. P2's writer dependency is unconfigured (`None`, so the public P2
  handler returns 503) and the handler passes the requester context to the writer
  port. No production adapter currently creates a server-side service context or
  preserves the requesting user in the audit. P5 must implement that boundary;
  the synthetic `X-Actor-ID` role map is not an authenticated service identity and
  must not be used to forge one.
- **Regression results:** Backend P2 suite: 181 passed; P2 router/API boundary
  suite (including the 12 prior failures): 24 passed; P5 backend suite: 79
  passed; D-013 identity/version guards: 16 passed; combined P2/P5 suites: 260
  passed. P2/P5 runtime imports, canonical P2 model identity, and temporary
  combined-router uniqueness probe passed. Frontend `npm test`: 108 passed, 5
  skipped (one live-API suite is gated); `npm run typecheck` passed; `npm run
  build` passed. No migrations, reset/seed scripts, live database, or live API
  were run.
- **Exact commands:**

  From `backend/`:

  ```text
  python -B -m pytest -o 'addopts=' app/feasibility/tests -q -p no:cacheprovider
  python -B -m pytest -o 'addopts=' app/feasibility/tests/test_router.py -q -p no:cacheprovider
  python -B -m pytest -o 'addopts=' tests -q -p no:cacheprovider
  python -B -m pytest -o 'addopts=' tests/test_assess_identity_guards.py -q -p no:cacheprovider
  python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider
  ```

  Runtime import/model/route probe, from `backend/`:

  ```text
  python -B -c "import sys; from pydantic import BaseModel; from app.core import schemas; from app.feasibility import models, materials, bom, inventory, fixtures; from app.feasibility.tests import test_bom, test_inventory, test_snapshots; from app.feasibility.router import router as p2_router; from app.main import app; assert bom.OperationalSnapshot is inventory.OperationalSnapshot is fixtures.OperationalSnapshot is test_bom.OperationalSnapshot is test_inventory.OperationalSnapshot is test_snapshots.OperationalSnapshot; assert materials.FrozenModel is models.FrozenModel; assert bom.MaterialRequirement is materials.MaterialRequirement; assert inventory.MaterialATP is materials.MaterialATP; assert models.FrozenModel.__bases__[0] is schemas.ContractModel.__bases__[0] is BaseModel; assert not any(name == 'backend' or name.startswith('backend.app') for name in sys.modules); from fastapi import FastAPI; from app.core.router import router as core_router; probe = FastAPI(); probe.include_router(core_router); probe.include_router(p2_router); keys = [(method, route.path) for route in probe.routes for method in (getattr(route, 'methods', None) or set()) if method not in {'HEAD', 'OPTIONS'}]; assert len(keys) == len(set(keys)), [key for key in set(keys) if keys.count(key) > 1]; print('P2/P5 runtime imports and canonical model identity OK; mounted Core + P2 route set unique')"
  ```

  From `frontend/`:

  ```text
  npm.cmd install --no-save --package-lock=false --ignore-scripts @tanstack/react-query@5.104.5
  npm.cmd test
  npm.cmd run typecheck
  npm.cmd run build
  ```
- **Environment and warnings:** Python 3.14.3, pytest 9.1.1 (outside
  `backend/pyproject.toml`'s declared `pytest>=8.3,<9`), FastAPI 0.139.2,
  Pydantic 2.13.4, SQLAlchemy 2.0.51. Each pytest run emitted the same
  Starlette warning that `httpx` with `TestClient` is deprecated. Node 24.14.0,
  npm 11.9.0, Vitest 5.0.5, Vite 7.3.7. The first frontend run found the
  lockfile-declared `@tanstack/react-query@5.104.5` missing from the local
  `node_modules`; it was installed without saving or changing either manifest.
  One overlapping Vitest run had a single P2 receipt-message assertion failure;
  the focused test and a subsequent isolated full run passed. No implementation
  change was needed.
- **Integration readiness and remaining work:** P2 public route, authenticated
  user-to-service authorization, authoritative snapshot provider, assessment
  writer/history, impact reader, supplier-delay/outbox processor, and stable P2
  frontend source are available only as interfaces or feature-local components;
  they are not configured or mounted. P2 pages remain placeholders in `App.tsx`.
  P3 can import the existing pure evaluator, but its serialized handoff remains
  owner-confirmation work. P5's D-013 and simulated handshake tests call Core
  directly with supplied assessments; they do not run P2 `evaluate()`, prove
  persistent P2 assessments, or establish full end-to-end readiness. Orbyte is
  optional and was not a dependency. Before Phase 7, P5 should define a trusted
  user-to-service writer boundary, mount P2's routes, provide authoritative
  snapshot and persistence/history/impact/supplier-event adapters, and wire the
  P2 frontend source; P3 should confirm its evaluator handoff. Then run the
  authenticated API, database and P2/P5 end-to-end path. These are next steps,
  not work performed in this sync.
- **Gate:** The Main sync is locally committed and regression-validated. This
  report and progress trace are recorded in a follow-up P2 commit. The branch is
  ready for independent P2 PR review of the sync checkpoint, with production
  integration still partial; no P2 PR was created, no P2
  production integration was claimed, and Phase 7 was not started.

## Previous attempt — Main PR #2 (superseded by the PR #3 sync above)

This historical attempt documented the duplicate route before D-013. Its test
failures and uncommitted Git state were resolved by the PR #3 sync above.

- P2 pre-sync HEAD: `4e04a662eda8c2b96505e27db976727b2f9d336f`; Main then was
  `0485d3d3490d9dacb97aedb634e99c6538327bbf`, including P5 PR #2 tip
  `6e09a5584000ed1b93d1f568d56e9675016b2e25`.
- The sole conflict was `docs/TEAM_LOG.md`, resolved by preserving P2 and P5
  history. The shared empty-Impact-Set fix and P2-owned correction were already
  validated. P2 then had 169 passed and 12 failures caused by the duplicate
  Core/P2 public assess route; no sync commit or push had yet been made.

## Historical report — previous synchronization of Main `4ec2ba1`

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
