"""REAL MODEL smoke only. Disabled in normal offline backend checks."""
import asyncio
import json
import os

import pytest

from app.context.ai.endpoint import EndpointAdapter, EndpointConfig
from app.context.ai.protocol import InferenceInput


@pytest.mark.skipif(os.environ.get("P1_RUN_REAL_GPU_SMOKE") != "1", reason="Real endpoint smoke is explicit opt-in; inference UNVERIFIED")
@pytest.mark.parametrize("engine", ["gliner", "qwen"])
def test_approved_real_gpu_endpoint(engine):
    endpoint = EndpointAdapter(EndpointConfig.from_env())
    request = InferenceInput(engine=engine, messages=[{"id": "m1", "text": "Please send 10 pcs burgers tomorrow."}])
    result = asyncio.run(endpoint.infer(request))
    assert result.fields and any(field.field == "product" for field in result.fields)
    assert result.inference_seconds > 0
    if engine == 'qwen':
        assert result.runtime_versions.get('parameter_device', '').startswith('cuda')
        assert result.gpu_name and result.gpu_name != 'CPU'
    print(json.dumps({'hardware_evidence': 'remote reported, not independent attestation',
                      'response': result.model_dump(mode='json')}, ensure_ascii=False))
