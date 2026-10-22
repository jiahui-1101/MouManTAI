import asyncio

import pytest

from app.context.ai.protocol import MODEL_CONFIG, InferenceOutput, Observation
from app.context.ai.service import ModelProposalService
from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS
from app.context.tests.test_deterministic_extraction import stored


@pytest.mark.parametrize("field,quote,value", [("product", "15 burgers", "BURGER"),
    ("quantity", "40 burgers", "40")])
def test_broad_span_normalization_retains_raw_and_precise_evidence(field, quote, value):
    text = "Hello, need " + quote + " tomorrow"
    msg = stored(text)
    obs = Observation(field=field, message_id="m1", quote=quote,
        start=text.index(quote), end=text.index(quote)+len(quote))
    candidate = ModelProposalService._candidate(obs, msg, PROVISIONAL_PRODUCTS, *MODEL_CONFIG["gliner"])
    assert candidate.value == value
    assert candidate.validation_status == "UNRESOLVED"
    assert candidate.metadata["domain_supported"] == "true"
    assert candidate.evidence[0].quote == quote
    assert candidate.evidence[1].quote == ("burgers" if field == "product" else "40")
    for ev in candidate.evidence:
        assert text[ev.start:ev.end] == ev.quote


@pytest.mark.parametrize("text", ["Need 15 burgers tomorrow", "Hello boss, need 40 burgers tomorrow 3pm",
    "20 pcs burgers tomorrow after 3pm", "20 burgers Oct 24"])
def test_metadata_only_uncertainty_never_calls_either_model(text):
    class Endpoint:
        async def infer(self, request):
            pytest.fail("Metadata/date safety uncertainty must not invoke models")
    msg = stored(text)
    msg.raw.business_timezone = None
    result = asyncio.run(ModelProposalService(Endpoint(), enabled=True).extract_stored(msg, catalog=PROVISIONAL_PRODUCTS))
    assert set(result.outcomes.values()) == {"not_needed"}
    assert not result.candidates


@pytest.mark.parametrize("text,quote", [("40 or 50 burgers", "40 or 50 burgers"),
    ("not 40 burgers", "40 burgers"), ("40 burgers, sorry make that 50", "40 burgers")])
def test_quantity_normalization_does_not_salvage_conflicting_request(text, quote):
    obs = Observation(field="quantity", message_id="m1", quote=quote, start=text.index(quote), end=text.index(quote)+len(quote))
    c = ModelProposalService._candidate(obs, stored(text), PROVISIONAL_PRODUCTS, *MODEL_CONFIG["gliner"])
    assert c.metadata["domain_supported"] == "false"
    assert c.validation_status != "VALID"


def test_rejected_span_never_becomes_rule_conflict():
    text = "20 burgers serving 40 guests"
    class Endpoint:
        async def infer(self, request):
            return InferenceOutput(engine=request.engine, model_id=MODEL_CONFIG[request.engine][0],
                revision=MODEL_CONFIG[request.engine][1], status="ok", finish_reason="stop",
                load_seconds=0, inference_seconds=.1, fields=[Observation(field="product", message_id="m1",
                    quote="serving 40", start=text.index("serving"), end=text.index(" guests"))])
    r = asyncio.run(ModelProposalService(Endpoint(), enabled=True, stages=("gliner",)).extract_stored(stored(text), catalog=PROVISIONAL_PRODUCTS))
    assert not r.conflicts
    assert r.candidates[0].metadata["disposition"] == "rejected"
    assert any(f.value == "BURGER" and f.validation_status == "VALID" for f in r.rules.fields)


def test_broad_product_span_equal_to_valid_rule_is_a_duplicate_not_conflict():
    text = '15 burgers serving 40 guests'
    class Endpoint:
        async def infer(self, request):
            return InferenceOutput(engine=request.engine, model_id=MODEL_CONFIG[request.engine][0],
                revision=MODEL_CONFIG[request.engine][1], status='ok', finish_reason='stop', load_seconds=0,
                inference_seconds=.1, fields=[Observation(field='product', message_id='m1', quote='15 burgers', start=0,end=10)])
    result = asyncio.run(ModelProposalService(Endpoint(), enabled=True, stages=('gliner',)).extract_stored(stored(text), catalog=PROVISIONAL_PRODUCTS))
    assert result.candidates[0].value == 'BURGER'
    assert result.candidates[0].metadata['disposition'] == 'duplicate'
    assert result.candidates[0].validation_status == 'UNRESOLVED'
    assert not result.conflicts
