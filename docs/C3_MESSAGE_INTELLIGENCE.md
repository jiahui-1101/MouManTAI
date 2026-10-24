# C3 message intelligence

Status: **implemented as an internal, side-effect-free adapter; fixture-validated only.** No provider credentials or live provider calls were used for this change. The API is not mounted and no Backend A–H, P1, P2, Core, Recovery, P4, or persistence contract was changed.

## Current source interfaces reused

`MessageIntelligenceService.analyze()` accepts an already tenant-scoped P1 `StoredMessage`, optional P1 `MessageAssociationRecord`, existing P1 `AttachmentRecord` metadata, and existing `DocumentExtractionResult` values. The adapter validates exact tenant/message/attachment bindings before interpreting any data. Its deterministic pass reuses `request_intent()` and `extract_explicit_fields()` from P1; it does not convert observations into an `OrderRequest`.

P1 attachments currently support PDF and PNG/JPEG image extraction. C3 consumes page-level `DocumentEvidence` from those extraction records and never reads attachment bytes or calls OCR. Plain text is handled from `RawMessageEnvelope.text`; P1 currently does not accept `text/plain` attachment uploads. Unprocessed, partial, failed, unsupported, stale, oversized, or unbound attachment evidence adds a review reason. Attachment snapshots carry the existing file content digest, evidence ref, extraction time, P1 evidence IDs and method versions when the tenant-scoped `AttachmentRecord` and extraction are present.

The returned `AnalysisOutcome` can contain a `CustomerInquiryCandidate` or a `SupplierDelaySignalCandidate`. Both bind to the exact source message, content digest, channel/provider message IDs, timestamp, thread/reply parent, tenant and attachment snapshots. Message citations use exact Unicode code-point spans. Document citations point to existing evidence ID, attachment, page and quote without inventing document offsets. Supplier reference and ETA values have their own source links.

Every candidate is non-authoritative. Supplier identity is `VERIFIED` only when an injected server-side trusted supplier resolver returns a versioned, tenant/channel/sender-bound evidence record; otherwise supplier identity remains unresolved. A verified supplier message still creates only a reported delay candidate requiring human review. The adapter never creates a P2 event, updates a snapshot, writes a review record, creates an order, changes stock, or calls P4 send.

## Deterministic and semantic behavior

P1 request-intent checks and local patterns run first. Recognized price, availability, delivery, and product questions or explicit delay language use exact source evidence. Conflicting topic, request, delivery-reference or ETA signals remain review-required. P1's empty `MISSING` fields do not count as extracted order facts. Explicit order-like language is labeled for the existing order handoff and requires review because C3 does not create an OrderRequest.

When the deterministic pass cannot decide, C3 calls Qwen first. It validates strict JSON against Pydantic schemas, rejects unknown fields and unsupported claims, checks each text span against the exact source segment, checks document citations against the full existing P1 evidence item, and rejects citations that intersect masked sensitive text. A valid model intent or field that contradicts a deterministic result is rejected and causes Gemini fallback. Gemini is tried after Qwen timeout, provider failure, invalid schema/evidence, or contradiction. A final failure or disagreement returns an unknown/review-required result.

Provider prompts contain only ephemeral segment IDs and redacted message/OCR text. Tenant IDs, sender identity IDs, names/aliases, provider message IDs, attachment IDs and recipient/contact metadata are not sent. Common email addresses, phone numbers and long numeric account-like values are masked with offset-preserving replacements. Free-form names and postal addresses are not comprehensively detected, so the owning privacy policy must approve any real external-provider use and limit the source fields allowed. Raw prompts, messages, attachment text, API keys and provider response bodies are never logged by these adapters.

## Provider setup

Qwen requires a Model Studio key, the workspace/region-specific OpenAI-compatible API base URL, and a model ID. Configure:

```text
DASHSCOPE_API_KEY
QWEN_API_BASE_URL
QWEN_MODEL_ID
```

The base URL must be HTTPS, have no embedded credentials/query string, and end at the compatible API version path (for example `/compatible-mode/v1`); the client appends `/chat/completions`. Model Studio uses region-specific endpoints and Qwen's JSON object output is parsed and locally schema-validated. Use the official [Qwen OpenAI-compatible Chat Completions API](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions) and [Qwen structured-output guide](https://help.aliyun.com/en/model-studio/qwen-structured-output) to select an endpoint/model supported by the account's region.

Gemini requires a Google AI API key and selected model ID. Configure:

```text
GEMINI_API_KEY
GEMINI_MODEL_ID
GEMINI_API_BASE_URL       # optional; defaults to https://generativelanguage.googleapis.com/v1beta
```

The client uses the `generateContent` endpoint, sends the API key in the `x-goog-api-key` header, requests JSON/schema output and validates the result locally. Review Google's [GenerateContent API reference](https://ai.google.dev/api/generate-content) and [structured-output guide](https://ai.google.dev/gemini-api/docs/structured-output) for model/schema availability.

Both providers also require an explicit operator-set pricing and per-analysis cap before any request can be made:

```text
C3_AI_MAX_ANALYSIS_COST_USD
QWEN_INPUT_USD_PER_1M_TOKENS
QWEN_OUTPUT_USD_PER_1M_TOKENS
GEMINI_INPUT_USD_PER_1M_TOKENS
GEMINI_OUTPUT_USD_PER_1M_TOKENS
```

Rates must match the selected model and region. C3 does not embed a changing public price table. Missing rate or cap configuration blocks the provider request and returns a review candidate. Each call reserves the full configured input-token ceiling plus output-token cap at those rates; UTF-8 byte size rejects a prompt that cannot fit that ceiling. The per-analysis ledger bounds retries and fallback together. This is process-local budget enforcement, not a durable tenant/day billing ledger.

Optional bounded controls:

```text
C3_AI_TIMEOUT_SECONDS       # default 8; allowed 0.1–20
C3_AI_MAX_RETRIES           # default 1; allowed 0–1 retry per provider
C3_AI_MAX_INPUT_CHARS       # default 4000; allowed 256–4000, no truncation
C3_AI_MAX_SEGMENTS          # default 32; allowed 1–32, no truncation
C3_AI_MAX_INPUT_TOKENS      # default 12000; allowed 256–64000
C3_AI_MAX_OUTPUT_TOKENS     # default 512; allowed 32–2048
```

`MessageIntelligenceService.from_env()` constructs clients only when the corresponding credential, endpoint/model configuration is present. Construction does not make a network call. The standard library HTTP client bounds response size and timeout, rejects redirects, retries only transient failures once, and classifies provider failures without retaining raw response bodies. No retry or transport result is treated as proof that a business action occurred.

Do not store provider credentials in source control or logs. Create credentials in the provider console, scope them to the selected test project/workspace, and inject them through the deployment's secret manager only after the product/security owner approves data handling and a configured test tenant/recipient exists. This C3 work did not use real credentials, create provider projects, send messages, deploy webhooks, or run provider E2E.

## Integration blockers and evidence status

- **Current code:** C3 analysis and candidate contracts are local internal interfaces; fixture and fake-transport tests validate behavior. Tier: `VALIDATED` for unit/contract mechanics only.
- **P1 source reader:** a trusted production adapter must obtain current tenant-scoped `StoredMessage`, `MessageAssociationRecord`, attachment metadata and extraction results. The local P1 routes are provisional and do not prove production authentication or a shared Backend A–H read port.
- **Supplier identity:** no current-main trusted supplier contact registry resolver contract was found. Until the owner supplies it, supplier identity remains unverified and every delay result requires Human Review.
- **Backend A–H:** approve candidate field names/version and the review-task/handoff reader. This branch does not add persistence, APIs, or a queue writer.
- **P2:** its ETA event contract requires authoritative before/after snapshots, exact resource identity, version/freshness checks and transactional deduplication/outbox; the current processor is unavailable. C3 output is not sufficient to call the P2 event route.
- **P4:** current outbound is recovery-scoped and configured to local mock channels. There is no approved inquiry-reply request/consent contract. C3 returns no send request and does not call P4 authorization or send.
- **Real AI evidence:** Qwen/Gemini keys, region/model selection, owner-approved prompt/data policy, provider smoke tests, real timeout/fallback observations, redacted usage/cost receipts and a provider E2E trace remain required. No provider is claimed `LIVE`.
- **Real attachment evidence:** actual PDF/image provider-ingestion-to-P1-extraction-to-C3 review evidence remains required; fixture tests establish only the handoff validation mechanics.
