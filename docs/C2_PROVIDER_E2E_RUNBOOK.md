# C2 controlled provider E2E runbook

Status on 2026-10-25: all four providers **FIXTURE TESTED ONLY**; `LIVE_PROVIDER_E2E = BLOCKED / NOT VERIFIED`. Process configuration inspection found no configured Telegram account/webhook/recipients, WhatsApp account/recipients, Resend inbox/outbound or Gmail OAuth mailbox. Outbound flags were all false. This does not claim accounts do not exist elsewhere. No provider credentials were exercised and no deployment or live message was created.

Use a disposable test database, a non-synthetic server-owned test tenant, an explicitly operator-approved provider account and test recipients. Record who authorized the test, exact configuration version, UTC time and code HEAD. Store secrets only in the deployment secret store; never paste tokens, private recipient addresses, message bodies or signed media URLs into PRs/logs. Public HTTPS reachability and console configuration are operator prerequisites, not established by fixture tests.

## Safe starting configuration

Keep these false until an approved P4 path and test authorization exist:

```powershell
$env:TELEGRAM_OUTBOUND_ENABLED = 'false'
$env:WHATSAPP_OUTBOUND_ENABLED = 'false'
$env:RESEND_OUTBOUND_ENABLED = 'false'
$env:TELEGRAM_AUTO_START = 'false'
$env:GMAIL_AUTO_START = 'false'
```

Start the existing app only with a reviewed disposable PostgreSQL configuration. Do not run the live deployment or set provider variables as part of automated tests. Fixture verification uses the commands in `C2_REAL_PROVIDER_ADAPTERS.md`; it makes no real provider call.

## Telegram

1. In BotFather create/choose an authorized test bot. Configure `TELEGRAM_BOT_TOKEN`, `TELEGRAM_TENANT_ID`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET` and `TELEGRAM_BOT_ID` (C2 alias `TELEGRAM_BOT_ACCOUNT_ID` supported). Explicit bot ID must match the numeric token prefix; conflicting aliases are rejected.
2. Choose webhook mode (`TELEGRAM_MODE=webhook`) or polling, not both. For webhook mode, deploy `/v1/channels/telegram/webhook` behind HTTPS; operator registers the exact URL and secret using Telegram's `setWebhook`. Never print the token-bearing URL. For polling, explicitly start the approved worker only after webhook conflict review. Use a dedicated state file per provider account.
3. In the authorized chat, send a harmless non-commercial test text, reply to it, then send a small PDF/photo. Capture actual Bot API update/message IDs, bot ID and chat ID in a private evidence manifest. Read PostgreSQL below; the child parent must be the native message ID, scoped to bot/chat.
4. Replay the original signed/secret-authenticated callback; the canonical message count must not grow. Omit/alter the secret and confirm 403/no persistence. Quote an absent parent and confirm UNRESOLVED; later ingest that exact parent and confirm REFERENCE_MATCH. Cross-chat/account/tenant inputs must not resolve.
5. Outbound remains BLOCKED by pending P4 contract. After P4 is approved, configure `TELEGRAM_TEST_RECIPIENT_IDS`, approve an exact P4 draft and authorize one controlled send. Capture actual provider acceptance ID and observe receipt in the test chat; do not fabricate delivered/read callback evidence. Timeout/UNKNOWN must not resend automatically.
6. Cleanup: operator removes test webhook/stops polling as appropriate, revokes temporary credentials and restores flags to false. Preserve approved evidence under the retention policy; do not delete immutable canonical rows as casual cleanup.

References: [Telegram Bot API](https://core.telegram.org/bots/api), including setWebhook, getUpdates, getFile and sendMessage.

## WhatsApp Cloud API

1. In Meta's developer console select the authorized app, test WABA/phone ID and approved test recipient. Subscribe `messages` callbacks to public HTTPS `/v1/channels/whatsapp/webhook`; complete GET verification with the configured token.
2. Configure `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_API_BASE_URL` and `WHATSAPP_TENANT_ID`. Verify the configured Graph API version against the provider console before live use; defaults are not proof of current account entitlement.
3. Send a test text, quote its exact native `wamid`, and attach a small supported PDF/image. Capture actual signed callback evidence/digest and provider media IDs privately. Verify provider account/native IDs, timestamps, attachment hash and exact parent in PostgreSQL.
4. Replay callbacks and verify no duplicate message. Alter raw body/HMAC or phone ID and confirm rejection with no source/attachment write. Test unsupported media and retrieval failure without claiming successful evidence extraction. Callback statuses must not be ingested as new customer messages.
5. Outbound remains BLOCKED pending P4 approval. Future controlled sends additionally require `WHATSAPP_OUTBOUND_ENABLED`, `WHATSAPP_TEST_RECIPIENT_IDS`, an authoritative current service-window expiry or configured `WHATSAPP_APPROVED_TEMPLATES`, and approved P4 intent. Capture actual acknowledgement and authenticated status events separately. HTTP acceptance is not delivered/read.
6. Cleanup: restore flags, stop test subscription where appropriate and revoke temporary tokens. Keep private receipt evidence and canonical retention intact.

Reference: [Meta WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/).

## Resend inbound / outbound email

1. Configure an approved receiving domain/inbox and separately verified sending domain in Resend. Configure a signed `email.received` webhook at HTTPS `/v1/channels/resend/webhook` and approved status events as supported. Store `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `RESEND_TENANT_ID`, `RESEND_ACCOUNT_ID` (receiving mailbox), `RESEND_INBOUND_ADDRESSES` and optional `RESEND_API_BASE_URL`/`RESEND_MAX_ATTACHMENT_BYTES` server-side. The account mailbox must be in the configured inbox allowlist.
2. **Inbound persistence is currently blocked**, even with valid signatures: `503 RESEND_CANONICAL_PROVIDER_CONTRACT_UNAPPROVED`. Verify no canonical message or attachment is created. Jiahui's approved additive source-provider contract must land before continuing a real inbound test; do not manually relabel an email as Gmail or bypass the guard.
3. Once that contract is approved/implemented, send a controlled email, exact RFC reply and small attachment to the test inbox. Capture native `email_id`, RFC Message-ID/In-Reply-To/References and Svix event ID privately; verify webhook raw-body signature, API-retrieved ID/recipient routing and canonical provider RESEND. Duplicate/late-parent behavior must match C1. References alone must not establish an exact parent.
4. Test wrong signature/stale timestamp, malformed/duplicate headers, missing native/RFC ID, wrong receiving account, unsafe Reply-To and attachment CDN/size failures. Fixture-only tests do not prove domain or webhook readiness.
5. Outbound remains BLOCKED pending P4. Future approved configuration uses `RESEND_VERIFIED_FROM_EMAIL`, optional `RESEND_REPLY_TO_EMAIL`, `RESEND_TEST_RECIPIENTS` and the disabled-by-default flag. Send only through approved P4 intent. Capture actual provider ID/Idempotency-Key and authenticated status receipt. Resend sending and Gmail reading are separate capabilities.
6. Cleanup: disable test webhooks/revoke temporary keys as approved and restore outbound false; preserve source/receipt evidence under the owner retention policy.

References: [received email API](https://resend.com/docs/api-reference/emails/retrieve-received-email), [webhook verification](https://resend.com/docs/webhooks/verify-webhooks-requests).

## Gmail OAuth inbound only

1. In the Google Cloud console enable Gmail API and configure OAuth consent/test user and redirect URI. Authorize only `gmail.readonly`; configure `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` (or controlled access token), `GMAIL_REDIRECT_URI`, `GMAIL_TENANT_ID`, `GMAIL_ACCOUNT_EMAIL`, query/poll settings and optional credentials-file path securely.
2. Use the existing OAuth authorize/callback routes. Verify the current token's profile matches the configured mailbox; a cached identity does not replace this check. Dedicate the state file to that account; mailbox rotation must not inherit another account's cursor/seen-ID cache.
3. Send a harmless email, reply with an exact RFC In-Reply-To and attach a small PDF/image. Trigger one approved poll. Capture actual Gmail message ID, threadId, RFC IDs and mailbox privately. PostgreSQL must keep Gmail native/thread IDs separate from RFC parent IDs. An untrusted Reply-To never replaces the original sender or verifies a human contact.
4. Poll again and confirm no duplicate. Test revoked/incorrect OAuth, account mismatch, missing/malformed RFC data and failed/oversized attachment retrieval. Preserve explicit uncertainty; no Gmail outbound is implemented or authorized.
5. Cleanup: stop polling, revoke temporary OAuth grant and protect state/tokens. Keep source evidence under the retention policy.

Reference: [Gmail getProfile](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile).

## PostgreSQL and evidence readback

Execute these read-only queries using an approved SQL client and private test identifiers. Never paste recipient data or raw JSON into public reports.

```sql
SELECT version_num FROM alembic_version;
SELECT message_id, tenant_id, provider, provider_account_id,
       provider_native_message_id, conversation_id, rfc_message_id,
       exact_parent_reference, parent_resolution, resolved_parent_message_id,
       source_authenticity, content_sha256
FROM p1_dev.inbound_messages
WHERE tenant_id = :approved_test_tenant
ORDER BY ingested_at;

SELECT attachment_id, evidence_ref, content_sha256, size_bytes
FROM p1_dev.attachments
WHERE tenant_id = :approved_test_tenant;
```

Native IDs/attachment hashes are provider evidence only when observed in a genuine approved test. Record evidence reference/digest, event/ingest time, tenant/provider/account, code HEAD, DB revision, authentication result and outcome for each case. P4 durable provider receipt readback remains BLOCKED until its approved mapping exists; adapter in-memory results or normalized callback dictionaries are not durable receipt proof. Delivery, customer assent, order acceptance and fulfilment stay separate.
