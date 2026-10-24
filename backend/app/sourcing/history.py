"""Supplier delivery history projection; input authenticity belongs to trusted readers."""

from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from app.orders.terms import Amount, ImmutableContract, Quantity, Text

Tier = Literal["VERIFIED", "REPORTED", "CLAIMED", "UNKNOWN", "DEMO_ONLY"]


class DeliveryFact(ImmutableContract):
    tenant_id: Text
    supplier_id: Text
    purchase_order_id: Text
    purchase_order_version: int = Field(ge=1, strict=True)
    quote_id: Text | None = None
    quote_version: int | None = Field(default=None, ge=1, strict=True)
    sku: Text
    unit: Text
    promised_quantity: Quantity
    promised_at: AwareDatetime
    promise_baseline_ref: Text | None = None
    received_quantity: Amount | None = None
    received_at: AwareDatetime | None = None
    receipt_id: Text | None = None
    quality_accepted: bool | None = None
    original_evidence_refs: tuple[Text, ...] = ()
    receipt_evidence_refs: tuple[Text, ...] = ()
    source_version: Text
    recorded_at: AwareDatetime
    trust_tier: Tier
    integration_mode: Literal["LIVE", "SYNTHETIC"]
    supersedes_source_version: Text | None = None

    @model_validator(mode="after")
    def coherent_receipt(self):
        if (self.received_quantity is None) != (self.received_at is None):
            raise ValueError("Receipt quantity and time must occur together")
        if self.received_at is not None and not self.receipt_id:
            raise ValueError("Receipt identity required")
        if (self.quote_id is None) != (self.quote_version is None):
            raise ValueError("Quote identity and version must occur together")
        return self


class HistorySnapshot(ImmutableContract):
    tenant_id: Text
    supplier_id: Text
    facts: tuple[DeliveryFact, ...] = Field(max_length=1000)
    source_watermark: Text
    complete: bool
    consistent_read: bool
    business_timezone: Text
    observed_at: AwareDatetime
    promise_policy: Literal["ORIGINAL_APPROVED", "APPROVED_REBASE", "UNAPPROVED"]
    integration_mode: Literal["LIVE", "SYNTHETIC"]

    @model_validator(mode="after")
    def valid_zone(self):
        try:
            ZoneInfo(self.business_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown business timezone") from exc
        return self


class HistoryMetrics(ImmutableContract):
    tenant_id: Text
    supplier_id: Text
    source_watermark: Text
    source_observed_at: AwareDatetime
    source_versions: tuple[Text, ...]
    evidence_refs: tuple[Text, ...]
    business_timezone: Text
    integration_mode: Literal["LIVE", "SYNTHETIC"]
    eligible_deliveries: int
    on_time_deliveries: int
    on_time_numerator: int
    eligible_denominator: int
    on_time_rate: Decimal | None
    known_late: int
    known_partial: int
    quality_exceptions: int
    missing_evidence: int
    evidence_coverage: Decimal | None
    incomplete_source_history: bool
    insufficient_history: bool
    observation_start: AwareDatetime | None
    observation_end: AwareDatetime | None
    limitations: tuple[Text, ...]


def analyze_history(snapshot: HistorySnapshot, *, minimum_sample: int = 3) -> HistoryMetrics:
    """Use one approved promise baseline per PO; never infer receipt from a claim."""
    if minimum_sample < 1:
        raise ValueError("minimum_sample must be positive")
    if not snapshot.consistent_read:
        raise ValueError("Inconsistent source snapshot")
    by_key: dict[tuple[str, str], DeliveryFact] = {}
    receipts: dict[str, tuple[str, Decimal | None, datetime | None]] = {}
    for fact in snapshot.facts:
        if fact.tenant_id != snapshot.tenant_id or fact.supplier_id != snapshot.supplier_id:
            raise ValueError("Tenant or supplier mismatch")
        if (
            fact.integration_mode != snapshot.integration_mode
            or fact.recorded_at > snapshot.observed_at
        ):
            raise ValueError("Mode mismatch or future source fact")
        if fact.received_at and fact.received_at > snapshot.observed_at:
            raise ValueError("Future receipt")
        key = (fact.purchase_order_id, fact.source_version)
        previous = by_key.get(key)
        if previous is not None and previous != fact:
            raise ValueError("Conflicting source replay")
        by_key[key] = fact
        if fact.receipt_id:
            receipt = (fact.purchase_order_id, fact.received_quantity, fact.received_at)
            owner = receipts.setdefault(fact.receipt_id, receipt)
            if owner != receipt:
                raise ValueError("Duplicate operational receipt")
    active: dict[str, DeliveryFact] = {}
    versions_by_order: dict[str, list[DeliveryFact]] = {}
    for fact in by_key.values():
        versions_by_order.setdefault(fact.purchase_order_id, []).append(fact)
    for order_facts in versions_by_order.values():
        ordered = sorted(order_facts, key=lambda item: item.purchase_order_version)
        for previous, revised in pairwise(ordered):
            if (
                revised.supersedes_source_version != previous.source_version
                or revised.purchase_order_version <= previous.purchase_order_version
                or (revised.sku, revised.unit, revised.quote_id, revised.quote_version)
                != (previous.sku, previous.unit, previous.quote_id, previous.quote_version)
            ):
                raise ValueError("Unbound purchase order revision")
    for fact in by_key.values():
        if fact.supersedes_source_version:
            older = by_key.get((fact.purchase_order_id, fact.supersedes_source_version))
            if older is None or older.purchase_order_version >= fact.purchase_order_version:
                raise ValueError("Unbound or out-of-order correction")
        current = active.get(fact.purchase_order_id)
        if current is None or fact.purchase_order_version > current.purchase_order_version:
            active[fact.purchase_order_id] = fact
        elif fact.purchase_order_version == current.purchase_order_version and fact != current:
            raise ValueError("Conflicting purchase order version")
    facts = tuple(active.values())
    eligible = on_time = late = partial = quality = missing = covered = 0
    limitations: set[str] = set()
    for fact in facts:
        verified = (
            fact.trust_tier == "VERIFIED"
            and bool(fact.original_evidence_refs)
            and bool(fact.receipt_evidence_refs)
            and fact.received_at is not None
            and fact.received_quantity is not None
        )
        if snapshot.integration_mode == "SYNTHETIC":
            limitations.add("SYNTHETIC_EVIDENCE_NOT_LIVE_AUTHORITY")
        if not verified:
            missing += 1
            limitations.add("MISSING_VERIFIED_PROMISE_OR_RECEIPT")
            continue
        covered += 1
        if fact.received_quantity < fact.promised_quantity:
            partial += 1
        if fact.quality_accepted is False:
            quality += 1
        if fact.quality_accepted is None:
            limitations.add("QUALITY_ACCEPTANCE_UNKNOWN")
        if not fact.promise_baseline_ref or snapshot.promise_policy == "UNAPPROVED":
            limitations.add("PROMISE_BASELINE_UNAPPROVED")
            continue
        eligible += 1
        if (
            fact.received_at <= fact.promised_at
            and fact.received_quantity >= fact.promised_quantity
        ):
            on_time += 1
        else:
            late += int(fact.received_at > fact.promised_at)
    if not snapshot.complete:
        limitations.add("INCOMPLETE_SOURCE_HISTORY")
    # A partial page or unapproved baseline cannot support a supplier success rate.
    rate_allowed = snapshot.complete and snapshot.promise_policy != "UNAPPROVED" and eligible > 0
    dates = [f.promised_at for f in facts]
    return HistoryMetrics(
        tenant_id=snapshot.tenant_id,
        supplier_id=snapshot.supplier_id,
        source_watermark=snapshot.source_watermark,
        source_observed_at=snapshot.observed_at,
        source_versions=tuple(sorted({fact.source_version for fact in by_key.values()})),
        evidence_refs=tuple(
            sorted(
                {
                    ref
                    for fact in by_key.values()
                    for ref in (*fact.original_evidence_refs, *fact.receipt_evidence_refs)
                }
            )
        ),
        business_timezone=snapshot.business_timezone,
        integration_mode=snapshot.integration_mode,
        eligible_deliveries=eligible,
        on_time_deliveries=on_time,
        on_time_numerator=on_time,
        eligible_denominator=eligible,
        on_time_rate=Decimal(on_time) / Decimal(eligible) if rate_allowed else None,
        known_late=late,
        known_partial=partial,
        quality_exceptions=quality,
        missing_evidence=missing,
        evidence_coverage=Decimal(covered) / Decimal(len(facts))
        if facts and snapshot.complete
        else None,
        incomplete_source_history=not snapshot.complete,
        insufficient_history=eligible < minimum_sample or not rate_allowed,
        observation_start=min(dates) if dates else None,
        observation_end=max(dates) if dates else None,
        limitations=tuple(sorted(limitations)),
    )
