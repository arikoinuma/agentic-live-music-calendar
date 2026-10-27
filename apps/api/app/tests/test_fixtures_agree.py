"""The keystone test: the real routes over the sample world return exactly what the fixtures hold (C2-D1).

The frontend's JSON fixtures are written from the sample world's pure builders (`fixture_payloads`, no
database). The API answers from Postgres. This test loads the same world, calls each route a fixture
stands for, and requires the two to be equal, so neither can drift without a red test: a route that orders
differently, a loader that drops a field, a column type that rounds, or a builder edit.

Where the expected values come from: `fixture_payloads()`, the pure builders. The actual values come from
the routes and the database. Neither is read from the other. The clock is the sample's START, so the
default window is the window the fixture claims.
"""

import pytest
from httpx import AsyncClient

from app.testing.sample_data import fixture_payloads

# Which route each fixture stands for. The ids are the ones the fixtures were written from
# (scripts/generate_fixtures.py): show 2, venue 3, artist 1.
ROUTES = {
    "metro.json": "/metro",
    "shows.json": "/shows",
    "show-detail.json": "/shows/2",
    "venues.json": "/venues",
    "venue-detail.json": "/venues/3",
    "artists.json": "/artists",
    "artist-detail.json": "/artists/1",
    "calendar-months.json": "/calendar/months",
}


def test_every_fixture_has_a_route_here() -> None:
    # Proves: a fixture added to `fixture_payloads()` without a route in this table fails here, instead of going
    # unchecked.
    assert set(ROUTES) == set(fixture_payloads())


@pytest.mark.parametrize("name", sorted(ROUTES))
async def test_the_route_returns_the_fixture(sample_client: AsyncClient, name: str) -> None:
    # Proves: the route's JSON equals the fixture's JSON, strictly (list order included: shows.json is stored in the
    # order the API returns, C2-PR1-1). Also covers the one place the sample's rules and the database's could differ
    # without another test noticing: Decimal and time round-tripping through Numeric(10, 2) and Time.
    response = await sample_client.get(ROUTES[name])
    assert response.status_code == 200
    assert response.json() == fixture_payloads()[name].model_dump(mode="json")
