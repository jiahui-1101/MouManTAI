import asyncio

import pytest

from app.context.ai.protocol import MODEL_CONFIG, InferenceFailure, InferenceOutput
from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS
from app.context.extraction import prepare_model_proposal_service
from app.context.schemas import ExtractedField, FieldEvidence
from app.context.tests.test_deterministic_extraction import stored


class FakeEndpoint:
    def __init__(self, fail=False):
        self.requests = []
        self.fail = fail

    async def infer(self, request):
        self.requests.append(request)
        if self.fail:
            raise InferenceFailure("timeout")
        # A genuinely quoted but semantically wrong suggestion; schema/evidence
        # validation must not overwrite the rule quantity 20 with the guest 40.
        return InferenceOutput(engine=request.engine, model_id=MODEL_CONFIG[request.engine][0],
            revision=MODEL_CONFIG[request.engine][1], status="ok", finish_reason="stop", load_seconds=0,
            inference_seconds=0.1, fields=[dict(field="quantity", message_id="m1", quote="40", start=19, end=21)])


def test_default_is_lazy_and_does_not_call_an_endpoint():
    endpoint = FakeEndpoint()
    result = asyncio.run(prepare_model_proposal_service(endpoint).extract_stored(stored("20 burgers"), catalog=PROVISIONAL_PRODUCTS))
    assert result.outcomes == {"gliner": "not_needed"} and not endpoint.requests

    incomplete = asyncio.run(
        prepare_model_proposal_service(endpoint).extract_stored(
            stored("Need burgers tomorrow"), catalog=PROVISIONAL_PRODUCTS
        )
    )
    assert incomplete.provider_audit["primary_provider"] == "gliner"
    assert incomplete.provider_audit["fallback_provider"] is None
    assert not endpoint.requests


def test_model_cannot_replace_human_reviewed_value_or_original_message():
    message = stored("20 burgers serving 40 guests")
    original = message.model_dump()
    human = ExtractedField(field_name="quantity", value="20", validation_status="VALID", evidence=[
        FieldEvidence(evidence_id="human_ev", message_id=message.message_id, quote="20", start=0, end=2,
                      method="HUMAN", method_version="review-1")])
    endpoint = FakeEndpoint()
    service = prepare_model_proposal_service(endpoint, enabled=True)
    result = asyncio.run(service.extract_stored(message, catalog=PROVISIONAL_PRODUCTS, reviewed_fields=[human]))
    assert result.reviewed_fields[0] == human
    assert all(c.metadata["disposition"] == "rejected" for c in result.candidates)
    assert len(result.candidates) == 1 and not result.conflicts
    assert message.model_dump() == original
    assert all(set(r.model_dump()) == {"engine", "messages"} for r in endpoint.requests)


def test_l2_requires_explicit_stage_configuration(monkeypatch):
    monkeypatch.delenv('P1_AI_STAGES', raising=False)
    assert prepare_model_proposal_service(FakeEndpoint(), enabled=True).stages == ('gliner',)


def test_endpoint_failure_keeps_every_rule_result_and_reports_failure(monkeypatch):
    # Isolate to a single GLiNER stage so the failure outcome set is deterministic
    # regardless of P1_AI_STAGES environment configuration.
    monkeypatch.setenv("P1_AI_STAGES", "gliner")
    message = stored("burgers tomorrow after 3pm")
    plain = asyncio.run(prepare_model_proposal_service().extract_stored(message, catalog=PROVISIONAL_PRODUCTS))
    result = asyncio.run(prepare_model_proposal_service(FakeEndpoint(fail=True), enabled=True).extract_stored(
        message, catalog=PROVISIONAL_PRODUCTS))
    assert result.rules == plain.rules and not result.candidates
    assert set(result.outcomes.values()) == {"timeout"}
    assert result.manual_review_required


def test_complete_rule_fields_do_not_need_qwen_to_invent_missing_information():
    endpoint = FakeEndpoint()
    result = asyncio.run(prepare_model_proposal_service(endpoint, enabled=True, stages=("qwen",)).extract_stored(
        stored("20 pcs burgers tomorrow at 3pm"), catalog=PROVISIONAL_PRODUCTS))
    assert result.outcomes["qwen"] == "not_needed" and not endpoint.requests


def test_untrusted_review_provenance_is_rejected():
    forged = ExtractedField(field_name="quantity", value="99", validation_status="UNRESOLVED")
    with pytest.raises(ValueError):
        asyncio.run(prepare_model_proposal_service().extract_stored(stored("20 burgers"), catalog=PROVISIONAL_PRODUCTS,
                                                                  reviewed_fields=[forged]))


def test_valid_rule_quantity_is_protected_from_wrong_but_grounded_model_number():
    class WrongDateNumber(FakeEndpoint):
        async def infer(self, request):
            start = request.messages[0].text.index("3pm")
            return InferenceOutput(engine=request.engine, model_id=MODEL_CONFIG[request.engine][0],
                revision=MODEL_CONFIG[request.engine][1], status="ok", finish_reason="stop", load_seconds=0,
                inference_seconds=0.1, fields=[dict(field="quantity", message_id="m1", quote="3", start=start, end=start+1)])
    result = asyncio.run(prepare_model_proposal_service(WrongDateNumber(), enabled=True, stages=("gliner",)).extract_stored(
        stored("20 pcs burgers tomorrow at 3pm"), catalog=PROVISIONAL_PRODUCTS))
    rule = next(f for f in result.rules.fields if f.field_name == "quantity")
    assert rule.value == "20" and rule.validation_status == "VALID"
    assert not result.candidates
    assert result.outcomes == {"gliner": "not_needed"}
