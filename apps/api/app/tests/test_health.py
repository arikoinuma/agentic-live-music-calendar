from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health() -> None:
    # Proves: the app imports and starts, and the liveness route /health answers 200 with {"message": "up"} without
    # touching the database. /health/db, which does, is not unit-tested: it uses the app's own engine, the development
    # database, not `calendar_test`. Uses the same async client as the route tests (C2); `TestClient` was the last
    # user of the deprecated httpx-with-Starlette path.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"message": "up"}
