from fastapi import FastAPI, status
from sqlalchemy import text

from app.db.session import engine
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
