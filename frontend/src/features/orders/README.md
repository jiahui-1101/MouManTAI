# Developer B — FE-ORD-01

This folder is a read-only queue presentation and integration boundary. It is not live order integration. Default production source fails honestly with `OrderQueueUnavailableError`; it makes no HTTP call and has no synthetic fallback. Synthetic fixtures exist exclusively in `OrderQueuePage.test.tsx`.

## Route and Sidebar integration (updated user authorization)

`frontend/src/App.tsx` now imports `OrderQueuePage` and registers `<Route path="/orders" element={<OrderQueuePage />} />` inside the existing AppShell routes. `/orders/:id` stays mapped to `OrderContextDetail` unchanged. The queue uses the existing AuthProvider, QueryClientProvider and Router. The Orders Sidebar entry is enabled in the existing `layout/AppShell.tsx` navigation array. The page explicitly shows backend unavailability until a verified source is supplied; production operational availability remains blocked. No Developer C action is needed solely to register this route.

Shared integration changes are limited to two files: App.tsx (one import, one route) and layout/AppShell.tsx (one navigation entry). No shared primitives, backend, dependencies or lockfile edits are included. The reported `layout/navigation.ts`, `Sidebar.tsx` and `foundation.css` do not exist in the inspected baseline; integration uses its actual shell structure. The Orbyte design document was absent from both pack and repository; CSS follows existing dark slate/sky conventions and reuses StatusBadge pending design review. During manual integration, merge these three additions into the current files instead of overwriting concurrent Developer A/C work.

## Backend handoff

`types.ts` describes a provisional UI model, not wire DTOs. `createOrderQueueHttpSource<VerifiedDto>(cacheKey, verifiedPath, map)` is an optional transport factory using shared apiRequest/authHeaders. Do not enable it until path, DTO validation, tenant/role authorization, canonical status mapping, coverage/pagination and provenance are frozen. Map wire data explicitly; do not cast unknown JSON to the UI model. Use a unique cache namespace for each adapter/version. Inject through `<OrderQueuePage source={verifiedSource} />`; keep this object stable outside render or memoize it.

The query key includes adapter version, tenant and actor. Fetches accept cancellation. Shared auth headers are development identity context, not proof of production authorization. Backend must enforce permissions and redact financial data. Mapper must preserve redaction; absent costs are never zero.

Preserve exact original received and separately information-completed timestamps, with explicit UTC offsets. Missing or offset-free dates are unavailable. All date filters apply to original received date inclusively in Asia/Kuala_Lumpur. Stable FCFS ordering uses received instant then lexicographic stable ID; unknown timestamps sort last. Do not substitute completed time. IDs must be unique/nonempty and resolve through legacy `/orders/:id`; confirm the ID association with P1 before enabling live rows.

`evidenceTier` describes the supplied source record. Assessments/recommendations remain explicitly computed/backend information and claims must retain their claim label; a mixed-source record must use UNKNOWN unless its fact/claim distinctions can be preserved. No frontend process verifies sources. Monetary amounts/quantities remain decimal strings. Profit is shown only with complete costs, price source, cost source, amount and currency; no arithmetic or optimizer runs in browser. Raw source references are rendered as text, not trusted links.

Only PENDING_ACCEPTANCE, ACCEPTED, REJECTED are matched into dedicated views. Other backend states, including amendment states if later returned, retain raw status in Other / unknown. Risk is independent; never infer a lifecycle status from risk. No speculative amendment enum has been declared.

Filters apply to the currently loaded snapshot. Partial coverage is prominent, all counts say loaded, no tenant-wide totals or server pagination is implied. The factory never follows invented cursors. A paginated backend needs an explicit approved paging adapter/UI extension; do not mark its first page complete. Backend portfolio results are not part of Phase 1: FCFS/Profit/Expiry-aware selectors explain the missing dependency without modifying queue ordering or claiming safe allocations.

## Validation

Run the repository scripts from frontend: `npm test -- --run` and `npm run build`. See the accompanying handoff report for observed results, source manifest and limitations. No mutation controls are provided. Native controls, pressed status buttons and a focusable horizontal table region support keyboard access. Mobile uses a contained horizontal table, wrapping controls and 44px targets; real-browser layout/accessibility review is still required before release.
