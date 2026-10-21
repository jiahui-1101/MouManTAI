# P2 Phase 7A execution plan — 2026-10-21

Goal: runnable synthetic supplier delay → same evaluator → evidence-backed impact,
with measured metrics and concrete integration contracts. Approved scope is the
user's Phase 7A execution prompt; stop after feature push for independent review.

Starting Main: `ee4dfc73deb998a5af902422220cb1a34e0182cc`.
Branch: `feat/p2-phase7-integration`; old branch remains untouched.

Architecture: add a P2 pure orchestration boundary around existing `assess_impact`,
not a second calculator. Keep production dependencies unconfigured. Validate the
actual P5 resource query into an explicitly incomplete summary. Store immutable
history in a synthetic reference repository only; propose durable schema to P5.
No shared schema, migration, route mount, auth or P3 source edits.

Alternatives considered: putting orchestration in P5 would leave a P2-owned gap;
implementing shared transactions here would cross ownership. The chosen pure
boundary lets P5 resolve trusted snapshots and wrap the calculation atomically.

- [x] Audit mandatory trace rows, source/tests, current P3 remote interfaces and P5 inputs.
- [x] Publish early `PHASE7A_HANDOFF.md` with evaluator example and exact P5 blockers.
- [x] Add failing `test_supplier_pipeline.py` for complete, incomplete, stale,
  replay, conflicting evidence/identity/version and nonmutation cases.
- [x] Implement `supplier_pipeline.py`, complete synthetic fixtures and runnable
  `python -m app.feasibility.demo`; reuse existing `evaluate` and `assess_impact` math and classification semantics; add content identity metadata only.
- [x] Add failing `test_history.py`; implement `history.py` canonical mapping,
  tenant-scoped append-only reference history and event replay conflict detection.
- [x] Add failing `test_resource_adapter.py`; implement `resource_adapter.py`
  using `get_resource_snapshot` with exact Decimal values and resource versions.
- [x] Add independently authored labels, metric arithmetic tests and executable
  `python -m app.feasibility.benchmark`; report counts, UNKNOWN and zero denominators.
- [x] Run focused tests after each change; combined P2/P5 backend, frontend tests,
  typecheck/build, runtime class identity and combined-route uniqueness at the end.
- [x] Update trace/progress/reports and P2-only TEAM_LOG with actual evidence.
- [x] Review diff and commit logical implementation checkpoints. Final feature-only
  publication, remote SHA and unchanged Main/old-branch verification are recorded
  in the task response. Stop for independent review after publication.

Risks: synthetic snapshots are historical, not current production authority;
resource versions cannot supply a global counter; source text alone cannot prove
supplier identity; memory history is neither durable nor a transactional outbox.
No production E2E completion claim is permitted while those dependencies remain.
