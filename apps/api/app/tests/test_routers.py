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

import datetime

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
    # Proves (api-contract.md §3, "Envelopes, not bare arrays"): each list endpoint answers 200 with an object holding a named
    # array (`shows`, `venues`, `artists`, `months`). The generated TypeScript and the frontend's reads depend on that shape.
    # Shape only: no data is asserted.
    response = client.get(path)
    assert response.status_code == 200
    # Every list endpoint returns an object with a named array, never a
    # bare array — see docs/dev/api-contract.md section 3.
    assert isinstance(response.json()[key], list)


@pytest.mark.parametrize("path", ["/venues", "/artists"])
def test_lists_are_alphabetical(path: str) -> None:
    # Proves (alpha-build-plan.md, B4: "flat alphabetical lists"): /venues and /artists are ordered by name. The expected order
    # is `sorted()` of the names the response itself returned, so this checks the ordering, not which names are listed.
    names = [row["name"] for row in client.get(path).json()[path.strip("/")]]
    assert names == sorted(names)


@pytest.mark.parametrize(
    ("path", "expected"), [("/shows/999", 404), ("/venues/99", 404), ("/artists/99", 404)]
)
def test_unknown_id_is_404_not_500(path: str, expected: int) -> None:
    # Proves: an id that matches no row is a 404 on all three detail routes, not a 500 (the module docstring's `== "None"`
    # bug). 999 and 99 are above every id in `sample_data.py`; A1b's seed must leave them unused.
    assert client.get(path).status_code == expected


@pytest.mark.parametrize("path", ["/shows/abc", "/venues/abc", "/artists/abc"])
def test_non_integer_id_is_422(path: str) -> None:
    # Proves: an id that is not an integer is a 422 on all three detail routes. If a route's path parameter lost its `int`
    # annotation, "abc" would reach the lookup and become a 404 (or a 500) instead.
    # Free from the `int` annotation on the path parameter; no code in
    # the route does this check.
    assert client.get(path).status_code == 422


def test_detail_endpoints_return_the_requested_record() -> None:
    # Proves: each detail route returns the record whose id was asked for. Venue 3, artist 1 and show 2 are rows in
    # `sample_data.py`; A1b's seed must have a row at each of those ids or this test must move with it.
    assert client.get("/venues/3").json()["id"] == 3
    assert client.get("/artists/1").json()["id"] == 1
    assert client.get("/shows/2").json()["id"] == 2


def test_show_detail_resolves_inherited_venue_fields() -> None:
    # Proves (api-contract.md §5): the read API returns the effective value of an inherited field, resolved on the server.
    # The expected `twenty_one_plus` and alcohol-serving come from show 2's venue in `sample_data.py`, set by hand there.
    # Show 2 sets none of the four inherited fields itself, so these come
    # from its venue — resolved server-side, per api-contract.md §5.
    show = client.get("/shows/2").json()
    assert show["age_restriction"] == "twenty_one_plus"
    assert show["serves_alcohol"] is True


def test_date_range_filters() -> None:
    # Proves (api-contract.md §2, §3): `start` and `end` bound the shows returned, and the response echoes the range it
    # used. The bounds are the literals in the URL; ISO dates compare correctly as strings.
    body = client.get("/shows?start=2026-10-01&end=2026-10-07").json()
    assert body["start"] == "2026-10-01"
    assert body["end"] == "2026-10-07"
    assert all("2026-10-01" <= s["date"] <= "2026-10-07" for s in body["shows"])


def test_repeated_filter_values_are_or_ed() -> None:
    # Proves (api-contract.md §2, "Filtering"): repeating `venue_id` means "either venue", so venues 1 and 3 together return
    # exactly venue 1's shows plus venue 3's (no show is at both). The expected count is the sum of the two single-venue
    # responses, not a literal.
    one = len(client.get("/shows?venue_id=1").json()["shows"])
    three = len(client.get("/shows?venue_id=3").json()["shows"])
    both = len(client.get("/shows?venue_id=1&venue_id=3").json()["shows"])
    assert both == one + three


def test_different_filters_are_and_ed() -> None:
    # Proves (api-contract.md §2, "Filtering"): different filters are AND-ed. Venue 3 with artist 1 is a non-empty subset of
    # venue 3's shows: non-empty because artist 1 plays venue 3 in `sample_data.py`, a subset because AND cannot add shows.
    venue_only = len(client.get("/shows?venue_id=3").json()["shows"])
    combined = len(client.get("/shows?venue_id=3&artist_id=1").json()["shows"])
    assert 0 < combined <= venue_only


def test_artist_filter_matches_anywhere_in_the_lineup() -> None:
    # Proves: the artist filter matches an artist anywhere in a lineup, not only as headliner. Artist 1 is third on one sample
    # bill (hand-checked in `sample_data.py`).
    # Artist 1 appears third on one bill; an artist's page should show
    # that night too, not only the ones they headline.
    shows = client.get("/shows?artist_id=1").json()["shows"]
    assert any(
        entry["artist"]["id"] == 1 and entry["sequence_number"] > 1
        for show in shows
        for entry in show["lineup"]
    )


def test_shows_are_ordered_by_date_then_time() -> None:
    # Proves: /shows returns shows ordered by date, then start time, with a show that has no time after the timed ones on
    # its date. That is the router's own rule (`shows._ordering`'s docstring explains why), which A1b's ORDER BY must
    # keep. The expected order is the response sorted by that key, so this checks order only.
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
    # Proves: an end before the start, and a range wider than `MAX_RANGE`, are each a 422 rather than an empty or an
    # unbounded answer. The rules are the router's (`app/routers/shows.py`, the two `HTTPException(422)` checks), not
    # the contract's, which mentions `MAX_RANGE` only for `upcoming=true` (§2). Both queries are written out above.
    assert client.get(f"/shows?{query}").status_code == 422


def test_openapi_exposes_the_response_schemas() -> None:
    """Proves: the OpenAPI document lists the response models the frontend's types are generated from.

    The reason these stub routes exist before the database does.

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
# (alpha-build-plan.md v0.1-G24) instead of a hard-coded literal.


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


# --- GET /shows?upcoming=true (B4-D2) ----------------------
# The artist page lists EVERY future show of an artist, not just the next
# four weeks. The client can't ask for that with dates (the server owns
# "now", api-contract.md §3), so `upcoming=true` means "from the server's
# today, no upper limit".
#
# Where the expected values come from: worked out by hand from the rows in
# sample_data.py, not read back from the code under test. Charlie Parr is
# artist 1 and plays: 2026-09-28 (venue 1), 2026-10-07 (venue 3),
# 2026-10-08 (venue 1), 2026-10-20 (venue 3) -- all inside the default
# window, which is 2026-09-28..2026-10-25 -- plus the one row B4 appended
# on purpose OUTSIDE it: 2026-10-29 at venue 1. Without that row `upcoming`
# and the default window are indistinguishable and nothing here could tell
# them apart.

CHARLIE_PARR_IN_WINDOW = ["2026-09-28", "2026-10-07", "2026-10-08", "2026-10-20"]


def _dates(query: str) -> list[str]:
    # The dates of the shows `GET /shows?<query>` returns, in the order the
    # API returned them (date, then time), so a test can compare a whole
    # result against a list written out by hand.
    return [s["date"] for s in client.get(f"/shows?{query}").json()["shows"]]


def test_upcoming_reaches_past_the_default_window() -> None:
    """Proves: `upcoming=true` returns shows beyond the 28-day default window.

    The contrast is in one test on purpose: the same artist, with and
    without the parameter, differs by exactly the 2026-10-29 show. If the
    parameter were ignored (FastAPI silently ignores unknown query
    parameters) both requests would return four shows and this fails on
    the content, not on a status code.
    """
    without = client.get("/shows?artist_id=1").json()
    assert [s["date"] for s in without["shows"]] == CHARLIE_PARR_IN_WINDOW
    assert without["end"] == "2026-10-25"

    upcoming = client.get("/shows?artist_id=1&upcoming=true").json()
    assert [s["date"] for s in upcoming["shows"]] == [*CHARLIE_PARR_IN_WINDOW, "2026-10-29"]
    # The echoed range: from the server's today to the last show returned.
    assert upcoming["start"] == "2026-09-28"
    assert upcoming["end"] == "2026-10-29"


def test_upcoming_starts_from_the_servers_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves: shows before the server's "today" are excluded, and "today" is the server's.

    The router reads `data.START` (the sample data's pinned "today") at
    call time, so moving it moves the lower bound. A client that computed
    its own start date would not be affected by this -- which is the
    point: the server decides what "upcoming" means.
    """
    monkeypatch.setattr(data, "START", datetime.date(2026, 10, 8))
    body = client.get("/shows?artist_id=1&upcoming=true").json()
    assert [s["date"] for s in body["shows"]] == ["2026-10-08", "2026-10-20", "2026-10-29"]
    assert body["start"] == "2026-10-08"


def test_upcoming_with_no_matches_is_a_valid_empty_range() -> None:
    """Proves: no upcoming shows is a 200 with an empty list and start == end, not an error.

    `end` falls back to `start` when nothing matched, so the echoed range
    is always valid (end >= start) and the page can still print "from ...".
    """
    response = client.get("/shows?artist_id=9999&upcoming=true")
    assert response.status_code == 200
    body = response.json()
    assert body["shows"] == []
    assert body["start"] == body["end"] == "2026-09-28"


def test_upcoming_combines_with_the_other_filters() -> None:
    """Proves: `upcoming` is one more AND-ed filter, like any other.

    Venue 3 (Zhora Darling) hosts two of Charlie Parr's five shows
    (2026-10-07 and 2026-10-20); the other three are at venue 1. And
    `venue_id=1` alone, upcoming, includes the 2026-10-29 show.
    """
    assert _dates("venue_id=3&artist_id=1&upcoming=true") == ["2026-10-07", "2026-10-20"]
    venue_one = _dates("venue_id=1&upcoming=true")
    assert "2026-10-29" in venue_one
    assert min(venue_one) >= "2026-09-28"


@pytest.mark.parametrize(
    "query",
    [
        # No venue or artist: every show in the metro with no upper bound is the
        # unbounded scan MAX_RANGE exists to prevent. One artist or venue
        # bounds the result by what they can play.
        "upcoming=true",
        # An explicit range contradicts "from today, open-ended"; silently
        # preferring one would hide a client bug.
        "artist_id=1&upcoming=true&start=2026-10-01",
        "artist_id=1&upcoming=true&end=2026-11-30",
    ],
)
def test_upcoming_rejects_contradictory_or_unbounded_requests(query: str) -> None:
    """Proves: the two guards on `upcoming` answer 422 rather than guessing."""
    assert client.get(f"/shows?{query}").status_code == 422


def test_upcoming_false_changes_nothing() -> None:
    """Proves: an explicit `upcoming=false` is the same request as leaving it out.

    A client that always sends the parameter (true or false) must not get
    different behaviour for false.
    """
    assert _dates("artist_id=1&upcoming=false") == _dates("artist_id=1")


def test_openapi_exposes_the_upcoming_parameter() -> None:
    """Proves: `upcoming` is in GET /shows's documented parameters.

    That document is what `make types` turns into lib/api-types.ts; if the
    parameter weren't declared on the route it would never reach the
    frontend's types (same reasoning as test_openapi_exposes_the_response_schemas).
    """
    parameters = app.openapi()["paths"]["/shows"]["get"]["parameters"]
    assert "upcoming" in {p["name"] for p in parameters}
