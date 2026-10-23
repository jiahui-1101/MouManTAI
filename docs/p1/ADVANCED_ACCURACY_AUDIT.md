# Workstreams 4–5 checkpoint — 2026-10-22

Branch `feat/p1-phase2-refinement`. Only extraction accuracy and saved historical semantics were changed. No migration/auth/Core contract/Review Drawer edits, ingestion rescan, historical mutation, Qwen inference, GPU startup, dependency/model install, push/merge/PR.

## Workstream 4 — DONE for this bounded optimization; recall targets partly missed

Implementation `4e5ba29` (`p1-deterministic-v5`, normalization `catalog_and_l0_subspan_v3`):

- Longest approved compound alias wins over contained short aliases across SKUs (`roti burger` vs `roti`; `bun burger` vs `burger`). Equal-span conflicting catalog meanings and separate products remain distinct/unresolved. No new catalog products or benchmark aliases added.
- GLiNER observations now use whole approved product mentions/optional literal quantity-unit prefixes, rather than arbitrary substring-to-SKU mapping. Quantity candidates cannot select the first number from guest counts, competing quantities or unknown product phrases. Original observation and normalized subspan are preserved, candidates remain untrusted.
- Literal Malay meridiem before `pukul/jam`, Chinese hour numerals and English noon normalize from original evidence. Missing timezone, DST, multiple expressions, unsupported bounds and source-clock guards remain intact; no guessed time/year/unit.
- Completed-delivery feedback and explicit cancellation cannot become VALID requested quantity/delivery. A singleton explicit amendment target can be extracted even with `instead`; competing old/new numbers remain unresolved, and no amendment is a confirmed commitment.
- Multi-item mentions are preserved; generic per-item quantity reconciliation remains unresolved where association is not explicit. No model confidence is treated as calibrated or authoritative.

Focused regression command (private test DB loaded, models disabled):

```powershell
.venv/Scripts/python.exe -m pytest backend/app/context/tests/test_multilingual_semantic_fixes.py backend/app/context/tests/test_deterministic_extraction.py backend/app/context/tests/test_conversational_rules.py backend/app/context/tests/test_delivery_expression_safety.py backend/app/context/tests/test_request_intent_safety.py backend/app/context/tests/test_ai_routing_and_costs.py backend/app/context/tests/test_model_candidate_safety.py backend/app/context/tests/test_qwen_phase1.py backend/app/context/tests/test_ai_pipeline_integration.py backend/app/context/tests/test_publication_safety.py -o addopts='' -q -ra --tb=short
```

**205 passed, 0 failed/skipped, 4.62s**, including PostgreSQL and mocked L2 safety (no actual Qwen call). `.local/advanced-focused.txt`. Updated an old routing fixture to assert zero calls now that its Malay clock is supported. Benchmark labels/scoring were not changed.

One final full 40-case run used the existing direct GLiNER worker after these tests. One health check, then **12 adapter requests / 12 validated responses**, 28 cases avoided inference. No exploratory per-example calls, no second benchmark, no weight/model change. Wrapper recorded raw requests/responses separately without changing the scorer.

| Metric | Baseline | After | Desired | Result |
|---|---:|---:|---:|---|
| Product F1 | 87.9% | 94.3% | ≥92% | met |
| Product recall | 78.4% | 89.2% (33/37) | ≥90% | missed |
| Quantity F1 | 90.6% | 94.5% | ≥93% | met |
| Quantity recall | 82.8% | 89.7% (26/29) | ≥90% | missed |
| Delivery F1 | 96.6% | 100% | ≥97% | met, entity metric only |
| Unit F1 | 100% | 100% | ≥98% | met |
| Malay case pass | 60% | 90% (9/10) | ≥80% | met |
| Overall case pass | 72.5% (29/40)* | 90% (36/40) | ≥90% | met |
| SKU false accept | 0 | 0 | 0 | retained on measured set |

*Baseline overall derived from saved language pass counts, not a previously established business-level metric. All four languages now pass 9/10. Known expected SKU cases: 33 correct, 0 missed; 7 unknown/non-order SKU cases rejected. Field precision is 100% in this small benchmark. These are the unchanged runner's combined **L0 plus provisional L1 entity** metrics, not GLiNER-only accuracy, normalized timestamp F1 or final BusinessContext correctness. No universal correctness/false-accept guarantee.

Remaining failures (4 cases / 7 field failures): pizzas, 云吞面, nasi lemak, curry puff are outside the approved benchmark catalog. Raw GLiNER misses product on pizzas and quantity on 云吞面/nasi lemak; it recognizes the other unknown product spans but catalog validation correctly rejects SKU membership. **Case-level regression:** pizza quantity was formerly accepted by stripping `10` from `10 pizzas`; strict source/domain normalization now refuses it, adding one quantity FN. Three other quantity misses improved, so net recall rises. Do not fix this by inventing products, dropping hard cases or weakening validation. Desired recall thresholds remain unmet; no further tuning run attempted.

Observed remote reports `urchade/gliner_multi-v2.1@443d26d654e0324125a96bebd8e796c14ff2efe6`, device CPU, `p1-colab-standalone-v1`, torch `2.11.0+cpu`, GLiNER `0.2.29`. Reports are not independent checkpoint/hardware attestation. Mean reported inference for the 12 responses 0.5847s; request wall mean 2.0166s. Runner mean 0.607s includes skipped cases, so is not CPU inference latency. No provider cost/billing claim.

Evidence (ignored local files): `.local/phase2-l1-benchmark.json` baseline; `.local/advanced-final-benchmark.json`, `.local/advanced-final-model-responses.json`, `.local/advanced-final-benchmark.log` final. Fixture SHA-256 `3d36ab09e36a11a42465fc96685d9b9ecae84c0e5dfeb01bded9e57b2918c457`; scorer SHA-256 `933975f251a19b74fc93d2231c9a1089d65ebbb2c5c4804abda542039808aac7`. Git diff confirms neither fixture nor scorer changed from `2cc41d6`. Dataset is now development/retrospective evidence, not fresh held-out validation.

## Workstream 5 — PARTIAL: all records classified, full semantic proof unavailable

Commit `3c4ac2d`: reusable offline verifier and 36 retrospective original-text annotations, covering all **177 saved records** without any database query. Duplicate text shares literal annotations, but every message's original quote spans, timestamps/timezone, stored fields and associated context snapshot are checked separately. Snapshot SHA-256 `22c046f519c78894b4aab785ae81e845776e8b0ea7ddd65740f4cb9018acf39d` is enforced to prevent silently transferring verdicts to changed data.

| Status | Count |
|---|---:|
| VERIFIED_CORRECT | 30 |
| VERIFIED_INCORRECT | 13 |
| AMBIGUOUS | 26 |
| INSUFFICIENT_EVIDENCE | 108 |
| NOT_REVIEWED | 0 |
| Total source/evidence records reviewed | 177 |

Only **43** have conclusive literal-field verdicts; **134** remain uncertain. Correct means supported saved literal extraction with no unverified context in the supplied snapshot; it does not mean independently verified customer intent, identity, agreement, fulfilment, or complete end-to-end BusinessContext accuracy. Assistant-assisted annotations alone are not independent human gold: conclusive findings require executable exact-source, numeric, explicit-time and catalog checks. Pragmatic intent, quotation attribution and undocumented corrections remain ambiguous/insufficient.

Confirmed historical defects: 2 equivalent-SKU false conflicts; 2 rejected explicit quantities; 5 omitted explicit clock expressions recorded as DATE_ONLY; 5 literal-delivery normalization omissions. Categories overlap on one record, giving **13 records**, not 14. The new Chinese/Malay clock fixes address 9 historical records' patterns; prior audited comma/normalization fixes address the retained legacy defects. Historical stored results were **not** corrected or reprocessed.

Representative records:

- `f2d5210e-9ecd-412d-8708-82920138d71b`, `98b806f2-a690-40e6-8d44-830189113793`: raw number + burgers model SKU caused a false conflict with the same canonical rule SKU (previous fix retained).
- `942c78f4-b7d6-4f84-850c-b81998b90568`: comma blocked quantity 40 (previous fix retained); missing timezone/future receipt must still remain unresolved.
- Text group 24 (5 records): explicit `后天下午三点` stored as DATE_ONLY, losing 15:00; new literal-hour parser tested on independent quantities/expressions.
- Text group 35 (4 records): `esok petang pukul 3` delivery marked INVALID; new Malay prefix clock parser fixes the general pattern.
- Guest counts / alternative quantities / unknown pastry / vague next week / standalone quoted request are uncertain, not automatically orders.

For 108 insufficient records the saved artifact lacks extraction or complete context delivery/evidence/review events/thread lineage. Examples include context quantity 35 after raw 20, and context 60 after raw 50: without the specific human review and superseding-message history, these are **not declared errors** and human values are not overwritten. The snapshot contains version IDs/counts but not the complete review rationale. Future completion should fetch only the missing version/review/lineage details for flagged context IDs if authorized/available; do not repeat ingestion scanning or auto-publish corrections. No new P5 handoff is requested.

```powershell
.venv/Scripts/python.exe -m pytest backend/app/context/tests/test_historical_semantic_verification.py -o addopts='' -q --tb=short
# 7 passed, 0 failed/skipped, 0.32s
.venv/Scripts/python.exe -m app.context.experiments.verify_historical_semantics --snapshot .local/phase2-historical-after.json --output .local/advanced-historical-semantics-final.json
# Already executed; refuses overwrite. Read existing evidence instead of rerunning.
```

Full per-message verdict, original text, expected literal facts, accepted stored values/evidence and context IDs: `.local/advanced-historical-semantics-final.json`. The initial scratch report is superseded by this final file. Script: `backend/app/context/experiments/verify_historical_semantics.py`; annotations: `historical_semantic_labels.json`. Additional tests prevent wrong numeric normalization, false SKU, missing spans, incorrect date-only precision, unsupported human-change conclusions and snapshot reuse. No model semantic judgement is used as automatic truth.

Stop these workstreams here. Do not repeat the final benchmark, claim 177/177 correctness, change historical data, start L2 Phase 2, or proceed automatically into migration/tenant/auth/delivery integration/Review Drawer work.
