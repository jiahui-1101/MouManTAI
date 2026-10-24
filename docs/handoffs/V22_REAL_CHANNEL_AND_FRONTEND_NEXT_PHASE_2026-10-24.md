# Real channel and Frontend handoff after Mock-backed Backend A–H

## Current verified boundary

The v2.2 Backend workflow uses controlled Mock inquiry facts and `LocalMockProvider` receipts to test order, Recovery and Communication business rules in isolation. Those are DEMO/SYNTHETIC fixtures. They do not prove a customer or supplier actually sent a message, saw a message or agreed to terms. Frontend Orders, Review, Recovery, Communication and advisory pages are not wired to the new `/v1/backend-v2` APIs yet. Their browser must use a trusted server-side proxy for the isolated key; the key must not enter `VITE_*`, local storage or client code.

## Existing code to extend and verify in the separate real-channel phase

- P1 has registered `/v1/channels/telegram/webhook`, `/v1/channels/whatsapp/webhook` and Gmail OAuth/poll/status routes in `backend/app/context/channels/router.py`, with adapters in `telegram.py`, `whatsapp.py` and `gmail.py`. These are implementation starting points, not a verified production-equivalent end-to-end claim. Verify HTTPS webhook setup, signatures/secrets, provider test accounts, durable deduplication and tenant/actor mapping against actual Telegram Bot API, Meta WhatsApp Cloud API test number and bidirectional test email.
- P1 `IngestionService`, association, deterministic extraction, attachment validation, PDF/image extraction and Qwen worker modules exist under `backend/app/context`. The known OCR blocker remains open. Verify real PDF/image extraction and failure-to-Human-Review behavior; add the specified Gemini API fallback after Qwen failure, timeout or structured-validation failure. Do not turn model output into authority.
- P4 currently uses `LocalMockProvider` in `backend/app/communication/providers.py` and Mock channel IDs in its contact/confirmation flow. Replace or supplement its outbound provider port with real Telegram/WhatsApp/Email transports and authenticated provider receipts. Preserve consent, contact policy, redaction, human review, draft/send separation, durable outbox, unknown-outcome reconciliation and reply-based reassessment. Provider send or delivery still does not prove customer assent.
- Add a human-verified Customer/Supplier Contact Registry across channels. Bind inbound and outbound identity to tenant, verified contact and Order ID before turning a message into a trusted customer/supplier event. Uncertain association, supplier-delay evidence and failed extraction go to Human Review. Replies must return via the originating channel and use only necessary disclosed fields.

## Frontend contract work

Use `docs/contracts/V22_MOCK_BACKEND_API_2026-10-24.md` and `/openapi.json` for Orders, Review, P2, Recovery, Communication, Supplier, Forecast, Optimization and Memory adapters. The Frontend team owns page wiring. Show pending, stale, unknown and evidence-tier states as returned; do not display Mock receipts as real provider actions. An API-to-UI test through a trusted server proxy is the completion gate. Real-channel UI states belong to the next phase after provider verification.

## Next phase gates

Exercise actual provider inbound → attachment extraction → deterministic/Qwen/Gemini analysis → verified contact and Order association → Human Review → exact OrderRequest; then approved outbound → actual provider receipt → inbound reply → evidence-backed reassessment. Test Telegram, WhatsApp and email separately with real test accounts and prove signature failure, duplicate/retry, wrong tenant, uncertain contact, OCR failure, model failure and provider unknown outcomes. Keep production identity and external action authority fail-closed until their respective verified adapters and credentials are configured.
