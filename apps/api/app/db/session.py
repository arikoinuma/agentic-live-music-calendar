"""The async engine and session factory.

One engine for the process, used by `app/main.py` (health check), the seed CLI,
the worker (from A4) and, from C2, the read routes through `get_db` below.

Resolved in A4 (docs/dev/implementations/a4-auditability.md, A4-D1): this engine
is pooled and async, and asyncpg connections are bound to the event loop that
created them, so calling `asyncio.run()` once per node against it would fail
on the second node. The worker therefore runs ONE event loop per process
(`asyncio.run(main())` in agent_worker/main.py) and the graph is `ainvoke`-only:
each node is wrapped by `agent_worker/trace.audited`, which awaits the audit
write on that loop and runs the synchronous node body in a thread. This
engine is shared by every node's audit write; no second engine is needed.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, closed when the response is done.

    The read routes never write, so nothing here commits; closing the session returns its connection to
    the pool and rolls back anything open. Tests replace this dependency to hand every route the test's
    own rolled-back session (`app.dependency_overrides[get_db]`).
    """
    async with SessionFactory() as session:
        yield session
