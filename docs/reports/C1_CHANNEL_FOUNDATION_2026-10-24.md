# C1 Channel Foundation — audit and execution plan
Date: 2026-10-24 (Asia/Kuala_Lumpur). Implementer: meishuet16. Reviewer: jiahui-1101 only.
Status: C1 PARTIAL; shared contract proposal AWAITING JIAHUI APPROVAL.

## Verified baseline before edits
- Fetched origin/main: 177461223d2b91950de88d33fdba484affdfc735.
- Original checkout: main at f8e147d, clean; preserved without switching/resetting/stashing.
- Isolated managed worktree: branch codex/c1-channel-foundation from fetched Main.
- Open overlap PRs at audit: #81 durable Mock orders, #82 Recovery/communication evidence,
  #83 suppliers, #84 forecasting, #85 CP-SAT; #79 Human Review frontend; #22 historical docs.
  No commits from these branches are copied or modified.
- Python 3.14; pytest 9.1.1, Ruff 0.17.2, psycopg 3.3.4, Pydantic 2.13.4,
  SQLAlchemy 2.0.51, httpx 0.28.1 installed. Docker available.
- Existing migration head: 0017_p1_real_channel_provenance. No schema edits authorized here.
- Baseline channel tests: 29 passed, one Starlette/httpx deprecation warning.
- Root v2.2 requirements govern; docs/REQUIREMENTS_SYSTEM.md explicitly labels itself LEGACY v1.
  Supplied Real Channel requirements are source requirements, not integration evidence.

## Phase 0 gap matrix
| Concern | Existing implementation and gap | C1 disposition |
|---|---|---|
| Provider IDs | Telegram tg_chat_message; WhatsApp wamid; Gmail gmail_id | Reuse formats; pure parser preserves native IDs separately |
| Raw persistence | p1_dev.inbound_messages.raw JSONB stores normalized envelope, not full callback | Reuse canonical repository; raw callback retention policy needs review |
| Tenant/channel | Server-config tenant; unique tenant/channel/provider_message_id | Account scope absent; shared change blocked |
| Immutable sender | Telegram numeric from.id, WA from, Email From | Missing sender can become placeholder; Email From is asserted, not authenticated contact |
| Thread | Telegram chat_id; Gmail threadId/RFC fallback; WA absent | Pure helper separates conversation and exact parent |
| Exact parent | RawMessageEnvelope field exists but adapters do not fill it | Pure parsing only; production wiring blocked by unsafe downstream fallback |
| Attachments | Existing validation, hashed byte storage, opaque evidence refs | Native source IDs discarded; failures logged/skipped; review gate still missing |
| Duplicate | PostgreSQL unique insert/immutable fingerprint; duplicate skips extraction | Reuse; random attachment IDs/retrieval timing can conflict on redelivery |
| Out of order | Unresolved string can be stored; no durable pending-parent reconciliation | Pure resolution can be rerun; durable reconciliation blocked |
| Authenticity | WA HMAC present; Telegram secret only checked if configured; Gmail OAuth | Helpers fail closed; existing route changes require review |
| Contact roles | SyntheticCustomerDirectory exact sender binding; aliases/models not authority | No production Contact Registry or supplier verification in C1 |
| Audit/events | Extraction attempts, associations, context versions/reviews; Core/P4 outbox exists | No canonical raw-ingest event/reconciliation ledger; proposal blocked |
| Real evidence | Mock SDK tests and REAL adapter labels exist | No actual provider callback/reply evidence established; NOT LIVE-VERIFIED |

## Entity-level reuse/extend/add/deprecate mapping
| Existing entity / owner | Decision | Proposed change, not executed |
|---|---|---|
| p1_dev.inbound_messages / P1 | REUSE + proposed EXTEND | Add account/native IDs and framing provenance to existing raw contract; scoped unique key transition |
| extraction_attempts / P1 | REUSE | Keep immutable source/attempt history |
| message_associations / P1 | REUSE | Keep verified contact/order decisions distinct from native reply framing |
| order_contexts / P1 | REUSE | No automatic rewrite of reviewed contexts |
| order_context_versions, context_reviews / P1 | REUSE | Explicit versioned changes only |
| attachments, document_extractions / P1 | REUSE + proposed EXTEND | Native attachment ID binding and failure/review state |
| Core commitments, audit_events, outbox_events / P5 | REUSE | No lifecycle/approval changes or new parallel outbox |
| communication_outbound_messages, communication_send_attempts and confirmation records / P4 | REUSE | Later exact outbound parent correlation only via reviewed contract |
| New source_messages / notifications / incidents tables | DO NOT ADD | Existing authorities remain canonical |

Table names above are verified from source/metadata; actual disposable database inventory is recorded in validation.
No shared/staging/production database inspected or migrated.

## Shared-contract gate — STOPPED for Jiahui approval
Existing get_contexts_by_thread_or_reply scans latest 50 tenant messages, lacks channel/account
parameters, and falls back from missing exact parent to same-thread matches. ContextService
can then try sender/partial-message heuristics. Simply filling reply_to_provider_message_id
would expose these semantics, so production activation is deliberately withheld.

Minimal proposed compatible extension:
1. Extend existing RawMessageEnvelope with optional versioned account/native ID, RFC headers,
   native attachment references and transport provenance; old records remain unknown.
2. Extend canonical lookup with explicit tenant/provider/account/channel/conversation key;
   unknown/ambiguous parent never falls back to thread/sender. Pending reference remains
   unresolved until a scoped unique parent exists. Never auto-edit reviewed Order Contexts.
3. Review additive migration/backfill/index/unique-key strategy after verifying current
   record counts/account ownership. Do not guess an account for historical records.
4. Reuse canonical transaction/outbox for first ingest and reconciliation dedup. Existing
   content conflicts remain conflicts; receipt timestamps are not immutable message content.
5. Frontend receives additive unknown/unresolved framing states only after synchronized DTO
   review. Backend A source readers must tolerate historical unknown provenance and keep
   exact term/assent checks. P4 authorization and outbound authority remain unchanged.

Why reuse alone is insufficient: envelope has only one opaque parent string and no account,
native/RFC identifier namespace, provenance or reconciliation state; repository lookup cannot
express the required scope. No canonical P1/P5 model, API, migration or P4 interface changed.
Owner decision requested only from jiahui-1101; no approval inferred from this task.

## Narrow design and executable plan
Use an internal, side-effect-free channels/reply_framing.py helper, not a shared API DTO,
repository or alternative message store. Frozen frames preserve tenant/provider/account,
native sender/message/conversation IDs, exact parent and attachment source IDs.
Email preserves RFC Message-ID/In-Reply-To/References separately from Gmail native IDs.
References-only does not prove exact parent. Native quoted framing is not contact identity,
delivery, order acceptance, customer assent or consent.

- [x] Audit actual code, routes, migration graph, tests and overlap before editing.
- [x] Write deterministic helper tests; observe missing-module RED.
- [x] Implement minimal parser, signature checks and strict scoped reference resolution.
- [x] Run focused tests and existing channel/context/v2.2 regressions.
- [x] Use a dedicated disposable PostgreSQL container for unchanged persistence tests and
  inventory; never run migrations against shared databases.
- [x] Run Ruff/format/compile/diff checks and record exact results.
- [ ] Review, commit focused slices, verify HEAD, normal push, Draft Backend PR to Main;
  request only jiahui-1101. Keep Draft until owner review and integration gates.

Alternative approaches rejected for this C1: changing canonical persistence now violates the
handoff gate; adding another durable inbox would duplicate authority. Local pure helpers
permit useful tested progress while the concrete shared proposal awaits review.

## Scope / requirements / authority
CH-04 ingestion framing, CH-05 no inferred roles, CH-06 scoped links, COM-02 reply evidence;
BE-MSG-01 and v2.2 immutable evidence/tenant boundaries. No C2/C3 Contact Registry, AI fallback,
outbound sending, business engine, real Orbyte, credentials or real customer data.
Integration modes: deterministic SYNTHETIC fixtures; unchanged Mock Orbyte.
No helper output grants CUSTOMER/SUPPLIER role, assent, acceptance, purchasing or emergency approval.

## Provider references checked
- [Telegram Message and webhook contracts](https://core.telegram.org/bots/api#message)
- [Gmail immutable native ID versus thread](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages)
- [RFC 5322 reply identification](https://www.rfc-editor.org/rfc/rfc5322#section-3.6.4)
- Meta documentation URL was inaccessible through web tooling; context.id matches the supplied
  requirements and existing fixture payload convention, and remains unverified against live Meta.

## Delivered files and compatibility
- backend/app/context/channels/reply_framing.py: internal frozen observations, separate
  native/RFC namespaces, exact-only scoped resolver, conservative attachment source parsing,
  explicit signature helpers. No repository, network or business side effects.
- backend/app/context/tests/test_reply_framing.py: 48 synthetic deterministic cases.
- backend/app/context/tests/test_c1_repository_regression.py: six PostgreSQL cases proving
  existing canonical immutability, late-parent retention, duplicate and conflict behavior,
  tenant/channel scope and absence of ingest-only contexts/outbox effects.
- .github/workflows/c1-channel-foundation.yml: independent Python 3.11/PostgreSQL 16 job
  for the new helpers and existing canonical channel/persistence/migration regressions.
- This report: verified Phase 0 mapping, minimal blocked shared proposal and actual evidence.

API/contract impact: none on registered routes, canonical DTOs, repository methods, P4 or
Frontend. No new tables, migrations, dependency declarations or adapter activation.
Internal parser output is not a contact, consent, business or provider-delivery attestation.
Malformed/unsupported framing raises FramingError; orchestration must eventually persist
the original evidence and route the error to review, not discard it. That wiring is blocked.
Attachment IDs here are source references only, not evidence that bytes were fetched/verified.

## Validation evidence
All commands below run from backend unless stated otherwise. Python 3.14 local runtime.
Offline environment for test invocations:
```powershell
$env:TELEGRAM_AUTO_START='false'
$env:GMAIL_AUTO_START='false'
$env:P1_AI_ENABLED='false'
$env:MOUMANTAI_SYNTHETIC_MODE='1'
```
- PASSED baseline:
  `python -m pytest app/context/tests/test_telegram_channel.py app/context/tests/test_whatsapp_channel.py app/context/tests/test_gmail_channel.py app/context/tests/test_channel_manager_and_routes.py -o addopts= -q --tb=short --basetemp=.pytest-c1-baseline2`
  -> 29 passed, one existing warning.
- RED then GREEN: helper import initially failed with ModuleNotFoundError; review-driven
  malformed-object/header tests failed six cases then passed; unnamed Gmail attachment
  regression failed on lost native ID then passed after correction.
- PASSED final scoped:
  `python -m pytest app/context/tests/test_reply_framing.py app/context/tests/test_telegram_channel.py app/context/tests/test_whatsapp_channel.py app/context/tests/test_gmail_channel.py app/context/tests/test_channel_manager_and_routes.py -o addopts= -q --tb=short --basetemp=.pytest-c1-reviewed-scoped`
  -> 77 passed, one existing warning (48 helper + 29 existing channel tests).
- PASSED v2.2:
  `python -m pytest tests/v2_2 -o addopts= -q --tb=short --basetemp=.pytest-c1-v22`
  -> 493 passed, five existing deprecation warnings. Portable suite, not PostgreSQL proof.
- FAILED broad portable context:
  `python -m pytest app/context/tests -o addopts= -q --tb=short --basetemp=.pytest-c1-context`
  -> 521 passed, 147 skipped, one failed. This earlier run predates six new PG cases
  and nine final helper cases. Failure:
  test_batch8_acceptance.py::test_e2e_11_pdf_image_evidence_traceable_payment_unverified.
  Reproduced independently in untouched original checkout at f8e147d using that exact node
  and --basetemp pointing to this task's .pytest-c1-original-ocr directory.
  PaddleOCR package is unavailable (`python -m pip show paddleocr`); existing extraction
  returns FAILED when OCR cannot execute. No test removed or changed to mask it.

Disposable PostgreSQL:
- Created dedicated container moumantai-c1-pg-20261024, ID
  15d68f8d2b1fd3884abbdc97ec36500e5db449a42f9ce20a9ee470d761ceebe2,
  verified 127.0.0.1:15473 -> 5432, database moumantai_c1_test. Existing application DB
  on 5433 untouched. Only this new disposable container uses trust authentication.
- Test-only fsync disabled after slow Windows Docker DDL; these runs prove logical SQL
  behavior, not crash/power-loss durability.
- Set `P1_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:15473/moumantai_c1_test`.
- PASSED:
  `python -m pytest app/context/tests/test_c1_repository_regression.py app/context/tests/test_postgres_repository.py app/context/tests/test_p1_alembic_migration.py app/context/tests/test_order_context_source_snapshot.py app/context/tests/test_order_context_storage.py app/context/tests/test_association_models_and_storage.py -o addopts= -q --tb=short --basetemp=.pytest-c1-pg`
  -> 40 passed, zero skipped, seven existing warnings.
- PASSED `DATABASE_URL=<same disposable URL> python -m alembic upgrade head`;
  `python -m alembic heads` and SQL alembic_version confirm sole 0017 head.
  Actual p1_dev tables: attachments, context_reviews, document_extractions,
  extraction_attempts, inbound_messages, message_associations, order_context_versions,
  order_contexts. Existing migration regression creates its own disposable child DB and
  tests owned downgrade/reupgrade; no migration files changed.
- FAILED broad PostgreSQL-backed context:
  `python -m pytest app/context/tests -o addopts= -q --tb=short --basetemp=.pytest-c1-context-pg`
  -> 675 passed, seven skipped, one failed, seven warnings in 209.90s.
  Same pre-existing OCR acceptance failure; no other failures. This run started before
  the final unnamed-attachment regression/fix; final 77-test scoped run covers that fix.
  Optional/live checks remained skipped; this is not a zero-skip full-suite result.

Static checks:
- PASSED `python -m ruff check app/context/channels/reply_framing.py app/context/tests/test_reply_framing.py app/context/tests/test_c1_repository_regression.py`.
- PASSED `python -m ruff format --check` with the same three paths.
- PASSED `python -m compileall -q` with the same three paths.
- PASSED `git diff --check`; final staged check recorded before commit.
- Read-only code review identified the unnamed Gmail attachment gap; reproduced and fixed.
  No further material scoped findings. Local Python minimum-version execution NOT_RUN;
  added CI uses Python 3.11. CI result is separate from local evidence.

## Integration status and follow-up
- IMPLEMENTED AND TESTED: internal C1 parsing/resolution/signature helpers; existing
  canonical repository guarantees covered on disposable PostgreSQL.
- PARTIAL: Phase 1 durable account-scoped framing, pending-parent reconciliation,
  attachment-failure review, canonical ingest/outbox integration; blocked shared proposal
  requires jiahui-1101 approval. Existing production Telegram secret-optional behavior and
  thread fallback are audited gaps, not repaired by unwired helpers.
- IMPLEMENTED BUT NOT LIVE-VERIFIED: existing provider adapter code; this task establishes
  no provider configuration/readiness proof. No callbacks/API calls or real sends executed.
- NOT IMPLEMENTED in C1: C2/C3 Contact Registry, AI provider fallback, full attachment
  retrieval/review, business journey wiring, outbound transport/receipt correlation.
- BLOCKED BY PROVIDER SETUP / verification: per-channel real E2E requires authorized
  accounts, callback/auth setup, test identities, mailbox/sender configuration and receipts.
  No credentials were created, copied, exposed or used.
- No REAL_CHANNEL_VERIFIED claim. All new fixtures are SYNTHETIC; Mock Orbyte unchanged.
- Human SME acceptance/reservation, exact customer assent, P4 sends and emergency
  approval/execution retain existing owners and guards. No helper grants any authority.
- Next: Jiahui reviews the concrete shared proposal; after approval, finish C1 canonical
  account-scoped persistence/lookup before moving to assigned C2 verified contact/evidence
  work. C3 outbound/reply receipt integration remains separate.
- Latest observed Main at pre-push fetch: 6b1f0c8cd127992d7b7eceadea10ac16297d45c1.
  Difference from C1 base 1774612 is README-only PR #86; no backend drift was imported.
- Affected owner: meishuet16 for C1; integration review exclusively jiahui-1101.
  Draft status must remain until owner review, migration safety and PostgreSQL gates.
