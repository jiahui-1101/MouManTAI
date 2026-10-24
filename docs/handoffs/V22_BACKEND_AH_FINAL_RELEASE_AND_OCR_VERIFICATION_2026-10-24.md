# MouManTAI v2.2 Backend A–H review, OCR verification, and safe-merge status

**Review date:** 2026-10-24
**Current `main`:** `f6eca1ac93b382c2ffe68965e18b55f12e03d322`
**Release verdict:** **NOT_READY** — the Mock-backed stack is operational on its stacked branches, but it remains unmerged under explicit review holds. No real channel or full Frontend-to-Backend E2E is claimed.

## OCR verdict and root cause

The P1 image acceptance failure is caused by an undeclared runtime dependency. `get_ocr_engine()` imports `paddleocr`, but the Backend package had no OCR extra and the Docker image and general CI installed only `dev`. The configured environment therefore had Pillow and NumPy but not PaddleOCR.

On untouched current `main`, with Python 3.11 and no OCR package installed, the exact test
`app/context/tests/test_batch8_acceptance.py::test_e2e_11_pdf_image_evidence_traceable_payment_unverified`
fails with `FAILED != SUCCESS`. Direct extraction returns:

```text
status=FAILED
diagnostic="OCR engine execution failed: No module named 'paddleocr'"
text=''
evidence_items=0
```

The acceptance traceback ends at the result assertion with `E assert 'FAILED' == 'SUCCESS'`; the captured extractor diagnostic above identifies the import failure. After the dependency fix, that exact test passes with the real model and persisted OCR evidence.

After installing the actual CPU runtime (PaddlePaddle 3.3.1 and PaddleOCR 3.7.0), the same acceptance passes and PaddleOCR recognizes the DuitNow transfer text. This reproduced the issue on the latest `main`, distinguishing it from an OCR parser regression.

The scoped fix adds an optional `ocr` extra for NumPy, Pillow, PyMuPDF, PaddlePaddle and PaddleOCR. The Docker image installs `ocr` plus the existing `optimization` extra for the complete Backend demo. A dedicated `Backend OCR` CI job requires the installed runtime, provisions PostgreSQL, runs the P1 acceptance/image/PDF suites with actual model execution, and fails if a selected test skips.

Runtime-backed regression tests found two additional correctness issues and now cover them:

- PaddleOCR can return whitespace-only entries for a blank image. Extraction now filters those entries before text, payment classification, evidence creation and the zero-lines diagnostic, while keeping original indices for boxes and confidence scores.
- A scanned PDF whose OCR engine raises was previously returned as `SUCCESS` with an error only in the diagnostic. It now returns `FAILED` with empty text, fields and evidence. A deterministic regression test verifies the failure path does not invent evidence.
- The scanned-PDF OCR test now generates an image-backed PDF at test time, so its real OCR execution does not depend on an absent repository fixture.

The fix is on branch `fix/p1-ocr-runtime-dependencies-main-20261024`, based on current `main`, at commit `effa5cf` (OCR code commit). It has not been merged.

## OCR validation

| Check | Result |
|---|---|
| Current-main baseline, no OCR extra: direct extraction | Reproduced `No module named 'paddleocr'` |
| Current-main baseline, exact P1 acceptance, no OCR extra | 1 failed as expected (`FAILED` rather than `SUCCESS`) |
| Current-main baseline with the real OCR runtime, exact P1 acceptance | 1 passed |
| Fix branch on current `main`: exact P1 acceptance | 1 passed |
| Fix branch on current `main`: focused image/PDF checks (including blank image, OCR exception, generated scanned PDF) | 7 passed |
| Fix environment dependency resolution | PaddleOCR 3.7.0, PaddlePaddle 3.3.1, PyMuPDF 1.28.2, Pillow 13.0.0, NumPy 2.3.5; `pip check` found no broken requirements |
| Static checks | Python compile, TOML/YAML parse and `git diff --check` passed |
| Full P1 PostgreSQL run on latest `main` + fix | 24 acceptance, image and PDF cases passed against an isolated PostgreSQL 16 service, with no skips. The CI OCR job runs these plus the Alembic migration file and enforces zero skips. |
| Separate existing Alembic migration case | Exploratory run on the pre-#79 `d3c2a3e` worktree: 25 passed, including the separate clean-chain migration/rollback case, in 971.24s against isolated PostgreSQL 16. This is supplemental evidence, not latest-main validation. |
| Demo Docker image build/runtime | Corrected image built successfully (2.63 GB local image). Runtime imports passed for PaddlePaddle 3.3.1, PaddleOCR 3.7.0, PyMuPDF 1.28.2, Pillow 13.0.0 and OR-Tools 9.15. A real in-image OCR call downloaded its official Paddle models and recognized `DuitNow Transfer Successful RM 88.00`; result `SUCCESS`, payment notice true, 1 evidence item. |
| Exact-head OCR CI on PR #92 (`e978a239`) | GitHub run [40106631992](https://github.com/jiahui-1101/MouManTAI/actions/runs/40106631992), OCR job 120909562078: **25 passed, 0 skipped** including acceptance, image/PDF and migration tests. |
| Exact-head required PR #92 checks (`e978a239`) | All 10 checks succeeded: Backend/PostgreSQL, general Backend, frontend, native Optimization, Forecasting, Decision Memory, Feature Suites, Hygiene, OCR and P1 Source Reader. Run [40106631992](https://github.com/jiahui-1101/MouManTAI/actions/runs/40106631992); separate source-reader run [40106631971](https://github.com/jiahui-1101/MouManTAI/actions/runs/40106631971). |

Known OCR coverage limitation: scanned-page fallback runs only when the PDF has no machine-readable text on any inspected page. A mixed PDF containing both text and scanned pages will not OCR the scanned pages. This was outside the reproduced acceptance failure and remains follow-up work.

OCR is **demo-deployment ready with a first-use limitation**: PaddleOCR downloads its model weights on first OCR use. This was exercised successfully in the Docker image; the demo environment therefore needs outbound access to the configured model source, or a pre-populated model cache. The Dockerfile includes the native runtime libraries required by PaddlePaddle/OpenCV. The OCR extra remains optional for non-OCR installs.

The exact acceptance command was `python -m pytest -q backend/app/context/tests/test_batch8_acceptance.py::test_e2e_11_pdf_image_evidence_traceable_payment_unverified`; it failed on baseline without the OCR extra and passed on the fix branch with the real runtime.

The focused command covered image order/payment/blank handling and machine-readable, scanned fallback and OCR-failure PDFs; it passed **7/7**:

```sh
python -m pytest -q -o addopts= \
  backend/app/context/tests/test_image_ocr.py::test_image_ocr_order_extraction \
  backend/app/context/tests/test_image_ocr.py::test_image_ocr_payment_screenshot_guard \
  backend/app/context/tests/test_image_ocr.py::test_image_ocr_blank_image \
  backend/app/context/tests/test_pdf_extraction.py::test_pdf_machine_readable_order_extraction \
  backend/app/context/tests/test_pdf_extraction.py::test_pdf_scanned_or_empty_detection \
  backend/app/context/tests/test_pdf_extraction.py::test_pdf_ocr_failure_is_failed_without_invented_evidence \
  backend/app/context/tests/test_pdf_extraction.py::test_scanned_purchase_order_pdf_ocr_fallback
```

The latest-main local PostgreSQL run used the P1 acceptance, image OCR and PDF extraction files (24 cases). The dedicated CI workflow runs those files plus `test_p1_alembic_migration.py`, then fails if any selected test skips:

```sh
pytest -v -rs --junitxml=ocr-report.xml \
  backend/app/context/tests/test_batch8_acceptance.py \
  backend/app/context/tests/test_image_ocr.py \
  backend/app/context/tests/test_pdf_extraction.py
```

For that local run, `P1_DATABASE_URL` targeted an isolated PostgreSQL 16 service. CI adds `backend/app/context/tests/test_p1_alembic_migration.py` to the command above.

## Backend A–H review and operational journeys

The six stacked PR heads were inspected with their changed-file lists, individual code paths, exact-head checks, reviews, dependency bases and discussion threads. The review found no new business-authority or cross-tenant access path in the stack. The reviewed code keeps the Orbyte adapter local and synthetic, scopes Mock records by tenant, requires the configured isolated Manager identity/key for the Mock workflow, and leaves production identity/external authority disabled. Human approval remains before high-risk Recovery execution. Supplier selection, forecasting, CP-SAT and Decision Memory are advisory only.

| Journey | Branch-stack status | Evidence and boundary |
|---|---|---|
| Mock Inquiry → OrderRequest → P2 → human review/approval → persistent Mock reservation → accepted Core Commitment | Operational on the stack | Registered FastAPI routes and PostgreSQL tests cover fresh terms/source/resource versions, approval, row-locked reservation, idempotency, stale inputs, unknown/rejected outcomes, audit/outbox and tenant/role denial. All inquiry/resource facts and reservation receipts are **MOCK / DEMO-SYNTHETIC**. No live customer message or Orbyte endpoint is used. |
| Supplier delay → Recovery plan → Human approval → internal execution receipt | Operational as a separate synthetic Recovery workflow | Existing P2/P3 routes and a live Uvicorn/worker/PostgreSQL integration test exercise approval and internal-task evidence. There is no automatic emergency execution or external supplier action, and it is not automatically dispatched from a newly accepted Mock order. |
| Communication request → P4 review → Mock send/receipt → operational status | Operational with the Mock provider | Status verifies the persisted send attempt and audit and labels the result `MOCK_PROVIDER_SENT`. A Mock send does not establish real customer delivery or agreement. |
| Supplier, Forecasting, Optimization and Decision Memory advisory APIs | Operational on the stack | Registered APIs persist controlled synthetic inputs in PostgreSQL and invoke the comparison, forecasting/backtest, native CP-SAT and Decision Memory engines. RFQ stays draft-only; advisory output grants no purchase, acceptance, send, execution or policy-update authority. |

These journeys are connected at registered API/database boundaries but are not one automatic customer-to-delivery chain. P1 channel ingestion is not automatically converted into an OrderRequest, and accepted-order events do not automatically create P3/P4 actions. The existing status report records these workflow boundaries and the Frontend handoff.

## PR inventory and merge disposition

All six PRs are open, non-draft, and GitHub reported them mergeable. Their current heads and dependency bases match the intended chain. Exact-head GitHub Actions runs succeeded:

| PR | Head SHA | Base | Exact-head CI | Review / disposition |
|---:|---|---|---|---|
| #81 | `b0c09a015f17285e5c383c8a314fd6debd50e081` | `main` | Success: runs `40095570438`, `40095588821` | Meishuet approved; no merge authorization. Open. |
| #82 | `040b3d24241d54d993c747fd36380b5474d24268` | #81 | Success: run `40095924770` | Meishuet approved; no merge authorization. Open. |
| #83 | `538cfa1afd825d80250c2b1bcc4b7d2e565bc912` | #82 | Success: run `40096644560` | Meishuet approved; no merge authorization. Open. |
| #84 | `7421bb7887eb2a7076c99fc000c87204ce381000` | #83 | Success: runs `40097344894` and `40097344889` (forecasting) | Meishuet approved; no merge authorization. Open. |
| #85 | `326dbcab1c81dcd9082fac293c4887347180cc4d` | #84 | Success: run `40099878928` | Meishuet approved exact head; no merge authorization. Open. |
| #88 | `d2fa4da975a3d7e939cd1bca2e8f6a0732eec8b6` | #85 | Success: run `40100794324` | Meishuet approved exact head, while explicitly withholding merge authorization pending the P1 release blocker and Jiahui's final Backend review. Open. |

The six PRs have no unresolved inline review threads and no top-level issue comments. Each approval states that code approval is not merge authorization. The required merge sequence was **not run**. The exact approval still needed is explicit authorization from the repository owner/release authority after the P1 fix is reviewed and the final Backend review/branch-protection requirements are satisfied. This release task does not override the reviewers' holds.

The scoped OCR fix is open separately as [PR #92](https://github.com/jiahui-1101/MouManTAI/pull/92), based on `main` at `f6eca1ac93b382c2ffe68965e18b55f12e03d322`. Its exact head `e978a23909428646a6117e0c26897d51647c0712` passed all 10 exact-head checks, including 25/25 OCR/P1/Alembic tests with zero skips. It remains unmerged pending independent review and release authorization.

PR #89 was not modified. Its C1 foundation is already an ancestor of current `main` (merge commit `d3c2a3e`). The separately opened PR #90 is Meishuet's draft C1 persistence/reply-association work; it remains untouched and has no changed-file overlap with this OCR fix. Its owner review asks that it stay Draft while its own CI/review gates are resolved. Open PR #91 changes only `README.md` and has no overlap. The other open draft PR inspected for overlap, #22, changes only `docs/TEAM_LOG.md`.

The latest `main` tip is `f6eca1ac93b382c2ffe68965e18b55f12e03d322`; it advanced after #89 with PR #79. No stack PR has been merged into this tip. Consequently there is no final merged-main Backend/PostgreSQL validation to report, and the six successful branch-head runs do not replace that post-merge gate.

## Frontend and real-channel handoff

**Frontend:** Backend route contracts are documented in the stacked API contract. Frontend typecheck, Vitest and build jobs passed on the exact stacked heads, but the Orders, Review, Recovery, Communication and advisory pages are not wired to these APIs and no browser-to-PostgreSQL cross-module E2E is claimed. The Frontend should call the APIs through a trusted server proxy; the isolated key must not be exposed in `VITE_*`, browser code or local storage.

**Real channels:** The existing P1/P4 Mock transports are integration fixtures only. The separate next phase must implement and verify Telegram Bot API HTTPS webhook, Meta WhatsApp Cloud API official test-number support, bidirectional test Email, provider receipts, replies on the originating channel, attachment extraction, Qwen-first analysis with Gemini fallback, a human-verified contact registry, cross-channel Order association, trusted supplier-delay alerts, Human Review for uncertain evidence/failures, minimal disclosure and sensitive-field redaction. Do not report the Mock provider as a real channel integration.

## Readiness labels

- **Mock-backed Backend A–H implementation:** operational on the reviewed PR stack; **not released to `main`**.
- **P1 OCR:** root cause fixed; real CPU execution verified in local and Docker runtimes; exact-head GitHub OCR/PostgreSQL CI passed 25/25 with zero skips. Independent PR review and release authorization remain required.
- **Actual Telegram/WhatsApp/Email communication:** **not ready / separate phase**.
- **Full Frontend + Backend system:** **not ready**; API wiring and browser E2E remain.
- **Overall release:** **NOT_READY** until the OCR PR is reviewed, the explicit merge authorization is supplied, the stack merges in dependency order, and final-main Backend/PostgreSQL/Frontend validation passes.
