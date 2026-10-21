# P2 Phase 5 API and Integration Handoff — 2026-10-21

**State: PARTIAL.** P2 has implemented five P2-owned route definitions and locally testable request/response boundaries. Production integration remains blocked on P5-owned security, authoritative data, persistence/outbox contracts, empty Impact Set support, and router mounting. The test app mounts the P2 router explicitly; this does not prove that the production FastAPI app is mounted, authenticated, or integrated.

## Approved baseline and ownership

- Branch: `feat/p2-feasibility-engine`.
- Phase 4 local baseline approved by the user: `f6ac87233534f0dc6deef3b5e464e0bd7fd1fd0e`.
- P2 changes are confined to `backend/app/feasibility/`, P2 tracking documents, and P2-only TEAM_LOG entries. No P5 app/Core/DB/schema/auth/migration files or P3 code were changed.
- `origin/main` was fetched and inspected at `4ec2ba1ef7ede4a67352631178a73a6882bcd774`. `FeasibilityAssessment.affected_commitment_ids` still has `min_length=1`; a real empty Impact Set therefore still cannot serialize. No IDs were fabricated and no shared contract was edited.

## P2 route inventory

| Route | P2 behavior implemented | Integration status |
|---|---|---|
| `POST /internal/feasibility/evaluate` | Validates the typed request, requires matching resolved tenant scope, obtains vetted snapshot/commitment through an injectable authority port, checks tenant and versions, then calls the existing pure `evaluate()`. Returns P2-local `EvaluationResult`, preserving status/solver/provenance and an explicit shared-output blocker. | Local route behavior tested. P5 must provide internal authorization, authoritative snapshot/input resolution, and production mounting. It returns unavailable when those dependencies are absent. |
| `POST /v1/commitments/{id}/assess` | Uses Core's tenant-scoped commitment lookup, requires the authoritative current snapshot and matching current commitment/snapshot versions, calls existing `evaluate(snapshot, None, commitment)`, then passes that exact P2 result and snapshot to the P5 writer. | No current-input authority or persistence writer is configured; returns 503 rather than a simulated success. |
| `GET /v1/commitments/{id}/assessments` | Performs tenant-scoped Core commitment lookup before calling the history reader. | No durable versioned history reader exists; returns 503. |
| `POST /v1/operations/events/supplier-delay` | Validates typed delivery-linked ETA evidence, tenant, one declared delivery resource, and increasing snapshot versions; delegates to the processor port. | No authoritative source-row verifier or transactional event/outbox processor exists; returns 503. Repeated unavailable requests do not demonstrate idempotent processing. |
| `GET /v1/impacts/{impact_id}` | Delegates to an injected impact reader. | No approved persistence reader exists; returns 503. |

P2 ports are interfaces, not persistence implementations. The assessment writer receives the route's exact `EvaluationResult`; it must re-read/lock the current commitment and snapshot versions and append this result to immutable history with audit/outbox records in one approved transaction. It must preserve status, solver status, snapshot identity and evidence/provenance. A future adapter must preserve Core's transaction/audit/outbox boundary. P2 does not write agreement, risk, recovery, or fulfilment state. `assess_impact()` remains the only P2 impact calculation and must be called by an approved supplier-event processor rather than duplicated.

## Exact decisions requested from P5

Please provide an explicit answer and the corresponding approved interface/owner for each item:

1. **Router mounting:** approve mounting the P2 `router` in `backend/app/main.py`; specify the prefix/lifespan arrangement and route registration test owned by P5.
2. **Authenticated context and internal access:** replace or wrap the demo header-based `get_request_context()` with authenticated actor identity and authoritative actor-to-tenant membership/role checks. Specify the internal authorization dependency for `/internal/feasibility/evaluate`. Caller-supplied `X-Tenant-ID`/`X-Actor-ID` headers are not proof of identity or production authorization.
3. **Snapshot authority:** implement both evaluator-input resolution and `resolve_current(context, commitment_id, expected_commitment_version)` used by `/assess`. Return the current tenant-scoped commitment and operational snapshot, validate source/evidence and freshness, and concurrency-safely bind their versions. The current provider must supply `current_snapshot_version`; P2 rejects missing authority (503) or a stale snapshot (409). The writer must recheck both versions in its transaction and reject/retry a change during calculation. Specify how historical replay is distinguished from current state.
4. **Empty Impact Set:** merge and test support for `affected_commitment_ids=[]` as the actual Impact Set. Assessment scope must not be substituted for actual affected IDs.
5. **Assessment history:** provide the durable append-only/versioned writer and tenant-scoped history reader contract, including audit linkage, transaction boundary, idempotency key, and stale/current-version behavior. The writer receives the exact `EvaluationResult` produced by P2 `evaluate()` and the immutable input snapshot; it must persist that result without recalculating or changing its status/provenance. P2 will map to the existing Core `FeasibilityAssessment` only after this contract and empty-list schema are verified.
6. **Supplier event/outbox:** identify the transaction owner and interface that verifies `event_id` idempotency, resolves the actual delivery/source row, checks current versions, applies the approved snapshot update, invokes P2 `assess_impact()`, and writes event/outbox/audit records atomically. Specify the failure/retry and duplicate-event response semantics. P2 will not publish an event or claim processing until this exists.
7. **Impact lookup and risk transition:** identify the approved durable impact reader and Core command/event boundary for any authoritative risk update. P2 output intents alone do not change Core state.

These are owner requests only; no P5 task/thread could be identified in the accessible recent or archived Codex task list during this work. The request is recorded here and in the P2-only TEAM_LOG. No P5 response is inferred.

## P3 hypothetical-evaluation contract (P3 code unchanged)

The P3 requirements and P2 implementation agree on the pure Python call:

```python
evaluate(
    snapshot: EvaluationSnapshot,
    proposed_changes: ProposedChanges | None,
    commitment: app.core.schemas.Commitment,
) -> EvaluationResult
```

Import from `app.feasibility.service`. `ProposedChanges` is version-bound to tenant, commitment, expected commitment version, and expected snapshot version; current supported changes are quantity, deadline, and production start. It validates on a private copy and does not insert supply, reserve stock, mutate jobs, or update Core lifecycle state. P3 must reuse this evaluator for alternatives and must preserve UNKNOWN/CONDITIONAL/INFEASIBLE semantics.

The P2 internal HTTP request is currently typed as snapshot + commitment + optional proposal, while its response is a **P2-local** `EvaluationResult`. This JSON shape is provisional; P3 owner confirmation is required before treating it as a frozen cross-module API. It is not a shared `FeasibilityAssessment`. P3's current backend module remains a placeholder, so no HTTP consumer or end-to-end call was verified.

## Validation and limitations

From `backend/`:

```text
python -B -m pytest -o 'addopts=' app/feasibility/tests/test_router.py -q -p no:cacheprovider
16 passed (one existing Starlette/httpx deprecation warning)

python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider
180 passed (one existing Starlette/httpx deprecation warning)
```

The tests exercise a local app that explicitly mounts P2 and Core routers with test dependencies. They cover typed validation, scope/version checks, missing adapters, no false persistence/event success, pure evaluation reuse, and empty/nonempty shared schema behavior. They do **not** establish production router registration, authenticated RBAC/tenant isolation, PostgreSQL persistence, source authenticity, atomic outbox behavior, P3 integration, or end-to-end success. Frontend, live PostgreSQL, production auth, actual event publishing, and E2E were not run.

`docs/AGENTS.md`, listed in the initial instructions, was not present. The repository root `AGENTS.md` was read but still refers to the old PromiseFlow name; canonical MouManTAI system requirements, TEAM_LOG ADR-010, and the user's supplied instructions were followed. No instruction file was guessed or changed.

**Gate: stop for external Phase 5 review. Do not start Phase 6 until that review and the P5 integration blockers are resolved.**
