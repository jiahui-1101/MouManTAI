# P1 Qwen primary and Gemini fallback

## Reuse and extension audit

| Existing P1 component | Current behavior | Change |
| --- | --- | --- |
| `deterministic_extraction.py` | L0 deterministic parsing and catalog checks | Kept first; a sufficient L0 result still skips model calls |
| `ai/endpoint.py` and `ai/protocol.py` | Qwen/GLiNER HTTP adapter, strict schema and source spans | Added safe error categories and provider identity metadata; Qwen remains primary |
| `ai/service.py` | Existing P1 proposal pipeline, tenant-scoped cache and candidate review | Added provider-chain telemetry and bounded total timeout; candidates still pass existing domain and review gates |
| `document_extractor.py` | Existing OCR/document parsing | Kept deterministic; no separate document-model pipeline was introduced |
| `postgres_repository.py` / `context_service.py` | Existing extraction attempts and Human Review contexts | Uses bounded `extraction_attempts.diagnostic`; provider failure creates an explicit conflict for review |
| `ai/worker.py` | Existing Qwen extraction instructions | Instructions are shared with Gemini so both stages receive the same extraction policy |

The adapter receives only the existing P1 message payload (`engine` and the bounded source messages). It does not receive tenant IDs, sender identity, attachment bytes, or unrelated conversation history. The existing tenant-scoped cache key remains in force.

## Configuration

Qwen must be configured and enabled before Gemini can be used. Gemini never becomes the primary provider.

| Variable | Default / accepted range | Purpose |
| --- | --- | --- |
| `P1_AI_ENDPOINT_URL` | Required to configure Qwen | Existing Qwen endpoint URL |
| `P1_AI_API_KEY` | Required to configure Qwen | Existing Qwen credential |
| `P1_AI_ENDPOINT_MODE` | `runpod` | Existing Qwen transport mode |
| `P1_AI_TIMEOUT_SECONDS` | `125`, up to 180 | Qwen request timeout |
| `P1_AI_ENABLED` | Must be truthy for model calls | Existing P1 opt-in switch |
| `P1_AI_STAGES` | Defaults to `gliner`; use `qwen` to enable the Qwen stage | Existing stage selection |
| `P1_GEMINI_API_KEY` | Unset disables fallback | Gemini API credential |
| `P1_GEMINI_MODEL` | `gemini-3.8-flash` | Gemini structured-output model |
| `P1_GEMINI_TIMEOUT_SECONDS` | `20`, range 0.1–60 | Timeout for each Gemini attempt |
| `P1_GEMINI_MAX_RETRIES` | `1`, range 0–2 | Retries for Gemini 429, 5xx and transport failures |

Qwen POST requests are not retried because a client timeout does not prove that a submitted paid job stopped. Gemini retries are bounded to at most three total attempts. There is no retry after Gemini schema, JSON or evidence validation failure. Provider keys are sent in authorization headers and are excluded from config representations and diagnostics. Error strings are restricted to fixed categories; unknown text is reduced to `provider_internal_error`.

## Data handling and failure behavior

Before either external provider call, a shared same-length masking pass replaces recognized email addresses, phone numbers, order/account/transaction references, long card-like numbers, postal codes, common street addresses, labeled names, greeting names and company names with `*`. Same-length masking preserves Unicode code-point offsets. Evidence that overlaps masked text is rejected; evidence outside masked spans is restored to the exact original source slice and checked again by the P1 span validator.

Redaction uses bounded patterns, not a named-entity detector, so it cannot guarantee recognition of every person, address, or commercial identifier. Do not treat it as permission to send unrestricted source data. The message itself remains the minimum current-message input required for extraction. Raw Gemini response content is discarded, provider error bodies are not stored, and diagnostics contain fixed error categories, timings, counts and validation results only.

Gemini is called only after a technical Qwen failure such as timeout, rate limit, service error, invalid JSON or schema-invalid output. A valid empty Qwen answer is an answer and does not trigger fallback. Missing or mismatched evidence, evidence overlapping redacted text, and other grounding failures fail closed and require review without another model call. Ambiguity or lack of an explicit source fact is not resolved by fallback.

If Qwen fails and Gemini credentials are absent, or if both providers fail, the existing deterministic fields remain available and the extraction attempt stores `review_required` with reason code `MODEL_PROVIDER_FAILURE`. `ContextService` exposes this through the existing `CONFLICT`/Human Review flow. Model-derived fields remain provisional proposals; this layer does not assert payment, acceptance, availability, supplier agreement, or commitment and does not write to P2, Recovery, or P4.

## Verification

Provider regression tests use `httpx.MockTransport`; ordinary test runs do not need live credentials. The live Gemini smoke test is skipped unless both `P1_RUN_REAL_GEMINI_SMOKE=1` and `P1_GEMINI_API_KEY` are configured. The test uses only the synthetic message `Hello`. No live provider call is implied by mocked-test success.

The Gemini REST request uses the official `generateContent` endpoint and JSON structured output configuration. See Google's [Generate content API reference](https://ai.google.dev/api/generate-content) and [structured output guide](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).

## Remaining integration limits

- P1 document OCR remains deterministic; Gemini fallback is currently attached to the existing message-inference stage only.
- Provider redaction is heuristic and needs review before use with data requiring guaranteed PII removal.
- No genuine Qwen or Gemini call has been performed as part of ordinary CI; only the opt-in Gemini smoke test can verify a live credential and model deployment.
- Exact-head CI and fresh owner review are still needed on the published branch. Do not merge until the parallel release contracts stabilize and the required reviewers authorize the exact tested head.
