import json

import pytest

from app.context.ai.protocol import InferenceInput
from app.context.ai.worker import OffsetSplitter, ground_raw_answer


def test_cjk_splitter_preserves_unicode_offsets_and_decimals():
    text = "🍔 要10个面包和2.5 kg rice"
    tokens = list(OffsetSplitter()(text))
    assert [t[0] for t in tokens] == ["🍔", "要", "10", "个", "面", "包", "和", "2.5", "kg", "rice"]
    assert all(text[start:end] == token for token, start, end in tokens)


@pytest.mark.parametrize("field", [
    {"field": "product", "message_id": "m1", "quote": "面包"},
    {"field": "product", "message_id": "m1", "quote": "面包", "start": 1, "end": 3},
])
def test_unique_quote_is_grounded_without_model_arithmetic(field):
    request = InferenceInput(engine="qwen", messages=[{"id": "m1", "text": "🍞面包"}])
    answer = ground_raw_answer(json.dumps({"fields": [field]}), request)
    assert (answer.fields[0].start, answer.fields[0].end) == (1, 3)


@pytest.mark.parametrize("field", [
    {"field": "product", "message_id": "m1", "quote": "bread"},
    {"field": "product", "message_id": "m1", "quote": "invented"},
    {"field": "identity_verified", "message_id": "m1", "quote": "bread", "start": 0, "end": 5},
    {"field": "product", "message_id": "m1", "quote": "bread", "start": 1, "end": 6},
])
def test_repeated_missing_wrong_or_authority_evidence_is_not_repaired(field):
    request = InferenceInput(engine="qwen", messages=[{"id": "m1", "text": "bread bread"}])
    with pytest.raises(ValueError):
        ground_raw_answer(json.dumps({"fields": [field]}), request)


def test_repeated_quote_with_correct_disambiguating_offset_is_allowed():
    request = InferenceInput(engine="qwen", messages=[{"id": "m1", "text": "bread bread"}])
    raw = '{"fields":[{"field":"product","message_id":"m1","quote":"bread","start":6,"end":11}]}'
    assert ground_raw_answer(raw, request).fields[0].start == 6
