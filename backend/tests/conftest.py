from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure pure-python SQLAlchemy implementation on environments with AppControl/WDAC
os.environ.setdefault("DISABLE_SQLALCHEMY_CEXT", "1")
# Ensure test default is in-memory SQLite unless explicitly overridden
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.core.dependencies import get_db
from app.db.base import Base
from app.main import app


@pytest.fixture
def test_engine():
    # Portable suite only. Migrated PostgreSQL coverage has a separate opt-in
    # fixture that never creates tables or silently switches database engines.
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)


@pytest.fixture
def session(test_engine) -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(test_engine) -> Generator[TestClient, None, None]:
    session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
