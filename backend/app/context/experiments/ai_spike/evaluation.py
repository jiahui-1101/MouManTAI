"""Strict span evaluation and experimental catalog/regex baseline (not P1 rules)."""
from __future__ import annotations

import json
import re
from pathlib import Path

FIELDS = ("product", "quantity", "unit", "delivery")
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["fields"],
    "properties": {"fields": {"type": "array", "maxItems": 40, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["field", "message_id", "quote"], "properties": {
            "field": {"enum": list(FIELDS)},
            "message_id": {"type": "string", "minLength": 1},
            "quote": {"type": "string", "minLength": 1, "maxLength": 300},
        }}}},
}


def fixtures():
    return json.loads(Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8"))


def evidence_gate(payload, messages):
    """Schema then exact unique source quote; field semantics still need evaluation.

    No identity/payment/agreement fields, tools, or authoritative state writes exist.
    Reject the entire model answer on one bad field; never silently salvage it.
    """
    from jsonschema import validate

    validate(payload, SCHEMA)
    sources = {m["id"]: m["text"] for m in messages}
    result = []
    for item in payload["fields"]:
        source = sources.get(item["message_id"])
        quote = item["quote"]
        if source is None or source.count(quote) != 1:
            raise ValueError("Missing, ambiguous or inconsistent source evidence")
        start = source.index(quote)
        span = {**item, "start": start, "end": start + len(quote)}
        if span not in result:
            result.append(span)
    return result


def parse_output(raw, messages):
    # Deliberately no Markdown/JSON repair: measure invalid structured output.
    return evidence_gate(json.loads(raw), messages)


def gold(case):
    return evidence_gate({"fields": case["gold"]}, case["messages"])


PATTERNS = {
    "product": r"\b(?:burgers|buns|bread|milk|nasi lemak)\b|面包|包子",
    "quantity": r"(?<![\w:])\d+(?:\.\d+)?(?![\w:]|\d)",
    "unit": r"\b(?:pcs|boxes|kg|packs|pieces)\b|个|盒|公斤",
    "delivery": r"tomorrow at \d{2}:\d{2}|明天下午三点|esok pukul 3 petang|Friday|明天|esok|tomorrow",
}


def baseline(messages):
    """Intentionally simple experimental baseline, no context or conflict resolver."""
    spans = []
    for message in messages:
        for field, pattern in PATTERNS.items():
            for match in re.finditer(pattern, message["text"], re.IGNORECASE):
                spans.append(dict(field=field, message_id=message["id"],
                                  quote=match.group(), start=match.start(), end=match.end()))
    return spans


def keys(spans, field=None):
    return {(s["field"], s["message_id"], s["start"], s["end"], s["quote"])
            for s in spans if field is None or s["field"] == field}


def score(cases, records):
    """Micro exact-span P/R; failed answers score empty, never drop hard cases."""
    by_id = {r["id"]: r for r in records}
    report = {}
    for field in (*FIELDS, "all"):
        tp = fp = fn = exact = 0
        for case in cases:
            expected = keys(gold(case), None if field == "all" else field)
            predicted = keys(by_id[case["id"]]["fields"], None if field == "all" else field)
            tp += len(expected & predicted)
            fp += len(predicted - expected)
            fn += len(expected - predicted)
            exact += expected == predicted
        report[field] = dict(tp=tp, fp=fp, fn=fn,
                             precision=tp / (tp + fp) if tp + fp else None,
                             recall=tp / (tp + fn) if tp + fn else None,
                             exact_cases=exact, cases=len(cases))
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    data = json.loads(args.result.read_text(encoding="utf-8"))
    cases = [c for c in fixtures()["cases"] if c["split"] == data["split"]]
    print(json.dumps(score(cases, data["records"]), indent=2))


if __name__ == "__main__":
    main()
