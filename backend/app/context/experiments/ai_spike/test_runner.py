import json
import subprocess
import sys
from argparse import Namespace

import pytest

from .evaluation import baseline, fixtures
from . import runner
from .runner import bounded_command, failure_record


def test_timeout_is_bounded_and_records_surviving_rules(tmp_path):
    code, timed_out = bounded_command([sys.executable, "-c", "import time; time.sleep(20)"],
                                    timeout=0.2, log=tmp_path / "worker.log")
    assert timed_out and code != 0
    case = fixtures()["cases"][0]
    record = failure_record(case, "timeout")
    assert record["fields"] == [] and record["manual_review"]
    assert record["fallback_fields"] == baseline(case["messages"])


def test_unavailable_model_returns_nonzero_with_honest_empty_model_result(tmp_path):
    output = tmp_path / "unavailable.json"
    result = subprocess.run([sys.executable, "-m", "backend.app.context.experiments.ai_spike.runner",
                             "--engine", "qwen", "--split", "development", "--cache", str(tmp_path),
                             "--output", str(output), "--timeout", "30"], capture_output=True, timeout=40)
    assert result.returncode == 2
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["load_error"].startswith("FileNotFoundError")
    assert all(r["status"] == "unavailable" and not r["fields"] for r in data["records"])
    assert data["scores"]["all"]["recall"] == 0
    assert data["records"][0]["fallback_fields"]


def test_complete_worker_timeout_backfills_every_case(tmp_path):
    output = tmp_path / "timeout.json"
    result = subprocess.run([sys.executable, "-m", "backend.app.context.experiments.ai_spike.runner",
                             "--engine", "baseline", "--split", "development", "--cache", str(tmp_path),
                             "--output", str(output), "--timeout", "0.001"], capture_output=True, timeout=20)
    assert result.returncode == 2
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["worker_timed_out"]
    assert len(data["records"]) == 4
    assert all(r["status"] == "timeout" for r in data["records"])


@pytest.mark.parametrize("mode,expected", [("malformed", "invalid_output"),
                                            ("no_evidence", "invalid_output"), ("timeout", "timeout")])
def test_worker_rejects_bad_model_answer_and_retains_rules(tmp_path, monkeypatch, mode, expected):
    class FakeQwen:
        def __init__(self, *args):
            pass

        def predict(self, messages, timeout):
            if mode == "timeout":
                raise TimeoutError()
            if mode == "malformed":
                return "not JSON", {}
            return '{"fields":[{"field":"product","message_id":"m1","quote":"hallucinated"}]}', {}

        def close(self):
            pass

    monkeypatch.setattr(runner, "Qwen", FakeQwen)
    output = tmp_path / "worker.json"
    case = fixtures()["cases"][0]
    runner.worker(Namespace(engine="qwen", split="development", cache=tmp_path, output=output,
                            load_timeout=1, case_timeout=1), [case])
    record = json.loads(output.read_text(encoding="utf-8"))["records"][0]
    assert record["status"] == expected
    assert record["manual_review"] and record["fields"] == []
    assert record["fallback_fields"] == baseline(case["messages"])
