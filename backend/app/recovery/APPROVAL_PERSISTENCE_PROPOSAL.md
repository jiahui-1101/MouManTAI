# P3 recovery approval persistence proposal — P5 review

Status: proposal only. No P5 schema or migration was changed. Current P3 approval
records are held in `IN_MEMORY_SYNTHETIC` recovery cases and are not durable.

## Proposed records

P5-owned Alembic migration to add two append-only tables:

- `recovery_approval_requests`: `tenant_id`, `approval_request_id`, `idempotency_key`,
  `recovery_case_id`, `commitment_id`, `commitment_version`, `plan_id`,
  `plan_version`, `snapshot_version`, `action_scope` (JSON),
  `maximum_approved_amount` (fixed precision `NUMERIC`, MYR), `reason`,
  `requested_by_actor_id`, `requested_at`, `expires_at`, `evidence_refs` (JSON),
  `correlation_id`, and optional `causation_id`. Primary key `(tenant_id,
  approval_request_id)`; unique `(tenant_id, idempotency_key)`.
- `recovery_approval_decisions`: `tenant_id`, `decision_id`,
  `approval_request_id`, the complete case/commitment/plan/snapshot binding,
  `decision` (`APPROVED`, `REJECTED`, `REVISION_REQUESTED`, `INVALIDATED`,
  `EXPIRED`), `action_scope`, approved MYR maximum, `actor_id`, `actor_role`,
  `reason`, `decided_at`, nullable `approved_at`, `expires_at`,
  `evidence_refs`, `audit_id`, `correlation_id`, and optional `causation_id`.
  Primary key `(tenant_id, decision_id)` and a foreign key to the request using
  `(tenant_id, approval_request_id)`.

Index tenant + commitment + plan + plan version + decision time for history reads.
Enforce append-only behavior in the P5 service boundary; application code must
never update or delete request/decision rows. Preserve all rows when a plan is
revised; append `INVALIDATED` for prior approvals rather than overwriting them.

## Transaction and ownership

P5 should own the migration, persistence models, and transaction method. The
method should lock/read the tenant-scoped commitment, verify the expected
commitment version and actor context, and insert the request/decision and P5
audit record atomically. P3 should pass the full bound plan snapshot and action
scope; P5 should not recalculate P2 feasibility. Event/outbox publication is a
separate agreed P5 interface and must not be inferred from this proposal.

Before implementation, P3/P5 must agree on authenticated actor provenance,
whether requesters may approve their own requests, currency/precision, terminal
decision uniqueness, and the P5 audit event type. This proposal does not grant
execution authority or change Commitment lifecycle state.
