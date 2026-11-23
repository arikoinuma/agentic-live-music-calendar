"""The FastAPI application: the `app` object, its routers, and the two health routes.

Read it top to bottom: the lifespan (a hosted API refuses to start without a good shared secret, C10-D9), then `app`
is created and the five routers (`app/routers/`) are attached to ONE guarded router (C10-D6), then `/health` (is the
process up, and which environment does it think it is in: open, no secret) and `/health/db` (can it reach Postgres:
guarded). Every other route lives in a router; the health routes stay here because they belong to the process, not to a
resource.

The guard is `app/security.py`'s `require_shared_secret`: every route needs the `X-Api-Secret` header except `/health`.
It is the default, so a router added later is guarded unless someone attaches it somewhere else on purpose, and a test
(`test_api_guard.py`, C10-T3) fails if a documented route answers anything but 401 without the header.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, status
from sqlalchemy import text

from app.config import settings
from app.db.session import engine
from app.flags import effective_flags
from app.routers import artists, calendar, metro, shows, venues
from app.schemas import HealthResponse
from app.security import openapi_url_for, require_shared_secret, shared_secret_problem


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Refuse to start a hosted API that would answer anyone (C10-D9).

    A laptop (`local`) serves openly with or without a secret, so the check is skipped there; that exemption is decided
    here and nowhere else (C10-PR1-7). On `dev`, `staging` and `prod` a missing or short `API_SHARED_SECRET` raises, so the
    deploy fails and Railway keeps the previous deployment serving. Plain `ASGITransport` tests never run a lifespan; the
    test that does is `test_api_guard.py` (C10-T6).
    """
    if settings.app_env != "local":
        secret = settings.api_shared_secret
        problem = shared_secret_problem(settings.app_env, None if secret is None else secret.get_secret_value())
        if problem is not None:  # `is not None`, not truthiness: an empty sentence must still stop a hosted API
            raise RuntimeError(problem)
    yield


app = FastAPI(
    title="Agentic Live Music Calendar API",
    # Shown at the top of /docs and carried in /openapi.json. Worth
    # setting because the generated TypeScript inherits the API's own
    # description of itself.
    description="Read API for the Minneapolis/St. Paul live music calendar.",
    version="0.1.0",
    # `/docs`, `/redoc` and `/openapi.json` are plain routes that no dependency covers, so staging and production serve
    # none of them (C10-D2, PQR1-12). A laptop and dev keep them.
    openapi_url=openapi_url_for(settings.app_env),
    lifespan=lifespan,
)

# The guarded router (C10-D6): the one place the shared-secret dependency is attached for every data route. The five
# routers are included into it, then it is included into the app, so a route in any of them needs the header and a sixth
# router added here is guarded without anyone remembering to.
#
# Attaching a router copies its routes onto the app, prefix and all, so every route in app/routers/ appears in
# /openapi.json. That schema is what `make types` turns into the frontend's TypeScript (docs/dev/api-contract.md). The
# dependency reads `Request` and declares no parameter, so it adds nothing to that schema (C10-D8).
protected = APIRouter(dependencies=[Depends(require_shared_secret)])
protected.include_router(shows.router)
protected.include_router(venues.router)
protected.include_router(artists.router)
protected.include_router(calendar.router)
protected.include_router(metro.router)
app.include_router(protected)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health() -> HealthResponse:
    # `app_env` is the environment this process believes it is in (C3-D6), so a wrong connection string or a
    # copied variable set is visible from outside. Read per request, from the settings the startup rule
    # (C3-D4) already checked. No database access: this is the route Railway's deploy check calls (C3-D8).
    #
    # `feature_flags` (C3.1-D16) lists the effective values outside production and is `null` in production, whose
    # `/health` is public. Evaluating flags reads only the process environment, which `Settings` already validated
    # at startup (C3.1-D12), so this route still touches no database and cannot fail on a malformed flag.
    return HealthResponse(
        message="up",
        app_env=settings.app_env,
        feature_flags=None if settings.app_env == "prod" else effective_flags(),
    )


# On `app`, not the guarded router, because the health routes belong to the process, but it carries the guard on its own
# decorator: it does a database round trip for whoever asks, which is what a stranger must not be able to cause (C10-D6,
# C10-PR1-1). `/health` above has none: Railway's deploy check and the status page call it with no header.
@app.get("/health/db", dependencies=[Depends(require_shared_secret)])
async def health_db() -> dict[str, str]:
    # Proves the app can reach Postgres with one round trip. A failure is deliberately not caught: SQLAlchemy
    # raises, FastAPI turns it into a 500, and a 500 is exactly the signal a health check should give.
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"message": "db connection up"}
