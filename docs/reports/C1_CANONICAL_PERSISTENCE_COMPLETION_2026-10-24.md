# C1 Completion — Canonical Persistence and Exact Reply Association

Date: 2026-10-24 (Asia/Kuala_Lumpur)
Repository: `jiahui-1101/MouManTAI`
Branch: `codex/c1-canonical-persistence-completion`
Validated implementation head: `9ebe2b235de7d8d3a15c802e6645c3415f508bb7`
Base refreshed from Main: `f6eca1ac93b382c2ffe68965e18b55f12e03d322` (PR #79).
Alembic head: `0018_c1_scoped_message_parent`.

## Scope and requirement IDs

Implements the explicitly requested C1 completion: canonical P1 message persistence, account-scoped provider identity, exact provider reply association, out-of-order parent reconciliation, authenticated channel ingress wiring, and regression coverage. This is implementation evidence for C1 only; it does not certify a live provider or Orbyte connection.

The implementation preserves the v2.2 evidence distinction: code and test-adapter behavior is `VALIDATED`; test inputs are synthetic or mocked; live provider and Orbyte behavior is `NOT_RUN`.

## Existing implementation reused

The work extends `RawMessageEnvelope`, `p1_dev.inbound_messages`, `PostgresMessageRepository`, `IngestionService`, `ContextService`, the existing Telegram/WhatsApp/Gmail adapters, and existing message/context routes. The legacy P1 tables, extraction, association, review, attachment, and Order Context histories remain the authorities. No second inbox or source-message table was added.

The new [`LEGACY_REUSE_MATRIX.md`](../../LEGACY_REUSE_MATRIX.md) maps the existing entities, routes, compatibility treatment, and migration verification. [`REPOSITORY_BASELINE.md`](../../REPOSITORY_BASELINE.md) records the pre-change tables, route families, test areas, starting commit, and Main refresh.

Process note: the reuse matrix and baseline were completed after the migration source file had been authored, but before any PostgreSQL upgrade/downgrade test ran. This did not meet the repository's required “mapping before schema change” sequence. The migration was applied only to the task-owned disposable PostgreSQL database; the reviewer should assess the documented entity mapping before approving the PR.

## Files and contracts changed

- P1 contracts and persistence: `backend/app/context/schemas.py`, `ingestion.py`, `postgres_repository.py`, `repository.py`, `context_service.py`, and `dev_database.py`.
- Channel framing and authentication: `backend/app/context/channels/reply_framing.py`, `config.py`, `state.py`, `telegram.py`, `whatsapp.py`, `gmail.py`, and `router.py`.
- Additive schema change: `backend/migrations/versions/0018_c1_scoped_message_parent.py`; it changes only `p1_dev.inbound_messages`.
- Regression coverage: new `test_c1_adapter_framing.py` and `test_c1_completion_persistence.py`, plus existing P1 adapter, repository, migration, provenance, and context-association tests.
- Audit documents: `LEGACY_REUSE_MATRIX.md`, `REPOSITORY_BASELINE.md`, this report, and the append-only C1 entry in `docs/TEAM_LOG.md`.

No frontend DTO, Core, P2, Recovery, P4 authorization, or shared A–H business contract changed.

## Backend behavior delivered

The envelope now retains provider account and native message identity, conversation scope, RFC mail identifiers and references, native attachment source IDs, correlation data, relationship source, framing errors, and source-authentication status. Historical rows migrate with unknown account scope and `LEGACY_UNKNOWN`; the migration does not infer missing history.

Idempotency is scoped by tenant, provider, account, and native message ID. Telegram also includes its chat/conversation ID because native message IDs are chat-scoped. Parent resolution requires a unique authenticated source message in the same tenant, provider, account, and provider-specific conversation or RFC identifier namespace. Unresolved and ambiguous references remain explicit. When a parent arrives later, the repository reconciles only parent-link columns; it does not rewrite immutable source evidence or context history.

When a provider asserts an exact parent but it cannot be uniquely resolved, P1 does not fall back to a sender or broad thread match. This relation only supports source association; it does not establish customer assent, acceptance, reservation, or any Core transition.

Telegram webhook ingress now requires the configured secret, while authorized Bot API polling marks its source verified. WhatsApp verifies the HMAC over the original request bytes and checks the configured phone-number account before ingestion. Gmail verifies the OAuth mailbox identity and keeps native Gmail IDs, RFC Message-IDs, and thread IDs separate. The public development ingest route forcibly records `SYNTHETIC` provenance regardless of client claims.

## Integration modes

`SYNTHETIC`: the public development ingest endpoint and synthetic fixtures.

`MOCK` / test adapters: provider-authentication and persistence paths exercised with local test responses and test credentials.

`LIVE`: not established. No real Telegram, WhatsApp, Gmail, or Orbyte account was configured or exercised in this validation.

## Validation commands and observed results

- **C1/PostgreSQL acceptance — PASSED:** `py -m pytest -q -o addopts='' --basetemp .pytest-c1-postgres-final-head app/context/tests/test_c1_completion_persistence.py app/context/tests/test_postgres_repository.py app/context/tests/test_c1_repository_regression.py app/context/tests/test_p1_inbox_acceptance_regressions.py app/context/tests/test_p1_alembic_migration.py --disable-warnings` — 40 passed, 7 warnings on the validated code/test head. It exercised fresh and legacy-row migrations, downgrade/re-upgrade, scoped duplicates, exact parent matches, late reconciliation, and tenant/account boundaries on a task-owned disposable PostgreSQL database.
- **Channel and framing regressions — PASSED:** 92 passed on the validated code/test head in the C1/channel/source-provenance subset.
- **Full v2.2 suite — PASSED:** `py -m pytest -q -o addopts='' --basetemp .pytest-c1-v22-final tests/v2_2` — 493 passed, 5 deprecation warnings.
- **Full P1 context suite — FAILED with two isolated failures:** `py -m pytest -q -o addopts='' --basetemp .pytest-c1-full-context-publish --disable-warnings app/context/tests` — 690 passed, 7 skipped, 2 failed at the validated head. `test_e2e_11_pdf_image_evidence_traceable_payment_unverified` returns `FAILED` because the optional OCR runtime is unavailable; the repository’s C1 foundation report already records this limitation. `test_catalog_is_provisional_fixture_aligned_and_tenant_scoped` fails against latest Main’s catalog/extractor update from PR #79; the same assertion passes with the pre-#79 versions of those two files at the task’s starting commit. Neither failing test is changed by C1.
- **Ruff on all changed Python paths — FAILED on pre-existing lint debt:** 156 diagnostics on this branch versus 159 on the same existing paths at `origin/main`; diagnostic comparison found no new findings. All three new C1 Python files and the modified ingestion guard pass Ruff. Ruff format check reports the same 22 pre-existing unformatted files as Main; all new C1 files and the changed ingestion guard are formatted.
- **Compile and whitespace — PASSED:** `py -m compileall -q backend/app`; `git -c core.whitespace=cr-at-eol diff --check origin/main...HEAD`.
- **Migration graph — PASSED:** `py -m alembic -c alembic.ini heads` reports the single head `0018_c1_scoped_message_parent`.

All PostgreSQL tests used the separately named task-owned disposable container. No shared or production database was migrated.

## Business/security approvals enforced

Provider authentication and source/account scope are checked before real adapter ingestion. The development endpoint remains synthetic. Exact reply linkage never asserts consent or business authority. No emergency CTA, acceptance, supplier selection, commitment, reservation, customer notification, or fulfillment path changed.

## Known limitations and follow-up

Historical messages without recoverable provider account identity remain `LEGACY_UNKNOWN`; they are not backfilled by sender, subject, thread, or timing. Malformed provider relationships require human review. RFC `References` without `In-Reply-To` remains informational and does not invent an exact parent.

No actual provider credentials, webhook callback, Gmail OAuth session, production traffic, or live Orbyte API was tested. A real deployment must configure and verify the provider account and apply migration 0018 through the normal reviewed deployment process. The full context suite remains non-green for the two recorded cases above; the P1 release owner should disposition the post-#79 catalog test separately.

## Affected module owners and follow-up

P1 Message Intelligence / Channel Integration owns the envelope, adapters, repository, and C1 tests. P5 owns deployment identity and credential configuration. The requested reviewer is `jiahui-1101`. Keep the pull request Draft until that review and current-head CI are complete; do not merge as part of C1 completion.

## Jiahui PR #90 CHANGES_REQUESTED review gates — 2026-10-25

This addendum supersedes the earlier checkpoint details above for the review-fix pass. Latest fetched Main before publication was `7c5ac1531e71bc5d1f762d098af69eaf3dd3785d` (PR #82); it contains PR #92 OCR fix `7ad3ba0482d3ea8cb4b1a6aa5b7b989d66eb19d0` and PR #81 Mock order migration. Main was integrated by normal merge commit, preserving the existing PR branch history. No C2, C3, OCR, or Backend A–H worktree/branch was edited. The full reproducibility and owner disposition are below.

| Gate / Jiahui request | Evidence and latest-Main comparison | C1 cause / files changed | Resolution and remaining owner action |
|---|---|---|---|
| **1. Frontend CI:** inspect exact Actions job, reproduce on PR and Main, identify assertion and ownership. | Original PR head `09c29d568fe1ee85894297e1618f105774b8c49b`: Actions run `40104826861`, failed job `120904236372`, `Frontend Checks (Typecheck, Vitest, Build)`. Node `20.20.2` / npm `10.8.2`; Vitest `5.0.5` warns its engine requires Node `^22.12.0 || ^24.0.0 || >=26.0.0`. The named failure is `frontend/src/features/orders/OrdersRoutingIntegration.test.tsx:90`: after `window.history.back()` is called inside `act`, the test immediately awaits the Portfolio heading but the rendered page remains Calendar. On clean current Main `7c5ac15`, the same Node 20.20.2 full Vitest command failed 6 tests (5 files; 1,209 passed, 5 skipped), including this assertion. Current C1 full run also failed (7 tests/files; 1,208 passed, 5 skipped); other failures varied across the two runs. The isolated named test passed on both the Main and PR trees during the earlier baseline comparison. C1 did not change frontend source or DTOs. | **Not caused by C1 for the named failure:** it reproduces on current Main and the original PR head; `frontend/` has no C1 diff. No Frontend source or DTO file changed. | **Reproduced pre-existing, with environment-sensitive full-suite behavior.** The failing test does not synchronize on the router's actual `popstate`/location transition after native `history.back()`; Node 20 is outside Vitest 5's declared engine range. Frontend owner action: make the test wait for the actual route transition and align CI Node/Vitest versions. No unrelated UI behavior was changed. Current exact-head GitHub check is recorded after publication below. |
| **2. P1 catalog:** compare the exact test on Main, PR #90 and against PR #79. | On clean Main `7c5ac15` and current integrated C1, `test_catalog_is_provisional_fixture_aligned_and_tenant_scoped` fails at `test_deterministic_extraction.py:107` with the same set-inclusion assertion. The pre-PR #79 commit `f8e147d682961c4a133e70a6476f19afe1ebde3c` passes (1 passed). The exact missing `(tenant, sku, unit)` rows are `('synthetic_tenant_a','CHICKEN_NUGGETS','box')`, `('synthetic_tenant_a','CHICKEN_NUGGETS','pcs')`, `('synthetic_tenant_a','chicken nuggets','box')`, `('synthetic_tenant_a','chicken nuggets','pcs')`, the same four rows for `synthetic_tenant_b`, and `('tenant_demo_01','BURGER','pcs')`, `('tenant_demo_01','CHICKEN_NUGGETS','box')`, `('tenant_demo_01','CHICKEN_NUGGETS','pcs')`, `('tenant_demo_01','chicken nuggets','box')`, `('tenant_demo_01','chicken nuggets','pcs')`. PR #79 (`f6eca1a`) introduced `backend/app/context/catalogs/catalog.json` and changed `backend/app/context/deterministic_extraction.py`; neither changed from PR #79 through current Main. | **Not caused by C1.** No catalog source, fixture, or assertion was changed. | **Reproduced on latest Main; PR #79 owns the mismatch.** P1 catalog owner should reconcile the exact tenant/SKU/unit rows or an approved versioned source while preserving tenant scoping. The assertion was not weakened or skipped. |
| **3. OCR:** record the existing failure/environment, verify whether the OCR fix reached Main, and avoid OCR changes. | The exact image acceptance case fails locally on both current Main and C1: `test_e2e_11_pdf_image_evidence_traceable_payment_unverified`, expected `SUCCESS`, got `FAILED`. Environment is Windows Python `3.14.3`, NumPy `2.5.1`, with `paddleocr` absent. PR #92's OCR fix is on current Main (`7ad3ba0` is its ancestor). At PR #92 head `f2a625b35c5b308b95f7314b3eb995a31a887060`, the dedicated OCR Actions job `120913899674` in run `40108100753` passed 25 tests with zero skips under Python `3.11.17`, PaddlePaddle `3.3.1`, PaddleOCR `3.7.0`; all 10 PR checks passed. | **No C1 cause or OCR files changed.** The remaining local failure is the current machine's missing optional OCR runtime, not evidence against the merged OCR fix. | **Upstream fix verified on Main and by its exact-head OCR job.** Use the supported `[dev,ocr]` runtime for a local acceptance rerun. Jiahui's independent OCR workstream was not modified or cherry-picked. |
| **4. Migration 0018:** verify scoped identity, unknown legacy rows, provenance, conflicts and downgrade safety on disposable PostgreSQL. | `0018_c1_scoped_message_parent` retains unknown account/native IDs as `NULL`, marks parent resolution `LEGACY_UNKNOWN` and source `UNVERIFIED`, and leaves raw source JSON/provenance untouched. Uniqueness remains global for legacy rows with unknown account; scoped uniqueness includes tenant/provider/account/native ID, and Telegram additionally includes conversation/chat ID. Ingress requires account + native ID and Telegram conversation scope. Existing old unique key prevents duplicate complete legacy keys before migration. The new regression creates same-legacy-key messages for two distinct accounts, attempts downgrade, and verifies the preflight fails before DDL; both messages, identities, raw IDs, authenticity and current indexes/revision remain. Latest Main PR #81 independently adds `0018_mock_order_requests`; mapping confirmed its five tables are not P1 message/context authorities. | **C1 change:** `backend/migrations/versions/0018_c1_scoped_message_parent.py` now fails downgrade before destructive DDL when account-scoped rows collide under the prior key; regression added in `test_p1_alembic_migration.py`. Because both Main and C1 revisions branch from 0017, added no-op `0019_merge_c1_mock` to join them without changing either schema. `LEGACY_REUSE_MATRIX.md` and `REPOSITORY_BASELINE.md` record the entity map first. | **Resolved on disposable PostgreSQL only.** Downgrade limitation is explicit: reconcile/export conflicting account-scoped records before downgrading; the migration refuses safely instead of discarding data. No shared/staging/production database was migrated. The focused collision + C1 persistence subset passed 9 tests; full C1/P1 PostgreSQL suite passed 41 tests. Alembic reports one head: `0019_merge_c1_mock`. |
| **5. Final verification:** integrate latest Main, rerun required suites, checks, and exact-head CI. | Latest Main `7c5ac1531e71bc5d1f762d098af69eaf3dd3785d` was merged normally. C1/P1 PostgreSQL: **41 passed, 9 warnings**. Channel/framing/source: **92 passed, 4 PostgreSQL-gated skips, 1 warning**. v2.2: **515 passed, 3 skips, 5 warnings**. TypeScript typecheck passed in the Node 20 full-suite runs; production build passed with Node `20.20.2` after including the repository `contracts/` types (209 modules; chunk-size warning). Migration Ruff and format passed; compileall passed; Alembic has one head; `git diff --check` passed. Ruff on the legacy migration-test file still reports two import-order findings; the same two findings reproduce on clean current Main, and format-check reports pre-existing formatting throughout that file. | **C1 changes only migration safety/graph/test and review documentation.** No business logic, P4 authorization, frontend DTO or C2/C3/OCR implementation changed. | Local PR and Main Frontend full-suite results remain red as shown in Gate 1; catalog and local OCR target remain red as shown in Gates 2–3. Exact current-head GitHub CI, reviewer request, and final Main/PR hashes are appended after publication. PR remains unmerged. |

### Review-fix file and scope summary

- Migration safety: `backend/migrations/versions/0018_c1_scoped_message_parent.py`, `backend/app/context/tests/test_p1_alembic_migration.py`.
- Alembic graph reconciliation with current Main: `backend/migrations/versions/0019_merge_c1_mock_heads.py` (revision ID `0019_merge_c1_mock`; no schema operations).
- Audit trail: `LEGACY_REUSE_MATRIX.md`, `REPOSITORY_BASELINE.md`, `docs/TEAM_LOG.md`, and this report.
- Integration modes remain `MOCK` / `SYNTHETIC`; live channel and Orbyte integration are `NOT_RUN`.
