from fastapi.testclient import TestClient

from app.main import app


def test_health():
    # Proves: the app imports and starts, and the liveness route /health answers 200 with {"message": "up"} without
    # touching the database. /health/db, which does, is not unit-tested: it uses the app's own engine, the development
    # database, not `calendar_test`.
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"message": "up"}
