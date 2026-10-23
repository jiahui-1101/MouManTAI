> Historical snapshot through `ebc4b01`, before the later Main/P5 merge. P5 amendment, multi-item, router and model-worker statements below describe that snapshot only. Current status and continuation: [PHASE2_CHECKPOINT.md](PHASE2_CHECKPOINT.md). Earlier tests are not tests of the newly merged branch.

# P1 operational extraction audit — 2026-10-22

Status: bounded audit/fixes verified locally; **P1 is not fully accepted or production integrated**. Actual branch: `feat/p1-ai-pipeline` (requested historical branch was `feat/p1-context-intelligence`). Baseline `71c2d20`; no push, merge, paid provisioning, or remote worker deployment. Other contributors' commits/changes were preserved.

## Requirements reviewed and implementation assessment

Read in full before editing: `docs/REQUIREMENTS_SYSTEM.md`, `docs/requirements/PERSON_1_CONTEXT_REQUIREMENTS.md`, root `AGENTS.md`, `docs/TEAM_LOG.md`. No applicable nested AGENTS files were found. Also reviewed `docs/p1/HANDOFF.md`, `P1_02B_FIX_VALIDATION.md`, `BATCH_6_STAGE_A_PROPOSAL.md`, `FINAL_DELIVERY_AND_ACCEPTANCE.md`, the CPU spike `backend/app/context/experiments/ai_spike/REPORT.md`, `docs/contracts.md`, `reply_P1.md`, `reply_P2.md`, and P2's `backend/app/feasibility/PHASE7A_HANDOFF.md`. No separate current integration-assumptions file was found; existing assumptions are distributed across these records. Historical plans are not accepted schemas.

| Requirement / source | Actual assessment and bounded correction |
|---|---|
| System §2.2 lines 71–81; P1 BE-03 lines 56–63; AGENTS §8 | L0 rules first, useful L1 GLiNER/OCR, selective L2 Qwen. Old routing called models for missing metadata; now only unresolved SKU/quantity triggers text interpretation. Factory default Qwen only; GLiNER opt-in. Missing timezone/year/identity and missing unit alone do not justify calls. |
| P1 FE-01/02 lines 17–30, BE-02 lines 50–54 | Preserve originals, exact spans, method/version, review history. Original messages are unchanged; full model observations and grounded normalized subspans are distinct. UI now shows all conflict evidence, actual attempt state, and explicit synthetic timezone. |
| System BusinessContext lines 87–104; P1 contracts lines 78–99 | Missing/conflicting terms must remain uncertain. Removed invented units, midnight/default deadlines and evidence. DATE_ONLY stays a date candidate, not midnight. Human review requires explicit offset and validated fields. |
| P1 identity lines 65–71; AGENTS §7/9 | Model output cannot verify identity, prove payment or confirm a commitment. Association considers deterministic source references only; document amounts/receipts are observations. No fuzzy candidate auto-link. |
| System handshake lines 174–186; AGENTS §3/4 | Only approved Core operations may publish. P1 now locks/rechecks current context/version and commits the Core/P1 pointer atomically. Non-REQUESTED changes fail closed because current Core facade would overwrite terms. Shared schema/amendment/auth decisions remain P5/P2 work. |
| System testing lines 213–230; P1 tests lines 107–122; AGENTS §10 | Unit/API/PostgreSQL/model-adapter/frontend tests, frozen conversational evaluation and real UI exercised. Mock success is not GPU proof. Real endpoint evaluation failed; no model accuracy uplift claimed. |

Operational path reviewed: synthetic composer → adapter/envelope → PostgreSQL ingest → `PostgresMessageRepository.process` → deterministic extraction → lazy proposal service → endpoint/protocol/worker → source/domain normalization → persisted attempts → context/review → publication → Inbox provenance. Related files are under `backend/app/context/` and `frontend/src/features/context/`.

## Original persisted examples and root causes

Records were read without reprocessing or modifying their original data/history.

**A:** provider `test-colab-gpu-001`, internal `942c78f4-b7d6-4f84-850c-b81998b90568`.
Text: `Hello boss, urgently need 40 burgers for tomorrow 3pm to Bangsar branch`.

- L0 quantity was blocked by a message-global comma/punctuation guard. `3pm` was already excluded from quantity numbers; time-token leakage was not this case's cause. Removed punctuation-only rejection while retaining alternative/negation/correction/multiple-quantity guards. Fixed L0 now extracts SKU BURGER and quantity 40.
- Model-labelled quantity `40 burgers` failed the old numeric-only whole-span validator. This is the returned model observation, not evidence that 40 is a SKU quantity by itself. Normalization now requires a uniquely validated L0 quantity subspan inside the observation; it preserves both full observation and numeric source span. Unsupported associations remain provisional/rejected.
- Persisted `message_at` and `business_timezone` are null. Delivery cannot safely become an instant. `received_at=2026-10-22T08:00Z` (16:00 KL) is later than `ingested_at=01:47:22.934803Z` (09:47 KL) by about 6h13m; this is a source clock anomaly, not display-zone conversion. No timestamp was rewritten. New extraction marks even otherwise supported delivery unresolved when receipt is in the future relative to storage.
- Three historical attempts at 01:47:25, 02:13:37 and 02:19:30Z show GLiNER proposals / Qwen HTTP failure, without trustworthy per-call device telemetry. Original completion timestamps were taken before model completion; old durations cannot establish inference time.

**B:** internal `f2d5210e-9ecd-412d-8708-82920138d71b`, provider `msg_idem_d7be1a3d1a`.
Text: `Need 15 burgers tomorrow`.

- L0 correctly extracted BURGER/15; missing unit remains missing. GLiNER product observation `15 burgers` was compared as a raw string against canonical BURGER, creating a false conflict. Strict whole approved alias plus optional supported quantity/unit prefix now normalizes it to BURGER and classifies equal values as duplicate observations. Rejected observations cannot invalidate valid rules.
- Missing timezone remains unresolved; the model cannot supply trusted metadata. Current synthetic composer explicitly sends the selected business timezone (or null when missing). Historical records remain null; the old record alone cannot prove which historical UI omitted it.
- Two attempts at 01:56:04.475637 and 01:56:05.781586Z are about 1.306s apart. Historical rows lack operation/trigger IDs, so intentional reprocess versus duplicate delivery is **not determinable**. New processing uses per-operation IDs under row lock, stable network retry, UI in-flight suppression, and separate explicit-reprocess history.

The broad observation labels came from the model/old worker output. Configuration cannot guarantee a trained model's label meaning; normalization gates must independently verify source and domain support. No exact-message exceptions were added.

## Corrected behavior and boundaries

- L0 version `p1-deterministic-v4`; combined observation version `p1-ai-pipeline-v2`. Greetings, harmless punctuation and labelled reference/phone numbers do not alone block supported quantity extraction. Semantic alternatives, cancellation (including Malay `jangan`/`batal`), fractions/negatives, competing products and incompatible units remain guarded.
- Relative dates use `message_at`, otherwise `received_at`, never processing clock. Source policy/provenance is recorded; future message/receipt clocks and delivery already past at receipt require review. No timezone from language/phone/destination/browser and no hard-coded year. Lower-bound, multiple independent dates/times, invalid partial times, nonexistent/ambiguous DST instants remain unresolved. Unsupported Malay `esok` is visible uncertainty, not false missing/valid normalization.
- Model output is parsed/schema checked, then source grounded and domain checked. Raw observation, normalized value, original spans, model/revision and normalization version are retained. Dispositions are rejected / duplicate / proposal / conflict. All model fields remain provisional: **accepted model fields = 0**. Confidence is not a calibrated probability.
- Valid rule/HUMAN values are preserved. Reviewed contexts survive reprocessing; ambiguous verified follow-ups preserve previous values and introduce review conflicts. No default `pcs`, no automatically chosen candidate order, no invented source IDs or review quote.
- Document/OCR candidates cannot borrow another tenant's catalog, invent units/quotes, prove payment or establish identity. Actual PaddleOCR-backed test ran; no model-output execution/tool invocation exists.
- UI distinguishes configuration, attempted call, validated response, rejected/provisional observations, zero accepted contribution, fallback and unverified/reported GPU. Static “Cloud Tesla T4 active” and AI-success badges were removed.

## Real model / resource evidence

Local host: Windows, Python 3.13.2, i5-1240P (12 cores / 16 logical), 15.68 GiB physical RAM, Intel Iris Xe (no local NVIDIA CUDA). Disk free at final observation: 35.37 GiB; this changes with usage. Optional inference dependencies remain separate from application installation. Only missing already-declared test dependency `alembic>=1.13,<2` was added to the app venv for migration collection (resolved Alembic 1.20.1, Mako 1.4.3, MarkupSafe 3.0.4).

Prepared worker checkpoint pins:

| Model | Revision | License / runtime |
|---|---|---|
| `urchade/gliner_multi-v2.1` | `443d26d654e0324125a96bebd8e796c14ff2efe6` | Apache-2.0; GLiNER 0.2.22 |
| `Qwen/Qwen3-4B-Instruct-2507` | `cdbee75f17c01a7cc42f958dc650907174af0554` | Apache-2.0; Transformers 4.51.0 |

Prepared image is digest-pinned PyTorch 2.7.1 / CUDA 12.8; other pins are in `backend/app/context/ai/requirements-gpu.txt`. This is a prepared configuration, **not an observed remote deployment**. Official cards: [GLiNER](https://huggingface.co/urchade/gliner_multi-v2.1), [Qwen3](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507); dtype capability follows [PyTorch CUDA API](https://docs.pytorch.org/docs/stable/generated/torch.cuda.is_bf16_supported.html). Hugging Face libraries/downloads are not hosted inference subscriptions.

Old Colab wrapper actually loaded Qwen2.5-1.5B but labelled it Qwen3-4B; GLiNER was unpinned and metadata/static dtype could mislead. Replaced it with the shared pinned CUDA worker/protocol, runtime device checks, BF16 capability detection else FP16, bounded authenticated requests, no CPU fallback or automatic tunnel/server creation. Retired a local regex endpoint that impersonated model inference. Historical rows did not store the endpoint URL, so it is impossible to attribute every old result to that simulator.

One actual existing remote GLiNER response was observed for `Synthetic order: burgers serving 40 guests`:

```json
[{"field":"product","quote":"burgers","start":17,"end":24},
 {"field":"quantity","quote":"40 guests","start":33,"end":42}]
```

Wall 1.029706s; remote reports inference 0.029005s, load 0s (warm, not cold-load benchmark), peak 4,277,141,504 bytes, Tesla T4, torch 2.11.0+cu130, dtype bfloat16. The old worker used static metadata; these reports do **not independently attest actual parameter CUDA/dtype/revision**, and `40 guests` does not establish ordered quantity. No successful real Qwen3 inference was verified. The corrected remote worker was not deployed/restarted. Later endpoint requests all failed; detailed sanitized output is local ignored `.local/p1-audit-real-smoke.json`.

No account, paid instance, subscription or resource was created/extended by this audit. Existing provider billing and teardown state were not accessible/verified; no “$0 account spend” or “teardown complete” claim is made. Client timeout/call count does not cap provider billing.

## Frozen development and evaluation

Runner: `backend/app/context/experiments/pipeline_audit.py`; labels: `pipeline_audit_fixtures.json`; tests: `tests/test_pipeline_audit.py`. Frozen in `e0adc33` before held-out evaluation. SHA-256 `7d7e950a2d27a77376140f298e7b2484e93a8c935a9a350c4d94efde62bdda40`.

10 development / 16 evaluation examples; evaluation has 4 English, 4 Chinese, 4 Malay, 4 mixed. Fixed source timestamp `2026-10-20T10:00:00+08:00`, declared business timezone per case, no current-date gold. Includes conversation, alternatives/cancellation, code switching, unrelated numbers and untrusted instructions; additional multi-item, fragmented-follow-up, DST and missing-evidence behavior is covered in regression tests. Scope remains the provisional synthetic BURGER catalog, integer quantities and explicitly supported date/unit patterns, not general multilingual commerce understanding.

Scoring: exact `(field_name, normalized_value)` pairs for VALID L0 fields only. A wrong value counts FP and misses the gold value (FN). Unresolved/model proposals are not accepted fields. This is not span F1, identity correctness, full-context readiness or confirmation accuracy.

| Split / field | Gold | TP | FP | FN |
|---|---:|---:|---:|---:|
| Development total | 24 | 24 | 0 | 0 |
| Evaluation SKU | 16 | 16 | 0 | 0 |
| Evaluation quantity | 10 | 10 | 0 | 0 |
| Evaluation unit | 8 | 8 | 0 | 0 |
| Evaluation delivery | 5 | 5 | 0 | 0 |
| Evaluation total | 39 | 39 | 0 | 0 |

Precision/recall/F1 = 1.0 on these 39 supported gold pairs. Quantity accepted in 10/16 cases, unit 8/16, delivery 5/16; excluded cases remain uncertain. Do not generalize this small result to arbitrary unseen text. Rules versus combined accepted results are identical because no model field is auto-accepted.

The existing remote evaluation explicitly opted into **both** stages: 6/16 messages routed, 12 actual requests, **12 transport_or_schema_error**, 0 successful model observations, 0 accepted model fields. Remaining 10 cases skipped both calls as not_needed. Default operational Qwen-only routing would need 6 calls for this dataset. Model precision, hallucination rate and invalid structured-output frequency cannot be measured from failed transport/schema responses; they are **unavailable**, not zero. No claimed model uplift. Mock adapters separately exercise rejected/duplicate/conflicting observations, timeout, malformed schema and missing/inconsistent evidence.

Reproduction (PowerShell from repository root; private env must already exist, never paste its contents):

```powershell
.venv/Scripts/python.exe -m app.context.experiments.pipeline_audit --split development --output .local/audit-new-development.json
.venv/Scripts/python.exe -m app.context.experiments.pipeline_audit --split evaluation --output .local/audit-new-evaluation.json
# Existing approved endpoint only; does not create any resource. Never overwrite evidence files.
.venv/Scripts/python.exe -c "from app.context import dev_app; import sys; from app.context.experiments.pipeline_audit import main; sys.argv=['pipeline_audit','--split','evaluation','--output','.local/audit-new-remote.json','--live-existing-endpoint','--stages','gliner,qwen']; main()"
```

Existing captured results: `.local/audit-conversation-development.json`, `audit-conversation-evaluation-rules.json`, `audit-conversation-evaluation-remote.json`; ignored, not committed. Weights, databases, caches, credentials and large output are excluded from Git.

## Final validation and real UI

```powershell
. .\backend\app\context\dev\load-env.ps1 -Path .local/p1.env
$env:P1_DATABASE_URL=$env:P1_TEST_DATABASE_URL
$env:P1_AI_ENABLED='false'
.venv/Scripts/python.exe -m pytest backend/app/context/tests backend/tests -o addopts='' -q -ra --tb=short -k 'not test_thread_concurrent_reservations_prevent_overallocation'
# 501 passed, 2 skipped, 1 deselected, 6 warnings in 152.48s

.venv/Scripts/python.exe backend/app/context/export_openapi.py
npm.cmd --prefix frontend run generate:types
cd frontend
npm.cmd test
# 228 passed, 5 skipped; 17 files passed, 1 skipped
npx.cmd tsc --noEmit -p tsconfig.app.json
npm.cmd run build
# both passed; Vite 112 modules, 2.77s
```

Initial final-suite collection failed because Alembic was absent, then the declared dependency was installed and the complete command above passed. Backend skips are 2 opt-in `P1_RUN_REAL_GPU_SMOKE` checks (their historical reason says “Paid endpoint”, but payment is not technically required). One shared SQLite native-thread reservation test is explicitly excluded because an earlier Windows/Python 3.13 run crashed in native code; that concurrent behavior remains unverified here. Frontend 5 skips are the P5-host `LIVE_API=1` smoke suite; no destructive shared DB reset was run. Warnings: missing Paddle ccache and Alembic legacy path separator. No amendments-success skip remains disguised as passing integration; tests now assert blocked non-REQUESTED changes and unchanged confirmed terms.

Actual UI at `http://localhost:5173/inbox` → existing P1 development API was exercised with unique synthetic records, preserving originals:

| Case / provider suffix (`audit-ui-…-e0adc33-01`) | Internal ID | Observed |
|---|---|---|
| short (submitted through composer) | `9b4a94a9-eb6c-4982-bb5b-21148e06d198` | BURGER/15 VALID, unit missing, DATE_ONLY, no model call |
| conversation | `5b83232d-a614-4226-8e7c-350202a270fc` | BURGER/40 VALID, explicit EXACT time, no model call |
| ambiguous | `396b8e55-03f4-40df-b911-452ae5efd0a2` | quantity unresolved, both 40/50 evidence, failed model / rules fallback |
| missing-timezone | `1f3914ff-c028-4941-8684-772721ab4aa2` | quantity 15 preserved, delivery unresolved, no model call |
| unavailable | `5d7fb8ce-36ec-4af6-b5c2-792f047063ff` | SKU preserved, quantity unresolved, attempted inference unsuccessful / GPU unverified |

All five remain identity UNVERIFIED and no accepted model fields. Four API-seeded messages use fixed source `2026-10-22T07:00Z`; composer case uses the form's explicit timestamp/timezone. Raw response evidence: `.local/audit-ui-cases.json`; screenshot `.local/audit-ui-conflict.jpg`. Tested default 319px viewport: fixed details width 304px, left 0 (previously 580px extending left); Close works. Desktop view also exercised and viewport restored. Browser `127.0.0.1:5173` was unavailable because current Vite listens on localhost; no existing user server was stopped.

## P5/P2 coordination and safe next work

Actual shared schema is `backend/app/core/schemas.py:165` (BusinessContext), not a planning note. It has an offset datetime but no DATE_ONLY or EXACT/DEADLINE qualifier. P1 readiness/identity statuses need explicit mappings; model candidates cannot supply readiness/identity. Current conservative P1 adapter publishes only one supported explicit-unit item, verified identity, evidence-backed **DEADLINE** and complete current context; DATE_ONLY, EXACT and lower bounds are blocked pending agreement. Core fallback to `now` is never used to repair missing P1 delivery.

`backend/app/core/integration.py` currently updates existing terms without an amendment gate; `core_publisher.py:203` blocks non-REQUESTED publication. Accepted `reply_P1.md` describes amendment/proposal behavior, but implementation is not that accepted contract. **BLOCK-P1-AUDIT-CORE-AMENDMENT:** P5 must provide the approved versioned amendment operation; P2 then consumes authoritative confirmed terms, not extraction candidates. No shared Core code/schema/migration changed in this audit.

Also coordinate P5 application host tenant/auth dependency and route mounting (`backend/app/main.py:39` mounts Core only), Alembic migration after 0007 for P1 tables, delivery/status mapping and multi-item representation. Current shell shows `tenant_demo_01` while P1 dev configuration uses its synthetic tenant; this is explicitly a local host integration gap, not production tenant/auth proof. P1 dev actor roles are server-selected but dev actor headers are not production authentication. Same-context publication locking/replay is tested; global same-order uniqueness across distinct contexts remains a shared Core concern.

Recommendation: retain L0 plus review, preserve OCR/source observations, keep GLiNER opt-in and Qwen provisional/selective. A real deployment of the corrected worker plus successful held-out GPU evaluation is required before claiming useful model uplift. No automatic TASK 2C or further model rollout. Do not describe P1 as complete until these shared integration and real-runtime gaps are resolved.

## Local change evidence

Each coherent change was tested before its local commit. These are audit commits, not unrelated contributor work:

| Commit | Purpose / relevant verification |
|---|---|
| `73053ff` | Conversational quantity guards; deterministic suite 156 passed |
| `ab86c41` | Selective routing, grounded normalization; 23 passed |
| `6f9e38d` | Remove simulator, shared pinned CUDA wrapper; 27 passed |
| `e95ab64` | No invented context/Core terms; 24 passed, historical P5 coordination skip |
| `25ecf34` | Attempt provenance/operation idempotency; 19 backend passed, 15 frontend passed/build |
| `70eb24c` | Unsupported delivery/future source clocks; 41 passed |
| `632fc0e` | No model-based identity/order authority; 15 passed |
| `ad106ce` | Explicit timezone and human validation; 7 backend / 7 frontend passed |
| `6fa881f` | Document source/tenant/unit safety; 8 passed (real OCR) |
| `bb39d44` | Explicit integration deadlines/evidence fixtures; covered by final suite |
| `5b00193` | Pipeline v2/reported runtime provenance; covered by final suite |
| `d6bf343` | Malay cancellation safety; deterministic regressions passed |
| `e0adc33` | Frozen dataset and scorer tests passed before evaluation |
| `8c54c52` | Confirmed-term guard / atomic current-context publication; focused safety suites passed |
| `c7b4558` | Reviewed context persistence / ambiguity; final context/API/storage 31 passed |
| `c4d2573` | Generated-order and tenant scope publication; focused safety suites passed |
| `2c1a497` | Equivalent normalized product regression; 11 passed |
| `fad5620` | All evidence and narrow details panel; 14 frontend passed + app TypeScript |
| `ebc4b01` | Regenerated actual operational OpenAPI/types; final frontend 228 passed/build |

Final aggregate results above supersede earlier intermediate counts. This report and current handoff supersede historical completion, GPU success, budget-enforcement and teardown claims; historical entries remain an audit trail, not current acceptance evidence.
