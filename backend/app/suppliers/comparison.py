"""Pure hard-requirement comparison using tenant-owned versioned specifications.

Construct from trusted source adapters after identity/evidence verification, not
from client/LLM approval assertions. No stock, recovery, purchase, selection or
message side effects. Price comparison is not functional substitutability.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Literal

from pydantic import AwareDatetime, Field, StrictBool, StrictStr, model_validator

from app.core.errors import DomainError
from app.orders.terms import Amount, ImmutableContract, Quantity, Text


class SpecField(ImmutableContract):
    name: Text
    kind: Literal["TEXT", "DECIMAL", "BOOLEAN"]
    unit: Text | None = None


class PropertyValue(ImmutableContract):
    name: Text
    value: StrictStr | StrictBool
    unit: Text | None = None
    evidence_refs: tuple[Text, ...] = ()


def _unique_names(values) -> None:
    if len({value.name for value in values}) != len(values):
        raise ValueError("Duplicate specification fields are ambiguous")


class CategorySpec(ImmutableContract):
    tenant_id: Text
    category_id: Text
    version: int = Field(ge=1, strict=True)
    authority: Literal["SME_CONFIG", "ORBYTE_CATALOG", "EXAMPLE"]
    approval_ref: Text | None
    evidence_refs: tuple[Text, ...]
    hard_fields: tuple[SpecField, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_fields(self):
        _unique_names(self.hard_fields)
        return self


class SupplierRequirement(ImmutableContract):
    tenant_id: Text
    category_id: Text
    spec_version: int = Field(ge=1, strict=True)
    properties: tuple[PropertyValue, ...]
    quantity: Quantity
    unit: Text
    needed_by: AwareDatetime
    currency: str = Field(pattern="^[A-Z]{3}$")

    @model_validator(mode="after")
    def unique_fields(self):
        _unique_names(self.properties)
        return self


class SupplierOffer(ImmutableContract):
    tenant_id: Text
    supplier_id: Text
    quote_id: Text
    quote_version: int = Field(ge=1, strict=True)
    category_id: Text
    spec_version: int = Field(ge=1, strict=True)
    properties: tuple[PropertyValue, ...]
    evidence_refs: tuple[Text, ...]
    price_per_pack: Amount | None
    units_per_pack: Quantity | None
    unit: Text
    moq: Quantity | None
    currency: str = Field(pattern="^[A-Z]{3}$")
    pack_evidence_refs: tuple[Text, ...]
    availability: Literal["CLAIMED", "VERIFIED", "UNKNOWN"]
    available_quantity: Amount | None
    availability_evidence_refs: tuple[Text, ...] = ()
    verified_property_names: frozenset[Text] = frozenset()
    verification_evidence_refs: tuple[Text, ...] = ()
    quoted_arrival: AwareDatetime | None
    arrival_evidence_refs: tuple[Text, ...] = ()
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def unique_fields(self):
        _unique_names(self.properties)
        return self


class OfferComparison(ImmutableContract):
    supplier_id: Text
    quote_id: Text
    quote_version: int = Field(ge=1, strict=True)
    spec_version: int | None = Field(ge=1, strict=True)
    status: Literal["MATCHES", "INCOMPATIBLE", "CONDITIONAL", "UNKNOWN"]
    violated_fields: tuple[Text, ...] = ()
    missing_fields: tuple[Text, ...] = ()
    reason_codes: tuple[Text, ...]
    normalized_unit_cost: Decimal | None = None
    currency: Text
    cost_basis: Text | None = None
    evidence_refs: tuple[Text, ...]
    purchasing_authorized: Literal[False] = False
    # Even a compatible verified quote is not an approved recovery plan.
    recovery_feasibility: Literal["CONDITIONAL"] = "CONDITIONAL"


def _value(field: SpecField, prop: PropertyValue | None):
    if prop is None or prop.unit != field.unit:
        return None
    if field.kind == "BOOLEAN":
        return prop.value if isinstance(prop.value, bool) else None
    if not isinstance(prop.value, str) or not prop.value.strip():
        return None
    if field.kind == "TEXT":
        return prop.value
    try:
        value = Decimal(prop.value)
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def compare_offers(
    schema: CategorySpec | None,
    requirement: SupplierRequirement,
    offers: Sequence[SupplierOffer],
    *,
    now: datetime,
) -> tuple[OfferComparison, ...]:
    """No implicit conversion, ranking, currency FX, policy approval or sourcing action."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Offset-aware comparison time required")
    if (schema is not None and schema.tenant_id != requirement.tenant_id) or any(
        offer.tenant_id != requirement.tenant_id for offer in offers
    ):
        raise DomainError(
            "SUPPLIER_INPUT_NOT_FOUND", "Supplier inputs were not found", status_code=404
        )
    results = []
    schema_valid = bool(
        schema
        and schema.authority != "EXAMPLE"
        and schema.approval_ref
        and schema.evidence_refs
        and schema.category_id == requirement.category_id
        and schema.version == requirement.spec_version
    )
    for offer in offers:
        base = {
            "supplier_id": offer.supplier_id,
            "quote_id": offer.quote_id,
            "quote_version": offer.quote_version,
            "spec_version": schema.version if schema else None,
            "currency": offer.currency,
            "evidence_refs": offer.evidence_refs,
        }
        if (
            not schema_valid
            or offer.category_id != requirement.category_id
            or offer.spec_version != requirement.spec_version
        ):
            results.append(
                OfferComparison(**base, status="UNKNOWN", reason_codes=("SPEC_UNKNOWN",))
            )
            continue
        required = {prop.name: prop for prop in requirement.properties}
        stated = {prop.name: prop for prop in offer.properties}
        violations, missing, reasons = [], [], []
        # Explicit SME requirements outside this approved schema cannot be
        # silently ignored or assigned an LLM-invented validation rule.
        missing.extend(sorted(set(required) - {field.name for field in schema.hard_fields}))
        for field in schema.hard_fields:
            expected, actual = (
                _value(field, required.get(field.name)),
                _value(field, stated.get(field.name)),
            )
            source = stated.get(field.name)
            if expected is None or actual is None or source is None or not source.evidence_refs:
                missing.append(field.name)
            elif expected != actual:
                violations.append(field.name)
        if violations:
            reasons.append("HARD_SPEC_MISMATCH")
        if missing:
            reasons.append("SPEC_UNKNOWN")
        if now >= offer.valid_until:
            reasons.append("QUOTE_EXPIRED")
        if requirement.needed_by <= now:
            reasons.append("REQUIREMENT_EXPIRED")
        if offer.moq is not None and requirement.quantity < offer.moq:
            reasons.append("MOQ_NOT_MET")
        if offer.available_quantity is not None and offer.available_quantity < requirement.quantity:
            reasons.append("INSUFFICIENT_AVAILABILITY")
        if offer.quoted_arrival is not None and offer.quoted_arrival > requirement.needed_by:
            reasons.append("ARRIVAL_AFTER_REQUIREMENT")
        if offer.unit != requirement.unit:
            reasons.append("UNIT_MISMATCH")
        unit_cost, basis = None, None
        if (
            offer.price_per_pack is not None
            and offer.units_per_pack is not None
            and offer.pack_evidence_refs
            and offer.evidence_refs
            and offer.currency == requirement.currency
            and offer.unit == requirement.unit
        ):
            with localcontext() as ctx:
                ctx.prec = 80
                unit_cost = (offer.price_per_pack / offer.units_per_pack).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )
            basis = (
                f"{offer.price_per_pack} / {offer.units_per_pack} {offer.unit}; "
                "rounded to 6 decimal places (HALF_UP)"
            )
        else:
            reasons.append("COST_BASIS_UNVERIFIED")
        required_names = {field.name for field in schema.hard_fields}
        verified = bool(
            offer.evidence_refs
            and offer.availability == "VERIFIED"
            and offer.availability_evidence_refs
            and offer.available_quantity is not None
            and offer.quoted_arrival is not None
            and offer.arrival_evidence_refs
            and offer.verification_evidence_refs
            and required_names <= offer.verified_property_names
            and offer.moq is not None
        )
        if not verified:
            reasons.append("SUPPLIER_CLAIM_NOT_VERIFIED")
        hard_codes = {
            "QUOTE_EXPIRED",
            "REQUIREMENT_EXPIRED",
            "MOQ_NOT_MET",
            "INSUFFICIENT_AVAILABILITY",
            "ARRIVAL_AFTER_REQUIREMENT",
            "UNIT_MISMATCH",
            "HARD_SPEC_MISMATCH",
        }
        status = (
            "INCOMPATIBLE"
            if hard_codes.intersection(reasons)
            else "UNKNOWN"
            if missing
            else "MATCHES"
            if verified
            else "CONDITIONAL"
        )
        refs = tuple(
            dict.fromkeys(
                (
                    *offer.evidence_refs,
                    *schema.evidence_refs,
                    *(ref for prop in offer.properties for ref in prop.evidence_refs),
                    *offer.verification_evidence_refs,
                    *offer.availability_evidence_refs,
                    *offer.arrival_evidence_refs,
                    *offer.pack_evidence_refs,
                )
            )
        )
        results.append(
            OfferComparison(
                **(base | {"evidence_refs": refs}),
                status=status,
                violated_fields=tuple(violations),
                missing_fields=tuple(missing),
                reason_codes=tuple(reasons),
                normalized_unit_cost=unit_cost,
                cost_basis=basis,
            )
        )
    return tuple(results)


def category_examples(tenant_id: str) -> tuple[CategorySpec, ...]:
    """Editable EXAMPLES only; no approval/source proof and therefore SPEC_UNKNOWN."""
    definitions = {
        "food_container": (
            SpecField(name="capacity_ml", kind="DECIMAL", unit="ml"),
            SpecField(name="material", kind="TEXT"),
            SpecField(name="food_safe", kind="BOOLEAN"),
        ),
        "perishable_ingredient": (
            SpecField(name="grade", kind="TEXT"),
            SpecField(name="storage_requirement", kind="TEXT"),
        ),
        "general_supply": (SpecField(name="sku", kind="TEXT"), SpecField(name="unit", kind="TEXT")),
    }
    return tuple(
        CategorySpec(
            tenant_id=tenant_id,
            category_id=category,
            version=1,
            authority="EXAMPLE",
            approval_ref=None,
            evidence_refs=(),
            hard_fields=fields,
        )
        for category, fields in definitions.items()
    )
