"""Optional real CPU diagnostic on historical DEVELOPMENT examples only."""
import argparse
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve prior output; use a fresh path")
    # Existing public files only. The diagnostic never provisions or calls a GPU.
    os.environ["HF_HUB_OFFLINE"] = "1"
    import torch
    from gliner.data_processing.tokenizer import WhitespaceTokenSplitter
    from ...ai.worker import load_gliner, LABELS, THRESHOLD, OffsetSplitter
    from ..ai_spike.evaluation import fixtures, score

    cases = [c for c in fixtures()["cases"] if c["split"] == "development"]
    torch.set_num_threads(4)
    torch.manual_seed(42)
    start = time.perf_counter()
    model = load_gliner(args.cache, "cpu")
    data = {"scope": "historical-development-only; CPU; not GPU acceptance", "load_seconds": time.perf_counter()-start, "runs": []}
    for name, splitter, threshold in (("historical-default", WhitespaceTokenSplitter(), 0.5),
                                      ("cjk-char-v1", OffsetSplitter(), THRESHOLD)):
        model.data_processor.words_splitter = splitter
        records = []
        for case in cases:
            before = time.perf_counter()
            entities = []
            with torch.inference_mode():
                for source in case["messages"]:
                    entities.extend({"message_id": source["id"], **e} for e in
                        model.predict_entities(source["text"], list(LABELS), threshold=threshold))
            fields = [{"field": LABELS[e["label"]], "message_id": e["message_id"], "quote": e["text"],
                       "start": e["start"], "end": e["end"]} for e in entities]
            records.append({"id": case["id"], "fields": fields, "raw_entities": entities, "inference_seconds": time.perf_counter()-before})
        data["runs"].append({"configuration": name, "threshold": threshold, "scores": score(cases, records), "records": records})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "load_seconds": data["load_seconds"],
                      "scores": [{"configuration": r["configuration"], "all": r["scores"]["all"]} for r in data["runs"]]}, indent=2))


if __name__ == "__main__":
    main()
