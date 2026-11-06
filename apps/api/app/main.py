from fastapi import FastAPI, status
from sqlalchemy import text

from app.config import settings
from app.db.session import engine
from app.routers import artists, calendar, metro, shows, venues

app = FastAPI(
    title="Agentic Live Music Calendar API",
    # Shown at the top of /docs and carried in /openapi.json. Worth
    # setting because the generated TypeScript inherits the API's own
    # description of itself.
    description="Read API for the Minneapolis/St. Paul live music calendar.",
    version="0.1.0",
)

# Attaching a router copies its routes onto the app, prefix and all, so every route in app/routers/ appears in
# /openapi.json. That schema is what `make types` turns into the frontend's TypeScript (docs/dev/api-contract.md).
app.include_router(shows.router)
app.include_router(venues.router)
app.include_router(artists.router)
app.include_router(calendar.router)
app.include_router(metro.router)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health():
    # `app_env` is the environment this process believes it is in (C3-D6), so a wrong connection string or a
    # copied variable set is visible from outside. Read per request, from the settings the startup rule
    # (C3-D4) already checked. No database access: this is the route Railway's deploy check calls (C3-D8).
    return {"message": "up", "app_env": settings.app_env}


@app.get("/health/db")
async def health_db():
    # Proves the app can reach Postgres with one round trip. A failure is deliberately not caught: SQLAlchemy
    # raises, FastAPI turns it into a 500, and a 500 is exactly the signal a health check should give.
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        return {"message": "db connection up"}
