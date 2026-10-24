# OrderRequest frontend facade — isolated demo implementation

**Status:** Orders Owner approved the synthetic-only facade in PR #114 on 2026-10-25. The owner explicitly waived additional P5 pre-implementation review for this isolated hackathon demo. Baseline Main `1cd91bf5b6cc3e92a91eb48d2c166f4b8af50456`. This decision does not approve production identity or shared authorization changes; none were made.

## Existing authority and reuse decision

`frontend/src/shared/auth.tsx` is a demo selector. It stores tenant/actor in React and sends `X-Tenant-ID`/`X-Actor-ID`; neither header proves an authenticated session. `backend/app/core/dependencies.py` accepts them only with `MOUMANTAI_SYNTHETIC_MODE=1`. `backend/app/orders/router.py` additionally requires the server-held `X-Isolated-E2E-Key`, configured manager ID and tenant, and refuses production. `frontend/vite.config.ts` already injects that key for selected Recovery and P4 requests. Its generic `/v1` proxy and client-controlled role selector do **not** provide a trusted Orders session. Simply adding a broad `/v1/backend-v2` proxy rule would expose fixture creation and unrelated privileged commands.

**Implemented reuse:** `frontend/demoBff.ts` is a Vite serve-only, loopback-only middleware using the existing local proxy server. It forwards an exact method/path allowlist to existing Orders and orchestration readers, with a server-held isolated key and server-resolved tenant/manager. There is no new acceptance engine, database table, migration, Core transition, or production route. Main had no reusable authenticated BFF or cookie session.

## Proposed browser-facing contract

Prefix: `/demo-bff`. The upstream Orders routes and their models remain the contract authority. Responses carry `Cache-Control: no-store`.

| Browser method/path | Existing delegated operation | Request and response | Facade permission |
|---|---|---|---|
| `GET /demo-bff/order-requests` | `GET /v1/backend-v2/order-requests` | `MockOrderRequestView[]` | Bound operator session, scoped tenant |
| `GET /demo-bff/order-requests/{id}` | `GET /v1/backend-v2/order-requests/{id}` | `MockOrderRequestView` | Same, exact ID |
| `GET /demo-bff/order-requests/{id}/feasibility` | Same upstream suffix | `MockFeasibilityView` | Same; read-only P2 result |
| `POST /demo-bff/order-requests/{id}/review` | Same upstream suffix | `ReviewMockRequest` (`expected_request_version` strict integer, `REVIEWED` or `REJECTED`, nonempty reason) -> `MockOrderRequestView` | Bound manager session, CSRF, explicit user confirmation |
| `POST /demo-bff/order-requests/{id}/accept-mock` | Same upstream suffix | `AcceptMockRequest` (strict request/snapshot versions, exact terms hash, stable idempotency key, reason) -> `AcceptMockResponse`, possibly 202 | Bound manager session, CSRF, explicit user confirmation |
| `GET /demo-bff/order-requests/{id}/timeline`, `GET /demo-bff/order-requests/{id}/operational-status` | Same upstream suffixes | Existing `MockTimelineEntry[]` / `MockOperationalStatus` | Same scoped read |
| `GET /demo-bff/reservations/{operation_id}` | `GET /v1/backend-v2/mock-orbyte/reservations/{operation_id}` | Existing `ReservationReceipt` | Same; unknown-outcome inspection |
| `GET /demo-bff/commitments/{id}/timeline`, `GET /demo-bff/commitments/{id}/notification-intents` | Existing orchestration readers | Same-Commitment chronology and pending P4 intents | Same scoped read |

The feasibility result already contains `snapshot_version`, so exposing the full Mock resource snapshot is unnecessary for the minimum acceptance UI. The `POST /reconcile-mock` route should remain unavailable to the browser until Orders/P5 decide whether reconciliation is a separate manager action. A 202 acceptance response must remain `RESERVATION_UNKNOWN`, with no Commitment displayed as accepted and no fresh key submitted automatically. The UI can inspect the durable receipt and direct the operator to a separately approved reconciliation process.

## Session, tenant, RBAC and request boundary

1. The facade is enabled only in an explicitly isolated synthetic environment and binds to loopback for local demo. It refuses production and missing server configuration. The upstream FastAPI guards remain in force.
2. `POST /demo-bff/session` accepts a separate 32+ character server-configured operator bootstrap token only over local same-origin JSON. The server issues a random opaque, HttpOnly, SameSite=Strict, Secure-on-HTTPS cookie, bound to the configured tenant and manager, expiring in 20 minutes. `GET /demo-bff/session` reads it; `DELETE /demo-bff/session` with CSRF revokes it. Sessions are in server memory and die on server restart. The bootstrap token is distinct from the backend credential. If this configuration is absent, all facade routes return 503 and the UI disables actions. The React selector never establishes this identity.
3. Server resolves tenant and actor for every request from that session and overwrites, rather than forwards, browser identity/key/correlation authority headers. It checks manager permission for review/accept. Session tenant must equal the configured isolated tenant. Unknown or cross-tenant IDs remain 404/403 per the upstream boundary, with no record leakage.
4. Mutations require an Origin matching the local Host, a session-bound `X-CSRF-Token`, JSON content type, 4096-character body limit, and an allowlisted path/method. Remote and non-loopback Host requests are denied. Browser `X-Tenant-ID`, `X-Actor-ID`, and `X-Isolated-E2E-Key` headers are rejected. No fixture import/resource write, reconcile, supplier, forecast, optimization, memory, or unrelated command is forwarded. The upstream `trusted_isolated_manager` guard checks configured manager permission for every delegated Orders operation. Local operator bootstrap is the access rate boundary; no network-exposed rate limiter is claimed.
5. The facade relays upstream response status and safe `{code,message,correlation_id,details}` errors. It never transforms a failed/unknown response to success. Secrets are excluded from logs, errors and bundles. Browser `401` means no valid session; `403` means role/scope/CSRF denial; `404` unknown scoped record; `409` stale version/terms/source/resource or duplicate-key conflict; `422` malformed command; `500/503` backend or authority unavailable. For 409, refresh the authoritative request and resource/assessment before a new explicit action.

## Delegation and durable behavior

The facade passes exact client-visible expected versions, terms hash, reason and idempotency key to Orders; Orders validates shape, rereads source and terms, locks rows, invokes P2, reserves Mock resources, verifies receipt, creates Core Commitment and audit/outbox in its existing transaction. The facade does not calculate feasibility, mint receipt status, change lifecycle fields, or write PostgreSQL. Review uses Orders' current source/version check and audit. For acceptance, preserve one idempotency key across transport retries of the same confirmed command; a timeout or 202 is unknown until the server response/receipt is reread. Do not automatically repeat with a fresh key. Audit actor is the server-resolved principal; client correlation headers are not forwarded.

The implementation leaves command schema validation to the existing Orders Pydantic DTOs. The browser retains an unresolved acceptance key and known receipt operation ID in tenant/request-scoped sessionStorage across refresh. It clears the key only after a confirmed matching Commitment. No retry is automatic.

## Local demo configuration

Start the migrated PostgreSQL backend and worker with `MOUMANTAI_SYNTHETIC_MODE=1`, `MOUMANTAI_ISOLATED_E2E=1`, an isolated `MOUMANTAI_ISOLATED_E2E_KEY`, and the matching `MOUMANTAI_ISOLATED_E2E_MANAGER_ID` and `MOUMANTAI_ISOLATED_E2E_TENANT_ID`. Start Vite on loopback with the same server-only values, a distinct `MOUMANTAI_BFF_BOOTSTRAP_TOKEN` of at least 32 characters, and `MOUMANTAI_LOCAL_API_PORT` for the local API. Open `/order-requests` and enter the operator bootstrap token. None of these values uses a `VITE_` prefix. The facade is absent from `vite build` and refuses production configuration. `scripts/seed_frontend_order_requests.py` seeds synthetic demo requests into a disposable stack; the browser test is `frontend/e2e-order-request.mjs` and requires Playwright plus Chrome (`CHROME_PATH` can override its path).

## Owner decision and boundary

Orders Owner approved this exact synthetic-only facade in PR #114 and waived an additional P5 pre-implementation review. P5 review remains available on the Draft PR but is not a prerequisite for demo implementation. The server bootstrap is configured by the local operator through `MOUMANTAI_BFF_BOOTSTRAP_TOKEN`, separate from `MOUMANTAI_ISOLATED_E2E_KEY`. The manager and tenant are configured server side. Upstream DTOs, authorization, migrations and Core authority are unchanged. Reconciliation remains server-only. The browser never claims `REVIEWED` or `RESERVATION_UNKNOWN` is accepted.

## Validation after approval

Local evidence on 2026-10-25: migrated PostgreSQL 16 and worker; real Chrome review, accept, refresh and reject journey; 17 Orders HTTP tests against migrated PostgreSQL (including stale versions, tenant/staff denial, replay and 202 unknown); one real HTTP/worker P3-to-P4 same-Commitment test against migrated PostgreSQL; frontend typecheck, build and 1,235 Vitest tests pass. The direct browser journey showed the P3 link and timeline; its accepted fixture had no P3 recovery action, so its P4 intent list was correctly empty. The separate real HTTP/worker test verified a P4 `PENDING_P4_REVIEW` intent linked to the same accepted Commitment with `NOT_SENT`. Exact-head CI is pending after push.

After Main #115 merged, #114 synchronized it with a two-parent merge commit. The Main change introduces no new OrderRequest/P5/frontend DTO or registered C3 route. On the merged head, fresh Chrome runs passed both confirmed acceptance and a separate `202 RESERVATION_UNKNOWN` path. The latter retained the durable unknown receipt and idempotency key across refresh, displayed no accepted Commitment and offered no new acceptance action. Migrated PostgreSQL Orders and real HTTP/worker P3 suites passed 18 focused tests; frontend typecheck, 1,236 Vitest tests and build passed. C3 semantic production activation and P4 provider sends remain outside this facade.
