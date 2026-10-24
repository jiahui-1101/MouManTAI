# Backend A6 — Latest Handoff

Updated: 2026-10-24 (MYT)

## Status

**DEVELOPMENT COMPLETE — INTEGRATION REVIEW PENDING.** The trusted P1 source reader is implemented and locally tested. The validated code/test commit is `acefd0fa8c4f01d55943f1324aee6ef9c7a692c2` on `backend-a/feat-v2-2-p1-trusted-source-reader`, based on PR #50 head `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`. Documentation publication is tracked separately; the live PR head is the authoritative exact current branch commit.

| Stage | Status | Evidence / gate |
|---|---|---|
| Implemented | Yes | Read-only P1 snapshot repository method and adapter around existing `map_order_context()`; no second `OrderTerms` or `AcceptanceCandidate`. |
| Locally tested | Yes | Exact fresh commands and outcomes below. |
| Integrated | No | No route, production tenant provider, or Backend B operational consumer is wired. |
| Reviewed | Independent A6 code review complete; owner review pending | No critical A6-owned code defect found. P1/P5 and Backend B reviews remain required at their boundaries. |
| Production-gated | Yes | No production identity provider, approved commercial/disclosure reader, durable OrderRequest, customer assent, acceptance, reservation, Core transition, or outbound operation. |

## Implemented boundary

The existing A6 commits `5a423da6033b99e0e56ce3bb9867630a1e05c939` and `80a7cc9c104ca6bfeedb8a5463c7c1becb717c6e` add:

- `backend/app/orders/p1_source_reader.py`: host-injected verified tenant scope, tenant-bound source validation, sanitized outcomes, and invocation of the existing P1 mapper.
- `backend/app/context/repository.py`: immutable `OrderContextSourceSnapshot` and read method in the repository protocol.
- `backend/app/context/postgres_repository.py`: context, versions, reviews, source messages, current associations, and extraction attempts read in a tenant-filtered PostgreSQL `REPEATABLE READ`, `READ ONLY` transaction.
- `backend/app/context/tests/test_order_context_source_snapshot.py` and updates to `backend/app/context/tests/test_postgres_repository.py`: snapshot and repository coverage.
- `backend/tests/v2_2/test_p1_source_reader.py`: source, identity, version, review, association, and fail-closed mapping tests. Commit `acefd0fa8c4f01d55943f1324aee6ef9c7a692c2` adds explicit OCR, PDF text, and attachment-only provenance cases; all return `REVIEW_REQUIRED` without exposing the attachment reference.

The review checked tenant filters at each P1 lookup, snapshot transaction setup, immutable/read-only behavior, context and source versions, message hash/provider/channel bindings, extraction spans and values, current review actor/version, association tenant/customer bindings, missing-source handling, and candidate status boundaries. No source-code correction was justified. PostgreSQL transaction behavior itself was not exercised because no approved disposable P1 test database was configured.

## What the reader can verify

The read result is bound to the tenant from `TrustedTenantScope`, an expected context ID and version, its current stored version snapshot, and the P1 records loaded in one database snapshot. It checks raw-message SHA-256, provider/mode/channel consistency, extracted evidence span/value/content-hash consistency, current P1 review evidence, and the current association row/version. It does not claim provider authenticity from the hash or actor authority from stored actor fields.

The reader always calls `map_order_context()` with `commercial_terms=None` and `existing_core_terms=None`. Consequently a valid P1-only candidate remains `INCOMPLETE`; it cannot manufacture `READY_FOR_VALIDATION`, an OrderRequest identifier/version, approved price, disclosure currentness, customer assent, feasibility, acceptance, or a reservation.

The current P1 association record has a version but no historical association-version table. Attachment/PDF/OCR evidence is outside this snapshot reader and fails closed unless separately represented through a current, validated P1 human review. No production tenant authentication provider or API route is wired.

## Fresh validation

Executed from `backend` on the A6 code/test checkpoint above, using portable local test storage. Results are current; prior counts in chronological handoff records remain historical.

| Command | Result |
|---|---|
| `python -m pytest tests/v2_2/test_p1_source_reader.py -o addopts= -q --tb=short --basetemp=../pytest-tmp-a6-final-focused-r2` | **21 passed, 5 existing FastAPI/Starlette deprecation warnings** |
| `python -m pytest tests/v2_2 -o addopts= -q --tb=short --basetemp=../pytest-tmp-a6-final-v22-r2` | **197 passed, 5 existing FastAPI/Starlette deprecation warnings** |
| Selected P1/Core command below, with `-rs` | **21 passed, 22 skipped, 5 warnings**; every skip states `P1_TEST_DATABASE_URL is unset; PostgreSQL validation NOT RUN` |
| `python -m pytest app/context/tests/test_order_context_source_snapshot.py app/context/tests/test_postgres_repository.py -o addopts= -q -rs --tb=short --basetemp=../pytest-tmp-a6-final-pg-r2` | **6 passed, 13 skipped**; all 13 state that `P1_TEST_DATABASE_URL` is unset |
| Scoped Ruff check below | **Passed** |
| `python -m ruff format --check app/orders/p1_source_reader.py tests/v2_2/test_p1_source_reader.py` | **Passed; 2 files already formatted** |
| Scoped `python -m compileall -q` below | **Passed; exit 0** |
| `git diff --check` | **Passed** |

Selected P1/Core command:

```powershell
python -m pytest app/context/tests/test_order_context_storage.py app/context/tests/test_association_models_and_storage.py app/context/tests/test_context_api.py app/context/tests/test_review_readiness.py app/context/tests/test_core_publisher.py app/context/tests/test_p2_consumer.py tests/test_core_api.py tests/test_core_assessment_writer_provenance.py -o addopts= -q -rs --tb=short --basetemp=../pytest-tmp-a6-final-p1core-r2
```

Static checks:

```powershell
python -m ruff check --select E,F,I --ignore E501,F401,F841 app/context/repository.py app/context/postgres_repository.py app/context/tests/test_order_context_source_snapshot.py app/context/tests/test_postgres_repository.py app/orders/p1_source_reader.py tests/v2_2/test_p1_source_reader.py
python -m ruff format --check app/orders/p1_source_reader.py tests/v2_2/test_p1_source_reader.py
python -m compileall -q app/orders/p1_source_reader.py app/context/repository.py app/context/postgres_repository.py app/context/tests/test_order_context_source_snapshot.py app/context/tests/test_postgres_repository.py tests/v2_2/test_p1_source_reader.py
```

PostgreSQL validation is **NOT_RUN / BLOCKED**: `P1_TEST_DATABASE_URL`, `P1_DATABASE_URL`, `TEST_DATABASE_URL`, `DATABASE_URL`, and `TEST_MIGRATION_DATABASE_URL` were unset. The 35 PostgreSQL-gated tests above were skipped, not passed. No database was created or modified, and no shared/development/production database was used. The repeatable-read and read-only transaction assertions remain unverified against live PostgreSQL on this branch.

## Dependencies and review gates

- PR #50 contains the mapper and canonical candidate contract. This branch is based on its current head and must remain stacked on PR #50's branch, `backend-a/feat-v2-2-p1-order-context-mapper`.
- PR #48 remains the canonical `OrderTerms` foundation; PR #52 carries separate foundation hardening. PR #49 and #53 are unaffected. No existing PR or branch history was rewritten.
- P1 review is required for repository ownership, persisted review/association semantics, and compatibility. P5 review is required for production tenant authentication and shared authority boundaries. Backend B must independently authenticate and re-read the current P1 and agreement records before operational use.
- A Product Owner/P1/P5-approved commercial source and disclosure-currentness authority, plus P4/Product Owner agreement evidence semantics, remain prerequisites for a future complete candidate. S1–S5 remain unratified.

## Publication and next task

Draft PR #55: [https://github.com/jiahui-1101/MouManTAI/pull/55](https://github.com/jiahui-1101/MouManTAI/pull/55), open, Draft, unmerged, and reported mergeable after GitHub completed its initial calculation. It targets `backend-a/feat-v2-2-p1-order-context-mapper` at `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`; its head is `backend-a/feat-v2-2-p1-trusted-source-reader`. Initial pushed head was `2e860a3cd430cb6538acb7483cf18d83bec0dbac`; this final publication metadata update is documentation-only, so the latest exact SHA is the head shown by PR #55 and the post-push `git rev-parse HEAD` check.

Requested reviewers: P1 `mavisbong41` and P5 `Gan0117`. GitHub compare reports 4 commits ahead / 0 behind the requested base and 11 changed A6 files. No PR-triggered workflow runs were returned for the published head. The worktree was clean after the normal push and is rechecked after this documentation-only follow-up. No merge, auto-merge, Main push, production communication, acceptance, reservation, or Core transition was performed.

Next safe Backend A slice after P1/P5 review: define and implement a trusted tenant-scoped commercial price-source and disclosure-currentness reader, preserving the mapper's fail-closed behavior. Do not add durable OrderRequest storage or acceptance workflow until its identity/version model and P4 assent evidence have explicit owner review; Backend B must approve the reread contract.

## Independent request-version / parent refresh — 2026-10-24

PR #50's corrected candidate contract now requires an independent positive `request_version` with source identity and currentness evidence. Repository inspection still finds no durable P1 OrderRequest record or authoritative request-version reader. This P1 source reader passes `commercial_terms=None` and returns `INCOMPLETE`; it does not infer request version from `context_version`, terms revision/hash, or any ID. A regression now advances the P1 context version and proves the candidate's OrderRequest version stays absent and readiness stays `INCOMPLETE`.

The #55 branch was refreshed by a non-rewriting merge of #50's new request-version contract. The refresh does not add a P1 column or migration. PR #55 remains blocked on P1/P5 source-reader review and real disposable PostgreSQL evidence; see the 2026-10-24 refresh section below for exact local validation.
