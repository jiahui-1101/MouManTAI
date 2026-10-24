# C3 message intelligence implementation plan

## Scope

Add a side-effect-free C3 analysis boundary in `backend/app/message_intelligence/`. Reuse the existing P1 deterministic intent/extraction, `StoredMessage`, identity association, and attachment extraction contracts. Provide evidence-linked customer-inquiry and supplier-delay candidates; call Qwen first and Gemini once as bounded fallback when Qwen fails, times out, or returns invalid/conflicting output. No database, route, OCR, P2/P4 write, canonical order, Core, Recovery, or shared A–H contract changes.

## Planned files

- `backend/app/message_intelligence/__init__.py`
- `backend/app/message_intelligence/contracts.py` — strict source, claim, candidate, provider-status and review contracts.
- `backend/app/message_intelligence/deterministic.py` — deterministic-first classification and source projection; reuse P1 `request_intent` and existing extraction entry points where compatible.
- `backend/app/message_intelligence/privacy.py` — offset-preserving sensitive-text redaction and payload minimization.
- `backend/app/message_intelligence/providers.py` — bounded Qwen/Gemini HTTP clients, error classification, retries, and explicit configured budgets; no logging of payloads/secrets.
- `backend/app/message_intelligence/service.py` — tenant/identity/source-evidence validation, provider fallback, contradiction handling, fail-closed candidate assembly.
- `backend/tests/test_message_intelligence.py` — realistic provider/source fixtures, contract tests, fallback, evidence, privacy, identity, tenant, attachment, and failure tests.
- `docs/reports/C3_EARLY_BACKEND_AH_CONTRACT_HANDOFF.md` — already created; update with final implemented scope and evidence.
- `docs/C3_MESSAGE_INTELLIGENCE.md` — provider setup, environment variables, test-only/live evidence limits and integration blockers.

## Sequence

1. Add failing contract tests for strict schema, evidence spans, source/tenant/identity checks, deterministic cases, provider fallback and no-authority behavior.
2. Implement P1 adapter/source validation and deterministic classification.
3. Implement privacy projection and provider clients with bounded timeout, retries, tokens/cost budgets, and redacted errors.
4. Implement Qwen-first orchestration, Gemini fallback, validation/contradiction review, and candidate contracts.
5. Add fixture-based provider transport tests and integration handoff documentation.
6. Run focused C3 tests, targeted existing P1 safety regressions, lint/type validation available in repo, and review the full diff for excluded files.
7. Fetch latest `origin/main`, rebase/merge without rewriting remote history, create a Draft PR, and request review only from `jiahui-1101`.

## Validation targets

- No provider network traffic or live send in tests.
- Every candidate links back to same-tenant source message and source evidence; invalid or missing evidence routes to Human Review.
- Qwen is preferred; timeout, provider failure, schema failure, invalid spans, and deterministic conflict permit Gemini fallback; invalid/failing Gemini becomes review-required.
- Supplier statements remain reported claims even when sender identity is verified. No P2 mutation or P4 send call is made.
- Existing P1/P4/P2 contracts and tests remain unchanged.
