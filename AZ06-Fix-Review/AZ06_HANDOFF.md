# AZ-06 — Order Queue navigation preferences

Implemented and verified in an isolated development copy of `frontend-orders-planning`, baseline `ffbcee31cea57ea82a73ab1056c9689f2f5605f0`. No commit, push, merge, Backend change, shared change or original repository modification. Original untracked `AZ03-Fix-Review/` is preserved.

## Exact frontend changes

- `frontend/src/features/orders/OrderQueuePage.tsx`: replaces the two component-local state declarations with the feature-local preferences hook. Existing query keys, source authorization, FCFS selectors, loading/error/unavailable behavior, source-option hiding, routes, controls and Reset Filters remain intact.
- `frontend/src/features/orders/useQueuePreferences.ts`: validates and canonicalizes URL state; retains all ten filter fields and Analysis through page unmounts and independent history visits; scopes snapshots to the current identity epoch.
- `frontend/src/features/orders/QueueNavigationState.test.tsx`: 17 regression cases, including real Portfolio, Calendar and Detail return links, MemoryRouter Back/Forward, actual App/StrictMode/BrowserRouter native history, tenant and actor changes both on Queue and while it is unmounted, identity round trips, direct URLs, malformed/duplicated values, invalid dates, expired markers, Reset Filters and history entry count.

No other developers' modules, shared files, App routing, AuthProvider, Backend, dependencies or configuration were edited. No approval or integration dependency on another developer is introduced.

## URL and privacy behavior

The public allowlist is `oqStatus`, `oqFrom`, `oqTo`, `oqAnalysis`, plus opaque `oqState`. Status and Analysis accept only existing enums; dates accept actual Gregorian `YYYY-MM-DD` dates. Duplicate values fail closed to defaults. A valid reversed date range remains an explicit existing validation error. Unknown parameters are removed because this page has no verified contract establishing that they are safe. The fragment is preserved.

Example fresh direct link:

`/orders?oqStatus=ALL&oqFrom=2026-10-01&oqTo=2026-10-31&oqAnalysis=FCFS`

Search, customer, product and the four source-derived option labels are held only in memory, associated with an opaque random snapshot marker. The URL contains no customer/order records, financial information, API responses, tenant IDs or actor IDs. No localStorage/sessionStorage or API-data persistence was introduced.

The existing AuthProvider memoizes `authHeaders` until tenantId or actorId changes. A WeakMap uses that object as the session epoch, rather than reusing tenant/actor string keys. A -> B -> A yields a fresh epoch even while Queue is unmounted. Old markers are rejected with **all** filters and Analysis reset; their safe-looking URL fields cannot override that reset. AuthProvider is unchanged. Future changes to its memoization contract should retain these regression tests.

All filter edits, Analysis edits, Reset and URL cleanup use Router `replace`. Normal links retain their existing `push` behavior. Thus Back/Forward restores each Queue visit's preferences without inserting an entry per keystroke. It does not undo each individual edit within one visit. Reset clears all filter parameters/private fields while preserving Analysis and the opaque marker.

## Observed verification

Run from the isolated copy's `frontend` directory:

| Command/check | Result |
| --- | --- |
| `npx tsc -p tsconfig.app.json --noEmit` | PASSED, exit 0 |
| `npm test -- --run --maxWorkers=2` | PASSED, exit 0; 53 files passed, 1 skipped; 879 tests passed, 5 skipped; 67.23 seconds |
| `npm run build` | PASSED, exit 0; existing large-chunk advisory remains |
| New AZ-06 regressions | 17 passed, included in full suite |
| Original repository status | Baseline unchanged; only pre-existing untracked `AZ03-Fix-Review/` |
| Minimal patch application | `git apply --check AZ06.patch` against clean baseline files: PASSED |

The five skipped tests belong to the pre-existing opt-in live smoke suite. They were not enabled. Queue navigation checks run in jsdom with the real page components; the native-history regression runs the actual App and BrowserRouter under StrictMode. No separate interactive-browser session or live Backend smoke test was run for this frontend state-only change. Synthetic test records remain test-only; production unavailable API behavior is still tested and unchanged.

## Limits and integration

- Preferences last for the current live AuthProvider identity session. Full reload, provider remount, HMR/module reload or a copied URL with an expired/foreign `oqState` intentionally resets all preferences. This prevents stale identity history from reviving private text. Fresh direct links **without** an opaque marker can initialize the allowlisted safe fields.
- The seven non-public filter fields are not shareable/bookmarkable through URLs. Source-derived selected option labels stay hidden until an authorized fresh source loads, preserving existing privacy behavior.
- Preference snapshots live in memory for the session, including those needed by older history visits; no order data is retained by this mechanism.
- Apply `AZ06.patch` at the repository root, or copy exactly the three included frontend files after reviewing local differences. The patch is based on `ffbcee3`; review before applying on a newer baseline. The original repository was not changed automatically.
- The ZIP contains all three changed frontend files, this report, the minimal patch and a SHA-256 manifest. No compiled output or node_modules is included.
