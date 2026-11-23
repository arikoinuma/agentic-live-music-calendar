"""Tests that the API refuses a call without the shared secret, and what a refusal does and does not touch (C10).

HOW TO READ THIS
  The real app (`app.main.app`), called in-process with `httpx.ASGITransport`, with a secret configured by patching
  `settings` for the test. The autouse fixture in `apps/api/conftest.py` clears it again, so no other test is guarded.

  1. The refusal itself (C10-T1): no header, a wrong header, a non-ASCII header.
  2. What a refusal skips (C10-T2): the database and query validation.
  3. Coverage (C10-T3): every operation the app documents, so a route added later cannot ship open.
  4. The lifespan (C10-T6) and the fail-closed fallback (C10-T7): a hosted API cannot run open.
  5. `/health` stays open and says nothing secret (C10-D6, C10-D14).

  The tests that only refuse use a stand-in for `get_db` that records its calls, so no database is needed. Only the
  accepting test (the right header answering 200) reads the sample world from Postgres, and skips without it.
"""

import re
from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.main import app
from app.security import SHARED_SECRET_HEADER

SECRET = "a-test-secret-that-is-at-least-32-characters-long"
HEADER = SHARED_SECRET_HEADER.encode()
REFUSAL = {"detail": "Missing or invalid API secret"}

# The one operation that is open: Railway's deploy check and the status page need it with no header (C10-D6). Written
# by hand, never computed, so a route that wrongly joined it is a red test and not a silent exemption.
OPEN = {("GET", "/health")}


@pytest.fixture
def guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a shared secret for the test (the suite's default is none: apps/api/conftest.py)."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr(SECRET))


@pytest.fixture
def db_calls() -> Iterator[list[str]]:
    """Replace the database session with one that records its use and gives nothing.

    A refusal must happen before any database work, so a test that expects 401 also expects this list to be empty. The
    override is removed afterwards, even if the test fails.
    """
    calls: list[str] = []

    async def _recording_session() -> AsyncIterator[AsyncSession]:
        calls.append("get_db")
        raise AssertionError("a refused request reached the database")
        yield  # pragma: no cover - makes this an async generator, which FastAPI's `Depends` expects

    app.dependency_overrides[get_db] = _recording_session
    try:
        yield calls
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# --- 1. the refusal (C10-T1) -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {HEADER: b"not-the-secret"},
        {HEADER: SECRET[:-1].encode()},
        {HEADER: "é".encode("latin-1")},  # bytes, because httpx would refuse to encode this str as ASCII
    ],
    ids=["absent", "wrong", "prefix", "non-ascii"],
)
async def test_a_request_without_the_right_secret_is_refused_the_same_way(
    guarded: None, db_calls: list[str], client: AsyncClient, headers: dict[bytes, bytes]
) -> None:
    # Proves (C10-T1, the deployment plan's first C10 test; C10-D7): with a secret configured, a request with no header,
    # a wrong one or an unreadable one is refused with the same 401 and the same body, so a caller cannot tell "absent"
    # from "wrong", and none of them is a 500 (the non-ASCII row is the `compare_digest`-on-`str` crash).
    response = await client.get("/metro", headers=headers)
    assert response.status_code == 401
    assert response.json() == REFUSAL


async def test_the_right_secret_reaches_the_route(guarded: None, sample_client: AsyncClient) -> None:
    # Proves (C10-T1, C10-D6): the guard lets the right value through and the route answers as it always did, so the
    # refusals above are not a guard that refuses everything. Reads the sample world from Postgres.
    response = await sample_client.get("/metro", headers={SHARED_SECRET_HEADER: SECRET})
    assert response.status_code == 200
    assert response.json()["slug"] == "msp"


# --- 2. what a refusal skips (C10-T2) ----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/shows?start=garbage", "/venues/0", "/health/db"])
async def test_a_refusal_comes_before_validation_and_before_the_database(
    guarded: None, db_calls: list[str], client: AsyncClient, path: str
) -> None:
    # Proves (C10-T2, C10-D6): an unauthenticated caller gets 401 even for a request that would be a 422, so it learns
    # nothing about the routes' parameters, and the database is never opened for it (Neon is not woken by a stranger).
    # `/health/db` is here because it does its own database round trip and must carry the guard on its decorator.
    response = await client.get(path)
    assert response.status_code == 401
    assert db_calls == []


# --- 3. coverage (C10-T3) ----------------------------------------------------------------------------------------------


async def test_every_documented_operation_is_guarded_except_health(
    guarded: None, db_calls: list[str], client: AsyncClient
) -> None:
    # Proves (C10-T3, C10-D6): fail-closed for routes added later. It reads the operations the app documents in
    # `/openapi.json`, sends each with no header, and expects 401 from all of them except the hand-written OPEN set.
    # It goes through behavior and not `app.routes` because FastAPI 0.162 keeps an included router as a lazy object
    # there (the routes are not `APIRoute`s), so a walk over `app.routes` would see two routes and pass while
    # guarding nothing. A new router included straight onto `app`, or a route on `app` without the dependency, fails here.
    paths = app.openapi()["paths"]
    for required in ("/metro", "/shows", "/venues", "/artists", "/calendar/months", "/health", "/health/db"):
        assert required in paths, f"{required} is no longer documented: the sweep would pass on emptiness"

    answers: dict[tuple[str, str], int] = {}
    for template, item in paths.items():
        url = re.sub(r"\{[^}]+\}", "1", template)
        for method in item:
            if method in {"get", "post", "put", "patch", "delete"}:
                response = await client.request(method.upper(), url)
                answers[(method.upper(), template)] = response.status_code

    expected = {key: (200 if key in OPEN else 401) for key in answers}
    assert answers == expected
    assert db_calls == []


# --- 4. the lifespan and the fail-closed fallback (C10-T6, C10-T7) ---------------------------------------------------------


async def test_a_hosted_api_refuses_to_start_without_a_good_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C10-T6, C10-D9): the lifespan raises on a hosted `APP_ENV` with no secret, and with a short one, so a
    # deploy with a forgotten variable fails (Railway keeps the previous deployment, C10-U3) instead of serving an open
    # API. `ASGITransport` never runs the lifespan, so this is the only test that does.
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "api_shared_secret", None)
    with pytest.raises(RuntimeError, match="API_SHARED_SECRET"):
        async with app.router.lifespan_context(app):
            pass
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("too-short"))
    with pytest.raises(RuntimeError, match="API_SHARED_SECRET"):
        async with app.router.lifespan_context(app):
            pass


@pytest.mark.parametrize(
    ("app_env", "secret"),
    [("staging", SECRET), ("local", None), ("local", SECRET)],
    ids=["hosted-with-secret", "laptop-without", "laptop-with"],
)
async def test_the_lifespan_starts_when_the_secret_is_good_or_the_environment_is_a_laptop(
    monkeypatch: pytest.MonkeyPatch, app_env: str, secret: str | None
) -> None:
    # Proves (C10-T6, C10-D9): the refusal is not a lifespan that always raises. A hosted API with a good secret
    # starts, and a laptop starts with or without one: the `local` exemption is decided in the lifespan alone (C10-PR1-7),
    # so this is its only test, and a lifespan that forgot the exemption would stop `make dev`.
    monkeypatch.setattr(settings, "app_env", app_env)
    monkeypatch.setattr(settings, "api_shared_secret", None if secret is None else SecretStr(secret))
    async with app.router.lifespan_context(app):
        pass


async def test_a_hosted_api_with_no_secret_still_refuses_requests(
    monkeypatch: pytest.MonkeyPatch, db_calls: list[str], client: AsyncClient
) -> None:
    # Proves (C10-T7, C10-D9's belt and braces): if a hosted process somehow got past start-up with no secret, the
    # guard itself fails closed (401) and does not read "unset" as "open". Only `local` may be open.
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "api_shared_secret", None)
    response = await client.get("/metro")
    assert response.status_code == 401
    assert db_calls == []


# --- 5. /health stays open and says nothing secret (C10-D6, C10-D14) -----------------------------------------------------------


async def test_health_is_open_and_never_echoes_the_secret(guarded: None, client: AsyncClient) -> None:
    # Proves (C10-D6, C10-D14): Railway's deploy check calls `/health` with no header and must get 200, and the body
    # carries no trace of the secret even though one is configured.
    response = await client.get("/health")
    assert response.status_code == 200
    assert SECRET not in response.text
