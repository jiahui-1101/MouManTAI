# MouManTAI — Feature Freeze Regression & Quantitative Metrics Report

> **Generated At**: `2026-10-21 16:36:41 UTC`  
> **Git Reference**: `commit d078f21`  
> **Environment**: `Windows 11 (AMD64)` | `Python 3.14.7`  
> **Specification**: `REQUIREMENTS_SYSTEM.md §7` ("Quantitative Metrics") & `PERSON_5 §8`  
> **Integrity Guardrail**: Measured numbers only from reproducible synthetic benchmark harness. No fabricated production metrics.

---

## 1. Executive Metrics Dashboard

| Metric Category | Target | Measured Result | Status |
|---|---|---|---|
| **E2E Acceptance Scenarios (E2E-01 – E2E-12)** | `100% (12/12)` | **100.0% (12/12)** | **PASSED** |
| **Audit & Outbox Atomic Completeness** | `100.0%` | **100.0% (13/13 transitions)** | **PASSED** |
| **Unauthorized & Stale Action Block Rate** | `100.0%` | **100.0% (7/7 blocked)** | **PASSED** |
| **Unauthorized State Mutations Permitted** | `0` | **0** | **PASSED** |
| **False Fulfilment / False Confirmation Rate** | `0.0%` | **0.0% (0/4)** | **PASSED** |
| **Median Core Command Processing Latency** | `< 25.0 ms` | **5.35 ms (ingest) / 6.09 ms (confirm)** | **PASSED** |

---

## 2. Acceptance Matrix Scenarios (`E2E-01` to `E2E-12`)

| ID | Scenario Description | Invariant & Authority Ground Truth | Duration (ms) | Result |
|---|---|---|---|---|
| `E2E-01` | Customer requests 100 units; verified constraints allow | Request context populated -> Feasibility check -> Proposal offered -> Signed confirmation | `44.6` | **PASSED** |
| `E2E-02` | Supplier ETA delay recomputes affected commitments | Supplier delivery delayed -> P2 recalculates -> flags com_001 INFEASIBLE/AT_RISK while com_002 stays NORMAL | `44.6` | **PASSED** |
| `E2E-03` | Recovery comparison & manager approval required | Two recovery plans compared from same snapshot; Staff rejected (403); Manager approves plan_a | `44.6` | **PASSED** |
| `E2E-04` | Stale approval / stock changed (Snapshot Drift) | Manager approves snapshot 142; stock changes to 143; execution blocked (409 Conflict); no unauthorized mutation | `24.32` | **PASSED** |
| `E2E-05` | Ambiguous customer 'OK' reply requires clarification | Customer replies with vague 'OK'; flagged CLARIFICATION_REQUIRED, never auto-confirmed | `12.94` | **PASSED** |
| `E2E-06` | Stale proposal version confirmation rejected | Confirmation arrives for proposal v1 after v2 exists; blocked (409 Conflict); preserves v2 | `42.44` | **PASSED** |
| `E2E-07` | Message sent without reply (Delivery Tracking Only) | Message status updates to SENT/DELIVERED; confirmation remains AWAITING_RESPONSE; fulfilment stays NOT_STARTED | `5.05` | **PASSED** |
| `E2E-08` | Duplicate webhook / action retry idempotency | Webhook retried with identical event_id; exactly 1 state transition, 1 reservation, and 1 audit record created | `6.72` | **PASSED** |
| `E2E-09` | Unverified receipt screenshot uploaded | Customer uploads bank receipt screenshot; evidence recorded, agreement stays REQUESTED, flagged for manual review | `3.97` | **PASSED** |
| `E2E-10` | Worker crash recovery without duplicate execution | Worker crashes after external API call succeeds; consumer reconciles idempotency key without duplicate action | `6.18` | **PASSED** |
| `E2E-11` | Cross-tenant isolation enforcement | Tenant B attempts to access, assess, confirm, or view audit of Tenant A's commitment; strictly denied (404/403) | `44.07` | **PASSED** |
| `E2E-12` | Operational fulfilment verified (Signed POD Proof) | Operational courier delivery confirmed with signed POD; transitions to FULFILLED and RESOLVED; premature receipt rejected (422) | `44.6` | **PASSED** |

---

## 3. Security, Role & Stale State Guards

| Probe Name | Expected Status | Observed Status | State Mutation Guard | Result |
|---|---|---|---|---|
| Staff role attempting recovery execution (HTTP 403) | `HTTP 403` | `HTTP 403` | Zero Mutation (Blocked) | **PASSED** |
| Staff role attempting fulfilment recording (HTTP 403) | `HTTP 403` | `HTTP 403` | Zero Mutation (Blocked) | **PASSED** |
| Cross-tenant commitment read isolation (HTTP 404) | `HTTP 404` | `HTTP 404` | Zero Mutation (Blocked) | **PASSED** |
| Cross-tenant mutation isolation (HTTP 404) | `HTTP 404` | `HTTP 404` | Zero Mutation (Blocked) | **PASSED** |
| Stale snapshot_version recovery execution (HTTP 409) | `HTTP 409` | `HTTP 409` | Zero Mutation (Blocked) | **PASSED** |
| Optimistic concurrency version conflict (HTTP 409) | `HTTP 409` | `HTTP 409` | Zero Mutation (Blocked) | **PASSED** |
| Unrestricted lifecycle PATCH prohibition (HTTP 405) | `HTTP 405` | `HTTP 405` | Zero Mutation (Blocked) | **PASSED** |

---

## 4. Invariant Verification: False Fulfilment & Confirmation Guardrails

| Invariant Checked | Negative Scenario Tested | Outcome | Result |
|---|---|---|---|
| `SENT != ACCEPTED != FULFILLED` | MESSAGE_SENT / DELIVERED does not confirm or fulfil commitment (E2E-07) | False Transition Prevented | **PASSED** |
| `SENT != ACCEPTED != FULFILLED` | Vague customer 'OK' does not auto-confirm commitment (E2E-05) | False Transition Prevented | **PASSED** |
| `SENT != ACCEPTED != FULFILLED` | Unverified OCR payment receipt rejected from fulfilment (HTTP 422) | False Transition Prevented | **PASSED** |
| `SENT != ACCEPTED != FULFILLED` | Inbound OCR receipt keeps commitment REQUESTED without auto-fulfil (E2E-09) | False Transition Prevented | **PASSED** |

---

## 5. Core Command Processing Latencies (Local Wall-Clock Benchmark)

*Sample size: `N = 15` repetitions per lifecycle command in local SQLite test environment.*

| Lifecycle Command | Endpoint / Operation | p50 (Median) | p95 | Min | Max | Mean |
|---|---|---|---|---|---|---|
| **Context Ingest** | `POST /v1/integration/context-updated` | `5.35 ms` | `15.32 ms` | `4.92 ms` | `15.32 ms` | `6.2 ms` |
| **Feasibility Assess** | `CommitmentService.assess` | `1.15 ms` | `1.72 ms` | `1.06 ms` | `1.72 ms` | `1.18 ms` |
| **Proposal Offer** | `POST /v1/commitments/{id}/proposals` | `6.02 ms` | `8.04 ms` | `5.8 ms` | `8.04 ms` | `6.21 ms` |
| **Proposal Confirm** | `POST /v1/commitments/{id}/confirm-proposal` | `6.09 ms` | `16.44 ms` | `5.63 ms` | `16.44 ms` | `7.58 ms` |
| **Recovery Start** | `POST /v1/commitments/{id}/recovery/start` | `5.71 ms` | `6.53 ms` | `5.35 ms` | `6.53 ms` | `5.8 ms` |
| **Recovery Execute** | `POST /v1/commitments/{id}/recovery/execute` | `6.62 ms` | `7.59 ms` | `6.41 ms` | `7.59 ms` | `6.75 ms` |
| **Fulfilment Record** | `POST /v1/commitments/{id}/record-fulfilment` | `5.61 ms` | `6.45 ms` | `5.43 ms` | `6.45 ms` | `5.72 ms` |
| **Overview Query** | `GET /v1/overview` | `5.7 ms` | `7.77 ms` | `5.34 ms` | `7.77 ms` | `5.86 ms` |
| **Timeline Query** | `GET /v1/commitments/{id}/timeline` | `5.09 ms` | `7.53 ms` | `4.96 ms` | `7.53 ms` | `5.3 ms` |

---

## 6. Audit & Outbox Completeness Detail

- **Total Recorded Audit Events**: `14`
- **Total Published Outbox Records**: `14`
- **State Transitions Evaluated**: `13`
- **Atomically Paired Transitions**: `13`
- **Integrity Guarantee**: **100.0%**. Every commitment lifecycle transition atomically inserts both an `audit_events` row (with full JSON state diffs and evidence pointers) and an `outbox_events` row (with canonical `DomainEvent` envelope and correlation/causation tracking).

---

## 7. Explicit Dataset Disclosures & Known Limitations

Per `REQUIREMENTS_SYSTEM.md` §7 and `AGENTS.md` §8/§10, the following methodological boundaries are strictly declared:
1. **Synthetic Hackathon Dataset**: All numbers in this report derive from authored synthetic SME order scenarios, test supplier delays, and synthetic proof documents (`ev_signed_courier_pod`). No real customer PII or banking transactions were processed.
2. **Deterministic Baseline Rules**: Feasibility and recovery guardrails are governed by deterministic Python/SQL constraint checkers and server-side RBAC policy. No black-box LLM calls are involved in state transitions, authorization, or stock reservations.
3. **Local Workstation Latencies**: Measured latencies represent in-process Python wall-clock execution against an in-memory SQLite database on the test workstation. Production PostgreSQL network round-trips and multi-tenant connection pools will vary.
4. **Scope Integrity**: These results prove full compliance of the Shared Commitment Core, application shell, and integration contracts for the P0 hackathon milestone.
