from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core import models as _core_models  # noqa: F401 - register ORM tables for Alembic metadata
from app.communication import models as _communication_models  # noqa: F401 - register P4 ORM tables
from app.feasibility import persisted_sources as _p2_sources  # noqa: F401 - register P2 ORM tables
from app.recovery import durable_plans as _p3_plans  # noqa: F401 - register P3 plan tables
from app.core import manager_approval as _manager_approval  # noqa: F401 - register Core approval table
from app.recovery import durable_actions as _p3_actions  # noqa: F401 - register P3 action tables
from app.db.base import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
