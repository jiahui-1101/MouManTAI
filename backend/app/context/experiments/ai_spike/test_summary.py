import hashlib
import json
from pathlib import Path

import pytest

from .evaluation import fixtures
from .summarize import summarize


def test_summary_requires_complete_matching_fixture_evidence(tmp_path):
    path = tmp_path / "run.json"
    path.write_text('{"split":"heldout"}')
    with pytest.raises(ValueError, match="digest"):
        summarize([path])
    path.write_text(json.dumps({"split": "heldout", "records": [], "dataset_sha256": hashlib.sha256(
        Path(__file__).with_name("fixtures.json").read_bytes()).hexdigest()}))
    with pytest.raises(ValueError, match="exactly one"):
        summarize([path])
