# Orders & Planning integration — 24 October 2026

## Stage 0 verified baseline

Runtime checkout: `codex/order-detail-workspace`, clean at `85ad272`.
Remote main fetched to `f8e147d`; development copy merges that baseline at `c625097`.
PR #76 Orders work and the existing Detail redesign are retained. No main development/push.
`/health` and `/v1/overview`: 200; overview exposes five commitments, not five accepted requests.
`/v1/contexts/by-order/ord_hero_001`: 404.
Read-only SQL against container `moumantai-uat-db-1`, bound only to 127.0.0.1:5434:
database `moumantai_demo`, Alembic `0017_p1_real_channel_provenance`, five exact
order/commitment links, four stocks, three proposals, zero operational snapshots,
zero reservations. Public tables inspected; Core, P2, Recovery, Communication tables exist.
No database/schema changes or seed/reset execution.

## Field authority and missing behavior

All synthetic requests come from `app/orders/fixtures/orders_demo_v1.json`.
The explicit tenant is `tenant_demo_01`; actor scope is checked server-side by demo reads.

| Frontend field | Authority / endpoint | Provenance / availability | Missing behavior |
|---|---|---|---|
| Order ID, customer display, items, received time, requested deadline, channel | shared synthetic request / `/v1/demo/orders` | versioned DEMO-ONLY fixture; not imported customer messages | reject malformed source |
| Lifecycle status | no authoritative OrderRequest transition | UNKNOWN | never derive Accepted/Completed from Core |
| Commitment link | fixture link, matched against tenant-scoped Core on detail | seed_demo.py mappings verified in DB | show warning if absent; reject mismatched link |
| Order value / profit | no approved customer price or complete costs | unavailable | Unknown; staff financial information redacted |
| Feasibility | existing `/v1/commitments/:id/assessments` | exact persisted P2 evidence only; not Core feasibility label | unverifiable/missing; no recalculation |
| Inventory / BOM / capacity / expiry | existing P2 snapshot authority | no persisted snapshot in current Demo | unavailable; stock is not BOM/ATP |
| Agreement / fulfilment | Core commitment read, separate dimensions | synthetic Core only | no acceptance or delivery inference |
| Reservations | explicit reservation evidence only | none in Demo | not verified |
| Calendar | shared request deadlines | REQUESTED / TENTATIVE; no production schedule | resource/conflict coverage Unknown |
| Portfolio | P2 common constraints + joint evaluator receipt | no registered production optimization API/approved adapter | unavailable; never invent optimizer |

## Ownership / reuse mapping

Reuse Core auth context, DB session, tenant-scoped Commitment, existing P1 read/history UI,
P2 assessment-history reader, and the shared frontend HTTP client. Add only isolated
demo read DTOs/source and fixture; no table added/extended/deprecated. Existing
`contracts/fixtures/demo_dataset.json` uses `ord_001` rather than the current seed's
`ord_hero_001`; do not mutate this historical P1/P2 scenario or silently join those IDs.
The new request fixture records synthetic request facts independently; copied SKU/quantity
and delivery dates are demo authoring choices aligned to the observed five Core rows,
not evidence that Core terms were an original customer request. Received timestamps and
customer labels are explicitly newly authored synthetic facts. All lifecycle states Unknown.

Core/P1/P2/P3 business rules and ingestion remain unchanged. The additive main router
registration is the only shared application wiring change and needs Core review on handoff.
Do not run `seed_demo.py`, `reset_and_seed_test_db.py`, or the new upstream P2 seed:
the latter requires BURGER terms incompatible with these five demo variants.

Portfolio formal integration is BLOCKED on P2/H owner confirmation of a registered,
authorized common ConstraintSpec + joint validation receipt and complete revenue/cost,
lot-expiry and resource sources. Pure optimization modules are not a production read API.
P1 owner: approve durable shared request ingestion/linkage before Inbox can read fixture requests.
Other Views are not modified; Dashboard/Recovery already read the linked Core IDs;
Suppliers has no verified request-read integration. Fixture evidence is SYNTHETIC only.
