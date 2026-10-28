import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


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
