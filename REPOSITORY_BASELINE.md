# MouManTAI Repository Baseline — C1 Persistence Completion

Audit date: 2026-10-24 (Asia/Kuala_Lumpur)
Repository: `jiahui-1101/MouManTAI`
Task branch: `codex/c1-canonical-persistence-completion`
Task start commit: `d3c2a3e927977d428b63f240f665db34594786d2` (merge of PR #89)
Initial working tree: clean. The feature branch was created from that commit in an isolated worktree.

## Persistence and migration baseline

Before this task, Alembic's single P1 persistence head was `0017_p1_real_channel_provenance`, following `0016_p1_context_persistence`. The P1 schema already contained these tables under `p1_dev`: `attachments`, `context_reviews`, `document_extractions`, `extraction_attempts`, `inbound_messages`, `message_associations`, `order_context_versions`, and `order_contexts`. `inbound_messages` had the legacy unique key `(tenant_id, channel, provider_message_id)`, immutable raw JSON/fingerprint fields, and provider/synthetic provenance. No C1-specific schema migration had been applied.

The repository also has Core, Recovery, Feasibility, Communication and other domain persistence defined in their own modules and migrations. C1 does not add or alter those authorities. Migration `0018_c1_scoped_message_parent` is the only C1 schema revision and extends `p1_dev.inbound_messages` in place.

## Existing P1 API and tests

`backend/app/context/router.py` already exposed the provisional development ingest endpoint, message list/detail/process/extraction/attempts/association routes, Order Context read/create/review/update/version/history/publish routes, and attachment upload/content/page-count/page/extract routes. `backend/app/context/channels/router.py` already exposed channel status/poll, Telegram webhook, WhatsApp webhook verification/callback, and Gmail OAuth/verification routes. The public `/v1/messages/ingest` route was explicitly synthetic; real-provider ingress used the existing channel adapters.

P1 tests already covered channel adapters and routes, PostgreSQL persistence, provenance and AI framing, E2E ingestion, context acceptance regressions, Alembic migration compatibility, attachments/OCR, Core publication, and human review. Existing OCR/PDF regressions are preserved; the repository log records an optional-dependency failure for one image/PDF acceptance test, so that historical failure is not treated as C1 evidence.

## Main refresh during implementation

At task start the fetched `origin/main` matched the task base. During the work, `origin/main` advanced to `f6eca1ac93b382c2ffe68965e18b55f12e03d322` (PR #79, human-review save synchronization). That change touched `backend/app/context/postgres_repository.py` and P1 UI files, but added no migration revision. The branch must incorporate this latest Main commit before publication and rerun the affected tests against the merged tree.

## C1 reuse decision

The C1 implementation extends the existing P1 message envelope, `p1_dev.inbound_messages`, repository, channel adapters and Order Context projection. It adds exact provider-account-scoped idempotency and durable parent-resolution fields to the existing message row. It does not create a second inbox/source-message table, change Core/P2/Recovery/P4 authority, or convert a message association into customer assent or order acceptance. See [`LEGACY_REUSE_MATRIX.md`](./LEGACY_REUSE_MATRIX.md) for the entity-level reuse/extend/add/deprecate mapping and verification references.

## Implementation audit snapshot

The C1 working tree adds migration `0018_c1_scoped_message_parent` and extends the P1 schema/repository/adapters. New test files are `backend/app/context/tests/test_c1_adapter_framing.py` and `backend/app/context/tests/test_c1_completion_persistence.py`; existing P1 channel, migration, repository and acceptance-regression tests are extended. No schema migration has been applied to any shared or production database. PostgreSQL migration tests use only the separately named task-owned disposable test container, which is removed after validation.
