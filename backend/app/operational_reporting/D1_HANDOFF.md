# Backend D D1 handoff

This module is pure and read-only. Its dataclasses are **trusted-reader transfer
shapes**, not authentication or evidence verification. Do not expose them as
request-body claims. `project_status`, `plan_milestone`, `aggregate_daily`, and
`feedback_readiness` are the entry points. No API route, database table,
fulfilment write, or outbound send is included.

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

A future server-side adapter must read a tenant-authorized Core Commitment,
reconciled acceptance and reservation receipts, versioned domain/operational
events, evidence with verified source/tier, and a consistent snapshot watermark
in one coherent read. It must map these into `OrderFacts`, excluding unverified
client claims. A separate trusted P4 reader must supply recipient verification,
consent/policy/channel capability and a complete send-history lookup. P4 must
atomically enforce the returned deduplication key when it eventually sends.
The pending authority for accepted/reservation and interim operational event
types prevents a real route or automatic milestone wiring in D1.

`aggregate_daily` includes only supplied orders. Its denominator is due orders
in that supplied source window; the caller must guarantee complete tenant/day
pagination and authorization. Coverage measures due orders whose status facts
pass the projection. Optional actuals require separately evidenced planned and
actual values with matching units; absent duration is unmeasured. Feedback
text has no path back into evidence or business state.

## Next bounded Backend D increment

After Core and P4 agree on authoritative accepted/reservation and operational
event readers, add a server-only adapter and identity-scoped read endpoint;
integrate milestone intents through P4's existing outbox/history authority.
