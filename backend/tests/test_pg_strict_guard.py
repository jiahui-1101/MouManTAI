"""F12 Guard Tests and PostgreSQL Strict Mode Assertions.

Verifies:
1. When REQUIRE_POSTGRES=1 is set, app.db.session.engine binds to PostgreSQL dialect (F12).
2. When REQUIRE_POSTGRES=1 is set, client request session dependency binds to PostgreSQL dialect (F12).
3. When REQUIRE_POSTGRES is not set (local default), PostgreSQL-specific tests skip cleanly without failing SQLite suite.
"""

from __future__ import annotations

import os
import pytest

from app.core.dependencies import get_db
from app.db.session import engine as app_db_engine
from app.main import app


@pytest.mark.postgres
def test_f12_guard_dialect_is_postgresql_under_require_postgres(client) -> None:
    """F12 Guard: Assert BOTH app.db.session.engine and client request session use postgresql."""
    require_pg = os.getenv("REQUIRE_POSTGRES", "0").lower() in ("1", "true", "yes")
    if not require_pg:
        pytest.skip("F12 guard active only when REQUIRE_POSTGRES=1")

    # 1. Assert app.db.session.engine dialect is postgresql
    assert app_db_engine.dialect.name == "postgresql", (
        f"F12 Violation: app.db.session.engine dialect is '{app_db_engine.dialect.name}', expected 'postgresql'"
    )

    # 2. Assert session injected into client requests has dialect postgresql
    override_fn = app.dependency_overrides.get(get_db)
    assert override_fn is not None, "Expected get_db dependency override in client fixture"
    db_gen = override_fn()
    try:
        session = next(db_gen)
        bind = session.get_bind()
        assert bind.dialect.name == "postgresql", (
            f"F12 Violation: client injected session dialect is '{bind.dialect.name}', expected 'postgresql'"
        )
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    # 3. Assert client request executes cleanly
    response = client.get("/health")
    assert response.status_code == 200
