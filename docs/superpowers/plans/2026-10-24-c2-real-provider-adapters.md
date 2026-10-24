# C2 Real Provider Adapters Implementation Plan

> **For agentic workers:** This plan is being executed inline under the user's explicit instruction to work autonomously. Keep each provider slice fixture-testable and preserve provider and business authority boundaries.

**Goal:** Add secure, bounded Telegram, WhatsApp Cloud API, Resend email and existing Gmail provider capabilities on a separate C2 branch without copying C1 persistence code or changing shared canonical schemas/migrations.

**Architecture:** Extend the current P1 channel adapters and current P1 message/attachment repository. Add a Resend webhook/API adapter and provider-neutral transport result/error types. Keep outbound transports disabled by default and internal: P4 currently supports only mock channels, so no production send path is wired until its owner contract supports real channel/account/reply metadata.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy P1 repository boundary, httpx, pytest with fixture `MockTransport`.

## Global Constraints

- Never make live sends, deploy webhooks or use real credentials in this task.
- Do not modify OCR, Backend A–H, shared canonical APIs or Alembic migrations.
- Use existing `RawMessageEnvelope`, `IngestionService`, `MessageRepository`, and attachment storage; do not create a second persistence system.
- Fail closed on unverified callback signatures, tenant/account mismatches, disallowed recipients, unsupported WhatsApp session/template cases, and unsafe email sender/Reply-To values.
- Never blind-retry a send whose provider outcome is unknown; use explicit provider classifications and idempotency where the provider supports it.
- Label fixture validation as `SYNTHETIC_ONLY`; no provider is `REAL_CHANNEL_VERIFIED` without real E2E evidence.

---

### Task 1: Provider transport contracts and bounded HTTP behavior

**Files:**
- Create: `backend/app/context/channels/provider_transport.py`
- Modify: `backend/app/context/channels/config.py`
- Test: `backend/tests/v2_2/test_c2_provider_adapters.py`

- [x] Define provider result, retry classification, safe error data and explicit per-provider outbound allowlist/disabled defaults.
- [x] Add tests for timeout bounds, redacted errors, disabled outbound, and stable provider ID scoping.
- [x] Implement after the tests failed for missing contracts, then run the focused tests.

### Task 2: Telegram Bot API transport and inbound framing

**Files:**
- Modify: `backend/app/context/channels/telegram.py`
- Modify: `backend/app/context/channels/router.py`
- Test: `backend/tests/v2_2/test_c2_provider_adapters.py`

- [x] Test fail-closed webhook secret, bot/account-scoped IDs, exact `reply_to_message_id`, document retrieval and deterministic attachment references.
- [x] Test text sends, reply metadata, test-recipient allowlist, provider response parsing and unknown timeout outcome.
- [x] Implement bounded Bot API methods; no automatic duplicate send after an unknown outcome.

### Task 3: WhatsApp Cloud API transport, statuses and replies

**Files:**
- Modify: `backend/app/context/channels/whatsapp.py`
- Modify: `backend/app/context/channels/router.py`
- Test: `backend/tests/v2_2/test_c2_provider_adapters.py`

- [x] Test raw-byte HMAC verification, account phone-number-ID match, quoted parent capture, safe media URL/size handling, and status event normalization.
- [x] Test outbound recipient allowlist, approved-template and service-window restrictions, text requests, and provider status normalization.
- [x] Implement official Graph API request shapes. Statuses stay normalized events for a future P4 delivery-status sink; do not create a status table.

### Task 4: Resend inbound/outbound and Gmail reply evidence

**Files:**
- Create: `backend/app/context/channels/resend.py`
- Modify: `backend/app/context/channels/config.py`
- Modify: `backend/app/context/channels/manager.py`
- Modify: `backend/app/context/channels/router.py`
- Modify: `backend/app/context/channels/gmail.py`
- Test: `backend/tests/v2_2/test_c2_provider_adapters.py`

- [x] Test Resend/Svix webhook raw-body signature, timestamp bounds, replay deduplication, tenant binding, retrieved body and attachments.
- [x] Test outbound sender verification configuration, safe Reply-To, RFC threading headers, provider idempotency key, and response/error handling.
- [x] Test Gmail `In-Reply-To`, `References`, sender and Reply-To parsing; keep existing Gmail polling and add bounded attachment retrieval.
- [x] Add Resend webhook/API configuration but do not persist a second mailbox or webhook state.

### Task 5: Provider setup, evidence and integration boundaries

**Files:**
- Create: `docs/C2_REAL_PROVIDER_ADAPTERS.md`
- Test: focused adapter suite, existing Telegram/WhatsApp/Gmail tests, P4 outbound tests, `backend/tests/v2_2` relevant suite.

- [x] Document exact environment variables, official provider setup, test recipient constraints, timeouts, error/retry semantics, and safe test procedure.
- [x] Record why P4 wiring remains pending, which source metadata current P1 persists, and which C1 contract fields still need integration after review/merge.
- [x] Run fixture/regression tests and static checks; distinguish the synthetic-identity prerequisite for route integration tests.
- [ ] Push a separate `codex/c2-real-provider-adapters` branch and open a Draft PR requesting review only from `jiahui-1101`; do not mark ready or merge.
