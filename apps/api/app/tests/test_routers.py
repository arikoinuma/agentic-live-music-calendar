"""Smoke tests for the read API's routes.

These cover shape and status code, not data correctness — the bodies
still serve app/sample_data.py, so asserting on specific shows would
just be testing the sample data. What's worth pinning down now is the
behavior that A1b must not break when it swaps the bodies for real
queries: the URLs, the filter semantics, and the error codes.

The 404 assertions exist because the first hand-written version of
get_venue used `== "None"` instead of `is None`, which returned a 500
for every unknown id. The happy path passed by hand; only the miss path
caught it.
"""

import pytest
from fastapi.testclient import TestClient

from app import sample_data as data
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("/shows", "shows"),
        ("/venues", "venues"),
        ("/artists", "artists"),
        ("/calendar/months", "months"),
    ],
)
def test_list_endpoints_return_their_envelope(path: str, key: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    # Every list endpoint returns an object with a named array, never a
    # bare array — see docs/dev/api-contract.md section 3.
    assert isinstance(response.json()[key], list)


@pytest.mark.parametrize("path", ["/venues", "/artists"])
def test_lists_are_alphabetical(path: str) -> None:
    names = [row["name"] for row in client.get(path).json()[path.strip("/")]]
    assert names == sorted(names)


@pytest.mark.parametrize(
    ("path", "expected"), [("/shows/999", 404), ("/venues/99", 404), ("/artists/99", 404)]
)
def test_unknown_id_is_404_not_500(path: str, expected: int) -> None:
    assert client.get(path).status_code == expected


@pytest.mark.parametrize("path", ["/shows/abc", "/venues/abc", "/artists/abc"])
def test_non_integer_id_is_422(path: str) -> None:
    # Free from the `int` annotation on the path parameter; no code in
    # the route does this check.
    assert client.get(path).status_code == 422


def test_detail_endpoints_return_the_requested_record() -> None:
    assert client.get("/venues/3").json()["id"] == 3
    assert client.get("/artists/1").json()["id"] == 1
    assert client.get("/shows/2").json()["id"] == 2


def test_show_detail_resolves_inherited_venue_fields() -> None:
    # Show 2 sets none of the four inherited fields itself, so these come
    # from its venue — resolved server-side, per api-contract.md §5.
    show = client.get("/shows/2").json()
    assert show["age_restriction"] == "twenty_one_plus"
    assert show["serves_alcohol"] is True


def test_date_range_filters() -> None:
    body = client.get("/shows?start=2026-10-01&end=2026-10-07").json()
    assert body["start"] == "2026-10-01"
    assert body["end"] == "2026-10-07"
    assert all("2026-10-01" <= s["date"] <= "2026-10-07" for s in body["shows"])


def test_repeated_filter_values_are_or_ed() -> None:
    one = len(client.get("/shows?venue_id=1").json()["shows"])
    three = len(client.get("/shows?venue_id=3").json()["shows"])
    both = len(client.get("/shows?venue_id=1&venue_id=3").json()["shows"])
    assert both == one + three


def test_different_filters_are_and_ed() -> None:
    venue_only = len(client.get("/shows?venue_id=3").json()["shows"])
    combined = len(client.get("/shows?venue_id=3&artist_id=1").json()["shows"])
    assert 0 < combined <= venue_only


def test_artist_filter_matches_anywhere_in_the_lineup() -> None:
    # Artist 1 appears third on one bill; an artist's page should show
    # that night too, not only the ones they headline.
    shows = client.get("/shows?artist_id=1").json()["shows"]
    assert any(
        entry["artist"]["id"] == 1 and entry["sequence_number"] > 1
        for show in shows
        for entry in show["lineup"]
    )


def test_shows_are_ordered_by_date_then_time() -> None:
    shows = client.get("/shows").json()["shows"]
    keys = [(s["date"], s["start_time"] is None, s["start_time"] or "") for s in shows]
    assert keys == sorted(keys)


@pytest.mark.parametrize(
    "query",
    [
        "start=2026-10-10&end=2026-10-01",  # end before start
        "start=2020-01-01&end=2030-01-01",  # wider than MAX_RANGE
    ],
)
def test_invalid_ranges_are_rejected(query: str) -> None:
    assert client.get(f"/shows?{query}").status_code == 422


def test_openapi_exposes_the_response_schemas() -> None:
    """The reason these stub routes exist before the database does.

    If a route stops declaring its return type, its models silently drop
    out of components.schemas and the generated TypeScript loses them —
    a failure that otherwise surfaces as a missing frontend type long
    after the change that caused it.
    """
    schemas = app.openapi()["components"]["schemas"]
    for name in ("ShowSummary", "ShowDetail", "VenueDetail", "ArtistDetail", "LineupEntry"):
        assert name in schemas


# --- GET /metro (B2) ------------------------------------------------------
# The layout's footer and <meta description> read the metro name from here
# (alpha-build-plan.md G24) instead of a hard-coded literal.


def test_metro_returns_the_live_metro() -> None:
    """Proves: /metro answers 200 with the single live metro's id, name and timezone.

    Expected values come from `sample_data.METRO`, the same object the
    route serves for now, so this pins the route to its source and the
    response *shape*; it can't say the data is right. The A1b swap to a
    database query keeps this test meaningful because the seed must agree.
    """
    response = client.get("/metro")
    assert response.status_code == 200
    assert response.json() == {
        "id": data.METRO.id,
        "name": data.METRO.name,
        "timezone": data.METRO.timezone,
    }


def test_openapi_exposes_the_metro_route() -> None:
    """Proves: /metro is in the OpenAPI document and its 200 response is MetroSummary.

    Deliberately not "add MetroSummary to the schema-name check above":
    MetroSummary is already in components.schemas, nested inside
    VenueDetail, so that assertion would pass before the route exists
    (B2-PR1-5). What the generated TypeScript needs is the *path*
    with a typed response; this fails if the return annotation is dropped.
    """
    paths = app.openapi()["paths"]
    assert "/metro" in paths
    ref = paths["/metro"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ref == {"$ref": "#/components/schemas/MetroSummary"}
