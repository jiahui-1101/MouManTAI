# Coordinated frontend redesign scope — 23 October 2026

This branch starts at PR #40 head `81de1677a6f29ef0812c5d685977beacc9c8ad81`, preserving its P3 recovery work. Its target is a single visual and functional frontend across P1–P5. The coordinated PR should stack on PR #40 while that PR remains open, or be rebased on Main after PR #40 merges. It must not rewrite or close PR #40.

## Ownership and delegation gate

`AGENTS.md` assigns frontend ownership by person. The user replied **“delegate”** in this chat on 23 October 2026 to the explicit P5/P1–P4 delegation question, authorizing coordinated cross-owner frontend edits. This chat is the delegation reference. All five owners must review the final current PR head before merge; the author cannot count as an independent reviewer.

## Intended frontend files and routes

| Owner | Scope |
| --- | --- |
| P5 | App shell, navigation, topbar, breadcrumbs, overview, activity, shared components and design tokens |
| P1 | Inbox, order/context detail, review and evidence |
| P2 | Commitment feasibility, impact and operational constraints |
| P3 | Recovery case/planning, option comparison, approval and replanning; preserve PR #40 |
| P4 | Communications, drafts, confirmation sessions and customer response evidence |

Use existing backend endpoints and contract types. Show disabled, pending or read-only states for unavailable operations. Keep `SENT`, `ACCEPTED`, `EXECUTED` and `FULFILLED` distinct. Do not change backend code or claim live Orbyte integration. Preserve tenant, commitment, plan, proposal, assessment and snapshot identifiers through navigation.

## Required verification

Focused route tests, full Vitest, TypeScript check, build and browser inspection at 1440, 1024, 768 and 390 pixels. Test real API behavior where an authorized local backend is available; report blocked paths separately. Request P1–P5 reviews and wait for CI before merge.
