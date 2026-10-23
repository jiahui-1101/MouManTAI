"""Exact typed terms. A hash proves equality, never authenticity or assent.

No acceptance/reservation command is enabled here. Persisted integration needs
owner S1 approval and a server-verified source/identity/disclosure adapter.
Canonical v1 uses six fractional digits at most and exact arithmetic with a
local decimal context; it never rounds commercial values or normalizes free text.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from app.core.errors import DomainError


def _not_float(value):
    if isinstance(value, (float, bool)):
        raise ValueError("Use a decimal string, not a floating point value")
    return value


def _precision(value: Decimal) -> Decimal:
    if not value.is_finite() or value.as_tuple().exponent < -6 or value.copy_abs() >= 10**18:
        raise ValueError("Finite value with at most 18 integer and 6 fractional digits required")
    return value


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Blank value")
    return value


Text = Annotated[str, Field(min_length=1, max_length=500), AfterValidator(_nonblank)]
Amount = Annotated[Decimal, BeforeValidator(_not_float), Field(ge=0), AfterValidator(_precision)]
Quantity = Annotated[Decimal, BeforeValidator(_not_float), Field(gt=0), AfterValidator(_precision)]
Evidence = Annotated[tuple[Text, ...], Field(min_length=1)]


class ImmutableContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class PriceSource(ImmutableContract):
    """Binding price-source identity plus nonbinding evidence references.

    The source type, ID, version, policy and disclosure time participate in
    OrderTerms v1 equality. Evidence references are provenance metadata and
    must be validated independently against a trusted, current evidence source.
    """

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
        try:
            zone = ZoneInfo(self.business_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Unknown business timezone") from None
        _validate_window_timezone(self.window_start, zone, "window_start")
        _validate_window_timezone(self.window_end, zone, "window_end")
        if self.window_start.astimezone(UTC) >= self.window_end.astimezone(UTC):
            raise ValueError("Fulfilment window must end after it starts")
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
        """Return versioned binding values, not a proof or evidence verdict.

        List item order is irrelevant; exact IDs, unit spelling, conditions and
        price-source identity/version/policy/disclosed-at are binding. Terms
        revision, message IDs, general evidence refs, and price-source evidence
        refs are omitted for v1 compatibility and provenance corrections. No
        fuzzy SKU/unit/address equivalence. Callers must validate evidence
        existence, tenant binding, relation, currentness, revocation and assent
        separately; hash equality establishes none of those facts.
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


def _validate_window_timezone(value: datetime, zone: ZoneInfo, field_name: str) -> None:
    """Validate local offset timestamps against the named business zone.

    UTC timestamps represent absolute instants and are accepted directly.
    Non-UTC inputs must identify one valid local wall time in the named zone
    and use that time's actual offset. Repeated or nonexistent wall times fail
    closed; callers can provide an explicit UTC instant to disambiguate a fold.
    """
    offset = value.utcoffset()
    if offset is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    if offset == timedelta(0):
        return

    wall_time = value.replace(tzinfo=None)
    candidates: dict[datetime, timedelta | None] = {}
    for fold in (0, 1):
        local_candidate = wall_time.replace(tzinfo=zone, fold=fold)
        instant = local_candidate.astimezone(UTC)
        round_trip = instant.astimezone(zone)
        if round_trip.replace(tzinfo=None) == wall_time:
            candidates[instant] = local_candidate.utcoffset()

    if not candidates:
        raise ValueError(f"{field_name} is a nonexistent local time in business_timezone")
    if len(candidates) > 1:
        raise ValueError(
            f"{field_name} is ambiguous in business_timezone; provide an explicit UTC instant"
        )
    expected_offset = next(iter(candidates.values()))
    if offset != expected_offset:
        raise ValueError(f"{field_name} offset does not match business_timezone")


class TermsComparison(ImmutableContract):
    matches: bool
    original_hash: str
    proposed_hash: str
    changed_fields: tuple[str, ...]
    required_action: Literal["NONE", "PROPOSAL_REQUIRED"]


def compare_terms(original: OrderTerms, proposed: OrderTerms) -> TermsComparison:
    """Compare binding commercial terms, excluding revision and proof metadata.

    A matching result establishes only commercial-value equality. It does not
    establish current disclosure, authenticity, customer identity, or assent.
    """
    before, after = original.canonical_values(), proposed.canonical_values()
    changed = tuple(sorted(key for key in before if before[key] != after[key]))
    return TermsComparison(matches=not changed, original_hash=original.terms_hash,
                           proposed_hash=proposed.terms_hash, changed_fields=changed,
                           required_action="PROPOSAL_REQUIRED" if changed else "NONE")


def require_exact_terms(original: OrderTerms, proposed: OrderTerms, *, tenant_id: str,
                        expected_revision: int, expected_terms_hash: str) -> None:
    """Guard an unchanged original revision; caller must load terms from trusted storage.

    Passing this guard does not authorize acceptance, establish source trust,
    validate current disclosure, grant customer assent, or replace P2/role/
    reservation checks. A changed offer requires the separate verified
    proposal/version/customer-assent workflow.
    """
    if tenant_id != original.tenant_id or tenant_id != proposed.tenant_id:
        raise DomainError("TERMS_NOT_FOUND", "Terms were not found", status_code=404)
    if expected_revision != original.terms_revision:
        raise DomainError("STALE_TERMS_VERSION", "Terms version changed", status_code=409)
    if proposed.terms_revision != original.terms_revision:
        raise DomainError("STALE_TERMS_VERSION", "Proposed terms version changed", status_code=409)
    comparison = compare_terms(original, proposed)
    if expected_terms_hash != original.terms_hash or not comparison.matches:
        raise DomainError("TERMS_MISMATCH", "Exact customer-agreed terms required; create a proposal",
                          status_code=409, details={"required_action": "PROPOSAL_REQUIRED",
                                                   "changed_fields": list(comparison.changed_fields)})
