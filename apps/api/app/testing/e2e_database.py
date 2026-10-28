"""The database the end-to-end job runs against: dropped, rebuilt and loaded on every run (C2-D7).

Run as `python -m app.testing.e2e_database` (Playwright does, as the first half of the API's start command,
`apps/calendar/playwright.config.ts`). It reads `DATABASE_URL`, refuses anything but a local database named
`calendar_e2e`, then: drops and recreates it, runs the migrations, and loads the sample world
(`app/testing/sample_data.py`). The browser specs then see the same shows `lib/fixtures` holds, from a real
Postgres.

The guard is the point of the first function. This process issues `DROP DATABASE`, and the laptop's
`apps/api/.env` has pointed `DATABASE_URL` at a hosted database before (`docs/dev/implementations/
c1-env-revalidation.md`). The name is a constant, not configurable, for the same reason as the pytest
fixtures' `calendar_test` (`app/testing/db.py`). Playwright also sets `DATABASE_URL` explicitly for this
process, so `.env` is never consulted.
"""

import asyncio
import datetime

import asyncpg  # type: ignore[import-untyped]  # ships no stubs or py.typed
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.testing.db import LOCAL_HOSTS, run_alembic
from app.testing.sample_data import load_sample_data

# The ONLY database this module will ever drop. Not a setting, so a mistyped variable can't redirect it.
E2E_DB_NAME = "calendar_e2e"


class UnsafeE2eDatabaseError(RuntimeError):
    """The database URL points somewhere the e2e job must not drop and rebuild."""


def check_e2e_database_url(url: URL) -> None:
    """Raise unless `url` is a database named exactly `calendar_e2e` on this machine."""
    if url.database != E2E_DB_NAME:
        raise UnsafeE2eDatabaseError(
            f"Refusing to run the end-to-end job against database {url.database!r}; it must be {E2E_DB_NAME!r}."
        )
    if url.host not in LOCAL_HOSTS:
        raise UnsafeE2eDatabaseError(
            f"Refusing to drop {E2E_DB_NAME!r} on host {url.host!r}: the end-to-end database must be local."
        )


def frozen_now_from(raw: str | None) -> datetime.datetime:
    """Parse `E2E_API_FROZEN_NOW` (an ISO instant with a zone) into the instant the API's clock is pinned to."""
    if not raw:
        raise RuntimeError("E2E_API_FROZEN_NOW is not set: the end-to-end API must run on a frozen clock")
    now = datetime.datetime.fromisoformat(raw)
    if now.tzinfo is None:
        raise RuntimeError(f"E2E_API_FROZEN_NOW={raw!r} has no timezone; write it with a zone, e.g. ...Z")
    return now


def _maintenance_dsn(url: URL) -> str:
    # Raw asyncpg rejects the "+asyncpg" driver suffix, and str(url) masks the password, so render it explicitly.
    return url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)


async def _recreate(url: URL) -> None:
    """Drop and create the database. Connects to the built-in `postgres` database: you can't drop the one you're in."""
    try:
        admin = await asyncpg.connect(_maintenance_dsn(url), timeout=5)
    except (OSError, TimeoutError) as exc:
        raise SystemExit(
            f"Postgres is not reachable at {url.host}:{url.port} ({exc!r}); start it with `make db-up`"
        ) from exc
    try:
        # E2E_DB_NAME is a constant checked above, never user input, so the f-string is safe here.
        await admin.execute(f'DROP DATABASE IF EXISTS "{E2E_DB_NAME}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{E2E_DB_NAME}"')
    finally:
        await admin.close()


async def _migrate_and_load(url: URL) -> None:
    # NullPool: connections are not reused across the migration and the load. The migration runs through
    # `run_alembic` on an injected connection, because the stock migrations/env.py calls asyncio.run, which
    # cannot run inside this running loop (app/testing/db.py, trap 2; C2-PR1-10).
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        await run_alembic(engine, "upgrade", "head")
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await load_sample_data(session)
            await session.commit()
    finally:
        await engine.dispose()


def main() -> None:
    url = make_url(settings.database_url)
    check_e2e_database_url(url)
    asyncio.run(_recreate(url))
    asyncio.run(_migrate_and_load(url))
    print(f"[e2e] {E2E_DB_NAME} rebuilt and loaded with the sample world")


if __name__ == "__main__":
    main()
