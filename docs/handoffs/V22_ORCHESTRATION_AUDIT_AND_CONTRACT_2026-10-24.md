# MouManTAI v2.2 orchestration audit and contract proposal

Date: 2026-10-24
Implementation branch: `feat/v22-business-orchestration-20261024`
Base: open PR #88, head `d2fa4da975a3d7e939cd1bca2e8f6a0732eec8b6`

## Verified architecture and dependency matrix

| Boundary | Existing authority and route | Status / owner dependency |
|---|---|---|
| Order acceptance | `order_requests`, `mock_orbyte_reservations`, Core `commitments` and audit; `POST /v1/backend-v2/order-requests/{id}/accept-mock` | Synthetic order acceptance exists in #81/#88. It uses a MockOrbyte source snapshot. |
| Supplier disruption | P2 `p2_operational_snapshots`, `p2_supplier_delay_events`; `POST /v1/operations/events/supplier-delay`, `GET /v1/impacts/{impact_id}` | P2 persists the typed event/impact and emits Core risk outbox events. The impact set is grounded in P2 snapshot membership and evidence paths. |
| Accepted-order → P2 source | No persisted projection from `mock_orbyte_states`/accepted `OrderRequestRecord` into `p2_operational_snapshots` | **Open contract, P5 + P2 + Orders owners.** This proposal never infers the link from SKU, customer, or message text. It links only when the exact commitment, version and terms are already present in the P2 source and accepted-order evidence verifies. |
| Recovery | `recovery_cases`, `recovery_plan_versions`, `manager_approval_decisions`, `recovery_action_executions`, `internal_recovery_tasks`; `/v1/recovery/...` | Existing P3 owns candidate generation, approval and guarded execution. No new execution route or action authority is proposed. |
| Verified execution | Core `recovery.internal_task_created` audit/outbox plus P3 task/execution/approval rows | Current allowlisted “execution” creates an internal review task. This proves task creation only; it does not prove supplier action, customer-visible milestone, fulfillment, or changed customer terms. |
| Communication | P4 `communication_requests`, recipient preferences, drafts/reviews, outbound messages/attempts; `/v1/communication/...` | Existing P4 authorization/send controls remain authoritative. P4 has no general status-milestone request contract or real channel provider in the inspected baseline. |
| Frontend timeline | Existing order, Recovery, operational-evidence and P4 read APIs | This proposal adds a tenant-scoped evidence timeline read model; Frontend server proxy and display wiring remain a separate handoff. |

## Entity reuse / extend / add / deprecate mapping

| Entity | Decision | Reason |
|---|---|---|
| OrderRequest / Core Commitment | Reuse by canonical IDs and exact versions | No duplicate order or commitment authority. |
| P2 operational snapshot, supplier delay event and impact payload | Reuse as disruption and impact authority | P2 already validates and persists evidence and results. |
| Recovery case, plan, approval, execution and internal task | Reuse by references | Existing P3 gates remain in force. |
| P4 communication request, outbound message and delivery receipt | Reuse only after P4 accepts an eligible request | No direct send or fake delivery. |
| `business_orchestration_impact_links` | Add derived, tenant-scoped link projection | Stores exact P2 impact → existing commitment/order acceptance evidence outcome and reason codes. It contains references and evidence summaries, not business state. |
| `business_orchestration_notification_intents` | Add P5-owned pending handoff record | P4 lacks a generic status milestone intent contract. This table cannot represent SENT/DELIVERED and does not replace P4 requests/outbound records. |
| New OrderRequest, Commitment, RecoveryCase, P4 message, provider or recipient authority | Do not add | Existing canonical owners already hold these entities. |
| Legacy notification/status tables | No change | This proposal does not create a second outbound/status authority. |

## Versioned boundary proposal

The API uses versioned P2/P3/P4 records, canonical tenant and entity IDs, timezone-aware timestamps, source/event/correlation identifiers, idempotent source event IDs, server-derived authorization context, exact evidence references, and explicit `SYNTHETIC`, `MOCK`, or `INTERNALLY_VERIFIED` mode/tier metadata.

1. P2 remains the only supplier-disruption intake and impact calculator. Submit typed evidence to `POST /v1/operations/events/supplier-delay` first.
2. `POST /v1/orchestration/impacts/{impact_id}/resolve` materializes an idempotent cross-module link for each P2 candidate. Link status is `LINKED_ACCEPTED_ORDER`, `LINKED_ACCEPTED_ORDER_UNAFFECTED`, or `UNRESOLVED_*`. Only an exact P2 snapshot commitment/version/terms match plus the existing accepted order reservation/audit proof can produce a linked status.
3. Existing `/v1/recovery/...` endpoints continue to list/generate plans, record authorized SME approval, and execute through P3's version revalidation. No orchestration endpoint can approve or execute on the caller's behalf.
4. A mandatory outbox consumer verifies the exact P3 execution, open internal task, manager/owner approval, Core audit and receipt before creating one P4 notification intent. Its event label is `recovery_internal_review_created`. The record stays pending, with no recipient/channel/consent claim and no send status. It must not be worded as a supplier action, delivery, fulfillment, or customer-facing milestone.
5. `GET /v1/orchestration/notification-intents/{id}` and `GET /v1/orchestration/commitments/{commitment_id}/timeline` expose reference-only projections with tenant filtering. The timeline is not a customer disclosure API.

### Owner review required before baseline merge

- P2/Orders/P5 owners must approve the exact accepted-order → P2 source projection and its snapshot refresh semantics. Until then, missing, stale or mismatched source rows stay `UNRESOLVED_HUMAN_REVIEW`.
- P4/Meishuet must approve the status-milestone intent DTO, contact/channel/consent fields and whether the internal task event qualifies for any customer-facing update. This proposal intentionally leaves it pending.
- P5 must review the additive migration and outbox subscriber registration. The branch's migration parent is #88's `0022_mock_memory_history`; the concurrent C1 branch has a conflicting historical `0018` revision and must be reconciled after the release baseline settles.
- Frontend must use a trusted server proxy and display source references, status and evidence tier; do not expose isolated E2E keys.

## Evidence and readiness limits

All current fixtures/adapters are synthetic or Mock. P2's accepted-order linkage can be proven only for already present exact P2 source rows; this branch does not create those rows. Current P3 action verification is for internal review-task creation only. No real Telegram, WhatsApp, Email, supplier outcome, customer assent, or customer-visible status milestone is claimed. The timeline is an internal diagnostic projection pending Frontend and owner review.
