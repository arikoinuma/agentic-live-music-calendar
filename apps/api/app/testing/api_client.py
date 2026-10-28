"""An in-process HTTP client for the real app, wired to a test's session and clock.

The route tests and the keystone fixture test call the real routes through `httpx.AsyncClient` +
`ASGITransport` (docs/references/fastapi-style-guide.md, "Testing") rather than `TestClient`, because
the routes are `async def` and read through an `AsyncSession` that must live on the test's own event
loop. Two dependencies are replaced for the duration (`app.dependency_overrides`):

  * `get_db` yields the test's session, which rides on a transaction the fixtures roll back, so a
    test's rows never outlive it and the route sees them without a commit.
  * `get_now` returns a fixed instant, so "today" is whatever the test says (C2-D2).
"""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import get_now
from app.db.session import get_db
from app.main import app
from app.testing.sample_data import FIXED_NOW


@asynccontextmanager
async def api_client(
    session: AsyncSession, now: datetime.datetime = FIXED_NOW
) -> AsyncIterator[AsyncClient]:
    """Yield a client for the real app reading through `session`, with its clock at `now`.

    The overrides are removed on exit, even if the test fails, so one test's clock or session can't leak
    into the next.
    """

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db] = _session
    app.dependency_overrides[get_now] = lambda: now
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_now, None)
