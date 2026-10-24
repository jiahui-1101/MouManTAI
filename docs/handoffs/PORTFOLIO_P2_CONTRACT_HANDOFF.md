# Phase 4 — Portfolio Solver contract audit and P2 handoff

Audit date: 2026-10-24 (Asia/Kuala_Lumpur).
Baseline: 2129352, preserved on feat/orders-planning-integration. User explicitly
requested implementation on frontend-orders-planning, overriding the attachment's
suggested new branch. The old branch was a verified ancestor and fast-forwarded;
no history rewritten, Main changed, push, migration or seed performed.

## Verified implementation and runtime

- Canonical requirements: docs/requirements/v2.2/REQUIREMENTS_FRONTEND.md FE-ORD-03.
  docs/frontend/AGENTS.md and docs/frontend/ORBYTE_DESIGN_SYSTEM.md are absent;
  existing shared/ui, foundation tokens and Overview/Queue styles were reused.
- backend/app/optimization/models.py contains PortfolioRequest, ComparisonResult,
  PortfolioScenario, ProjectedPortfolio and JointVerificationResult; strategy
  enum is FCFS / PROFIT / EXPIRY_AWARE. These are Python consumer/service models,
  NOT a published frontend HTTP DTO. Frontend's provisional EXPIRY mapping must
  be confirmed by the owner before any HTTP integration.
- backend/app/optimization/service.py compare/_verify implements advisory paths;
  LIVE _verify explicitly raises P2_JOINT_VERIFIER_UNAVAILABLE. Synthetic verifiers
  must identify SYNTHETIC_TEST_FIXTURE. A pure service method is not an API.
- backend/app/feasibility/portfolio_readiness.py only checks existing confirmed
  demand; Pending OrderRequest IDs yield PENDING_TARGET_UNSUPPORTED. Profit and
  expiry availability and allocation_authorized are explicitly False.
- app/main.py registers Core, P1, P2 reads, orders preview and synthetic Orders
  reads; no optimization/portfolio HTTP router. OpenAPI on both local runtimes
  was inspected. No Portfolio Solver endpoint is available to wire today.
- Existing /v1/resources/snapshot and assessment/commitment reads are NOT portfolio
  comparison results. They cannot be repurposed to fabricate allocation/profit.
- Ordinary Backend8000 retained PID5056. Read-only Backend8001 retained PID15224.
  Demo source launcher validates exact5434/moumantai_demo and forces Core/P1 to the
  same readonly database. No environment/source/backend/database changes in Phase4.
- Five shared synthetic Queue requests are not proof of Solver eligibility.

## Contract Coverage Matrix

All rows below concern production/runtime Portfolio reads, not test fixtures.
Available/Partial in a Python model never implies an authorized HTTP read exists.

| Field | Backend Available? | Authoritative Source | Frontend Handling |
|---|---|---|---|
| Scenario ID | Missing published identity | Internal PortfolioScenario lacks frontend stable scenario ID/version contract | Provisional validated scenario.id/version only; runtime unavailable |
| Solver Run ID | Partial, internal only | ComparisonResult.portfolio_run_id | Unavailable; no guessed run ID |
| Strategy Type | Partial, internal enum | Strategy FCFS/PROFIT/EXPIRY_AWARE | Fixed display cards; no source means Not evaluated; EXPIRY mapping awaits owner |
| Estimated Profit | Partial input/objective, no authorized read | FinancialEvidence + solver objective unit | Existing metric guard requires authorization, known metric, complete model, currency and evidence; Redacted never usable |
| Selected Orders | Partial, internal only | selected_order_ids + CandidateBinding | Only validated, evidenced presentation allocations; never Queue count |
| Deferred Orders | Missing ratified mapping | No explicit published DEFERRED contract | Unknown/Unavailable; no inferred deferrals |
| Excluded Orders | Partial, internal only | Exclusion.order_request_id/reason_code | Explicit source mapping required; strategic omission != hard infeasibility |
| Capacity Utilization | Missing aggregate/read scope | P2 schedules/resource model, not frontend arithmetic | Source values qualified by missing resource/window basis; no invented percentage |
| Remaining Capacity | Missing published metric | P2 operational authority | Unavailable, never derived from calendar gaps |
| Expiry Risk | Partial lot constraints, missing aggregate | P2 lot evidence + internal constraint spec | Unavailable; no local waste/expiry calculation |
| Delivery Risk | Partial internal diagnostics | P2 snapshot/constraints | Only supplied guarded metric; otherwise Unknown |
| Applied Constraints | Partial internal constraints | P2 common ConstraintSpec | Preserve source findings; no category inferred from prose |
| Explanation | Partial diagnostics/assumptions | Internal scenario limitations/diagnostics/exclusion codes | Guarded source recommendation reason only; otherwise Solver explanation is not available |
| Source Timestamp | Partial internal receipt times | evaluated_at / valid_through | Existing validated snapshot timestamp displayed only for fresh authorized presentation data |
| Snapshot Version | Partial internal models | snapshot_id/version/spec version/watermark | Identity/version mismatch withholds results; no new API mapping |
| Tenant / Actor Scope | Tenant internal, actor read policy missing | Server-owned auth and financial projection policy required | Existing tenant+actor query keys/boundary validation retained; Unauthorized and wrong scope withheld |

Availability semantics retained: Missing/Unknown != zero; Redacted values never
rendered; Unauthorized hides results; stale/expired/future/conflicting source
withholds metrics, allocations and recommendation. Partial coverage never grants
a whole-portfolio recommendation. No client optimization or solver request button.

## Minimum P2 / Optimization / Core owner decisions

This is a proposal to review, NOT an implemented endpoint or approved wire schema.

1. Confirm a server-authenticated, tenant-scoped read operation for an existing
   comparison/run; owner chooses actual URL, method and response DTO. No speculative
   endpoint is added. Frontend source.load(auth, signal) remains the integration seam.
2. Supply stable run/scenario IDs and versions; canonical FCFS/PROFIT/EXPIRY_AWARE
   mapping; solver status, implementation/version and elapsed execution time.
3. Supply considered/eligible request identities with request version, terms revision,
   terms hash and source identity; explain excluded vs deferred vs unknown without
   equating any membership with ACCEPTED or resource reservation.
4. Bind each result to exact snapshot/spec/watermark, resource scope, analysis window,
   timezone, evaluation time/expiry and P2 joint-validation receipt/digests. Confirm
   live JointPortfolioVerifier authority; do not promote fixture receipts.
5. Specify per-field financial access/redaction, approved complete revenue/cost model,
   currency and provenance. Owner defines any permitted differences/comparability;
   UI currently calculates no profit difference or improvement ranking.
6. Provide quantity/unit, requested delivery, source reasons and evidence per allocation;
   define optional metric availability explicitly. Missing values stay unavailable.
7. Provide typed inventory/capacity/expiry/delivery constraint categories, findings,
   assumptions/warnings/exclusion reasons and evidence. Free text is not classification.
8. Define read roles, 401/403/409/error DTOs and safe cancellation/refresh behavior.
   Optional recommendation must identify exact scenario/version/snapshot and rationale.
9. Supply ratified contract fixtures and tests before a production HTTP adapter is wired.
   Existing test-only portfolioTest.fixtures.ts remains test-only; no Demo solver added.

Stage6 status: BLOCKED for actual API integration. Existing feature-local PortfolioSource,
validatePortfolio, freshness guards and cancellation/identity/financial regression tests
are retained. No Stage6 API-integration commit or empty commit is created.

## Safe frontend delivered

Header -> Analysis Scope -> colored Strategy Cards -> Comparison Matrix -> selected
Order Allocation -> Solver Explanation & Constraints -> Decision Navigation.
FCFS blue, Profit-first violet, Expiry-aware amber; colors identify objectives, not
success/approval. Explicit selection label and aria-pressed supplement color. Missing
strategies are disabled and never selected. All original comparison selection, source
ordering and B-01 redaction/recommendation guards remain. Cards/select change only the
selected source scenario and its allocation/explanation; no backend calculation runs.

Matrix keeps fixed strategy columns and grouped financial/operational/inventory/delivery
rows. Unsupported fields stay unavailable. Currency/unit/scope caveats are explicit;
no local profit arithmetic or fabricated chart. Repeated-strategy scenarios require
selecting one source scenario for comparison, rather than implicitly ranking them.

Selected allocation uses explicit frontend presentation enum mapping
INCLUDED->Include, DEFERRED->Defer, EXCLUDED->Exclude, UNKNOWN->Unknown. This mapping
is NOT claimed to be a ratified backend wire enum. Source-bound IDs alone drive View
Details. Quantity/run ID remain unavailable where absent. Failed/infeasible or invalid
validation states withhold positive metrics and allocation recommendations.

Actual page defaults to the honest unavailable state. Rich results, selection, invalid,
redacted and mixed-strategy states are exercised using isolated test fixtures only.
No Core approval, Backend business logic, routing, AuthProvider, seed, .env or database
files changed. No chart dependency or other package installed.

## Final validation (observed)

| Stage | Status | Commit | Tests | Blocker |
|---|---|---|---|---|
| 0 | Read-only audit complete | none | Actual code/DTO/router/OpenAPI inspected | No authorized Portfolio HTTP read |
| 1 | Complete | 24e1cd2 | 39 focused passed, typecheck/build | Planning scope absent |
| 2 | Complete | c15f6c3 | 40 focused passed, typecheck/build | Runtime scenarios absent |
| 3 | Complete | ee6d100 | 115 focused passed, typecheck/build | No approved extra metrics or comparable window |
| 4 | Complete | 672afb0 | 119 focused passed, typecheck/build | Quantity/run ID absent from presentation contract |
| 5 | Complete | 586a267 | 121 focused passed, typecheck/build | Typed constraint groups/execution metadata absent |
| 6 | Blocked API only; safe source interface retained | no empty commit | Identity/version/financial/freshness tests retained | P2 read DTO + joint verifier + authority |
| 7 | Complete | final test commit | Full suite 1180 passed / 5 skipped / 0 failed | Rich scenarios are isolated test fixtures only |

Exact final command: npm test -- --run --maxWorkers=2 --testTimeout=15000 --reporter=json.
Typecheck and production build passed; git diff --check passed. Existing Vite bundle-size
warning remains. No packages installed. Net17 additional frontend regression cases.

Browser on existing5173: canonical /planning/portfolio, three unavailable unselected
cards, real keyboard Enter on Refresh. Queue still returns5 shared requests; Dashboard5
commitments. Existing backend PIDs/ports unchanged. Source authentication, financial
redaction, stale/error/unavailable and aliases covered by full frontend tests.

Actual iframe browser measurements (CSS viewports, not jsdom):
-1280px: document1265px client/scroll; three261.6px strategy columns; no global overflow.
-768px: document753px client/scroll; cards stacked674.1px; no global overflow.
-390px: document375px client/scroll; cards stacked321.2px; no global overflow.
An isolated TEST FIXTURE ONLY page also rendered actual source-backed matrix/allocation
states at all three widths; mobile matrix scrolls locally, document does not overflow.
Native Enter on Profit changed active scenario and its first row from Include to Exclude
in that isolated fixture page. These fixture previews never enter production source or
shared Demo runtime. Temporary validation server/pages were outside the original repo.

Ready for Manual UI Testing of layout, responsive behavior, navigation, unavailable
states and read-boundary guards. End-to-end operational Portfolio UAT remains blocked
until the owners ratify and expose the real read contract. No production scenario,
profit, allocation, waste or recommendation is claimed to be connected.
