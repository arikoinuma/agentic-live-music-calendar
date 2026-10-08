"""Alembic's entry point: how migrations find the database and the models.

WHAT THIS FILE IS
  Alembic (the schema-migration tool) runs this file every time you run
  `alembic upgrade head`, `make migrate`, `make migration m="..."`, etc. It
  answers three questions: which database to connect to, which models to
  compare it against (for autogenerate), and how to run the migration
  scripts in migrations/versions/ against that connection.

TWO WAYS IT GETS A CONNECTION
  1. Normal use (the command line): it builds its own async engine from
     DATABASE_URL (app/config.py) and runs the migrations on it.
  2. Injected (the test suite): the caller passes an already-open
     connection in `config.attributes["connection"]` and this file uses it
     as is. That lets tests run migrations against the throwaway
     `calendar_test` database; see app/testing/db.py for why that matters.

Based on Alembic's async template; the A1 additions are the models import,
`target_metadata`, `COMPARE_OPTS`, and the injected-connection path.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing the models package is what registers every table on
# Base.metadata. It is imported for that side effect alone, which is why it
# needs the noqa: without it `target_metadata` below would be an empty
# MetaData, and autogenerate would cheerfully report "no changes" — or worse,
# propose dropping every table.
import app.db.models  # noqa: F401
from app.config import settings
from app.db.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# A caller may hand us a live connection: `config.attributes["connection"]`.
# The test suite does (app/testing/db.py) so migrations run against
# `calendar_test` rather than whatever DATABASE_URL points at, and without
# `asyncio.run`, which can't be called from inside pytest-asyncio's loop.
# Normal CLI use (`alembic upgrade head`, `make migrate`) never sets it.
injected_connection = config.attributes.get("connection")

if injected_connection is None:
    # Override the placeholder sqlalchemy.url from alembic.ini with the real
    # connection string, sourced from the same Settings class (and therefore
    # the same apps/api/.env) that the FastAPI app itself uses — one source
    # of truth for DATABASE_URL rather than keeping it in sync in two places.
    # Skipped for an injected connection: this line is unconditional in the
    # stock env.py, and it would silently point a test's `downgrade base` at
    # the dev database.
    config.set_main_option("sqlalchemy.url", settings.database_url)

    # Interpret the config file for Python logging. Also skipped when
    # injected: fileConfig() disables every existing logger by default, which
    # would break caplog and the app's own loggers for the rest of a pytest
    # session.
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)

# What autogenerate compares the database against.
target_metadata = Base.metadata

# Not set here: compare_type. Alembic has defaulted it to True since 1.12, so
# column type changes are already detected. compare_server_default is the one
# that is off by default, and it's what makes autogenerate notice a changed
# DEFAULT — which matters here because the defaults are deliberately
# server-side (see app/db/base.py).
COMPARE_OPTS = {"compare_server_default": True}

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **COMPARE_OPTS,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    # Shared by both connection paths: tell Alembic which connection and
    # which models to use, then run the migration scripts inside one
    # transaction (Postgres can roll back schema changes, so a failure
    # leaves the database untouched).
    context.configure(
        connection=connection, target_metadata=target_metadata, **COMPARE_OPTS
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an AsyncEngine
    and associate a connection with the context.

    DATABASE_URL uses the asyncpg driver (see app/config.py), which is
    async-only — hence async_engine_from_config here instead of Alembic's
    default sync engine_from_config, and run_sync() below to run the
    (synchronous) Alembic migration machinery inside that async connection.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations against a live database (as opposed to emitting SQL)."""
    if injected_connection is not None:
        # Already a synchronous connection (the caller used run_sync), so
        # there is no engine to build and no event loop to start.
        do_run_migrations(injected_connection)
        return
    asyncio.run(run_async_migrations())


# Alembic imports this file and expects it to do the work at import time.
# "Offline" mode (`alembic upgrade --sql`) prints SQL instead of running it.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
