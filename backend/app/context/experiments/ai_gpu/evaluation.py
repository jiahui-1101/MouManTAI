"""Frozen literal span and association evaluation. Never imported by P1 service."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from ...ai.protocol import InferenceInput, InferenceOutput, Observation, validate_evidence
from ...deterministic_extraction import ProductAlias, extract_explicit_fields
from ...ingestion_schemas import StoredMessage
from ...schemas import RawMessageEnvelope


def dataset():
    return json.loads(Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8"))


def digest():
    # Canonical content hash survives Windows CRLF checkouts.
    return hashlib.sha256(json.dumps(dataset(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def input_for(case, engine):
    return InferenceInput(engine=engine, messages=[{"id": m["id"], "text": m["text"]} for m in case["messages"]])


def span_key(field):
    return (field["field"], field["message_id"], field["start"], field["end"], field["quote"])


def association_pairs(fields):
    groups = {f.get("group_id") for f in fields} - {None, ""}
    return {(span_key(p), span_key(q)) for group in groups for p in fields for q in fields
            if p.get("group_id") == q.get("group_id") == group and p["field"] == "product" and q["field"] == "quantity"}


def counts(expected, predicted):
    tp, fp, fn = len(expected & predicted), len(predicted - expected), len(expected - predicted)
    return {"tp": tp, "fp": fp, "fn": fn}


def rates(count):
    tp, fp, fn = (count[key] for key in ("tp", "fp", "fn"))
    return {**count, "precision": tp/(tp+fp) if tp+fp else None, "recall": tp/(tp+fn) if tp+fn else None,
            "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None}


def score(cases, records):
    lookup = {r["id"]: r for r in records}
    if set(lookup) != {c["id"] for c in cases} or len(lookup) != len(records):
        raise ValueError("Include exactly one result per case, including failures")
    totals = {name: Counter(tp=0, fp=0, fn=0) for name in ("product", "quantity", "unit", "delivery", "order_reference", "all", "associations")}
    safety_correct = 0
    for case in cases:
        row = lookup[case["id"]]
        predicted = row["fields"]
        # Reject a corrupted evidence artifact independently from model schema.
        request = input_for(case, "qwen")
        sources = {m.id: m.text for m in request.messages}
        for raw in predicted:
            item = Observation.model_validate(raw)
            source = sources.get(item.message_id, "")
            if not 0 <= item.start < item.end <= len(source) or source[item.start:item.end] != item.quote:
                raise ValueError("Evaluation artifact contains unsupported source evidence")
        for name in totals:
            if name == "associations":
                expected_set, predicted_set = association_pairs(case["gold"]), association_pairs(predicted)
            else:
                expected_set = {span_key(f) for f in case["gold"] if name == "all" or f["field"] == name}
                predicted_set = {span_key(f) for f in predicted if name == "all" or f["field"] == name}
            totals[name].update(counts(expected_set, predicted_set))
        safety_correct += row["rule_delivery_status"] == case["expected_delivery_status"]
    return {"fields": {k: rates(v) for k, v in totals.items()}, "rule_delivery_safety_status_matches": safety_correct,
            "cases": len(cases), "note": "Safety status is the deterministic baseline, not a model interpretation accuracy claim"}


def deterministic(case):
    catalog = [ProductAlias(**{**p, "aliases": tuple(p["aliases"])}) for p in dataset()["catalog"]]
    fields, statuses, all_rules = [], [], []
    names = {"sku": "product", "quantity": "quantity", "unit": "unit", "requested_delivery_at": "delivery", "order_id": "order_reference"}
    for source in case["messages"]:
        raw = RawMessageEnvelope(tenant_id=case["tenant_id"], channel="WHATSAPP", provider_message_id=source["id"],
            sender_identity_id="synthetic_unverified", sender_alias="Synthetic", received_at=source["received_at"],
            message_at=source["message_at"], business_timezone=case["business_timezone"], text=source["text"])
        message = StoredMessage(message_id=source["id"], raw=raw, content_sha256=hashlib.sha256(source["text"].encode()).hexdigest(),
            processing_status="RECEIVED", synthetic_provider="SYNTHETIC_WHATSAPP", ingested_at=raw.received_at, updated_at=raw.received_at)
        result = extract_explicit_fields(message, catalog=catalog)
        # Credit the baseline's actual single-item association capability;
        # do not manufacture a zero association baseline for model comparison.
        valid_skus = [f for f in result.fields if f.field_name == "sku" and f.validation_status == "VALID"]
        valid_counts = [f for f in result.fields if f.field_name == "quantity" and f.validation_status == "VALID"]
        group = source["id"] + ":rule_item" if len(valid_skus) == len(valid_counts) == 1 else None
        all_rules.extend(result.fields)
        statuses.extend(f.validation_status for f in result.fields if f.field_name == "requested_delivery_at" and f.validation_status != "MISSING")
        for field in result.fields:
            if field.field_name not in names:
                continue
            fields.extend({"field": names[field.field_name], "message_id": source["id"], "quote": e.quote,
                           "start": e.start, "end": e.end,
                           "group_id": group if field.field_name in {"sku", "quantity", "unit"} and field.validation_status == "VALID" else None}
                          for e in field.evidence)
    status = "MISSING" if not statuses else statuses[0] if len(statuses) == 1 else "UNRESOLVED"
    selective = len(case["messages"]) > 1 or any(f.validation_status in {"UNRESOLVED", "CONFLICT"}
                                               and f.field_name != "order_id" for f in all_rules)
    return {"id": case["id"], "fields": fields, "rule_delivery_status": status, "selective_qwen": selective}
