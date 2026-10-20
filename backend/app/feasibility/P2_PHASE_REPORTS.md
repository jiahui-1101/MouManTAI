# P2 Phase Review Reports

## Phase 0 — Inspect + Contract Trace

- **State:** PARTIAL (Phase 0 artifacts are prepared; P5-owned contract decisions remain open.)
- **Date:** 2026-10-21
- **Branch:** `feat/p2-feasibility-engine`
- **Commit SHA:** see phase response.
- **Initial Git state:** clean `main` at `aedb152`, matching `origin/main`; new P2 branch created from that commit. No unrelated edits were present.
- **Dirty status at report preparation:** expected changes are this report, progress, trace and P2-only team-log rows; final post-commit status will be recorded in the phase response.

### Inspection findings

- The designated clone at `D:\dunno\0.SDC\MouManTAI` was the Git root. `origin` is `https://github.com/jiahui-1101/MouManTAI.git`; local/remote branch inventory contained only `main`/`origin/main` before creating the requested branch.
- Actual tracked project files before this phase were `README.md`, `docs/AGENTS.md`, `docs/REQUIREMENTS_SYSTEM.md`, and `docs/TEAM_LOG.md`. There is no backend/frontend skeleton, P2 module, shared `contracts/`, or test suite. No assumption was made that the skeleton exists.
- The actual local P2 requirements file and P1/P3/P5 owner requirements were read from the authorized parent workspace. They remain outside the Git repository and were not copied or modified.
- The P2 reference copy in Appendix A was normalized for its closing separator and compared line-by-line with the actual local P2 file; they match. The trace follows the actual local source.
- `docs/REQUIREMENTS_SYSTEM.md` supplies the canonical assessment base shape, the pure internal route, event envelope, lifecycle invariants, and P2→P3/P5 handshake. P3 explicitly requires reuse of `POST /internal/feasibility/evaluate` or the same pure library. P5 owns contracts, authentication, shared database, outbox, and authoritative state transitions. No P5 implementation is present to finalize additive fields or public route wiring.

### Changes and trace evidence

- Created `backend/app/feasibility/P2_REQUIREMENT_TRACE.md` with individual P2 requirement rows, applicable shared-system requirements, implementation/test paths, truthful status, and explicit P3/P5 ownership/blockers.
- Created `backend/app/feasibility/P2_PROGRESS.md` with the branch/repo baseline, gated phase board, provisional pure evaluator and event contract, P3 handoff example, synthetic scenario, and exact open decisions.
- Appended this Phase 0 checkpoint to `backend/app/feasibility/P2_PHASE_REPORTS.md`.
- Updated only the P2 rows in `docs/TEAM_LOG.md`; P1/P3/P4/P5 entries and shared decision history were left untouched.
- The provisional scenario uses the shared example `BURGER` SKU: `com_001` needs 100 patties by `09:00`, with 60 unreserved on hand and 40 confirmed inbound originally due `08:00`; `com_002` has 20 units reserved from the 80 on-hand, and needs them the following day. Moving the delivery ETA to `11:00` makes the expected `com_001` shortage 40 while `com_002` remains buffered. A separate 100+40 demand / 30 on-hand / 110 inbound fixture is proposed for two affected commitments. These are hand-calculated fixture expectations only; no evaluator exists and no runtime output was observed.

### Validation and tests

- **Tests:** NOT RUN, as explicitly required for Phase 0. No test command was invoked.
- **Inspection commands:** `git status --porcelain=v1`, `git remote -v`, `git branch --list`, `git branch -r`, `git log --oneline --decorate -n 12`, `git rev-parse --show-toplevel`, `rg --files -g '!\.git'`. Observed a clean initial tree, the stated Git root/remote, and only the four documentation/project files listed above.
- **Runtime/API/UI behavior:** NOT RUN / NOT IMPLEMENTED. The input/output and fixture examples in the report are contract proposals, not observed results.

### Trace status and remaining deficiencies

- Phase 0 inspection/contract mapping is recorded. Runtime acceptance criteria remain `NOT_STARTED` or `BLOCKED` in the trace; no P2 implementation criterion is marked PASS from documentation alone.
- P5 must confirm OperationalSnapshot and assessment extensions, tenant/auth/API integration, storage/outbox/events, canonical fixture types, and Core state update operations. P1/P5 must confirm SKU/BOM/units and normalized context inputs. P3 must confirm proposed-change serialization and import usage. P3/P5 own command-side reservations and concurrency proof.
- Highest-risk assumptions: the temporary shared example SKU can become the approved synthetic fixture; the hand-calculated 40-unit shortage depends on the reservation being counted exactly once and the material-use deadlines being adopted; the P2 additions to shared assessment/event payloads are not yet ratified.
- **Next phase:** Phase 1 operational snapshots and synthetic fixtures, only after the user returns `APPROVED — CONTINUE P2` following external review.
