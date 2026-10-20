# P2 synthetic snapshot fixtures

These fixtures are P2-local and provisional until P5/P1 approve shared snapshot, SKU, and Commitment contracts. They contain only synthetic data. Phase 2 ATP reproduces the hand-labelled material shortages; the full feasibility evaluator remains Phase 3 work.

## Allocation and reservation rules used to label the examples

1. Active reservations are claims against the named inventory lot and are owned by the named confirmed commitment. The reserved quantity is credited only to that owner and removed once from the lot's unreserved pool. It is not subtracted again as general demand. Released and consumed reservations do not hold stock.
2. After owned reservations are applied, allocate unreserved stock and eligible receipts by `(material_use_at, commitment_id, commitment_version, line_id)`, ascending. Commitment ID is a stable lexical tie-break when material-use times are equal. This is a deterministic fixture policy, not an owner-approved business preference or a reservation command.
3. A lot is usable only if its expiry is strictly after material use; equality is expired. Incoming supply requires CONFIRMED status, validated confirmation/ETA evidence, current linked sources, and ETA no later than both material use and logistics cutoff (equality included). Unconfirmed promises never count. Outstanding receipts due at/before calculation time require reconciliation and yield UNKNOWN, preventing double counting of goods potentially already in stock.
4. Supplies and demand normalize to base units using explicit SKU-specific `unit_conversions`: ID, tenant, from/to units, positive Decimal factor and BOM-kind source refs. No inferred reverse/chained/cross-SKU conversion. Ambiguous mappings are rejected. Converted reservations cannot exceed normalized lot quantity. BOM quantity is per one parent base unit; `waste_multiplier >= 1` is consumption markup, not yield division. The default 1 is disclosed as no known loss. Each multiplier and conversion appears in assumptions.
5. Free lots use earliest expiry then lot ID; receipts follow by ETA/ID. Active reservation surplus remains held for its owner. Released/consumed reservations do not hold stock; source on-hand must already reflect actual consumption.
6. Scoped line warehouse IDs require exact lot/receipt warehouse matches. An unlocated receipt cannot supply scoped demand. Unscoped demand explicitly pools warehouses; this is an assumption, not a verified transfer plan.

## Phase 2 calculation interface and limits

```python
from backend.app.feasibility.bom import explode_bom
from backend.app.feasibility.inventory import calculate_atp

scenario = build_supplier_delay_scenario()
requirements = explode_bom(scenario.after, tenant_id=scenario.after.tenant_id)
materials = calculate_atp(scenario.after, tenant_id=scenario.after.tenant_id)
```

Both functions revalidate immutable inputs, including Pydantic copies that bypass validators. ATP processes all confirmed commitments in one batch. Repeated queries cannot reserve or consume operational inventory. Default calculation time is `captured_at`; explicit offset-aware `as_of >= captured_at` rechecks freshness. Capture-time replay is historical, never proof of current state. Relevant source categories must represent complete, current stock/reservation/receipt/competing-demand ledgers. Empty rows with a current source represent a source-verified zero; missing/stale sources do not. P5 must uphold completeness/authenticity at its adapter boundary.

`BomExpansion` gives COMPLETE/UNKNOWN, leaf quantities, paths/component IDs, evidence and assumptions. `MaterialATP` gives COVERED/SHORTAGE/UNKNOWN, snapshot ID/version, tenant, calculation time, issues and material rows. `usable`, `reserved`, and `confirmed_incoming` are disjoint **allocated** quantities, not reusable stock totals. Rows also give required/shortage/unit/need-time, allocation supply/reservation IDs and evidence. Exact arithmetic ignores caller precision/exponent/trap settings. Unsupported limits yield UNKNOWN or input validation errors.

Missing/stale relevant sources, missing BOM, cycles, past material demand and overdue outstanding receipts make the entire batch UNKNOWN without confident material rows. Stocked manufactured assemblies also yield UNKNOWN: leaf explosion does not net finished/intermediate stock against new production. Deeper BOM inputs inherit root material-use time; no production lead times are invented. Capacity/job conflicts, full FeasibilityAssessment status, hypothetical plans, events, API/auth and persistence are later phases. COVERED is not FEASIBLE; SHORTAGE is a material constraint under the declared priority, not proof that every alternative allocation/schedule fails.

## Supplier-delay fixture: one affected, one buffered

`build_supplier_delay_scenario()` returns immutable versions 1 and 2 for `tenant-synthetic-p2`. Each burger needs one patty, bun, and wrap. Commitment `com-001` needs 100 patties at `2026-10-23T09:00:00+08:00`; `com-002` needs 20 at `2026-10-24T09:00:00+08:00`. The 80-patty lot has 20 units actively reserved for `com-002`, leaving 60 unreserved. A confirmed 40-patty delivery is due at `08:00` in version 1, then delayed to `11:00` in version 2. The fixture labels `com-001` with a 40-patty shortage in version 2; `com-002` remains covered by its owned reservation and has a later material-use time. A separate 500-patty promise is explicitly unconfirmed and is not eligible supply. The logistics cutoff is `2026-10-24T08:00:00+08:00`. The `kitchen-line-1` capacity calendar includes `07:00–17:00` windows with 480 available minutes on both Oct 23 and Oct 24 (+08:00), covering the two material-use timestamps in each snapshot version. This test establishes calendar coverage only; it does not prove that the production schedule is feasible.

## Supplier-delay fixture: two affected commitments

`build_two_affected_scenario()` has 30 unreserved patties, confirmed inbound quantity 110, and two commitments needing 100 and 40 patties at the same `2026-10-23T09:00:00+08:00` material-use time. The 110-unit receipt changes from `08:00` to `11:00`; the fixture logistics cutoff is `08:00`. The stable lexical tie-break gives `com-001` the 30 on-hand units first. Labels are therefore shortages of 70 for `com-001` and 40 for `com-002`, total 110, with both commitments affected. Without the declared priority, individual shortage labels would be arbitrary and the same 30 units could be counted twice.

## Supplier confirmation provenance (P2-local, provisional)

Every `CONFIRMED` `IncomingDelivery` must carry a `confirmation_evidence_id` that resolves to a typed `CONFIRMATION` claim nested in a validated `SourceEvidence` row. The claim identifies its tenant, supplier, delivery, evidence reference, and observation time. Validation requires the claim's source to be an incoming-deliveries source, the exact evidence reference to exist in that source row, the source ID to remain linked from the delivery, and the tenant/supplier/delivery IDs to match. Its observation time must match `confirmed_at`. A generic source reference, quote-only claim, ETA-change claim, or claim for another delivery cannot establish confirmation.

For an ETA change, the next snapshot retains the original `confirmation_evidence_id` and original source link, then adds a separate `ETA_CHANGE` evidence ID and source link. The changed ETA notice is not substituted for the initial supplier confirmation. Focused tests verify both associations resolve in the before/after fixture and reject missing, quote-only, ETA-only, or disconnected confirmation provenance.

This P2-local structure guarantees only traceable, correctly typed associations inside the validated snapshot. Synthetic evidence references do not prove an external supplier's identity, document authenticity, or truth. Authenticity and trusted classification of evidence from real adapters remain a P5 source-adapter responsibility. These P2 model fields are provisional and do not modify the shared P5 contract.

## Time handling

Every snapshot and row timestamp must include an explicit UTC offset; naive local datetimes are rejected. Fixture business times use `+08:00` / `Asia/Kuala_Lumpur`. Comparisons normalize instants to UTC, so equivalent offsets represent the same instant. `material_use_at` is when inputs are required by production; `delivery_deadline` is the customer-facing deadline. They are separate values. Capacity calendars name their IANA timezone and store offset-aware window boundaries. No timestamp inherits the machine's local timezone.

## Ownership and audit limits

Source rows retain tenant scope, adapter/source references, observed time, validity horizon, and evidence references. Snapshot objects are immutable and each ETA change creates a new ID/version. These local models do not persist snapshots, write Core state, publish events, reserve inventory, or define the final shared serialization contract; P5 owns those integrations.
