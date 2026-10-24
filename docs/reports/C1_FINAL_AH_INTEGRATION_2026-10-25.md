# C1 final Backend A–H integration

Date: 2026-10-25 (Asia/Kuala_Lumpur). PR: #90.

## Scope and requirement IDs

User-authorized C1 final integration against finalized Backend A–H. Preserve canonical source evidence, tenant/provider/account scope, exact-parent resolution and all existing safety tests (AGENTS §§3, 3.1.6, 8, 11, 15).

## Existing implementation reused

C1 base `ee6196144ffe3d977bc2a744362a0671a4aabe2e`; Main `7035a509a61f684163cfa828f05d47619c0484f6` includes merged #88. Reuse existing P1 source/context/attachment persistence and unchanged A–H authorities. The integration has no text conflicts. Shared Core/Orders/P4/Frontend sources match Main exactly. Main's root requirements removals are preserved; the v2.2 copies remain in `docs/requirements/v2.2/`.

## Files, contract and migration changes

`LEGACY_REUSE_MATRIX.md` records the actual final mapping before merge revision authoring. Add graph-only `0024_merge_c1_ah`, joining unchanged `0020_merge_c1_p4` and `0023_mock_memory_history`. Upgrade/downgrade contain no DDL or data writes. Keep all prior revisions and the scoped-delivery downgrade collision refusal. Update that test's expected head and add upgrade/replay coverage from both parent histories with source-row preservation. No duplicate store or schema/data deletion.

#95 is an unchanged, separate Draft dependency. Its owner must reconcile its migration lineage after C1; this change does not copy or modify orchestration.

## UI and backend behavior delivered

No new business behavior or UI. Existing C1 persistence/framing is integrated with A–H. Exact source association grants no contact verification, customer assent, acceptance, reservation, supplier selection or emergency authority.

## Integration modes

PostgreSQL and HTTP fixture behavior: VALIDATED with SYNTHETIC/MOCK inputs. Provider E2E: NOT_RUN. No live outbound configuration, credentials or provider calls enabled.

## Validation commands and observed results

Run from `backend/`, Python 3.14 with existing installed dependencies and task-owned PostgreSQL 16 on port 15473. Set `MOUMANTAI_SYNTHETIC_MODE=1`, `TELEGRAM_AUTO_START=false`, `GMAIL_AUTO_START=false`, `P1_AI_ENABLED=false`; P1 PostgreSQL URL points only to `moumantai_c1_test`.

- PASSED: `python -m pytest -q -o addopts= --basetemp=<task-temp> app/context/tests/test_c1_completion_persistence.py app/context/tests/test_postgres_repository.py app/context/tests/test_c1_repository_regression.py app/context/tests/test_p1_inbox_acceptance_regressions.py app/context/tests/test_p1_alembic_migration.py app/context/tests/test_reply_framing.py app/context/tests/test_c1_adapter_framing.py app/context/tests/test_telegram_channel.py app/context/tests/test_whatsapp_channel.py app/context/tests/test_gmail_channel.py app/context/tests/test_channel_manager_and_routes.py app/context/tests/test_real_provenance_and_ai_pipeline.py --tb=short` — 135 passed, 20 warnings. Covers fresh migrations, legacy unknown provenance, upgrades from either parent, replay, blocked downgrade without data loss, scoped idempotency, exact/late parents and negative ingress/tenant/account cases.
- PASSED: `python -m alembic heads` — sole head `0024_merge_c1_ah`.
- PASSED: `python -m ruff check migrations/versions/0024_merge_c1_ah.py`, `python -m ruff format --check migrations/versions/0024_merge_c1_ah.py`, `python -m compileall -q app`, `git diff --check`.
- Initial run: 98 passed, 37 setup errors caused by Windows access denial on the shared pytest temp root. The task-specific `--basetemp` rerun above passed without changing application code or skipping tests. The first migration run also caught the old expected-head assertion; it was updated to the new head, retaining all collision/data checks.
- Broader backend/feasibility/communication and authoritative migrated PostgreSQL regressions are running at publication preparation; final observed outcomes will be posted in #90. PostgreSQL uses task-owned `moumantai_c1_final_20261025_test` and `moumantai_c1_final_migration_test`, with `REQUIRE_POSTGRES=1`, `TEST_DATABASE_APPROVED=1` and matching P1/P4 suite URLs. These tests never target the application database.
- Exact publication-head GitHub CI must be verified after push. Older-head CI is not proof for this integration.

## Business/security/CTA approvals enforced

No authority or transport enabling change. Fresh Jiahui approval, explicit merge authorization, required Ready-for-Review process and exact-head successful CI remain merge gates. Keep Draft while those gates are unresolved; do not use an older approval for this integration.

## Known limitations, owners and follow-up

Jiahui: final-head C1 review and explicit merge authorization, #95 lineage reconciliation, source-retention policy for Main's existing physical DELETE operation. C2 #96 stays unchanged until #90 merges. Its Resend attribution/shared constraint changes and P4 send/contact/consent/durable receipt mapping need designated owner approval. No provider E2E or credential verification is claimed. Main's prior catalog/OCR/frontend review history is in the existing C1 completion report; exact new-head CI is authoritative for this publication.
