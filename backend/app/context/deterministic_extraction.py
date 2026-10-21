"""Minimal, opt-in rules over StoredMessage; not wired to ingestion.

Supported: ORD-<digits> or synthetic_order_<alphanumeric>, burger/burgers,
and one immediately preceding ASCII quantity, optionally followed by pcs/pieces.
Only positive integer counts are valid for the provisional BURGER/pcs catalog.
Other numbers, lists, alternatives, negation or repeated products defer quantity
association. No dates, identity lookup, persistence or BusinessContext readiness.
Offsets are [start,end) Unicode code points in the UNCHANGED original text.
"""
from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Sequence

from .extraction import ExtractionResult
from .ingestion_schemas import StoredMessage
from .schemas import ExtractedField, FieldEvidence

VERSION = "p1-explicit-v1"


@dataclass(frozen=True)
class ProductAlias:
    tenant_id: str
    sku: str
    aliases: tuple[str, ...]
    unit: str


# Mirrors fixtures/scenarios.json, not an approved inventory or production SKU
# registry. Aliases are a narrow English spelling/plural rule, not fuzzy matching.
PROVISIONAL_PRODUCTS = tuple(ProductAlias(tenant, "BURGER", ("burger", "burgers"), "pcs")
                             for tenant in ("synthetic_tenant_a", "synthetic_tenant_b"))
ORDER = re.compile(r"(?<!\w)(?:ORD-[0-9]+|synthetic_order_[a-z0-9]+)(?!\w)", re.IGNORECASE)
NUMBER = re.compile(r"(?<![\w.,+\-])[+\-]?[0-9]+(?:[.,][0-9]+)?(?![\w.,])")
PREFIX = re.compile(r"(?<![\w.,+\-])(?P<quantity>[+\-]?[0-9]+(?:[.,][0-9]+)?)"
                    r"\s+(?:(?P<unit>[A-Za-z]+)\s+)?$")
UNSAFE_ASSOCIATION = re.compile(r"\b(?:and|or|dan|atau|not|no|cancel|instead)\b|[,;/]|和|或|不要|改成", re.IGNORECASE)


def extract_explicit_fields(message: StoredMessage, *, catalog: Sequence[ProductAlias]) -> ExtractionResult:
    """Return literal observations only. VALID means rule-valid, not authority.

    Caller supplies a tenant-scoped catalog; PROVISIONAL_PRODUCTS is development
    data only. An extracted order_id is always UNRESOLVED until an authorized
    lookup exists. Flat fields are safe here only for a single product mention;
    multiple mentions never receive a VALID associated quantity.
    """
    text = message.raw.text

    def evidence(start, end):
        return FieldEvidence(evidence_id=f"rule:{message.message_id}:{start}:{end}",
                             message_id=message.message_id, quote=text[start:end], start=start, end=end,
                             method="RULE", method_version=VERSION)

    def field(name, value, status, spans=()):
        return ExtractedField(field_name=name, value=value, validation_status=status,
                              evidence=[evidence(start, end) for start, end in spans])

    orders = list(ORDER.finditer(text))
    fields = [field("order_id", m.group(), "UNRESOLVED", [m.span()]) for m in orders]
    mentions = []
    for product in catalog:
        if product.tenant_id != message.raw.tenant_id:
            continue
        for alias in product.aliases:
            for match in re.finditer(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.IGNORECASE):
                key = (match.start(), match.end(), product.sku, product.unit)
                if not any(key == entry[0] for entry in mentions):
                    mentions.append((key, product, match))
    mentions.sort(key=lambda entry: entry[0])
    fields.extend(field("sku", p.sku, "VALID", [m.span()]) for _, p, m in mentions)
    numbers = [m for m in NUMBER.finditer(text)
               if not any(o.start() <= m.start() and m.end() <= o.end() for o in orders)]
    if not mentions:
        fields.extend([field("sku", None, "UNRESOLVED"),
                       field("quantity", None, "UNRESOLVED" if numbers else "MISSING",
                             [m.span() for m in numbers])])
    else:
        _, product, mention = mentions[0]
        prefix = PREFIX.search(text[:mention.start()])
        if len(mentions) != 1 or UNSAFE_ASSOCIATION.search(text) or len(numbers) > 1:
            fields.append(field("quantity", None, "UNRESOLVED", [m.span() for m in numbers]))
        elif prefix is None or len(numbers) != 1 or prefix.span("quantity") != numbers[0].span():
            fields.append(field("quantity", None, "UNRESOLVED" if numbers else "MISSING",
                                [m.span() for m in numbers]))
        else:
            raw_quantity = prefix.group("quantity")
            raw_unit = prefix.group("unit")
            unit_supported = product.unit == "pcs" and (raw_unit is None or raw_unit.lower() in {"pcs", "pieces"})
            # Commas, signs, fractions and unsupported units never become a
            # positive count by dropping punctuation or coercing to an integer.
            valid = raw_quantity.isascii() and raw_quantity.isdigit() and Decimal(raw_quantity) > 0
            fields.append(field("quantity", raw_quantity, "VALID" if valid and unit_supported else "INVALID",
                                [prefix.span("quantity")]))
            fields.append(field("unit", "pcs" if unit_supported and raw_unit else raw_unit,
                                "MISSING" if raw_unit is None else "VALID" if unit_supported else "INVALID",
                                [] if raw_unit is None else [prefix.span("unit")]))
    return ExtractionResult(status="AVAILABLE", fields=fields,
                            reason="Partial literal extraction only; delivery, identity and order authorization unresolved; manual review required")
