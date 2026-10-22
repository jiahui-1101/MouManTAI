from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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
    db_url = os.environ.get("TEST_DATABASE_URL")
    if db_url:
        import socket
        resolved_url = db_url
        if resolved_url.startswith("postgresql://"):
            resolved_url = resolved_url.replace("postgresql://", "postgresql+psycopg://", 1)
        if ":5432/" in resolved_url:
            sock = socket.socket()
            sock.settimeout(0.2)
            try:
                res = sock.connect_ex(("127.0.0.1", 5432))
            except Exception:
                res = 1
            finally:
                sock.close()
            if res != 0:
                resolved_url = resolved_url.replace(":5432/", ":5433/")
        engine = create_engine(resolved_url, pool_pre_ping=True)
        Base.metadata.create_all(engine)
        try:
            yield engine
        finally:
            with engine.begin() as conn:
                try:
                    conn.execute(text("TRUNCATE TABLE recovery_case_triggers, recovery_cases CASCADE"))
                except Exception:
                    pass
                for table in reversed(Base.metadata.sorted_tables):
                    conn.execute(table.delete())
    else:
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
