# P3-assisted P5 Core integration handoff — 2026-10-22

**Status:** IN_REVIEW. P5 approval verbally confirmed by P3; formal P5 code review pending. Contributor: P3. Owner/reviewer: P5.

**Base:** `origin/main` `7baffd551f7d01fcbddcbc7ca175aa5547ded03a`. Local branch: `fix/p3-assist-p5-core-integration`. No push, PR submission, PR #10 edit, or demo integration.

## Review scope

- Core assessment audit now distinguishes the evaluated Commitment Version from the resulting risk transition version. The P5 writer preserves the P2 result's exact assessment and snapshot identities; the authoritative history reader rejects missing or inconsistent provenance. The risk event carries exact assessment identity, evaluated version, snapshot version/ID where supplied, and source evidence. The handshake uses a genuine `CommitmentService.assess()` transition and persisted audit/outbox assertions with no identity fallback.
- Stale mandatory outbox events remain failed and retryable when the named subscriber has not completed. Once completion is durably recorded, supersession can publish without replaying stale state. Duplicate consumer delivery remains idempotent; transaction B failure rolls back consumer writes.
- The public legacy execute route returns `EXECUTION_APPROVAL_UNAVAILABLE` (503) when no trusted server-side identity and durable, scoped approval authority is wired. Role and scope errors retain their 403 behavior. Existing synthetic route tests explicitly inject a test-only authority and change only in-memory test records. No live consequential execution was performed.
- Portable test fixtures use SQLite and no longer select PostgreSQL or run `create_all()` as migration evidence. The opt-in PostgreSQL tests require an explicitly approved isolated `TEST_DATABASE_URL`, verify the PostgreSQL dialect and applied Alembic 0007 or descendant, then check real migrated Case/Trigger and ProcessedEvent constraints, RESTRICT, and rollback. No database is created, migrated, reset, or dropped by that suite.

## Exact local evidence

From the isolated worktree's `backend` directory, run:

```text
python -m pytest tests/test_core_assessment_writer_provenance.py tests/test_assessment_reader_fail_closed.py tests/test_outbox_events.py tests/test_transaction_ab_isolation.py tests/test_migration_0007.py tests/test_legacy_execute_safety.py tests/integration/test_feature_handshakes.py tests/integration/test_e2e_hero_journey.py tests/integration/test_e2e_negative_matrix.py tests/integration/test_postgresql_recovery_migration.py -q -p no:cacheprovider
```

Result: **57 passed, 2 skipped, 6 warnings**. Full `python -m pytest tests app/feasibility/tests -q -p no:cacheprovider` also exited 0. The two skipped tests require an approved PostgreSQL test database. Focused `ruff check --select F` and `compileall` passed. `git diff --check` passed. No PostgreSQL connection was made: **PostgreSQL BLOCKED / NOT VERIFIED**. No concurrency, restart, or live P3 subscriber coverage is claimed.

## P5 decisions still needed

1. Review this patch and provide a trusted server-side actor resolver plus durable Manager Approval lookup/verification before enabling public execute. `authorize()` alone does not establish approval. The direct facade execution entry point also needs an authority boundary if it becomes externally callable.
2. Decide how all Core assessment callers provide a trusted `snapshot_id`. The direct facade call lacks that field; the reader rejects its audit as incomplete. Older audit rows without evaluated version or snapshot ID also fail closed. Do not synthesize either value.
3. Coordinate with P2 on the separate P2-owned feasibility adapter, which still uses its own assessment identity and snapshot defaults and is not wired as the Core production writer. No P2-owned file was changed here.
4. Review and, when ready, integrate P3-owned live subscriber and Case/Trigger code separately; those files are absent from this `main`. Verify the opt-in migrated PostgreSQL suite only against an explicitly approved isolated test database and record its sanitized identifier, Alembic revision, dialect, command, and results.

Recommended PR title: **P3-assisted P5 Core provenance, stale outbox, and execute safety fixes**.

Recommended handoff: **P5, please review the focused Core changes and the fail-closed execute authority boundary. Portable focused tests pass (57 passed); PostgreSQL is not verified because no isolated test database was approved. The P2 adapter and direct facade snapshot contract need your decision before live P3 integration.**
