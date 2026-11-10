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
    body = response.json()
    assert body["message"] == "up" and body["app_env"] == settings.app_env


async def test_health_reports_the_configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3-D6): `/health` returns the environment the process was configured with, read when the request
    # arrives, so a wrong connection string is visible from outside. The value is patched to one `local` never
    # is: a route that hard-coded "local" would pass `test_health` above in every test run and fail here.
    monkeypatch.setattr(settings, "app_env", "staging")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    body = response.json()
    assert body["message"] == "up" and body["app_env"] == "staging"


async def test_health_lists_the_feature_flags_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T8, C3.1-D16): outside production `/health` carries the effective flag values, so whoever
    # checks a deployment can see whether a switch is on without reading the dashboard. The expected dict is a
    # literal for the one registered flag, first at its default (off), then with its variable set (on): a route
    # that cached the dict at import, or hard-coded it, passes the first and fails the second.
    # Needs `resolve_value` (C3.1-K1) to be filled in.
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.delenv("FLAG_WORKER_SCHEDULED_RUNS", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).json()["feature_flags"] == {"worker.scheduled_runs": False}
        monkeypatch.setenv("FLAG_WORKER_SCHEDULED_RUNS", "true")
        assert (await client.get("/health")).json()["feature_flags"] == {"worker.scheduled_runs": True}


async def test_health_hides_the_feature_flags_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T8, C3.1-D16): in production `feature_flags` is `null`, present but empty of values. `/health`
    # is public and unauthenticated until C10, and whether the cron is armed is operational state. The key is
    # still there (null, not absent) so a client tells "hidden" from "an older API". A route that always listed
    # the flags would pass the test above and fail this one. `settings.app_env` is patched, as in the test
    # above, so nothing about the database is involved.
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setenv("FLAG_WORKER_SCHEDULED_RUNS", "true")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/health")).json()
    assert body == {"message": "up", "app_env": "prod", "feature_flags": None}


async def test_health_still_answers_with_the_flags_when_nothing_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T8): `/health` makes no database call, flags included: the app's engine is replaced by one
    # that fails on any use, and the route still answers 200. It is Railway's deploy check (C3-D8), so a
    # flag lookup that reached for the database would take the deploy check down with the database.
    monkeypatch.setattr(main, "engine", FailingEngine())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200


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


def test_health_declares_the_health_response_model() -> None:
    # Proves (C3.1-T8, C3.1-D16): `/health` is annotated `-> HealthResponse`, so /openapi.json (the source `make
    # types` turns into the frontend's TypeScript) carries a `HealthResponse` with a string `message` and
    # `app_env` and a `feature_flags` that is a map of booleans or null. Expected shape is written out from the
    # plan's model; an unannotated route or the old `dict[str, str]` fails this.
    document = app.openapi()
    schema = document["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/HealthResponse"}
    model = document["components"]["schemas"]["HealthResponse"]
    assert set(model["properties"]) == {"message", "app_env", "feature_flags"}
    assert set(model["required"]) == {"message", "app_env", "feature_flags"}
    assert model["properties"]["feature_flags"]["anyOf"] == [
        {"type": "object", "additionalProperties": {"type": "boolean"}},
        {"type": "null"},
    ]


def test_health_db_declares_a_string_map_response() -> None:
    # Proves (PQR1-15): `/health/db` is annotated `-> dict[str, str]`, so FastAPI puts a typed 200 schema in
    # /openapi.json (the source `make types` turns into the frontend's TypeScript) instead of an empty one. Expected
    # value is FastAPI's own rendering of `dict[str, str]`, an object whose additional properties are strings; it is
    # not read from the code under test. An unannotated route fails this with a schema that has no `type`.
    schema = app.openapi()["paths"]["/health/db"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert {key: value for key, value in schema.items() if key != "title"} == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
