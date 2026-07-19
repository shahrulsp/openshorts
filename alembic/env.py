"""Alembic environment (async) for cloud- or SaaS-mode migrations."""
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from saas.config import load_saas_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = load_saas_settings()

if settings.enabled:
    from saas.database import Base

    try:
        import saas.models  # noqa: F401
    except ModuleNotFoundError as exc:
        if exc.name != "saas.models":
            raise
    db_url = settings.database_url or os.environ.get("DATABASE_URL", "")
else:
    from cloud.database import Base
    import cloud.models  # noqa: F401

    db_url = os.environ.get("DATABASE_URL", "")

if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
