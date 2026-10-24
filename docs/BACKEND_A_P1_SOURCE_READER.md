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
