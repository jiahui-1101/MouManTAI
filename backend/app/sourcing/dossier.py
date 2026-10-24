"""Side-by-side advisory display of canonical comparisons and source-bound history."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field

from app.orders.terms import ImmutableContract, Text
from app.sourcing.history import HistoryMetrics
from app.suppliers.comparison import (
    CategorySpec,
    SupplierOffer,
    SupplierRequirement,
    compare_offers,
)


class DossierEntry(ImmutableContract):
    tenant_id: Text
    supplier_id: Text
    quote_id: Text
    quote_version: int = Field(ge=1, strict=True)
    required_quantity: Decimal
    required_unit: Text
    quoted_unit: Text
    quoted_available_quantity: Decimal | None
    availability_evidence_refs: tuple[Text, ...]
    category_id: Text
    spec_version: int = Field(ge=1, strict=True)
    canonical_status: Literal["MATCHES", "CONDITIONAL", "INCOMPATIBLE", "UNKNOWN"]
    advisory_status: Literal[
        "COMPATIBLE_FOR_CONSIDERATION",
        "CONDITIONAL_MORE_EVIDENCE_REQUIRED",
        "INCOMPATIBLE",
        "COMPARISON_UNAVAILABLE",
    ]
    violated_fields: tuple[Text, ...]
    missing_fields: tuple[Text, ...]
    reason_codes: tuple[Text, ...]
    normalized_unit_cost: Decimal | None
    cost_basis: Text | None
    cost_comparable_for_selection: bool
    currency: Text
    evidence_refs: tuple[Text, ...]
    availability_trust: Text
    quoted_arrival: AwareDatetime | None
    historical_on_time_rate: Decimal | None
    historical_sample_size: int
    historical_evidence_coverage: Decimal | None
    quality_exceptions: int | None
    history_source_watermark: Text | None
    history_source_observed_at: AwareDatetime | None
    history_integration_mode: Literal["LIVE", "SYNTHETIC"] | None
    quote_valid_until: AwareDatetime
    missing_information: tuple[Text, ...]
    safe_next_action: Text
    source_limitations: tuple[Text, ...]
    purchasing_authorized: Literal[False] = False


def build_dossier(
    schema: CategorySpec | None,
    requirement: SupplierRequirement,
    offers: Sequence[SupplierOffer],
    histories: Sequence[HistoryMetrics],
    *,
    now: datetime,
) -> tuple[DossierEntry, ...]:
    comparisons = compare_offers(schema, requirement, offers, now=now)
    history_by_supplier = {}
    for history in histories:
        if history.tenant_id != requirement.tenant_id or history.supplier_id in history_by_supplier:
            raise ValueError("History tenant mismatch or duplicate supplier")
        history_by_supplier[history.supplier_id] = history
    if len({(o.supplier_id, o.quote_id, o.quote_version) for o in offers}) != len(offers):
        raise ValueError("Duplicate quotation version")
    if not set(history_by_supplier) <= {offer.supplier_id for offer in offers}:
        raise ValueError("History supplier does not match any quotation")
    results = []
    labels = {
        "MATCHES": "COMPATIBLE_FOR_CONSIDERATION",
        "CONDITIONAL": "CONDITIONAL_MORE_EVIDENCE_REQUIRED",
        "INCOMPATIBLE": "INCOMPATIBLE",
        "UNKNOWN": "COMPARISON_UNAVAILABLE",
    }
    for offer, comparison in zip(offers, comparisons, strict=True):
        history = history_by_supplier.get(offer.supplier_id)
        missing = set(comparison.missing_fields)
        if not offer.evidence_refs:
            missing.add("QUOTE_SOURCE_EVIDENCE")
        if not offer.availability_evidence_refs or offer.availability != "VERIFIED":
            missing.add("VERIFIED_AVAILABILITY")
        if comparison.normalized_unit_cost is None:
            missing.add("COMPARABLE_COST_BASIS")
        if offer.quoted_arrival is None:
            missing.add("QUOTED_ARRIVAL")
        limitations = set(history.limitations if history else ("NO_SUPPLIER_HISTORY",))
        if history and history.insufficient_history:
            limitations.add("INSUFFICIENT_HISTORY")
        if offer.currency != requirement.currency:
            limitations.add("CURRENCY_NOT_COMPARABLE_WITHOUT_APPROVED_FX")
        if offer.availability == "VERIFIED":
            limitations.add("QUOTED_AVAILABILITY_IS_NOT_RECEIVED_INVENTORY")
        results.append(
            DossierEntry(
                tenant_id=requirement.tenant_id,
                supplier_id=offer.supplier_id,
                quote_id=offer.quote_id,
                quote_version=offer.quote_version,
                required_quantity=requirement.quantity,
                required_unit=requirement.unit,
                quoted_unit=offer.unit,
                quoted_available_quantity=offer.available_quantity,
                availability_evidence_refs=offer.availability_evidence_refs,
                category_id=offer.category_id,
                spec_version=offer.spec_version,
                canonical_status=comparison.status,
                advisory_status=labels[comparison.status],
                violated_fields=comparison.violated_fields,
                missing_fields=comparison.missing_fields,
                reason_codes=comparison.reason_codes,
                normalized_unit_cost=comparison.normalized_unit_cost,
                cost_basis=comparison.cost_basis,
                cost_comparable_for_selection=(
                    comparison.status == "MATCHES" and comparison.normalized_unit_cost is not None
                ),
                currency=comparison.currency,
                evidence_refs=comparison.evidence_refs,
                availability_trust=offer.availability,
                quoted_arrival=offer.quoted_arrival,
                historical_on_time_rate=history.on_time_rate if history else None,
                historical_sample_size=history.eligible_denominator if history else 0,
                historical_evidence_coverage=history.evidence_coverage if history else None,
                quality_exceptions=history.quality_exceptions if history else None,
                history_source_watermark=history.source_watermark if history else None,
                history_source_observed_at=history.source_observed_at if history else None,
                history_integration_mode=history.integration_mode if history else None,
                quote_valid_until=offer.valid_until,
                missing_information=tuple(sorted(missing)),
                safe_next_action="SME_REVIEW_QUOTE"
                if comparison.status == "MATCHES"
                else "REQUEST_EVIDENCE_OR_ALTERNATIVE",
                source_limitations=tuple(sorted(limitations)),
            )
        )
    return tuple(
        sorted(results, key=lambda item: (item.supplier_id, item.quote_id, item.quote_version))
    )
