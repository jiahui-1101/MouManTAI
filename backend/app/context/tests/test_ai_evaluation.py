from collections import Counter

import pytest

from app.context.ai.protocol import Observation
from app.context.experiments.ai_gpu.evaluation import dataset, deterministic, digest, score


def test_new_splits_and_labels_have_exact_source_evidence():
    data = dataset()
    assert Counter(c["split"] for c in data["cases"]) == {"development": 8, "heldout": 24}
    heldout = [c for c in data["cases"] if c["split"] == "heldout"]
    assert Counter(c["language"] for c in heldout) == {"en": 6, "zh": 6, "ms": 6, "mixed": 6}
    assert len({c["id"] for c in data["cases"]}) == 32
    for case in data["cases"]:
        sources = {m["id"]: m["text"] for m in case["messages"]}
        for item in case["gold"]:
            observation = Observation.model_validate(item)
            assert sources[observation.message_id][observation.start:observation.end] == observation.quote
    assert len(digest()) == 64


def test_scoring_identity_control_not_real_model_quality():
    cases = dataset()["cases"]
    records = [{"id": c["id"], "fields": c["gold"], "rule_delivery_status": c["expected_delivery_status"]} for c in cases]
    result = score(cases, records)
    assert result["fields"]["all"]["precision"] == result["fields"]["all"]["recall"] == 1
    assert result["fields"]["associations"]["fp"] == 0
    with pytest.raises(ValueError):
        score(cases, records[:-1])


def test_rule_baseline_is_measured_without_gold_or_remote_endpoint():
    cases = [c for c in dataset()["cases"] if c["split"] == "development"]
    records = [deterministic(c) for c in cases]
    result = score(cases, records)
    assert result["cases"] == 8 and result["fields"]["all"]["fn"] > 0
    assert any(r["selective_qwen"] for r in records)
