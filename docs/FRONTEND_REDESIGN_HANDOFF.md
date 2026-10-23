# Frontend redesign — owner handoff

Status: owner review required; implementation in this branch is P3 Recovery only.
Baseline: origin/main bcf97834c816805c818d6fc88bcde3f248ade0e6 (fetched 2026-10-23).
Branch: feat/frontend-orbyte-redesign.

## Design proposal

Use the public Orbyte platform philosophy—shared identity, workflow and business context, with modular capabilities—as inspiration only. Do not copy its UI or imply a MouManTAI partnership/live API. Orbyte distinguishes live capabilities from platform direction: [Platform](https://www.orbyte.my/platform), [Overview](https://www.orbyte.my/).

P5 should approve shared tokens: canvas #f3f7fa, surface #fff, text #18324b, muted #60758a, border #dce5ed, blue #1769aa, teal #087e80; semantic green for verified success, amber for pending/conditional, red for confirmed errors, and gray for UNKNOWN/unavailable. These values are from the P3 feature styling, not official Orbyte brand colors. Use shared spacing/focus/motion rules and components in P5-owned styles/layout; feature owners retain domain-specific panels.

## Route/API/action matrix at baseline

“Real API” means the code contract exists, not that local API/E2E was available or a mutation is authorized.

| Route | Owner | Current API / interaction | State or blocker |
|---|---|---|---|
| /, /overview | P5 | GET /v1/overview; read filters/retry | API-derived metrics; P5 owns redesign. |
| /activity | P5 | GET /v1/commitments, /timeline, or /v1/audit | Read-only; verify generated impact links use impact_id. |
| /inbox | P1 | Message ingest/list/process, extraction/association, context review/publish APIs | Existing tests; P1 redesign approval required. |
| /orders/:id | P1 | Context by ID/order, versions/reviews | Existing tests; P1 approval required. |
| /commitments/:id | P2 | GET Core commitment + assessment history | Historical only; no trusted current snapshot/recalculate API. |
| /impact/:id | P2 | GET /v1/impacts/{impact_id} | Requires impact_id, not commitment_id or assessment_id. |
| /recovery/:id | P3 | GET case, pending/completed trigger read fallback | Durable-only and read-only. API returns no impact_id. |
| /recovery/:id/plans | P3 | GET case/plans/history; POST generate/approval; P3 then P4 communication requests | Server gates remain; two browser requests mean durable SYS-008 handoff is pending. |
| /communications | P4 | GET summary/list/detail; POST prepare/review/mock-send | Synthetic send is not acceptance; P4 redesign approval required. |
| /confirmations/:id | P4 | GET confirmation/attempts; read-only UI | P4_EVIDENCE_ONLY; no Core transition or fulfilment claim. |
| /communications/follow-ups | P4 | Follow-up queue/read/cancel/run-due APIs | P4 redesign approval required. |

Synthetic-only: /recovery/demo/plans and shell role selector; neither authorizes or persists business outcomes. P1 review/publish, P3 plan/approval APIs, and P4 review/mock-send are governed server calls. P2 recalculation/currentness, durable automatic P3→P4 handoff, and normal-worker confirmation response processing remain unavailable; do not add success UI for these.

## P3 changes and integration finding

The P3 pages now use a light-neutral feature style, compact case/version/snapshot summaries, trigger/response/evidence history, explicit pending-input/error states, and neutral UNKNOWN status. Existing API interactions and guards are preserved; case view remains read-only.

P3 previously linked /impact/{commitment_id}, but P2 expects impact_id and the P3 case response has none. This branch replaces the dead link with an explicit unavailable note. P2/P5 must agree and return a trusted impact reference before restoring navigation. P5 Activity should audit its assessment-to-impact identifier mapping too.

## Owner handoffs

- **P5:** approve shared tokens; redesign shell/navigation/breadcrumbs; keep simulated identity explicit; audit deep-link IDs and shared API/auth context. Browser review found horizontal top navigation overflow at 390px and numbered unstyled breadcrumbs at desktop; these are existing shell issues outside this diff.
- **P1:** redesign /inbox and /orders/:id in its owned feature directory; preserve source evidence, uncertainty and server validation.
- **P2:** redesign commitment/impact routes in its owned feature directory; keep recalc disabled until authoritative snapshot currentness; provide canonical impact ID.
- **P4:** redesign communication/confirmation/follow-up routes in its owned directory; keep SENT, response, Core agreement and fulfilment distinct.

No P1/P2/P4/P5 source files are changed. Owner approval is required before this branch edits their files.

## QA evidence and limits

- Open PRs observed in GitHub 2026-10-23: #39 draft, #38 open, #22 draft; #32 and #34 are in Main ancestry.
- Browser rendered http://127.0.0.1:5173/recovery/demo/plans as an explicitly synthetic scenario. Viewports: 1440×1000, 1024×900, 768×900 and 390×844. No P3 document-level horizontal overflow; shared mobile navigation still overflows.
- GET http://localhost:8000/health timed out. No real API-backed case or end-to-end persisted browser workflow was verified.
- After the final impact-link guard: focused P3 recovery tests 21 passed; full frontend suite 475 passed, 5 skipped (480 total); typecheck passed; production build passed with the existing >500 kB bundle warning (583.51 kB JS).

Next: P5 approves shared shell/tokens and the ID contract; P2 supplies the impact reference/currentness contract; owners redesign their routes; then run browser workflow against an authorized isolated backend and obtain current-head reviews/CI. PostgreSQL remains pending until approved PG CI actually runs.
