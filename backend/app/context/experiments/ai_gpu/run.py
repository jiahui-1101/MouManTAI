"""Reproducible evaluation preparation. Network execution requires approval flag.

Example baseline (no endpoint): python -m app.context.experiments.ai_gpu.run
  --split heldout --output .local/ai-gpu/rules.json
Paid runs additionally require --approved-resource and credentials in environment.
That flag records an operator action; it does not grant human resource approval.
"""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import statistics
import math

from pydantic import ValidationError

from ...ai.endpoint import EndpointAdapter, EndpointConfig
from ...ai.protocol import InferenceFailure
from ...ai.worker import RawAnswer
from .evaluation import dataset, deterministic, digest, input_for, score, span_key


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merged(*groups):
    unique = {}
    for fields in groups:
        for field in fields:
            key = span_key(field)
            if key not in unique:
                unique[key] = field
            elif unique[key].get("group_id") is None and field.get("group_id"):
                unique[key] = {**unique[key], "group_id": field["group_id"]}
    return list(unique.values())


def diagnostics(observed, case):
    if not observed:
        return {"model_observation_missing": 1}
    result = {"raw_fields": 0, "unsupported_source_fields": 0, "invalid_json_or_schema_answers": 0,
              "evidence_rejected_answers": 0, "truncated_answers": int(observed["finish_reason"] == "length")}
    sources = {m["id"]: m["text"] for m in case["messages"]}
    if observed["engine"] == "qwen":
        try:
            raw = RawAnswer.model_validate_json(observed["raw_output"])
            rows = [f.model_dump() for f in raw.fields]
        except ValidationError:
            result["invalid_json_or_schema_answers"] = 1
            return result
    else:
        rows = observed["fields"]
    result["raw_fields"] = len(rows)
    for item in rows:
        source, quote = sources.get(item["message_id"]), item["quote"]
        start, end = item.get("start"), item.get("end")
        supported = source is not None and ((start is None and end is None and source.count(quote) == 1)
            or (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(source) and source[start:end] == quote))
        result["unsupported_source_fields"] += not supported
    result["evidence_rejected_answers"] = int(result["unsupported_source_fields"] > 0)
    return result


async def evaluate(split, *, endpoint=None, output=None, max_seconds=2700, max_requests=96):
    cases = [c for c in dataset()["cases"] if c["split"] == split]
    data = {"dataset_sha256": digest(), "split": split, "scope": "baseline_only" if endpoint is None else "approved_endpoint_evaluation",
            "criteria_sha256": hashlib.sha256(Path(__file__).with_name("acceptance.json").read_bytes()).hexdigest(),
            "methods": {"rules": []}, "calls": [], "actual_provider_cost_usd": None,
            "cost_note": "ExecutionTime and client elapsed time are not a provider invoice. Reconcile with provider billing."}
    if endpoint:
        data["methods"].update(gliner_assisted=[], selective_qwen=[], combined=[])
    started = time.monotonic()
    for case in cases:
        rules = deterministic(case)
        data["methods"]["rules"].append(rules)
        if endpoint:
            proposals = {}
            for engine in ("gliner", "qwen"):
                if engine == "qwen" and not rules["selective_qwen"]:
                    proposals[engine] = []
                    continue
                if len(data["calls"]) >= max_requests or time.monotonic()-started >= max_seconds - 180:
                    proposals[engine] = []
                    data["calls"].append({"case": case["id"], "engine": engine, "status": "client_budget_exhausted"})
                    continue
                request = input_for(case, engine)
                before = time.monotonic()
                status, fields = "ok", []
                try:
                    answer = await endpoint.infer(request)
                    fields = [f.model_dump() for f in answer.fields]
                except InferenceFailure as error:
                    status = str(error)
                proposals[engine] = fields
                observed = endpoint.last_output.model_dump() if endpoint.last_output else None
                data["calls"].append({"case": case["id"], "engine": engine, "status": status,
                    "wall_seconds": time.monotonic()-before, "observed": observed, "provider": endpoint.last_provider_metrics,
                    "diagnostics": diagnostics(observed, case)})
            for method, fields in (
                ("gliner_assisted", merged(rules["fields"], proposals["gliner"])),
                ("selective_qwen", merged(rules["fields"], proposals["qwen"])),
                ("combined", merged(rules["fields"], proposals["gliner"], proposals["qwen"]))):
                data["methods"][method].append({**rules, "fields": fields})
        if output:
            save(output, data)
    data["scores"] = {method: score(cases, records) for method, records in data["methods"].items()}
    data["call_outcomes"] = dict(Counter(call["status"] for call in data["calls"]))
    data["by_language"] = {language: {
        method: score([c for c in cases if c["language"] == language],
                      [r for r in records if r["id"] in {c["id"] for c in cases if c["language"] == language}])
        for method, records in data["methods"].items()} for language in sorted({c["language"] for c in cases})}
    data["model_diagnostics"] = {}
    for engine in ("gliner", "qwen"):
        calls = [call for call in data["calls"] if call["engine"] == engine]
        if not calls:
            continue
        totals = Counter()
        for call in calls:
            totals.update(call.get("diagnostics", {}))
        warm = sorted(call["wall_seconds"] for call in calls if call.get("observed") and call["observed"]["load_seconds"] == 0)
        data["model_diagnostics"][engine] = {"calls": len(calls), "totals": dict(totals),
            "unsupported_source_field_rate": totals["unsupported_source_fields"]/totals["raw_fields"] if totals["raw_fields"] else None,
            "invalid_schema_answer_rate": totals["invalid_json_or_schema_answers"]/len(calls),
            "evidence_rejected_answer_rate": totals["evidence_rejected_answers"]/len(calls),
            "warm_median_seconds": statistics.median(warm) if warm else None,
            "warm_p95_seconds": warm[math.ceil(len(warm)*0.95)-1] if warm else None,
            "cold_load_seconds": [call["observed"]["load_seconds"] for call in calls if call.get("observed") and call["observed"]["load_seconds"] > 0]}
    data["elapsed_seconds"] = time.monotonic()-started
    data["interpretation"] = "Candidate retrieval metrics; conflicts/provenance retained, no automatic model promotion. Association groups scored independently. Rejected answers contribute no model fields."
    if output:
        save(output, data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["development", "heldout"], default="development")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approved-resource", action="store_true", help="Only after explicit human provider/GPU/budget/shutdown approval")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path; preserve prior observations")
    endpoint = EndpointAdapter(EndpointConfig.from_env()) if args.approved_resource else None
    result = asyncio.run(evaluate(args.split, endpoint=endpoint, output=args.output))
    print(json.dumps({"scope": result["scope"], "scores": result["scores"], "outcomes": result["call_outcomes"]}, indent=2))


if __name__ == "__main__":
    main()
