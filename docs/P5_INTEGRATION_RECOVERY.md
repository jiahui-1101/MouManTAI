# P5 Integration Recovery — 2026-10-23

## Baseline and Scope

- Branch: `feat/p5-integration-recovery`
- Base: `origin/main` at `1d540e855895d517b5bad6efb2649e10d8e776bf`
- No database migration was needed.
- Header-based synthetic identity is off by default. Worker subscriptions remain off unless the keyed isolated-E2E gate is enabled.

## Producer / Consumer Registration Matrix

This matrix reflects event names and payloads present in code on the branch base, plus the P5 registrations added for this recovery.

| Event | Producer and payload evidence | Consumer / registration | Status and owner |
|---|---|---|---|
| `business.context_updated` | Required by the system handshake table; no producer with this name is present on `origin/main`. P1's `CoreContextPublisher` calls Core and Core writes `commitment.context_ready` with `context_id`, `order_id`, `commitment_id`, and `audit_id`. | None under this name. | **Missing name / contract mapping needed** — P1 + P5. Current code maps the handoff to `commitment.context_ready`; record the mapping before a future contract rename. |
| `commitment.context_ready` | Core emits this after eligible P1 context publication. | P2 `p2_feasibility_evaluator` exists in `backend/app/context/p2_consumer.py`; it is not registered by the isolated worker. It builds a snapshot from `build_production_example()`. | **Missing runtime registration** — P2 must provide an approved persisted-source handler before P5 wires it. Left unregistered to avoid writing an authoritative assessment from synthetic fixture data. |
| `commitment.proposal_offered` | Core proposal creation emits proposal ID/version, audit ID, and evidence refs. | P2 `p2_proposal_evaluator` exists in the same helper; it is not registered by the worker and uses a synthetic example snapshot. | **Missing runtime registration** — P2/P5. Left unregistered until the consumer uses an approved operational source. |
| `commitment.confirmed` | Core confirmation emits the exact proposal ID/version, decision, audit ID, and evidence refs. | `p2_confirmed_evaluator`, backed by persisted confirmed-event and operational-source readers; isolated worker registration requires the keyed gate. | **Exists / gated** — P5 worker composition, P2 handler. |
| `commitment.at_risk` | Core writes this when an authoritative assessment changes a confirmed commitment to `AT_RISK`; payload includes assessment/version/snapshot/evidence/affected IDs. | `p3.recovery_trigger.v1` uses the persisted Core assessment lookup; isolated worker registration requires the keyed gate. | **Exists / gated** — P5 worker composition, P3 handler. |
| `recovery.communication_requested` | P3 durable handoff persists the proposed plan/proposal version, approval evidence, snapshot, and approved terms into the Core outbox. | P4 resolves the exact persisted source event through its typed `RecoveryCommunicationReference`; it is not a worker subscriber. | **Exists as a source contract** — P3 producer, P4 reader. |
| `confirmation.accepted` | P4 terminal event payload includes confirmation/communication/outbound IDs, proposal/version, terms digest, response state, evidence refs, `P4_EVIDENCE_ONLY`, `SYNTHETIC_ONLY`, decision ID, attempt ID, and intent. | P4 bridge calls `p5.confirmation.required`; P5 re-reads the persisted evidence, checks tenant/identity/proposal/version bindings, and calls Core in the dispatcher's transaction. | **Exists / gated** — P5 command and worker registration, P4 evidence producer. |
| `confirmation.rejected` | Same P4 terminal envelope as acceptance. | `p5.confirmation.required` updates only the current proposal/agreement state and leaves accepted terms untouched; `p3.confirmation_response.v1` records the response and publishes the replan event. Both are mandatory named subscribers. | **Exists / gated** — P5 Core, P3 replanning, P4 evidence producer. |
| `confirmation.counteroffer_received` | Same terminal envelope plus the validated persisted `proposed_changes`. | P5 validates the evidence but does not infer terms; `p3.confirmation_response.v1` owns counteroffer replanning. Both are mandatory named subscribers. | **Exists / gated** — P5 Core validation, P3 replanning, P4 evidence producer. |
| `recovery.replan_required` | P3 confirmation consumer publishes the existing typed event after REJECT/COUNTEROFFER handling. | P5's `P5RecoveryOutboxBoundary` checks the service principal, tenant, correlation and event type, then appends without committing. Dispatcher commit includes P3 state, outbox and `processed_events`. | **Exists / gated** — P3 producer, P5 transactional outbox boundary. No second worker consumer is needed for the P3-owned replan. |
| `recovery.action_completed` / `recovery.action_failed` | P3 orchestrator prepares typed events through `RecoveryEventCoordinator`. | No P5 runtime outbox subscriber is registered for these action outcomes. | **Missing durable Core handoff** — P3/P5. Action success remains separate from fulfilment; it cannot set `FULFILLED`. |
| `commitment.fulfilment_verified` | Core emits this only after the exact evidence policy passes and agreement is `CONFIRMED`. | No worker consumer; Core aggregate, audit and outbox are updated together. | **Exists; no consumer required** — P5 Core. |

### Terminal Confirmation Rules

- `ACCEPT` and `REJECT` must match the current active Core proposal and expected commitment version. Acceptance applies revised terms only when the exact current proposal has them. Rejection leaves terms unchanged.
- `COUNTEROFFER` is validated and handed to P3; Core does not infer or persist proposed terms.
- The dispatcher uses `processed_events` and commits the Core transition/audit/outbox with the P4 consumer marker. Rejected and counteroffer events require both named consumers; wildcard subscriptions do not satisfy D-017.
- Missing named subscribers leave terminal response events `PENDING`. Failed consumers roll back all handlers in that delivery and follow the existing retry/dead-letter policy.
- A stale `confirmation.rejected` or `confirmation.counteroffer_received` event is deterministically superseded when its tenant, commitment, proposal ID, and proposal version resolve to exactly one durable P3 plan whose recorded Core version is no later than the event version, and the current Core commitment version has advanced. The dispatcher writes one `commitment.event_superseded` audit, publishes the event, and invokes no subscriber, including P3.
- For any stale event not proven superseded by that exact P3 plan binding, missing a required `processed_events` marker leaves it `FAILED` for reconciliation (or dead-lettered after the existing retry limit); the dispatcher does not invoke consumers. If all required markers already exist, the stale event is audited and published idempotently.

## Fulfilment Evidence Policy

There is no trusted operational delivery connector in this demo. A fulfiller may submit only exact synthetic refs in this format:

```text
ev_synthetic_delivery|<tenant_id>|<commitment_id>|<evidence_id>
```

Every ref in the request must match the caller's tenant and the target commitment, and at least one ref is required. The full string must match; a prefix, substring, receipt, message, action result, or legacy `ev_ops_delivery_*` label is not proof. This format is explicitly synthetic and does not claim a real-world POD. No table or migration was added.

## Synthetic Demo Startup

The API checks `MOUMANTAI_SYNTHETIC_MODE=1` before accepting the fixed server-side `X-Tenant-ID` / `X-Actor-ID` role map. It defaults to `0` (off). These headers resolve to fixed demo actors and are not authentication; enable this flag only for synthetic/test environments and never in production. Worker subscriptions additionally require `MOUMANTAI_ISOLATED_E2E=1` and a server-owned `MOUMANTAI_ISOLATED_E2E_KEY` of at least 32 characters.

The shared `app.main` entrypoint applies the same default-off gate to P1 message, context, attachment and `/dev/p1` routes, which have their own development identity dependency. P1's separate `app.context.dev_app` is explicitly development-only and is not mounted by `app.main`; its smoke runner requires `P1_TEST_DATABASE_URL` ending in `_test`.

PowerShell from the repository root:

```powershell
$env:MOUMANTAI_SYNTHETIC_MODE = "1"
$env:MOUMANTAI_ISOLATED_E2E = "1"
$env:MOUMANTAI_ISOLATED_E2E_KEY = "replace_with_server_owned_key_of_at_least_32_chars"
docker compose up --build
```

Replace the key placeholder with a local server-owned value and do not commit it. For API-only work with no background consumers, set `MOUMANTAI_SYNTHETIC_MODE=1` and leave `MOUMANTAI_ISOLATED_E2E=0`. The root README has PowerShell and bash startup commands; `.env.example` keeps all gates off and contains placeholders only. The Vite development proxy sends actor headers, so its backend must be started with synthetic mode enabled. `scripts/evaluate_metrics.py` also uses header identity and must be invoked with synthetic mode enabled. Seed scripts connect to the database directly and do not bypass API identity checks.

### Demo startup check

Before a reviewer or demo operator starts the API, set `MOUMANTAI_SYNTHETIC_MODE=1` in the environment consumed by the API service (Compose reads the shell value and passes it to `api`). This is the only required variable for header-based API/demo identity. Without it, header identity requests return HTTP `403` with code `SYNTHETIC_IDENTITY_DISABLED`.

For the background confirmation/recovery demo, also set `MOUMANTAI_ISOLATED_E2E=1` and `MOUMANTAI_ISOLATED_E2E_KEY` to a local server-owned value of at least 32 characters; Compose passes these to `worker`. If the flag is unset or `0`, isolated subscribers remain unregistered and their outbox events stay pending. If the flag is `1` but the key is too short or absent, the worker exits with `Isolated E2E worker requires a server-owned mutation key`. Keep both worker gates off outside a synthetic/test environment. `P1_AI_ENABLED=false` is recommended for the offline deterministic demo, but is not an identity gate.

## PostgreSQL Scenario Status

No PostgreSQL scenario has been run locally. Each status below is **NOT RUN** until the existing `backend-postgres` job from PR #38 reports a result.

| Scenario | Status | Where it runs |
|---|---|---|
| Duplicate delivery / confirmation replay | NOT RUN | `backend/tests/integration/test_p5_postgresql_scenarios.py::test_postgres_p4_accept_commits_core_transition_audit_and_processed_event_atomically`; also `test_confirmed_p2_event_retries_atomically_through_core_risk_to_p3_case`. |
| Stale or out-of-order mandatory event | NOT RUN | `backend/tests/integration/test_p2_confirmed_to_p3_postgresql.py::test_stale_confirmed_event_is_not_discarded_without_p2_completion`; exercises stale mandatory delivery and reconciliation. |
| Stale proposal version | NOT RUN | `backend/tests/integration/test_p5_postgresql_scenarios.py::test_postgres_stale_p4_proposal_cannot_overwrite_newer_proposal`. |
| Wrong tenant / evidence scope | NOT RUN | `backend/tests/integration/test_p5_postgresql_scenarios.py::test_postgres_fulfilment_evidence_must_be_exact_and_tenant_scoped` and `test_postgres_wrong_tenant_unauthorized_role_and_unconfirmed_fulfilment_are_rejected`. |
| Unauthorized approval | NOT RUN | `backend/tests/integration/test_p3_live_postgresql_http.py::test_real_http_worker_restart_and_verified_action_on_migrated_postgresql` checks a staff actor receives 403. |
| Invalid / forged confirmation | NOT RUN | `backend/tests/integration/test_p5_postgresql_scenarios.py::test_postgres_p4_confirmation_rejects_tampered_persisted_event`. |
| Missing fulfilment evidence | NOT RUN | `backend/tests/integration/test_p5_postgresql_scenarios.py::test_postgres_fulfilment_missing_evidence_and_stale_version_fail_closed`. |
| Worker restart / replay | NOT RUN | `backend/tests/integration/test_p3_live_postgresql_http.py::test_real_http_worker_restart_and_verified_action_on_migrated_postgresql`; P5 confirmation redelivery is also covered in the duplicate-delivery test above. |
| Failed consumer and retry | NOT RUN | `backend/tests/integration/test_p2_confirmed_to_p3_postgresql.py::test_confirmed_p2_event_retries_atomically_through_core_risk_to_p3_case`. |
| No external side effect in synthetic confirmation | NOT RUN | `backend/tests/integration/test_p5_postgresql_scenarios.py::test_postgres_p4_accept_commits_core_transition_audit_and_processed_event_atomically`; uses P4's synthetic inbound fixture and `LocalMockProvider`, and asserts `SYNTHETIC_ONLY`. |

## PostgreSQL CI

PR #38 (`feat/p5-postgres-ci`) owns the existing `backend-postgres` job. PostgreSQL scenarios in this branch use the existing `REQUIRE_POSTGRES`-based skip mechanism when PostgreSQL is unavailable locally; after #38 merges, that job is responsible for running them. No PostgreSQL service was started locally, and all PostgreSQL scenarios remain **NOT RUN — no CI output available**; BE-03 stays **In progress, pending CI evidence**.
