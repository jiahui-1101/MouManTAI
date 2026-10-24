# C2 real provider adapters

Status: final C1 integration pass, 2026-10-25, existing PR [#96](https://github.com/jiahui-1101/MouManTAI/pull/96), branch `codex/c2-real-provider-adapters`. Frozen Main is `1c34b8dbcdd944b60c856ceb7a5dd7ada890564f` (merged C1 #90); prior C2 HEAD was `ef27d8a61263a3ebe26399d40ea0371d88eb7769`. No replacement PR. Actual final publication HEAD and its exact-head CI are recorded in the PR description after push. Validated code commit is recorded below after local verification.

These adapters reuse C1 `RawMessageEnvelope`, native reply framing, existing P1 `MessageRepository` and `p1_dev.inbound_messages` / `attachments`. Five conflicts in config/Gmail/router/Telegram/WhatsApp were reconciled block by block. No shared schema, migration, Core/Orders/P4 authority, OCR, #95, #102, #103 or frontend business code changed relative to frozen Main. Main removed root requirements; v2.2 requirements remain in `docs/requirements/v2.2/`.

**Partial / owner gates remain:** Telegram/WhatsApp/Gmail consume the merged C1 contract. Resend parsing and transports are fixture-tested, but **canonical Resend ingestion is blocked** with `503 RESEND_CANONICAL_PROVIDER_CONTRACT_UNAPPROVED`, before retrieval/attachment/message writes. Its parsed envelope remains UNVERIFIED to prevent direct canonical-ingestion bypass. Current P1 derives EMAIL as GMAIL_API; the additive RESEND source-provider/constraint proposal has been [requested from Jiahui](https://github.com/jiahui-1101/MouManTAI/pull/96#issuecomment-6388431518) and is not implemented without approval. No Resend source is silently labelled Gmail.

Migration graph: unchanged sole head `0024_merge_c1_ah`. No new migration is needed for authorized C2 adapter-only changes. Shared Resend schema work requires an actual entity reuse mapping and designated approval first. #95's owner must reconcile its own migration branch separately.

Full operator steps, environment/readback/security checks and cleanup: [provider E2E runbook](./C2_PROVIDER_E2E_RUNBOOK.md). Minimal P4/contact/consent/dispatch/durable receipt and Resend schema proposal: [pending owner contract](./contracts/C2_P4_PROVIDER_BOUNDARY_PROPOSAL_2026-10-25.md).

## Provider scope and evidence

| Provider capability | Implementation | Evidence tier |
|---|---|---|
| Telegram webhook authentication, inbound messages, native parent reply IDs, photo/document retrieval, outbound text/replies | Existing P1 ingress extended; outbound is an internal adapter guarded by enable flag and test-recipient allowlist | `VALIDATED` with HTTP fixtures; no Telegram live E2E |
| WhatsApp Cloud webhook HMAC, account ID check, inbound text/media, quoted parent IDs, delivery callback normalization, text/template sends | Existing P1 ingress extended; status receipts are returned/normalized but are not durably stored; outbound is internal and allowlisted | `VALIDATED` with HTTP fixtures; no Meta test-number live E2E |
| Resend inbound webhook/API parsing, signed attachment retrieval, outbound email with RFC reply headers, provider idempotency key | C1-compatible parsing; canonical ingestion explicitly BLOCKED pending approved source-provider contract; outbound remains internal | `FIXTURE TESTED ONLY`; canonical provider integration and live E2E BLOCKED |
| Gmail inbound MIME parsing and attachment retrieval, exact `In-Reply-To` association | Existing Gmail OAuth/polling retained and hardened; OAuth scope remains `gmail.readonly` | Existing fixtures plus C2 parent-association fixtures; no Gmail live E2E |
| Gmail outbound | Not implemented. Resend is the email outbound adapter; Gmail currently has read-only OAuth consent and P4 only supports mock channel types. | `NOT_RUN` |
| P4 authorization/send workflow integration | Not connected. Existing P4 `OutboundProvider`, one-submission durable intent, authorization and audit remain unchanged and mock-channel-only pending contract review. | `NOT_RUN` |

`ACCEPTED` means provider acceptance, not delivery. WhatsApp/Resend status observations are normalized but not durable P4 receipts. C1 retains provider-account/native IDs, exact parent, RFC Message-ID/In-Reply-To/References, attachment source IDs, timestamps and authentication provenance. Telegram native parent IDs are not prefixed delivery aliases; Gmail threadId is not an RFC parent; References alone never asserts an exact parent. Existing canonical tenant/provider/account/native unique keys and late-parent reconciliation remain authoritative. Resend's native email_id remains separate from its RFC Message-ID, but its ingestion stays blocked pending truthful provider attribution.

Telegram token/account and environment-alias mismatches fail closed. WhatsApp verifies the original raw-body HMAC and rejects a different parsed payload. Gmail rechecks the OAuth profile before reusing cached mailbox/cursor state and refuses state bound to another account; use a dedicated state file for each provider account. Existing manual/human associations and immutable original evidence are not rewritten by adapter integration.

All outbound transports default to disabled. To exercise them, an operator must explicitly enable the provider and configure test recipients. This code was not used to send a message, register a provider webhook, or contact an external provider with credentials.

Real provider readiness requires a server-configured tenant assignment. The legacy `synthetic_tenant_a` fallback and any `synthetic*` tenant ID cannot enable provider polling, webhook ingestion, or outbound transport. Set the provider-specific `*_TENANT_ID` to the authorized tenant, or set the existing `P1_DEV_TENANT_ID` fallback to a non-synthetic tenant in a controlled environment; never take tenant scope from an incoming provider payload.

## Shared transport behavior

- `CHANNEL_REQUEST_TIMEOUT_SECONDS` defaults to 10 seconds and accepts 1–30 seconds; connect timeout is capped at 3 seconds.
- Safe `GET` reads retry once only on a network failure or HTTP 502/503/504. Outbound `POST` requests are not automatically retried. A timeout after a POST returns `UNKNOWN`; callers must check provider status before taking a deliberate retry action.
- The internal send gate binds each idempotency key to a request fingerprint and caches `ACCEPTED`, `REJECTED`, and `UNKNOWN` outcomes in memory, up to 4096 entries per adapter process. A process restart or oldest-entry eviction forgets prior keys; this is a fixture/internal duplicate-send guard, not durable storage. P4 must own durable send intent before production integration.
- Resend additionally receives the provider-supported `Idempotency-Key` on `/emails`. Telegram has no send idempotency primitive. WhatsApp sends `biz_opaque_callback_data` to correlate status callbacks; that field does not make the Meta send API idempotent.
- Provider errors are reduced to bounded classifications (`AUTHENTICATION`, `RATE_LIMITED`, `TRANSIENT`, `PERMANENT`, `UNKNOWN`) and safe codes. Tokens, message bodies, signed attachment URLs and raw provider error bodies are not logged.
- Attachments are size-bounded, content-validated by the existing P1 validator, and saved using stable provider-derived evidence IDs so webhook re-delivery does not produce random attachment references.
- Webhook bodies are read incrementally and rejected as soon as the configured 2 MiB limit is crossed. WhatsApp HMAC validation happens against the raw bytes before JSON parsing.

## Telegram setup

Create a bot with BotFather, keep its token in a secret store, and configure a public HTTPS endpoint for `/v1/channels/telegram/webhook`. Register the webhook with Telegram’s `setWebhook` API using the same secret configured below. The adapter’s `set_webhook` method now requires both HTTPS and a valid secret token. Configure polling mode instead of webhook mode when using `getUpdates`; Telegram does not allow both concurrently.

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot API credential |
| `TELEGRAM_MODE` | `webhook` or `polling` |
| `TELEGRAM_WEBHOOK_URL` | Public HTTPS callback URL for operator setup |
| `TELEGRAM_WEBHOOK_SECRET` | Shared value sent as `X-Telegram-Bot-Api-Secret-Token` |
| `TELEGRAM_BOT_ACCOUNT_ID` | Optional configured bot ID used to scope native message IDs when several bots share a tenant |
| `TELEGRAM_TENANT_ID` | Server-side P1 tenant assignment |
| `TELEGRAM_OUTBOUND_ENABLED` | Must be `true` to enable internal sends; default `false` |
| `TELEGRAM_TEST_RECIPIENT_IDS` | Comma-separated chat IDs that the internal transport may contact |
| `TELEGRAM_AUTO_START`, `TELEGRAM_POLL_INTERVAL`, `TELEGRAM_POLL_TIMEOUT` | Existing polling worker controls |

Telegram replies use `reply_parameters.message_id`; inbound `reply_to_message.message_id` is normalized to the same provider ID scheme. The bot can message only a configured allowlisted chat, and Telegram still requires that a user has initiated the conversation or otherwise made the bot reachable.

## WhatsApp Cloud API setup

Use Meta’s official Cloud API test assets first. Add the test recipient to the app’s allowed test recipients, subscribe the WhatsApp Business Account to the `messages` webhook field, and configure the callback URL and verify token. The POST callback must include Meta’s `X-Hub-Signature-256` HMAC over the exact raw body. The adapter checks `metadata.phone_number_id` against the configured phone number ID. The default Graph API base is pinned to `https://graph.facebook.com/v26.0` for the current implementation date; set `WHATSAPP_API_BASE_URL` explicitly when upgrading after checking Meta’s version schedule.

| Variable | Purpose |
|---|---|
| `WHATSAPP_PHONE_NUMBER_ID` | Configured Cloud API sender account ID |
| `WHATSAPP_ACCESS_TOKEN` | Meta access token with WhatsApp messaging permission |
| `WHATSAPP_APP_SECRET` | HMAC verification secret |
| `WHATSAPP_VERIFY_TOKEN` | GET webhook challenge token |
| `WHATSAPP_API_BASE_URL` | Versioned Graph API base (default v26.0) |
| `WHATSAPP_TENANT_ID` | Server-side P1 tenant assignment |
| `WHATSAPP_OUTBOUND_ENABLED` | Must be `true` to enable internal sends; default `false` |
| `WHATSAPP_TEST_RECIPIENT_IDS` | Comma-separated E.164 digits for configured test recipients |
| `WHATSAPP_APPROVED_TEMPLATES` | Comma-separated pre-approved template names allowed outside a customer-service window |

Free-form text sends require an authoritative service-window expiry supplied by the future approved caller. Template sends require a configured approved template and provider-side approval. These methods are not HTTP-exposed and do not authorize a business decision by themselves.

## Resend email setup

Resend is the preferred email path for new inbound integration. Enable inbound on a Resend-provided `*.resend.app` address or a configured custom domain. Register a webhook for `email.received` at `/v1/channels/resend/webhook`; store the webhook signing secret. The handler verifies the Svix signature over the raw body with a five-minute timestamp window, then retrieves message content and attachment metadata from the receiving API. Attachment downloads are restricted to the HTTPS `inbound-cdn.resend.com` host.

| Variable | Purpose |
|---|---|
| `RESEND_API_KEY` | Resend receiving and sending API credential |
| `RESEND_WEBHOOK_SECRET` | Svix signing secret (`whsec_...`) |
| `RESEND_TENANT_ID` | Server-side P1 tenant assignment |
| `RESEND_INBOUND_ADDRESSES` | Comma-separated inbox addresses bound to this tenant |
| `RESEND_API_BASE_URL` | Resend API base (default `https://api.resend.com`) |
| `RESEND_MAX_ATTACHMENT_BYTES` | Attachment limit up to the existing 10 MiB P1 validator limit |
| `RESEND_OUTBOUND_ENABLED` | Must be `true` to enable internal sends; default `false` |
| `RESEND_TEST_RECIPIENTS` | Comma-separated recipient addresses permitted by the internal transport |
| `RESEND_VERIFIED_FROM_EMAIL` | Operator-configured sender already verified in Resend |
| `RESEND_REPLY_TO_EMAIL` | Optional operator-controlled Reply-To address |

The provider adapter accepts one explicit recipient, validates it against the test allowlist, and uses only the configured verified sender. It does not derive the outbound recipient from an inbound `Reply-To`. Replies include validated RFC `In-Reply-To` and `References` headers. Resend’s provider idempotency key is sent on `/emails`; acceptance is not delivery confirmation.

## Gmail existing support

Gmail continues to use its existing read-only OAuth flow and incremental inbox poller. MIME `From` determines the inbound sender identity; an inbound `Reply-To` header is not treated as authenticated identity. Attachments are fetched through Gmail’s authenticated attachment endpoint and retained in the existing P1 evidence store. `In-Reply-To` and `References` are parsed to preserve exact parent association while Gmail `threadId` remains the conversation reference. Gmail outbound is deliberately not enabled by this adapter: the current OAuth scope is `gmail.readonly`, and the approved P4 provider path still accepts mock channels only.

Existing Gmail setup variables remain: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` or `GMAIL_ACCESS_TOKEN`, optional `GMAIL_CREDENTIALS_FILE`, `GMAIL_TENANT_ID`, `GMAIL_QUERY`, `GMAIL_API_BASE_URL`, and `GMAIL_AUTO_START`. The OAuth scope remains `https://www.googleapis.com/auth/gmail.readonly`.

## Validation and live-evidence boundary

Final local adapter source checkpoint (2026-10-25): **707 passed, 3 skipped, 24 warnings**. Includes all v2.2 tests, C1 persistence/framing/repository/migrations, new HTTP→PostgreSQL C2 tests, Telegram/WhatsApp/Gmail routes and P4 synthetic route compatibility. The three skips are PostgreSQL-gated v2.2 cases when the broad portable command has no `TEST_DATABASE_URL`; no test was removed. The authoritative PostgreSQL run at the preceding integration checkpoint had **1039 passed, zero skipped, 42 warnings**; final post-review exact-head authoritative coverage is reported by CI after push. New security tests were demonstrated failing before fixes and independently reviewed; **9 passed** in the final review rerun. Full commands below were run from `backend/` with `MOUMANTAI_SYNTHETIC_MODE=1`, `P1_AI_ENABLED=false`, both polling auto-start flags false and P1's disposable test URL on port 15473. A unique external `--basetemp` avoids the host's existing shared pytest-directory ACL failure.

```text
python -m pytest -q -o addopts= --basetemp=<unique-task-temp> tests/v2_2 app/context/tests/test_c2_canonical_integration.py app/context/tests/test_c1_completion_persistence.py app/context/tests/test_c1_adapter_framing.py app/context/tests/test_c1_repository_regression.py app/context/tests/test_postgres_repository.py app/context/tests/test_p1_alembic_migration.py app/context/tests/test_reply_framing.py app/context/tests/test_telegram_channel.py app/context/tests/test_whatsapp_channel.py app/context/tests/test_gmail_channel.py app/context/tests/test_channel_manager_and_routes.py app/context/tests/test_real_provenance_and_ai_pipeline.py app/context/tests/test_channel_e2e_integration.py app/communication/tests/test_route_integration.py --tb=short

REQUIRE_POSTGRES=1 TEST_DATABASE_APPROVED=1 TEST_DATABASE_URL=<p4_test_c2_final_20261025_test> TEST_MIGRATION_DATABASE_URL=<p4_test_c2_migration_20261025_test> P4_TEST_DATABASE_URL=<suite-url> P1_DATABASE_URL=<suite-url> python -m pytest tests -q -o addopts= --basetemp=<unique-task-temp> --tb=short --junitxml=<task-temp>/c2-pg-final.xml

python -m ruff check --select F,I app/context/channels/config.py app/context/channels/gmail.py app/context/channels/manager.py app/context/channels/provider_transport.py app/context/channels/resend.py app/context/channels/router.py app/context/channels/telegram.py app/context/channels/whatsapp.py tests/v2_2/test_c2_provider_adapters.py tests/v2_2/test_c2_integration_security.py app/context/tests/test_c2_canonical_integration.py
python -m ruff check tests/v2_2/test_c2_integration_security.py app/context/tests/test_c2_canonical_integration.py
python -m compileall -q app/context/channels
python -m alembic heads
git diff --check
```

Static checks above passed; new files are formatted. A broad channel-directory Ruff scan additionally found two unchanged Main diagnostics (`state.py` unused os and `worker.py` undefined Any); those unrelated files were not changed. The same catalog alignment test still **fails (1 failed, 62 deselected)** outside CI on C2 and the frozen Main source: `python -m pytest -q -o addopts= app/context/tests/test_deterministic_extraction.py -k test_catalog_is_provisional_fixture_aligned_and_tenant_scoped --tb=short`. Test/catalog/extractor sources match frozen Main exactly. Prior C1 report contains the clean Main reproduction; P1 owner disposition remains pending. No assertion or catalog policy was weakened.

Independent review reproduced and then confirmed fixes for Gmail same-filename inline attachment evidence overwrite and verify/startup account-rebinding of cached cursors. Evidence keys now include tenant/provider/account/native source/MIME part/content digest; changed bytes create new evidence rather than overwrite. Resend callback correlation uses native email_id, never an RFC Message-ID. Final merge readiness remains **BLOCKED** by unapproved shared Resend/P4 contracts, final-head owner review and explicit merge authorization; fixture success is not feature approval or live integration.

Fixture tests use HTTPX `MockTransport` and fake provider credentials. They validate payloads, signatures, media retrieval, attachment evidence persistence, reply IDs, outbound request bodies, recipient restrictions, error classes, timeout handling and safe retry policy. They do not prove provider account setup, webhook reachability, Meta test recipient registration, Resend domain verification, real delivery, or provider status callbacks. Those need an explicitly approved operator-run E2E against configured test recipients.

Primary provider references:

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Meta’s official WhatsApp Cloud API Postman workspace](https://www.postman.com/meta/whatsapp-business-platform/collection/wlk6lh4/whatsapp-cloud-api)
- [Resend inbound email](https://resend.com/features/inbound)
- [Resend retrieve received email](https://resend.com/docs/api-reference/emails/retrieve-received-email)
- [Resend retrieve received attachment](https://resend.com/docs/api-reference/emails/retrieve-received-email-attachment)
- [Resend webhook signature verification](https://resend.com/changelog/managing-webhooks-via-api)
- [Gmail send and threading contract](https://developers.google.com/workspace/gmail/api/guides/threads) (reference only; Gmail sending remains disabled here)
