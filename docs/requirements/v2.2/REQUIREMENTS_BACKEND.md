# MouManTAI 2.2 — Backend Requirements & Contracts

**Status:** Implementation Baseline Review v2.2 · 2026-10-23 · targeted full product, evidence-gated claims  
**Normative business specification:** [`REQUIREMENTS_SYSTEM.md`](./REQUIREMENTS_SYSTEM.md)  
**Frontend counterpart:** [`REQUIREMENTS_FRONTEND.md`](./REQUIREMENTS_FRONTEND.md)  
**Important:** All endpoint/new entity names are **target contracts**, not evidence they exist. Reuse actual legacy models, schema and API where possible. `[DESIGN-RESOLVED / REVIEW]` means an explicit proposed engineering choice requiring owner signoff; `[CONFIRMED]` preserves owner-locked behavior. Evidence tiers: `TARGET`, `DEMO-ONLY`, `VALIDATED`, `LIVE`.

## 1. Architecture, ownership and trust boundaries

**Target pattern:** FastAPI / Pydantic v2 / SQLAlchemy / PostgreSQL modular monolith with domain services, read-only calculation engines, transactional state changes, an outbox and background workers. Keep existing React+TS frontend contracts synchronized through OpenAPI or checked-in shared types. No independent microservice required merely because a product character exists.

### 1.1 Logical modules (not necessarily literal current folders)

| Module | Responsibility | Reuse / constraints |
|---|---|---|
| `core` | Tenant, identity, roles, policies, Commitment Registry, audit, outbox, versions | Preserve existing P5 contracts |
| `message_intelligence` | Channel adapters, ingestion, attachment processing/OCR, GLiNER/Qwen parsing, evidence | Preserve P1 normalization/extraction |
| `conversations` | Inquiry, public knowledge, Replit reply adapter, order drafts, issue clarification, human review | Existing P1 + P4 |
| `orders` | Pending/accepted/rejected, amendments, status, fulfillment, customer feedback | Core + new request domain |
| `feasibility` | Pure inventory/BOM/capacity/deadline constraints, impact recalculation | **One existing P2 evaluator only** |
| `optimization` | Multi-order CP-SAT portfolio solver and explanatory comparisons | Calls feasibility; no duplicate stock authority |
| `suppliers` | Quotations, specifications, compatibility, verified historical performance | Existing ingestion + new models |
| `sourcing` | RFQ preparation and reply consolidation [PROPOSED] | Existing communication send tracking |
| `forecasting` | Evaluated demand/expiry/stock/delay/capacity models [PROPOSED] | Forecast facts separate from authoritative stock |
| `incidents` | Risk/actual disruption, affected orders and severity | Existing impact and recovery |
| `recovery` | Validated plans, **mandatory human approval**, controlled execution and verification | Preserve P3 code, tighten approval |
| `communication` | Replit reply generation, outbound channel transport, templates, status milestones, confirmations | Preserve P4 lifecycle semantics |
| `decision_memory` | Historical case/outcome and retrieval [PROPOSED] | No unsupervised auto policy updates |
| `integrations/orbyte` | Business read, approval callback, notification and write-back adapters [PROPOSED] | Do not fabricate real Orbyte API |

### 1.2 Trust classification

- **Authoritative fact:** Verified Orbyte/operational data, human-approved decision or trusted receipt.
- **Reported claim:** Incoming customer/supplier message not yet verified.
- **Derived calculation:** Feasibility, CP-SAT scenario, estimated contribution, supplier comparison from explicit assumptions.
- **Prediction:** Forecast model output with uncertainty, NEVER authoritative inventory or confirmed incident.
- **LLM interpretation/draft:** Untrusted candidate data requiring schema, evidence and business gates.
- **Human approval:** Verified authenticated SME actor authorizes exact scope; cannot be inferred from model confidence, chat text or previous decisions.

Every significant record includes `tenant_id`, stable IDs, provenance/evidence refs, created/updated timestamps, version and correlation where applicable.

## 2. Canonical data ownership, minimum schema changes, and legacy mapping

**Do not implement the v2.0 logical table-family list as 40+ new physical tables.** Reuse the existing P1–P5 ORM/migration structures, with **one write authority per aggregate**. This is a mapping hypothesis until an actual read-only schema audit is completed; naming in the legacy requirement docs does not establish a physical table.

| Legacy concept / likely current table (verify) | Canonical aggregate / new capability | Migration directive |
|---|---|---|
| `inbound_messages` / contextual source | `SourceMessage` authoritative message/evidence | Reuse, add channel/source refs only as needed; **no duplicate `source_messages`** |
| Existing BusinessContext/order context | Parsed structured fields and order drafts | Extend with `OrderRequest` reference and extraction evidence; preserve existing context IDs |
| Existing `context_reviews` | Typed `HumanReviewTask` for inquiry, order, supplier | Extend, do not build independent approval queues with duplicate state |
| Request/order context | `OrderRequest`: original requested terms, info-complete timestamp, SME decision and source link | Add only missing distinct pending-request semantics; no mirrored `Commitment` decision authority |
| Existing `Commitment` + `commitment_versions` | **Only authoritative accepted terms** + agreement, risk, feasibility and fulfilment dimensions | Reuse Core; link `source_order_request_id`, `terms_version`, original customer evidence |
| Existing proposal/customer confirmation | Proposed **changed** terms and customer assent | Reuse version/identity/expiry policy; never overwrite accepted terms prior to agreement |
| P2 assessments + Inventory/BOM/Capacity | Versioned `OperationalSnapshot` + pure `FeasibilityAssessment` | Reuse shared validator; optimization uses shared canonical constraint input |
| P3 recovery cases/plans/actions | Incident, Plan, Approval, Execution | Reuse/extend; plan-level approval once, execution separate |
| P4 `outbound_messages` | Reply, clarification, reminder, milestone, supplier inquiry | Reuse with `purpose`, `source_event_id`, dedup key; **do not add independent mutable `status_notifications` send state** |
| P5 audit/outbox/event | All domain actions | Reuse immutable events, correlation, idempotency and actor/tenant ownership |
| Supplier offers/specs/performance | CategorySpec(version), SupplierOffer(version), VerifiedDeliveryFact | Add only if absent; link original P1 evidence |
| Portfolio advisory results | PortfolioRun(snapshot ref, strategy, solver status, P2 validation proof) | Derived immutable record; no reservation authority |
| Operational stats/feedback | Event-derived daily read model + optional feedback record | Derive from Orbyte and existing status events first; minimal SME input |
| Forecast/decision-memory | Versioned *derived* records with data-sufficiency and evidence tier | Add only when approved; never a second business fact authority |
| Mock Orbyte inventory/orders | `MockOrbyte` adapter-owned schema/service | **Isolate in `mock_orbyte` schema or separate test/mock service**; app accesses only ports |

**Canonical fields across aggregates:** `tenant_id` from authenticated server context, stable IDs, source evidence refs, decimal-string / SQL `NUMERIC` quantity and money, version, UTC/offset-aware timestamps plus business timezone, `correlation_id`, actor, schema version. Avoid prematurely multiplying orthogonal state tables; store states in the owning aggregates and expose **derived read models** for UI/calendar/notifications.

**Required additive deltas (as missing):** `OrderRequest`→accepted `Commitment` link, per-issue clarification progress and no-reply timer fields, approval-to-execution consumed-token fields, category spec validation/version, supplier quote selection evidence, forecasting provenance/DEMO badge, portfolio evaluator attestation. All changes require a real table/ORM review before Alembic migrations.

## 3. Lifecycle ownership and domain invariants [DESIGN-RESOLVED / REVIEW]

### 3.0 Canonical `OrderTerms`, exact-terms guard and acceptance receipt [DESIGN-RESOLVED / REVIEW]

- Canonical persisted `OrderTerms` SHALL capture line-item catalog SKU/variant, Decimal quantity/unit, fulfilment method, explicit delivery/pickup window/timezone, address/location where needed, special constraints, total/line price, fees/discounts/currency and source evidence. Price provenance includes approved catalog/quote ID, immutable version, pricing policy, and evidence the customer was shown/acknowledged the binding price. Missing agreed essential pricing → `TERMS_INCOMPLETE` or proposal, **not silent accepted terms**.
- Produce `customer_offered_terms_hash` and `current_decision_terms_hash` from validated business values. Only safe deterministic canonicalization may support equality (normalized units, dates, currency and exact field identities); AI semantic similarity is not authority.
- `ACCEPT_ORDER(order_id, expected_request_version, expected_terms_hash, idempotency_key)` MUST reject any mismatch with `409 TERMS_MISMATCH` / `PROPOSAL_REQUIRED`, with **zero reservation/commitment side effects**. `Proposal` is a counteroffer when initial terms have not been accepted, a versioned amendment when a Commitment already exists.
- After customer assents to the **exact** Proposal hash/version, perform fresh P2 and SME acceptance/reservation. If customer assent or catalog price disclosure cannot be proven, do not call terms mutually confirmed.
- If `BusinessCommandPort` reports reservation pending, order state may become `ACCEPTING` but **not `ACCEPTED`** until authoritative receipt and guarded Core write are reconciled. Durable intent, operation IDs, receipt query and compensating/retry policy must avoid orphan reservations/duplicate Commitments.
- These policies are normative proposed implementation resolutions pending owner ratification; they close the critical loophole in the original unchanged-offer shortcut. See `IMPLEMENTATION_BLUEPRINT.md` §3.

### 3.1 Original customer request → accepted commitment

1. `OrderRequest` starts `DRAFT`, `AWAITING_CUSTOMER`, `HUMAN_REVIEW`; after validated completeness → `PENDING_ACCEPTANCE`. None is inventory reservation.
2. Authorized SME issues `ACCEPT_ORDER(expected_request_version, expected_terms_hash, idempotency_key)` with the **exact customer-agreed terms (unmodified original offer OR a versioned counteroffer explicitly assented by that customer)**, including authoritative catalog/quote price provenance; on mismatch return `TERMS_MISMATCH` with no reservation. Latest snapshot is re-read server-side.
3. Common P2 evaluation validates newest authoritative stock/lot/BOM/capacity/deadline; `BusinessCommandPort.reserve_resources(...)` succeeds using concurrency/version safeguards.
4. Only then atomically/equivalently promote `OrderRequest.status=ACCEPTED` and create/activate **one Core `Commitment`** with linked request + exact terms version. For an unambiguous original customer request accepted unchanged, customer original request **plus SME acceptance** establishes the initial agreed terms (`agreement_state=CONFIRMED`); no additional customer confirmation click required. If original intent/terms were not unambiguous, set `AGREEMENT_PENDING` until verified.
5. `OrderRequest.ACCEPTED` **never acts as a separate source of truth for `Commitment.agreement_state`**; both states written together through Core command or reconciled guarded saga. No direct row edits from API/AI.
6. `REJECT_ORDER` is authorized and audited; never reserves stock.

### 3.2 Revised accepted terms and customer assent

For any changed terms: create versioned `Proposal` (`OFFERED`, `AMENDMENT_PENDING`) based on current `Commitment` version; existing accepted terms remain authoritative. Provider `SENT/DELIVERED` is not consent. Match customer response to exact proposal/version, verified identity, terms and expiry. Require SME authorization and fresh feasible reservation delta; only then promote new `agreement_state=CONFIRMED` and update terms. Never show "customer agreed" without this evidence.

### 3.3 Completion vs fulfilment

`fulfillment_state=FULFILLED` requires authenticated operational/delivery completion evidence or tenant-approved equivalent verification, **not** a click-only message or outbound notification. Customer-visible `COMPLETED` is **a projection exclusively of `FULFILLED`**. If SME merely reports done without qualifying evidence, preserve `COMPLETION_REPORTED/UNVERIFIED`, use "verification pending", and do not claim delivery completed. Feedback invitation only after qualified completion.

### 3.4 Other independent dimensions

`feasibility_state` (snapshot-specific), `risk_state`, `recovery_state`, `communication_state` and `agreement_state` remain separate **inside their owner service/core aggregate**; avoid eight independently mutable lifecycle flags distributed across request, proposal and status tables. `UNKNOWN ≠ FEASIBLE`; `SENT ≠ AGREED`; `APPROVED ≠ EXECUTED ≠ VERIFIED`; `FORECAST_RISK ≠ CONFIRMED_DISRUPTION`; Supplier ETA claim ≠ goods received. All events include versions, evidence and idempotency, and are projected to read models. No arbitrary lifecycle `PATCH`.

## 4. Ingestion, extraction and Qwen/Replit responsibilities

### BE-MSG-01 — Channel ingest [CONFIRMED]

1. Verify configured integration mode and relevant sender/provider authenticity when live.
2. Deduplicate provider event/message per tenant, connector and external ID.
3. Store original message and attachment references before downstream processing.
4. Normalize timestamps, encodings, sender aliases and attachment formats; OCR fallback with source spans.
5. Route by verified counterparty/intent to Customer or Supplier paths; ambiguous associations stay unresolved.
6. Emit versioned context event and preserve per-field evidence/confidence.

### BE-MSG-02 — AI pipeline [CONFIRMED]

- Start with deterministic parsing/validation and existing specialized extraction; Qwen for semantic interpretation/ambiguity/evidence summarization where helpful.
- Validate Qwen output against strict Pydantic schema; no dynamic SQL/tools/code/actions from model text.
- Qwen returns intent, candidate values, interpretation/risk explanation and citations to available source refs; confidence alone is insufficient for action.
- Replit provider adapter receives **minimal approved answer context** + a constrained reply brief, generates text; backend validates no unauthorized promises/disclosure and passes to channel-send adapter.
- Transport success and reply generation are different steps. Retry/reconcile provider status and failure via idempotency.
- Replit endpoint, model pricing and delivery capabilities require actual connector discovery; no guessed API contract.

### BE-CUS-01 — Public inquiry gate [CONFIRMED]

- `answerable = authorized_information_present && evidence_current && identity_scope_ok && no_unapproved_commercial_commitment && interpretation_sufficient`.
- Existing published/fixed-price FAQs are eligible for auto-answer within current policy; negotiated/new prices, discount offers and delivery guarantees route to Human Review.
- Reply context from server-enforced public knowledge allowlist with scoped retrieval and redaction. Policy version recorded with reply.
- On uncertainty, create review task including original message, Qwen interpretation, reasons/evidence and safe editable draft; do not auto-send unsupported answer.

### BE-REPLY-01 — ReplyGenerator boundary and factual template-first path [DESIGN-RESOLVED / REVIEW]

- `ReplyGenerator.generate(ReplyContext) -> DraftResult` with `TemplateGenerator` as deterministic baseline and `ReplitGenerator` as selected optional AI-based natural-language provider. Never assume Replit provides a confirmed inference API before endpoint and auth verification.
- **Milestone/status replies, one-reminder notifications and public approved fixed-price/FAQ facts default to allowlisted template+slots**, using authoritative server-filtered fields. Qwen may classify/interpret the incoming request, but not provide operational facts. Replit remains available for controlled free-form wording and other inquiries when verified; a model call is not mandatory for templated replies.
- Enforce backend field-level public knowledge allowlist, validated slot types and per-message authorizations before transport. On external provider failure, use the approved factual template if possible; else `REVIEW_REQUIRED`. Never synthesize a missing ETA, price, stock or customer identity.
- One shared outbound owner (reuse legacy outbound messages); purpose `FAQ`, `CLARIFICATION`, `NO_REPLY_REMINDER`, `MILESTONE`, `RFQ`, `AMENDMENT`, etc. Send attempts/provider receipts are not order state.

### 4.1 Reply provider readiness and controlled fallback [DESIGN-RESOLVED / REVIEW]

Preserve the owner's **Qwen = understanding/analysis; Replit = preferred natural-language reply generation** choice while separating *intended provider* from *verified operational capability*. Replit endpoint/model/auth/approved data disclosure must pass an explicit request/timeout/error/privacy smoke test before `provider_mode=READY`. **Never guess an endpoint or silently substitute Qwen.** `ReplyGenerator` has `TemplateGenerator` for canonical facts, conditional `ReplitGenerator`, and optional separately configured Qwen wording adapter only if approved. `ChannelAdapter` is separate. Failure or unavailable endpoint -> factual template where permitted, otherwise Human Review; no fabricated prices, ETA or implied delivery.

## 5. Conversational ordering and adaptive clarification

### BE-ORD-01 — Order draft assembly [CONFIRMED]

- Extract tenant-configured mandatory fields, normalize quantities via Decimal and explicit units, validate SKU and delivery time in business timezone, append source refs to draft version.
- Only merge new message into an order if the sender/order link is sufficiently verified; no cross-customer/order fuzzy merge.
- Capture unique `OrderRequest`, `order_version`, stable issues and per-field statuses.

### BE-ORD-02 — Deterministic per-issue progress and no-reply follow-up [CONFIRMED core / DESIGN-RESOLVED detail]

Track each issue with `issue_id`, `field_group`, `allowed_candidates_before`, `resolved_values`, `consecutive_no_progress`, `question_count`, `sent_at`, `response_due_at`, `reminder_sent_at`, `expiry_at`, evidence, and issue state.

**Progress predicates (not Qwen judgement):**

| Issue type | Validated progress | NOT progress |
|---|---|---|
| Product/SKU | Exact Orbyte catalog SKU verified, or candidate set **strictly shrinks** via explicit answer | "usual one" with same unknown options, unrelated product, model confidence change alone |
| Quantity / unit | Positive bounded Decimal quantity + permitted unit, or confirmed unit choice | vague "many", wrong unit, unsupported quantity |
| Delivery date/time | Parse to explicit business timezone/date/time window accepted by SME configuration, or narrower valid window | "soon", unchanged broad/ambiguous time, past date error |
| Address/method | Required structured fields validated or known pickup/delivery option explicitly chosen | partial statement with no net reduction in missing fields |
| Specific catalog option | Customer unambiguously picks a previously offered eligible option | free-text restatement with same ambiguity |

Qwen supplies extracted candidates + source spans only; **deterministic validator** decides whether (a) resolved, (b) measurable candidate-set reduction, (c) no progress. New evidence can replace prior candidates only with version/identity checks. A meaningful validated improvement resets that issue's consecutive no-progress; two consecutive **answered** clarification attempts without progress → Human Review. Progress on issue A does not reset issue B.

**Separate inactivity control (preserve P4 follow-up):** time waiting for Customer does **not** count as clarification failure. Per-tenant policy has `response_due_at`, `max_reminders=1`, `escalate_or_expire_at`, business timezone and allowed communication window. **Example fixture only:** reminder after 24h and Human Review/expiry at 48h; not universal hardcoded SME policy. Reminder is event-ID deduped and not sent if already replied/resolved or channel unavailable. After expiry, maintain draft/evidence and show `STALE_AWAITING_CUSTOMER` or assigned review; do not auto-accept/reject.

**Loop caps:** configurable maximum total asked turns per draft and maximum active clarification age even if incremental progress appears; exceed → Human Review instead of infinite questioning. Delivery failure does not advance asked-turn success. `NO_PROGRESS` must only be evaluated on linked customer answers to successfully sent questions.

```text
candidate = qwen_extract(message)  # untrusted
updated_issues = deterministic_validate(candidate, catalog, field_rules, prior_draft)
for issue in updated_issues:
    if issue.resolved: close_and_append_version(issue)
    elif issue.validated_progress: issue.consecutive_no_progress = 0
    elif issue.has_customer_answer_to_delivered_question: issue.consecutive_no_progress += 1
    if issue.commercial_risk or issue.consecutive_no_progress >= 2 or total_budget_exceeded:
        open_human_review(issue)
    elif issue.still_unresolved: plan_focused_clarification(issue)
# independent scheduled task: if no reply at due time -> one reminder -> expired/review
```

### BE-ORD-03 — Human review and confirmed amendments

- Separate task class for ambiguity, identity conflict, commercial question and stalled issue; reviewer edits evidence-backed order fields, not raw message history.
- Draft correction appends new version and preserves origin; confirmed commitment changes start versioned amendment with SME approval, customer agreement where required, new feasibility and reservation delta.
- Upon complete valid fields → `PENDING_ACCEPTANCE`; never auto-accept.

## 6. Deterministic feasibility & order acceptance

### BE-FEA-01 — Reuse only one calculation kernel [CONFIRMED]

Preserve P2-style **pure** `evaluate_feasibility(operational_snapshot, requested_order_or_plan, assumptions)` returning structured result and constraints. One function/service shared by new order assessment, portfolio optimization prechecks and emergency plan validation. Do not make it mutate authoritative inventory.

Key inputs: order items / BOM, required production/use times, existing accepted/reserved allocations, raw stock lots with safety/expiry, verified incoming delivery, machine/staff schedule and business deadlines. Conditional future supplier quote does **not** count as confirmed inventory.

### BE-ORD-ACC-01 — Human decision and reservation [CONFIRMED]

1. Accept request initiated only by authorized authenticated SME.
2. Check `expected_order_version`, current operational snapshot and readiness.
3. Compute feasibility with all accepted commitments fixed and respect hard stock/lot/capacity constraints.
4. Atomically reserve stock/capacity in the authoritative resource system (local Postgres transaction with locks/serializable version checks, or a properly defined remote Orbyte reservation operation with reconciliation).
5. Only after confirmed reservation, transition OrderRequest/Commitment state to accepted; atomically append audit/outbox where local DB is authority.
6. If reservation/validation fails, no success state; remain pending and show conflict reason.
7. Reject is SME-driven state transition and audited; automated recommendation alone cannot trigger it.

For remote APIs without an atomic transaction spanning both systems, use a controlled state (`ACCEPTING/RESERVING`) and idempotent saga + reconcile/compensate instead of claiming distributed atomicity.

## 7. Multi-Order Optimization — one constraint authority, two search techniques

### BE-OPT-01 — Business trigger and input provenance [CONFIRMED capability / DESIGN-RESOLVED applicability]

- Normal case: one pending order or multiple orders not contending for scarce resources → **P2 single-order deterministic assessment**, not forced solver execution.
- Portfolio case: ≥2 eligible pending orders share a constrained material lot, capacity interval, or SME explicitly requests comparison. Demo fixture must include a **two-order contention** with validated BOM/stock/capacity facts; never claim resource contention typical for all SMEs without evidence.
- Freeze authoritative read snapshot, accepted commitments/reservations, product/BOM rules, price/cost facts (when relevant), business timezone, precision/scaling and policy versions. Pending order inclusion `x_i` is **advisory** and never directly changes stock.

### BE-OPT-02 — Shared P2 constraint semantics and CP-SAT verification [MUST]

1. Preserve exactly one P2-style `evaluate_feasibility(...)` and **one versioned constraint definition/builder** (`ConstraintSpec`) as the semantic authority for stock ATP, BOM, compatible valid lot allocations, expiry-at-use, incoming supply certainty, manufacturing windows, staffing/equipment, deadline, location and accepted reservations.
2. The optimization layer compiles CP-SAT constraints from `ConstraintSpec`, **not** from duplicated feature-local formulas with separate semantics. The solver may express integer lot assignments and optional intervals (scheduling requires a mathematical encoding), but cannot redefine business meaning.
3. Only compatible, quality-verified and time-valid lots may be assigned; the solver constrains joint assignment of every selected pending order on shared resources, with existing accepted commitments fixed. Use **scaled integers** from Decimal with explicit rounding/overflow checks.
4. **Mandatory post-solve P2 verification:** assemble a *projected operational snapshot* containing all selected pending orders, their **joint lot and capacity allocations**, fixed accepted reservations and scheduler output. Validate the **whole portfolio allocation** through the common evaluator and each selected order against that same projection. **Per-order validation on the old snapshot alone is insufficient** because it misses shared contention.
5. Persist `constraint_spec_version`, solver version, snapshot ID, projected allocations, `p2_validation_ids` and `validation_status`. Any solver/P2 disagreement → `VALIDATION_MISMATCH`, log reproducible diagnostics and **do not show the portfolio as feasible or actionable**.
6. On missing mandatory data, return `UNKNOWN/CONDITIONAL` with evidence reasons; solver `UNKNOWN` or timeout is not proof of infeasibility.

### BE-OPT-03 — Three business strategy projections [CONFIRMED]

**FCFS:** deterministic greedy candidate inclusion by configured verified received timestamp + stable ID tie-break, invoking P2 portfolio feasibility after *each candidate addition*. **No CP-SAT requirement for FCFS**; it is still part of the same three-strategy Optimization API. Protect accepted reservations, never implicitly override prior customer promises.

**PROFIT:** CP-SAT maximize **estimated incremental contribution**, not revenue. `revenue` source must be an approved Orbyte catalog fixed price or an SME-approved customer-specific quote **matching exact product/quantity/terms/version**. `incremental_cost` sources: versioned BOM/lot costs from Orbyte inventory/purchasing, configured production/labour rate and delivery/set-up where available; mark omitted shared costs. Never let Qwen invent missing prices, costs or discounts. If required data absent/outdated, return **`PROFIT_COMPARISON_UNAVAILABLE`**, not zero-cost/high-profit recommendation. Profit optimization is only eligible for a verified-data subset; show coverage prominently.

**EXPIRY_AWARE:** CP-SAT joint FEFO-compatible allocation with safety/use-time constraints; objective to minimize avoidable expiry waste over specified horizon, with declared tie-break. Unknown future demand must be explicit; do not infer wasted units without assumptions. When lot/expiry data absent, mark `EXPIRY_COMPARISON_UNAVAILABLE` and offer FCFS assessment.

**Output:** scenario `{strategy, order_ids, excluded_reasons, joint_allocations, schedule, objective_value/unit, evidence_refs, snapshot_version, solver_status, p2_validation_status, limitations}`. `NOT_SELECTED_UNDER_OBJECTIVE` ≠ `INFEASIBLE`. Respect `OPTIMAL`, `FEASIBLE_NOT_PROVEN_OPTIMAL`, `INFEASIBLE`, `UNKNOWN`, `VALIDATION_MISMATCH` and unavailable inputs. No AI-created opaque "ranking score".

### BE-OPT-04 — Safety, user decision and graceful fallback

- Show strategy-specific scenarios only after successful joint P2 verification. Timeout/validation mismatch → clearly labelled no portfolio guarantee; fall back to P2 **per-order feasibility** and a transparent FCFS view if it can be validated; do not invent a solver optimum.
- SME still manually chooses Accept/Reject. On execution, re-read current authoritative snapshot and P2 validate/atomically reserve before changing `OrderRequest`/Core Commitment; saved portfolio is never permission to reserve.
- No independent solver stock or capacity cache becomes a business fact store. Keep a reproducible 2-order stock contention fixture plus multi-lot expiry and schedule regression fixtures.

## 8. Customer status, engagement and operational feedback

### BE-STAT-01 — Canonical read-model projection [CONFIRMED]

- `ORDER_ACCEPTED` customer milestone maps to **successful SME acceptance + authoritative reservation**. **Never call it customer confirmation of changed terms**; customer-visible wording: "Your order has been accepted by the business." Original customer request + unchanged SME acceptance can support agreed terms in Core; amendments require new explicit assent to versioned proposal.
- Customer-visible `COMPLETED` maps **only** from `Commitment.fulfilment_state=FULFILLED` with credible completion evidence. `COMPLETION_REPORTED` remains internal or visible as verification pending, never silently converted.
- `PREPARING`, `READY`, `OUT_FOR_DELIVERY` require recorded corresponding operational events. Identity-scoped `GET status` returns only linked order data; Qwen identifies status intent but cannot calculate fact/status. Return authoritative factual slots.

### BE-STAT-02 — Milestone messages [CONFIRMED / DESIGN-RESOLVED template default]

- Domain event → idempotent outbox → existing P4 outbound message owner (`purpose=MILESTONE`) → channel adapter. **No duplicate `status_notifications` write authority or separate AI free-form acceptance letter**.
- Template required for `ORDER_ACCEPTED`, `PREPARING`, `READY`, `COMPLETED`, changes/cancel as permitted; template/version, consent/channel capabilities, verified recipient and event dedup key. Replit only optional approved wording enhancement, not mandatory.
- Provider queued/sent/delivered failure tracked separately; status remains authoritative even if notification fails. SME sees last message attempt and error.

### BE-ORD-FOLLOWUP-01 — No customer response follow-up [DESIGN-RESOLVED]

The issue-based clarification scheduler handles no reply separately from answered-but-no-progress: configured wait period → **one** permitted deduplicated reminder → expired/unanswered review at configured later period. Never count a missing response as failed clarification, and never leave indefinite invisible `AWAITING_CUSTOMER`.

### BE-FB-01 — Lightweight actuals and feedback [CONFIRMED product goal / DESIGN-RESOLVED capture]

- Derive daily due/accepted/fulfilled-late/fulfilled-on-time metrics from **Orbyte/order lifecycle events** and their evidence and business timezone. Expose `coverage` and denominator.
- Allow one-click staff **`REPORT_COMPLETION`** with authenticated actor and reference where native operational feed missing; distinguish `REPORTED` from `FULFILLED` until tenant-approved verification criterion is met. Actual duration, exact production quantity and delay cause are optional absent a reliable source; never force complex daily manual logging.
- Optional customer feedback can be invited after evidenced `FULFILLED` through approved template/channel and linked to order; feedback is opinion, not trusted receipt/production actuals.
- Daily planned-vs-actual units/hours only appears when **both values have sufficient evidence**, otherwise show "Not measured" and partial data coverage. Any future capacity parameter proposal needs SME review before changing business rules.

## 9. Supplier intelligence, comparison and selection

### BE-SUP-01 — Supplier offer extraction & storage [CONFIRMED]

- Use normalized source/evidence pipeline; correlate verified supplier identity, product/offer version, quote validity, currency, price/pack/unit, MOQ, pack size, technical specs, delivery terms, quoted lead time and availability **claim status**.
- Normalize units only when conversion is valid and recorded (e.g. volume per pack); store original value and quotation version unchanged.
- Automatic grouping by *compatible normalized product class*; association ambiguity remains unresolved, not forced.

### BE-SUP-02 — Versioned category specification + requirement-gated comparison [CONFIRMED / DESIGN-RESOLVED]

**Low-burden configuration:** preseed editable versioned `food_container`, `perishable_ingredient`, `general_supply` templates. Hard fields, unit normalization and quality/safety evidence are category-specific; owner edits only exceptions. Absent category/template or absent required hard field -> `SPEC_UNKNOWN`, no AI-declared equivalence. These are starting templates, not universal business truths.

- Category schema and required dimensions come from **versioned Orbyte product catalog** when present, or SME-authored per-category configuration (`CategorySpec`) when Orbyte lacks it; record schema version and owner. E.g., container: capacity, material, heat safe; produce: grade, freshness/storage rules. Unknown field means unknown, not interchangeable. Never let Qwen create mandatory schema on the fly.
- SME requirement includes product functionality, non-negotiable specification fields, quantity, location, desired arrival and safety/quality restrictions.
- Evaluate each offer: `MATCHES`, `INCOMPATIBLE`, `CONDITIONAL`, `UNKNOWN`, violated requirements and source refs.
- Only compare standardized costs under defensible equivalent dimensions; do not equate different freshness, heat resistance, size or sourcing terms solely due to normalized unit price.
- Produce evidence-grounded pros/cons and missing-data list; LLM may explain structured comparison, not override hard constraints or choose supplier.
- No automatic purchase or external purchase obligation on comparison result.

### BE-SUP-03 — Historical performance [CONFIRMED]

- Link Orbyte purchase/delivery records with source messages, separating verified promised vs actual date/quantity/quality facts and unverified supplier explanations or claims.
- Historical metrics include on-time numerator/eligible denominator, delays, completeness, exceptions and evidence coverage, with sample size and time window. Missing records means unknown/insufficient history, not a low score or proof of fault.
- Quote corrections and event source changes remain auditable.

### BE-SUP-04 — SME selection & RFQ [CONFIRMED / PROPOSED]

- SME selects offer(s) from comparison by authenticated action, stores selected quote/version, actor and reason. Do **not** create binding purchase automatically; handoff **[OPEN]**.
- For recovery, `ALTERNATIVE_SUPPLY` can **reference** that selected offer/version as evidence, but remains `CONDITIONAL` pending verified supplier availability, required specification/ETA, SME approval of recovery plan and authorized purchasing/transport steps. Never treat quote selection as inventory receipt or CTA execution.
- **[PROPOSED]** RFQ case: SME composes requirement/recipients, system prepares identical compliant inquiry, human authorizes outbound send, messages correlated to case, side-by-side replies and unanswered required fields visible.

## 10. Forecasting and forward-looking planning [PROPOSED full target; evidence-gated]

### BE-FORE-01 — Initial transparent baseline

- Support a basic moving-average or seasonal-naive demand baseline plus **deterministic forward inventory/capacity scenarios** derived from dated accepted orders and known confirmed resources. These are useful planning mechanics even without ML.
- On a self-generated synthetic history, label predictions, charts and in-sample/out-of-sample exercises `DEMO-ONLY`, with fixtures/method and no claims of validated accuracy, improved SME business outcomes or generalization. A synthetic backtest tests pipeline mechanics, not real-world predictive skill.
- If there is no credible historical series, `INSUFFICIENT_HISTORY` / descriptive scenario only, not a numeric AI-predicted certainty. Qwen may phrase the structured result but never invent numbers.

### BE-FORE-02 — Full target model and evidence gate

- After real chronologically separated Orbyte/SME operational history is available, evaluate naive baseline vs suitable intermittent-demand methods, optionally structured ML/time-series models. Track external data cutoff, horizon, model/version, training leakage checks, hold-out period, WAPE/MAE/MASE where appropriate, interval coverage, sample size and model-vs-baseline difference.
- Target four families: demand, stock-out/expiry exposure, supplier delay, capacity/deadline risks. Supplier data sparsity/selection bias must be disclosed, and non-applicable numerical risk probabilities omitted.
- `ForecastRun`: evidence tier, tenant/target, data origin, input cutoff/window, model, predictions and intervals if justified, known future covariates, limitations, retrospective evaluation evidence; `ForecastAlert` is **advisory** and never a confirmed disruption.
- No model self-training or business policy update from synthetic performance or unverified customer feedback. Maintain ability to extend but do not claim maturity without evidence.

## 11. Incident management & human-governed Change-to-Action

### BE-EM-01 — Incident classification

Support `PREDICTED_RISK`, `REPORTED_DISRUPTION`, `CONFIRMED_DISRUPTION`, `RESOLVED` with evidence and actor. Distinguish supplier ETA claim awaiting verification from authoritative operational change. Proposed additional triggers: stock loss, power/water outage, equipment/staff shortage, logistics failure, customer amendment.

### BE-EM-02 — Impact & recovery plans

- Confirmed incident recalculates **actually affected accepted commitments** via the same pure feasibility evaluator; no blanket all-orders-at-risk for a supplier.
- Generate typed options (`ALTERNATIVE_SUPPLY`, `LOCAL_SOURCING`, `RESCHEDULE_PRODUCTION`, `RESOURCE_REALLOCATION`, `PARTIAL_FULFILMENT`, `NEGOTIATE_DELIVERY`, `ESCALATE_MANUALLY`) with prerequisites, cost, delay, other commitments affected, constraints and evidence.
- Candidate may be `CONDITIONAL` if supplier quote/availability or customer agreement missing. `ALTERNATIVE_SUPPLY` must reference supplier comparison/selected offer version and cannot be declared guaranteed until availability, compatibility, ETA and required human procurement authority are verified. Ranking is under SME policy, not model-proclaimed absolute best.
- No safe option is a valid outcome; create human escalation rather than fabricate recovery.

### BE-CTA-01 — Mandatory Human Review and Approval [CONFIRMED, NON-NEGOTIABLE]

**Never execute any Emergency Change-to-Action without a prior explicit approval from an authorized human SME for the exact version and action set.** This includes internal synthetic/mock resource/scheduling actions that are part of an emergency plan. No trust-score exception, no default preapproval, no generated model approval.

Required sequence:

1. Persist specific incident, plan ID/version, based-on assessment/snapshot, action IDs, effects, cost ceilings, affected commitments, required customer agreement.
2. Create `REVIEW_REQUIRED`, show evidence and alternatives.
3. Receive authenticated SME `APPROVE` / `REJECT` / `REQUEST_REVISION` decision; server validates tenant, role and plan/current terms; audit human actor/reason/time/scope/expiry.
4. **One explicit plan-level approval** may cover multiple enumerated low-level actions and cost/authority boundaries; do not force separate clicks per action. `APPROVE_PLAN` only grants **one-time scoped execution authorization**; it **never executes**. A separate `EXECUTE_APPROVED_PLAN` command consumes the authorization after all guards pass. Automatic risk alerts, analyses, harmless notifications and draft generation are not CTA execution.
5. Immediately before action side effect, re-run feasibility, snapshot/preconditions, existing reservations, authorization, limits and plan version.
6. Material change or expired approval → `INVALIDATED / REAPPROVAL_REQUIRED`; **new human review & approval** mandatory; never auto-expand scope.
7. Use typed allowlisted action adapters, idempotent operation IDs, provider-status reconciliation and durable attempt/receipt evidence.
8. Verify results independently; `submitted`/`sent` != executed/fulfilled; subsequent customer agreement and logistics/production completion are separate events.

**Any draft message generation, incident analysis, candidate plan building and simulation may run automatically; the consequent emergency business action may not.**

### BE-CTA-02 — Action classes and communication

- Actions may create tracked internal tasks, adjust approved scheduling resources, initiate an approved sourcing workflow, or prepare customer amendment communication, **only within explicitly approved plan scope**.
- No real money movement, purchase charge or external binding obligation without additional appropriately authorized connector/approval and verified provider capability.
- Customer amendment must bind proposal identity/terms/version, authenticated recipient and expiry. Human-approved internal plan does not equal customer agreement; do not mark commitment changed/fulfilled prematurely.

### 11.1 Approve & Execute: one explicit human click, two durable commands [DESIGN-RESOLVED / REVIEW]

- Backend retains separate, individually authenticated/audited `APPROVE_PLAN` (creates one-time exact-scope approval, **no action**) and `EXECUTE_APPROVED_PLAN` (consumes authorized token and revalidates). Only explicit user interaction can initiate approval.
- Frontend may offer primary **Approve & Execute**: after display of full plan/action scope, a single SME click invokes approve then execute with the returned durable approval ID and idempotency key. This is **not** approval bypass and creates two distinct audit events. Secondary **Approve Only** keeps `APPROVED_AWAITING_EXECUTION` for deliberately deferred action.
- If approve succeeds but execute fails/times out, report `APPROVED_AWAITING_EXECUTION` or `EXECUTION_STATUS_UNKNOWN` and query operation status before retry. Do not auto-retry a potentially executed irreversible side effect. A material change requires new human review and approval.
- One human-approved plan covers its explicit enumerated action set; per-action repetitive approval clicks are not required, while contractual amendment requires its own customer agreement.

## 12. Decision memory and experience learning [PROPOSED full target; evidence-gated]

- Store lightweight references to **existing audit, plan, supplier and outcome records** rather than duplicate all situation facts in new tables. The `DecisionMemoryCase` can be a derived projection `(situation_ref, alternatives_ref, SME decision, reason, outcome_ref, verified status)`.
- Initial synthetic seeded examples may demonstrate retrieval UI, labelled `DEMO-ONLY`; **not** proof that the system learned effective business preferences. If insufficient **verified** case pool, return `INSUFFICIENT_CASE_HISTORY` and make no similarity-based claim.
- Once real historical outcomes exist, constrained case retrieval can show previous choice, actual consequences, similarities/differences and evidence; historical choice is neither a proof of optimality nor permission to perform a new recovery action.
- Never automatically fine-tune Qwen, rewrite BOM/ATP/capacity policy or increase action permissions from customer feedback or unverified outcomes. SME reviews data corrections and proposed configuration changes.

## 13. Orbyte adapters & business authority

### BE-ORB-01 — Adapter interfaces [PROPOSED until official contracts]

```python
class BusinessDataReader(Protocol):
    def get_product_catalog(self, tenant_id: str, ...): ...
    def get_inventory_lots(self, tenant_id: str, ...): ...
    def get_confirmed_orders_and_schedule(self, tenant_id: str, ...): ...
    def get_supplier_purchase_history(self, tenant_id: str, ...): ...

class BusinessCommandPort(Protocol):
    def reserve_resources(self, tenant_id: str, order_id: str, expected_version: int, ...): ...
    def read_reservation_status(self, tenant_id: str, operation_id: str): ...

class ApprovalNotificationPort(Protocol):
    def publish_review_task(self, tenant_id: str, task_id: str, ...): ...
    def verify_approval_callback(self, signed_payload: bytes, ...): ...
```

The code sketch is **illustrative**. Inspect Orbyte official contracts before implementing a live adapter. No assumed external URL, identity scope or storage transaction. Synthetic adapter must state `mode=SYNTHETIC` and provide faithful result/version/error semantics.

### BE-ORB-01A — Isolated mock bounded context [DESIGN-RESOLVED]

When official Orbyte interfaces are not available, mock only **Orbyte-owned facts** (catalog price and SKU, inventory lots, capacity schedule, reservations, purchase/delivery history, identities) within a named `mock_orbyte` database schema or a separate synthetic service. Mock business operations have authoritative operation IDs, version checks, conflict handling and idempotency. **No application repository/service imports or directly writes the mock tables**; only calls `BusinessDataReader`, `BusinessCommandPort`, `ApprovalNotificationPort` interfaces, just as it would call a live integration. Synthetic mode is disclosed on each dashboard/API evidence. Do not claim this is a connected Orbyte tenant.

### BE-ORB-02 — Authority / configuration

- Orbyte/connected inventory system authoritative for stock and actual reservations, configured order/business systems for product/schedule, provider for send receipt, MouManTAI for assessments and review cases.
- Deterministic tenant policy stores required order fields, public business knowledge, product rules, expiry/safety, FCFS time basis, channel consent, approval roles and forecast thresholds.
- Orbyte → intelligence → notification/review → approved response → validated write-back → audit. The UI and API disclose actual connection mode.

## 14. Proposed API surface

**Command semantics that must stay unambiguous:** `POST /v1/orders/{id}/accept` = SME authenticated decision + versioned reservation, response indicates `ACCEPTING` or final `ACCEPTED` with reservation operation and commitment version; `POST /v1/commitments/{id}/amendments` creates a proposal only; `POST /v1/confirmations/{id}/respond` records customer assent to exact terms; `POST /v1/recovery/plans/{id}/approve` grants one-time plan scope without executing; `POST /v1/recovery/plans/{id}/execute` revalidates and executes previously approved plan; `POST /v1/orders/{id}/report-complete` records report, **not automatic `FULFILLED`** unless evidence policy independently validates.

Do not introduce a writable `status_notifications` API separate from existing `outbound_messages`; status notifications are projections of communication-purpose records. Version/API naming stays tentative until checked against real routes.


**Path examples** below; keep compatible old paths via adapter/redirect or versioned mapping where practical. Prefer nouns, command endpoints for guarded state changes, no generic lifecycle PATCH.

| HTTP | Route | Main result / semantics |
|---|---|---|
| `POST` | `/v1/messages/ingest` | Idempotent source message accept, normalized pipeline status |
| `GET` | `/v1/conversations/{id}` | Message thread, interpretation, issue state |
| `GET` | `/v1/conversations/{id}/issues` | Per-issue no-progress count, current state |
| `POST` | `/v1/conversations/{id}/clarify` | Controlled question request/draft/send status |
| `GET` | `/v1/reviews` | Tenant-scoped human review queue |
| `POST` | `/v1/reviews/{id}/resolve` | Authenticated edit/reply/resolve + evidence |
| `GET` | `/v1/orders` | Status/date/priority-filtered queue |
| `GET` | `/v1/orders/{id}` | Order version, evidence, assessments, status |
| `POST` | `/v1/orders/{id}/assess` | Pure feasibility persisted result |
| `POST` | `/v1/orders/portfolios/compare` | Three CP-SAT-based scenarios, solver info, explanations |
| `POST` | `/v1/orders/{id}/accept` | SME guarded acceptance, reservation before success |
| `POST` | `/v1/orders/{id}/reject` | SME audited rejection |
| `POST` | `/v1/orders/{id}/amendments` | Versioned amendment proposal |
| `GET` | `/v1/calendar` | Accepted/Pending events + workload |
| `GET` | `/v1/orders/{id}/status` | Authorized order status/internal audit view |
| `POST` | `/v1/customer/status-inquiries` | Verified channel-linked customer status reply intent |
| `GET` | `/v1/orders/{id}/notifications` | Milestone channel state history |
| `POST` | `/v1/orders/{id}/feedback` | Scoped optional customer feedback |
| `GET` | `/v1/operations/daily-summary` | Planned vs actual by date/resource |
| `GET` | `/v1/suppliers/{id}` | Supplier detail/quote/performance |
| `GET` | `/v1/suppliers/offers` | Structured offers / grouping |
| `POST` | `/v1/suppliers/comparisons` | Hard requirements, differences, evidence |
| `POST` | `/v1/suppliers/selections` | SME-selected offer+reason, **no purchase** |
| `POST` | `/v1/sourcing/requests` | [PROPOSED] sourcing/RFQ case |
| `GET` | `/v1/forecasts` | [PROPOSED] uncertainty-labelled forecasts |
| `GET` | `/v1/incidents` | Confirmed/reported incident list |
| `GET` | `/v1/incidents/{id}` | Incident detail/impact/plan refs |
| `POST` | `/v1/incidents/{id}/plans/generate` | Analysis only, no action |
| `POST` | `/v1/recovery/plans/{id}/approve` | **SME decision** + exact action/version scope |
| `POST` | `/v1/recovery/plans/{id}/reject` | SME decision + reason |
| `POST` | `/v1/recovery/plans/{id}/request-revision` | SME decision / state transition |
| `POST` | `/v1/recovery/plans/{id}/execute` | Hard approval and revalidation guard, verified execution tracking |
| `GET` | `/v1/recovery/plans/{id}/actions` | Actual action statuses and receipts |
| `GET` | `/v1/decisions/history` | [PROPOSED] evidence-linked cases |
| `GET` | `/v1/audit` | Tenant-scoped correlated audit events |
| `GET` | `/v1/overview` | Shared aggregated real business state |

**Authentication:** All internal SME mutation endpoints require server-authenticated actor/tenant; customer-facing status/feedback use verified scoped identity/challenge, not a freely supplied `customer_id`. Orbyte callback requires verified signature/identity contract when available.

**General JSON error shape:** `{"code":"...","message":"...","correlation_id":"...","details":{...}}`. Use `401/403` authorization, `404` safe scoped missing, `409` version/constraint conflict, `422` validation; do not claim asynchronous provider operation completed upon enqueue.

### 14.1 Proposed response: `PortfolioScenario`

```json
{
  "scenario_id": "port_012",
  "tenant_id": "tenant_demo_01",
  "strategy": "PROFIT",
  "snapshot_version": 142,
  "solver_status": "OPTIMAL",
  "p2_validation_status": "PASSED",
  "constraint_spec_version": "p2-v1",
  "selected_order_ids": ["ord_b"],
  "excluded_orders": [{"order_id": "ord_a", "reason_code": "NOT_SELECTED_UNDER_OBJECTIVE"}],
  "estimated_incremental_profit": "320.00",
  "currency": "MYR",
  "stock_allocations": [{"order_id": "ord_b", "lot_id": "lot_02", "quantity": "80", "unit": "pcs"}],
  "scheduled_capacity": [{"order_id": "ord_b", "resource_id": "line_01", "minutes": 120}],
  "assumptions": ["All lots valid at planned consumption time"],
  "evidence_refs": ["ev_stock_03", "ev_capacity_02"],
  "recommendation_only": true,
  "evidence_tier": "DEMO-ONLY"
}
```

Illustrative synthetic response; not a real run. Solver status and example lot allocation must be based on actual valid snapshot in production.

### 14.2 Proposed event envelope

```json
{
  "event_id": "evt_102",
  "event_type": "order.accepted",
  "schema_version": 2,
  "tenant_id": "tenant_demo_01",
  "order_id": "ord_102",
  "commitment_id": "com_102",
  "aggregate_version": 4,
  "correlation_id": "corr_09",
  "causation_id": "evt_sme_accept",
  "occurred_at": "2026-10-23T13:00:00+08:00",
  "evidence_refs": ["ev_reservation_102"],
  "payload": {"reservation_id": "res_102"}
}
```

Events and outbox published at least once; consumers dedupe and handle out-of-order versions. Do not put full PII, source texts or provider keys in event payloads.

## 15. Non-functional requirements

1. **Reliability:** state+outbox atomicity, retry-safe/idempotent channel/action adapters, eventual reconciliation for unknown provider timeouts, meaningful error states; never invent success.
2. **Security:** tenant isolation across DB, logs, media, cache and embeddings; backend RBAC; scoped customer status; externally-supplied prompts treated as data only; least privilege and secret redaction.
3. **Precision:** Decimal/SQL NUMERIC for monetary values and quantities; CP-SAT integer scaling documented; offset-aware ISO 8601 timestamps; business timezone explicit for dates/deadlines.
4. **Provenance:** immutable original evidence, per-field source refs, model/baseline/policy/version snapshots, auditable reviewer/action identity.
5. **Extensibility:** configurable business rules and adapters for different SMEs; live Orbyte capabilities validated rather than guessed; provider swap possible without data model rewrite.
6. **Monitoring:** event/trace correlation IDs; queue retry counts, end-to-end latency, optimizer solve time, forecast freshness/error, feedback coverage, failure modes.
7. **Data lifecycle:** consent, retention/erasure policy, minimal external AI disclosure, audited exports and deletion restrictions to meet applicable organizational/PDPA requirements in production.
8. **Synthetic honesty:** synthetic records and mock adapters remain clearly labelled in API, logs, UI and evaluation evidence.

## 16. Acceptance, legacy regression and measurement requirements

**Existing 1.0 E2E cases remain the regression floor**; preserve names/assertions or provide an explicit compatibility mapping instead of deleting old coverage. In particular: tenant separation, ambiguous customer response, wrong proposal version, supplier reported-vs-verified evidence, duplicate events, stale approval, unauthorized emergency execution and reservation integrity. The owner deferred discussion of extra negative examples, **not** the engineering safety obligations.

| Suite | Mandatory behavior / evidence |
|---|---|
| `BE-STATE` | Original unchanged request: `PENDING` → SME accept + reservation → `ACCEPTED` + Core `CONFIRMED` with both-party evidence; revised terms need exact customer assent; `COMPLETED` projects only evidenced `FULFILLED`. |
| `BE-CLAR` | Deterministic SKU/quantity/date progress; two answered no-progress issue attempts escalate; valid progress resets only that issue; separate one-reminder / timer / expiry; global loop cap; timeout does not count as answered. |
| `BE-REPLY` | Approved fixed-price/FAQ and milestone templates send factual slots; Replit timeout falls back safely; draft/send/delivered statuses separated. |
| `BE-OPT` | 2-order stock-contention example; FCFS deterministic, profit with approved costs, expiry with valid lots; **joint portfolio P2 verifier**; deliberate solver/evaluator mismatch blocked; insufficient cost → unavailable. |
| `BE-ORBYTE` | Mock inventory/capacity/schema accessed only through ports; version conflicts and idempotency; synthetic mode in response. |
| `BE-SUP` | Category schema compatibility and incompatible offers; selected quote ref into conditional alternative-supply recovery option. |
| `BE-FORE/MEM` | Synthetic outputs labelled demo; insufficient history does not claim accuracy or past success. |
| `BE-CTA` | Plan approval one time covers exact included actions, approval does not execute, separate execute command enforces scope/version/revalidation; no unapproved background worker path. |
| `BE-FB` | Operational metrics derived from actual event availability; missing duration not zero; completion report differs from fulfilled; optional customer feedback after evidenced completion. |

**Measured value:** establish timed manual baseline from representative scenarios vs instrumented system flow (same input, same participant conditions, human review time included). Record dataset/participants, median/range, errors, test commands and limitations. Synthetic performance measures mechanics, not actual SME time savings or real model accuracy. Use explicit `PASS`, `FAIL`, `NOT_RUN`, `BLOCKED` in delivery reports.

## 16.1 Minimal measured SME-value protocol [DESIGN-RESOLVED]

Time three comparable manual-vs-assisted tasks—approved FAQ, multi-turn order information completeness and consolidation of three supplier offers—**including human verification**. Log sample size, participant type, scripted fixture version, manual time, assisted time, errors and synthetic vs real status. No fabricated ROI/retention. See Blueprint §12.

## 17. Non-destructive migration and implementation process

1. **Audit actual repo:** read-only `git status`, Alembic migration history, ORM metadata, tables, routes, enums, P1–P5 existing fixtures/tests and outbox events. Do not infer table existence from v2.0 proposal names.
2. Produce `legacy_entity_mapping.md` with **actual** model/table/event IDs and classify `REUSE / EXTEND / ADD / DEPRECATE`; owner/signoff needed before modifying shared schema.
3. Add linkage and read-model projection instead of duplicating existing `Commitment`, review, inbound or outbound message state. Keep existing IDs/history, event consumers and old routes while migrating.
4. Create mock Orbyte bounded context separately, enforce ports even in fixtures; test port parity against any subsequently confirmed official APIs.
5. Generate CP-SAT constraints from shared `ConstraintSpec` and validate projected full portfolios with P2 evaluator before returning recommendation.
6. Keep comprehensive safety/E2E regression baseline and add new tests before old route/table cleanup; rollback plan required for nontrivial migration.
7. Every feature reports `TARGET / DEMO-ONLY / VALIDATED / LIVE` accurately and does not present synthetic predictive backtests as real-world performance.

## 18. Backend open questions (not blockers to read-only design)

The following must be resolved by product/technical owners before claiming a finalized live integration: automatic milestone templates and permitted channels; RFQ/purchase handoff; FCFS time rule; industry and forecast granularity; exact Orbyte APIs/auth/stock reservation/approval callbacks; customer amendment acceptance policy; provider identities; compliant message consent/retention; authorized emergency action adapters. Until resolved, implement safe configurations/mock ports and expose uncertainty—not fabricated guarantees.

## 19. Additional endpoint and compatibility notes — v2.2

- Add `expected_terms_hash`, `expected_request_version`, `idempotency_key` to guarded acceptance requests (or compatible header/DTO) and return `TERMS_MISMATCH` without mutation; add exact Proposal terms/version/hash/price provenance to customer assent flow.
- Add read-only original-versus-proposed term diff for SME and customer messages. If `accept` response is `ACCEPTING`, do not enqueue an Accepted milestone until authoritative reservation receipt and Core commitment are synchronized.
- `GET /capabilities` may return safe environment/evidence info but never secrets or unverified provider labels.
- Phase 0 implementation gate: repo audit of actual models/migrations/routes/tests before any new table or destructive rename; fill `LEGACY_REUSE_MATRIX.md` with path/symbol and migration decision. This document alone cannot certify schema.
