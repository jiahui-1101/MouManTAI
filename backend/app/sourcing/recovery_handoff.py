"""Pure conditional alternative-supply input for P3 owner integration."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field

from app.orders.terms import ImmutableContract, Quantity, Text
from app.sourcing.dossier import DossierEntry
from app.sourcing.selection import SelectionPreview


class RecoveryContext(ImmutableContract):
    tenant_id: Text
    commitment_id: Text
    commitment_version: int = Field(ge=1)
    recovery_case_id: Text | None = None
    sourcing_case_id: Text
    quantity: Quantity
    unit: Text
    requirement_deadline: AwareDatetime
    current_source_version: Text
    evidence_refs: tuple[Text, ...]


class AlternativeSupplyHandoff(ImmutableContract):
    tenant_id: Text
    commitment_id: Text
    commitment_version: int
    recovery_case_id: Text | None
    sourcing_case_id: Text
    supplier_id: Text
    quote_id: Text
    quote_version: int
    spec_version: int
    comparison_status: Text
    historical_comparison_status: Text
    quote_validity_at_handoff: Literal["VALID_AT_HANDOFF", "EXPIRED_AT_HANDOFF"]
    demand_binding_status: Literal["PARTIAL_QUANTITY_UNIT_MATCH", "MISMATCHED"]
    supply_coverage_status: Literal["UNVERIFIED"] = "UNVERIFIED"
    availability_trust: Text
    quantity: Quantity
    unit: Text
    estimated_arrival: AwareDatetime | None
    requirement_deadline: AwareDatetime
    historical_on_time_rate: str | None
    historical_sample_size: int
    evidence_refs: tuple[Text, ...]
    missing_prerequisites: tuple[Text, ...]
    source_version: Text
    status: Literal["CONDITIONAL"] = "CONDITIONAL"
    sme_approval_required: Literal[True] = True
    purchasing_integration: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    received_inventory: Literal[False] = False
    p2_feasibility_override: Literal[False] = False


def prepare_alternative_supply(
    context: RecoveryContext, selection: SelectionPreview, entry: DossierEntry, *, now: datetime
) -> AlternativeSupplyHandoff:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Offset-aware current time required")
    if (
        context.tenant_id != selection.tenant_id
        or context.tenant_id != entry.tenant_id
        or context.sourcing_case_id != selection.sourcing_case_id
        or context.current_source_version != selection.current_source_context_version
        or (
            selection.supplier_id,
            selection.quote_id,
            selection.quote_version,
            selection.spec_version,
        )
        != (entry.supplier_id, entry.quote_id, entry.quote_version, entry.spec_version)
    ):
        raise ValueError("Recovery context and selected quote mismatch")
    missing = set(selection.outstanding_risks)
    quote_expired = entry.quote_valid_until <= now
    if quote_expired:
        missing.add("QUOTE_EXPIRED")
    missing.add("CURRENT_TRUSTED_QUOTATION_REVALIDATION")
    # The versioned requirement ID and version are not carried by the canonical
    # SupplierRequirement/DossierEntry contract, so this handoff cannot prove
    # that the selected quote still belongs to the current demand revision.
    missing.update(
        (
            "REQUIREMENT_ID_REVALIDATION",
            "REQUIREMENT_VERSION_REVALIDATION",
            "SKU_REVALIDATION",
        )
    )
    demand_binding_matches = (
        context.quantity == entry.required_quantity
        and context.unit == entry.required_unit
        and entry.quoted_unit == entry.required_unit
    )
    if context.unit != entry.required_unit or entry.quoted_unit != entry.required_unit:
        missing.add("DEMAND_UNIT_REVALIDATION")
    if context.quantity != entry.required_quantity:
        missing.add("DEMAND_QUANTITY_REVALIDATION")
    if entry.quoted_available_quantity is None:
        missing.add("SUPPLIER_AVAILABILITY_REVALIDATION")
    elif entry.quoted_available_quantity < entry.required_quantity:
        missing.update(("INSUFFICIENT_QUOTED_QUANTITY", "SUPPLIER_AVAILABILITY_REVALIDATION"))
    # Even an adequate quoted quantity is not current inventory or a trusted
    # versioned availability receipt. Revalidate at operational consideration.
    missing.add("SUPPLIER_AVAILABILITY_REVALIDATION")
    if not entry.evidence_refs or not context.evidence_refs:
        missing.add("SOURCE_EVIDENCE")
    if entry.quoted_arrival is None:
        missing.add("ARRIVAL_ESTIMATE")
    elif entry.quoted_arrival > context.requirement_deadline:
        missing.add("ARRIVAL_AFTER_COMMITMENT_DEADLINE")
    if entry.availability_trust != "VERIFIED":
        missing.add("VERIFIED_AVAILABILITY")
    if entry.canonical_status != "MATCHES":
        missing.add("HARD_SPEC_MATCH")
    missing.update(
        (
            "P2_FEASIBILITY_REEVALUATION",
            "P3_PLAN_APPROVAL",
            "PURCHASE_AUTHORITY",
            "ACTUAL_RECEIPT_NOT_VERIFIED",
        )
    )
    return AlternativeSupplyHandoff(
        tenant_id=context.tenant_id,
        commitment_id=context.commitment_id,
        commitment_version=context.commitment_version,
        recovery_case_id=context.recovery_case_id,
        sourcing_case_id=context.sourcing_case_id,
        supplier_id=entry.supplier_id,
        quote_id=entry.quote_id,
        quote_version=entry.quote_version,
        spec_version=entry.spec_version,
        comparison_status="STALE_COMPARISON" if quote_expired else entry.canonical_status,
        historical_comparison_status=entry.canonical_status,
        quote_validity_at_handoff=("EXPIRED_AT_HANDOFF" if quote_expired else "VALID_AT_HANDOFF"),
        demand_binding_status=(
            "PARTIAL_QUANTITY_UNIT_MATCH" if demand_binding_matches else "MISMATCHED"
        ),
        availability_trust=entry.availability_trust,
        quantity=context.quantity,
        unit=context.unit,
        estimated_arrival=entry.quoted_arrival,
        requirement_deadline=context.requirement_deadline,
        historical_on_time_rate=selection.historical_on_time_rate,
        historical_sample_size=entry.historical_sample_size,
        evidence_refs=tuple(sorted(set(entry.evidence_refs) | set(context.evidence_refs))),
        missing_prerequisites=tuple(sorted(missing)),
        source_version=context.current_source_version,
    )
