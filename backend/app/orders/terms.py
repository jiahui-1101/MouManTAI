"""Exact typed terms. A hash proves equality, never authenticity or assent.

No acceptance/reservation command is enabled here. Persisted integration needs
owner S1 approval and a server-verified source/identity/disclosure adapter.
Canonical v1 uses six fractional digits at most and exact arithmetic with a
local decimal context; it never rounds commercial values or normalizes free text.
"""

from datetime import UTC
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator,
)

from app.core.errors import DomainError


def _not_float(value):
    if isinstance(value, (float, bool)):
        raise ValueError("Use a decimal string, not a floating point value")
    return value


def _precision(value: Decimal) -> Decimal:
    if not value.is_finite() or value.as_tuple().exponent < -6 or abs(value) >= 10**18:
        raise ValueError("Finite value with at most 18 integer and 6 fractional digits required")
    return value


Text = Annotated[str, Field(min_length=1, max_length=500), AfterValidator(
    lambda v: v if v.strip() else (_ for _ in ()).throw(ValueError("Blank value")))]
Amount = Annotated[Decimal, BeforeValidator(_not_float), Field(ge=0), AfterValidator(_precision)]
Quantity = Annotated[Decimal, BeforeValidator(_not_float), Field(gt=0), AfterValidator(_precision)]
Evidence = Annotated[tuple[Text, ...], Field(min_length=1)]


class ImmutableContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class PriceSource(ImmutableContract):
    source_type: Literal["APPROVED_CATALOG", "APPROVED_QUOTE"]
    source_id: Text
    source_version: Text
    policy_ref: Text
    disclosed_at: AwareDatetime
    evidence_refs: Evidence


class OrderLine(ImmutableContract):
    sku: Text
    variant: Text | None = None
    quantity: Quantity
    unit: Text
    unit_price: Amount


def _decimal_text(value: Decimal) -> str:
    # format(f) is independent of the process Decimal context; normalize() is not.
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if value == 0 else text


class OrderTerms(ImmutableContract):
    tenant_id: Text
    order_request_id: Text
    customer_id: Text
    terms_revision: int = Field(ge=1)
    items: tuple[OrderLine, ...] = Field(min_length=1, max_length=100)
    fulfilment_method: Literal["DELIVERY", "PICKUP"]
    location_ref: Text
    window_start: AwareDatetime
    window_end: AwareDatetime
    business_timezone: Text
    currency: str = Field(pattern="^[A-Z]{3}$")
    fees: Amount
    tax: Amount
    discount: Amount
    total: Amount
    price_source: PriceSource
    special_conditions: tuple[Text, ...] = ()
    binding_policy_ref: Text
    source_message_ids: Evidence
    evidence_refs: Evidence

    @model_validator(mode="after")
    def validate_business_values(self):
        if self.window_start >= self.window_end:
            raise ValueError("Fulfilment window must end after it starts")
        try:
            ZoneInfo(self.business_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Unknown business timezone") from None
        keys = [(line.sku, line.variant, line.unit) for line in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate SKU/variant/unit lines must be resolved explicitly")
        with localcontext() as ctx:
            ctx.prec = 80
            expected = sum((line.quantity * line.unit_price for line in self.items), Decimal(0))
            expected += self.fees + self.tax - self.discount
            if expected < 0 or expected != self.total:
                raise ValueError("Total must equal exact line amounts plus fees/tax minus discount")
        return self

    def canonical_values(self) -> dict:
        """Versioned binding values; evidence IDs and extraction revision are metadata.

        List item order is irrelevant; exact IDs, unit spelling, conditions and
        pricing provenance are binding. No fuzzy SKU/unit/address equivalence.
        """
        values = self.model_dump(mode="json", exclude={
            "terms_revision", "source_message_ids", "evidence_refs", "price_source",
        })
        values["items"] = sorted([
            dict(sku=line.sku, variant=line.variant, unit=line.unit,
                 quantity=_decimal_text(line.quantity), unit_price=_decimal_text(line.unit_price))
            for line in self.items
        ], key=lambda line: (line["sku"], line["variant"] or "", line["unit"]))
        for name in ("fees", "tax", "discount", "total"):
            values[name] = _decimal_text(getattr(self, name))
        for name in ("window_start", "window_end"):
            values[name] = getattr(self, name).astimezone(UTC).isoformat()
        values["price_source"] = self.price_source.model_dump(mode="json", exclude={"evidence_refs"})
        values["price_source"]["disclosed_at"] = self.price_source.disclosed_at.astimezone(UTC).isoformat()
        return values

    @property
    def terms_hash(self) -> str:
        encoded = json.dumps(self.canonical_values(), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")
        return "order-terms-v1:" + sha256(encoded).hexdigest()


class TermsComparison(ImmutableContract):
    matches: bool
    original_hash: str
    proposed_hash: str
    changed_fields: tuple[str, ...]
    required_action: Literal["NONE", "PROPOSAL_REQUIRED"]


def compare_terms(original: OrderTerms, proposed: OrderTerms) -> TermsComparison:
    before, after = original.canonical_values(), proposed.canonical_values()
    changed = tuple(sorted(key for key in before if before[key] != after[key]))
    return TermsComparison(matches=not changed, original_hash=original.terms_hash,
                           proposed_hash=proposed.terms_hash, changed_fields=changed,
                           required_action="PROPOSAL_REQUIRED" if changed else "NONE")


def require_exact_terms(original: OrderTerms, proposed: OrderTerms, *, tenant_id: str,
                        expected_revision: int, expected_terms_hash: str) -> None:
    """Side-effect-free precondition; caller must load original from trusted storage.

    Passing this guard does not authorize acceptance, establish source trust,
    grant customer assent, or replace P2/role/reservation checks.
    """
    if tenant_id != original.tenant_id or tenant_id != proposed.tenant_id:
        raise DomainError("TERMS_NOT_FOUND", "Terms were not found", status_code=404)
    if expected_revision != original.terms_revision:
        raise DomainError("STALE_TERMS_VERSION", "Terms version changed", status_code=409)
    comparison = compare_terms(original, proposed)
    if expected_terms_hash != original.terms_hash or not comparison.matches:
        raise DomainError("TERMS_MISMATCH", "Exact customer-agreed terms required; create a proposal",
                          status_code=409, details={"required_action": "PROPOSAL_REQUIRED",
                                                   "changed_fields": list(comparison.changed_fields)})
