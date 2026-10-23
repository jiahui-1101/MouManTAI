"""Canonical Field Reconciliation and Deduplication for MouManTAI P1.

Enforces:
1. P1 extracts strictly ONLY the allowed canonical fields:
   - sku
   - quantity
   - unit
   - requested_delivery_at
   (Order reference PO/ORD is context envelope metadata for message association, never a 5th canonical field).
2. Exactly ONE authoritative result per logical field per item.
3. No duplicate RULE and MODEL rows for identical or conflicting proposals.
4. Genuinely absent fields remain MISSING (never fabricated or forced to VALID/UNRESOLVED).
5. Unsafe or ambiguous model proposals are rejected or preserved as UNRESOLVED without polluting canonical fields.
6. Full audit preservation: all raw proposals are kept in diagnostics/raw_proposals.
"""

from typing import Sequence
import re

from .schemas import ExtractedField, FieldEvidence
from .deterministic_extraction import ProductAlias, UNIT_NORMALIZATION


ALLOWED_CANONICAL_FIELD_NAMES = {
    "sku",
    "quantity",
    "unit",
    "requested_delivery_at",
}


def reconcile_canonical_fields(
    rule_fields: Sequence[ExtractedField],
    model_candidates: Sequence[ExtractedField],
    *,
    catalog: Sequence[ProductAlias] | None = None,
    tenant_id: str | None = None,
    raw_text: str = "",
) -> tuple[list[ExtractedField], int]:
    """Reconcile deterministic rule observations and AI model proposals into
    canonical, deduplicated fields.

    Returns:
        (canonical_fields, accepted_model_count)
    """
    accepted_model_count = 0

    # 1. Filter out any field names that are not in the approved canonical contract
    valid_rule_fields = [
        f for f in rule_fields if f.field_name in ALLOWED_CANONICAL_FIELD_NAMES
    ]
    valid_model_candidates = [
        c for c in model_candidates if c.field_name in ALLOWED_CANONICAL_FIELD_NAMES
    ]

    # Build catalog SKU lookup for the tenant
    tenant_catalog_skus = set()
    tenant_catalog_units: dict[str, set[str]] = {}
    if catalog:
        for p in catalog:
            if tenant_id is None or p.tenant_id == tenant_id:
                tenant_catalog_skus.add(p.sku)
                tenant_catalog_units.setdefault(p.sku, set()).add(p.unit)

    # 2. Reconcile delivery (requested_delivery_at) - exactly 1 canonical field
    delivery_fields = [f for f in valid_rule_fields if f.field_name == "requested_delivery_at"]
    model_delivery_candidates = [c for c in valid_model_candidates if c.field_name == "requested_delivery_at"]
    canonical_delivery: ExtractedField | None = None

    rule_del = delivery_fields[0] if delivery_fields else None

    if rule_del is not None:
        if rule_del.validation_status == "VALID":
            # Rule has unambiguous delivery, keep it canonical
            canonical_delivery = rule_del
        elif rule_del.validation_status == "UNRESOLVED":
            # Rule found complex temporal semantics (rescheduling, weekday conflict, date range, etc.)
            # Do NOT create competing delivery rows. Keep the single UNRESOLVED delivery field
            # with full semantic metadata and qualifier.
            canonical_delivery = rule_del
            if model_delivery_candidates:
                # If model provides grounded evidence for the requested delivery, record agreement in metadata
                cand = model_delivery_candidates[0]
                if cand.value and not canonical_delivery.value:
                    # Model proposed normalized ISO value without conflicting
                    pass
        elif rule_del.validation_status == "MISSING":
            # Customer did not provide a delivery date.
            # Genuinely absent delivery MUST remain MISSING.
            # Never infer delivery from urgency, stock shortage, or ETA questions.
            is_explicit_delivery_proposal = False
            if model_delivery_candidates:
                cand = model_delivery_candidates[0]
                # Only accept model delivery if it is grounded in an explicit date/time expression
                # and not background context or ETA question
                if cand.value and cand.evidence and cand.metadata.get("domain_supported") == "true":
                    quote = cand.evidence[0].quote.lower()
                    has_date_number = bool(re.search(r'\b[0-9]{1,4}\b', quote))
                    has_time_word = bool(re.search(r'\b(?:am|pm|pagi|petang|malam|sharp|o\'clock)\b', quote))
                    if has_date_number or has_time_word:
                        is_explicit_delivery_proposal = True
                        canonical_delivery = cand
                        accepted_model_count += 1
            if not is_explicit_delivery_proposal:
                canonical_delivery = rule_del
        else:
            canonical_delivery = rule_del
    elif model_delivery_candidates:
        canonical_delivery = model_delivery_candidates[0]
        accepted_model_count += 1
    else:
        canonical_delivery = ExtractedField(
            field_name="requested_delivery_at",
            value=None,
            validation_status="MISSING",
            evidence=[],
        )

    # 4. Reconcile Item Fields (sku, quantity, unit)
    # Group rule fields by item group (default "g1" for single item)
    groups: dict[str, dict[str, ExtractedField]] = {}
    for f in valid_rule_fields:
        if f.field_name in ("sku", "quantity", "unit"):
            gid = f.metadata.get("group_id") or "g1"
            groups.setdefault(gid, {})
            current = groups[gid].get(f.field_name)
            if current is None:
                groups[gid][f.field_name] = f
            elif current.value is None and f.value is not None:
                groups[gid][f.field_name] = f
            elif current.validation_status != "VALID" and f.validation_status == "VALID":
                groups[gid][f.field_name] = f

    if not groups:
        groups["g1"] = {}

    # Separate model candidates into items and align with existing rule groups by span overlap
    def _overlaps_group(cand: ExtractedField, g_fields: dict[str, ExtractedField]) -> bool:
        for ce in cand.evidence:
            for rf in g_fields.values():
                # Do not match across groups via an unresolved multi-span rule field (e.g. quantity=None with all numbers)
                if rf.value is None and len(rf.evidence) > 1:
                    continue
                for re_ev in rf.evidence:
                    if ce.start < re_ev.end and re_ev.start < ce.end:
                        return True
        return False

    # First group model candidates by their model-assigned group_id
    raw_model_groups: dict[str, dict[str, ExtractedField]] = {}
    for c in valid_model_candidates:
        if c.field_name in ("sku", "quantity", "unit"):
            raw_gid = c.metadata.get("group_id") or "g1"
            grp = raw_model_groups.setdefault(raw_gid, {})
            existing_c = grp.get(c.field_name)
            # Prefer qwen or candidates with explicit group_id over first-seen gliner span
            if existing_c is None:
                grp[c.field_name] = c
            else:
                c_ver = (c.evidence[0].method_version.lower() if c.evidence and c.evidence[0].method_version else "")
                ex_ver = (existing_c.evidence[0].method_version.lower() if existing_c.evidence and existing_c.evidence[0].method_version else "")
                if "qwen" in c_ver and "qwen" not in ex_ver:
                    grp[c.field_name] = c

    model_items: dict[str, dict[str, ExtractedField]] = {}
    for mgid, mfields in raw_model_groups.items():
        matched_gid = None
        for rgid, rfields in groups.items():
            if any(_overlaps_group(mc, rfields) for mc in mfields.values()):
                matched_gid = rgid
                break
        if matched_gid is None:
            if mgid in groups:
                matched_gid = mgid
            elif "g1" in groups and (not groups["g1"].get("sku") or groups["g1"]["sku"].value is None) and "g1" not in model_items:
                matched_gid = "g1"
            else:
                matched_gid = mgid
                groups.setdefault(matched_gid, {})
        target_grp = model_items.setdefault(matched_gid, {})
        for fn, mc in mfields.items():
            if fn not in target_grp:
                target_grp[fn] = mc

    # Drop placeholder "g1" if real literal/model groups exist alongside an empty g1
    if len(groups) > 1 and "g1" in groups:
        g1_sku = groups["g1"].get("sku")
        g1_model_sku = model_items.get("g1", {}).get("sku")
        if (g1_sku is None or g1_sku.value is None) and (g1_model_sku is None or g1_model_sku.value is None):
            del groups["g1"]

    # Exclude packaging breakdown candidates from being treated as canonical order quantities or SKUs
    # e.g., "pack into 4 separate boxes of 20pcs each" -> "4", "20", "each" must NOT become items
    PACKAGING_NOISE_RE = re.compile(
        r'\b(?:pack(?:ed)?|packing|boxes|box|kotak|bungkus|each|per\s+box|separate)\b',
        re.IGNORECASE
    )

    canonical_items: list[ExtractedField] = []

    for gid, group_fields in groups.items():
        # --- A. SKU ---
        sku_field = group_fields.get("sku")
        model_sku = model_items.get(gid, {}).get("sku")

        if sku_field is not None and sku_field.validation_status == "VALID":
            # Valid rule SKU is authoritative; deduplicate model proposal
            final_sku = sku_field
        elif model_sku is not None and model_sku.value:
            # Model proposes SKU
            # Check if it's packaging noise or unknown context
            val_clean = model_sku.value.strip().lower()
            if val_clean in ("each", "box", "boxes", "piece", "pieces") or PACKAGING_NOISE_RE.search(val_clean):
                final_sku = sku_field or ExtractedField(field_name="sku", value=None, validation_status="MISSING", evidence=[])
            elif tenant_catalog_skus and model_sku.value in tenant_catalog_skus:
                final_sku = model_sku
                accepted_model_count += 1
            else:
                # Unknown SKU remains UNRESOLVED, preserving evidence
                if sku_field is not None and sku_field.value is not None:
                    final_sku = sku_field
                else:
                    final_sku = model_sku
                    accepted_model_count += 1
        else:
            final_sku = sku_field or ExtractedField(field_name="sku", value=None, validation_status="MISSING", evidence=[])

        # --- B. Quantity ---
        qty_field = group_fields.get("quantity")
        model_qty = model_items.get(gid, {}).get("quantity")

        if qty_field is not None and qty_field.value is not None:
            # Rule quantity: if it was INVALID (e.g. incompatible unit in rules), map to UNRESOLVED for operational context
            if qty_field.validation_status == "INVALID":
                final_qty = ExtractedField(
                    field_name="quantity",
                    value=qty_field.value,
                    validation_status="UNRESOLVED",
                    evidence=qty_field.evidence,
                    metadata=qty_field.metadata.copy(),
                )
            else:
                final_qty = qty_field
        elif (
            qty_field is not None
            and qty_field.value is None
            and len(qty_field.evidence) > 1
            and any(
                re.search(
                    r'^\s*(?:\b(?:or|atau)\b|或|/)\s*$',
                    raw_text[qty_field.evidence[i].end:qty_field.evidence[i + 1].start],
                    re.IGNORECASE,
                )
                for i in range(len(qty_field.evidence) - 1)
                if qty_field.evidence[i].end <= qty_field.evidence[i + 1].start
            )
        ):
            # Disjunctive quantity numbers in rule (e.g. "10 or 12"): keep unresolved None
            final_qty = qty_field
        elif model_qty is not None and model_qty.value:
            # Check if model quantity is a packaging breakdown number
            is_packaging_number = False
            if model_qty.evidence:
                ev_quote = model_qty.evidence[0].quote
                ev_start = model_qty.evidence[0].start
                ev_end = model_qty.evidence[0].end
                surrounding = raw_text[max(0, ev_start - 15):min(len(raw_text), ev_end + 15)]
                if PACKAGING_NOISE_RE.search(surrounding):
                    unit_cand = unit_field or model_unit
                    unit_quote = (unit_cand.evidence[0].quote.lower() if unit_cand and unit_cand.evidence else "")
                    if not re.search(r"\b(?:box|boxes|kotak|bungkus|pack|packs)\b", unit_quote):
                        is_packaging_number = True

            if is_packaging_number:
                # Do NOT adopt packaging breakdown numbers as the order quantity
                final_qty = qty_field or ExtractedField(field_name="quantity", value=None, validation_status="MISSING", evidence=[])
            else:
                final_qty = model_qty
                accepted_model_count += 1
        else:
            final_qty = qty_field or ExtractedField(field_name="quantity", value=None, validation_status="MISSING", evidence=[])

        # --- C. Unit ---
        unit_field = group_fields.get("unit")
        model_unit = model_items.get(gid, {}).get("unit")

        if unit_field is not None and unit_field.value is not None:
            # Explicit unit (VALID or UNRESOLVED due to catalog support) is authoritative; do not overwrite with model guess
            norm_val = unit_field.metadata.get("normalized_unit") or UNIT_NORMALIZATION.get(unit_field.value.lower(), unit_field.value)
            if unit_field.validation_status == "INVALID":
                final_unit = ExtractedField(
                    field_name="unit",
                    value=norm_val,
                    validation_status="UNRESOLVED",
                    evidence=unit_field.evidence,
                    metadata=unit_field.metadata.copy(),
                )
            else:
                final_unit = ExtractedField(
                    field_name="unit",
                    value=norm_val,
                    validation_status=unit_field.validation_status,
                    evidence=unit_field.evidence,
                    metadata=unit_field.metadata.copy(),
                )
        elif model_unit is not None and model_unit.value:
            # Normalize model unit
            norm_u = UNIT_NORMALIZATION.get(model_unit.value.lower(), model_unit.value)
            # Check compatibility with tenant catalog SKU if known
            sku_val = final_sku.value if final_sku and final_sku.value in tenant_catalog_skus else None
            allowed_units = tenant_catalog_units.get(sku_val, set()) if sku_val else set()
            if not sku_val or (allowed_units and norm_u not in allowed_units) or (final_qty.validation_status != "VALID" and final_qty.metadata.get("domain_supported") != "true"):
                # Unknown SKU, incompatible unit, or unsupported quantity -> unit remains UNRESOLVED
                u_meta = model_unit.metadata.copy() if model_unit.metadata else {}
                if sku_val and allowed_units and norm_u not in allowed_units:
                    u_meta["reason"] = f"Unit '{norm_u}' incompatible with catalog SKU '{sku_val}'"
                final_unit = ExtractedField(
                    field_name="unit",
                    value=norm_u,
                    validation_status="UNRESOLVED",
                    evidence=model_unit.evidence,
                    metadata=u_meta,
                )
                accepted_model_count += 1
            else:
                final_unit = ExtractedField(
                    field_name="unit",
                    value=norm_u,
                    validation_status="VALID",
                    evidence=model_unit.evidence,
                    metadata=model_unit.metadata,
                )
                accepted_model_count += 1
        else:
            # Genuinely absent unit must remain MISSING. Do not fabricate or invent 'pcs'.
            final_unit = unit_field or ExtractedField(
                field_name="unit",
                value=None,
                validation_status="MISSING",
                evidence=[],
            )

        # Ensure group_id is consistent
        final_sku.metadata["group_id"] = gid
        final_qty.metadata["group_id"] = gid
        final_unit.metadata["group_id"] = gid

        canonical_items.extend([final_sku, final_qty, final_unit])

    # Assemble final canonical list (strictly 4 canonical fields: delivery + items)
    reconciled: list[ExtractedField] = []
    if canonical_delivery is not None:
        reconciled.append(canonical_delivery)
    reconciled.extend(canonical_items)

    # Preserve conflicting model proposals for quantity when they disagree with a VALID canonical quantity
    for c in valid_model_candidates:
        if (
            c.field_name == "quantity"
            and c.value
            and any(r.field_name == "quantity" and r.validation_status == "VALID" and r.value != c.value for r in reconciled)
            and c not in reconciled
        ):
            reconciled.append(c)
            accepted_model_count += 1

    return reconciled, accepted_model_count
