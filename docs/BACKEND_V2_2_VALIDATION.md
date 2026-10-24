> PR #49 supplier-comparison evidence is recorded in the final section. The separate PostgreSQL checkpoint below belongs to PR #55 and does not validate PR #49.

# v2.2 backend validation evidence — 24 October 2026 MYT

Historical original PR #49 checkpoint: code snapshot `7e14477`; fetched main `ec3ffbc970ab38abca8468abfe0466ff0464b998`; integrated upstream `3efa7f23fc2842664f1164cc1dce363f7371bdd3` was merged **into the feature**, never into main. Current PR #49 evidence follows in the final section.

| Run | Observed result | Scope / limits |
|---|---|---|
| New v2.2 tests, Windows Python 3.14 | **134 passed**, 5 existing warnings | 45 terms/port, 54 reply/clarification, 13 API, 22 supplier cases; no new live/provider activation |
| Linux Python 3.12 cumulative portable regression | **1254 passed, 146 skipped**, 79 warnings, 106.16s | All `tests`, P2 and P4; PostgreSQL-only/optional fixture gates skipped in portable mode; no deselection |
| Linux Python 3.12 strict PostgreSQL 16 | **565 passed, zero skipped**, 40 warnings, 45.84s | Entire `tests`, real migrations/transactions/HTTP/worker/approval/race regressions; JUnit independently checked zero failures/errors/skips |
| PR #48 exact head `741976d3cdd59352d66a30c5712ce9eca5d3bc16` | **5/5 CI jobs success** | [Run 39981862097](https://github.com/jiahui-1101/MouManTAI/actions/runs/39981862097): backend, authoritative PG with zero-skips step, feature suites, frontend typecheck/Vitest/build, hygiene |
| Isolated legacy P1, Windows | **616 passed, 7 skipped, 1 failed** | `test_batch8_acceptance.py::test_e2e_11_pdf_image_evidence_traceable_payment_unverified`; direct diagnostic: `OCR engine execution failed: No module named 'paddleocr'` |
| Scoped Ruff, compileall, source hashes, single Alembic head | **PASSED** | Existing head `0017_p1_real_channel_provenance`; six canonical source documents match attachment SHA256 exactly |

No tests or assertions removed, relaxed, retried-until-green, or hidden. No frontend code changed; local frontend commands NOT_RUN, remote #48 frontend job verified separately. Test durations above are execution measurements, **not SME savings or model-accuracy claims**.

## Exact final commands / environment

Run from `backend`:

```powershell
python -m pytest tests/v2_2 -o addopts= -q --tb=short
python -m ruff check app/orders app/integrations app/conversations app/suppliers tests/v2_2 --select F,E4,E7,E9
python -m compileall -q app/orders app/integrations app/conversations app/suppliers
python -m alembic heads
```

Linux image `moumantai-v22-tests:20261023` was built from tracked `git archive 7e14477`, **not** the live working directory or ignored `.env`. It uses official `python:3.12-slim` (digest `sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704`), installs `./backend[dev]` and Ruff, and sets `GMAIL_AUTO_START=false`, `TELEGRAM_AUTO_START=false`, `P1_AI_ENABLED=false`. No model download or real channel send is part of these runs.

Portable container: network `none`, tmpfs `/tmp`, `DATABASE_URL=sqlite+pysqlite:///:memory:`, report directory mounted at `/reports`:

```bash
python -m pytest tests app/feasibility/tests app/communication/tests -o addopts= -q --tb=short --junitxml=/reports/linux-portable-ram.xml
```

Strict container: network shared with **new task-owned** PostgreSQL16 container `moumantai-v22-pg-memory`, tmpfs test scratch and PostgreSQL data, default fsync settings unchanged. Fresh databases for final run; no P1 test suite ran concurrently in them. Environment:

```text
REQUIRE_POSTGRES=1
TEST_DATABASE_APPROVED=1
MOUMANTAI_SYNTHETIC_MODE=1
TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/p4_test_v22_linux_clean
P4_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/p4_test_v22_linux_clean
P1_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/p4_test_v22_linux_clean
TEST_MIGRATION_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/moumantai_v22_migration_clean
```

```bash
python -m pytest tests -o addopts= -q --tb=short --junitxml=/reports/linux-strict-pg-clean.xml
```

Physical disk crash durability is NOT tested; transactions and restart/read-back use real PostgreSQL, not a fake repository. No new migration was authored. The existing migrated-schema and negative-control tests remain intact.

Artifacts: `D:/dunno/0.SDC/backend-v2-2-validation-20261023/` contains source archive, Dockerfile, final logs/JUnit and earlier failed/interrupted reports. Containers are disposable test resources; recreate fresh databases to rerun migration tests. Do not point these commands at shared/dev/prod data.

## Earlier outcomes retained for diagnosis

- Initial Windows broad run: 857 passed / 11 skipped / 475 setup errors from system temporary-directory `WinError 5`; task-owned basetemp resolved that permission issue.
- Concurrent root strict/P1 tests accidentally shared a disposable DB. Root fixture truncates every application schema, causing missing P1 rows/schema and deadlocks. Split DBs; no application code changed to hide this harness error.
- Windows standalone/combined file-backed suites and first Linux overlay runs were interrupted for excessive disk-sync latency. They are **not** passing evidence. Final full tmpfs runs changed storage only, not tests or skip policy.
- First Linux strict run: 556 passed / 8 skipped / 1 failure because the safety guard requires database name `p4_test_*`, and P4 URL was absent. Corrected harness to CI-compatible disposable URLs.
- Next strict run: 564 passed / 1 migration failure because the reused migration database retained `p1_dev` while the legacy test resets only `public`. Fresh migration DB yielded final **565 passed, zero skipped**. No schema reset of unknown data or acceptance-criteria change.
- Legacy P1 OCR failure remains visible; installing/verifying the owner's optional PaddleOCR runtime is separate work. No fabricated OCR or payment verification.

## Coverage versus activation

Validated: exact terms consistency and tenant/version guards; immutable DTOs and receipt bindings; public-field filtering before generation; template fallback; independent issue progress/age/reminder decisions; isolated API/DB status projection; hard supplier specifications and explicit unknowns.

Not implemented/activated: durable v2.2 OrderRequest/issue adapter, order acceptance/reservation saga, live Orbyte/Replit/channel integration, joint CP-SAT portfolio verifier, supplier persistence/selection, new emergency action handlers, milestone consent/feedback policies, forecasting/memory/RFQ. S1–S5 remain unratified. Full customer→accepted/reserved order v2.2 journey is **not complete**. Legacy Core/P2/P3/P4 authority and regression paths remain preserved.
## Backend A mapper checkpoint — 2026-10-24 MYT

This section records validation on the separate Backend A branch, not PR #48/#49 and not the historical supplier snapshot above.

- Repository: jiahui-1101/MouManTAI
- Branch: backend-a/feat-v2-2-p1-order-context-mapper
- Base: exact PR #48 head 741976d3cdd59352d66a30c5712ce9eca5d3bc16
- Main at fetch: 3efa7f23fc2842664f1164cc1dce363f7371bdd3
- Validated code commit: `c492ac6` (`fix(backend-a): bind candidate evidence to validated sources`); the code did not change after the final local run. The handoff/docs checkpoint committed as `9681f9ad51ef8e6e0b3d250e51d17e7aa77a52be` when PR #50 was opened.
- PR #50: [open Draft](https://github.com/jiahui-1101/MouManTAI/pull/50), base `codex/feat-v2-2-backend` (PR #48), opened at head `9681f9ad51ef8e6e0b3d250e51d17e7aa77a52be`; P1 `mavisbong41` and P5 `Gan0117` requested. No automatic PR check is reported for this stacked branch; the workflow filter only targets PRs based on `main`.
- PR #48: open Draft, base `main`, head `741976d3cdd59352d66a30c5712ce9eca5d3bc16`; PR #49: open Draft, base PR #48 branch, head `62040da02b4ec3532ea02d734567e0913996ec2b`. Neither was modified or merged.
- Requirements: BE-MSG-01, SYS-MSG-04, BE-ORD-01; BE-ORD-ACC-01 is only an input boundary here and its acceptance workflow remains out of scope.

| Status | Evidence |
|---|---|
| Implemented | Pure P1 context → existing canonical OrderTerms mapper and typed AcceptanceCandidate in backend/app/orders/context_mapping.py; deterministic positive/negative tests in backend/tests/v2_2/test_context_mapping.py. No route, ORM, migration, Core mutation, send, reservation, acceptance or Backend B evaluator was added. |
| Tested locally | From backend: python -m pytest tests/v2_2 -o addopts= -q --tb=short → 153 passed, 5 warnings. |
| Tested locally | From backend: python -m pytest app/context/tests/test_order_context_storage.py app/context/tests/test_association_models_and_storage.py app/context/tests/test_context_api.py app/context/tests/test_review_readiness.py app/context/tests/test_core_publisher.py app/context/tests/test_p2_consumer.py tests/test_core_api.py tests/test_core_assessment_writer_provenance.py -o addopts= -q --tb=short → 21 passed, 22 skipped, 5 warnings. The 22 PostgreSQL-gated cases were skipped because PostgreSQL URL/approval variables were deliberately unset; they are NOT_RUN on this branch. |
| Static checks | From backend: python -m ruff check app/orders/context_mapping.py tests/v2_2/test_context_mapping.py → All checks passed; python -m ruff format --check app/orders/context_mapping.py tests/v2_2/test_context_mapping.py → both formatted; python -m compileall -q app/orders/context_mapping.py → exit 0. Root git diff --check → exit 0. |
| Integrated | No: local function and tests only; P1 storage/route, durable OrderRequest, Backend B decision, P4 assent, Core state, and external provider flow are not wired. |
| Production-gated | Yes: no trusted live identity, approved price source adapter, customer assent, feasibility/reservation authority, or real channel/provider was exercised. |
| PostgreSQL | NOT_RUN for the current branch. No shared or development database was used. PostgreSQL-only selected P1/Core tests skipped as described above. |
| Frontend / live provider | NOT_RUN: this slice changed no frontend; no external provider or production operation was invoked. |

The test commands ran from the isolated worktree backend directory with REQUIRE_POSTGRES=0 and P1/test database variables removed from the child process. Synthetic test fixtures only. Historical #48 CI (5/5 jobs at #48 SHA) and PR #49 validation (source snapshot 7e14477) remain historical branch evidence and do not validate this new head.

The review follow-up added structured price-disclosure evidence bound to tenant, customer, context/version, request, terms revision/hash, price source/version and disclosure time, plus the authority reference. It also preserves each verified P1 association ID and version in the candidate. Subsequent reviews found commercial-data echo on failed candidates, acceptance of naïve review timestamps, commercial evidence references on canonical-terms validation failure, and an unverified existing order ID on an association error; all now have regression coverage. Failed candidates suppress request/order IDs, commercial source/disclosure identifiers and terms revision; canonical validation failures include only trusted P1 base references; and naïve or mixed-naïve current review timestamps return `REVIEW_REQUIRED` before sorting. The pure mapper still cannot authenticate an internal adapter's claims; tenant-scoped trusted retrieval and currentness rereads remain required.

Current gaps: no adapter authenticates the origin/freshness of an OrderCommercialEvidence object; no durable OrderRequest; no customer-offer or exact assent evidence; no API/event handoff; Backend B has not yet reviewed the proposed interface. The mapper sets agreement basis to UNKNOWN and never infers assent from a hash.

## Backend A additional PR #48 review hardening — 2026-10-24

- Repository: `jiahui-1101/MouManTAI`; branch `backend-a/feat-v2-2-p1-order-context-mapper`; code commit `6ae6424` based on PR #48 head `741976d3cdd59352d66a30c5712ce9eca5d3bc16`. Fetched `origin/main` is `3efa7f23fc2842664f1164cc1dce363f7371bdd3`; PR #49 head remains `62040da02b4ec3532ea02d734567e0913996ec2b`. PR #48/#49/#50 are open Drafts and unmerged; #50 targets the #48 branch.
- Review findings: evidence currentness remains separate from hash equality; `require_exact_terms()` now requires proposed revision equality with the authoritative original for the unchanged-original path; named business timezone offsets are validated without changing canonical hash v1.
- From `backend`: `python -m pytest tests/v2_2 -o addopts= -q --tb=short` → **174 passed, 5 warnings**.
- From `backend`: selected P1/Core regression command above → **21 passed, 22 PostgreSQL-gated skipped, 5 warnings**. The skips are NOT_RUN for PostgreSQL; no approved disposable URL was configured.
- From `backend`: full portable `python -m pytest tests -q -rs -o addopts= --basetemp="C:\Users\User\.codex\worktrees\backend-a-order-mapper\pytest-tmp-full-suite"` → **566 passed, 31 skipped, 12 warnings**. An initial run without an explicit basetemp hit 10 Windows `PermissionError [WinError 5]` setup errors while scanning `pytest-of-User`; rerunning with the task-local basetemp passed. PostgreSQL URL/approval variables were unset; no shared/dev database was used.
- Static checks: `python -m ruff check --select E,F,I --ignore E501 app/orders/terms.py app/orders/context_mapping.py tests/v2_2/test_terms.py tests/v2_2/test_context_mapping.py` → all checks passed; `python -m ruff format --check app/orders/context_mapping.py tests/v2_2/test_context_mapping.py` → both files already formatted; `python -m compileall -q app/orders/terms.py app/orders/context_mapping.py` → exit 0; `git diff --check` → exit 0. Default Ruff and full-file formatter checks also report existing legacy style in `terms.py` and `test_terms.py`; those unrelated expressions/assertions were preserved.
- Compatibility: no hash inputs/version changed, so existing correct `order-terms-v1` hashes remain stable. Incorrect local offsets and DST gaps are rejected. During a repeated local hour, a matching explicit offset selects its unique fold; missing/mismatched offsets fail closed. Equivalent explicit UTC instants remain valid. No timestamp correction or migration was performed.
- Not implemented/integrated: no trusted live adapter, approved freshness TTL, durable OrderRequest, customer assent, API/event, migration, acceptance, reservation, Core mutation, external send, or Backend B decision logic. Backend B must re-read authority before acting. S1–S5 remain unratified; P1/P5/Backend B foundation review is pending.

### Fresh Backend A review-follow-up validation — 2026-10-24

- Validated code HEAD: `bce0f49727e51e8ad66a2f1b2f52b86924bdbd31` on `backend-a/feat-v2-2-p1-order-context-mapper`; based on PR #48 head `741976d3cdd59352d66a30c5712ce9eca5d3bc16`. PR #50 is the existing Draft stacked on #48. Latest fetched Main was `3efa7f23fc2842664f1164cc1dce363f7371bdd3`.
- From `backend`, `python -m pytest tests/v2_2 -o addopts= -q --tb=short` → **176 passed, 5 warnings**.
- From `backend`, the selected P1/Core regression command above → **21 passed, 22 PostgreSQL-gated skips, 5 warnings**.
- From `backend`, `REQUIRE_POSTGRES=0` with database environment variables unset: `python -m pytest tests -q -rs -o addopts= --basetemp="C:\Users\User\.codex\worktrees\backend-a-order-mapper\pytest-tmp-final"` → **568 passed, 31 skipped, 12 warnings**. The 31 skips are PostgreSQL-gated scenarios; no shared/development database was used.
- Static checks: scoped `ruff check --select E,F,I --ignore E501` on the four changed Python files passed; `ruff format --check` on mapper and mapper tests passed; `compileall` on terms and mapper passed; root `git diff --check` passed. Full default Ruff and whole-file formatting still identify pre-existing legacy style in `terms.py`/`test_terms.py`; no unrelated style rewrite was made.
- Review correction: for repeated New York wall time `2026-11-01 01:30`, explicit `-04:00` and `-05:00` each resolve to their distinct valid instant; equivalent UTC values have identical canonical values/hash. Missing or invalid offsets and nonexistent local times fail closed. A known fixed v1 hash vector now guards serialization compatibility. PostgreSQL integration remains **NOT_RUN**; no approved disposable PostgreSQL URL was configured.

## Backend A6 trusted P1 source reader — 2026-10-24

- Code commit: `5a423da6033b99e0e56ce3bb9867630a1e05c939`, branch `backend-a/feat-v2-2-p1-trusted-source-reader`, based on fetched PR #50 head `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`. Fetched Main was `67627cb782a02c7e47bd0812d861f55ff8bb5982`. PR #48/#49/#50/#52/#53 refs and compatibility note are in `BACKEND_V2_2_HANDOFF.md`. This is a local code checkpoint; not pushed and no PR opened.
- Focused adapter tests: `python -m pytest tests/v2_2/test_p1_source_reader.py -o addopts= -q --tb=short` → **18 passed, 5 warnings**.
- Existing v2.2 regressions: `python -m pytest tests/v2_2 -o addopts= -q --tb=short --basetemp=../pytest-tmp-a6-v22-final` → **194 passed, 5 warnings**.
- Selected P1/Core regressions: `python -m pytest app/context/tests/test_order_context_storage.py app/context/tests/test_association_models_and_storage.py app/context/tests/test_context_api.py app/context/tests/test_review_readiness.py app/context/tests/test_core_publisher.py app/context/tests/test_p2_consumer.py tests/test_core_api.py tests/test_core_assessment_writer_provenance.py -o addopts= -q --tb=short --basetemp=../pytest-tmp-a6-p1core-final` → **21 passed, 22 PostgreSQL-gated skipped, 5 warnings**.
- P1 source snapshot/repository checks: `python -m pytest app/context/tests/test_order_context_source_snapshot.py app/context/tests/test_postgres_repository.py -o addopts= -q --tb=short --basetemp=../pytest-tmp-a6-postgres-final` → **6 passed, 13 skipped**. The P1 database-backed snapshot test was skipped because `P1_TEST_DATABASE_URL` was unset. No PostgreSQL connection, shared/development database, or destructive fixture was used.
- Static checks: scoped `ruff check --select E,F,I --ignore E501,F401,F841` on the six changed Python files passed; `ruff format --check` on the new reader and test files passed; `python -m compileall -q` on the reader/repository/test files passed; `git diff --check` passed. `F401`/`F841` are excluded because the existing large P1 repository files already contain unrelated legacy lint findings; no cleanup outside A6 was made.
- **Implemented / locally tested**: read-only P1 records loaded in one tenant-filtered PostgreSQL repeatable-read/read-only transaction; typed `AcceptanceCandidate` prepared through the existing mapper; missing/unverified/stale/conflicting/unproven inputs fail closed. **Not integrated/reviewed/production-gated**: no authenticated tenant provider is wired; no route or commercial/disclosure/assent reader exists; no request, acceptance, reservation, Core transition, P2 extension, message send, migration or order persistence is present. P1/P5 and eventual Backend B review remain required. See `docs/BACKEND_A_P1_SOURCE_READER.md` for the data boundary and blockers.

### Backend A6 final review and validation — 2026-10-24

- Fresh remote check: `origin/main` `67627cb782a02c7e47bd0812d861f55ff8bb5982`; PR #48 `741976d3cdd59352d66a30c5712ce9eca5d3bc16`; #49 `62040da02b4ec3532ea02d734567e0913996ec2b`; #50 `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`; #52 `8d7ca20c0651db947092dec34510fe1b0b63aaaa`; #53 `3680e82266e8b2a982df2928e75b42160a58ce2d`. A6 test commit `acefd0fa8c4f01d55943f1324aee6ef9c7a692c2` is based on current PR #50; the following publication documentation is a separate logical commit.
- Independent A6 review found no critical A6-owned implementation defect. Added three explicit fail-closed regression cases for OCR, PDF text, and attachment-only references. No mapper, repository behavior, shared schema, or lifecycle semantics were changed during this finalization.
- Fresh focused A6 tests: **21 passed / 5 FastAPI/Starlette deprecation warnings**. Fresh v2.2 regressions: **197 passed / 5 warnings**.
- Selected P1/Core compatibility suite: **21 passed / 22 skipped / 5 warnings**. All 22 skips explicitly state `P1_TEST_DATABASE_URL is unset; PostgreSQL validation NOT RUN`.
- P1 snapshot/repository suite: **6 passed / 13 skipped**. All 13 skips explicitly state `P1_TEST_DATABASE_URL is unset; PostgreSQL validation NOT RUN`.
- Scoped Ruff check and formatting check passed; scoped compileall exited 0; `git diff --check` passed. Ruff excludes `E501`, `F401`, and `F841` on existing large P1 files to avoid unrelated legacy findings.
- PostgreSQL validation is **NOT_RUN / BLOCKED**. `P1_TEST_DATABASE_URL`, `P1_DATABASE_URL`, `TEST_DATABASE_URL`, `DATABASE_URL`, and `TEST_MIGRATION_DATABASE_URL` were unset. The 35 gated tests were skipped, not passed. No database was created or touched. Live PostgreSQL repeatable-read/read-only transaction assertions remain unverified.
- The current A6 handoff, implementation status, dependency, and owner gates are maintained in [`docs/BACKEND_A6_LATEST_HANDOFF.md`](BACKEND_A6_LATEST_HANDOFF.md). It supersedes the earlier local-only A6 publication status above while preserving that checkpoint as history.
- Published as Draft PR [#55](https://github.com/jiahui-1101/MouManTAI/pull/55), base `backend-a/feat-v2-2-p1-order-context-mapper` at `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`; requested P1 `mavisbong41` and P5 `Gan0117`. The PR compare is 4 commits ahead / 0 behind and lists 11 A6-only files. No PR-triggered workflow runs were returned. This metadata update contains documentation only; tested Python code remains at `acefd0fa8c4f01d55943f1324aee6ef9c7a692c2`.
## 2026-10-24 — Prompt 2: PR #50/#52 consolidation validation

Dependency evidence, read before editing:
- PR #48 HEAD `568e5deff97a29244944ae31b5d138fa910a4042`; exact-head GitHub CI `40054989068` completed SUCCESS with all five jobs, including the authoritative PostgreSQL job with zero skips.
- PR #50 starting HEAD `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`; PR #52 `8d7ca20c0651db947092dec34510fe1b0b63aaaa`; PR #55 `2a97cf553b8d686d277d322b40db15fdabcc3ae8`, based on the exact #50 starting head.
- PR #48's two reservation/version findings are corrected in the pushed source and tests; reviewer re-approval remains pending. The technical dependency is present, not approved/merged.

Implementation in the isolated PR #50 worktree:
- Merged corrected #48 into #50 with merge commit `c49889e07a8c20679e51fad4d9553a901680490e` (no rebase/history rewrite).
- Consolidation code commit `c7a05149b6d51513e9bf2d8acf35b4989b5be260`. Changed implementation/test files: `backend/app/orders/terms.py`, `backend/tests/v2_2/test_terms.py`. PR #48 additionally contributes its corrected `backend/app/integrations/business_ports.py` and `backend/tests/v2_2/test_business_ports.py` unchanged through the merge. `context_mapping.py` and `test_context_mapping.py` remain unchanged from #50.
- All nine distinct #52-added term regression functions were retained alongside #50's tests: evidence-reference/currentness boundary; proposed revision mismatch; Kuala Lumpur wrong offset; both explicit DST folds and equivalent UTC instants; repeated local hour requires explicit offset; spring transition; UTC-instant order through a DST fold; wrong repeated-hour offset; nonexistent local time. Shared fixed hash vector remains present. Terms hash semantics are unchanged.

Commands (run from `backend`, each pytest run used a fresh GUID-based `--basetemp` below `C:\Users\User\.codex\worktrees\backend-a-order-mapper` and `MOUMANTAI_SYNTHETIC_MODE=1`):
- `python -m pytest tests/v2_2/test_terms.py -o addopts= --basetemp=$temp -q --tb=short` → **56 passed, 5 warnings**.
- `python -m pytest tests/v2_2/test_context_mapping.py -o addopts= --basetemp=$temp -q --tb=short` → **52 passed, 5 warnings**.
- `python -m pytest tests/v2_2/test_business_ports.py -o addopts= --basetemp=$temp -q --tb=short` → **68 passed, 5 warnings**.
- `python -m pytest tests/v2_2 -o addopts= --basetemp=$temp -q --tb=short` → **243 passed, 5 warnings**.
- `python -m pytest app/context/tests/test_order_context_storage.py app/context/tests/test_association_models_and_storage.py app/context/tests/test_context_api.py app/context/tests/test_review_readiness.py app/context/tests/test_core_publisher.py app/context/tests/test_p2_consumer.py tests/test_core_api.py tests/test_core_assessment_writer_provenance.py -o addopts= --basetemp=$temp -q -rs --tb=short` → **21 passed, 22 skipped, 5 warnings**. Every skip reports `P1_TEST_DATABASE_URL is unset; PostgreSQL validation NOT RUN`.
- `python -m pytest app/feasibility/tests -o addopts= --basetemp=$temp -q -rs --tb=short` → **288 passed, 1 warning**.
- `python -m pytest tests/test_resource_reservations.py tests/test_outbox_events.py tests/test_p5_integration_recovery.py tests/test_core_api.py tests/test_core_assessment_writer_provenance.py -o addopts= --basetemp=$temp -q -rs --tb=short` → **48 passed, 5 warnings**.
- Ruff `check --select E,F,I --ignore E501,F401,F841` on terms, mapper, ports and relevant tests → pass. `ruff format --check` on mapper/ports and their tests → pass. Full terms/test_terms formatting check → pre-existing fail; the same check on their unchanged pre-consolidation #50 HEAD also exited 1. `python -m compileall -q app tests/v2_2` → pass. `python -m alembic heads` → one head, `0017_p1_real_channel_provenance`. `git diff --check` → pass. Secret scan on changed source/test files → no matches.
- No local PostgreSQL database was started or used. There is no approved disposable P1 database URL; all gated P1 tests are reported NOT_RUN/skipped, not passed. PR #48 PostgreSQL CI does not validate PR #55's separate database tests.

PR #50's own exact-head CI will be checked after the normal push. No CI result is inferred from #48. PRs remain Draft; no merge, auto-merge or production operation.

Independent read-only review of the consolidated implementation found no actionable code issues. It confirmed the corrected #48 contract is an ancestor, all 17 #52 test function definitions remain (nine transferred because absent from original #50), PR #50 mapper files are unchanged, and hash semantics remain stable. Latest fetched Main is `b1255f5a428e8cd87a0ecb48576bc373b6286c50` (#58); it is separate UI/design/spec changes and was not pulled into this stacked PR. This review does not constitute owner signoff.

Publication follow-up: final code/docs checkpoint `ba2d5ad9956ad0cba82e417f7a14b336cfb56025` was pushed normally and verified at the existing PR #50 branch. PR #50 remains open Draft and unmerged, based on corrected #48 HEAD `568e5deff97a29244944ae31b5d138fa910a4042`. Exact-head GitHub workflow lookup found no PR-triggered run. Fresh P1/P5/Backend B review requests were sent; no new review submission was available at this checkpoint. PR #55 remains based at its old #50 SHA `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`; refresh it only through a reviewed update. Its PostgreSQL-gated P1 tests remain NOT_RUN without an approved disposable database.

Request-version regression checkpoint (PR #50 follow-up, 2026-10-24; local worktree based on `ed2ed58baf74784fa94625013106363f68a739be`):

- `python -m pytest -p no:cacheprovider -o 'addopts=' tests/v2_2/test_context_mapping.py --tb=short` → **77 passed, 5 warnings**.
- `python -m pytest -p no:cacheprovider -o 'addopts=' tests/v2_2/test_terms.py tests/v2_2/test_business_ports.py --tb=short` → **124 passed, 5 warnings**.
- Full v2.2 suite → **268 passed, 5 warnings**.
- Adjacent P1/Core contract suite → **21 passed, 22 skipped** because `P1_TEST_DATABASE_URL` was unset. **BLOCKED — REAL POSTGRESQL VALIDATION NOT PERFORMED.**
- Ruff check and format, Python compileall, and `git diff --check` passed. These are local results; GitHub exact-head CI has not run for the follow-up yet.

## PR #55 refresh validation — 2026-10-24

- Focused P1 source reader: **22 passed, 5 warnings**.
- Full v2.2 suite after merging #50 `f676da95c6d0e453327df4edfb1593c0c0d17144`: **290 passed, 5 warnings**.
- `python -m pytest -p no:cacheprovider -o 'addopts=' backend/app/context/tests/test_order_context_source_snapshot.py backend/app/context/tests/test_postgres_repository.py -q -rA --tb=short` → **6 passed, 13 skipped**. Every skip says `P1_TEST_DATABASE_URL is unset; PostgreSQL validation NOT RUN`.
- `python -m alembic -c backend/alembic.ini heads` → one head, `0017_p1_real_channel_provenance`. This verifies migration graph metadata only; it is not a PostgreSQL migration run.
- **BLOCKED — REAL POSTGRESQL VALIDATION NOT PERFORMED.** A disposable local PostgreSQL DB and `P1_TEST_DATABASE_URL` are required. Reproduce from `backend` with `python -m pytest -p no:cacheprovider -o 'addopts=' app/context/tests/test_p1_alembic_migration.py app/context/tests/test_order_context_source_snapshot.py app/context/tests/test_postgres_repository.py -q -rA --tb=short` after setting that URL to the disposable DB.

Latest #55 parent refresh to #50 `9dba996db2c066f7ea5997dbc8dbf7b5dd277540` (2026-10-24): reader **22 passed**; full v2.2 **290 passed / 5 warnings**; P1 migration/source-snapshot/PostgreSQL repository suite **6 passed / 14 skipped**. Every skip is due to unset `P1_TEST_DATABASE_URL`; no real PostgreSQL run occurred. `git diff --check` and focused Ruff check/format on the P1 reader test passed. Exact-head Actions will be checked after publication.
PR #50 post-retarget validation against fetched `main` `eaa5097452f17f5c4f1c9ccc6c0a5b9f5678c86a` (2026-10-24): full v2.2 **268 passed / 5 warnings**; selected adjacent P1/Core suite **21 passed / 22 skipped**, all explicitly skipped because `P1_TEST_DATABASE_URL` is unset. These runs are local and do not substitute for exact-head Actions. The P1 database-backed cases remain NOT_RUN.

## 2026-10-24 final real PostgreSQL validation (supersedes earlier NOT_RUN checkpoints)

**PostgreSQL gate PASSED; BLOCKED_BY_OWNER_APPROVAL. Keep Draft.** Validated code/test HEAD: `79b46197c1f3735e08b533f79c5cdca6f0d608c9`. PR #50 merged at `4ffb6c2b1999362aa0e27cb3d834af58cc057267`; #55 now targets `main` and includes fetched main `585467d4389e5d8ada6e5e59a78c96306f3a0bc1` through normal merge commits `997c7a3fe63fc62f8787dff044ee1f8d222945e7` and `ab0e4b632dce04fab7cfbd3204511983fb94dbb1`. No published history was rewritten.

Real PostgreSQL 16.15, task-owned disposable Docker container, actual Alembic head `0017_p1_real_channel_provenance`: required gate **22 passed / 0 failed / 0 skipped**, including all 14 previously skipped DB cases plus two new migrated-schema transaction regressions. Server reports READ ONLY and REPEATABLE READ; a deliberate DML probe is rejected with SQLSTATE 25006; a concurrent committed review cannot mix context/version/review states, and a subsequent stale-version read fails closed. Production code and migrations are unchanged.

Full v2.2: **290 passed**. Combined v2.2/Backend B feasibility/Core/reservation/outbox: **642 passed**. Selected P1/Core: **43 passed / 0 skipped**. Full P1: **625 passed / 1 failed / 4 skipped / 0 setup errors**. The one OCR acceptance failure reproduces on unchanged pre-task #55 `f2300c5ef67750403c32dc4ddd191b2e77acf2eb`; optional OCR/PDF dependencies are unavailable. No claim that the whole P1 suite is green. Scoped Ruff, format, compileall and diff checks pass.

Exact test-head CI [40072357617](https://github.com/jiahui-1101/MouManTAI/actions/runs/40072357617) passed all five jobs, including frontend typecheck/Vitest/build. The current CI does not set P1_TEST_DATABASE_URL or run app/context/tests, so it does not replace the separate real PostgreSQL evidence. The final documentation-only publication SHA and its exact-head CI are recorded in the [existing PR #55 description](https://github.com/jiahui-1101/MouManTAI/pull/55), avoiding a self-referential commit SHA.

P1/P5 CHANGES_REQUESTED reviews remain effective until owners re-review. Fresh requests sent to mavisbong41, Gan0117 and jiahui-1101. No unresolved inline review threads were returned; no review was dismissed or discussion resolved by the author. Main's ruleset requires Backend Tests (PostgreSQL Authoritative), prohibits force updates and branch deletion; legacy protection endpoint returned 404.

The durable P1 OrderRequest/version and approved commercial/disclosure sources remain unavailable. The reader still supplies commercial_terms=None, leaves request_version absent, and stays INCOMPLETE. No acceptance, reservation, approval or Core transition is activated. Backend B must independently reread current authoritative evidence. Full commands, provenance and limitations follow in BACKEND_V2_2_VALIDATION.md.

## PR #49 supplier comparison — refreshed against current main (2026-10-24)

This section is specific to PR #49 and supersedes earlier supplier test counts in this file. Local tests were run from `backend/` against source/test snapshot `60b741635f0ad9823573b1aa97643a96ece12ce5`, which includes latest `origin/main` `57636642750d366a85045c3655afa0c51581e3be`. The first posted head `470fae5fba9eeea591c401bb46f01b045f58ee26` adds the documentation-only checkpoint and passed exact-head CI. The subsequent validation-document amendment is also documentation-only; its current exact-head run is linked from [PR #49 checks](https://github.com/jiahui-1101/MouManTAI/pull/49/checks).

### Local validation

| Check | Result | Observed result |
|---|---|---|
| Supplier comparator | **PASS** | `python -m pytest -p no:cacheprovider -o "addopts=" tests/v2_2/test_supplier_comparison.py -q -rA --tb=short` — 22 passed, 5 warnings, 0 failures/skips |
| Full v2.2 | **PASS** | `python -m pytest -p no:cacheprovider -o "addopts=" tests/v2_2 -q -rA --tb=short` — 312 passed, 5 warnings, 0 failures/skips |
| P1 / OrderTerms / P2 / P3 / P5 regressions | **PASS** | Selected source reader, context mapper, terms, assessment provenance/identity, supplier pipeline, Recovery and Core tests — 254 passed, 5 warnings, 0 failures/skips |
| PR #59 sourcing handoff compatibility | **PASS** | 28 passed, 5 warnings in a temporary copy of the refreshed #49 tree with sourcing source/tests taken from #59 head `6dcebe5d7baf46f0136160abe153ee30885331c6`; no #59 branch, commit or file changed |
| Ruff | **PASS** | `python -m ruff check app/suppliers tests/v2_2/test_supplier_comparison.py` — all checks passed |
| Ruff format | **PASS** | `python -m ruff format --check app/suppliers tests/v2_2/test_supplier_comparison.py` — 3 files already formatted |
| Compile | **PASS** | `python -m compileall -q app/suppliers` — exit 0 |
| Diff whitespace | **PASS** | `git diff --check` on the final task diff — exit 0 |
| Local PostgreSQL | **NOT RUN** | Comparator is pure/in-memory; PR #49 adds no migration or database-backed supplier test. No local database URL was used. The exact-head CI PostgreSQL evidence is recorded below; PR #55's historical PostgreSQL results above are separate. |

### Exact-head GitHub Actions — code/test publication head

- GitHub Actions run [40080165292](https://github.com/jiahui-1101/MouManTAI/actions/runs/40080165292), exact commit `470fae5fba9eeea591c401bb46f01b045f58ee26`, completed **5/5 success**: Backend Tests (pytest & syntax), Backend Tests (PostgreSQL Authoritative), Feature Suites (Feasibility & Communication), Frontend Checks (Typecheck, Vitest, Build), and Hygiene & Secret Checks.
- The authoritative job used a GitHub-hosted Ubuntu 24.04.5 runner, Python 3.12.15 and a fresh `postgres:16` service; job logs report PostgreSQL **16.15** (Debian 16.15-1.pgdg13+2). The job created separate `p4_test_moumantai_suite` and `moumantai_migration` databases and set `REQUIRE_POSTGRES=1` and `TEST_DATABASE_APPROVED=1`.
- Alembic head check: `0017_p1_real_channel_provenance (head)`. `backend/tests/conftest.py::pg_suite_engine` applies actual `command.upgrade(..., "head")` to the suite database. The migration test separately executed the real `0006_recovery_cases -> 0007_recovery_case_constraints_alignment -> downgrade 0006 -> upgrade head` sequence on the disposable migration database. Full job command: `pytest backend/tests -v -rs --junitxml=pg-report.xml`; result **743 passed, 0 failed, 0 skipped, 40 warnings**. The workflow also verified zero skipped cases.
- ORM-schema coverage remains distinguishable: ordinary `test_engine` fixtures use the Alembic-migrated PostgreSQL schema under `REQUIRE_POSTGRES=1`; `tests/integration/test_p1_core_p2_e2e.py` and `tests/integration/test_p1_review_drawer_e2e.py` initialize their P1 PostgreSQL schema and create Core tables through `Base.metadata.create_all`. `tests/test_amendment_protection.py`, `tests/test_outbox_events.py` and `tests/test_registry.py` use SQLite with ORM `Base.metadata.create_all`, so they are not PostgreSQL migration evidence. No production/shared database was touched.

### Synchronization and scope

- Original remote #49 head: `63fb44de2e85917562602076d997b50b29ac79a8`; original merge base: `eaa5097452f17f5c4f1c9ccc6c0a5b9f5678c86a`. At latest main before publication, #49's old head was 9 commits ahead and 45 behind.
- First synchronization with `dc4b1a1d928fbba2bc98d1f9e3731a6a879065c3` had documentation conflicts in `BACKEND_V2_2_HANDOFF.md`, `BACKEND_V2_2_VALIDATION.md` and `TEAM_LOG.md`. Latest-main copies were retained; this #49 checkpoint was added without losing Main's history. No supplier or shared contract code conflicted. A subsequent merge of current `main` `57636642750d366a85045c3655afa0c51581e3be` was clean and carried only `backend/tests/test_migration_0007.py`.
- PR scope remains the pure supplier hard-spec comparison and tests, its existing plan entry, and this review/validation handoff. Outcomes remain `MATCHES`, `CONDITIONAL`, `INCOMPATIBLE`, `UNKNOWN`; the comparator remains advisory, fail-closed, and grants no purchasing, reservation, dispatch, Core acceptance or Recovery execution authority. S1–S5 remain unratified.
- Exact publication SHA and all five GitHub Actions job results (Backend Tests, Backend Tests (PostgreSQL Authoritative), Feature Suites, Frontend Checks, Hygiene & Secret Checks) are tracked on the live PR checks page linked above. Branch-protection required-check API was not accessible to this connection (HTTP 403); no protection settings were changed.

### Review and downstream gates

- P1's `COMMENTED` review is not approval. P3 and P5 approvals cite old head `62040da02b4ec3532ea02d734567e0913996ec2b`; fresh P1/P3/P5 review is required on the refreshed publication head. No unresolved inline threads were returned during this audit.
- PR #59 remains stacked at base `62040da02b4ec3532ea02d734567e0913996ec2b`, head `6dcebe5d7baf46f0136160abe153ee30885331c6`. Its old-head five-job CI passed, and its 28 sourcing tests pass against the refreshed #49 comparator in the temporary compatibility snapshot. Its owner still needs to refresh the base to the new #49 head and rerun checks. This result does not make #59 merge-ready.

### Disposable database provenance and migration evidence

Created a new `postgres:16` container named `moumantai-pr55-validation` (container ID prefix `1a696f2c69f2`) for this task. It used a fresh generated credential, user `pr55_test`, database `pr55_validation_test`, loopback-only ephemeral port, and no shared data volume. No application/ordinary DATABASE_URL, team database or production database was selected. URLs were process-scoped and never committed or printed. PostgreSQL version: **16.15 (Debian 16.15-1.pgdg13+2), x86_64**; local Python **3.14.3**.

`DATABASE_URL` was explicitly set only inside the migration process to this independently verified disposable target. `python -m alembic upgrade head` and `python -m alembic current` succeeded at `0017_p1_real_channel_provenance`. Inspector found eight P1 tables: attachments, context_reviews, document_extractions, extraction_attempts, message_associations, order_context_versions, order_contexts, inbound_messages.

The existing migration fixture creates a fresh UUID-named child database, runs the real chain, verifies persistence/review/Core replay, downgrade to 0015 and re-upgrade, then drops only its own child DB. The two new regressions reuse that migration fixture; they do not use metadata.create_all. Existing pg_engine repository tests still use isolated ORM-created UUID schemas: those prove repository behavior, while the separate migration and new snapshot tests prove actual migrated-schema compatibility. ORM setup is not claimed as migration validation.

### Exact commands and observed results

All Python commands below ran from backend. P1_TEST_DATABASE_URL was set process-locally to the disposable PostgreSQL URL for P1/DB commands. Broader portable regressions retained their existing fixture configuration. Counts overlap across commands; do not add them as unique tests.

```powershell
python -m alembic upgrade head
python -m alembic current
python -m pytest -p no:cacheprovider -o 'addopts=' app/context/tests/test_p1_alembic_migration.py app/context/tests/test_order_context_source_snapshot.py app/context/tests/test_postgres_repository.py -q -rA --tb=short
# 22 passed, 0 failed, 0 skipped, 6 existing Alembic warnings
python -m pytest -p no:cacheprovider -o 'addopts=' tests/v2_2 -q --tb=short
# 290 passed, 5 deprecation warnings
python -m pytest -p no:cacheprovider -o 'addopts=' tests/v2_2/test_context_mapping.py tests/v2_2/test_terms.py tests/v2_2/test_p1_source_reader.py -q --tb=short
# 155 passed (mapper 77 + terms 56 + reader 22), 5 warnings
python -m pytest -p no:cacheprovider -o 'addopts=' tests/v2_2 app/feasibility/tests tests/test_core_api.py tests/test_core_assessment_writer_provenance.py tests/test_resource_reservations.py tests/test_outbox_events.py -q -rs --tb=short
# 642 passed, 0 failed, 0 skipped, 5 warnings
python -m pytest -p no:cacheprovider -o 'addopts=' app/context/tests/test_order_context_storage.py app/context/tests/test_association_models_and_storage.py app/context/tests/test_context_api.py app/context/tests/test_review_readiness.py app/context/tests/test_core_publisher.py app/context/tests/test_p2_consumer.py tests/test_core_api.py tests/test_core_assessment_writer_provenance.py -q -rs --tb=short
# 43 passed, 0 failed, 0 skipped, 5 warnings
$testTemp = Join-Path $env:TEMP ('pr55-p1-' + [guid]::NewGuid().ToString('N'))
# Set P1_DATABASE_URL too, only to the verified disposable database.
python -m pytest -p no:cacheprovider -o 'addopts=' app/context/tests --basetemp=$testTemp -q -rs --tb=short
# 625 passed, 1 failed, 4 skipped, 0 setup errors, 7 warnings
python -m ruff check --select E,F,I --ignore E501,F401,F841 app/context/repository.py app/context/postgres_repository.py app/context/tests/test_order_context_source_snapshot.py app/context/tests/test_postgres_repository.py app/orders/p1_source_reader.py tests/v2_2/test_p1_source_reader.py
python -m ruff format --check app/orders/p1_source_reader.py tests/v2_2/test_p1_source_reader.py app/context/tests/test_order_context_source_snapshot.py
python -m compileall -q app/orders app/context/repository.py app/context/postgres_repository.py app/context/tests/test_order_context_source_snapshot.py tests/v2_2
 git diff --check
# All static checks passed; formatting checks cover these three files only.
```

### Previously skipped cases actually exercised

All 14 original DB-gated cases passed: migration clean-chain/persistence/review/Core replay/rollback (1); source snapshot tenant scoping (1); durable original across engine restart (1); duplicate receipt preservation (1); conflicting duplicate variants changes0..changes5 (6); database unique constraint (1); concurrent identical delivery (1); concurrent conflicting delivery (1); tenant-scoped literal search/pagination (1). Six portable cases also passed. Two added migrated-database tests bring the gate to 22: test_migrated_source_transaction_rejects_writes and test_migrated_source_snapshot_survives_concurrent_review.

### Wider P1 baseline limitation

Initial unrestricted-temp P1 run: 582 passed, 1 failed, 7 skipped, 40 setup errors. All 40 errors were WinError 5 on the existing pytest-of-User temp directory. Rerunning with a fresh task-owned --basetemp and P1_DATABASE_URL pointing to the owned test DB eliminated setup errors and three attachment DB skips: **625 passed, 1 failed, 4 skipped**.

Remaining failure: `app/context/tests/test_batch8_acceptance.py::test_e2e_11_pdf_image_evidence_traceable_payment_unverified` expects OCR SUCCESS but returns FAILED. Exact same command against pre-task #55 f2300c5 reproduced **1 failed**; the production extractor and acceptance test are unchanged. Optional paddleocr/pymupdf packages are absent; no heavy models were installed for the read-only database scope. Remaining skips: image OCR module, PDF extraction module, and two explicitly opt-in live inference cases. They are not PostgreSQL gate skips. P1 owns OCR environment/test follow-up. No assertions or tests were weakened/deleted.

Independent static review of the two new transaction tests found no actionable issue; it did not independently rerun tests. Scope remains test/evidence-only, plus normal main merges. Future live source integration still requires authenticated tenant provider, durable request/version, commercial/disclosure authority, P1/P5 design approval and Backend B decision-time reread.
