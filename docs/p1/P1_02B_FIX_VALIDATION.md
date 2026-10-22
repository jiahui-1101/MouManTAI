# P1 TASK 2B-FIX — Extraction Safety Validation

2026-10-21 (Asia/Singapore). Branch: `feat/p1-context-intelligence`, baseline: `772bb1e`, initial worktree clean.
Reviewed commits: `7c6ab30`, `243fab1`, `9a83e3b`, `772bb1e`. Requirements read from canonical paths: root `AGENTS.md`, `docs/REQUIREMENTS_SYSTEM.md`, `docs/requirements/PERSON_1_CONTEXT_REQUIREMENTS.md`, and recent `docs/TEAM_LOG.md`.
This task only modified P1 pure extraction rules, local envelope defaults, tests, and documentation. No Core schemas, database infrastructure, or model integrations modified.

## Fixes and Reproducible Evidence

Fixed baseline: `received_at=2026-10-20T02:00:00Z`, explicit `Asia/Kuala_Lumpur`; DST samples explicitly specify `America/New_York` with fixed dates.

| Input / Scenario | Measured Pre-Fix | Measured Post-Fix |
|---|---|---|
| `Deliver tomorrow after 3pm` | VALID / EXACT / 2026-10-21 15:00 | UNRESOLVED / null, preserving lower-bound semantics |
| `tomorrow at 3pm; ...2026-10-24 at 4pm` | Silently chose first item | UNRESOLVED, preserving conflicting source quotes |
| `Deliver tomorrow; call at 3pm` | Date and time merged across sentences | UNRESOLVED |
| Envelope omits `business_timezone` | Auto-defaulted to `Asia/Kuala_Lumpur` | None; relative/local delivery dates UNRESOLVED |
| `Oct 24` (with or without timezone) | Implicitly used source year or 2026 | UNRESOLVED, quote preserved; never fabricates year |
| `2026-03-08 02:30`, New York | VALID -05:00 (nonexistent wall clock) | UNRESOLVED (nonexistent DST gap) |
| `2026-11-01 01:30`, New York | VALID -04:00 (arbitrary fold selected) | UNRESOLVED (ambiguous DST fold) |
| Sent Oct 20 with tomorrow, received Oct 21, `message_at` present | Computed relative to `received_at` (Oct 22) | Computed relative to `message_at` (Oct 21) with provenance |
| Same request received with delay on Oct 23 | Recomputed to new future date | UNRESOLVED; metadata preserves Oct 21 candidate, no date roll |
| `25:00`, `3:99pm`, `15:000`, seconds field, `3pmx` | Partially parsed as valid time or fell back to DATE_ONLY | INVALID, no truncation of illegal suffix |
| `3:30pm`; full Chinese YYYY-MM-DD | Multiple overlapping regex tokens | Single token; claims full expression before validation |
| `maybe at 3pm`, `around`, `between`, `not before`, explicit text tz | Partially mislabeled EXACT | UNRESOLVED; unsupported qualifiers not projected to enum |
| Past date / past time today | VALID | UNRESOLVED; preserves `candidate_delivery_value` |
| `before 2026-10-24` | DATE_ONLY discarded qualifier relation | DATE_ONLY string, `metadata.date_relation=DEADLINE`; no midnight |
| Same alias mapping to multiple SKUs or units | SKU candidate marked VALID | SKU and associated quantity UNRESOLVED |

Each group added a failing regression test before fixing. Safety tests total 77 assertions.

## Explicit Policies and Scope

- Rule version: `p1-deterministic-v3`. Original text and `StoredMessage` remain immutable; all fields use original `message_id`, `RULE/version`, original quote, and `[start,end)` Unicode code-point offsets.
- **Timezone**: No trusted tenant default in this module. Omitted or null timezone provides no parsing context. Explicit value records `timezone_source=message.business_timezone` (declared source only).
- **Relative Date**: `message_at_else_received_at_v1` prioritizes persisted `message_at`, falling back to `received_at`; never reads execution clock.
- **Year**: Full dates must be unambiguous. No "nearest this/next year" guessing. Incomplete dates remain UNRESOLVED.
- **DST**: Evaluates fold 0/1 round-trip via UTC per Python ZoneInfo specification; rejects gap and fold without guessing.
- **Past Date**: Evaluated relative to fixed `received_at`. Past requests remain unconfirmed observations.
- **Expressions**: Multiple independent date/time expressions never pick first. Cross-sentence date/time does not merge.
- **Units**: Normalization strictly respects SKU compatibility; incompatible units mark INVALID without guessing.
- VALID indicates local rule validation passed; never implies identity verification, commitment confirmation, or READY status.

## Core Contract Alignment

Checked `backend/app/core/schemas.py`.
Probe observations with `BusinessContext.model_validate`: DATE_ONLY `2026-10-24` rejected; offset-aware datetime accepted; `status=READY` normalizes to INFORMATION_READY; PARTIAL rejected; AMBIGUOUS identity rejected; extra qualifier field rejected.

| Local Dimension | Current Core Contract | Alignment Requirement |
|---|---|---|
| DATE_ONLY | `requested_delivery_at` accepts offset-aware datetime or null | Dates preserved without midnight fabrication |
| EXACT / DEADLINE | Core uses `deadline` without range/qualifier | EXACT cannot be silently treated as deadline |
| Readiness | `INFORMATION_READY`, `INFORMATION_PARTIAL`, `CONFLICT`, `UNRESOLVED` | Unverified contexts do not enter Core |
| Identity | `UNVERIFIED`, `LINK_CANDIDATE`, `LINK_VERIFIED`, `CONFLICT` | AMBIGUOUS must be resolved before publication |
| Empty Item Partial | `requested_items` requires at least one item | No fake items fabricated to pass validation |
