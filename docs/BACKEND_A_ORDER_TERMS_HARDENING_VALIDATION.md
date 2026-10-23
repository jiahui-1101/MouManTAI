# Backend A OrderTerms Foundation Hardening — Validation Record

Date: 2026-10-24 (Asia/Kuala_Lumpur)

## Scope and refs

- Branch: `backend-a/fix-order-terms-foundation-hardening`.
- Base: PR #48 branch `codex/feat-v2-2-backend`, head `741976d3cdd59352d66a30c5712ce9eca5d3bc16`.
- Code HEAD at validation: `941b81716fbbcba558b253afcc5cf840f71a0fae`.
- Latest fetched Main: `67627cb782a02c7e47bd0812d861f55ff8bb5982`.
- Current PR #48/#49/#50 heads at verification: `741976d3cdd59352d66a30c5712ce9eca5d3bc16` / `62040da02b4ec3532ea02d734567e0913996ec2b` / `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`; each open Draft and unmerged. PR #50 is based on #48.
- Code files: `backend/app/orders/terms.py`, `backend/tests/v2_2/test_terms.py`. No mapper, AcceptanceCandidate, schema, migration, API, P2, reservation or Core lifecycle change.

## Findings and behavior

1. **Evidence currentness and disclosure** — commercial hash equality does not validate evidence. Evidence refs remain outside the v1 commercial hash for compatibility and provenance correction. `OrderTerms` is pure and cannot check persisted tenant/customer binding, freshness, revocation or disclosure. A trusted server adapter and independent consumer reread are required. No assent is synthesized. Provenance correction is allowed only after that trusted evidence boundary verifies same binding terms.
2. **Terms revision** — `require_exact_terms()` rejects a proposed revision that differs from the authoritative original revision on the unchanged-original-offer path (`STALE_TERMS_VERSION`). Revision equality is not assent. An intentional amended offer requires separately reviewed proposal/version/customer-assent behavior.
3. **Timezone/offset** — offset-aware non-UTC local values must match the named IANA timezone. An explicit valid offset disambiguates a repeated DST hour; wrong offsets, a fold with no disambiguating offset and nonexistent wall times fail closed. Explicit UTC instants are accepted. Equivalent instants serialize/hash identically and window ordering uses UTC instants. `order-terms-v1` inputs are unchanged.

## Executed validation

| Command / setup | Result |
|---|---|
| Focused new failing tests on clean PR #48 base before fix | RED: 4 regression failures reproduced (revision mismatch; Kuala Lumpur wrong offset; wrong repeated-hour offset; nonexistent local time). |
| `python -m pytest tests/v2_2/test_terms.py -o addopts= -q --tb=short` | 44 passed after fix. |
| `python -m pytest tests/v2_2 -o addopts= -q --tb=short` | 122 passed, 5 warnings. |
| Selected P1/Core command: `python -m pytest app/context/tests/test_order_context_storage.py app/context/tests/test_association_models_and_storage.py app/context/tests/test_context_api.py app/context/tests/test_review_readiness.py app/context/tests/test_core_publisher.py app/context/tests/test_p2_consumer.py tests/test_core_api.py tests/test_core_assessment_writer_provenance.py -o addopts= -q --tb=short` | 21 passed, 22 PostgreSQL-gated skipped, 5 warnings. |
| Full portable backend `tests` suite with `REQUIRE_POSTGRES=0`, database URL vars unset and task-local `--basetemp` | 514 passed, 31 PostgreSQL-gated skipped, 12 warnings. No shared/development database used. |
| PR #50 compatibility overlay: at actual PR #50 HEAD `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`, overlaid the foundation `terms.py`, retained PR #50 tests, then ran `python -m pytest tests/v2_2 -o addopts= -q --tb=short` | 176 passed, 5 warnings. Scratch worktree was restored clean and archived after the run. |
| `python -m ruff check --select E,F,I --ignore E501 app/orders/terms.py tests/v2_2/test_terms.py` | Passed. |
| `python -m compileall -q app/orders/terms.py` | Passed. |
| `git diff --check` (code change) | Passed. |
| `ruff format --check app/orders/terms.py tests/v2_2/test_terms.py` | Not clean due legacy whole-file formatting in these pre-existing files; no unrelated reformat applied. |
| PostgreSQL-specific validation | NOT_RUN: no approved disposable PostgreSQL URL was configured. |

## Compatibility and unresolved trust boundary

The PR #50 mapper remained compatible in the overlay run. No PR #50 code was changed by this branch. Its candidate readiness remains preparation only. Trusted disclosure/currentness validation requires server-side persisted reads and an approved freshness policy; a pure `OrderTerms` hash cannot establish disclosure, identity or customer assent.

The A-side proposal is `docs/BACKEND_A_B_INTEGRATION_CONTRACT.md` on PR #50. `BACKEND_AB_CONTRACT_HANDOFF.md` was not present in the actual fetched PR #48 or PR #50 trees, so the B-side comparison is NOT_RUN pending delivery of that document. Do not infer Backend B's proposed fields or lifecycle.

## Review / release gates

- Required: PR #48 P5/P1 review of the foundation semantics and timestamp compatibility, and Backend B review of the candidate/re-read boundary.
- S1–S5 remain unratified; no product policy or customer assent semantics were ratified here.
- No persistence, acceptance, P2 evaluation, SME approval, reservation, Core transition, outbound communication or production operation is implemented/enabled.
- This is a separate foundation hardening change based on PR #48, not a duplicate P1 mapper/AcceptanceCandidate PR.
## Publication checkpoint

- Final branch HEAD: `9f25d6c7e3edf1bfdbdc2b377fbcba5e4412cf6b` (`941b817` code/tests plus `9f25d6c` docs).
- Draft PR #52: https://github.com/jiahui-1101/MouManTAI/pull/52, based on open Draft PR #48 branch at `741976d3cdd59352d66a30c5712ce9eca5d3bc16`. P1 `mavisbong41` and P5 `Gan0117` requested. PR #52 is open, Draft, unmerged and mergeable; no CI statuses were returned at this check.
- PR #48/#49/#50/#52 all remain open Draft/unmerged at heads `741976d3...` / `62040da0...` / `fd7be2e2...` / `9f25d6c7...`. Latest fetched Main: `67627cb782a02c7e47bd0812d861f55ff8bb5982`.
