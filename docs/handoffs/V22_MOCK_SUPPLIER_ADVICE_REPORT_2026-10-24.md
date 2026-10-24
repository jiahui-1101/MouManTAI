# v2.2 Mock supplier advisory follow-up

Stacked on PR #82 and PR #81. This branch registers `/v1/backend-v2/mock-suppliers` for controlled synthetic supplier datasets, actual hard-spec and normalized unit-cost comparison, one durable human quote choice and an unsent RFQ draft. The pure comparator remains the decision engine; request bodies cannot assert a comparison status. An approved category spec, requirement and each quote must be tenant-bound, current and carry `synthetic://` refs. The Manager identity and tenant are server-bound to the isolated demo environment. Production routes remain disabled.

Migration 0019 persists datasets, selections and audit, with uniqueness for one selection per dataset and per idempotency key. A selection locks its dataset, checks exact versions and fresh facts, reruns the comparison and rejects an incompatible or unknown quote. The selection and outbox event commit together. Responses label `MOCK` and `DEMO-ONLY`, and explicitly deny purchasing or sending authority. These records do not represent supplier assent, real stock or an executed purchase.

The new PostgreSQL HTTP tests cover source seed, comparison of matching and incompatible quotes, normalized cost, persisted selection, replay, audit/outbox, RFQ draft, stale versions, missing quote, foreign evidence, expired source, tenant/role denial and production disablement. The wider v2.2 gate and branch CI should be used before merging.

Outstanding full A–H work: accepted-order outbox is not yet consumed into P3/P4; supplier selection does not purchase. Forecasting, optimization and decision-memory APIs still need source-backed registration. Frontend pages need a trusted server proxy and API wiring.
