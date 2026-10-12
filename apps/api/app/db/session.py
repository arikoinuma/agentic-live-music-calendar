"""The async engine and session factory.

One engine for the process, used by `app/main.py` (health check) and the
seed CLI, and — from A4 — by the worker. There is deliberately no `get_db`
FastAPI dependency yet: nothing consumes one until the read routes move off
`app/sample_data.py`, and this repo doesn't scaffold what has no consumer.

Known consequence for A4 (docs/dev/alpha-build-plan.md, A4): this engine is
pooled and async, created at import. The worker's nodes are synchronous, and
asyncpg connections are bound to the event loop that created them — so
calling `asyncio.run()` once per node against *this* engine fails on the
second node. The worker must either use `async def` nodes or build its own
NullPool engine per `asyncio.run`.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings

# Created once, at import time, and reused for every request — an engine per
# request would open a fresh connection pool each time, defeating pooling.
#
# pool_pre_ping=True (carried over from app/main.py): without it, a pooled
# connection that Neon has silently closed server-side after sitting idle
# gets handed back out for reuse anyway, and fails with "connection is
# closed" the moment a query runs on it — confirmed directly against the
# deployed Railway service. The pool pings each connection before handing it
# out and transparently reconnects a stale one, instead of surfacing a 500 on
# the first request after any idle period.
engine = create_async_engine(settings.database_url, pool_pre_ping=True)

# The factory that hands out sessions. Use it as `async with SessionFactory()
# as session:` — each session is one unit of work (a request, a seed run, a
# commit_node transaction). It borrows connections from `engine` above.
#
# expire_on_commit=False: with an async session, touching an expired
# attribute after commit would trigger a lazy load, which can't happen
# implicitly under asyncio.
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
