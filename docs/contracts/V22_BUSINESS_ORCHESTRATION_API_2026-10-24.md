# MouManTAI v2.2 business orchestration API proposal

Contract version: `1`
Evidence mode: synthetic / Mock only
Implementation base: dependent on open Backend PR #88

## End-to-end sequence

P2 remains the source of disruption inputs and impact calculations. Recovery endpoints remain the P3 source of case, plan, approval and execution state. The orchestration routes persist and serve cross-module references; they do not decide feasibility, approve plans, execute actions, draft messages, or send messages.

1. Stage the versioned P2 before/after snapshots and submit the typed event through the existing `POST /v1/operations/events/supplier-delay` endpoint. That route is available only in the keyed isolated E2E runtime today.
2. Resolve a persisted P2 impact with `POST /v1/orchestration/impacts/{impact_id}/resolve` as an OWNER or MANAGER. This creates an idempotent P5 projection for each exact commitment already present in P2's before snapshot.
3. Read `GET /v1/orchestration/impacts/{impact_id}`. A linked result requires (a) P2 source membership and matching source commitment version and terms, (b) exactly one accepted OrderRequest, and (c) the existing matched Mock reservation receipt and Core acceptance audit. A missing or mismatched input returns an `UNRESOLVED_*` status and review reason.
4. Use existing Recovery routes to inspect/generate plans, approve as an authorized SME, and execute. The P3 implementation rechecks Core/P2 versions, exact approval, feasibility and idempotency immediately before creating its allowlisted internal review task.
5. The mandatory `recovery.internal_task_created` outbox consumer verifies the P3 execution row, task, plan, approval, Core audit, receipt and event bindings, then persists one pending notification intent. It does not call a P4 send endpoint.
6. The Frontend can read `GET /v1/orchestration/commitments/{commitment_id}/timeline` and notification intent APIs through a trusted server proxy.

## Registered orchestration routes

All routes require the existing synthetic request identity (`X-Tenant-ID`, `X-Actor-ID`) and filter records by the resolved tenant. Mutation requests do not accept tenant, actor, recipient, channel, consent, approval, or evidence authority in the JSON body.

| Method and path | Purpose |
|---|---|
| `POST /v1/orchestration/impacts/{impact_id}/resolve` | Materialize or reconcile P2 → accepted order links. OWNER/MANAGER only. Replays do not duplicate links or audits; a prior unresolved order link may transition to linked only after exact reservation/audit evidence becomes available. |
| `GET /v1/orchestration/impacts/{impact_id}` | Read the persisted link projection. Returns 404 for another tenant or unknown P2 impact. |
| `GET /v1/orchestration/commitments/{commitment_id}/timeline` | Internal evidence timeline over Core/order/P2/P3/P4 records and pending intents. Not a customer status API. |
| `GET /v1/orchestration/commitments/{commitment_id}/notification-intents` | List pending intents for one tenant-scoped commitment. |
| `GET /v1/orchestration/notification-intents/{intent_id}` | Read one tenant-scoped P4 handoff intent. |

Existing routes provide the other workflow operations:

- P2 supplier disruption: `POST /v1/operations/events/supplier-delay`; impact read `GET /v1/impacts/{impact_id}`.
- P3 Recovery: `/v1/recovery/cases/{commitment_id}`, `/trigger`, `/generate`, `/plans`; `/v1/recovery/plans/{plan_id}/approve`, `/reject`, `/execute`, `/actions`.
- P4 revised-terms communication: `/v1/communications/requests`, `/{communication_id}/prepare`, draft review, send eligibility, and send. The current P4 request is for an approved revised-terms proposal; it is not a general status milestone message API.

## Link response shape

`POST` and `GET /impacts/{impact_id}` return `ImpactResolutionView` version 1:

```json
{
  "schema_version": 1,
  "tenant_id": "tenant-demo",
  "impact_id": "impact-example",
  "event_id": "supplier-delay-event-1",
  "idempotency_key": "supplier-delay-event-1",
  "correlation_id": "corr-example",
  "discovery_complete": true,
  "overall_status": "UNRESOLVED_HUMAN_REVIEW",
  "links": [{
    "schema_version": 1,
    "tenant_id": "tenant-demo",
    "impact_id": "impact-example",
    "event_id": "supplier-delay-event-1",
    "idempotency_key": "supplier-delay-event-1",
    "correlation_id": "corr-example",
    "commitment_id": "commitment-1",
    "commitment_version": 3,
    "classification": "CONFIRMED_IMPACT",
    "link_status": "UNRESOLVED_ORDER_ACCEPTANCE",
    "order_request_id": null,
    "order_request_version": null,
    "customer_ref": null,
    "before_snapshot_id": "snapshot-4",
    "before_snapshot_version": 4,
    "after_snapshot_id": "snapshot-5",
    "after_snapshot_version": 5,
    "resource_refs": ["delivery-7", "patty-lot-2"],
    "evidence_refs": ["synthetic-eta-evidence-1"],
    "reason_codes": ["ACCEPTED_ORDER_RECORD_MISSING"],
    "source_provenance": {"p2_event_id": "supplier-delay-event-1"},
    "authorization_context": {"actor_role": "MANAGER", "authority": "P5_READ_SIDE_LINK_ONLY"},
    "occurred_at": "2026-10-24T00:00:00+08:00",
    "integration_mode": "SYNTHETIC",
    "evidence_tier": "DEMO-ONLY"
  }]
}
```

`LINKED_ACCEPTED_ORDER` marks a P2 `CONFIRMED_IMPACT`; `LINKED_ACCEPTED_ORDER_UNAFFECTED` preserves a P2 `VERIFIED_UNAFFECTED` result. Other P2 classifications, missing source rows, source term/version conflicts, or absent acceptance evidence remain unresolved. P2 candidates are never discovered by matching customer text, SKU alone, or similar names.

## Notification intent contract for P4 / Meishuet

`NotificationIntentView` version 1 contains:

- `tenant_id`, `source_event_id`, `source_event_type`, `correlation_id`, `causation_id`;
- `idempotency_key` equal to the exact P3 source event ID;
- canonical `commitment_id` and exact `commitment_version`;
- optional canonical `order_request_id` and `order_request_version` when the accepted order is verified;
- `notification_type = recovery_internal_review_created` and the verified internal change (`task_id`, `task_status`);
- P3 `plan_id`, `plan_version`, `approval_id`, `task_id`, Core `audit_id`, and exact `receipt_ref` in the durable source record;
- exact P2 / Core / P3 source `evidence_refs`, source snapshot provenance, and server-derived authorization context;
- optional `order_request_id`/version and `customer_ref`, plus nullable `contact_ref`, `channel_ref`, `original_channel_ref`, `consent_ref`;
- explicit `review_requirements` for P4 owner review, human review before drafting and existing P4 send authorization;
- `integration_mode = SYNTHETIC`, `evidence_tier = DEMO-ONLY`, and `verification_status = INTERNALLY-VERIFIED` for the P3 task receipt;
- a pending `status` and `delivery_status = NOT_SENT`.

Current status values are `UNRESOLVED_ORDER_ACCEPTANCE` and `PENDING_P4_REVIEW`. Blockers include `INTERNAL_REVIEW_TASK_IS_NOT_A_CUSTOMER_VISIBLE_MILESTONE`, `NO_STATUS_UPDATE_CHANNEL_OR_PURPOSE_SPECIFIC_CONSENT_BOUND`, and `ORDER_ACCEPTANCE_EVIDENCE_UNRESOLVED` when acceptance cannot be verified. A customer reference may be copied only from a unique, verified accepted OrderRequest; it is not a channel address. `order_request_version` is the accepted request's current lifecycle version. The reservation receipt version is separately bound through Core's `mock_order_request_version`, because the OrderRequest version increments after acceptance. The current P4 preference table only holds consent for revised terms and is not treated as consent for status notifications.

The intent is therefore a durable integration handoff, not a request to deliver a customer message. P4/Meishuet must approve the event taxonomy and recipient/channel/consent contract before any status-milestone draft or transport is enabled. `SENT` and `DELIVERED` are not valid states in this table.

## Timeline contract for the Frontend

`GET /v1/orchestration/commitments/{commitment_id}/timeline` returns version 1, sorted by timezone-aware `occurred_at`, with:

- canonical `commitment_id`, current version and `overall_readiness` (`PARTIAL` or `UNRESOLVED_HUMAN_REVIEW`);
- entries with `event_id`, `event_type`, `status`, referenced entity ID and exact commitment version when available;
- `correlation_id` when the source authority provides it;
- evidence refs and source-store provenance, plus server-derived actor / approval context;
- `integration_mode` (`SYNTHETIC`, `MOCK`, or `MIXED`) and `evidence_tier` (`DEMO-ONLY` or `INTERNALLY-VERIFIED`).

The timeline includes Core audits, OrderRequest audit, P2 supplier impacts, P3 cases/plans/approvals/executions, P4 requests/outbound status, and notification intents. It excludes message bodies, raw customer/supplier content and recipient addresses. `PARTIAL` means the internal records are available; it does not mean the order journey is ready for a real customer. Frontend access must be server-side and must retain the evidence-tier and source labels.

## Synthetic fixtures and validation coverage

- `build_pipeline_example(mode="complete")`: P2 typed supplier delay with one confirmed impacted and one verified unaffected candidate; used by the registered HTTP/PostgreSQL integration test.
- `build_pipeline_example(two_affected=True)`: two grounded impacted commitments; existing P2 pipeline/history tests validate both.
- `build_pipeline_example(mode="missing_supplier")`: incomplete supplier-ledger coverage; existing P2 tests preserve `UNKNOWN` rather than guessing.
- `backend/tests/integration/test_p3_live_postgresql_http.py`: starts the registered FastAPI service and worker against migrated PostgreSQL, then covers supplier event intake, impact-link persistence/replay, one positive link from exact persisted accepted-order evidence, multi-impact scope, missing supplier evidence, cross-tenant denial, Recovery trigger, approval/rejection, guarded execution, pending P4 intent persistence, timeline and non-delivery state. The positive acceptance fixture seeds existing authority records directly; it does not claim a live OrderRequest-to-P2 source projection.

Open test gaps: the all-in-one multi-impact journey across Recovery, concurrent outbox replay, and an end-to-end execution-failure journey remain unproven in this branch. Unit/pipeline tests cover some individual P2 scenarios but do not substitute for those cross-module cases.
