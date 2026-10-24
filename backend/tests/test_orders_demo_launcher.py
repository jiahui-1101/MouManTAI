from pathlib import Path
import runpy

import pytest


def test_launcher_refuses_original_database_and_other_hosts():
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/run_orders_readonly_demo.py"))
    validate = launcher["validate_target"]
    validate("postgresql+psycopg://test:unused@127.0.0.1:5434/moumantai_demo")
    for url in ("postgresql+psycopg://test:unused@127.0.0.1:5433/moumantai",
                "postgresql+psycopg://test:unused@remote:5434/moumantai_demo",
                "postgresql+psycopg://test:unused@127.0.0.1:5434/moumantai", "sqlite:///:memory:"):
        with pytest.raises(ValueError):
            validate(url)
