# MouManTAI v2.2 orchestration audit and contract proposal

Date: 2026-10-25
Implementation branch: `feat/v22-business-orchestration-20261024`
Base: open PR #88, head is the latest PR #95 branch commit

## Verified architecture and dependency matrix

| Boundary | Existing authority and route | Status / owner dependency |
|---|---|---|
| Order acceptance | `order_requests`, `mock_orbyte_reservations`, Core `commitments` and audit; `POST /v1/backend-v2/order-requests/{id}/accept-mock` | Synthetic order acceptance exists in #81/#88. It uses a MockOrbyte source snapshot. |
| Supplier disruption | P2 `p2_operational_snapshots`, `p2_supplier_delay_events`; `POST /v1/operations/events/supplier-delay`, `GET /v1/impacts/{impact_id}` | P2 persists the typed event/impact and emits Core risk outbox events. The impact set is grounded in P2 snapshot membership and evidence paths. |
| Accepted-order → P2 source | P2 projection handler invoked after verified Mock acceptance; current schedule read from P2 `ProductionData.plans` | **Implemented on PR #95, synthetic only.** Adds a derived demand row to a new immutable snapshot only when the persisted acceptance event, OrderRequest, Core commitment, receipt, audit and exact fresh P2 plan bind. Otherwise returns `UNRESOLVED` without changing P2 current state. |
| Recovery | `recovery_cases`, `recovery_plan_versions`, `manager_approval_decisions`, `recovery_action_executions`, `internal_recovery_tasks`; `/v1/recovery/...` | Existing P3 owns candidate generation, approval and guarded execution. No new execution route or action authority is proposed. |
| Verified execution | Core `recovery.internal_task_created` audit/outbox plus P3 task/execution/approval rows | Current allowlisted “execution” creates an internal review task. This proves task creation only; it does not prove supplier action, customer-visible milestone, fulfillment, or changed customer terms. |
| Communication | P4 `communication_requests`, recipient preferences, drafts/reviews, outbound messages/attempts; `/v1/communication/...` | Existing P4 authorization/send controls remain authoritative. P4 has no general status-milestone request contract or real channel provider in the inspected baseline. |
| Frontend timeline | Existing order, Recovery, operational-evidence and P4 read APIs | This proposal adds a tenant-scoped evidence timeline read model; Frontend server proxy and display wiring remain a separate handoff. |

## Accepted OrderRequest → P2 source projection: exact missing boundary

The acceptance route in #81 persists the accepted OrderRequest, confirmed Mock reservation receipt, canonical Core Commitment and Core audit/outbox event. The PR #95 follow-up now consumes that exact persisted acceptance event and can add the accepted demand to P2's `p2_operational_snapshots`. P2 supplier-delay candidate discovery reads commitment membership and versions from its before-snapshot, so a valid accepted order without a current P2 projection still cannot be included in that P2 impact calculation.

P2's typed `ConfirmedCommitment` requires more than the accepted order supplies: tenant, canonical commitment ID and version, delivery deadline, and one or more lines with SKU, quantity, unit, `material_use_at`, optional warehouse, and P2 source references. P2 also validates its complete versioned source snapshot and its `SourceKind.CONFIRMED_COMMITMENTS` evidence. In particular, neither a product deadline nor a Mock reservation timestamp is a supported substitute for P2's material-use schedule.

Smallest owner-compatible implementation and current PR #95 behavior:

1. P2 owns an idempotent projection/refresh handler for the durable `commitment.mock_order_accepted` event. It verifies the exact tenant, accepted OrderRequest ID/current version/terms hash, Core commitment ID/version, acceptance audit and confirmed reservation receipt before considering a projection.
2. P2 resolves `material_use_at` from exactly one tenant-bound, version-matched `ProductionPlan` in the current snapshot. Its plan source must be observed by acceptance time and valid through acceptance time; the plan must start at or after acceptance and dispatch by the accepted delivery deadline. Missing, stale, ambiguous, mismatched, or out-of-window schedule evidence returns `UNRESOLVED` and leaves P2's current snapshot unchanged.
3. When source-complete, P2 creates a new immutable operational snapshot version under its existing snapshot row lock, preserving existing data while adding one `ConfirmedCommitment` and matching `SourceEvidence(kind=confirmed_commitments)`. Provenance includes canonical OrderRequest evidence, Core commitment, acceptance audit/event, confirmed receipt and P2 schedule evidence. P2's evaluator and impact logic remain unchanged.
4. The accept response returns `PROJECTED`, `ALREADY_PROJECTED`, or `UNRESOLVED` plus reason codes. Replaying the same accept request/idempotency key rechecks current P2 schedule evidence. A fresh unchanged projection is idempotent; missing or changed P2 scheduling evidence remains unresolved. The older P2 snapshots remain immutable.

This adds no second Order or Commitment entity and no database table: Core remains Commitment authority, Orders remains accepted-request authority, and the P2 snapshot is a derived planning input. Missing outcomes are returned with the acceptance response and are not separately persisted; the existing acceptance event and idempotent route provide retry. P5 continues to link by canonical IDs and exact versions. Production owner review is still required for schedule ownership, snapshot-current promotion and changed-schedule lifecycle semantics.

## Refreshed release and Alembic graph (2026-10-25)

`origin/main` refreshed to `65b525ff00d98771c2b626edd239ac68f80df036` after PR #94, #92, the #81/#82 foundation and later documentation updates merged. Main's current migration head remains `0018_mock_order_requests`; PR #89 has no migration. PRs #83–85 and #88 remain open, so the A–H release baseline is still incomplete. PR #95 remains based on #88 at `d2fa4da975a3d7e939cd1bca2e8f6a0732eec8b6`.

The current branch chain is `0017_p1_real_channel_provenance` → `0018_mock_order_requests` → `0019_mock_supplier_advice` → `0020_mock_forecast_history` → `0021_mock_optimization_dataset` → `0022_mock_memory_history` → `0023_business_orch_links`. Concurrent C1 PR #90 adds a distinct revision `0018_c1_scoped_message_parent` whose parent is also `0017_p1_real_channel_provenance`. These are sibling revisions with different revision IDs (the shared `0018` numeric prefix is not itself an ID collision). When the two branches are present together, Alembic has two heads: `0023_business_orch_links` and `0018_c1_scoped_message_parent`.

Once the release baseline and C1 #90 are both merged, add a merge-only Alembic revision (proposed ID `0024_merge_mock_memory_c1_heads`) with `down_revision = ("0023_business_orch_links", "0018_c1_scoped_message_parent")`. Keep schema operations in their owning revisions: #90 modifies existing `p1_dev.inbound_messages`; #81's 0018 and descendants create the Mock order/advisory/forecast/optimization/memory tables; #95's 0023 creates orchestration references and pending intents. Then validate from the refreshed main baseline on PostgreSQL: both single-branch upgrade paths, combined `alembic upgrade head`, `alembic heads` (one merged head), and downgrade/upgrade of the merge point and owned revisions. Do not reparent 0023 onto the C1 revision or edit the shared #81–90 migrations to hide the branch; preserve both histories and combine them with an explicit merge revision.

PR #92 resolves the previously recorded optional OCR-runtime failure on refreshed main: its dedicated latest-main PostgreSQL image/PDF acceptance run reports 24 passed and zero skipped, and its Docker OCR smoke passed. The OCR item remains stale text in open PR #88's body; that does not make OCR an active blocker on current main. It does not replace the need to rerun release CI and migrated E2E after the A–H baseline lands.

At the latest 2026-10-25 refresh, origin/main is `65b525ff00d98771c2b626edd239ac68f80df036`. PR #83 is open against main and GitHub reports `mergeable=false`; the earlier read-only merge-tree identified a conflict in `backend/app/main.py`. No resolution was applied to that shared branch. PRs #84, #85 and #88 remain open and stacked behind #83; their reported mergeability is true. PRs #86 and #87 are merged. C1 PR #90 is open Draft at head `f7c3f553e6776b3f5ca0bf787bae3ab078a36d97` and currently reports `mergeable=true`; its migration remains sibling revision `0018_c1_scoped_message_parent` from `0017_p1_real_channel_provenance`. PR #95 is open Draft at head `9db096d64a3540171d68107e6504daf9372b648f`, still based on #88's head `d2fa4da975a3d7e939cd1bca2e8f6a0732eec8b6`. Exact-head run `40112205573` passed all six CI jobs; its authoritative PostgreSQL 16 stage upgraded to one current head and reports 975 passed, zero skipped (44 warnings). Keep #95 stacked on #88 until the remaining A–H dependencies have merged in order. Do not reconcile #95 directly onto main before that baseline settles.

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

All current fixtures/adapters are synthetic or Mock. P2 creates an accepted-order demand row only when its own current exact schedule exists; otherwise the result is unresolved. Current P3 action verification is for internal review-task creation only. No real Telegram, WhatsApp, Email, supplier outcome, customer assent, or customer-visible status milestone is claimed. The timeline is an internal diagnostic projection pending Frontend and owner review.

## Post-#88 Main reconciliation (2026-10-25)

The earlier release and migration paragraphs above describe the pre-merge stack and are superseded for this integration candidate. PRs #83, #84, #85 and #88 are merged. Main `7035a509a61f684163cfa828f05d47619c0484f6` was merged normally into #95; the only textual conflict was `backend/app/main.py`, where the integrated router imports retain both Main's Orders/Forecasting/Optimization routes and #95's orchestration route.

The actual Main Alembic chain is `0018_mock_order_requests → 0019_p4_orders_persistence → 0020_mock_supplier_advice → 0021_mock_forecast_history → 0022_mock_optimization_dataset → 0023_mock_memory_history`. The #95 candidate adds `0024_business_orch_links` after `0023_mock_memory_history`. The former published #95 stack contained `0023_business_orch_links` after `0022_mock_memory_history`, along with older revision IDs for Supplier, Forecast, Optimization and Decision Memory. The user confirmed on 2026-10-25 that no shared or staging database was migrated using the old #95 revisions. Those old IDs remain in Git history but are not valid ancestors in the reconciled Main graph. If an unreported database records any old stack revision, inventory its schema and `alembic_version` and approve a database-specific transition before running this candidate. The fresh candidate graph makes no claim that an old deployed stack is automatically upgradeable.

C1 PR #90 remains Draft and unmerged. Its current branch includes `0018_c1_scoped_message_parent` from `0017_p1_real_channel_provenance`, plus merge-only revisions `0019_merge_c1_mock` and `0020_merge_c1_p4` joining its branch with Mock Orders and P4 Orders. If C1 is integrated later, inspect its then-current graph and add a new merge-only revision joining the actual C1 and business heads; do not reuse the earlier proposed `0024_merge_mock_memory_c1_heads` identifier or edit C1's published revisions. C2 PR #96 has no migration and remains a separate provider-adapter contract. Its normalized provider receipts are not durable P4 delivery evidence, and its internal transports are not authorized by a P5 pending intent.

### C1 merge after the first #95 integration candidate

Main advanced to `1c34b8dbcdd944b60c856ceb7a5dd7ada890564f` when #90 merged. Its new `0024_merge_c1_ah` has parents `0020_merge_c1_p4` and `0023_mock_memory_history`. #95's published `0024_business_orch_links` is a separate sibling head from `0023_mock_memory_history`. A normal Main merge preserved both histories. New no-op revision `0025_merge_c1_business_orch` joins `0024_merge_c1_ah` and `0024_business_orch_links`; neither owner migration was edited. An empty disposable PostgreSQL database upgraded to the sole `0025` head. A database at #95's prior `0024_business_orch_links` upgraded by applying C1 and both merge revisions. Downgrade to `0023_mock_memory_history` removed the orchestration tables, and re-upgrade restored the sole head. These checks do not grant P1 source-message evidence customer-assent authority.
