# C3 verified ingress reuse map — 25 October 2026

Status: implementation mapping for this branch; no new business authority.

| Entity / boundary | Decision | Reason |
|---|---|---|
| `p1_dev.inbound_messages` | Reuse | Canonical tenant, provider account, native ID, immutable payload and digest remain P1 owned. |
| `outbox_events` / `processed_events` | Extend by event type | One `p1.message_verified` event is written in the P1 ingest transaction and consumed by the existing retrying worker. No second inbox or event ledger. |
| `c3_message_reviews` | Reuse | Existing source-bound pending review and human decision aggregate. |
| `c3_classification_results` | Add | Durable result for every analyzed source, including no-review deterministic results. It records the full typed outcome and optional review ID. It grants no Orders, P2, P3 or P4 authority. |
| Context / OrderRequest / commitment / outbound tables | No change | Classification and review decisions do not create business commitments or send messages. |

The event binds tenant, canonical message ID, provider account/native ID and content digest. The worker re-reads P1 under that tenant and verifies current source before analysis. A failure rolls back the result and review; existing outbox retry/dead-letter policy applies. An inference request interrupted before its database commit can be retried, so provider call counts are not an exactly-once claim.
