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
