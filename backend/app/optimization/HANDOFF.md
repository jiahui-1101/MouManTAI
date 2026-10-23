# Backend H optimization handoff

## Scope and authority

BE-OPT-01/02/03/04 are implemented as an advisory, pure Python consumer. No API route,
database table, reservation, acceptance, purchase, Recovery execution, or message send
is added. `P2ConstraintSpec` is a **provisional typed consumer shape**, not a claim that
P2 has approved or published these semantics. The test suite uses an owner-labelled
`SYNTHETIC_TEST_FIXTURE`; it cannot produce a LIVE recommendation.

Current `origin/main` (`b1255f5`) provides `app.feasibility.inventory.calculate_atp`,
`app.feasibility.capacity.check_capacity`, and `app.feasibility.service.evaluate`.
Their inputs are `OperationalSnapshot` and `EvaluationSnapshot`; `evaluate` requires a
confirmed Core commitment already present in the snapshot. The feasibility package has
no `ConstraintSpec`, pending-order projection evaluator, or joint allocation verifier.
Its existing ATP and capacity tests remain the relevant regression gate. Backend H does
not coerce pending requests into accepted commitments or copy P2 BOM/ATP logic.

## P2_OPTIMIZATION_CONTRACT_HANDOFF

`meishuet16` should own and review an adapter that:

1. Receives an authenticated, tenant-scoped, current `PortfolioRequest`, resolves each
   exact `OrderRequest` ID/version and OrderTerms revision/hash, and binds the trusted
   SME comparison request and verified FCFS received timestamp policy. Request DTO flags
   are not authentication; no public optimizer endpoint exists yet.
2. Produces a versioned `P2ConstraintSpec` for one frozen operational snapshot and
   assessment watermark. Its `CandidateBinding` rows must match each trusted request
   version, OrderTerms revision/hash and source identity exactly. Its BOM-expanded
   `MaterialRequirement` rows must already use
   P2's normalized unit and material-use task. `compatible_lot_ids` must reflect P2
   quality, warehouse, location, substitution and expiry rules. `free_quantity` must
   be net of protected accepted reservations and accepted demand, with no double
   subtraction. Confirmed incoming supply may appear only as P2-authorized lots with
   a backed `available_minute`; unconfirmed ETA cannot enter the spec.
3. Supplies P2-owned non-preemptible `ProductionTask` durations (including supported
   setup), delivery/dispatch bounds, simultaneous exclusive resources, full calendar
   windows, and fixed accepted `FixedJob` intervals. This consumer uses integer minutes
   relative to the frozen snapshot; P2 must explicitly approve that granularity and
   reject any source that cannot be represented without unsafe rounding.
4. Implements `JointPortfolioVerifier.verify(request, projection)` over the **entire
   projected shared portfolio** and every included pending order in that same projection.
   It must check exact allocations, scheduling, accepted commitments/reservations,
   tenant, snapshot/spec/assessment versions, evidence freshness and source IDs. Return
   a real `portfolio_validation_id`, exact validated order IDs, evidence refs and status;
   do not persist hypothetical demand. A P2 rejection or incomplete proof produces
   `VALIDATION_MISMATCH`/UNKNOWN, never a fabricated certificate.
5. Documents unsupported P2 cases: current `evaluate` is a one-confirmed-target API,
   current ATP allocates only confirmed demand, and current `check_capacity` verifies
   supplied fixed bookings. Neither checks a pending jointly allocated portfolio.

`Gan0117` retains P5 acceptance and reservation authority. `mavisbong41` owns any P1
order identity/provenance reader. `jiahui-1101` should review Backend B/P3 compatibility
and arrange independent review of this PR.

## Design and measured fixture behavior

- FCFS uses verified received time plus stable ID and attempts each cumulative portfolio.
  A mathematical infeasibility excludes the candidate; each admitted portfolio requires
  a complete joint verifier receipt.
- Profit maximizes exact incremental contribution in one currency, using versioned
  revenue and all required cost fields. Missing or stale finance returns
  `PROFIT_COMPARISON_UNAVAILABLE`; revenue is never treated as contribution.
- Expiry strategy maximizes number served, then prioritizes allocation from earlier
  P2-authorized expiring lots within safe material-use boundaries. The secondary term
  is a FEFO preference, **not** a measured waste-saving claim. Missing expiry returns
  `EXPIRY_COMPARISON_UNAVAILABLE`; future demand is unknown.
- CP-SAT uses optional intervals, `NoOverlap`, exact integer material quantities,
  one worker, fixed seed and a 30-second maximum. Replay is expected only with the
  same OR-Tools version and inputs. Statuses preserve OPTIMAL/FEASIBLE/INFEASIBLE/
  UNKNOWN/MODEL_INVALID. The solver API requires a float for its bounded timeout;
  material and currency conversion remains exact Decimal-to-integer.
- The synthetic two-order fixture has 7 leaf units (old lot 4, new lot 3), protected
  accepted work from minute 0–30, and 60-minute candidate jobs. A (6 units) arrives
  first; B (7 units) has MYR 115 contribution. Each is individually feasible, while
  both together are infeasible. The tests assert FCFS=A, Profit=B (MYR 115),
  Expiry=B with 4 old + 3 new, and `FIXTURE_VALIDATED` joint verification. These are demo facts,
  not Orbyte data or P2-owned live verification.

## Requirements status

| Requirement | Status |
|---|---|
| BE-OPT-01 | IMPLEMENTED_PURE_BOUNDARY_ONLY |
| BE-OPT-02 | BLOCKED_BY_P2_CONSTRAINT_SPEC and BLOCKED_BY_MISSING_PENDING_TARGET_ADAPTER |
| BE-OPT-03 | IMPLEMENTED_AND_TESTED on SYNTHETIC_TEST_FIXTURE |
| BE-OPT-04 | IMPLEMENTED_AND_TESTED |
| BE-FEA-01 | BLOCKED_BY_OWNER_CONTRACT for live joint verification |
| BE-ORD-ACC-01 | IMPLEMENTED_PURE_BOUNDARY_ONLY; no business mutation |
| BE-ORB-01/02 | BLOCKED_BY_MISSING_AUTHORITATIVE_DATA and source reader |

## Dependency and validation notes

`backend[optimization]` adds OR-Tools without increasing the base dependency set.
CI has a dedicated `backend-optimization` job on Python 3.12 that executes native
CP-SAT tests. Local tests use isolated Python 3.11 x64 and OR-Tools 9.15.6755.
There is no migration. Local PostgreSQL was not used without an approved disposable
database. The PR CI result must be checked against its final head.
