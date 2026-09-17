from __future__ import annotations

import logging
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from muzikk.config import get_env_config
from muzikk.models import Base

config = context.config

# Only take over logging when Alembic runs on its own. Muzikk applies migrations
# in process at startup, and alembic.ini would replace the root handlers with a
# console-only one, silencing the log file for the rest of the run.
if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if not config.get_main_option("sqlalchemy.url", default=None):
    config.set_main_option("sqlalchemy.url", get_env_config().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
