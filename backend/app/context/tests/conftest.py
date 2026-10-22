import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app.context.dev_database import create_p1_engine
from app.context.postgres_repository import P1Base


@pytest.fixture(autouse=True)
def offline_models_by_default(monkeypatch):
    # dev_app may load a user's live .env during collection. Unit/PG tests must
    # never spend GPU quota unless an explicit live smoke test opts in.
    monkeypatch.setenv("P1_AI_ENABLED", "false")


@pytest.fixture
def pg_engine():
    url = os.environ.get("P1_TEST_DATABASE_URL")
    if not url:
        pytest.skip("P1_TEST_DATABASE_URL is unset; PostgreSQL validation NOT RUN")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Use an isolated PostgreSQL database ending in _test")
    schema = f"p1_test_{uuid4().hex}"
    base = create_p1_engine(url)
    # Shared Core tables used by P1 integration tests must be isolated too;
    # never leave confirmed fixtures in the user's public schema across runs.
    engine = base.execution_options(schema_translate_map={"p1_dev": schema, None: schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        from app.db.base import Base
        Base.metadata.create_all(connection)
        P1Base.metadata.create_all(connection)
    try:
        yield engine
    finally:
        assert schema.startswith("p1_test_") and len(schema) == 40
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        base.dispose()
