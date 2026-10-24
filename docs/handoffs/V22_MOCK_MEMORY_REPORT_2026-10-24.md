# v2.2 Mock Decision Memory follow-up

Stacked on PR #85. The registered `/v1/backend-v2/mock-memory` routes persist controlled DEMO historical decisions, source manifest and test-only retrieval policy, then call the existing Backend G validation, case assembly, retrieval, outcome summary and human-review proposal logic. Source snapshots, cases and current context are tenant-bound and explicitly synthetic. The adapter authenticates only the isolated synthetic principal and checks exact persisted facts; it does not attest real historical outcomes.

Migration 0022 stores immutable datasets and separate audit, with an outbox record on seed. The insights POST is read-only; it carries structured current context and does not change policy or operational state. Responses say `DEMO-ONLY`, `operational_action_authorized=false`, and `policy_update_authorized=false`. Synthetic verified outcomes describe fixture semantics and make no real business-performance claim.

PostgreSQL HTTP tests exercise three synthetic historical cases, one eligible verified fixture outcome, retrieval, outcome counts, review proposal, replay, persistence, incomplete/foreign source rejection, unverified current context, tenant/role denial, production disablement and OpenAPI registration. The existing Backend G pure tests remain the detailed evidence/chronology regression gate.
