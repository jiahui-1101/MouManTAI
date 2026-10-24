# v2.2 Mock Backend integration report

Status: implementation branch `feat/v22-mock-order-acceptance-20261024`. All Orbyte-origin facts and effects in this branch are labelled `MOCK` / `DEMO-ONLY`. No real Orbyte credentials, API calls, supplier purchase, customer delivery or production identity are enabled.

## Operational journeys

| Journey | Evidence | Current boundary |
|---|---|---|
| Synthetic inquiry → durable OrderRequest → SME review → fresh P2 → Mock stock-lot reservation → Core accepted commitment | Registered `/v1/backend-v2` APIs; PostgreSQL migration 0018; live Uvicorn + PostgreSQL test; concurrent and negative tests | Operational for one SKU line in one isolated, server-bound synthetic tenant. The inquiry is a controlled Mock source, not an authenticated real customer or automatic P1 context conversion. |
| Supplier delay → impact → Recovery case/plan → human approval → controlled internal action receipt | Existing registered P2/P3 flow and `test_p3_live_postgresql_http.py` passing against migrated disposable PostgreSQL | Operational as a separate synthetic journey. It is not yet triggered from newly accepted OrderRequests. |
| Communication request → draft/review → Mock provider send/receipt | Existing P4 routes and tests; Mock provider is local | Separate synthetic P4 flow. New accepted-order outbox has no subscribed P4 customer milestone or verified recipient contact. |
| Operational status and timeline | Registered OrderRequest status/timeline APIs backed by request/Core audit plus Mock reservation receipt | `ORDER_ACCEPTED` requires matching persisted evidence; production and delivery actuals remain `NOT_AVAILABLE`. No fabricated daily KPI. |
| Supplier, forecasting, portfolio optimization, decision memory advice | Existing pure engines and fixtures | No source-backed registered advisory workspace API on this branch; not operational end to end. |

## Implementation and persistence

Migration `0018_mock_order_requests` creates `mock_order_sources`, `order_requests`, `order_request_audit`, `mock_orbyte_states`, and `mock_orbyte_reservations` with tenant keys, status constraints and idempotency uniqueness. The Mock adapter serializes reservations with PostgreSQL row locks, checks source and snapshot versions, reserves exact stock lots, records durable confirmed/failed/unknown receipts and handles reject/unknown/reconcile. The acceptance service rechecks exact terms and P2 against the locked current snapshot and commits Mock receipt, Core commitment, audit and outbox together. It makes no cross-system atomicity claim.

The exact registered routes, request/response schemas, errors and Frontend page mapping are in [the API contract](../contracts/V22_MOCK_BACKEND_API_2026-10-24.md). The React pages are owned by the Frontend team and are not wired here. The isolated key belongs on a trusted server, not in browser code.

## Verification

- Focused local v2.2 API, terms and new Mock tests: 91 passed, 3 PostgreSQL-only skipped.
- Migrated disposable PostgreSQL v2.2 suite after tenant binding and resource HTTP setup: 518 passed, 5 warnings, no skips. Final focused migrated PostgreSQL Mock suite after durable rejected receipts and replay checks: 25 passed, 5 warnings, no skips.
- Live Uvicorn + PostgreSQL Mock order workflow: passed inside the focused suite.
- Existing live Uvicorn + worker + PostgreSQL supplier-delay Recovery workflow: 1 passed.
- Alembic has a single head, `0018_mock_order_requests`; `git diff --check` passed.
- P4 suite invoked without its required `MOUMANTAI_SYNTHETIC_MODE=1` produced 44 identity-gate failures. With the flag set, 442 passed and one existing follow-up migration rollback assertion failed because it assumed migration 0015 was still the Alembic head. The assertion now first downgrades to 0015 to test its own parent boundary; the affected follow-up test file passed (28 passed, 29 skipped). The first run was an environment setup error, and the second failure was a test assumption invalidated by additive migrations.
- Frontend production build passed. A parallel Vitest run under concurrent backend tests had 4 order/calendar navigation failures (1126 passed, 5 skipped). All four affected files passed serially (56 tests), and the full serial rerun passed (1130 passed, 5 skipped). No Frontend source was modified; the parallel failures were timing sensitive in this Windows run.

## Security and release state

Mock business routes require the isolated feature gate, a server-owned 32+ character key, exact server-configured Manager actor and server-configured tenant. Production disables the routes. Tenant headers outside the configured tenant are rejected. Malformed versions and decimal floats are rejected. Unknown reservation outcomes cannot create accepted commitments; reconciliation confirms no Mock resource effect before retry.

The new work is unmerged. CI on the exact PR head and Meishuet's review are still required. Preserve the previously reported OCR issue as a visible release blocker until fixed and independently verified. Verdict for the whole A–H request: **PARTIALLY_INTEGRATED**. P0 Mock accepted-order execution is working; P1/P2 cross-module and advisory coverage remains incomplete.
