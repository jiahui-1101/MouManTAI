# Phase 3 implementation plan

Approved scope: production capacity/deadlines and one pure evaluator only.
Baseline: clean feat/p2-feasibility-engine at 5a1e827b6431d4fddbaf6bf2938865f0bfdef567.

1. Add focused tests before implementation for explicit exclusive-resource
   processing rates, fixed production bookings, complete existing-job ledgers,
   exact working windows, conflicts, deadline/dispatch/transit constraints,
   conservative missing/stale/unsupported data and shared constraint mapping.
2. Add production.py for frozen P2-local operational evidence and proposal types,
   capacity.py for interval checks, service.py for ATP reuse and status aggregation,
   and production_fixtures.py for a separate, explicitly synthetic Phase 3 fixture.
   Preserve every existing Phase 1/2 model, fixture, algorithm and test.
3. Run focused tests; fix failures individually. Run the existing 73-test
   P2/shared regression command after the Phase 3 tests pass.
4. Review scope and safety; update progress, requirement trace, reports and only
   P2 TEAM_LOG entries. Stage explicit P2 paths, inspect diff, commit and push
   only the user-authorized feature branch; stop for external review.

Design: evaluate the supplied fixed, non-preemptible schedule; do not infer a
production rate, transit time, schedule optimization or split working time from
daily totals. Multiple resources are exclusive and simultaneously occupied.
Missing ledgers differ from evidenced empty ledgers. Unsupported routing of
manufactured intermediate products is UNKNOWN, even though BOM arithmetic works.
Hypothetical quantity/deadline/start changes are version-bound, evaluated in a
private copy with all competing demand, and explicitly conditional on approval.
SOFT preferences never make a hard-feasible schedule infeasible.

Shared-output gate: P5 has not confirmed the meaning of nonempty
affected_commitment_ids for a single-commitment assessment. Do not default it
to the target or infer impacted IDs. Provide independent local calculation;
evaluate returns a P2-local result using shared enums/ConstraintReason but no
affected IDs. User confirmed this gate during implementation; the final shared
assessment adapter stays BLOCKED until P5 records a decision. Do not implement
a caller-controlled bypass or claim full Phase 3 PASS.
No shared schema, dependency, persistence, route, impact propagation or UI changes.
