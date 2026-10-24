# OrderRequest frontend facade proposal — owner decision required

**Status:** PROPOSED, NOT APPROVED. Frozen Main `1cd91bf5b6cc3e92a91eb48d2c166f4b8af50456`. Owners: P5 (`Gan0117`) for identity/authorization and shared routing; Orders (`jiahui-1101`) for OrderRequest semantics. This document adds no runtime authority or API implementation.

## Existing authority and reuse decision

`frontend/src/shared/auth.tsx` is a demo selector. It stores tenant/actor in React and sends `X-Tenant-ID`/`X-Actor-ID`; neither header proves an authenticated session. `backend/app/core/dependencies.py` accepts them only with `MOUMANTAI_SYNTHETIC_MODE=1`. `backend/app/orders/router.py` additionally requires the server-held `X-Isolated-E2E-Key`, configured manager ID and tenant, and refuses production. `frontend/vite.config.ts` already injects that key for selected Recovery and P4 requests. Its generic `/v1` proxy and client-controlled role selector do **not** provide a trusted Orders session. Simply adding a broad `/v1/backend-v2` proxy rule would expose fixture creation and unrelated privileged commands.

**Proposed smallest reuse:** keep all existing Orders/Core/P2 business routes and DTOs. Add only a method/path allowlisted, synthetic-only server-side facade in the existing local server/proxy layer. The facade forwards approved calls to the registered `/v1/backend-v2` Orders routes with a server-held key and server-resolved tenant/manager; it never accepts browser identity or an isolated key as authority. No new acceptance engine, database table, migration, or Core transition is proposed. P5 must confirm the trusted operator/session bootstrap below before this is implemented. There is no existing reusable authenticated BFF or cookie session in Main.

## Proposed browser-facing contract

Prefix suggestion: `/demo-bff/order-requests`. The path is an implementation detail for P5 review; the upstream Orders routes and their models are the contract authority. All responses remain `MOCK` / `DEMO-ONLY` and carry `Cache-Control: no-store`.

| Browser method/path | Existing delegated operation | Request and response | Facade permission |
|---|---|---|---|
| `GET /demo-bff/order-requests` | `GET /v1/backend-v2/order-requests` | `MockOrderRequestView[]` | Bound operator session, scoped tenant |
| `GET /demo-bff/order-requests/{id}` | `GET /v1/backend-v2/order-requests/{id}` | `MockOrderRequestView` | Same, exact ID |
| `GET /demo-bff/order-requests/{id}/feasibility` | Same upstream suffix | `MockFeasibilityView` | Same; read-only P2 result |
| `POST /demo-bff/order-requests/{id}/review` | Same upstream suffix | `ReviewMockRequest` (`expected_request_version` strict integer, `REVIEWED` or `REJECTED`, nonempty reason) -> `MockOrderRequestView` | Bound manager session, CSRF, explicit user confirmation |
| `POST /demo-bff/order-requests/{id}/accept-mock` | Same upstream suffix | `AcceptMockRequest` (strict request/snapshot versions, exact terms hash, stable idempotency key, reason) -> `AcceptMockResponse`, possibly 202 | Bound manager session, CSRF, explicit user confirmation |
| `GET /demo-bff/order-requests/{id}/timeline`, `GET /demo-bff/order-requests/{id}/operational-status` | Same upstream suffixes | Existing `MockTimelineEntry[]` / `MockOperationalStatus` | Same scoped read |
| `GET /demo-bff/mock-orbyte/reservations/{operation_id}` | Same upstream path | Existing `ReservationReceipt` | Same; unknown-outcome inspection |

The feasibility result already contains `snapshot_version`, so exposing the full Mock resource snapshot is unnecessary for the minimum acceptance UI. The `POST /reconcile-mock` route should remain unavailable to the browser until Orders/P5 decide whether reconciliation is a separate manager action. A 202 acceptance response must remain `RESERVATION_UNKNOWN`, with no Commitment displayed as accepted and no fresh key submitted automatically. The UI can inspect the durable receipt and direct the operator to a separately approved reconciliation process.

## Session, tenant, RBAC and request boundary

1. The facade is enabled only in an explicitly isolated synthetic environment and binds to loopback for local demo. It refuses production and missing server configuration. The upstream FastAPI guards remain in force.
2. P5 must nominate a trusted session bootstrap: a server-issued opaque, HttpOnly, SameSite=Strict, Secure-on-HTTPS cookie bound to one configured demo tenant and the configured manager principal. A client-chosen `X-Tenant-ID`, `X-Actor-ID`, `X-Actor-Role`, tenant query/body field, or React role selector must never establish or switch that identity. There is no such bootstrap in Main; approval must identify who can establish the session and how it expires/revokes. If no trusted bootstrap is approved, browser mutations remain disabled.
3. Server resolves tenant and actor for every request from that session and overwrites, rather than forwards, browser identity/key/correlation authority headers. It checks manager permission for review/accept. Session tenant must equal the configured isolated tenant. Unknown or cross-tenant IDs remain 404/403 per the upstream boundary, with no record leakage.
4. Mutations require same-origin checks plus a session-bound CSRF token in a request header, a JSON content type, bounded body, and an allowlisted path/method. Deny all other `/v1/backend-v2` paths, including fixture import/resource writes, supplier, forecast, optimization, memory and unrelated commands. Rate limiting and origin/host validation should be scoped to the local facade. A browser-accessible Vite proxy rule alone is insufficient for identity/CSRF.
5. The facade relays upstream response status and safe `{code,message,correlation_id,details}` errors. It never transforms a failed/unknown response to success. Secrets are excluded from logs, errors and bundles. Browser `401` means no valid session; `403` means role/scope/CSRF denial; `404` unknown scoped record; `409` stale version/terms/source/resource or duplicate-key conflict; `422` malformed command; `500/503` backend or authority unavailable. For 409, refresh the authoritative request and resource/assessment before a new explicit action.

## Delegation and durable behavior

The facade passes exact client-visible expected versions, terms hash, reason and idempotency key to Orders after validating shape; Orders rereads source and terms, locks rows, invokes P2, reserves Mock resources, verifies receipt, creates Core Commitment and audit/outbox in its existing transaction. The facade must not calculate feasibility, mint receipt status, change lifecycle fields, or write PostgreSQL. Review uses Orders' current source/version check and audit. For acceptance, preserve one idempotency key across transport retries of the same confirmed command; a timeout or 202 is unknown until the server response/receipt is reread. Do not automatically repeat with a fresh key. Audit actor is the server-resolved principal; propagate correlation ID safely, without client-selected authority fields.

## Owner decisions requested

1. **P5:** Is an isolated, loopback-only manager session acceptable for this synthetic demo? Specify trusted session bootstrap, lifetime/revocation, CSRF and the owned server layer. If not, identify an existing approved session provider to reuse. Confirm whether facade error mapping and header overwrite preserve the shared authorization contract.
2. **Orders:** Approve the exact read/review/accept delegation and status/receipt behavior, including use of the P2 feasibility `snapshot_version` as the preview input and whether browser receipt inspection is sufficient while reconciliation stays server-only. Confirm the UI's mapping of `PENDING`, `REVIEWED`, `ACCEPTED`, `REJECTED`, `RESERVATION_UNKNOWN` without treating `REVIEWED` or a message as accepted.
3. Both owners: confirm no change is needed to the upstream DTOs, database migration, Core authority, or production identity contract. Record any requested revision here before code is written.

## Validation after approval

Use a fresh migrated PostgreSQL 16 database, configured isolated manager/tenant and worker. Cover missing/expired session, forged headers, CSRF, wrong origin, staff, cross-tenant reads and writes, stale request/source/resource/terms, duplicate submission, 202 unknown receipt, backend unavailable, and secret non-disclosure. Exercise the same Commitment in a real browser through review/accept and P2/P3/P4/timeline, refresh the browser, and verify persisted state. Typecheck, Vitest, build, relevant backend tests and exact-head CI follow implementation. No API/component test is to be reported as Browser E2E.
