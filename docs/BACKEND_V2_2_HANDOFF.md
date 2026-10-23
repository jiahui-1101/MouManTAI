# MouManTAI 2.2 Backend — Living Handoff

Updated (UTC and MYT): 2026-10-23; exact test/checkpoint times appended below.
Canonical spec: Implementation Baseline Review v2.2, root six Markdown files; source hashes `docs/V2_2_SOURCE_CHECKSUMS.json`. CODEX_PROMPT.md read from extracted attachment outside repo. Archive `docs/legacy/AGENT_RULES_V1.md` is noncanonical.
Repo: jiahui-1101/MouManTAI; origin/main observed `ec3ffbc970ab38abca8468abfe0466ff0464b998`; branch `codex/feat-v2-2-backend`; starting HEAD same; PR not yet created.
Task: cross-owner backend; BE-STATE, BE-ORB-01, BE-CUS-01, BE-REPLY-01, BE-ORD-02, BE-STAT-01; prepare contracts without unratified activation.
Reviewers: P5 Gan0117 (Core/shared), P1 mavisbong41 (context), P4 Sheng554 (reply/communication); P2 meishuet16 (feasibility compatibility); P3 affected only if recovery changes. S1–S5 remain pending, not signed by inclusion in pack.

## Snapshot / phase table

| Slice | Requirements | Implemented | Tested | Integrated | Evidence | Acceptance | Code refs | Validation commit |
|---|---|---|---|---|---|---|---|---|
| 0 | Blueprint 8–9 | Audit/docs | 68 baseline tests passed | Code inventories | VALIDATED code audit only | PASS | REPOSITORY_BASELINE / LEGACY_REUSE_MATRIX | ec3ffbc |
| A | BE-STATE / BE-ORB-01 | Immutable terms + typed ports | 44 passed | Pure only, no acceptance | VALIDATED validators; TARGET workflow | PARTIAL / PRODUCTION-GATED | app/orders/terms.py; app/integrations/business_ports.py | 0eccb0b |
| B | BE-REPLY / BE-CLAR | Pending | NOT_RUN | No | TARGET | PARTIAL | plan | None |
| C–G | order saga/optimization/supplier/CTA/status/extensions | Existing legacy retained; v2.2 not implemented | NOT_RUN new behavior | No | TARGET | BLOCKED pending prerequisites | matrix | None |

## Work completed since previous checkpoint

Initial checkpoint: worktree isolated, fetched actual latest main, read supplied sources completely, deployed byte-identical canonical docs, verified concrete existing authorities. No code/schema modification yet. See compact baseline rather than duplicating teammate architecture audit.

## Next executable tasks (priority order)

Execute A1/A2 test-first in BACKEND_V2_2_PLAN.md; then B1/B2 and read-only gated C. Review and commit each coherent slice; continue independent safe tasks if a later activation gate blocks.

## Contracts & migrations

No migrations. Single existing head 0017_p1_real_channel_provenance. Existing p1_dev inbound/context/reviews, Core commitments, P4 communication_outbound_messages and P3 recovery_cases remain authorities. New DTOs do not replace legacy Core schemas or instantiate another database.

## Evidence and commands

From backend: `python -m alembic heads` -> one head 0017. Baseline focused pytest command in REPOSITORY_BASELINE -> 68 passed / 5 existing warnings. Docker available; attempted new disposable PostgreSQL 16 container `moumantai-v22-disposable` on loopback 15462; startup result pending. No existing/dev/prod database touched.

## Blockers / policy decisions

- BLOCK-S1 | product/P5 | initial exact terms and pricing assent not ratified | no acceptance activation | safe pure contracts | explicit signoff and persistence mapping.
- BLOCK-S5 | product/P1/P4 | tenant clarification/consent/completion policy absent | no default business timers/sends | caller-supplied policy for pure mechanisms.
- BLOCK-AUTH | P5 | legacy header role registry is synthetic | no production mutation | isolated key only.
- BLOCK-PORTS | P5/P2 | no official Orbyte contract or shared portfolio ConstraintSpec | no real reservation/CP-SAT guarantee | typed seams.
- BLOCK-PROVIDER | P4 | Replit endpoint not verified | no live generation claim | factual template or review.

## Safety & runtime modes

No send, purchase, approval, execution, acceptance, inventory mutation or deployment. Legacy emergency approval remains intact. Synthetic tests only. Pure hash/evidence checks prove consistency, not sender authenticity.

## PR / merge status

No PR yet; all work will remain UNMERGED. #38 merged upstream; #39/#40/#42 open draft at audit, no dependencies copied. No teammate audit findings received yet.

## Resume instructions

`git -C C:/Users/User/.codex/worktrees/backend-v2-2/MouManTAI status --short --branch`; read this file and BACKEND_V2_2_PLAN.md. Run tests from backend. Do not edit original checkout, recreate worktree, redo source import, merge, or enable unsigned policy. Fetch and compare main before reconciling new findings.

## Chronological checkpoints (append only)

- Phase 0: complete read-only audit and source deployment; 68 baseline tests passed; code not yet implemented. Detailed subsequent checkpoints follow here.

- 2026-10-23T15:28:43.367328+00:00: Slice A: terms tests RED 33 missing module -> GREEN 33; port tests RED 11 -> GREEN 11. `python -m pytest tests/v2_2 -o addopts= -q --tb=short` -> 44 passed / 5 legacy warnings. No schema change. Ruff initially unavailable; installing developer checker, no application dependency change. Docs commit 1d7fda9; code commit 0eccb0b. Initial checkpoint writer failed on Windows GBK decoding before modifying docs; repaired immediately in this follow-up using explicit UTF-8. Source Markdown hard-break trailing whitespace preserved byte-for-byte; default diff --check reports it, code-only check passed. Disposable PG targeted regression in progress. Next B: factual reply authorization and independent clarification reducer.
