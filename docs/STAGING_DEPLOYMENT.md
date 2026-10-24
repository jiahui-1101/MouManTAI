# MouManTAI v2.2 staging deployment

Baseline audited: `0d04c73548683337f0ab4136d2c3a2e2459b55ed` (`origin/main`, 2026-10-25), integrated by normal merge commit `2ac24828ea1568356e5257fa44d22b779c31b7ad`. PR #115's C3/P1 Integration Foundation is included alongside #90, #96, and #95. This document describes a **synthetic, private staging** deployment. It does not assert a live provider or business E2E result.

## Architecture and readiness matrix

```text
HTTPS ingress with team access control (owner supplied)
  -> 127.0.0.1:8080 -> nginx SPA + same-origin /v1, /dev, /health proxy
                       -> FastAPI app.main:app
                       -> PostgreSQL 16, private Docker network
  -> provider webhook paths only when separately enabled and verified
outbox worker: python -m app.worker -> same PostgreSQL
one-shot migrate: preflight -> Alembic upgrade head -> head check
```

The repository README mentions Vercel and Render as hosting, but no deployment identifier or URL is recorded. The connected Vercel account returned no MouManTAI project on 2026-10-25. No Render access is available to this workstream. This Compose target is therefore the smallest reproducible local/host topology; a public host, DNS, TLS, secret store, and team access control must be supplied before shared staging is exposed. The Compose frontend binds to loopback only. The database and API have no host ports. Backend Python packages are exact-version pinned in `backend/requirements-staging.lock.txt`; frontend packages use `npm ci` and the committed package lock. Base images are pinned by digest.

| Component | Main baseline | Staging configuration | Gate |
|---|---|---|---|
| Database | PostgreSQL 16 Compose service | Dedicated `moumantai_staging` database and user; private volume | Fresh upgrade, version and indexes verified locally |
| Migrations | Alembic from `backend/migrations` | One-shot `migrate`, before API and worker | Single head and `current --check-heads` |
| API | `app.main:app`, `/health` | Private service, same-origin proxy | Startup, DB and authorization smoke |
| Outbox | `python -m app.worker` | Separate single worker | Startup and safe pending-event check |
| Channel polling | API lifecycle manager | Disabled initially by `*_AUTO_START=false` | Enable after credentials and provider authorization |
| Frontend | Vite React SPA | `npm ci` build, nginx fallback, relative API URLs | Build, deep link, no localhost in bundle |
| Ingress | Telegram, WhatsApp, Resend routes | No public endpoint until owner supplies HTTPS and access rules | Synthetic signature tests; real providers `NOT_RUN` |
| Identity | Synthetic header actor mapping | Synthetic data only, private team ingress | **Never use for public/customer traffic** |
| P1 Qwen/Gemini | Shared P1 Qwen-primary, Gemini technical-fallback boundary from #115 | `P1_AI_ENABLED=false`; no provider credentials passed | Mocked fallback and failure cases; live inference `NOT_RUN` |
| C3 intelligence | Deterministic intent/candidates, current P1 source reader, read-only handoffs from #115 | `MessageIntelligenceService.from_env()` has no semantic gateway | Exact source hash, account, evidence and association provenance; no independent provider loop |
| C3 semantic/review | Shared semantic task contract and durable review writer still need owner approval | Semantic gateway unwired | Live semantic classification `DISABLED`; no automatic business mutation |
| P4 outbound | Server authorization and transport flags | All provider outbound flags `false`; isolated E2E `0` | `NOT_SENT` must remain honest |

`/health` is liveness only; it does not query the database. The smoke procedure checks DB connectivity and Alembic separately. There is no dedicated ready endpoint in Main.

## Secrets and environment

Use [the placeholder template](../staging.env.example) as a key list. Keep the actual file outside the repository or in a deployment secret store. Use a unique staging password and URL-encode the password in `STAGING_DATABASE_URL`. The preflight checks that the URL targets `db/moumantai_staging` and that P1 shares that URL. Do not reuse development or production credentials. `.dockerignore` excludes local env files from build contexts.

| Variable | Scope | Purpose |
|---|---|---|
| `STAGING_DB_USER`, `STAGING_DB_PASSWORD` | host/DB | Dedicated staging PostgreSQL role |
| `STAGING_DATABASE_URL` | API, worker, migrate | psycopg URL; only `db/moumantai_staging` accepted |
| `STAGING_ORIGIN` | API | Exact HTTPS browser origin for CORS |
| `STAGING_LOCAL_PORT` | host | Loopback-only frontend port |
| `MOUMANTAI_SYNTHETIC_MODE=1`, `APP_ENV=synthetic`, `P4_RUNTIME_MODE=SYNTHETIC`, `P4_SYNTHETIC_TENANTS=synthetic_tenant_a` | API/worker | Explicit synthetic authority scope; no customer data |
| `MOUMANTAI_ISOLATED_E2E=0`, `P1_AI_ENABLED=false` | API/worker | Isolated mutations and live Qwen/Gemini inference disabled |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_BOT_ID`, `TELEGRAM_TENANT_ID`, `TELEGRAM_MODE`, `TELEGRAM_WEBHOOK_URL` | API secret store | Optional inbound Telegram; do not enable polling and webhook together |
| `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_TENANT_ID` | API secret store | Optional Meta inbound verification and account mapping |
| `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `RESEND_ACCOUNT_ID`, `RESEND_INBOUND_ADDRESSES`, `RESEND_TENANT_ID` | API secret store | Optional signed email inbound if configured/approved |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `GMAIL_MAILBOX_ACCOUNT_ID`, `GMAIL_REDIRECT_URI`, `GMAIL_TENANT_ID` | API secret store | Optional read-only Gmail polling/OAuth |
| `P1_AI_STAGES`, `P1_AI_ENDPOINT_URL`, `P1_AI_API_KEY`, `P1_AI_ENDPOINT_MODE`, `P1_AI_TIMEOUT_SECONDS` | API secret store | P1 Qwen configuration, reserved for approved future activation; omitted from current Compose |
| `P1_GEMINI_API_KEY`, `P1_GEMINI_MODEL`, `P1_GEMINI_TIMEOUT_SECONDS`, `P1_GEMINI_MAX_RETRIES` | API secret store | P1 technical fallback configuration, reserved for approved future activation; omitted from current Compose |
| `TELEGRAM_OUTBOUND_ENABLED=false`, `WHATSAPP_OUTBOUND_ENABLED=false`, `RESEND_OUTBOUND_ENABLED=false` | API/worker | Provider sends disabled |

Never put server credentials in `VITE_*` variables. The staging bundle uses same-origin relative URLs; `VITE_API_BASE_URL` is empty. Main still has header-based synthetic identity. A team access gate at the HTTPS ingress is required before any internet exposure; this does not turn it into production authentication. Restrict staging to synthetic data and test accounts.

## Local deployment and verification

Use a private env file whose path is passed to `--env-file`. The committed template values are placeholders and must never be used for shared staging. The release SHA should be recorded with every deployment. Run from repository root:

```sh
docker compose --env-file /secure/path/staging.env -f docker-compose.staging.yml config --quiet
docker compose --env-file /secure/path/staging.env -f docker-compose.staging.yml build
docker compose --env-file /secure/path/staging.env -f docker-compose.staging.yml up -d db migrate api worker frontend
docker compose --env-file /secure/path/staging.env -f docker-compose.staging.yml ps
docker compose --env-file /secure/path/staging.env -f docker-compose.staging.yml exec -T api alembic -c alembic.ini heads
docker compose --env-file /secure/path/staging.env -f docker-compose.staging.yml exec -T api alembic -c alembic.ini current --check-heads
docker compose --env-file /secure/path/staging.env -f docker-compose.staging.yml exec -T api python scripts/staging_smoke.py
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/overview >/dev/null
```

The `migrate` service deliberately does not seed data automatically. Seed only synthetic fixtures after the database and authority scope have been confirmed. Verify persisted reads, tenant denial, unauthorized denial, duplicate ingestion, and P4 `NOT_SENT` state with task-owned fixtures. Check browser bundle requests and deep links through the actual HTTPS ingress. The `frontend` healthcheck proves static nginx response, not business readiness. Run existing #95 orchestration, P2/P3, and channel fixture suites before promoting the release.

For logs use `docker compose ... logs --since=10m api worker migrate frontend` and inspect failures without copying secrets. The default Docker log driver retains local logs; configure host rotation/collection before long-lived shared use. The worker is a single instance; do not scale it without reviewing outbox claiming semantics. API lifecycle polling must likewise remain one replica when enabled.

## Webhook handoff

| Provider | Route | Current requirement | Initial status |
|---|---|---|---|
| Telegram | `POST /v1/channels/telegram/webhook` | HTTPS, bot account/tenant assignment, `X-Telegram-Bot-Api-Secret-Token` | Synthetic invalid/valid fixture only; real `NOT_RUN` |
| WhatsApp | `GET/POST /v1/channels/whatsapp/webhook` | HTTPS, challenge token, HMAC `X-Hub-Signature-256`, phone account/tenant match | Synthetic invalid/valid fixture only; real `NOT_RUN` |
| Resend | `POST /v1/channels/resend/webhook` | Signed Svix headers, configured receiving address and approved canonical provider contract | Real `NOT_RUN` |
| Gmail | OAuth callback and read-only polling | Authorized test mailbox and refresh token; no inbound webhook | Real `NOT_RUN` |

Keep provider dashboards and subscriptions unchanged until owner authorization. At ingress, bypass the **team login gate only for exact provider webhook paths**, while retaining application signature/secret validation and rate/body limits. Do not expose `/v1/channels/poll` or `/v1/channels/status` publicly. A successful synthetic fixture never counts as real provider delivery.

Main's channel configuration rejects tenant IDs beginning with `synthetic` for a real provider assignment. The initial Compose environment also does not pass provider credentials or enable channel polling. A provider activation therefore needs an approved test-tenant mapping, secret-store wiring, a reviewed Compose change, and a new staging validation run. Do not add real credentials to the current synthetic baseline to work around this boundary.

## Release, backup, rollback

The manual [staging release check](../.github/workflows/staging-release-check.yml) requires a reviewed Main ancestor SHA, serializes runs, builds a disposable stack, and checks migrations, health and SPA routing. Configure required reviewers on the GitHub `staging` environment; naming the environment in YAML alone does not establish a reviewer gate. It does not deploy to the shared host. For shared deployment, a single approved operator obtains a host lock, checks `origin/main` and CI on the reviewed SHA, records the old SHA and DB revision, and takes a PostgreSQL backup before migrations. Deploy only a reviewed Main commit; do not use #114's unmerged BFF branch as shared baseline. Use the exact commands above, verify head/API/worker/frontend and synthetic records, then record SHA and results. Do not run two releases concurrently.

Example backup from the private DB service (store the resulting file securely, outside Git):

```sh
docker compose --env-file /secure/path/staging.env -f docker-compose.staging.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > /secure/backups/moumantai-staging.dump
```

Rollback an application image/checkout to the prior reviewed SHA **only when its schema is compatible**. For an incompatible migration, stop API and worker, restore the pre-release dump into the isolated staging database under an approved maintenance window, then deploy the prior SHA and verify. Do not blindly run `alembic downgrade` on shared data; migration `0018_c1_scoped_message_parent` explicitly guards a non-restorable uniqueness case. Never restore a staging dump into production. Preserve the failed release logs and SHA for diagnosis.

PR #115 incorporates the C3/P1 foundation, but does not authorize provider activation. Before any live semantic test, obtain the shared task contract, scoped test credentials, privacy and business approval, then redeploy and verify evidence/review gates. After #114 merge, rebuild the frontend, verify its secure facade and browser review/accept flow against the same-Commitment recovery/communication timeline, and run browser E2E. #114 remains outside this baseline.

## Current decision

Infrastructure Ready: **NO-GO for shared HTTPS staging** until a host, DNS/TLS, private access gate, secret storage, and deployment owner are provided and the live gates above pass. Local Compose validation is separately recorded in the team log. Full Business Demo Ready: **NO-GO** until #114, the C3 semantic/review and P4 authorization contracts, and complete browser/provider tests pass.
