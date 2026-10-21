# Person 4 — Closed-Loop Communication & Confirmation

> **Owner**: P4 · **Type**: Full-Stack + Outbound Messaging + Reply Validation + tests
> **Depends on** P1 inbound message normalization, P3 `RecoveryPlan/Proposal`, P5 Commitment/identity/auth/versioning.
> **Mission**: Ensure a message has its own delivery status, an explicit agreement has its own confirmation evidence, and actual fulfilment requires separate operational evidence.

## 1. Acceptance Journey

A manager-approved recovery option requests customer acceptance of a revised deadline. UI shows exact approved terms, recipient/channel and message draft. After appropriate send approval, the synthetic provider records a realistic message state. A valid reply/confirmation **bound to the correct proposal version and recipient** changes confirmation state, which P5 can use for a new Commitment version. A rejection triggers F3 replan. An ambiguous “ok” when multiple proposals exist remains unresolved. An operational completion event (not the reply) is needed to mark `FULFILLED`.

## 2. Frontend Ownership

**Routes**: `/communications`, `/confirmations/:id`; optionally shared detail drawer on `/recovery/:id` via component exported to P3.

### FE-01 Communication Center
- [ ] List/filter by commitment, customer/supplier, channel, message state, confirmation state, follow-up deadline.
- [ ] Show approved source Recovery Plan and terms before composing; source data read-only without corresponding plan change.
- [ ] `Draft → Preview → Request Approval (if needed) → Send` explicit buttons and backend confirmation.
- [ ] Sender/recipient/channel selection only among verified or authorized options; fake provider labelled synthetic.
- [ ] Distinguish `QUEUED`, `SUBMITTED`, `SENT`, `DELIVERY_UNKNOWN`, `FAILED`, `DELIVERED` (where provider capable) from `ACCEPTED`.
- [ ] Inline send errors, retry rules, duplicate suppression messaging, history and audit.

### FE-02 Confirmation Workspace
- [ ] Show specific `confirmation_id`, `proposal_id`, `proposal_version`, exact terms, expiry, recipient, verified identity status.
- [ ] Accept/Reject/Counteroffer/Request Clarification supported; must include clear terms, version and server verification.
- [ ] Expired/superseded/wrong recipient confirmation disables action and shows why.
- [ ] Uncertain natural-language reply shows candidate intent and evidence with manual review option.
- [ ] Clear separation: "Message sent", "Terms accepted", "Action completed", "Fulfilled"; do not visually collapse statuses.
- [ ] Follow-up status, last reminder, next due, escalation reason; accessibility + mobile layout.

## 3. Backend Ownership

**Suggested module**: `backend/app/communication/`: `schemas.py`, `templates.py`, `drafting.py`, `outbound.py`, `channel_adapters.py`, `confirmations.py`, `followup.py`, `service.py`, `router.py`, `tests/`.

### BE-01 Communication Request
- [ ] Consume P3 `recovery.communication_requested` (plus F1 missing info and F2 impact notifications, appropriately scoped).
- [ ] Resolve recipient, channel authorization, communication purpose, approved terms, proposal version, consent/preference, message classification.
- [ ] Refuse unknown recipient, invalid identity for sensitive changes, expired proposal, no allowed channel, stale plan.
- [ ] Store `communication_id`, content hash/version, source plan, policy decision and evidence refs.

### BE-02 Template-First Drafting
- [ ] Jinja2 / typed template for ordinary messages, including exact `order_id`, proposed quantity, deadline, reply instructions.
- [ ] Optional shared Qwen3 for more complex natural-language wording; **ground to known approved facts**, enforce output Schema and blocked sensitive/unapproved promises.
- [ ] Language choice (English/Malay/Chinese as templates; support preference). Any unsupported language uses transparent fallback/hand review.
- [ ] Edits to consequential text require revalidation and possibly new approval; don't reuse old approval for material changes.
- [ ] Sanitize untrusted customer/supplier text; no arbitrary instructions passed as tool commands.

### BE-03 Outbound Adapter and Delivery
- [ ] Provider interface: `validate_recipient`, `prepare_payload`, `send`, `query_delivery_status` if supported.
- [ ] Implement synthetic `MOCK_WHATSAPP`/`MOCK_EMAIL`/`MOCK_TELEGRAM` with distinguishable capability and message state; don't invent delivery/read receipt universally.
- [ ] Production connectors roadmap: Meta WhatsApp Cloud API (template/window/opt-in), Gmail / Microsoft Graph scopes and threading, Telegram bot permission rules.
- [ ] Important messages require owner-approved send per policy; owner role validated server-side.
- [ ] Stable idempotency + unique logical send ID; if provider timeout ambiguous do not automatically resend blindly.
- [ ] Track `DRAFT`, `VALIDATED`, `PENDING_APPROVAL`, `QUEUED`, `SUBMITTED`, `SENT`, `DELIVERY_UNKNOWN`, `FAILED`, `DELIVERED` as separate from confirmation.

### BE-04 Reply Understanding and Confirmation
- [ ] Consume inbound replies normalized by P1 (do not duplicate raw webhook parsing).
- [ ] Deterministic confirmations preferred: signed/unguessable `confirmation_token`, identity linkage, target proposal version, expiry, accepted terms.
- [ ] Structured response may be `ACCEPT`, `REJECT`, `COUNTEROFFER`, `CLARIFICATION`, `UNKNOWN`.
- [ ] Optional BERT-style reply classification (XLM-RoBERTa fine-tuned and evaluated) + GLiNER for terms; Qwen3 only for complex ambiguous cases. No untrained base model claimed as accuracy-certified classifier.
- [ ] Natural-language “OK” is not automatically valid when target/terms ambiguous; no force-link based solely on semantic similarity.
- [ ] Confirmation validation: verified sender/channel, proposal ID/version, expiry, no conflicting newer proposal, full acceptance of exact terms vs conditional acceptance.
- [ ] Emit `confirmation.accepted`, `confirmation.rejected`, `confirmation.counteroffer_received`, `confirmation.unresolved`; P5 Core owns authoritative Agreement transition.
- [ ] A third party cannot confirm another customer's sensitive commitment solely by knowing an order ID.

### BE-05 Follow-Up / Escalation
- [ ] Response SLA policy: deadline, max reminders, minimum interval, allowed hours, opt-out and escalation.
- [ ] On confirmed response cancel pending reminder; on rejection cancel irrelevant follow-ups and notify P3.
- [ ] P0 use DB-backed due tasks and worker/endpoint for deterministic scheduled simulation. Temporal production roadmap; no timer-dependent flaky tests.
- [ ] Prevent repeated reminders across two channels for same unanswered request unless policy allows and recipient permission is verified.

### BE-06 Outcome Evidence Boundary
- [ ] Communication can record approved agreement and recipient acknowledgment; **cannot by itself prove completed delivery**.
- [ ] Actual fulfilment derives from P5 trusted operational completion adapter and corresponding evidence rules; UI reads fulfilment from Core only.
- [ ] Supplier “we will deliver tomorrow” proves a supplier statement/offer, not received stock.

## 4. Contracts & APIs

Use shared `CommunicationRequest`, `Confirmation`, `DomainEvent`, `Commitment` from `REQUIREMENTS_SYSTEM.md`. P3 supplies versioned proposal; P1 supplies source reply + identity; P5 resolves authoritative status.

```text
POST /v1/communications/requests
GET  /v1/communications
GET  /v1/communications/{id}
POST /v1/communications/{id}/prepare
POST /v1/communications/{id}/approve
POST /v1/communications/{id}/send
GET  /v1/confirmations/{id}
POST /v1/confirmations/{id}/respond
GET  /v1/follow-ups
POST /v1/follow-ups/{id}/cancel
```

**Events**: `communication.requested`, `.approval_required`, `.sent`, `.delivery_failed`; `confirmation.accepted`, `.rejected`, `.counteroffer_received`, `.unresolved`; `communication.followup_due`, `.escalation_required`.

Do not create real public network sends in synthetic demo mode or send without permission; record exact `mock=true` provider status. Include correlation ID and `proposal_version` on confirmation results.

## 5. Data Entities

`communication_requests`, `communication_threads` (reference P1 canonical threads), `outbound_messages`, `delivery_attempts`, `message_templates`, `recipient_preferences`, `confirmation_requests`, `confirmation_responses`, `communication_approvals`, `followup_workflows`, `communication_exceptions`.

No duplicate customer identity database; use P1/P5 references and authentication. Store content versions, approval scopes and evidence refs; protect PII in outbound/inbound logs.

## 6. Tests & Failure Handling

| Test | Expected |
|---|---|
| F4-01 Draft message based on plan V3 | Terms match exact approved V3; no invented amounts |
| F4-02 Send without authorization | Denied before provider action |
| F4-03 Mock send accepted but not delivered | `SUBMITTED`/`SENT`, **not** `DELIVERED/ACCEPTED` |
| F4-04 “Okay” reply to two open proposals | `UNRESOLVED`, not automatic accepted |
| F4-05 Correct signed response for current proposal | Valid acceptance event with evidence refs |
| F4-06 Response to superseded V2, V3 active | Rejected as stale; no accidental commitment change |
| F4-07 Nonmatching recipient uses confirmation token | Fail identity policy, no acceptance |
| F4-08 Customer counteroffer | Emit replan request and preserve original commitment |
| F4-09 Duplicate webhook reply | One confirmation state transition |
| F4-10 No reply before deadline | Follow-up once and escalation per policy |
| F4-11 Confirmation accepted, no delivery evidence | Agreement updated only; fulfilment NOT `FULFILLED` |
| F4-12 Send outcome unknown + retry | No blind second actual send |

**FE**: version/expiry controls, approval state, message vs confirmation badges, rejection/clarification, error and loading. **Metric**: false acceptance rate, confirmation-resolution accuracy, duplicate sends, reminder-policy correctness, separate delivery/fulfilment rates.

## 7. Timeline

| Date | P4 deliverable |
|---|---|
| 20 Oct | Confirm P1 message/reference and P3 proposal contract; routes/forms/mock channel |
| 21 Oct | Template drafting, message list, signed confirmation flow (synthetic) |
| 22 Oct | Backend send state + confirmation API integrated into P5 Core |
| 23 Oct | P3 approval→communication→accept/reject loop, follow-up/negative tests |
| 24 Oct | Verify sender/version/expiry edge cases; freeze and metrics |
| 25 Oct | Submission support |

## 8. Scope

**P0**: synthetic outbound adapter and confirmation UX/API, exact current proposal version validation, accepted/rejected/counteroffer loop, follow-up or escalation example, audit.
**Optional**: natural language reply classifier / Qwen3 drafting after deterministic safeguards and evaluation.
**Production later**: live WhatsApp/Gmail/Graph/Telegram, verified consent management, provider delivery callbacks, Temporal durable reminders, multilingual evaluation.
**Never**: message sent implies accepted, read implies accepted, acceptance implies fulfilled, model decides legally binding terms, undocumented auto-send of significant promises.

## 9. Handoff Checklist

- [ ] F4 receives P3 approved plan/proposal without duplicating approval logic.
- [ ] F1 inbound reply identity/reference is reused, not independently assumed.
- [ ] P5 confirms proposal acceptance from evidence and version validation.
- [ ] Mock send and true sent/delivered semantics are visibly separate.
- [ ] UI and API handle rejection/ambiguity/expiry, backed by tests.
- [ ] `TEAM_LOG.md` updated truthfully; demo depends on real integrated state.
