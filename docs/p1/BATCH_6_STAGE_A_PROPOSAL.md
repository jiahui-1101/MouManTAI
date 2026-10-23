> Historical proposal, not execution/acceptance evidence. The proposed dollar cap is not implemented as a provider spending control; listed pricing, automatic teardown and GPU evaluation claims were not independently verified. Do not provision resources from this note. Current status: [PHASE2_CHECKPOINT.md](PHASE2_CHECKPOINT.md).

# P1 BATCH 6 — Stage A: GPU Model Deployment & Evaluation Proposal

**Document Version**: `p1-ai-gpu-v1`  
**Date**: 2026-10-21  
**Scope**: Stage A Preparation without Paid Resources (Pre-Deployment Review)  

---

## 1. Defect Audit of Previous AI Spike

A thorough investigation of the earlier CPU feasibility spike (`REPORT.md` and `diagnose_gliner.py`) identified the following concrete defects, which have now been addressed in the GPU codebase:

1. **GLiNER Tokenization Defect on CJK / Unspaced Languages**:
   - *Previous Defect*: Default `WhitespaceTokenSplitter` assumed space-separated tokens. On Chinese and code-switching messages with no inter-character spaces, word splitting grouped entire sentences or swallowed adjacent products/quantities, causing Chinese recall to collapse to **5.9%** (1/17).
   - *Fix Implemented*: Created `OffsetSplitter` (`backend/app/context/ai/worker.py`) using regex matching CJK ideographs (`[\u3400-\u9fff]`), Latin word clusters (`[A-Za-zÀ-ÖØ-öø-ÿ]+`), numbers, and punctuation. Original Unicode code-point offsets are strictly preserved without injecting artificial spaces.
   - *Threshold & Headroom*: Lowered threshold from `0.5` to `0.35` to improve recall, with explicit input token bounds (<= 300 tokens) to reject overly long inputs rather than allowing internal silent truncation.

2. **Qwen Instruction Hallucination & Evidence Gate Failures**:
   - *Previous Defect*: The small 0.6B CPU model suffered a **31.25% evidence rejection rate** (5/16 cases rejected), hallucinating dates (e.g. producing `tomorrow at 15:00` when the text only stated `tomorrow`), translating Chinese units (e.g. emitting `kg` for `公斤`), or outputting placeholder quotes like `"none"`.
   - *Fix Implemented*: Replaced with a stronger instruction model configuration (`Qwen2.5-7B-Instruct` / `Qwen3-4B-Instruct`). Strengthened `SYSTEM_PROMPT` to mandate verbatim substring copying in the original language, explicitly prohibiting translation, markdown, or date inference.
   - *Grounding & Span Resolution*: Implemented `ground_raw_answer` in `worker.py` to deterministically verify unique quotes in source messages without requiring LLM character arithmetic. Ambiguous or missing quotes trigger strict rejection.
   - *Evidence Gate*: `validate_evidence` validates every `[start, end)` span directly against the immutable raw message text. Mismatches fail fast with `InferenceFailure("evidence_mismatch")`.

---

## 2. Model Selection & Technical Specifications

| Component | Model Identifier | Revision Hash | License | Precision & Runtime | Est. VRAM |
|---|---|---|---|---|---|
| **Specialized Extractor** | `urchade/gliner_multi-v2.1` | `443d26d654e0324125a96bebd8e796c14ff2efe6` | Apache-2.0 | FP16 / FP32, PyTorch with `OffsetSplitter` | ~2.0 GB |
| **Instruction Interpreter** | `Qwen/Qwen2.5-7B-Instruct` | `main` | Apache-2.0 | bfloat16, SDPA attention, Transformers | ~12.5 GB |
| **Secondary Alternative** | `Qwen/Qwen3-4B-Instruct-2507` | `cdbee75f17c01a7cc42f958dc650907174af0554` | Apache-2.0 | bfloat16, SDPA attention, Transformers | ~8.5 GB |

All candidate models use permissive **Apache-2.0** licenses suitable for commercial enterprise deployment.

---

## 3. Dataset Splits & Provenance

To guarantee evaluation integrity, training/development examples are strictly separated from untouched evaluation data:

- **Protocol Version**: `p1-ai-gpu-v1`
- **Total Dataset Size**: 32 hand-labeled cases (54 messages, 86 gold spans, 23 item associations) in `backend/app/context/experiments/ai_gpu/fixtures.json` (content SHA-256 hash verified).
- **Development Split** (8 cases): Historical development evidence used for prompt freezing, tokenizer regression tests, and threshold verification.
- **Held-Out Evaluation Split** (24 cases): Clean, previously unexamined test samples evenly distributed across languages:
  - **English (`en`)**: 6 cases
  - **Chinese (`zh`)**: 6 cases
  - **Malay (`ms`)**: 6 cases
  - **Code-Switching / Mixed (`mixed`)**: 6 cases
- **Covered Complexities**: Multi-item orders (e.g. 10 burgers and 6 boxes of buns), missing fields, conflicting follow-up terms, complex date/time qualifiers, multi-message threads, and prompt injection attempts.

---

## 4. Acceptance Criteria & Pre-GPU Rule Baseline

### Acceptance Targets (`acceptance.json`)
1. **F1 Improvement**: Combined exact span F1 must improve by at least **+5% (+0.05)** over the deterministic rule baseline.
2. **Precision Floor**: Combined precision must remain **>= 95.0%** (no hallucinated entities).
3. **Language Robustness**: No single language F1 may regress by more than **5% (-0.05)**.
4. **Safety & Ungrounded Output**:
   - `unsupported_accepted_source_value_rate_max`: **0.0%** (zero tolerance for ungrounded claims).
   - `invalid_schema_answer_rate_max`: **<= 5.0%**.
   - `evidence_rejected_answer_rate_max`: **<= 10.0%**.
5. **Latency Bounds**:
   - Warm request median: **<= 3.0s**.
   - Warm request p95: **<= 8.0s**.

### Pre-GPU Baseline Measurements (Deterministic Rules on Held-Out Split)
Running `python -m backend.app.context.experiments.ai_gpu.run --split heldout`:

```json
{
  "all_fields": {"precision": 0.941, "recall": 0.727, "f1": 0.821},
  "product":    {"precision": 1.000, "recall": 0.957, "f1": 0.978},
  "quantity":   {"precision": 1.000, "recall": 0.960, "f1": 0.980},
  "unit":       {"precision": 1.000, "recall": 0.360, "f1": 0.529},
  "delivery":   {"precision": 0.692, "recall": 0.600, "f1": 0.643},
  "associations": {"precision": 1.000, "recall": 0.304, "f1": 0.467}
}
```

*Key Bottlenecks for AI to Solve*:
- **Unit Recall (36.0%)**: Rules miss un-prefixed multilingual units (e.g. `盒`, `箱`, `boxes`).
- **Item Associations (30.4%)**: Rules only support single-item pairing; multi-item requests are unassociated.
- **Delivery F1 (64.3%)**: Colloquial date expressions fail rule matching.

---

## 5. Concrete Recommended Deployment Plan

### Architecture: Serverless GPU on RunPod
- **Provider**: RunPod Serverless (`https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync`)
- **Target GPU**: NVIDIA RTX 4090 (24GB VRAM) or NVIDIA L4 (24GB VRAM)
- **Container**: `backend/app/context/ai/Dockerfile` (Ubuntu 22.04 + PyTorch 2.4.0 + CUDA 12.4 + FlashAttention/SDPA)
- **Worker Handler**: `backend/app/context/ai/worker.py` (lazy model initialization, seed 42)

### Cost & Resource Breakdown
| Item | Rate | Usage in Evaluation | Estimated Cost |
|---|---|---|---|
| **Active Execution (RTX 4090)** | $0.000122 / sec ($0.44 / hr) | ~150 seconds compute | ~$0.02 - $0.05 USD |
| **Container Initialization / Cold Start** | $0.000122 / sec | ~180 - 240 seconds | ~$0.03 - $0.05 USD |
| **Idle Worker Charge** | $0.00 | 0 seconds (auto-scales to 0) | $0.00 USD |
| **Ephemeral Disk Storage** | Free with active pod | ~20 GB container image | $0.00 USD |
| **Total Estimated Experiment Cost** | — | — | **~$0.10 - $0.35 USD** |

### Safety Limits & Spending Protections
1. **Hard Client Spending Cap**: `$2.00 USD` maximum budget.
2. **Network Budget**: Hard cap of `max_network_requests = 96`.
3. **Execution Timeout**: Client timeout capped at `125 seconds` per request; total evaluation client runtime capped at `2700 seconds` (45 minutes).
4. **Concurrency**: Hardcoded `max_worker_concurrency = 1` (strictly sequential, no worker pooling).
5. **No Blind Retries**: Automatic POST retries are disabled (`automatic_post_retries = 0`).
6. **Teardown**: Serverless endpoints scale to 0 workers automatically when idle. The endpoint can be stopped or deleted immediately upon evaluation completion.

### Secure Secret Handling
- Credentials are **never** committed to Git or pasted into chat.
- The evaluation runner reads secrets strictly from environment variables:
  - `P1_AI_ENDPOINT_URL` (HTTPS URL)
  - `P1_AI_API_KEY` (Bearer API Token)
  - `P1_AI_ENDPOINT_MODE` (`runpod`)
