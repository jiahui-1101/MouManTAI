# Phase 6 P2 frontend handoff — 2026-10-21

**PARTIAL: P2-owned views and injected-port tests implemented; shared production integration blocked.**
Phase 5 local correction `85d46b2f48bea9a2e149f6dd70badc7311334061` was externally approved by the user.
Phase 6 requires independent external review. Phase 7 is not authorized or started.

## P5 mounting (proposal; shared files were not edited)

In `frontend/src/App.tsx`, replace only the two existing P2 placeholder elements,
after P5 has approved/provided a stable, authenticated `P2DataSource` instance:

```tsx
import { CommitmentFeasibilityPage } from "./features/feasibility/CommitmentFeasibilityPage";
import { ImpactDetailPage } from "./features/feasibility/ImpactDetailPage";

<Route path="/commitments/:id" element={<CommitmentFeasibilityPage source={p2Source} />} />
<Route path="/impact/:id" element={<ImpactDetailPage source={p2Source} />} />
```

Keep existing AppShell/navigation/router. The pages read `id` through the existing
React Router. An omitted source shows unavailable API with retry, not fixture data.
Do not instantiate a fresh source on every render; replace it on session/tenant
change. Sources are scoped to the authenticated tenant by P5; `tenantId` is a UI
cross-check, never proof of authorization. All authorization remains server-side.

For an explicitly labeled synthetic preview ONLY, P5/test harness can inject
`createPreviewSource()` from `frontend/src/features/feasibility/preview.ts` at
`/commitments/com-001` and `/impact/synthetic-impact-2`. The preview source is never
imported by production page modules, never a fallback, and has no recalculation.
Authored UI examples are based on the prior synthetic buffered scenario, not an
engine run, persisted record or new metric. `com-missing` deliberately demonstrates
an unevaluated candidate; discovery is marked incomplete. The minimal material
projection shows PATTY only, not a complete BOM fixture.

## Exact feature ports and required public response enrichment

See `frontend/src/features/feasibility/models.ts` for P2 presentation projections;
they are not replacement shared API contracts. Core `Commitment`, shared
`FeasibilityAssessment`, enums/constraints/decimal strings are imported unchanged.

P5 must approve the endpoint/response extension and map all fields below before a
full live source is wired. Do not call `/internal/feasibility/evaluate` from a browser.

1. `loadFeasibility(id): Promise<FeasibilityView>` combines:
   - tenant-scoped `GET /v1/commitments/{id}` Core record, including confirmed terms,
     agreement/risk and actual commitment version;
   - persisted shared assessment metadata/history selection, explicitly bound to
     commitment and snapshot versions (do not assume history order is latest);
   - authoritative `current_snapshot_version`, separate from historical assessment;
   - `details` with matching commitment ID/version and snapshot version,
     `evidence_complete`, source rows (ID/ref/observation/valid-through/currentness/
     evidence), target-filtered material rows, target-filtered capacity operations.
   - map material fields directly from EvaluationResult.materials.materials:
     line/SKU, required, usable, reserved, confirmed_incoming, shortage, unit,
     needed_by, evidence refs. `usable` is allocated unreserved lot supply;
     `reserved` is allocated owned reservation, not all tenant reservations.
   - map production operations from EvaluationResult.capacity.operations:
     line/resources/start/finish/required_minutes/available_minutes/evidence.
     Preserve null availability. Constraint reasons and assumptions remain shared
     assessment fields; do not invent safe capacity from absent operations.
   - source freshness must describe relevant complete operational AND production
     sources at the assessment basis, plus authoritative currentness. UI checks
     reported status and validity at assessed_at AND live display time (refreshes
     each minute); it does not establish source trust. Missing source bounds remain
     null/UNKNOWN. Explicit previews use their labeled historical assessment basis.
2. `loadImpact(id): Promise<ImpactView | null>` needs a mounted, authorized persisted
   `GET /v1/impacts/{impact_id}` adapter/enrichment:
   - ImpactAssessment event/tenant/ID, before/after versions, discovery completeness,
     candidate IDs, each CommitmentImpact classification/reasons/material and HARD
     constraint deltas/buffers/paths/evidence;
   - trigger_evidence_refs from OperationalChange, and changed resource rows
     with kind/ID/before/after values/evidence from the actual source snapshots.
     ImpactAssessment alone does not expose ETA before/after values;
   - optional `risk_change` only from a verified Core transition/audit mapping.
     It is not derived from CONFIRMED_IMPACT or an in-memory at-risk intent.
   - missing candidate results remain UNKNOWN; evidence-free confirmed/verified
     classifications are downgraded to UNKNOWN. Empty affected IDs imply nothing
     about verified-unaffected candidates. NO_NEW_ADVERSE_DELTA is separate.
3. Optional `recalculate(id, {expected_commitment_version, expected_snapshot_version})`:
   - only supply after authorized durable assessment and snapshot adapters exist;
   - existing POST `/v1/commitments/{id}/assess` accepts only
     `{expected_commitment_version}`. P5 must resolve/recheck current snapshot
     transactionally. Feature expected snapshot version expresses the viewed basis;
     do not add an unapproved field to the existing POST body;
   - return a fully resolved, valid persisted FeasibilityView response only after the
     authoritative result is obtained. A queued/submitted response is not this type;
   - preserve prior view during pending/errors. Foreign identity, changed terms/version,
     regressing snapshots/time or stale returned versions
     reject replacement; the UI offers retry and explicit current-data reload;
   - unchanged authoritative inputs may return the same deterministic ID/time;
     a correctly bound repeat is valid and is not a version conflict;
   - no Core terms, risk, reservation or operational mutation from this UI.
4. Decode/validate wire data before returning typed projections. Error adapter must
   retain HTTP status/code/message (e.g. FeatureDataError); 403 permission, 409
   conflict, 503 unavailable must reject. Current shared apiRequest throws a plain
   Error and loses status; P5's unmerged new helper must be integrated/reviewed
   before relying on its structured errors. No P2 duplicate client was introduced.

### Presentation boundary — PH6-R1 retained, PH6-R2 supersedes the proof exception

- The P2 runtime classification list contains exactly the five existing backend
  values. An unsupported runtime value rejects the entire response with
  `FeatureDataError(502, "INVALID_IMPACT_CLASSIFICATION", ...)`; the page shows
  error/retry without dropping or reinterpreting the candidate or using fixtures.
  Neither this rejection nor conservative projection changes mutate the input.
- A buffer is labeled `Verified buffer` only when `evidence_refs` is a nonempty
  array of nonblank strings. Missing/non-array/empty/blank refs render
  `Reported buffer — evidence unavailable` and no verified claim for that buffer.
  Reference presence indicates supplied support, not authenticity. P5 remains
  responsible for authoritative evidence validation and complete trusted inputs.
- All displayed buffers of a VERIFIED_UNAFFECTED row are conservatively treated
  as required support. At least one must have a strictly positive decimal-string
  value and adequate references; every required buffer must have adequate refs.
  An empty list, no positive supported buffer, or missing evidence for any required
  buffer yields UNKNOWN with `UNAFFECTED_BUFFER_EVIDENCE_INSUFFICIENT`. Zero,
  negative and invalid values cannot count as positive proof. The structural
  positivity check supports decimal/exponent strings without floating-point
  underflow; it does not recompute feasibility or implement backend `_classify()`.
- Row-level classification evidence remains mandatory; neither unrelated row refs
  nor FEASIBLE/COMPLETED/evidence-complete before/after metadata can bypass missing
  buffer proof. Conversely, complete buffer refs cannot bypass missing row refs.
  The former frontend `unaffected_proof` property, helper type and bypass function
  have been removed. Legacy runtime metadata has no authority in this gate.
- Genuinely independent proof is a **future P5 integration decision** requiring an
  approved authoritative contract and validation. There is no active frontend
  schema/flag/bypass for it. P5 must not wire the removed presentation property.
  Public mapping/authenticated integration and evidence authenticity remain P5
  responsibilities. Other classifications and PH6-R1 rejection/label behavior
  remain unchanged; no backend enum/shared contract changes were made.

`createCoreOnlySource(tenantId, readCommitment)` reuses a supplied P5 reader and
can show actual Core identity/terms without implying an assessment. It cannot
recalculate or load impacts. This seam was tested with an injected reader only;
no live Core API or production authentication was exercised.

## Verified branch distinction and outstanding dependencies

Read-only fetch/inspection verified Main `4ec2ba1ef7ede4a67352631178a73a6882bcd774`,
P2 baseline `85d46b2f48bea9a2e149f6dd70badc7311334061`, P5 feature branch
`a5f99151f2bc88f1c4d2cd530b0243a869a45d9c`.
Empty Impact Set schema support is **IMPLEMENTED ON P5 BRANCH, PENDING INTEGRATION**.
P5 auth scaffolding/TanStack Query/new shared helpers also remain unmerged into
P2; this feature does not import/copy them. Generic outbox availability on P5 does
not integrate the P2 supplier-delay processor. Historical
EvaluationResult.shared_output_blocker is never used by the frontend.

No synchronization performed. A future sync needs explicit authorization and must
preserve both P2 and P5 TEAM_LOG histories. P5 still owns mounting, authenticated
context/internal-service access, authoritative input resolution, transactional
version checks, final shared mapping, assessment/history/impact persistence,
supplier-delay/outbox integration and authoritative Core risk transitions.
P3 pure-evaluator reuse/ProposedChanges and serialized hypothetical HTTP contract
confirmation remain pending; this phase changes no backend calculation or contract.

Nonblocking later backend checkpoint: explicit SKU and unit Commitment-binding
regressions, without reopening approved Phase 5 behavior in this frontend phase.

## Validation limits

Focused component/adapter tests exercise injected ports and labeled fixture data;
HTTP statuses are simulated as structured adapter errors, not live HTTP calls.
App routes still display existing P5 placeholders. No actual production frontend
API integration, live PostgreSQL, supplier processing/outbox, cross-feature E2E or
operational metrics is claimed. Typecheck/build compatibility does not establish
route mounting, public contracts, authentication or fulfillment.
