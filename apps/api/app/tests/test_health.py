"""Tests for the two health routes in `app/main.py`.

`/health` is the liveness route (no database access); `/health/db` proves one round trip to Postgres. They are read
in three sections: what `/health` returns, what `/health/db` returns and does when the database is down (against a
real test database for success and a stand-in engine for failure), and what the OpenAPI document says about both (PQR1-15).
"""

from types import TracebackType
from typing import Self

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app import main
from app.config import settings
from app.main import app

# --- /health -------------------------------------------------------------------------------------------------------


async def test_health() -> None:
    # Proves: the app imports and starts, and the liveness route /health answers 200 with {"message": "up"} and the
    # environment (C3-D6) without touching the database. /health/db, which does, is not unit-tested: it uses the app's own engine, the development
    # database, not `calendar_test`. Uses the same async client as the route tests (C2); `TestClient` was the last
    # user of the deprecated httpx-with-Starlette path.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"message": "up", "app_env": settings.app_env}


async def test_health_reports_the_configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3-D6): `/health` returns the environment the process was configured with, read when the request
    # arrives, so a wrong connection string is visible from outside. The value is patched to one `local` never
    # is: a route that hard-coded "local" would pass `test_health` above in every test run and fail here.
    monkeypatch.setattr(settings, "app_env", "staging")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.json() == {"message": "up", "app_env": "staging"}


# --- /health/db ----------------------------------------------------------------------------------------------------


class FailingEngine:
    """Stands in for the app's engine when the database is down: `connect()` hands back a connection whose first
    statement raises. Only the failure case uses it; the success case runs against real Postgres."""

    def connect(self) -> "FailingEngine":
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None

    async def execute(self, statement: object) -> None:
        raise ConnectionError("database is down")


async def test_health_db_returns_its_body_after_one_round_trip(
    monkeypatch: pytest.MonkeyPatch, migrated_engine: AsyncEngine
) -> None:
    # Proves (PQR1-15): `/health/db` makes a real round trip and answers 200 with its message. The app's own engine
    # points at the development database, so the suite's `migrated_engine` (on `calendar_test`) is patched in: the
    # route's one job, reaching Postgres, runs against Postgres and not a stand-in. Moving the `return` out of the
    # `async with` block must not drop the body.
    monkeypatch.setattr(main, "engine", migrated_engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"message": "db connection up"}


async def test_health_db_lets_a_database_error_through(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (PQR1-15): a database failure is deliberately not caught in the route. It reaches FastAPI, which answers
    # 500, the signal a deploy check needs. A tidy-up that wrapped the block in `try/except` and returned a 200 "down"
    # body would turn that into a passing health check. `raise_app_exceptions=False` makes the client see the 500
    # that a real caller sees, instead of re-raising the error.
    monkeypatch.setattr(main, "engine", FailingEngine())
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/db")
    assert response.status_code == 500


# --- The OpenAPI document ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/health", "/health/db"])
def test_the_health_routes_declare_a_string_map_response(path: str) -> None:
    # Proves (PQR1-15): both routes are annotated `-> dict[str, str]`, so FastAPI puts a typed 200 schema in
    # /openapi.json (the source `make types` turns into the frontend's TypeScript) instead of an empty one. Expected
    # value is FastAPI's own rendering of `dict[str, str]`, an object whose additional properties are strings; it is
    # not read from the code under test. An unannotated route fails this with a schema that has no `type`.
    schema = app.openapi()["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert {key: value for key, value in schema.items() if key != "title"} == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
