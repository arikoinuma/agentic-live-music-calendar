"""Fixtures for the read-API tests: the real app over the sample world, in a rolled-back transaction."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.testing.api_client import api_client
from app.testing.sample_data import load_sample_data


@pytest_asyncio.fixture(loop_scope="session")
async def sample_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """A client for the real app, reading the sample world from Postgres, clock at the sample's START.

    The world is loaded into `db_session` (flushed, never committed), so it disappears with the test's
    transaction. `expunge_all()` afterwards is what makes the routes read from the database and not from
    the loader's in-memory objects: without it the routes would be handed `Decimal('10')` where Postgres
    stores `Decimal('10.00')`, and no test would exercise the column types (C2-PR1-2).
    """
    await load_sample_data(db_session)
    db_session.expunge_all()
    async with api_client(db_session) as client:
        yield client
