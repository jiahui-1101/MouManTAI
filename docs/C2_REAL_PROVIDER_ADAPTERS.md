# C2 real provider adapters

Status: implementation branch `codex/c2-real-provider-adapters`, based on `origin/main` at `f6eca1ac93b382c2ffe68965e18b55f12e03d322` (24 Oct 2026). These adapters use the existing P1 `MessageRepository` and P1 `inbound_messages` / `attachments` records. No migration, alternate persistence, OCR, Backend A–H engine, or canonical shared API change is included.

## Provider scope and evidence

| Provider capability | Implementation | Evidence tier |
|---|---|---|
| Telegram webhook authentication, inbound messages, native parent reply IDs, photo/document retrieval, outbound text/replies | Existing P1 ingress extended; outbound is an internal adapter guarded by enable flag and test-recipient allowlist | `VALIDATED` with HTTP fixtures; no Telegram live E2E |
| WhatsApp Cloud webhook HMAC, account ID check, inbound text/media, quoted parent IDs, delivery callback normalization, text/template sends | Existing P1 ingress extended; status receipts are returned/normalized but are not durably stored; outbound is internal and allowlisted | `VALIDATED` with HTTP fixtures; no Meta test-number live E2E |
| Resend inbound webhook/API receive, signed attachment retrieval, outbound email with RFC reply headers, provider idempotency key | New provider adapter; inbound writes only through existing P1 repository; outbound remains an internal transport | `VALIDATED` with HTTP fixtures; no Resend live E2E |
| Gmail inbound MIME parsing and attachment retrieval, exact `In-Reply-To` association | Existing Gmail OAuth/polling retained and hardened; OAuth scope remains `gmail.readonly` | Existing fixtures plus C2 parent-association fixtures; no Gmail live E2E |
| Gmail outbound | Not implemented. Resend is the email outbound adapter; Gmail currently has read-only OAuth consent and P4 only supports mock channel types. | `NOT_RUN` |
| P4 authorization/send workflow integration | Not connected. Existing P4 `OutboundProvider`, one-submission durable intent, authorization and audit remain unchanged and mock-channel-only pending contract review. | `NOT_RUN` |

`ACCEPTED` means the provider accepted an outbound request, not that it was delivered. WhatsApp and Resend status callbacks are normalized for caller visibility but are not persisted because no approved shared/P4 status contract exists on this branch. C1’s unmerged schema work was not copied. Current P1 `RawMessageEnvelope` stores channel, tenant, provider message ID, conversation/thread reference, exact parent reference, timestamps, text and attachment evidence. It cannot persist all original provider account IDs and arbitrary RFC headers; those require the separately reviewed C1 persistence contract.

All outbound transports default to disabled. To exercise them, an operator must explicitly enable the provider and configure test recipients. This code was not used to send a message, register a provider webhook, or contact an external provider with credentials.

## Shared transport behavior

- `CHANNEL_REQUEST_TIMEOUT_SECONDS` defaults to 10 seconds and accepts 1–30 seconds; connect timeout is capped at 3 seconds.
- Safe `GET` reads retry once only on a network failure or HTTP 502/503/504. Outbound `POST` requests are not automatically retried. A timeout after a POST returns `UNKNOWN`; callers must check provider status before taking a deliberate retry action.
- The internal send gate binds each idempotency key to a request fingerprint and caches `ACCEPTED`, `REJECTED`, and `UNKNOWN` outcomes for the lifetime of the adapter process. This is a duplicate-send guard, not durable storage; P4 must own durable send intent before production integration.
- Resend additionally receives the provider-supported `Idempotency-Key` on `/emails`. Telegram has no send idempotency primitive. WhatsApp sends `biz_opaque_callback_data` to correlate status callbacks; that field does not make the Meta send API idempotent.
- Provider errors are reduced to bounded classifications (`AUTHENTICATION`, `RATE_LIMITED`, `TRANSIENT`, `PERMANENT`, `UNKNOWN`) and safe codes. Tokens, message bodies, signed attachment URLs and raw provider error bodies are not logged.
- Attachments are size-bounded, content-validated by the existing P1 validator, and saved using stable provider-derived evidence IDs so webhook re-delivery does not produce random attachment references.

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

Fixture tests use HTTPX `MockTransport` and fake provider credentials. They validate payloads, signatures, media retrieval, attachment evidence persistence, reply IDs, outbound request bodies, recipient restrictions, error classes, timeout handling and safe retry policy. They do not prove provider account setup, webhook reachability, Meta test recipient registration, Resend domain verification, real delivery, or provider status callbacks. Those need an explicitly approved operator-run E2E against configured test recipients.

Primary provider references:

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Meta’s official WhatsApp Cloud API Postman workspace](https://www.postman.com/meta/whatsapp-business-platform/collection/wlk6lh4/whatsapp-cloud-api)
- [Resend inbound email](https://resend.com/features/inbound)
- [Resend retrieve received email](https://resend.com/docs/api-reference/emails/retrieve-received-email)
- [Resend retrieve received attachment](https://resend.com/docs/api-reference/emails/retrieve-received-email-attachment)
- [Resend webhook signature verification](https://resend.com/changelog/managing-webhooks-via-api)
- [Gmail send and threading contract](https://developers.google.com/workspace/gmail/api/guides/threads) (reference only; Gmail sending remains disabled here)
