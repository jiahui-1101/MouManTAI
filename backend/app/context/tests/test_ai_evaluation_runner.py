import asyncio

from app.context.ai.protocol import InferenceFailure
from app.context.experiments.ai_gpu.run import evaluate, merged, diagnostics


def test_baseline_has_no_remote_calls_and_keeps_every_case():
    result = asyncio.run(evaluate("development"))
    assert result["scope"] == "baseline_only" and not result["calls"]
    assert result["scores"]["rules"]["cases"] == 8
    assert result["actual_provider_cost_usd"] is None


def test_unavailable_endpoint_is_not_a_successful_model_extraction():
    class Unavailable:
        last_output = None
        last_provider_metrics = {}
        async def infer(self, request):
            raise InferenceFailure("unavailable")
    result = asyncio.run(evaluate("development", endpoint=Unavailable()))
    assert result["call_outcomes"]["unavailable"] > 0
    # This equality is explicitly rules fallback, not successful model quality.
    assert result["scores"]["combined"] == result["scores"]["rules"]
    assert all(call["observed"] is None for call in result["calls"])


def test_combination_retains_rule_association_instead_of_overwriting_it():
    item = dict(field="product", message_id="m1", quote="bread", start=0, end=5, group_id="rule_item")
    assert merged([item], [{**item, "group_id": "model_item"}]) == [item]


def test_invalid_authority_output_is_a_schema_failure_not_a_good_empty_answer():
    case = {"messages": [{"id": "m1", "text": "bread"}]}
    observed = dict(engine="qwen", finish_reason="stop", raw_output='{"fields":[{"field":"identity_verified","message_id":"m1","quote":"bread"}]}')
    assert diagnostics(observed, case)["invalid_json_or_schema_answers"] == 1
