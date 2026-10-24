# MouManTAI 2.2 — Frontend Requirements Specification

**Status:** Implementation Baseline Review v2.2 · 2026-10-23 · full target UX, with evidence-gated demos and design resolutions pending owner signoff  
**Source of truth:** [`REQUIREMENTS_SYSTEM.md`](./REQUIREMENTS_SYSTEM.md); Backend/API counterpart [`REQUIREMENTS_BACKEND.md`](./REQUIREMENTS_BACKEND.md).  
**Scope:** Full target UX in the Orbyte-embedded SME workspace, plus customer/supplier **messaging experiences** without assuming separate authenticated external portals.  
**Label convention:** `[CONFIRMED]`, `[PROPOSED]`, `[OPEN]`, `[DESIGN-RESOLVED / REVIEW]` as defined in System. Every mock-only UI and synthetic benchmark displays `DEMO-ONLY / SYNTHETIC`; do not report as live Orbyte or real model effectiveness.

## 1. Product experience & navigation

### FE-FOUND-01 — Unified Business Command Center [PROPOSED]

MouManTAI SHALL appear as an Orbyte business module/branch, not a second generic ERP. Landing Overview answers:
1. What should I handle now? Pending acceptance, human reviews, recovery approvals and communications needing action.
2. What has happened? Verified new messages, order status, supplier quotation changes, confirmed disruptions.
3. What could happen? Distinct predicted risks, upcoming schedule overload and inventory exposure.
4. What are the available choices? Deep links to evidence-backed options and current status.

**Suggested routes** (do not forcibly rename functioning routes without migration):

| Route | Page | User purpose |
|---|---|---|
| `/overview` | Business Command Center | Unified KPIs, alerts, tasks, calendar preview, workflow links |
| `/customer-inbox` | Customer Messages | Inquiry, conversational orders, status inquiries, thread/evidence |
| `/orders` | Order Decision Queue | Filter pending vs accepted/rejected, compare portfolios |
| `/orders/:id` | Order Detail | Raw customer request, extracted fields, analysis, decision, timeline |
| `/human-review` | Human Review | Ambiguous/untrusted messages, commercial questions, draft replies |
| `/calendar` | Calendar & Schedule | Accepted vs pending, workloads, deadlines, predicted load |
| `/suppliers` | Supplier List | Offers, latest changes, history, active comparisons |
| `/suppliers/:id` | Supplier Detail | Profile, quote revisions, communication and performance |
| `/supplier-comparison` | Supplier Offer Comparison | Side-by-side requirements and pros/cons |
| `/sourcing/:id` | RFQ/Sourcing Workspace [PROPOSED] | SME request, recipients, responses and comparisons |
| `/forecasts` | Forecast & Planning [PROPOSED] | Demand/stock/supplier/capacity future risk |
| `/emergencies` | Emergency Cases | Verified/reported incidents and impacted commitments |
| `/emergencies/:id` | Emergency Detail & CTA | Options, consequences, **mandatory human approval**, execution trail |
| `/decisions/history` | Decision Memory [PROPOSED] | Past decisions, evidence and verified outcomes |
| `/activity` | Audit / Timeline | Cross-feature correlation, source and state transitions |
| `/settings/business` | Business Configuration | Required order fields, public knowledge, constraints, policies |

Keep redirects for old `/inbox`, `/commitments/:id`, `/impact/:id`, `/recovery/:id` and `/communications` as applicable. Do not introduce P1–P5 nav labels. The app shell shows active tenant/business, user role, connection mode and last-updated time.

### FE-FOUND-01A — Coherent hero workflow and contextual visibility [DESIGN-RESOLVED]

The UI must make one normal SME task completely navigable: customer message → clarification / complete order → **PENDING** → P2 feasibility + original evidence → SME accept → authoritative resource reservation → **ORDER_ACCEPTED** milestone → progress / verified completion. Keep Supplier Intelligence and mandatory-human Emergency CTA as linked workspaces, and full-target Forecast/Memory available without disguising sparse synthetic results as validated learning. For small businesses with no competing pending orders, **show per-order recommendations first**; reveal multi-order portfolios when limited resources actually conflict or a user requests the comparison. Do not force all users through a complex optimizer.

### FE-FOUND-02 — Shared design primitives

- Common Status Badge / Source Evidence Drawer / Actor + Timestamp / Last-Updated / Uncertainty / Action Confirmation Dialog / State Timeline / Empty State / Error + Retry / Version Conflict Banner.
- Separate visual treatment for **verified fact**, **supplier/customer claim**, **computed assessment**, **forecast**, **scenario** and **synthetic demo**.
- Every recommended action explains prerequisites, why, affected orders, uncertainty and whether approval is required.
- Responsive desktop-first layout that remains usable on a tablet/mobile viewport; accessible contrast, semantic controls, keyboard focus, labelled inputs, tables with mobile overflow.
- Money/unit/date formatting must respect currency, physical units and business timezone. Show server-derived timestamps and immutable original received time.
- No placeholder success indicators or counts rendered as production metrics. Demo values display `SYNTHETIC`.

### FE-FOUND-03 — API integration standard

Use React + TypeScript + Vite (reuse installed UI library and Router), TanStack Query or repository's established query client, a single typed HTTP layer and generated/frozen API contracts. Each mutation handles queued/pending, confirmed success, domain reject, auth failure, validation failure, state conflict and retry. Server is authoritative for identity, approval and operational state. No independent frontend stock calculation.

## 2. Customer Inbox & Understanding

### FE-CUS-01 — Unified customer inbox [CONFIRMED]

- Filter by channel (WhatsApp / Telegram / Outlook), intent (`INQUIRY`, `ORDERING`, status inquiry and any supported mixed), resolution/automation state, date and review status.
- Display sender/customer verified-link status, chronological original messages, attachments, source evidence, OCR extraction summary and Qwen interpretation.
- Show whether response generated, pending provider submission, sent, failed, or needs human review. No message claims delivered/read unless provider explicitly confirms.
- Thread view links to `OrderRequest`, unresolved issues, human-review task, communication attempts and milestone updates.

### FE-CUS-02 — Inquiry detail [CONFIRMED]

- Original message + identified question + approved knowledge snippet/source and freshness.
- Clearly indicate `AUTO_REPLY_ELIGIBLE`, `REVIEW_REQUIRED`, `REPLY_SENT`, `REPLY_FAILED`, `INSUFFICIENT_KNOWLEDGE` as API-provided states (names indicative).
- Qwen Analysis panel contains intent, alternate interpretation, confidence/risk reason, authorized evidence, unverified assumptions.
- SME can inspect generated response for historical or review cases; do not present restricted source material as publicly sent.
- Public approved fixed-price FAQ is permitted for safe automatic response. New/custom price, negotiated discounts and delivery guarantees go to review.

### FE-CUS-03 — Ordering draft & field evidence [CONFIRMED]

- Show extracted and required fields with `VALID`, `MISSING`, `AMBIGUOUS`, `CONFLICTING`, `UNVERIFIED` per-field status.
- Each value links to original message/span/source; show versions and amendments rather than overwriting corrections.
- Show progress toward `PENDING_ACCEPTANCE`; information completeness **not** acceptance or fulfillment.
- Show configured business-specific fields rather than hard-code a catering form across all SME tenants.

### FE-CUS-04 — Issue-based clarification timeline [CONFIRMED]

- For each unresolved issue show: field(s), proposed values, original problem, sent clarification questions, customer responses, progress status and **consecutive no-progress attempts**.
- Timeline distinguishes effective answer, ineffective answer, awaiting reply, provider send failure and escalation.
- After **second consecutive answered no-progress**, show `ESCALATED_TO_HUMAN_REVIEW` on that issue with reason. **Show deterministic validator explanation**: SKU candidate set narrowed, quantity/unit validated, explicit date accepted, or no validated delta. Qwen confidence alone is not a progress verdict.
- A different field becoming resolved resets or closes **that field's** issue; not a global conversation counter. Idle/no reply is a **separate follow-up lane**: `AWAITING_REPLY → REMINDER_DUE → REMINDER_SENT_ONCE → REVIEW_OR_EXPIRED`, with configured deadlines, channel/provider status and user-visible explanation. Example demo 24h/48h thresholds are not universal tenant policy.
- Display a **total conversation clarification turn/age budget** (configurable); if exceeded route to review, even if tiny partial progress prevents the per-issue counter. Timer/failed-send is not counted as answered no-progress.
- SME can manually resolve/correct with evidence and role-appropriate audit; clarified draft returns to completeness evaluation.

## 3. Human Review Workspace

### FE-HR-01 — Separate queue [CONFIRMED]

Must NOT be combined into Pending Acceptance. Include ambiguity, unsupported knowledge, risky commercial inquiry, ambiguous supplier/customer association and stuck clarification.

Suggested review list columns: priority/age, task type, received at, customer/channel, original snippet, Qwen intent/uncertainty, affected order, assigned person and status.

### FE-HR-02 — Review details and controls

Display side-by-side or stacked:
1. **Original evidence:** actual customer/supplier message, attachments and timestamps.
2. **AI understanding:** Qwen extracted values, interpretation, confidence rationale and explicit unconfirmed reason.
3. **Authorized context:** allowed business knowledge and linked order details, excluding restricted data in outbound preview.
4. **Recommended next step:** clarify, editable reply, correction, resolve or assign.
5. **Human action:** edit, send (subject to channel policy), manually mark unresolved, or forward for manager review.

All decisions must retain reviewer identity, timestamp, reason and evidence. Backend rejects unauthorized mutation; frontend guard is convenience only.

## 4. Order Decisions & Calendar

### FE-ORD-01 — Order queue [CONFIRMED]

- Separate tabs or filters: `PENDING_ACCEPTANCE`, `ACCEPTED`, `REJECTED`, and applicable amendment/at-risk status.
- Show original received time, information completed time, customer, product/quantity, deadline, delivery/pickup, feasibility status, expected profit **with source/cost completeness label**, stock/expiry/capacity reasons, current recommendation.
- Search/filter by date, product, origin channel, status, priority, risk, customer and order size; support FCFS / Profit / Expiry-aware analysis views.
- Never label a pending order as already reserved or committed.

### FE-ORD-02 — Order detail & assessment [CONFIRMED]

- Explain what the customer requested (original messages + structured fields), what business resources are currently committed, and what can actually be fulfilled.
- Display availability per material, BOM, resource/lot location/expiry, confirmed incoming supply (if any), existing accepted reservations, capacity requirements, schedule conflict and delivery deadline.
- Show reasons for recommendation, hard constraints, assumptions, evidence refs and snapshot age. Where profit appears, display **price provenance** (Orbyte approved public SKU price or authorized quote version) plus **cost coverage** (BOM/stock valuation, labour and delivery if present). Do not render unknown profit as RM0 or an invented estimate.
- Distinguish `FEASIBLE`, `CONDITIONAL`, `INFEASIBLE`, `UNKNOWN`; unknown source or missing cost cannot be glossed over by a positive badge.
- SME can Accept / Reject after reading info. Accept requires confirmation showing order version, resources to reserve, important terms and effect on calendar.
- On successful acceptance show reservation reference and authoritative new state; on revalidation failure remain Pending and display reason. Do not optimistically commit state.

### FE-ORD-02A — Accept as Requested vs Propose Changes [DESIGN-RESOLVED / REVIEW]

Order Detail must show **original customer-offered terms** next to **proposed SME decision terms**, including line items, quantity, price source/version/disclosure, fees, fulfilment window, delivery location and material conditions. **`Accept as Requested`** applies to unchanged original request, while **`Accept Agreed Proposal`** applies only after customer assents to the exact proposal; both require backend canonical hash and authoritative pricing/agreement completeness; show received-version and stale-evidence warnings. Any changes—including adding an undisclosed price—go through **`Propose Changes`**, a versioned counteroffer requiring exact customer assent before acceptance. Display field-level diff, proposal send/assent state and separate resource reservation status. `TERMS_MISMATCH` must leave Pending unchanged and offer the Proposal flow; never imply the UI's equality check alone authorizes acceptance.

### FE-ORD-03 — Resource-contention portfolio comparison [CONFIRMED capability / DESIGN-RESOLVED presentation]

Three side-by-side/adaptable strategy tabs with backend-computed results:

| View | Display |
|---|---|
| FCFS | Chosen pending orders in arrival order; skipped-by-constraint vs not selected; source time policy. |
| Profit | Feasible portfolio total estimated incremental contribution, cost provenance, included and excluded orders. |
| Expiry-aware | Batch allocations, expiring stock consumed *safely*, estimated avoidable waste, constraints. |

Every strategy shows selected order IDs, excluded order explanations, required stock/lots, expected capacity load, schedule/deadline feasibility, **profit only if the authorized price/cost model is complete**, expiry impacts, solver or evaluation outcome (`NOT_APPLICABLE` for deterministic FCFS, otherwise `OPTIMAL`, `FEASIBLE_NOT_PROVEN_OPTIMAL`, `INFEASIBLE`, `UNKNOWN`, `VALIDATION_MISMATCH`), calculation time and operational snapshot/version. Present **recommendation only**; no one-click automatic accept of entire recommended set without human review and backend revalidation.

Comparison must distinguish hard-infeasible orders from feasible orders omitted due to strategic objective. Unavailable/incomplete cost shows explicit uncertainty rather than fabricated profit.

- Portfolio view is **conditional**: when fewer than two pending orders compete for scarce resources, default to regular P2 order assessments; allow manual "Compare orders" if desired.
- Three strategy outputs distinguish **FCFS = deterministic P2-checked greedy**, **Profit = CP-SAT with complete approved prices/costs**, **Expiry-aware = CP-SAT with lot/FEFO evidence**. Never present an unavailable profit/expiry strategy as a weak numerical score; show `PROFIT_COMPARISON_UNAVAILABLE` or `EXPIRY_COMPARISON_UNAVAILABLE` with precise missing inputs.
- Show canonical shared feasibility result and `portfolio_validation_status`; on `VALIDATION_MISMATCH`, hide any green feasible claim, show safe per-order fallback and diagnostics reference. Explain **not selected under objective** vs **hard-infeasible** distinctly.

### FE-CAL-01 — Calendar [CONFIRMED]

- Month/week/day views with **Accepted and Pending clearly distinguished**; legend, filters, date counts, production slots, delivery/pickup, scheduled workload.
- Click date to see accepted commitments, their resource reservations, pending requests, stock/lot needs, and available capacity.
- Link to order detail and strategy comparison for that date/range.
- **[PROPOSED]** Overlay forecast-risk periods and read-only What-if simulation, clearly distinguished from actually reserved capacity.
- Do not derive order status from frontend color or inferred calendar events; backend state is authoritative.

### FE-ORD-04 — Amendments

- Confirmed order modifications use a separate Amendment panel with existing terms, proposed new terms, initiator, customer communication/consent requirements and revised feasibility.
- Do not hide previous confirmed terms or apply amendment as a simple edit to an Accepted row.

## 5. Customer Status & Feedback

### FE-STAT-01 — Status in SME workspace [CONFIRMED]

- Order detail shows internal states and customer-friendly status, timestamp/source of latest verified transition, outgoing milestone delivery state and full notification timeline.
- Key status transitions automatically enqueue factual **template-based** milestone updates; UI must show this **without inventing an additional AI-generated order confirmation email**. Source event, template version and provider status visible.
- Show unambiguous badges: `ORDER_ACCEPTED` = SME acceptance and reservation; `CONFIRMED_TERMS` = customer/SME agreement about exact terms; amended terms pending agreement remain `CHANGE_PROPOSED`. Customer `COMPLETED` only when Core has evidential `FULFILLED`; reported-complete without verification must not look completed.
- If status notification sending fails, order status can remain valid, but communication failure must be visible and actionable.
- SME can see which customer/channel/order is involved, without accessing other tenants' information.

### FE-STAT-02 — Customer-facing messaging experience [CONFIRMED]

- Customer requests `Where is my order?`; return a reply based on the authoritative and identity-scoped order state.
- Customer receives permitted milestone notification, e.g., **`Your order has been accepted by the business`**, `Preparing`, `Ready`, `Completed` **only when fulfilled with evidence**. Never label original-order acceptance as separate customer consent to an amendment or invent ETA. Status and public fixed-price FAQ replies use approved factual templates by default; optional Replit wording can be used when available and authorized.
- Do not assume a separate customer web portal is required; messaging is sufficient for target scope.

### FE-FB-01 — Completion & customer feedback [CONFIRMED]

- On **evidenced fulfillment** allow a channel-appropriate optional feedback prompt and collect satisfaction/quality/delivery/comments linked to the correct order; timing/template **[OPEN]**. Missing customer response does not invalidate fulfillment.
- Customer feedback responses must not be shown as verified logistics facts or as real feedback when synthetic.
- SME overview/order detail can inspect feedback (access-controlled) and aggregate by SKU/time without exposing identity unnecessarily.

### FE-FB-02 — Daily performance [CONFIRMED]

- Day/week performance derives **orders due**, completed on time, completed late, incomplete from authoritative Orbyte/order events first. Planned workload vs actual units/hours and cause only appear when **measured**; show data coverage, "not measured" and provenance if missing. No mandatory daily logging UI.
- Clearly separate planned production, actually produced, dispatched, delivered and verified completed. If native completion event is unavailable, SME may use **one-click Report Completed** with actor/time/evidence; UI must distinguish `COMPLETION_REPORTED` and `FULFILLED`, not pretend an unsupported click proves delivery.
- **[PROPOSED]** Surface recommendations for reviewing inaccurate duration/capacity assumptions and link to forecast evaluation rather than silently editing business settings.

## 6. Supplier Detail, Comparison & Sourcing

### FE-SUP-01 — Supplier workspace [CONFIRMED]

- List suppliers with business identity, categories, latest offer, pending updates, quotation age, selected history and evidenced performance statistics.
- Supplier detail contains overview, products/specs, current/historical quotes, MOQ/units/cost conditions, delivery history, reported quality anomalies, full linked message/evidence timeline.
- Separate verified delivery records from supplier claims; show sample size/coverage when aggregating supplier performance.

### FE-SUP-02 — Requirement-aware side-by-side comparison [CONFIRMED]

Category selection must show **preloaded editable templates** for food container, perishable ingredient and general supply. Show what spec fields were required, their source/version and `SPEC_UNKNOWN` for unsupported categories; do not force user to author every schema from scratch.

- SME inputs target product and configurable hard properties (specification, safety, quantity, date, location); alternatively opens auto-generated same-category offer group. **Schema source/version shown**: Orbyte Product Catalog or SME-configured `CategorySpec`; absent or unknown spec is labelled `UNKNOWN`, not matched by AI guess.
- Render a column per offer and rows for SKU, specification, dimension/unit, quantity/MOQ, price/currency/normalized unit costs, delivery, terms, availability certainty, historical performance.
- Mark `MATCHES`, `CONDITIONAL`, `INCOMPATIBLE`, `UNKNOWN` with exact violated requirements and evidence. Incompatible offers remain visible as **alternatives**, not silently removed nor marked valid substitutes.
- Pros/cons must reference actual facts/assumptions; distinguish normalization (e.g. per litre) from functional substitutability. No AI-selected default supplier.
- SME selects an offer and records decision reason; show immutable offer version. Post-selection buying/sending is **[OPEN]**. In a Recovery detail, a linked selected supplier offer may appear as `ALTERNATIVE_SUPPLY / CONDITIONAL` until actual availability, specification and permitted procurement are verified; never display it as purchase completed.

### FE-SUP-03 — RFQ collaboration [PROPOSED]

- SME creates sourcing request, chooses supplier recipients and required fields; system drafts common question, shows explicit recipients, risks and terms for human-approved send.
- Reply dashboard shows who replied, what was extracted, what is still missing, outstanding follow-up and whether comparison is now possible.
- Never show a draft inquiry as actual supplier agreement or purchase.

## 7. Forecast & Planning [PROPOSED]

### FE-FORE-01 — Proactive risk views

- Cards/charts for demand by SKU/horizon, stock-out and expiry exposure, supplier delay risk, future capacity/deadline risk.
- Each plot/report shows forecast horizon, last updated, predicted/confirmed differentiation, confidence/interval **only where measured**, data-sufficiency status, model/baseline version and evidence. **Synthetic history and seeded outcomes must show a prominent `DEMO-ONLY` badge and "This chart does not demonstrate real-world forecast accuracy."** Missing real history displays `INSUFFICIENT_HISTORY`, with transparent simple planning scenario instead of fabricated probabilities.
- Calendar overlays risk without changing accepted inventory/appointment facts; allow inspect affected orders/resources.
- Show `INSUFFICIENT_HISTORY`, out-of-date model, or unknown status rather than a visually attractive but false estimate.

### FE-FORE-02 — Actionable planning

- From risk alert navigate to source records, feasible planning/sourcing suggestions and existing order calendar.
- Forecast may prepare a hypothetical scenario but does not directly modify inventory, accept orders, mark an incident confirmed or trigger emergency CTA execution.
- Comparison of forecast vs actual and model error/interval coverage visible in advanced details.

## 8. Emergency Recovery & Mandatory Approval

### FE-EM-01 — Incident management [CONFIRMED recovery retained / PROPOSED broader incidents]

- Incident queue distinguishes predicted risk, reported disruption, confirmed disruption, active recovery and resolved incident.
- Incident detail includes changed fact, linked message/operational event, affected accepted orders, latest impact assessment, lost material/capacity, deadline severity and unresolved sources.
- Do not convert every forecast alert into a confirmed incident.

### FE-EM-02 — Recovery option comparison

- Display >=1 safe/conditional candidate when calculable; no-plan state is valid. Explain effects per order, additional costs, supplier assumptions, customer agreement dependencies, new schedule, risks and source evidence.
- Show side-by-side, rank only under selected SME business preferences; do not claim globally best supplier/plan.
- Optional historical similar cases with verified outcomes and conditions, visually separate from current proof.

### FE-CTA-01 — Human Review and Explicit Approval [CONFIRMED, MUST]

- For **every emergency Change-to-Action**, SME must inspect selected plan and explicit action preview before the `Approve` action is available.
- Approval screen displays plan/version, actor authority, scope, affected commitments, business snapshot/preconditions, estimated cost/limits, target systems, customer consent requirements, expiration and irreversible implications.
- Controls: `Approve`, `Reject`, `Request Revision`, with mandatory appropriate decision reason and permission validation.
- There is **no** auto-execute toggle, AI approval button or automatic execute-on-suggest behavior for emergency actions.
- If already approved but current state differs, show `INVALIDATED / REAPPROVAL_REQUIRED` with the reason; no hidden execution.

- Present the exact reviewed plan/action scope once. **Primary `Approve & Execute` is one explicit SME click**, then the client calls two distinct audited backend commands in order (`approve` then `execute`); **secondary `Approve Only`** supports deferred execution, with a later `Execute Approved Plan` action. Neither plan rendering nor AI suggestion executes anything. Server guard remains final authority; harmless draft creation/viewing notifications needs no CTA approval.

### FE-CTA-01A — Single-step SME approval UX with two backend commands [DESIGN-RESOLVED / REVIEW]

The **primary button SHALL be `Approve & Execute`** after the exact plan scope, effects and evidence are visible, and an authorized SME explicitly confirms. The UI then calls the separately audited `approve` and `execute` APIs in sequence. This is **one human action**, not AI authorization; the execution command still checks current plan/version/resources. Provide secondary `Approve Only` for deferred execution. If only approval succeeds, show `APPROVED_AWAITING_EXECUTION`; if execution receipt is unknown, show `EXECUTION_STATUS_UNKNOWN` with safe status refresh and no duplicate blind execution. Explain that plan approval does not equal verified outcome; customer contractual assent is separate.

### FE-CTA-02 — Execution & evidence

- After explicit approval: separate `Approved`, `Revalidating`, `Executing`, `Verifying`, `Succeeded`, `Failed`, `Needs Reapproval` timeline states.
- Show what actions actually ran, provider/mock receipts and genuine follow-up; explain customer agreement and operational fulfilment separately.
- UI must not turn optimistic 200/202 responses into completed business outcomes.

## 9. Decision Memory & Audit

### FE-MEM-01 — Decision memory [PROPOSED]

- Search case history by incident/order/supplier type, dates, SKU and linked constraints.
- Case detail displays situation snapshot, assessed alternatives, SME choice and rationale, authorized actions, outcome verification, costs, similarities/differences with current case. Seeded cases show `DEMO-ONLY`; if no verified historical pool exists, show **"Not enough verified decision history yet"**, not hallucinated learned recommendations.
- A previous successful choice is labelled historical evidence, not current authorization or guarantee.

### FE-AUD-01 — Unified Activity

- Timeline correlates original message → structured interpretation → order review → feasibility/portfolio → acceptance/reservation → status → completion/feedback and any incident/recovery.
- Preserve actor, event, time, source/evidence, old/new versions, integration mode, failures and approval reason; hide sensitive data by role.
- Filtering by order/customer/supplier/incident, status and date, with deep links to current detail.

## 10. Business Configuration & permissions

### FE-SET-01 — Tenant-specific policies [PROPOSED UI; backend enforcement REQUIRED]

- Business Profile / Product Catalog and allowed Customer Knowledge (public vs restricted).
- Order required fields, units and constraints; staffing/capacity/working hours; inventory lot/expiry use.
- FCFS policy setting if product owner approves; other optimization objectives are confirmed but not adjustable weights yet.
- Notification templates/channels and provider connection mode; RFQ policy; SME authorization matrix; forecast thresholds.
- Display effective role and prevent unauthorized settings editing; never send private data to LLM through frontend bypass.

## 11. Frontend data contract expectations

The backend should return typed data for:
- `SourceMessageSummary` (channel, source_message_id, verified identity, timestamp, excerpt, evidence_refs);
- `ConversationSession`, `UnresolvedIssue`, `OrderDraftVersion`, `HumanReviewTask`;
- `OrderRequest`, `OrderDecisionAssessment`, `FeasibilityAssessment`, `PortfolioScenario`, `ResourceReservation`, `Commitment`;
- `CustomerOrderStatus`, `StatusNotification`, `CustomerFeedback`, `DailyFulfilmentSummary`;
- `Supplier`, `SupplierOffer`, `SupplierComparison`, `SupplierPerformanceRecord`, `SupplierSelection`, `SourcingRequest`;
- `ForecastRun`, `RiskAlert`, `DisruptionIncident`, `RecoveryPlan`, `ApprovalDecision`, `ActionExecution`, `DecisionMemoryCase`, `AuditEvent`.

All IDs stable strings and tenant-scoped; timestamps offset-aware ISO 8601; money/quantity decimal strings, not floating point. Include versions and source evidence refs. UI should never reconstruct backend constraint decisions from incomplete frontend subsets.

## 12. Frontend acceptance criteria / user journeys

| Test ID | Journey | Required visible result |
|---|---|---|
| FE-UAT-01 | Customer asks approved public question | Grounded automated reply shown in message timeline; actual channel submission status separate. |
| FE-UAT-02 | Customer creates ambiguous order | Correct per-field extraction/issue tracking; meaningful-progress clarification; separate review if stuck. |
| FE-UAT-03 | Complete order | Appears under Pending Acceptance, not already accepted; opens evidence-backed analysis. |
| FE-UAT-04 | Select FCFS / Profit / Expiry-aware | Actual backend portfolio changes and reasons visible; no action performed automatically. |
| FE-UAT-05 | SME accepts order | Review and revalidation; final state/reservation from backend; calendar updated. |
| FE-UAT-06 | Status changes | SME sees new state and customer milestone send status; customer inquiry returns matching authoritative state. |
| FE-UAT-07 | Order completes | Optional feedback can be recorded; daily planned/actual completion view updates. |
| FE-UAT-08 | Two supplier offers differ | Visible hard requirement mismatch and grounded pros/cons; human choice stored. |
| FE-UAT-09 | Forecast alert [PROPOSED] | Visible future-risk qualification and evidence, not labelled confirmed incident. |
| FE-UAT-10 | Emergency CTA | No execute path before authorized human review/approval; approved scoped action shows real execution evidence. |
| FE-UAT-11 | Decision memory [PROPOSED] | History displays previous choice and *verified* outcome or obvious synthetic demo/no-history badge without claiming learned recommendation authority. |
| FE-UAT-12 | Clarification response absent | Distinct one-reminder + timeout escalation timeline; does not inflate issue no-progress counter or silently expire with no trace. |
| FE-UAT-13 | Status/fulfilment semantic | Accepted milestone describes SME acceptance only; amended terms need consent; reported-completed does not show Completed without verified fulfilment. |
| FE-UAT-14 | Profit/forecast evidence gap | Missing cost makes Profit unavailable; synthetic forecast explicitly demo-only; no fake precision. |
| FE-UAT-15 | Recovery one plan approval | SME sees approval scope once, then separate guarded Execute command; rejection never causes action. |

## 13. Frontend delivery conventions

- For each page/mutation: loading, empty, partial/unknown, conflict/stale, error, permission, retry and integration-mode states. Show `MOCK_ORBYTE`/`SYNTHETIC` clearly; never hide real integration gaps.
- Include a concise **Risk & Fallback** pane in demo/admin or docs: Qwen/Replit unavailable → approved templates/review; Orbyte absent → mock bounded-context adapter; CP-SAT unavailable/timeout → P2 single-order explanation; profit missing → no fabricated profit optimization; forecasting unvalidated → demo-only baseline.
- Make live API connectivity and semantic correctness a separate completion requirement from visual readiness.
- Test with Vitest + Testing Library for state transitions, conditional actions, queue separation, statuses, sourcing comparison and CTA mandatory approval. Cross-page E2E should exercise real backend/test adapter—not local fake `setState` success only.
- Document `CONFIRMED`, `PROPOSED`, `OPEN`, and current implementation status in PR; avoid misrepresenting unbuilt design as shipped feature.

## 14. Final UX implementation gate — v2.2

- Use one **capability × evidence tier** viewer for internal operator/QA; statuses about owner decisions are not UI feature-completeness badges.
- `ACCEPTING`, `PROPOSAL_AWAITING_CUSTOMER`, `ACCEPTED`, `COMPLETION_REPORTED`, `FULFILLED` must have distinct status copy and never infer customer agreement/fulfilment from message-send status.
- Provide reviewable measured-value journeys for public FAQ reply, clarification/order-ready assembly and three-quote supplier comparison; instrument interaction timing without invented claims.
- Never remove existing recovery approval routes/tests until a real repo dependency audit is complete. See `IMPLEMENTATION_BLUEPRINT.md` for required acceptance and rollback rules.
