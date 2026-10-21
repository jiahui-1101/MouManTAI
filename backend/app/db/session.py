from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    try:
        import psycopg  # noqa: F401
        DATABASE_URL = "postgresql+psycopg://moumantai:moumantai@localhost:5433/moumantai"
    except ImportError:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        DATABASE_URL = f"sqlite:///{os.path.join(repo_root, 'test_live.db').replace(os.sep, '/')}"

engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
