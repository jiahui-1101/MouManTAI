# Orders & Planning integration — 24 October 2026

## Stage 0 verified baseline

Runtime checkout: `codex/order-detail-workspace`, clean at `85ad272`.
Remote main fetched to `f8e147d`; development copy merges that baseline at `c625097`.
PR #76 Orders work and the existing Detail redesign are retained. No main development/push.
`/health` and `/v1/overview`: 200; overview exposes five commitments, not five accepted requests.
`/v1/contexts/by-order/ord_hero_001`: 404.
Read-only SQL against container `moumantai-uat-db-1`, bound only to 127.0.0.1:5434:
database `moumantai_demo`, Alembic `0017_p1_real_channel_provenance`, five exact
order/commitment links, four stocks, three proposals, zero operational snapshots,
zero reservations. Public tables inspected; Core, P2, Recovery, Communication tables exist.
No database/schema changes or seed/reset execution.

## Field authority and missing behavior

All synthetic requests come from `app/orders/fixtures/orders_demo_v1.json`.
The explicit tenant is `tenant_demo_01`; actor scope is checked server-side by demo reads.

| Frontend field | Authority / endpoint | Provenance / availability | Missing behavior |
|---|---|---|---|
| Order ID, customer display, items, received time, requested deadline, channel | shared synthetic request / `/v1/demo/orders` | versioned DEMO-ONLY fixture; not imported customer messages | reject malformed source |
| Lifecycle status | no authoritative OrderRequest transition | UNKNOWN | never derive Accepted/Completed from Core |
| Commitment link | fixture link, matched against tenant-scoped Core on detail | seed_demo.py mappings verified in DB | show warning if absent; reject mismatched link |
| Order value / profit | no approved customer price or complete costs | unavailable | Unknown; staff financial information redacted |
| Feasibility | existing `/v1/commitments/:id/assessments` | exact persisted P2 evidence only; not Core feasibility label | unverifiable/missing; no recalculation |
| Inventory / BOM / capacity / expiry | existing P2 snapshot authority | no persisted snapshot in current Demo | unavailable; stock is not BOM/ATP |
| Agreement / fulfilment | Core commitment read, separate dimensions | synthetic Core only | no acceptance or delivery inference |
| Reservations | explicit reservation evidence only | none in Demo | not verified |
| Calendar | shared request deadlines | REQUESTED / TENTATIVE; no production schedule | resource/conflict coverage Unknown |
| Portfolio | P2 common constraints + joint evaluator receipt | no registered production optimization API/approved adapter | unavailable; never invent optimizer |

## Ownership / reuse mapping

Reuse Core auth context, DB session, tenant-scoped Commitment, existing P1 read/history UI,
P2 assessment-history reader, and the shared frontend HTTP client. Add only isolated
demo read DTOs/source and fixture; no table added/extended/deprecated. Existing
`contracts/fixtures/demo_dataset.json` uses `ord_001` rather than the current seed's
`ord_hero_001`; do not mutate this historical P1/P2 scenario or silently join those IDs.
The new request fixture records synthetic request facts independently; copied SKU/quantity
and delivery dates are demo authoring choices aligned to the observed five Core rows,
not evidence that Core terms were an original customer request. Received timestamps and
customer labels are explicitly newly authored synthetic facts. All lifecycle states Unknown.

Core/P1/P2/P3 business rules and ingestion remain unchanged. The additive main router
registration is the only shared application wiring change and needs Core review on handoff.
Do not run `seed_demo.py`, `reset_and_seed_test_db.py`, or the new upstream P2 seed:
the latter requires BURGER terms incompatible with these five demo variants.

Portfolio formal integration is BLOCKED on P2/H owner confirmation of a registered,
authorized common ConstraintSpec + joint validation receipt and complete revenue/cost,
lot-expiry and resource sources. Pure optimization modules are not a production read API.
P1 owner: approve durable shared request ingestion/linkage before Inbox can read fixture requests.
Other Views are not modified; Dashboard/Recovery already read the linked Core IDs;
Suppliers has no verified request-read integration. Fixture evidence is SYNTHETIC only.

## Final stage report

| Stage | Result | Commit | Verification | Remaining blockers |
|---|---|---|---|---|
| 0 | Completed read-only inspection | none | runtime health/overview, schema, links, Git and owner contracts | no accepted-request authority |
| 1 | Shared independent synthetic requests | 8b7e87f | 2 fixture/identity tests | not imported into P1 Inbox |
| 2 | Queue API + explicit demo frontend | 0b2a055 | 15 backend tests; 73 queue-related frontend tests; typecheck/build | lifecycle/value/risk authority missing |
| 3 | Detail + Core association + P2 evidence failure states | 6392368 | 17 API tests; 76 frontend tests; typecheck/build | P1 context absent; P2 provenance missing |
| 4 | BLOCKED formal integration; handoff completed | none | registered routes and pure optimization/ports inspected | P2/H joint receipt + authoritative common constraints/source adapter |
| 5 | Requested delivery calendar | a9eb8fc | 24 backend tests; 114 frontend tests; typecheck/build | no confirmed production plan or reservation evidence |
| 6 | Read-only runtime/UAT, identity fix and regression | this commit | see commands/results below | full business demo remains blocked by stages 3/4 sources |

Stage counts overlap; do not add them as independent tests. Original high-concurrency
Orders suite run: 577 passed / 7 async wait failures under 24 workers. Rerun with
`--maxWorkers=2`: 584/584 passed. A final customer identity regression increases
the suite to 585 tests; the final full run PASSED 585/585. No tests were removed or
timeouts extended to conceal concurrency failures.

Backend commands, from `backend`, using the existing project virtualenv Python:

```powershell
python -m pytest tests/test_orders_demo_data.py tests/test_orders_demo_api.py tests/v2_2/test_terms.py tests/test_feasibility_adapter_a5.py tests/integration/test_backend_bdfgh_foundation_contracts.py app/feasibility/tests/test_router.py
# PASSED: 121 tests (SQLite disposable test adapter; no Demo/original DB resets)
python -m pytest tests/test_orders_demo_launcher.py tests/test_orders_demo_data.py tests/test_orders_demo_api.py
# PASSED: 25 tests including explicit rejection of original DB target
```

Frontend, from `frontend`:

```powershell
npm test -- src/features/orders --maxWorkers=2
npm run typecheck
npm run build
```

Typecheck and production build PASSED. Existing Vite large-chunk warning remains;
FastAPI lifecycle/Starlette deprecation warnings remain. No migration was introduced.
The final Customer ID/display-label fix separately passed 47 source/decision tests.
Core decision binding still rejects a different authoritative customer ID; the change
does not relax tenant/order/commitment matching or grant command authority.

Runtime command from repository root:

```powershell
python scripts/verify_orders_readonly_demo.py
```

PASSED against actual PostgreSQL-backed server on port 8001: all five Queue/Detail
requests and their Core associations match; Calendar requested dates match Queue;
Owner/Manager/Staff reads pass; wrong tenant/unknown actors fail on all three routes.
Hero and Delay report UNVERIFIABLE / ASSESSMENT_PROVENANCE_MISSING; Normal,
Ambiguous and Fulfilled report UNAVAILABLE. None is promoted to accepted/completed/feasible.
Launcher verified `SHOW default_transaction_read_only = on` before serving.

Browser UAT PASSED for 5 synthetic rows, partial-total KPI, Hero search, View Details,
unchanged requested deadline in Detail, Unknown Feasibility, explicit provenance error,
Core agreement/history reads after Customer ID fix, Back/Forward preserving search,
refresh and Staff/Owner switching. Calendar Month/Week/Day and previous/next exercised;
all five requested dates present and labelled not promised. Canonical
`/planning/portfolio` visibly reports Portfolio API unavailable. Existing canonical
and sidebar alias registrations are untouched and covered by Orders routing tests.
Desktop and 390x844 mobile Queue inspected; screenshots saved outside Git in
`outputs/orders-backend-integration-20261024/`. Temporary viewport override reset.
Queue retains its existing horizontally scrollable table on narrow screens.
This is smoke UAT of supported read paths, not proof of complete acceptance/scheduling UX.

## Runtime operations and data sources

Current development copy: `work/orders-backend-integration-20261024`, branch
`codex/orders-demo-integration`. Original 8000/5173 processes remain untouched.
Reviewable read-only demo: `http://127.0.0.1:5175/orders`, Backend 8001.
No Push, PR or Main merge was performed. The local merge `c625097` only brought the
fetched main baseline into this feature branch before implementation.

New API inventory (all GET only):

| API | Source |
|---|---|
| `/v1/demo/orders` | validated immutable shared JSON request fixture |
| `/v1/demo/orders/{order_id}` | same request; tenant-scoped Core get and existing authoritative P2 history reader |
| `/v1/demo/orders/planning/calendar?from_date=...&to_exclusive=...&time_zone=Asia/Kuala_Lumpur` | same fixture, timezone-aware half-open window, at most 370 days |

All endpoints require backend `MOUMANTAI_ORDERS_DEMO=1` AND
`MOUMANTAI_SYNTHETIC_MODE=1`; ENVIRONMENT `production`/`prod` always denies reads.
Only `tenant_demo_01` and recognized human demo actors are allowed. This is explicit
header-based **synthetic identity**, not live authentication or authorization evidence.
No fallback to fixture data occurs when a real API request fails.

| Page | Data Source |
|---|---|
| `/orders` | `demoOrderQueueSource` only in explicit demo mode; otherwise `unavailableOrderQueueSource` |
| `/orders/:id` | `demoOrderDetailSource` in demo mode + retained legacy P1 History/Core decisions; otherwise existing P1 detail source |
| `/planning/portfolio` | existing `unavailablePortfolioSource`; no invented solver/scenarios |
| `/calendar` | `demoScheduleSource` for REQUESTED/TENTATIVE delivery only in demo mode; otherwise `unavailableScheduleSource` |

Verified mapping:
`ord_normal_01 → com_normal_01`, `ord_hero_001 → com_001`,
`ord_delay_01 → com_delay_01`, `ord_ambiguous_01 → com_ambiguous_01`,
`ord_fulfilled_01 → com_fulfilled_01`. Cross-tenant or different Core order links
are denied, not silently substituted. A missing Core row preserves the request with
an explicit unavailable association. Historical Core assessment versions never become
request versions. Fixture calendar validity ends 24 Nov 2026 16:02:48 MYT; it describes
immutable request-source validity only, not current operational stock or capacity.
After expiry, calendar freshness guard withholds events until an explicit source revision.

Launch with the already-existing DPAPI credential file (no plaintext credential file):

```powershell
# Repository root; use the path to an existing virtualenv Python.
./scripts/Start-OrdersReadOnlyDemo.ps1 -PythonPath 'C:/path/to/backend/.venv/Scripts/python.exe'
# In a second terminal, frontend:
$env:VITE_ORDERS_DEMO='1'
$env:VITE_API_BASE_URL='http://127.0.0.1:8001'
npm run dev -- --mode demo --host 127.0.0.1 --port 5175 --strictPort
```

The backend launcher accepts only the exact 5434 Demo database, forces PostgreSQL
read-only connection settings, disables mutation HTTP methods and isolated E2E,
clears external channel credentials, disables channel autostart/AI, and starts no
send worker. Secrets remain in process memory; log streams redact credentials.
Frontend requires both MODE=demo and VITE_ORDERS_DEMO=1. Normal production builds
remain unavailable. To disable, stop these task-specific 8001/5175 processes and
unset VITE_ORDERS_DEMO/MOUMANTAI_ORDERS_DEMO (rebuild/restart frontend after flag changes).
Launcher PID at handoff: 12996, Python child 39868; recheck process identity before stopping.

Actual Demo database writes: **none**. Only disposable SQLite test adapters were
written by regression tests. No connection or write was made to 5433/moumantai by
this implementation; original DB and Docker volumes were left untouched. No global
before/after fingerprint was taken of the original DB, so changes by other concurrent
processes are outside this assertion.

Manual testing can begin now for Queue/Detail/requested-delivery read flows at 5175.
Full four-page business acceptance is NOT_READY: P1 must approve/import durable original
requests; Core/B must supply authoritative lifecycle/exact acceptance and reservation
contracts; P2 must supply version-bound assessment/snapshot evidence; P2/H must confirm
portfolio joint validation and financial/expiry sources. P3 recovery associations can
use existing Core IDs; no P3 approval/execution behavior was changed.

Final concurrent-work check: the original runtime checkout advanced independently
from `85ad272` to `344de8f` during this task, adding `d589087` (acceptance/proposal UX)
and `344de8f` (amendment history/progress). Its working tree is clean. These two
concurrent frontend commits are not part of this independent development copy;
do not replace the original directory with this copy. Reconcile them on a feature
branch before applying the five exported integration patches to that checkout.
Both copies still reference fetched main `f8e147d`; Main itself was not modified.
