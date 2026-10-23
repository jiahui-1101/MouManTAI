# Unified frontend redesign — review evidence

23 October 2026. Base: open draft PR #40, `81de1677a6f29ef0812c5d685977beacc9c8ad81`, on Main `bcf97834c816805c818d6fc88bcde3f248ade0e6`. This PR is stacked on PR #40 and includes its P3 recovery changes. It does not merge or replace PR #40.

## Route and action review

| Route | Owner | Visual work | API and actions | Browser result / blocker |
| --- | --- | --- | --- | --- |
| `/overview` | P5 | Shared shell, tokens, metrics, filters, error state | Existing `/v1/overview` read and retry retained | Rendered at all four widths; local API unavailable |
| `/activity` | P5 | Timeline, filters and badges unified | Existing Core reads retained; assessment ID no longer passed as impact ID | Rendered at all four widths; local API unavailable |
| `/inbox` | P1 | Inbox palette, surface, controls, mobile fit | Existing ingestion, list, review and retry retained | Rendered at all four widths; P1 endpoint returned 500 |
| `/orders/:id` | P1 | Shared context surface; exact Core commitment link | Existing context read/review/publish APIs retained | Demo ID has no record in local service |
| `/commitments/:id` | P2 | Unified cards, tables, states and contextual links | Existing Core/assessment reads retained; recalculate remains disabled without trusted snapshot version | API unavailable in local browser |
| `/impact/:id` | P2 | Unified resource/dependency tables and load state | Existing exact impact ID read retained | API unavailable in local browser |
| `/recovery/:id` | P3 | PR #40 case redesign included | Existing durable case read retained; no invented impact link | API unavailable in local browser |
| `/recovery/:id/plans` | P3 | PR #40 planning and comparison included | Existing governed plan/approval APIs retained; demo is read only | Synthetic walkthrough rendered at all four widths |
| `/communications` | P4 | Unified list, metrics, drafts and status surfaces | Existing summary/list/detail/prepare/review/mock-send APIs retained | API unavailable in local browser |
| `/communications/follow-ups` | P4 | Unified filters, metrics and evidence cards | Existing queue/response reads retained | API unavailable in local browser |
| `/confirmations/:id` | P4 | Unified proposal, response evidence and exact commitment navigation | Existing confirmation/attempt reads retained | API unavailable in local browser |

The source retains distinct `SENT`, `ACCEPTED`, `EXECUTED` and `FULFILLED` meanings. Links use an available exact order, commitment or case identity. Assessment IDs are displayed as references, not treated as impact IDs. The current P3 case contract supplies no impact ID. The app does not claim live Orbyte integration.

## Verification

- Full Vitest: **475 passed, 5 skipped** across 30 files. Existing ReviewDrawer `act(...)` warnings remain; no test failed.
- TypeScript: `npm run typecheck` passed.
- Build: `npm run build` passed. Vite reported the existing JS chunk size warning.
- Chrome browser smoke: `/overview`, `/activity`, `/inbox`, `/orders/demo`, `/commitments/demo`, `/impact/demo`, `/recovery/demo`, `/recovery/demo/plans`, `/communications`, `/communications/follow-ups`, `/confirmations/demo` at **1440, 1024, 768, 390** pixels. Every page had `document.scrollWidth === viewport width`; no document overflow. At 390 pixels, menu opened, Activity navigation closed it, role selector remained visible.
- A browser route fixture rendered all seven populated overview KPI cards in [this screenshot](screenshots/unified-frontend/overview-populated-1440.png). The fixture is visual test data, not backend evidence.
- [Before screenshots](screenshots/unified-frontend/before) are from PR #40. [After screenshots](screenshots/unified-frontend) are from this branch. They show actual disconnected, error and synthetic states; they are not a live backend success claim.

## Backend and review gates

P2 has no trusted current snapshot version for public recalculation. P3/P4 durable operations still need the isolated backend and workers; normal local browsing cannot prove persistence or customer response processing. The P4-reported P3 PostgreSQL JSON equality and OFFERED version progression defects must be verified on the backend branch before a live hero run. P1 local backend returned 500 on inbox read and needs its PostgreSQL setup. No backend files were edited here.

Formal current-head P1–P5 review and CI are required before merge. The user designated P5 `Gan0117` as the independent reviewer for P3 Core/version/migration compatibility; P4 `Sheng554` is also requested for confirmation-response compatibility. The P3 author cannot self-approve. All four requested reviewers have GitHub write permission. No `CODEOWNERS` file exists at this head. GitHub branch-protection and rules APIs returned 403, so merge-rule requirements are not independently verified; do not merge until GitHub displays the required checks and reviews as satisfied.
