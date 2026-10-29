"""The scratch Postgres database the graph-level harness scores in, and the guard in front of it.

What this is: `eval/graph_eval.py` runs the real graph, whose reconcile and commit steps read and write Postgres, and scores the
rows left behind (C5-D2). Those rows must not land in the developer's own database, so the harness creates a database of its own,
`calendar_eval`, migrates it, runs in it, and drops it. This module is the create/migrate/drop trio and the guard that makes
them safe to run.

The guard mirrors the test fixtures' (`app/testing/db.py`): the database name is a CONSTANT, so a typo or a stray environment
variable cannot aim a `DROP DATABASE` at something real, and the host must be this machine. It is a small copy, not an import:
`app/tests/test_no_testing_imports.py` scans `agent_worker/eval/` and forbids importing `app.testing`.

docs/dev/implementations/c5-pipeline-eval-harness.md, Step 5 (C5-D2, C5-M7).
"""

from pathlib import Path

import asyncpg  # type: ignore[import-untyped]  # ships no stubs or py.typed (as in app/testing/db.py)
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# apps/api/ — two levels up from agent_worker/eval/scratch_db.py. Used to find alembic.ini and migrations/ from any cwd.
API_DIR = Path(__file__).resolve().parents[2]

# The ONLY database name this module will ever create, migrate, truncate or drop. A constant, not configurable.
EVAL_DB_NAME = "calendar_eval"
# Hosts that are this machine. (Hostnames are matched exactly; "::1" is IPv6 loopback.)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class UnsafeEvalDatabaseError(RuntimeError):
    """The target database is not the harness's scratch database, or not on this machine."""


def eval_database_url(base_url: str) -> URL:
    """`base_url` (the configured DATABASE_URL) with the database name swapped for the scratch one: same server, same login."""
    return make_url(base_url).set(database=EVAL_DB_NAME)


def check_eval_database_url(url: URL) -> None:
    """Raise `UnsafeEvalDatabaseError` unless it is safe to wipe this database: the name is the constant and the host is local.

    Both checks always apply (unlike the test fixtures, there is no "explicit URL" escape: the harness is a local tool, and a
    hosted server is never a target, per AGENTS.md on reaching hosted databases)."""
    if url.database != EVAL_DB_NAME:
        raise UnsafeEvalDatabaseError(
            f"Refusing to create, drop or truncate database {url.database!r}; the harness only touches {EVAL_DB_NAME!r}."
        )
    if url.host not in LOCAL_HOSTS:
        raise UnsafeEvalDatabaseError(
            f"Refusing to use a database on host {url.host!r}: the harness's scratch database must be on this machine."
        )


def _maintenance_dsn(url: URL) -> str:
    """A DSN for the server's built-in `postgres` database (you can't drop a database while connected to it). Two traps:
    `str(url)` masks the password, so it is rendered explicitly, and raw asyncpg rejects SQLAlchemy's `+asyncpg` suffix."""
    return url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)


async def create(url: URL) -> None:
    """Drop any old scratch database and create an empty one. Plain f-string SQL is safe here only because the guard has just
    proved the name is the constant."""
    check_eval_database_url(url)
    admin = await asyncpg.connect(_maintenance_dsn(url), timeout=5)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{EVAL_DB_NAME}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{EVAL_DB_NAME}"')
    finally:
        await admin.close()


async def drop(url: URL) -> None:
    """Drop the scratch database (the harness does this at the end unless asked to keep it)."""
    check_eval_database_url(url)
    admin = await asyncpg.connect(_maintenance_dsn(url), timeout=5)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{EVAL_DB_NAME}" WITH (FORCE)')
    finally:
        await admin.close()


async def migrate(url: URL) -> None:
    """Run every migration (`alembic upgrade head`) on the scratch database, over a connection we own.

    Alembic's command API is synchronous and the engine is async, so the connection is handed over through `run_sync`;
    `migrations/env.py` sees the injected connection and skips its own URL override (which would point at DATABASE_URL). The
    commit afterwards matters: without it the migrated schema is invisible to every other connection.
    """
    check_eval_database_url(url)
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    engine = create_async_engine(url, poolclass=NullPool)

    def upgrade(sync_conn: Connection) -> None:
        config.attributes["connection"] = sync_conn
        command.upgrade(config, "head")

    try:
        async with engine.connect() as conn:
            await conn.run_sync(upgrade)
            await conn.commit()
    finally:
        await engine.dispose()


def session_factory(url: URL) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """An engine and session factory on the scratch database; the caller disposes the engine."""
    check_eval_database_url(url)
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
