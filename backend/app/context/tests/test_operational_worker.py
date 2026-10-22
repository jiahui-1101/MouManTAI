import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from app.context.ai.worker import ModelRuntime
from app.context.dev_app import app


def worker():
    path = Path(__file__).resolve().parents[4] / "scripts" / "colab_gpu_worker.py"
    spec = importlib.util.spec_from_file_location("p1_colab_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retired_fake_model_endpoint_fails_honestly():
    with TestClient(app) as client:
        r = client.post('/dev/p1/infer', json={"engine": "gliner", "messages": [{"id": "m1", "text": "15 burgers"}]})
    assert r.status_code == 503
    assert "gpu_name" not in r.json()


def test_colab_reuses_pinned_runtime_and_rejects_unconfigured_auth(monkeypatch):
    m = worker()
    assert isinstance(m.runtime, ModelRuntime)
    monkeypatch.delenv("P1_AI_API_KEY", raising=False)
    with TestClient(m.app) as client:
        r = client.post('/infer', json={"engine": "gliner", "messages": [{"id": "m1", "text": "15 burgers"}]})
    assert r.status_code == 503


def test_worker_failure_is_sanitized_and_unlocks(monkeypatch):
    m = worker()
    monkeypatch.setenv("P1_AI_API_KEY", "test-only-private")
    def fail(request):
        raise RuntimeError("sensitive path and token must not escape")
    monkeypatch.setattr(m.runtime, 'predict', fail)
    with TestClient(m.app) as client:
        body = {"engine": "qwen", "messages": [{"id": "m1", "text": "unknown"}]}
        assert client.post('/infer', json=body).status_code == 401
        for _ in range(2):
            r = client.post('/infer', json=body, headers={"Authorization": "Bearer test-only-private"})
            assert r.status_code == 503
            assert "sensitive" not in r.text
