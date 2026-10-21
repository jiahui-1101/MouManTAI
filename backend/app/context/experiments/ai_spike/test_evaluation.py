import copy
import json

import pytest
from jsonschema import ValidationError

from .evaluation import baseline, evidence_gate, fixtures, gold, parse_output, score


def test_frozen_data_has_distinct_splits_and_valid_evidence():
    data = fixtures()
    assert data["business_timezone"] == "Asia/Kuala_Lumpur"
    assert len({c["id"] for c in data["cases"]}) == len(data["cases"])
    assert {c["split"] for c in data["cases"]} == {"development", "heldout"}
    for case in data["cases"]:
        assert gold(case) is not None
        assert all(m["timestamp"] == "2026-10-20T10:00:00+08:00" for m in case["messages"])


@pytest.mark.parametrize("raw", ["oops", '```json\n{"fields": []}\n```', '{"fields": null}'])
def test_malformed_output(raw):
    with pytest.raises((ValueError, ValidationError)):
        parse_output(raw, [])


@pytest.mark.parametrize("item", [
    {"field": "product", "message_id": "absent", "quote": "bread"},
    {"field": "product", "message_id": "m1", "quote": "invented"},
    {"field": "product", "message_id": "m1", "quote": "bread", "approved": True},
    {"field": "identity_verified", "message_id": "m1", "quote": "bread"},
    {"field": "product", "message_id": "m1"},
])
def test_evidence_and_authority_rejected(item):
    with pytest.raises((ValueError, ValidationError)):
        evidence_gate({"fields": [item]}, [{"id": "m1", "text": "bread"}])


def test_unicode_codepoint_offsets_and_ambiguous_quote():
    result = parse_output('{"fields":[{"field":"product","message_id":"m1","quote":"面包"}]}',
                          [{"id": "m1", "text": "🍞要面包"}])
    assert (result[0]["start"], result[0]["end"]) == (2, 4)
    with pytest.raises(ValueError):
        evidence_gate({"fields": [{"field": "product", "message_id": "m1", "quote": "面包"}]},
                      [{"id": "m1", "text": "面包 面包"}])


def test_valid_evidence_is_not_semantic_correctness():
    case = copy.deepcopy(fixtures()["cases"][0])
    wrong = gold(case)
    wrong[0]["field"] = "delivery"
    # All quotes can be genuine while the field labels are wrong.
    assert score([case], [{"id": case["id"], "fields": wrong}])["all"]["fp"] > 0


def test_perfect_and_failed_scoring():
    cases = fixtures()["cases"]
    result = score(cases, [{"id": c["id"], "fields": gold(c)} for c in cases])
    assert result["all"]["precision"] == result["all"]["recall"] == 1
    failed = score(cases, [{"id": c["id"], "fields": []} for c in cases])
    assert failed["all"]["recall"] == 0
    assert baseline(cases[0]["messages"])
