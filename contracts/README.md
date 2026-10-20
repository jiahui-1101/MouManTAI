# MouManTAI shared contracts

The shared contract boundary is intentionally small during Phase 0:

- `backend/app/core/schemas.py` is the runtime Pydantic validation source.
- `contracts/types.ts` is the synchronized TypeScript type source used by the frontend.
- `contracts/fixtures/demo_dataset.json` is the one synthetic cross-feature fixture.

All IDs are strings, timestamps are offset-aware ISO 8601 values, and quantities/costs
are decimal strings on the JSON wire. Feature owners must extend these contracts through
an additive, reviewed change recorded in `docs/TEAM_LOG.md`.

## Phase 0 contract audit

1. The system example used `BusinessContext.status = READY`, while P1's owner contract
   uses `INFORMATION_READY`. The canonical value is `INFORMATION_READY`; the backend
   accepts the old `READY` input as a compatibility alias and normalizes it.
2. The system document names `Confirmation` but does not provide a complete JSON shape.
   Phase 0 defines the minimum versioned, identity-bound shape required by P4.
3. Approval and execution states were described across P3/P4 rather than frozen in one
   list. Phase 0 freezes only the states required by the existing lifecycle language;
   it does not add a new business capability.
