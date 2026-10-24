# MouManTAI 2.2 — Final Implementation Blueprint (Review-ready)

**Date:** 2026-10-23 · **Product:** MouManTAI / SDC Domain 2 / Orbyte Smart SME Challenge  
**Document type:** Implementation-ready architecture and implementation contract; **not proof that the repository has been migrated**.  
**Inputs:** Product-owner confirmed Customer / SME / Supplier workflows, mandatory human-approved Emergency Change-to-Action, v2.1 System/Backend/Frontend/AGENTS, two successive design reviews, legacy requirements.  
**Read alongside:** `REQUIREMENTS_SYSTEM.md`, `REQUIREMENTS_BACKEND.md`, `REQUIREMENTS_FRONTEND.md`, `AGENTS.md` (v2.2).  
**Status:** **Recommended engineering baseline, awaiting owner signoff** where explicitly marked. Existing owner-confirmed choices retain their precedence.

---

## 1. Objective engineering judgment: which review points are correct?

| Review | Verdict | Final engineering disposition |
|---|---|---|
| 1. Accepting modified customer terms is undefined | **Critical, accept** | `accept` accepts only the customer's *exact agreed terms*. Any material deviation—including price, quantity, SKU, delivery date/time, fulfilment type, fees, special constraints—creates versioned Proposal and requires specific customer assent before acceptance. |
| 2. Replit endpoint not verified | **Correct technical observation; proposed replacement is too strong** | Keep **owner-selected Qwen analysis + Replit generation** as product intent; never invent an API endpoint. Put Replit behind `ReplyGenerator`, require provider integration smoke-test before enabling; static facts use `TemplateGenerator`. Qwen-generated wording is an optional separately configured fallback, **not a silent provider substitution**. |
| 3. Documentation labels overly complex | **Accept** | Use an authoritative **capability/evidence matrix**. Two independent axes: requirement decision (`CONFIRMED`, `PROPOSED`, `OPEN`, `DESIGN-RESOLVED/REVIEW`) and implementation evidence (`TARGET`, `DEMO-ONLY`, `VALIDATED`, `LIVE`). `MUST` is normative wording, not a third status axis. |
| 4. Two backend CTA commands should not mean two routine UI clicks | **Accept** | One clear **Approve & Execute** UX calls two audited commands in sequence. Keep **Approve Only** for deferred execution. Handle partial success visibly and idempotently. |
| 5. Need small measured manual-vs-system comparison | **Accept** | Run 3 scripted tasks: public FAQ reply; clarification/order-ready assembly; consolidate 3 supplier quotations. Record sample count, median time, assisted-review time, errors, operator type, simulation caveat; no invented savings. |
| 6. Category-specific supplier schema is a setup burden | **Accept** | Seed 2–3 editable versioned category templates: food packaging, perishable ingredients, general supplies. SME only adjusts relevant fields; unknown categories `SPEC_UNKNOWN`, no model-guessed compatibility. |
| Repository not actually audited | **Major feasibility limit** | **Phase 0 read-only inventory before any migration.** No physical table/route/import names claimed as verified here. Produce a signed-off `LEGACY_REUSE_MATRIX.md` from actual code. |

**Explicit non-goal:** This review does **not** approve deletion of Forecasting, Historical Decision Memory or feedback. They remain full-product target capabilities, but proof of real forecasting effectiveness or learned improvement requires genuine records. Similarly, it does not relax the owner's mandatory human approval for emergency business actions.

## 2. One coherent product, three perspectives and a shared decision core

**Product promise:** Help SMEs answer and collect customer requests, decide which commitments are safe to accept, consolidate supplier evidence, anticipate future resource risks and respond to disruptions **without giving AI commercial authority**.

**Business actors:** Customer (messaging channels); SME (Orbyte-hosted MouManTAI workspace); Supplier (existing channels/quotes). There is no mandatory new customer/supplier portal.

**Main end-to-end workflow** (also the clearest evaluation/pitch story):

```text
Customer message (WhatsApp / Telegram / Outlook/email)
  -> canonical inbound message + evidence -> Qwen classification/extraction
  -> safe factual FAQ reply OR conversational order draft
  -> issue-based auto clarification / no-reply follow-up / human review
  -> complete exact customer-requested terms
  -> PENDING_ACCEPTANCE -> shared P2 feasibility and (if contention) portfolio analysis
  -> SME accepts *exact same terms* and resource reservation succeeds
  -> accepted Commitment + factual customer milestone notification
  -> operational status tracking -> evidenced fulfilment -> optional feedback
```

**Connected supporting workflows:** supplier quotes + human selection; verified operational incident + impact + candidate recovery plans + **human approval** + governed execution; evidence-gated demand/stock/capacity forecasting; history/outcome learning. The supplier, forecast and emergency modules consume the **same** product/stock/order sources and audit services.

### 2.1 Capability × evidence matrix (single review source of truth)

| Capability | Requirement decision | Planned implementation evidence | Release gate / caveat |
|---|---|---|---|
| Multi-channel ingestion + OCR + Qwen analysis | CONFIRMED | `TARGET`; upgrade only after repo audit/test | Synthetic adapters ≠ live channel |
| Public FAQ + auto clarification | CONFIRMED | `TARGET` | Template source authorization, no fabricated price/ETA |
| Complete order + separate review/acceptance queue | CONFIRMED | `TARGET` | Issue progress deterministic; no-reply timer |
| SME P2 feasibility + acceptance / reservation | CONFIRMED | `TARGET` | Exact terms, latest version, authoritative receipt |
| FCFS / Profit / Expiry-aware portfolio | CONFIRMED | `TARGET` | P2 joint validation; Profit requires sourced cost/revenue |
| Customer status query + milestone notifications | CONFIRMED | `TARGET` | Channel verified; completion needs evidence |
| Supplier offer comparison + history + SME decision | CONFIRMED | `TARGET` | Versioned category schema; no automatic purchasing |
| Emergency Recovery + Change-to-Action | CONFIRMED | `TARGET` | **Mandatory explicit human approval** for each scoped plan |
| Forecasting beyond descriptive baseline | PROPOSED | `TARGET` / synthetic mechanism `DEMO-ONLY` | Real chronological holdout needed for `VALIDATED` |
| Decision Memory recommendations | PROPOSED | `TARGET` / synthetic case `DEMO-ONLY` | Verified case count/coverage gate |
| Supplier RFQ collaboration | PROPOSED | `TARGET` | Sending/PO handoff requires explicit policy |
| Genuine Orbyte/WhatsApp/Telegram integration | OPEN (external contracts) | `TARGET`, isolated mocks may be `DEMO-ONLY` | Provider/auth/receipt verified before `LIVE` |

**How to maintain:** `Requirement decision` is about *what to build*, `Evidence` about *what is proven to work*. Never convert synthetic mechanism tests into `VALIDATED` claims about real SMEs. Feature-level evidence status must be backed by test/verification reference and date. Table above is **not** an assertion that any capability has been implemented in the current checkout.

## 3. Canonical order terms, acceptance and agreement: frozen implementation decision

> **Engineering resolution requiring owner ratification:** Terms cannot be accepted with silent deviations. This is a correctness guard, not optional polish.

### 3.1 Canonical `OrderTerms` (minimum binding terms)

```text
order_request_id, customer_identity_ref, business_tenant_id
line_items[{catalog_sku, variant/spec_id, quantity_decimal, unit}]
fulfilment_type, location/address_ref if applicable
delivery_or_pickup_window (explicit timezone)
unit_price/total_currency/fees/taxes/discounts when part of offer
price_source{source_type, catalog_or_quote_id, source_version, disclosed_to_customer_at}
special_conditions, agreed_policies / reference, source_message_ids
terms_revision, canonical_terms_hash, evidence refs
```

- Prices must have an **authoritative source**: approved Orbyte catalog with immutable version or SME-approved quoted offer version; negotiated price is **not** inferred from Qwen. Store amount, currency, source/version and when terms were disclosed/acknowledged by the customer.
- `terms_hash` is a reproducible canonicalization of legally/operationally relevant fields after safe type/unit/time normalization; it is not merely a comparison of free-text summaries. Backend determines equality, not LLM semantic similarity.
- If customer did **not** receive/acknowledge a binding price/fees or another material term, the initial request is not a complete agreed offer. Ask for missing permissible facts or enter the customer **Proposal/Agreement** workflow. Do **not** manufacture a price or pretend customer consent.
- Correcting extraction without changing the customer's actual original instruction is allowed with evidence and revision audit; changing the commercial terms is a **Proposal**.

### 3.2 Two exact acceptance paths

**A. Unchanged original customer offer:**

```text
Customer submits explicit request incl. disclosed agreed binding terms
-> order draft validated (terms_hash = customer_offered_terms_hash)
-> PENDING_ACCEPTANCE
-> SME POST /orders/{id}/accept (request_version, expected_terms_hash, idempotency_key)
-> backend verifies 1:1 terms equality + latest feasibility
-> authoritative ResourceReservation SUCCESS
-> atomic/guarded bind to Commitment(version 1) + agreement_state=CONFIRMED
-> OrderRequest.ACCEPTED; milestone "Your order has been accepted by the business"
```

`ACCEPTED` means **SME decision AND successful reservation**. The unchanged customer's explicit offer + matching SME acceptance is sufficient agreement evidence; no extra AI acceptance email, no new customer confirmation click. A reservation still pending or failed means `ACCEPTING` or remain `PENDING_ACCEPTANCE`, **never** `ACCEPTED`.

**B. Different / newly supplied terms (counteroffer first, accept only after assent):**

```text
SME offers lower quantity / higher price / later date / changed item / new fee / etc.
-> POST /orders/{id}/proposals (based_on_request_version, exact_new_terms, reason)
-> original request remains pending; proposal OFFERED / AWAITING_CUSTOMER_ASSENT
-> customer receives exact proposal terms over verified channel
-> explicit assent linked to proposal ID + exact hash (NOT generic "OK" without context)
-> SME acceptance + updated feasibility + latest authoritative reservation
-> Commitment confirmed at the agreed terms version; ACCEPTED + milestone
```

For an **existing accepted Commitment**, proposal is `amendment v+1`, old commitment stays authoritative until exact customer assent, reservation adjustment and appropriate SME authorization all succeed. For a **not-yet-accepted request**, it is an **initial counteroffer/proposal revision**, not a false `Commitment v+1`. Never call `accept` with a changed `terms_hash`: return `409 TERMS_MISMATCH` with a `PROPOSAL_REQUIRED` route, no side effects.

**Customer-facing projection:** `ORDER_ACCEPTED` comes from accepted/reserved state; `ORDER_CONFIRMED` may be used only for a fully agreed exact terms version. `COMPLETED` is rendered **only** from evidenced `Commitment.fulfilment_state=FULFILLED`; SME one-click “report ready/done” alone yields `COMPLETION_REPORTED` or an industry-policy-verifiable event, not arbitrary delivery proof. `SENT != DELIVERED != CUSTOMER_ASSENT != FULFILLED`.

### 3.3 API guard sketch (illustrative contract, adapt actual routes post-audit)

```python
async def accept_order(command: AcceptOrder, actor: SMEActor) -> AcceptResult:
    request = repo.get_locked_request(command.order_id, tenant=actor.tenant_id)
    require_role(actor, "order.accept")
    require_match(command.expected_request_version, request.version)
    require_match(command.expected_terms_hash, request.customer_agreed_terms_hash)
    require_equal(request.current_offer_terms_hash, request.customer_agreed_terms_hash)
    require_status(request, "PENDING_ACCEPTANCE")
    assessment = evaluate_feasibility(latest_snapshot(), request.current_terms)
    require_feasible(assessment)
    receipt = await business_command_port.reserve_with_idempotency(
        request, assessment, command.idempotency_key
    )
    if receipt.pending:
        return AcceptResult(state="ACCEPTING", operation_id=receipt.id)
    require_authoritative_reservation_success(receipt)
    return core.commit_accepted_request_and_record_outbox(request, receipt, actor)
```

Implementation must handle the **distributed transaction gap** between external reservation and local Core commit: durable acceptance intent/outbox, idempotency and receipt reconciliation; if Core commit fails after a successful external reservation, recover/reconcile or release according to port policy—never silently create a duplicate commitment. Physical locking/atomic boundary depends on actual storage and Orbyte adapter contracts.

## 4. Customer: intake, clarification, replies and status

### 4.1 Qwen / Replit technology contract

- **Confirmed product intent:** Qwen performs intent classification, extraction, ambiguity analysis and candidate explanation. **Replit is the owner's preferred external natural-language reply generation provider** when a working, authorized inference endpoint is actually available.
- **Not confirmed:** exact callable Replit endpoint, authentication model, model ID, outbound messaging permissions. Replit's AI Integrations product description alone does **not** verify that this backend can call a chosen endpoint. Do a configuration+request+error+privacy smoke-test before claiming integration.
- **Mandatory interface:** `ReplyGenerator.generate(ReplyContext)->DraftResult`; implementations `TemplateGenerator` (default for factual statuses/approved fixed FAQ), `ReplitGenerator` (preferred conditional), optional explicitly configured `QwenWordingGenerator` (requires separate owner approval; no automatic substitution). **Transport is always a distinct `ChannelAdapter.send`**.
- **Failure strategy:** template when all fields authoritative, otherwise Human Review; no made-up ETA, price, availability or implied delivery. No third-party model gets raw database access; server filters authorized knowledge and logs policy/version/provenance.

```python
class ReplyGenerator(Protocol):
    async def generate(self, context: AuthorizedReplyContext) -> DraftResult: ...

class ChannelAdapter(Protocol):
    async def send(self, message: ApprovedOutboundMessage) -> ProviderSendReceipt: ...
```

### 4.2 Adaptive per-issue clarification, deterministic progress

For each unresolved issue persist `issue_type`, `candidate_values`, `validated_fields`, `failed_answered_attempts`, `question_version`, `last_sent_at`, `response_source_ids`, `max_global_budget`, `status`. Qwen outputs *candidates*; deterministic validators decide resolution/progress:

| Issue | Validated progress (examples) | Does not count as progress |
|---|---|---|
| SKU / variant | Exact catalog SKU confirmed or candidate set strictly narrowed by explicit customer selection to allowable products | AI invents “usual one”; customer repeats unspecified term |
| Quantity | Typed positive Decimal and valid unit; explicit quantity range becomes narrower if still unresolved | LLM changes unit without supported conversion |
| Date / time | Unambiguous explicit local date/window with timezone rules; supported narrowing of options | Relative phrase remains ambiguous or wrong business date |
| Address / fulfilment | Verified address or customer selects registered pickup option | Vague 'same place' without verified matching context |
| Special constraint | Customer supplies required categorical value meeting SME policy | Model confidently infers undisclosed allergy/material requirement |

Decision rules: (1) candidate pool narrowed OR validated necessary field newly resolved → progress; (2) answered clarification with no such progress → increment **for the specific issue**; (3) two consecutive answered no-progress attempts → Human Review; (4) progress resets that issue's no-progress counter; (5) risk/commercial ambiguity escalates immediately. To prevent endless tiny improvements, enforce configurable **global total questions + conversation age cap**. Example fixture defaults only: `max_auto_questions=6`, `reminder_after=24h`, `expire_after=72h`. Actual tenant policy must be configured/confirmed.

**Idle follow-up independent:** `AWAITING_CUSTOMER` timer fires → one deduplicated factual reminder → subsequent expiry or Human Review. Waiting or failed send does *not* count as failed answered clarification. A reply after expiry is a new, clearly linked version/reopen request and cannot silently accept old expired terms.

### 4.3 Status / customer retention / feedback

- Customer status query requires channel/customer/order association verification; return **latest authorized authoritative state**; not AI-predicted progress.
- Key verified milestones auto-publish allowlisted templates via the existing outbound owner with idempotency keyed by `(tenant, order, milestone, state_version, channel)`; SME can view attempts, deliveries, failures. **No additional free-form AI confirmation email** after acceptance.
- Completion feedback invitation is optional; customer ratings/comments are separate from fulfilment evidence.
- Daily production planned-vs-actual derives from available Orbyte/operational events; optional minimal SME report when business data lacks actuals; disallow forced daily detailed logging or unsupported capacity-learning claims. Suggestions to change production durations require SME review.

## 5. SME: feasibility, CP-SAT portfolios, acceptance and calendar

### 5.1 Same calculation authority

`OperationalSnapshot/ConstraintSpec` produced by one shared P2 domain engine. CP-SAT compiles *this* spec into integer search variables; **it cannot invent separate BOM/ATP/expiry/capacity semantics**. After finding selected orders and lot/time allocations, run `evaluate_feasibility` on the **whole projected portfolio** with shared inventory/schedule, and on each included order in that joint projection. Any mismatch → `VALIDATION_MISMATCH` and suppress recommended acceptance. Accepted commitments and authoritative reservations are fixed constraints. Time/money/quantities use Decimal/NUMERIC and explicit integer scaling for CP-SAT.

- **No real contention:** normal per-order P2 analysis; do not pretend every SME routinely needs portfolio optimization.
- **FCFS:** deterministic sequential greedy admission using P2; no need to force CP-SAT for this strategy.
- **Profit:** CP-SAT maximize vetted **incremental margin** across a feasible portfolio; require price version and complete scoped cost basis (material, labour, delivery and applicable joint costs). Else `PROFIT_COMPARISON_UNAVAILABLE`, show other strategies.
- **Expiry-aware:** CP-SAT lot/time-safe allocation minimizing avoidable expiring balance without violating confirmed orders, FEFO-compatible; do not mark expired/unsafe goods usable.
- **Output:** selected IDs, excluded IDs with reasons (`HARD_CONSTRAINT` vs `NOT_CHOSEN_BY_OBJECTIVE`), solver status (`OPTIMAL`, `FEASIBLE_NOT_PROVEN_OPTIMAL`, `INFEASIBLE`, `UNKNOWN`, `VALIDATION_MISMATCH`), assumptions, snapshot and evaluator attestations.
- **Never auto-accept:** SME chooses; each accept rechecks exact terms, current P2 feasibility, latest inventory/schedule and reservation receipt.

### 5.2 Minimal meaningful contention fixture

Two or three competing Pending Orders for a time-limited inventory lot; FCFS favors earlier order, Profit alternative favors a different feasible order where **approved fixture prices and cost inputs exist**, Expiry-aware must demonstrate material-validity gating. Present why combinations differ, not a magic score. In a no-contention fixture, portfolio view is absent/optional.

## 6. Supplier intelligence, specifications and sourcing

- Ingest messages and documents via existing P1 pipeline; store supplier identity, offers, products, quote revision/time/expiry, evidence. Distinguish supplier stated stock/ETA from verified inbound goods.
- **Three seeded versioned category templates (editable with low effort):**
  1. `food_container`: capacity ml, dimensions, material, heat/food-safe requirements, MOQ, units/pack, delivery window, quoted unit/pack price.
  2. `perishable_ingredient`: item/grade, unit weight, origin when relevant, lot/use-by date, storage/temperature requirement, MOQ, delivery time, freshness **only if evidenced**.
  3. `general_supply`: SKU, unit, quantity, dimensions/options as configured, MOQ, price, lead time.
- Each category declares **mandatory hard-match fields**, normalized units/conversion, optional comparability fields, evidence requirements and revision version. Unknown category/unknown hard field → `SPEC_UNKNOWN / INSUFFICIENT_EVIDENCE`, never silently classify comparable.
- **Auto group** cautiously by category/catalog link + normalized hard dimensions; ambiguous items remain ungrouped/review. **On-demand** compare against SME hard requirement then show qualified/conditional/incompatible offers side-by-side, pros/cons and historical verified-vs-reported records.
- SME selection records offered version, alternative comparisons and decision reason; **never auto-purchase**. In emergency `ALTERNATIVE_SUPPLY`, offered quote is only `CONDITIONAL` until availability/fit/current price/approval are checked; do not use supplier quotation as inbound stock.
- Optional RFQ workflow: draft common requirements → SME-authorized send → replies consolidate → SME decision; purchase/PO handoff remains `OPEN`.

## 7. Emergency Recovery and mandatory human-approved Change-to-Action

**Unchanged owner-locked rule:** every *emergency business Change-to-Action* requires SME **human inspection + explicit authorized plan approval** before execution. AI may ingest, detect, analyze, draft and simulate, but may not execute or authorize emergency actions.

### 7.1 Backend split and approval scope

```text
INCIDENT_REPORTED / VERIFIED
-> impact via P2 + recovery candidate options
-> PLAN_DRAFT -> HUMAN_REVIEW
-> APPROVE_PLAN(actor, plan_id, version, enumerated actions, limits, expiry)
-> APPROVED / EXECUTION_PENDING (NO SIDE EFFECT)
-> EXECUTE_APPROVED_PLAN(approval_id, same version, idempotency key)
-> REVALIDATE(snapshot, authority, constraints, approval scope)
-> EXECUTING -> EXECUTED / PARTIAL / FAILED / UNKNOWN
-> VERIFY actual side effects -> VERIFIED / NEEDS_FOLLOW_UP
```

One explicit human approval **per plan**, covering exact listed actions and limits; no extra approval click for every routine sub-action within that plan. Customer-facing contractual changes still require separately recorded customer assent to the exact changed version.

### 7.2 Frontend: one-click Approve & Execute, two backend commands

- Primary button **`Approve & Execute`** only after plan detail, alternatives, evidence, affected orders and action scope are visible and SME explicitly confirms intended scope.
- On the user's click, frontend (or a server-side coordinator restricted to the authenticated click intent) calls `POST /plans/{id}/approve`, obtains durable `approval_id`, then calls `POST /plans/{id}/execute` using that exact authorization and an idempotency key. Approval remains a real independent event/command.
- Secondary button **`Approve Only`** records approval and leaves `APPROVED_AWAITING_EXECUTION`; a future deliberate SME execution action consumes it. Approval may expire / be invalidated.
- **If approval succeeds but execution fails/times out:** show `APPROVED_AWAITING_EXECUTION` or `EXECUTION_STATUS_UNKNOWN`, query operation status before retry, never claim success or repeat side effects blindly. Stale data returns `REAPPROVAL_REQUIRED`; previous approval cannot silently stretch to changed plan.
- No auto-approval from forecasts or supplier proposals. No unapproved external purchase/payment. Idempotent action IDs and independent outcome receipts required.

## 8. Orbyte integration and actual legacy code reuse

**Authority:** Real Orbyte-connected operational system would own inventory/schedule/reservations when available. The developer demo uses `mock_orbyte` **bounded context** with realistic version/transaction semantics, reached **only** via `BusinessDataReader`, `BusinessCommandPort`, `ApprovalNotificationPort`. Do not call it a live Orbyte tenant.

**Phase 0 (must happen before schema/code changes):** inspect *actual* Git branch/commit, `AGENTS.md`, migrations/Alembic history, SQL tables, Pydantic/TS DTOs, API routes, P1 extraction/context, P2 BOM/ATP/capacity evaluator, P3 recovery approval/executor, P4 outbound/follow-up, P5 core registry/audit/outbox, UI pages, tests/fixtures and configs. Produce `LEGACY_REUSE_MATRIX.md` with concrete file symbols/table names/route dependencies, and `REPOSITORY_BASELINE.md` with reproducible tests. No invented physical names.

**Mapping format** (required, fill from real code):

| Legacy file/function/table/route (verified path) | New owning bounded context | Action (`REUSE`,`EXTEND`,`ADD`,`DEPRECATE`) | Compatibility strategy | Migration/tests |
|---|---|---|---|---|
| *TO BE AUDITED* | Message Intelligence | REUSE or EXTEND | Preserve channel/source IDs | Existing extraction tests |
| *TO BE AUDITED* | Core Commitments | REUSE | One write authority, terms hash linkage | Existing lifecycle tests |
| *TO BE AUDITED* | P2 Feasibility | REUSE+EXTEND | ConstraintSpec + joint verifier | Existing P2 + portfolio tests |
| *TO BE AUDITED* | P3 Recovery | REUSE+EXTEND | Human-approval plan scope | Approval/execution tests |
| *TO BE AUDITED* | P4 Communication | REUSE+EXTEND | Purpose-type templates/reminders/status | Existing outbound/idempotency tests |
| *TO BE AUDITED* | Mock Orbyte port | ADD if missing | Separate schema/service behind port | Integration contract tests |

**Schema rule:** never create a duplicate `source_messages` vs existing `inbound_messages`, `human_review_tasks` vs `context_reviews`, `status_notifications` vs `outbound_messages`, or `disruption_incidents` vs `recovery_cases` merely because target names differ. Additive Alembic only after explicit mapping and compatibility strategy, preserving old IDs, audit data and tests.

## 9. Implementation sequencing with concrete release gates (not a time estimate)

> Sequence is based on dependencies, **not** a proposal to cut the full product. Each phase ends in runnable tests and an API/UI observation rather than documents alone.

| Sequence | Build slice | Must be demonstrably true before progressing |
|---|---|---|
| **0 — Inspect** | Read-only repository and DB audit; exact old→new map, baseline build/tests, authoritative owners | `LEGACY_REUSE_MATRIX.md` and `REPOSITORY_BASELINE.md`; no destructive edit |
| **1 — Contracts** | Canonical `OrderTerms`, hashes, statuses, Proposal, approval/envelope DTOs, Orbyte ports | Terms-equality and price-source tests; old DTO compatibility |
| **2 — Customer** | Qwen extraction, ReplyGenerator adapter+templates, issue progress, no-reply follow-up, separate review | Inquiry, ambiguous order, two no-progress, reminder and no invented promise tests |
| **3 — SME order** | Calendar/order queue, P2 pre-acceptance assessment, `accept` exact terms and authoritative reservation | One-click SME acceptance reflected in Core+customer milestone; modified terms → proposal |
| **4 — Optimization** | Canonical constraint spec, FCFS and CP-SAT profit/expiry, P2 projected joint validator | Deterministic contention fixture, no-contention fallback, mismatch blocks advice |
| **5 — Supplier** | Seed categories, offer versions, history provenance, hard-spec comparison/SME selection | Three offers correctly marked qualified/conditional/incompatible; selected reason audited |
| **6 — Emergency** | Legacy recovery reconnected to supplier/stock evidence, human review/approval, one-click approve-and-execute | No action before approved plan; partial/unknown execution visible; audit receipts |
| **7 — Status and feedback** | Milestone templates, status query, daily actuals from events and optional feedback | Customer sees only own order; verified vs reported completion distinct |
| **8 — Full target** | Forecasting with historical data gates, Decision Memory, RFQ and real adapters when contracted | Synthetic labelled `DEMO-ONLY`, historical metrics withheld until genuine validation |
| **9 — Evidence** | Automated full regression, timed manual-vs-system workflow study, rubrics crosswalk, deployment smoke test | Measured times and sample size documented; no false `LIVE` claims |

**No stage authorizes deleting old modules before routes/DB records/tests are mapped.** A staging implementation may merge slices, but cannot skip gates.

## 10. API / UI contract deltas that v2.1 must receive

### 10.1 Minimum API changes (names illustrative until repo audit)

| Endpoint / command | Required change |
|---|---|
| `POST /orders/{id}/accept` | Requires `expected_terms_hash` and `expected_request_version`; reject changed price/SKU/date/fees with `409 TERMS_MISMATCH`; accept only after valid reserve receipt. |
| `POST /orders/{id}/proposals` | Creates initial counteroffer if pre-acceptance terms differ, or amendment if post-acceptance; exact quote/catalog price source and version mandatory. |
| `POST /proposals/{id}/respond` | Authenticated customer assent linked to proposal hash/version; generic ambiguous reply cannot approve. |
| `GET /orders/{id}/terms-diff` | Read-only original vs proposed terms, including price provenance, evidence and what requires consent. |
| `GET /replies/providers/status` (admin only) | Which reply adapter is configured/tested; do not expose secrets. Unverified Replit cannot be listed as live. |
| `POST /recovery/plans/{id}/approve` | Human-approved scoped plan, no execution. |
| `POST /recovery/plans/{id}/execute` | Consume approval + revalidate + execute, idempotent; status query available for unknown responses. |
| `GET /capabilities` (admin/diagnostic) | Expose safe per-tenant configured `mode`, `evidence_tier`, `last_verified` for truthful UI badges (not a writable implementation truth). |

**Indicative error codes:** `TERMS_MISMATCH`, `PROPOSAL_REQUIRED`, `PRICE_SOURCE_UNVERIFIED`, `RESERVATION_PENDING`, `RESERVATION_CONFLICT`, `INSUFFICIENT_FEASIBILITY_DATA`, `PROFIT_COMPARISON_UNAVAILABLE`, `VALIDATION_MISMATCH`, `REAPPROVAL_REQUIRED`, `EXECUTION_STATUS_UNKNOWN`, `SPEC_UNKNOWN`, `INFERENCE_PROVIDER_UNAVAILABLE`.

### 10.2 UX deltas

- Order Decision detail: **"Accept as Requested"** for an unchanged original offer, **"Accept Agreed Proposal"** after exact customer assent, versus **"Propose Changes"** for unilateral changes—with a field-by-field diff and price source. Never one ambiguous Accept button for amended terms.
- Customer milestones: `ORDER_ACCEPTED` uses factual acceptance copy; `PROPOSAL_AWAITING_RESPONSE` never says accepted/confirmed; `COMPLETED` only after true fulfillment evidence.
- Recovery: **Approve & Execute** primary, **Approve Only** secondary, visible execution status/two-event audit.
- Supplier category: preloaded templates with simple edit path; `UNKNOWN` and incompatible differences visible.
- Capability badges/evidence: show one evidence tier (synthetic, validated with scope, real connection), not `[CONFIRMED]` as if it were an implementation badge.

## 11. Acceptance criteria and non-negotiable tests

**Behavioral acceptance (at least):**

1. SME attempts to accept customer's 100 units as 80 → `409 TERMS_MISMATCH`, **no stock reserved**, Proposal created only by separate explicit command.
2. SME changes price/fee/delivery time or silently adds undisclosed pricing → same outcome; original terms remain unchanged.
3. Customer explicitly approves versioned counteroffer → SME revalidates and reserves before `ACCEPTED`; customer gets factual milestone; response linked to exact proposal/version/identity.
4. Already accepted order amended without customer assent → existing Commitment remains unchanged; no false confirmation.
5. Qwen or Replit unavailable → authorized factual template works where applicable; other responses go to Human Review; no fabricated facts or claimed send.
6. Same issue two **answered** no-progress attempts escalates; real progress resets that issue; unattended customer gets one reminder then expiry/review; total questions/time bounded.
7. Profit inputs missing → `PROFIT_COMPARISON_UNAVAILABLE` while FCFS/valid expiry alternatives remain; CP-SAT result passes shared P2 **joint** evaluation.
8. Supplier offers with mismatched capacity/material + unknown proof are not labelled interchangeable; versioned category templates used.
9. Emergency **Approve & Execute** produces distinct review/approve/execute/audit records from one human click; no action executes without approved exact scope. If execute fails after approve, status remains recoverable and no blind replay.
10. Customer sees only own status; `COMPLETED` only from evidenced `FULFILLED`; milestone sender is idempotent and uses delivery receipt states.
11. Synthetic forecast/seed history is `DEMO-ONLY` and cannot surface a real validation claim; source truth labels propagate to UI/API.
12. Legacy tests for duplicate events, stale versions, unauthorized plan execution, tenant isolation, reservation conflicts and customer agreement remain active.

**Test layers:** pure validators/normalizers; P2 and portfolio property/scenario tests; API auth/version/terms tests; mock Orbyte adapter contract tests; E2E React→FastAPI→Postgres→outbox→customer milestone; idempotency/approval after simulated timeout; migration up/down only where non-destructive and approved.

## 12. Minimum measured-value study (not invented marketing)

Choose **three comparable, scripted** tasks and record manual versus system-assisted time **including human verification**:

| Task | Manual baseline | System-assisted method | Accuracy check |
|---|---|---|---|
| Public FAQ reply | Locate SME published FAQ and type response | Qwen classify + authorized template/Replit path + verify/send | Correct source, no privacy leakage, actual send status |
| Complete customer order | Read multi-turn messages; chase missing SKU/date; enter order | Structured extraction + issue clarification + review | Exact SKU, qty, date and no unapproved commitments |
| Compare three supplier quotes | Open three channel messages/PDFs, reconcile unit/size/MOQ | Offer extraction + versioned category comparison + SME read-through | Correct incompatibility and quote provenance |

For each trial record `task_id`, `dataset/fixture_version`, `participant_role`, `is_real_SME`, `manual_seconds`, `assisted_seconds`, `verification_seconds`, `errors_manual`, `errors_assisted`, `channel_mode`, `sample_count`. Specify counterbalancing or acknowledge order/learning effects. Only calculate reduction after actual times exist: `saving_pct = (median_manual - median_assisted) / median_manual * 100`, report both medians and sample count; if n is tiny, show range and no statistical generalization. Do not claim business adoption/retention improvements from team trials.

For hackathon messaging: use the **hero customer-to-safe-commitment flow plus explicit emergency human-approved recovery** as narrative backbone. Supplier comparison is the evidence bridge. Forecast/Memory are clearly bounded future/predictive intelligence, not a substitute for the value story.

## 13. Risks and fallbacks

| Failure | User-visible safe behavior | Evidence required for integration claim |
|---|---|---|
| Replit inference endpoint/auth unavailable | TemplateGenerator on supported facts; otherwise Human Review | Provider smoke-test, auth handling, no invented endpoint |
| Qwen unavailable | Deterministic validation where possible, else Review | Structured extraction regression |
| Orbyte no published API | Isolated synthetic adapter, `MOCK` tag, no `LIVE` claim | Contract tests; actual API docs for live |
| Inventory reservation async/failed | Show `ACCEPTING`/pending; never `ACCEPTED` | Reservation receipt + commitment write audit |
| Cost/price data absent | Profit comparator unavailable, no guessed margins | Catalog/approved quote version and cost basis |
| CP-SAT unknown/timeout or diverges from P2 | Single-order P2 advisory; no unsafe group recommendation | Solver status + P2 joint certification logs |
| Supplier category lacks spec schema | `SPEC_UNKNOWN`, display raw terms without equivalence | Versioned category template or tenant config |
| No genuine forecast/case history | `INSUFFICIENT_DATA`, synthetic demos flagged | Held-out business history/outcome evidence |
| CTA approved but execution API times out | Query action ID; show approved/unknown, no blind repeat | Idempotency key, remote receipt and reconciliation |
| Customer unresponsive | One reminder, then policy expiry/review | Timer, dedup record, explicit age/limit |

## 14. Owner signoff and code-audit gates

**Owner-confirmed and preserved:** three characters; Qwen analysis; Replit preferred for generated replies; exact-reason human review; SME-only Accept/Reject and supplier choice; per-issue 2 no-progress rule; CP-SAT + 3 strategies; customer status query + auto milestone; human-reviewed and approved Emergency CTA.

**Recommended explicit signoff before implementation of business-policy changes:**

- `SIGNOFF-01` Accept only terms already expressly agreed by customer: unchanged original offer, or exact customer-assented Proposal. All unilateral material deviations require a Proposal (including new price or fees).
- `SIGNOFF-02` Replit remains intended generation provider; template-first factual replies; **no silent Qwen substitution**. Replit endpoint is an integration verification gate.
- `SIGNOFF-03` CTA primary UX one click Approve & Execute while backend keeps approval/execution separate; Approve Only supported.
- `SIGNOFF-04` Timers/max conversation budget are per SME business config; fixture defaults illustrative, not universal contractual timers.
- `SIGNOFF-05` Three category templates, otherwise unknown; supplier selection still doesn't buy anything.
- `SIGNOFF-06` Initial operating agreement semantics, what counts as valid completion proof by business profile, which milestones may auto-send.

**Cannot be certified until inspecting actual repository:** Physical ORM/table/route mapping, precise backward compatibility, live Replit inference, genuine Orbyte adapter, actual test counts, migration safety, and whether specific legacy components are currently operational. Deliver **audit report first**, then implement. All external dependencies remain subject to explicit user-owned credentials/configuration.

### Appendix: verified technical references (not claims of integration)

- Google OR-Tools CP-SAT official guide: https://developers.google.com/optimization/cp/cp_solver — solver statuses and integer-only modeling.
- Google OR-Tools solver limits: https://developers.google.com/optimization/cp/cp_tasks — bounded search.
- Replit AI Integrations product announcement: https://replit.com/blog/ai-integrations — supports adding AI integrations within Replit; **does not establish a callable MouManTAI backend inference endpoint or channel-send API**.

---

**Concluding architecture decision:** preserve the complete MouManTAI product, but make **contracted customer terms, a single P2 semantic validator, a human approval gate, verified business state and provider-neutral adapters** the implementation spine. The immediate next action in the real repository is **read-only legacy audit**, not speculative database migration.
