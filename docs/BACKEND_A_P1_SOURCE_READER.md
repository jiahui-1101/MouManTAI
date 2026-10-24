> Latest checkpoint: real PostgreSQL gate PASSED on 2026-10-24; owner approval pending. Earlier NOT_RUN entries below are historical. See the final validation section.

# Backend A6 — Trusted P1 Source Reader

Latest final validation, publication status, and current next-task handoff: [`BACKEND_A6_LATEST_HANDOFF.md`](BACKEND_A6_LATEST_HANDOFF.md).

## Checkpoint and status

The A6 slice adds a read-only adapter around the existing `map_order_context()` function. It loads P1 records in one tenant-scoped PostgreSQL `REPEATABLE READ`, `READ ONLY` transaction and prepares the existing `AcceptanceCandidate`. It does not create a new terms contract, persistence model, route, request, or lifecycle transition.

| State | A6 status |
|---|---|
| Implemented | Repository snapshot method, injected tenant trust boundary, P1 provenance/currentness checks, mapping with no commercial evidence. |
| Locally tested | Focused adapter regressions and portable P1/Core checks; live PostgreSQL snapshot test is gated by the isolated test URL. |
| Integrated | No route or production identity provider is wired; not integrated with Backend B. |
| Reviewed | Awaiting P1/P5 and Backend B review of the repository and evidence boundary. |
| Production-gated | No production authentication, approved pricing/disclosure authority, OrderRequest, or assent workflow is present. |

## P1 records that can be loaded and checked

`PostgresMessageRepository.read_order_context_source(tenant_id, context_id)` reads the current context, context-version history, context reviews, its referenced inbound messages, their current message-association rows, and extraction attempts. The query filters each record by tenant and context/message ID, and returns the current association version and update time. It uses one read-only repeatable snapshot so records from separate database moments are not combined.

The source reader obtains tenant ID only from an injected `TrustedTenantScope`. Missing or invalid scope returns `IDENTITY_UNVERIFIED` before repository access. Existing header-based synthetic request identity is not used. A production caller must supply a host-authenticated tenant provider; none is wired by this slice.

Before mapping, it checks the expected context version against the current context and highest persisted version, verifies the persisted version snapshot matches the context, validates tenant/context/message bindings, verifies raw-message SHA-256 and channel/provider/mode consistency, and checks each field span against both original text and a processed extraction attempt over the same content hash. Extracted normalized values must agree with the current context value. Human field evidence must bind to the exact current P1 review, changed field/value, actor, role, and version. Current review eligibility is also checked by the mapper.

These checks establish consistency within trusted P1 storage. A digest does not prove the external sender or provider. P1 currently stores only the current message-association row and its version, not historical association versions; the candidate preserves that version, and consumers must re-read it.

## Intentionally unsupported evidence

The current P1 source has no approved commercial evidence reader. This slice does not read or invent an OrderRequest ID/version, catalog or quote price, price-source authority, taxes/fees/discounts/total, complete binding fulfilment terms, current disclosure record, customer offer, proposal version, or exact customer assent. It also does not resolve attachment/OCR evidence into source spans. Such evidence fails closed for mapping. It always invokes `map_order_context()` with `commercial_terms=None`; where P1 context and reviews are otherwise valid the result stays `INCOMPLETE` with `COMMERCIAL_EVIDENCE_MISSING`. `READY_FOR_VALIDATION` is not manufactured.

Stored P1 review actor/role fields are checked for record consistency, but the reader cannot independently validate the actor's production authority. The production authentication boundary and any commercial/disclosure authority require P1/P5 and relevant product-owner review.

## Backend B reread boundary

Backend B may use the candidate only as a locator and preparation snapshot. Before an operational decision it must authenticate its own tenant scope and independently reload the latest P1 context/version, source messages and extraction provenance, current review, current association version, approved commercial source and disclosure currentness, and exact customer agreement records. It must apply its own request/version concurrency checks and P2/P5 decision authorities. The candidate is not authorization, feasibility, reservation, or acceptance evidence.

## Before durable OrderRequest or acceptance work

Required first: a reviewed production tenant provider; P1/P5 agreement on association and review authority/currentness; an approved tenant-scoped catalog/quote and disclosure-currentness reader; an owner-reviewed durable OrderRequest identity/version model and migration; P4/Product Owner definition of original-offer versus exact-proposal assent evidence and still-open S1–S5 signoffs; and Backend B review of the shared read/revalidation contract. No persistence, migration, acceptance API, reservation, P2 extension, or Core transition is included here.

## Independent request-version boundary — 2026-10-24

PR #50 now carries a separate `request_version`, but the current P1 schema and this reader do not persist or retrieve an authoritative OrderRequest lifecycle version. The reader continues to pass no commercial evidence, so its result is `INCOMPLETE`. In particular, a changed `context_version` does not populate `request_version`; the test suite asserts that behavior. Do not add a P1 migration or treat the mapper's synthetic adapter fixture as database-backed evidence without P1/P5 approval.

The #55 branch is refreshed through #50 head `9dba996db2c066f7ea5997dbc8dbf7b5dd277540`, including #50's non-rewriting merge of current `main`. This does not change P1 storage or make request-version evidence available. The P1 reader remains read-only and fail-closed.

## 2026-10-24 final real PostgreSQL validation (supersedes earlier NOT_RUN checkpoints)

**PostgreSQL gate PASSED; BLOCKED_BY_OWNER_APPROVAL. Keep Draft.** Validated code/test HEAD: `79b46197c1f3735e08b533f79c5cdca6f0d608c9`. PR #50 merged at `4ffb6c2b1999362aa0e27cb3d834af58cc057267`; #55 now targets `main` and includes fetched main `585467d4389e5d8ada6e5e59a78c96306f3a0bc1` through normal merge commits `997c7a3fe63fc62f8787dff044ee1f8d222945e7` and `ab0e4b632dce04fab7cfbd3204511983fb94dbb1`. No published history was rewritten.

Real PostgreSQL 16.15, task-owned disposable Docker container, actual Alembic head `0017_p1_real_channel_provenance`: required gate **22 passed / 0 failed / 0 skipped**, including all 14 previously skipped DB cases plus two new migrated-schema transaction regressions. Server reports READ ONLY and REPEATABLE READ; a deliberate DML probe is rejected with SQLSTATE 25006; a concurrent committed review cannot mix context/version/review states, and a subsequent stale-version read fails closed. Production code and migrations are unchanged.

Full v2.2: **290 passed**. Combined v2.2/Backend B feasibility/Core/reservation/outbox: **642 passed**. Selected P1/Core: **43 passed / 0 skipped**. Full P1: **625 passed / 1 failed / 4 skipped / 0 setup errors**. The one OCR acceptance failure reproduces on unchanged pre-task #55 `f2300c5ef67750403c32dc4ddd191b2e77acf2eb`; optional OCR/PDF dependencies are unavailable. No claim that the whole P1 suite is green. Scoped Ruff, format, compileall and diff checks pass.

Exact test-head CI [40072357617](https://github.com/jiahui-1101/MouManTAI/actions/runs/40072357617) passed all five jobs, including frontend typecheck/Vitest/build. The current CI does not set P1_TEST_DATABASE_URL or run app/context/tests, so it does not replace the separate real PostgreSQL evidence. The final documentation-only publication SHA and its exact-head CI are recorded in the [existing PR #55 description](https://github.com/jiahui-1101/MouManTAI/pull/55), avoiding a self-referential commit SHA.

P1/P5 CHANGES_REQUESTED reviews remain effective until owners re-review. Fresh requests sent to mavisbong41, Gan0117 and jiahui-1101. No unresolved inline review threads were returned; no review was dismissed or discussion resolved by the author. Main's ruleset requires Backend Tests (PostgreSQL Authoritative), prohibits force updates and branch deletion; legacy protection endpoint returned 404.

The durable P1 OrderRequest/version and approved commercial/disclosure sources remain unavailable. The reader still supplies commercial_terms=None, leaves request_version absent, and stays INCOMPLETE. No acceptance, reservation, approval or Core transition is activated. Backend B must independently reread current authoritative evidence. Full commands, provenance and limitations follow in BACKEND_V2_2_VALIDATION.md.
