# Backend D D1 handoff

This module is pure and read-only. Its dataclasses are **trusted-reader transfer
shapes**, not authentication or evidence verification. Do not expose them as
request-body claims. `plan_milestone`, `aggregate_daily`, and
`feedback_readiness` are the entry points. No API route, database table,
fulfilment write, or outbound send is included.

## PR #48 ownership correction

Draft PR #48 (`codex/feat-v2-2-backend`, head `741976d`) already owns
`app/orders/status.py::read_status_preview`. It reads Core Commitment and
fulfilment audit, refuses to infer accepted status from legacy `CONFIRMED`,
and projects `COMPLETED` only from scoped synthetic fulfilment proof. Its
status preview tests are in `backend/tests/v2_2/test_api.py`. Its separate
conversation clarification and reply preparation modules are unrelated to D1.
The Backend D pure status projection from the first D1 commit overlapped this
reader and was removed in the follow-up correction. The original commit remains
in branch history for review. `StatusProjection` here is now an input contract
for the one authoritative status owner, not a second projection algorithm.
PR #48 is unmerged and is not imported into this main-based branch.

## Verified reuse and required integration seam

- Core `CommitmentRecord` in `app/core/models.py` owns tenant/order/customer
  bindings, agreement and fulfilment states, aggregate version and update time.
  `app/core/schemas.py` defines the matching typed states and `DomainEvent`.
- Core `OutboxEventRecord` has event ID, commitment/version, tenant and time.
  `app/core/events.py` defines `commitment.fulfilment_verified`. Core currently
  has no universal accepted/reservation receipt event or operational
  preparing/ready/out-for-delivery events in this verified main snapshot.
- Core demo fulfilment evidence uses the scoped synthetic reference policy in
  `app/core/fulfilment_evidence.py`. This is `DEMO_ONLY`, never live proof.
- P4 `OutboundMessageRecord` and recipient preferences are in
  `app/communication/models.py`. P4 remains the only send/history owner.

A future server-side adapter owned by the order-status/Core integration must
extend or reuse PR #48's single status reader. It must obtain a tenant-authorized
Core Commitment, reconciled acceptance and reservation receipts, versioned
domain/operational events, evidence with verified source/tier, and a consistent
snapshot watermark in one coherent read. It must map these into `OrderFacts`
and the corresponding `StatusProjection`, excluding unverified client claims.
A separate trusted P4 reader must supply recipient verification,
consent/policy/channel capability and a complete send-history lookup. P4 must
atomically enforce the returned deduplication key when it eventually sends.
The pending authority for accepted/reservation and interim operational event
types prevents a real route or automatic milestone wiring in D1.

`aggregate_daily` includes only supplied orders. Its denominator is due orders
in that supplied source window; the caller must supply authorized tenant/day
pagination and an honest completeness statement. Coverage measures due orders with a fresh, bound
status from the status owner. Optional actuals require separately evidenced planned and
actual values with matching units; absent duration is unmeasured. Feedback
text has no path back into evidence or business state.

## D2 reliability boundary

`validation.py::validate_events` checks event IDs, tenant/order/commitment and
version bindings, source window, timestamps, evidence references/kinds/tiers,
and the supplied status source. Identical replays collapse. Conflicting IDs,
versions, evidence or stale source/status fail closed for that order. This is
structural consistency only: `verified=True`, evidence tier and the source
manifest must be populated from authenticated repositories, not a request.
It does not prove an acceptance receipt, reservation or provider receipt.

`ReportingSource` now carries the requested tenant/day window, watermark,
pagination and missing-source state. A report with incomplete pagination or
missing sources returns `source_complete=False` and explicit limitations;
`data_coverage` remains a separate ratio over the supplied due-order subset.
The future reader must atomically establish that its page set and watermark
cover the requested population before marking it complete. D2 has no database
reader and cannot independently verify that assertion.

`DEMO_ONLY` evidence can still be represented for isolated diagnostics. It
cannot produce a live-eligible milestone or feedback intent and is excluded
from verified fulfilment and live evidence coverage. No execution-mode flag
was invented. A later production path requires a status-owner evidence
contract and P4 policy review. Current P4 recipient preference persistence
only constrains `TRANSACTIONAL_REVISED_TERMS` consent; it does not authorize
milestone or feedback sends. The future P4 adapter must supply a verified,
purpose-specific, unexpired recipient/policy result and complete send history,
then atomically enforce the existing proposed dedup key. D2 does not alter
recipient-level dedup scope or P4 records.

## Next bounded Backend D increment

After Core and P4 agree on authoritative accepted/reservation and operational
event readers, the PR #48 order-status owner should extend its existing reader
and add an identity-scoped read endpoint. Backend D can then consume that
reader's status and integrate milestone intents through P4's outbox/history.
