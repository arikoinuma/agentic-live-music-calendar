from fastapi import FastAPI, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.routers import artists, calendar, shows, venues

app = FastAPI(
    title="Agentic Live Music Calendar API",
    # Shown at the top of /docs and carried in /openapi.json. Worth
    # setting because the generated TypeScript inherits the API's own
    # description of itself.
    description="Read API for the Minneapolis/St. Paul live music calendar.",
    version="0.1.0",
)

# Attaching a router copies its routes onto the app, prefix and all.
# Every route in app/routers/ now appears in /openapi.json — which is
# the whole reason these stub routes exist before the database does.
# See docs/dev/api-contract.md.
app.include_router(shows.router)
app.include_router(venues.router)
app.include_router(artists.router)
app.include_router(calendar.router)

# create an async SQLAlchemy engine using settings.database_url.
# create_async_engine() takes the connection string as its first argument.
# This is created once, at import time, and reused for every request —
# creating a new engine per request would open a fresh connection pool
# every time, which defeats the point of pooling.
#
# pool_pre_ping=True: without it, a pooled connection that Neon has
# silently closed server-side after sitting idle gets handed back out
# for reuse anyway, and fails with "connection is closed" the moment a
# query actually runs on it — confirmed directly against the deployed
# Railway service. This makes the pool test each connection with a
# lightweight ping before handing it out, transparently reconnecting if
# it's gone stale, rather than surfacing a 500 on the next request after
# any idle period.
engine = create_async_engine(settings.database_url, pool_pre_ping=True)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health():
    return {"message": "up"}


@app.get("/health/db")
async def health_db():
    # this route proves the app can actually reach Postgres.
    # Steps:
    #   1. Open a connection from the engine as an async context manager:
    #        async with engine.connect() as conn:
    #   2. Inside that block, run a trivial round-trip query:
    #        await conn.execute(text("SELECT 1"))
    #   3. Return something indicating success, e.g. a dict like the one
    #      above.
    # You don't need to catch exceptions yet — if the connection or query
    # fails, SQLAlchemy raises, and FastAPI turns any uncaught exception
    # into a 500 response on its own. That's a fine signal for this stage.
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        return {"message": "db connection up"}
