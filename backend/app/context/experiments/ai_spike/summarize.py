"""Produce a compact, shareable synthetic-only observation record from local runs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

from .evaluation import fixtures, score


def summarize(paths):
    dataset = fixtures()
    digest = hashlib.sha256(Path(__file__).with_name("fixtures.json").read_bytes()).hexdigest()
    summary = {"dataset_sha256": digest, "business_timezone": dataset["business_timezone"], "runs": []}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("dataset_sha256") != digest:
            raise ValueError("Missing or mismatched fixture digest")
        cases = [c for c in dataset["cases"] if c["split"] == data["split"]]
        records = data["records"]
        scores = score(cases, records)
        timing = [r["inference_seconds"] for r in records if "inference_seconds" in r]
        run = {k: data[k] for k in ("engine", "split", "load_seconds", "resources", "versions", "models", "prompt_sha256")}
        run.update(source_file=path.name, scores=scores,
                   statuses=dict(Counter(r["status"] for r in records)),
                   invalid_json_or_schema=sum(r.get("error_type") in ("JSONDecodeError", "ValidationError") for r in records),
                   evidence_rejections=sum(r.get("error_type") == "ValueError" for r in records),
                   inference_seconds={"median": statistics.median(timing), "min": min(timing), "max": max(timing), "total": sum(timing)},
                   by_language={})
        for language in sorted({c["language"] for c in cases}):
            subset = [c for c in cases if c["language"] == language]
            ids = {c["id"] for c in subset}
            run["by_language"][language] = score(subset, [r for r in records if r["id"] in ids])["all"]
        run["records"] = [{k: r[k] for k in ("id", "status", "fields", "raw", "details", "inference_seconds", "error_type") if k in r} for r in records]
        summary["runs"].append(run)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summarize(args.results), ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
