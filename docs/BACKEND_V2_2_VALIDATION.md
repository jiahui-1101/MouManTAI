# v2.2 backend validation evidence — 24 October 2026 MYT

Code snapshot: `7e14477` (foundation plus supplier contracts). Later commits are documentation only.
Initial fetched main: `ec3ffbc970ab38abca8468abfe0466ff0464b998`.
Integrated upstream: `3efa7f23fc2842664f1164cc1dce363f7371bdd3`, merged **into feature**, never into main.

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
- Current code checkpoint: mapper/test implementation in the dedicated branch; latest local validation includes follow-up review fixes.
- PR #48: open Draft, base main, head 741976d3...; PR #49: open Draft, base PR #48 branch, head 62040da0.... No PR has been created yet for this branch.
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
