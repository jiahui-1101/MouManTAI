# P2 synthetic snapshot fixtures

These fixtures are P2-local and provisional until P5/P1 approve shared snapshot, SKU, and Commitment contracts. They contain only synthetic data. They are reproducibility inputs and hand-labelled expected outcomes; no feasibility evaluator runs in Phase 1.

## Allocation and reservation rules used to label the examples

1. Active reservations are claims against the named inventory lot and are owned by the named confirmed commitment. The reserved quantity is credited only to that owner and removed once from the lot's unreserved pool. It is not subtracted again as general demand. Released and consumed reservations do not hold stock.
2. After owned reservations are applied, allocate unreserved stock and eligible receipts by `(material_use_at, commitment_id, commitment_version, line_id)`, ascending. Commitment ID is a stable lexical tie-break when material-use times are equal. This is a deterministic fixture policy, not an owner-approved business preference or a reservation command.
3. A lot expired at snapshot capture is preserved as evidence but marked unusable. An incoming delivery is eligible for future availability only when its status is `CONFIRMED`, its ETA is no later than both the line's material-use time and the snapshot's logistics cutoff, and the delivery has confirmation evidence. `UNCONFIRMED` promises remain visible in the snapshot but never count as verified supply.
4. Supplies are considered per SKU and base unit. Phase 1 rejects implicit unit conversion; conversion rules are deferred to Phase 2 and require explicit source-backed mappings.

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
