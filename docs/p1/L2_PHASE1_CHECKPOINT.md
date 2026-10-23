# L2 Phase 1 checkpoint — stop before GPU verification

Branch `feat/p1-phase2-refinement`; implementation commit `75b5c87`. Phase 1 DONE; real L2 inference UNVERIFIED. No endpoint probes, real model calls, model downloads/loads, CPU Qwen, dependency installs or resource startup occurred. No push/merge/PR. Review Drawer commit `018748b` and other existing work were preserved.

Changed implementation: `backend/app/context/ai/service.py` and `ai/worker.py`. Reused strict `RawAnswer`/`InferenceOutput`, exact evidence grounding, pinned model and existing bounded HTTP transport.

- L2 opt-in only (constructor and factory default to GLiNER); unique stages enforce L1 before L2. Escalate unresolved source association, multiple products/values and meaningful interpretation gaps. Do not invoke to invent absent quantities or solve trusted timezone/year/DST/lower-bound metadata.
- L1 sufficient proposals avoid another model. L1 failure may escalate only if a meaningful need remains. All candidates stay provisional and require review; no model publication, identity verification, payment proof or commitment mutation.
- Qwen SKU aliases require whole supported mentions, quantities cannot pick the first digit from guest counts/multiple values, and units require SKU compatibility. Unknown products remain unsupported. Exact full observations and normalized subspans are retained.
- HUMAN values take precedence over older rule values when detecting model conflicts. PostgreSQL regression proves persisted candidates, retained reviewed values after reprocessing, and no Core/outbox side effects.
- Custom adapters also receive a bounded async timeout and fresh Pydantic validation. Existing HTTP timeout remains bounded; automatic POST retries remain **zero** to prevent duplicate inference/jobs. Call counters count attempts, not proof the remote worker received/completed them; cache/shared requests do not count as new calls.
- Qwen worker refuses CPU before importing model loaders. CUDA availability and actual parameter placement still require future runtime verification. No claim of model accuracy, deployed GPU or hardware attestation.

## Tests actually executed

```powershell
. .\backend\app\context\dev\load-env.ps1 -Path .local/p1.env
$env:P1_DATABASE_URL=$env:P1_TEST_DATABASE_URL
$env:P1_AI_ENABLED='false'
$env:P1_RUN_REAL_GPU_SMOKE='0'
.venv/Scripts/python.exe -m pytest backend/app/context/tests/test_qwen_phase1.py backend/app/context/tests/test_ai_routing_and_costs.py backend/app/context/tests/test_ai_proposals.py backend/app/context/tests/test_model_candidate_safety.py backend/app/context/tests/test_ai_endpoint.py backend/app/context/tests/test_ai_worker_protocol.py backend/app/context/tests/test_ai_pipeline_integration.py backend/app/context/tests/test_publication_safety.py -o addopts='' -q -ra --tb=short
```

**85 passed, 0 failed, 0 skipped in 4.64s**, including PostgreSQL. Log `.local/l2-phase1-final.txt`. Covers defaults, stage order, L0/L1 sufficiency, meaningful escalation, multi-item preservation, cache/counters, malformed output, missing/fabricated evidence, unknown/partial SKU, incompatible units, timeout/failure/no retry, HUMAN conflicts and persistence. The existing outage test now uses an actual quantity ambiguity rather than expecting an unnecessary call to fill absent facts. Python compilation also passed for service, worker and opt-in real-endpoint test. No full-suite/L0-L1 benchmark/frontend repetition.

Other test changes: `tests/test_qwen_phase1.py`, `test_ai_pipeline_integration.py`, `test_ai_real_endpoint.py`. The **real-endpoint test was prepared but NOT executed**; it now checks Qwen's reported CUDA placement and prints sanitized synthetic response/runtime evidence.

## Phase 2 — only after user supplies a working GPU endpoint

Required: existing protocol-compatible HTTPS endpoint with Bearer authentication, `engine=qwen`, strict structured output and original evidence. Expected model `Qwen/Qwen3-4B-Instruct-2507`, revision `cdbee75f17c01a7cc42f958dc650907174af0554`. Updated worker must run Qwen on CUDA (`P1_DEVICE=cuda` on remote worker); do not use the existing CPU GLiNER worker for Qwen. Remote metadata remains self-reported, not independent attestation. Full L1→L2 operation needs a worker serving both configured engines; verification below calls only Qwen.

Set credentials privately; never paste them in logs or commits. Keep operational L2 disabled until verification passes. Future exact command (repository root):

```powershell
$env:P1_AI_ENDPOINT_URL='https://YOUR_GPU_HOST/infer'
$env:P1_AI_API_KEY='<private bearer key>'
$env:P1_AI_ENDPOINT_MODE='direct'
$env:P1_AI_TIMEOUT_SECONDS='125'
$env:P1_RUN_REAL_GPU_SMOKE='1'
.venv/Scripts/python.exe -m pytest backend/app/context/tests/test_ai_real_endpoint.py -k qwen -o addopts='' -q -s
```

This is a future real call, **not run during Phase 1**. After successful verification and explicit activation, existing configuration `P1_AI_ENABLED=true`, `P1_AI_STAGES=gliner,qwen` enables selective operational L2; nothing in this phase edited private env or enabled it.

Remaining dependency: user-provided working GPU endpoint, followed by real pinned-model/schema/evidence/runtime smoke and held-out usefulness evaluation. Mock tests do not establish real Qwen quality or hardware. No new P5 handoff/shared-contract change is required for this isolated P1 Phase 1. Earlier migration/auth/date/historical integration tasks remain in the preceding checkpoint; do not treat this L2 implementation as completing them. Stop here; do not start Phase 2 automatically.
