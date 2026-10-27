"""Tests for the read API's routes, against a real Postgres (C2).

Until C2 these routes served an in-memory sample and the tests pinned shape and status codes only. They
now run the real app over the sample world loaded into the test database (`sample_client`, in
conftest.py), so they pin the data as well: the URLs, the filter semantics, the error codes and what the
queries return.

Where the expected values come from. The sample world's rows are written out in
`app/testing/sample_data.py`; the expectations here are worked out by hand from those rows and the
calendar, never read back from the code under test. Tests that need a case the sample doesn't have insert
their own rows (small helpers below) instead of editing the sample: it is the shared baseline for the
fixtures and the browser specs.

The 404 assertions exist because the first hand-written version of get_venue used `== "None"` instead of
`is None`, which returned a 500 for every unknown id. The happy path passed by hand; only the miss path
caught it.

Sections: the contract the routes always had (ported from the sample-backed version), then what only a
database can get wrong (removed shows, metro scoping, inheritance, ordering, the clock), then the
statement count.
"""

import datetime
from collections.abc import Sequence

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.db.models import Artist, Event, Metro, Show, ShowArtist, Venue
from app.enums import AgeRestriction, Seating, Setting, ShowStatus
from app.main import app
from app.testing import sample_data as data
from app.testing.api_client import api_client

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


async def _settle(session: AsyncSession) -> None:
    """Flush a test's edits and forget every loaded object, so the next request re-reads Postgres.

    A route reads through the same session the test wrote with. Without the expunge it would be handed
    the test's in-memory objects, which can differ from what the database stores (C2-PR1-2).
    """
    await session.flush()
    session.expunge_all()


async def _add_show(
    session: AsyncSession,
    *,
    venue_id: int,
    date: datetime.date,
    start: datetime.time | None = None,
    lineup: Sequence[tuple[int, int | None]] = (),
    **columns: object,
) -> int:
    """Insert a show (and its lineup of `(artist_id, sequence_number)` pairs); return its id.

    The tests that need a case the sample world doesn't have build it with this, so the shared sample
    stays as the fixtures and browser specs expect it.
    """
    show = Show(venue_id=venue_id, date=date, start_time=start, **columns)
    session.add(show)
    await session.flush()
    for artist_id, sequence_number in lineup:
        session.add(ShowArtist(show_id=show.id, artist_id=artist_id, sequence_number=sequence_number))
    await session.flush()
    return show.id


async def _dates(client: AsyncClient, query: str) -> list[str]:
    """The dates of the shows `GET /shows?<query>` returns, in the order the API returned them."""
    return [s["date"] for s in (await client.get(f"/shows?{query}")).json()["shows"]]


# ---------------------------------------------------------------------
# The contract the routes always had (ported from the sample-backed tests)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("/shows", "shows"),
        ("/venues", "venues"),
        ("/artists", "artists"),
        ("/calendar/months", "months"),
    ],
)
async def test_list_endpoints_return_their_envelope(sample_client: AsyncClient, path: str, key: str) -> None:
    # Proves (api-contract.md §3, "Envelopes, not bare arrays"): each list endpoint answers 200 with an object holding a named
    # array (`shows`, `venues`, `artists`, `months`). The generated TypeScript and the frontend's reads depend on that shape.
    # Shape only: no data is asserted.
    response = await sample_client.get(path)
    assert response.status_code == 200
    assert isinstance(response.json()[key], list)


@pytest.mark.parametrize("path", ["/venues", "/artists"])
async def test_lists_are_alphabetical(sample_client: AsyncClient, path: str) -> None:
    # Proves (alpha-build-plan.md, B4: "flat alphabetical lists"): /venues and /artists are ordered by name, ignoring case
    # (C2-D5). The expected order is `sorted()` of the names the response itself returned, so this checks the ordering, not
    # which names are listed.
    names = [row["name"] for row in (await sample_client.get(path)).json()[path.strip("/")]]
    assert names == sorted(names, key=str.casefold)


@pytest.mark.parametrize(
    ("path", "expected"), [("/shows/999", 404), ("/venues/99", 404), ("/artists/99", 404)]
)
async def test_unknown_id_is_404_not_500(sample_client: AsyncClient, path: str, expected: int) -> None:
    # Proves: an id that matches no row is a 404 on all three detail routes, not a 500 (the module docstring's `== "None"`
    # bug). 999 and 99 are above every id the sample world loads (shows 1-26, venues 1-4, artists 1-10).
    assert (await sample_client.get(path)).status_code == expected


@pytest.mark.parametrize("path", ["/shows/abc", "/venues/abc", "/artists/abc"])
async def test_non_integer_id_is_422(sample_client: AsyncClient, path: str) -> None:
    # Proves: an id that is not an integer is a 422 on all three detail routes. If a route's path parameter lost its `int`
    # annotation, "abc" would reach the lookup and become a 404 (or a 500) instead. Free from the annotation; no code in
    # the route does this check.
    assert (await sample_client.get(path)).status_code == 422


async def test_detail_endpoints_return_the_requested_record(sample_client: AsyncClient) -> None:
    # Proves: each detail route returns the record whose id was asked for. Venue 3, artist 1 and show 2 are rows in the
    # sample world, loaded with their sample ids.
    assert (await sample_client.get("/venues/3")).json()["id"] == 3
    assert (await sample_client.get("/artists/1")).json()["id"] == 1
    assert (await sample_client.get("/shows/2")).json()["id"] == 2


async def test_show_detail_resolves_inherited_venue_fields(sample_client: AsyncClient) -> None:
    # Proves (api-contract.md §5): the read API returns the effective value of an inherited field, resolved on the server.
    # The expected `twenty_one_plus` and alcohol-serving come from show 2's venue (venue 3, Zhora Darling) in the sample
    # world, set by hand there. Show 2 sets none of the four inherited fields itself, so these come from its venue.
    show = (await sample_client.get("/shows/2")).json()
    assert show["age_restriction"] == "twenty_one_plus"
    assert show["serves_alcohol"] is True


async def test_date_range_filters(sample_client: AsyncClient) -> None:
    # Proves (api-contract.md §2, §3): `start` and `end` bound the shows returned, and the response echoes the range it
    # used. The bounds are the literals in the URL; ISO dates compare correctly as strings.
    body = (await sample_client.get("/shows?start=2026-10-01&end=2026-10-07")).json()
    assert body["start"] == "2026-10-01"
    assert body["end"] == "2026-10-07"
    assert body["shows"]
    assert all("2026-10-01" <= s["date"] <= "2026-10-07" for s in body["shows"])


async def test_repeated_filter_values_are_or_ed(sample_client: AsyncClient) -> None:
    # Proves (api-contract.md §2, "Filtering"): repeating `venue_id` means "either venue", so venues 1 and 3 together return
    # exactly venue 1's shows plus venue 3's (no show is at both). The expected count is the sum of the two single-venue
    # responses, not a literal. Catches mutation C2-M9 (OR turned into AND).
    one = len((await sample_client.get("/shows?venue_id=1")).json()["shows"])
    three = len((await sample_client.get("/shows?venue_id=3")).json()["shows"])
    both = len((await sample_client.get("/shows?venue_id=1&venue_id=3")).json()["shows"])
    assert one and three
    assert both == one + three


async def test_different_filters_are_and_ed(sample_client: AsyncClient) -> None:
    # Proves (api-contract.md §2, "Filtering"): different filters are AND-ed. Venue 3 with artist 1 is a non-empty subset of
    # venue 3's shows: non-empty because artist 1 plays venue 3 in the sample world, a subset because AND cannot add shows.
    venue_only = len((await sample_client.get("/shows?venue_id=3")).json()["shows"])
    combined = len((await sample_client.get("/shows?venue_id=3&artist_id=1")).json()["shows"])
    assert 0 < combined <= venue_only


async def test_artist_filter_matches_anywhere_in_the_lineup(sample_client: AsyncClient) -> None:
    # Proves: the artist filter matches an artist anywhere in a lineup, not only as headliner. Artist 1 is third on one sample
    # bill (hand-checked in `sample_data.py`: the 2026-10-20 Zhora Darling bill of Humbird, Lanue and Charlie Parr).
    shows = (await sample_client.get("/shows?artist_id=1")).json()["shows"]
    assert any(
        entry["artist"]["id"] == 1 and entry["sequence_number"] > 1
        for show in shows
        for entry in show["lineup"]
    )


async def test_a_two_act_match_returns_the_show_once(sample_client: AsyncClient) -> None:
    # Proves: asking for two artists who share one bill returns that show once, not once per matching act. Show 7's bill is
    # Jaedyn James, Tarnation and Beasthead (artists 6, 10, 9; hand-read from `_SHOW_ROWS`, 2026-10-07 at The Terminal Bar).
    # A filter written as a join on the lineup repeats a row per matching act; `EXISTS` does not (C2-K1).
    shows = (await sample_client.get("/shows?artist_id=6&artist_id=10&artist_id=9&start=2026-10-07&end=2026-10-07")).json()["shows"]
    ids = [s["id"] for s in shows]
    assert len(ids) == len(set(ids))
    assert 8 in ids


async def test_shows_are_ordered_by_date_then_time(sample_client: AsyncClient) -> None:
    # Proves: /shows returns shows ordered by date, then start time, with a show that has no time after the timed ones on
    # its date. That is the router's own rule (`queries._ordering`'s docstring explains why). The expected order is the
    # response sorted by that key, so this checks order only.
    shows = (await sample_client.get("/shows")).json()["shows"]
    keys = [(s["date"], s["start_time"] is None, s["start_time"] or "") for s in shows]
    assert keys == sorted(keys)


@pytest.mark.parametrize(
    "query",
    [
        "start=2026-10-10&end=2026-10-01",  # end before start
        "start=2020-01-01&end=2030-01-01",  # wider than MAX_RANGE
    ],
)
async def test_invalid_ranges_are_rejected(sample_client: AsyncClient, query: str) -> None:
    # Proves: an end before the start, and a range wider than `MAX_RANGE`, are each a 422 rather than an empty or an
    # unbounded answer. The rules are the router's (`app/routers/shows.py`, the two `HTTPException(422)` checks), not
    # the contract's, which mentions `MAX_RANGE` only for `upcoming=true` (§2). Both queries are written out above.
    assert (await sample_client.get(f"/shows?{query}")).status_code == 422


def test_openapi_exposes_the_response_schemas() -> None:
    """Proves: the OpenAPI document lists the response models the frontend's types are generated from.

    If a route stops declaring its return type, its models silently drop out of components.schemas and the
    generated TypeScript loses them: a failure that otherwise surfaces as a missing frontend type long after
    the change that caused it.
    """
    schemas = app.openapi()["components"]["schemas"]
    for name in ("ShowSummary", "ShowDetail", "VenueDetail", "ArtistDetail", "LineupEntry"):
        assert name in schemas


# --- GET /metro (B2) ------------------------------------------------------
# The layout's footer and <meta description> read the metro name from here
# (alpha-build-plan.md v0.1-G24) instead of a hard-coded literal.


async def test_metro_returns_the_live_metro(sample_client: AsyncClient) -> None:
    """Proves: /metro answers 200 with the single live metro's id, name and timezone.

    Expected values come from `sample_data.METRO`, which the loader wrote to the database, so this pins
    the route to the stored row and the response shape.
    """
    response = await sample_client.get("/metro")
    assert response.status_code == 200
    assert response.json() == {
        "id": data.METRO.id,
        "name": data.METRO.name,
        "timezone": data.METRO.timezone,
    }


def test_openapi_exposes_the_metro_route() -> None:
    """Proves: /metro is in the OpenAPI document and its 200 response is MetroSummary.

    Deliberately not "add MetroSummary to the schema-name check above": MetroSummary is already in
    components.schemas, nested inside VenueDetail, so that assertion would pass before the route exists
    (B2-PR1-5). What the generated TypeScript needs is the *path* with a typed response; this fails if the
    return annotation is dropped.
    """
    paths = app.openapi()["paths"]
    assert "/metro" in paths
    ref = paths["/metro"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ref == {"$ref": "#/components/schemas/MetroSummary"}


# --- GET /shows?upcoming=true (B4-D2) ----------------------
# The artist page lists EVERY future show of an artist, not just the next four weeks. The client can't ask
# for that with dates (the server owns "now", api-contract.md §3), so `upcoming=true` means "from the
# server's today, no upper limit".
#
# Where the expected values come from: worked out by hand from the rows in sample_data.py, not read back
# from the code under test. Charlie Parr is artist 1 and plays: 2026-09-28 (venue 1), 2026-10-07 (venue 3),
# 2026-10-08 (venue 1), 2026-10-20 (venue 3) -- all inside the default window, which is 2026-09-28..2026-10-25
# -- plus the one row B4 appended on purpose OUTSIDE it: 2026-10-29 at venue 1. Without that row `upcoming`
# and the default window are indistinguishable and nothing here could tell them apart.

CHARLIE_PARR_IN_WINDOW = ["2026-09-28", "2026-10-07", "2026-10-08", "2026-10-20"]


async def test_upcoming_reaches_past_the_default_window(sample_client: AsyncClient) -> None:
    """Proves: `upcoming=true` returns shows beyond the 28-day default window.

    The contrast is in one test on purpose: the same artist, with and without the parameter, differs by
    exactly the 2026-10-29 show. If the parameter were ignored (FastAPI silently ignores unknown query
    parameters) both requests would return four shows and this fails on the content, not on a status code.
    """
    without = (await sample_client.get("/shows?artist_id=1")).json()
    assert [s["date"] for s in without["shows"]] == CHARLIE_PARR_IN_WINDOW
    assert without["end"] == "2026-10-25"

    upcoming = (await sample_client.get("/shows?artist_id=1&upcoming=true")).json()
    assert [s["date"] for s in upcoming["shows"]] == [*CHARLIE_PARR_IN_WINDOW, "2026-10-29"]
    # The echoed range: from the server's today to the last show returned.
    assert upcoming["start"] == "2026-09-28"
    assert upcoming["end"] == "2026-10-29"


async def test_upcoming_starts_from_the_servers_today(db_session: AsyncSession) -> None:
    """Proves: shows before the server's "today" are excluded, and "today" is the server's.

    The clock the API reads is moved to October 8 (noon in Minneapolis); the lower bound moves with it. A
    client that computed its own start date would not be affected by this, which is the point: the server
    decides what "upcoming" means.
    """
    await data.load_sample_data(db_session)
    await _settle(db_session)
    now = datetime.datetime(2026, 10, 8, 17, 0, tzinfo=datetime.UTC)
    async with api_client(db_session, now) as client:
        body = (await client.get("/shows?artist_id=1&upcoming=true")).json()
    assert [s["date"] for s in body["shows"]] == ["2026-10-08", "2026-10-20", "2026-10-29"]
    assert body["start"] == "2026-10-08"


async def test_upcoming_with_no_matches_is_a_valid_empty_range(sample_client: AsyncClient) -> None:
    """Proves: no upcoming shows is a 200 with an empty list and start == end, not an error.

    `end` falls back to `start` when nothing matched, so the echoed range is always valid (end >= start)
    and the page can still print "from ...".
    """
    response = await sample_client.get("/shows?artist_id=9999&upcoming=true")
    assert response.status_code == 200
    body = response.json()
    assert body["shows"] == []
    assert body["start"] == body["end"] == "2026-09-28"


async def test_upcoming_combines_with_the_other_filters(sample_client: AsyncClient) -> None:
    """Proves: `upcoming` is one more AND-ed filter, like any other.

    Venue 3 (Zhora Darling) hosts two of Charlie Parr's five shows (2026-10-07 and 2026-10-20); the other
    three are at venue 1. And `venue_id=1` alone, upcoming, includes the 2026-10-29 show.
    """
    assert await _dates(sample_client, "venue_id=3&artist_id=1&upcoming=true") == ["2026-10-07", "2026-10-20"]
    venue_one = await _dates(sample_client, "venue_id=1&upcoming=true")
    assert "2026-10-29" in venue_one
    assert min(venue_one) >= "2026-09-28"


@pytest.mark.parametrize(
    "query",
    [
        # No venue or artist: every show in the metro with no upper bound is the unbounded scan MAX_RANGE exists
        # to prevent. One artist or venue bounds the result by what they can play.
        "upcoming=true",
        # An explicit range contradicts "from today, open-ended"; silently preferring one would hide a client bug.
        "artist_id=1&upcoming=true&start=2026-10-01",
        "artist_id=1&upcoming=true&end=2026-11-30",
    ],
)
async def test_upcoming_rejects_contradictory_or_unbounded_requests(sample_client: AsyncClient, query: str) -> None:
    """Proves: the two guards on `upcoming` answer 422 rather than guessing."""
    assert (await sample_client.get(f"/shows?{query}")).status_code == 422


async def test_upcoming_false_changes_nothing(sample_client: AsyncClient) -> None:
    """Proves: an explicit `upcoming=false` is the same request as leaving it out.

    A client that always sends the parameter (true or false) must not get different behaviour for false.
    """
    assert await _dates(sample_client, "artist_id=1&upcoming=false") == await _dates(sample_client, "artist_id=1")


def test_openapi_exposes_the_upcoming_parameter() -> None:
    """Proves: `upcoming` is in GET /shows's documented parameters.

    That document is what `make types` turns into lib/api-types.ts; if the parameter weren't declared on the
    route it would never reach the frontend's types (same reasoning as test_openapi_exposes_the_response_schemas).
    """
    parameters = app.openapi()["paths"]["/shows"]["get"]["parameters"]
    assert "upcoming" in {p["name"] for p in parameters}


# ---------------------------------------------------------------------
# What only a database can get wrong (C2-D5, C2-D6)
# ---------------------------------------------------------------------


async def test_a_removed_show_is_invisible_everywhere(sample_client: AsyncClient, db_session: AsyncSession) -> None:
    """Proves (api-contract.md §2, "Soft-deleted shows"): a `removed` show appears in no read response.

    Show 2 (2026-09-30, Zhora Darling) is marked removed. It leaves the list, its detail is a 404, and
    September's month count falls from 3 (shows 1, 2 and 3 are the only September rows in the sample: offsets 0,
    2 and 2 from 2026-09-28) to 2. Catches mutation C2-M1 (dropping the status filter from one query).
    """
    show = await db_session.get(Show, 2)
    assert show is not None
    show.status = ShowStatus.REMOVED
    await _settle(db_session)

    listed = [s["id"] for s in (await sample_client.get("/shows")).json()["shows"]]
    assert 2 not in listed
    assert (await sample_client.get("/shows/2")).status_code == 404
    months = {(m["year"], m["month"]): m["show_count"] for m in (await sample_client.get("/calendar/months")).json()["months"]}
    assert months[(2026, 9)] == 2


async def test_a_month_with_only_removed_shows_disappears(sample_client: AsyncClient, db_session: AsyncSession) -> None:
    """Proves: removing every show in a month removes the month from the dropdown's list, not just its count.

    Shows 1, 2 and 3 are all of September in the sample world (see the test above).
    """
    for show_id in (1, 2, 3):
        show = await db_session.get(Show, show_id)
        assert show is not None
        show.status = ShowStatus.REMOVED
    await _settle(db_session)

    months = [(m["year"], m["month"]) for m in (await sample_client.get("/calendar/months")).json()["months"]]
    assert months == [(2026, 10)]


async def test_inherited_fields_use_is_none_not_truthiness(sample_client: AsyncClient, db_session: AsyncSession) -> None:
    """Proves (api-contract.md §5, C2-D6): a show's own value wins over its venue's, including `False`.

    Show 2 is at venue 3, which serves alcohol and is twenty-one-plus, indoor and standing. The show then
    overrides `serves_alcohol` with False, which a `show.x or venue.x` resolution would discard because
    False is falsy (mutation C2-M2). It overrides `age_restriction`, `setting` and `seating` with values that
    differ from the venue's. Show 1 is at venue 1, which sets none of the four, and sets none itself, so all
    four are null: absence is "not stated", not a default.
    """
    show = await db_session.get(Show, 2)
    assert show is not None
    show.serves_alcohol = False
    show.age_restriction = AgeRestriction.ALL_AGES
    show.setting = Setting.OUTDOOR
    show.seating = Seating.SEATED
    await _settle(db_session)

    body = (await sample_client.get("/shows/2")).json()
    assert body["serves_alcohol"] is False
    assert body["age_restriction"] == "all_ages"
    assert body["setting"] == "outdoor"
    assert body["seating"] == "seated"

    neither = (await sample_client.get("/shows/1")).json()
    assert (neither["serves_alcohol"], neither["age_restriction"], neither["setting"], neither["seating"]) == (
        None,
        None,
        None,
        None,
    )


async def test_a_show_returns_its_event(sample_client: AsyncClient, db_session: AsyncSession) -> None:
    """Proves (C2-PR1-3): `ShowDetail.event` is `{id, name}` for a show that belongs to an event and null otherwise.

    The easy implementation returns null always, and nothing else would notice until the first festival
    show. Expected values are the two rows this test writes.
    """
    festival = Event(name="Summer Fest")
    db_session.add(festival)
    await db_session.flush()
    show = await db_session.get(Show, 2)
    assert show is not None
    show.event_id = festival.id
    event_id = festival.id
    await _settle(db_session)

    assert (await sample_client.get("/shows/2")).json()["event"] == {"id": event_id, "name": "Summer Fest"}
    assert (await sample_client.get("/shows/1")).json()["event"] is None


async def test_missing_array_columns_come_back_empty(sample_client: AsyncClient, db_session: AsyncSession) -> None:
    """Proves (C2-D5): a venue whose `phone_numbers`, `emails` and `extra_metadata` are NULL answers `[]`, `[]` and `{}`.

    The columns are nullable and the response model's defaults are empty collections; a route that passed the
    NULL through would fail response validation, or send `null` where the type says a list.
    """
    venue = await db_session.get(Venue, 1)
    assert venue is not None
    venue.phone_numbers = None
    venue.emails = None
    venue.extra_metadata = None
    await _settle(db_session)

    body = (await sample_client.get("/venues/1")).json()
    assert (body["phone_numbers"], body["emails"], body["extra_metadata"]) == ([], [], {})


async def test_other_metros_never_leak_in(sample_client: AsyncClient, db_session: AsyncSession) -> None:
    """Proves (api-contract.md §2, "Metro scoping"): a second metro's venue and show appear in none of this metro's responses.

    The live metro is the lowest-id row (C2-D5). Everything the second metro owns must be invisible: absent from
    the lists and the month counts, and a 404 by id. Catches mutation C2-M5 (dropping the metro scope).
    """
    before_months = (await sample_client.get("/calendar/months")).json()
    elsewhere = Metro(name="Elsewhere", timezone="America/New_York")
    db_session.add(elsewhere)
    await db_session.flush()
    venue = Venue(metro_id=elsewhere.id, name="Elsewhere Hall", calendar_url="https://example.com/elsewhere")
    db_session.add(venue)
    await db_session.flush()
    venue_id = venue.id
    show_id = await _add_show(db_session, venue_id=venue_id, date=datetime.date(2026, 10, 5), lineup=[(1, 1)])
    await _settle(db_session)

    assert "Elsewhere Hall" not in [v["name"] for v in (await sample_client.get("/venues")).json()["venues"]]
    assert show_id not in [s["id"] for s in (await sample_client.get("/shows")).json()["shows"]]
    assert (await sample_client.get("/calendar/months")).json() == before_months
    assert (await sample_client.get(f"/venues/{venue_id}")).status_code == 404
    assert (await sample_client.get(f"/shows/{show_id}")).status_code == 404


async def test_an_empty_database_answers_503_naming_the_seed(db_session: AsyncSession) -> None:
    """Proves (C2-D3): a migrated database with no metro row answers 503 on the metro-scoped routes, with a `detail`
    that says to run the seed, while `/health` (which touches no data) still answers 200.

    No sample world is loaded, so there is no metro.
    """
    async with api_client(db_session) as client:
        for path in ("/metro", "/venues", "/shows", "/calendar/months"):
            response = await client.get(path)
            assert response.status_code == 503, path
            assert "seed" in response.json()["detail"]
        assert (await client.get("/health")).status_code == 200


# --- Ordering --------------------------------------------------------------


async def test_shows_tie_break_by_venue_name_then_id(sample_client: AsyncClient, db_session: AsyncSession) -> None:
    """Proves (C2-D5): on one date, shows sort by start time, then venue name, then id, with an untimed show last.

    Four shows are added on 2026-10-22, which already has one show at 21:00 (show 20, The Terminal Bar). In
    insertion order: Zhora Darling 20:00 (27), The White Squirrel Bar 20:00 (28 and 29, identical), and an
    untimed one at The Midway Saloon (30). Expected order, by hand: the two White Squirrel shows (venue
    "The White Squirrel Bar" sorts before "Zhora Darling") by id, then Zhora, then the 21:00 show, then the
    untimed one. Catches mutation C2-M4 (dropping the sort).
    """
    day = datetime.date(2026, 10, 22)
    eight = datetime.time(20, 0)
    zhora = await _add_show(db_session, venue_id=3, date=day, start=eight, lineup=[(1, 1)])
    squirrel_a = await _add_show(db_session, venue_id=1, date=day, start=eight, lineup=[(2, 1)])
    squirrel_b = await _add_show(db_session, venue_id=1, date=day, start=eight, lineup=[(3, 1)])
    untimed = await _add_show(db_session, venue_id=2, date=day, lineup=[(4, 1)])
    await _settle(db_session)

    shows = (await sample_client.get("/shows?start=2026-10-22&end=2026-10-22")).json()["shows"]
    assert [s["id"] for s in shows] == [squirrel_a, squirrel_b, zhora, 20, untimed]


async def test_lineups_are_ordered_by_sequence_with_unnumbered_acts_last(
    sample_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Proves (C2-D5): a lineup is sorted by `sequence_number`, acts with none after the numbered ones, ties by artist id.

    The worker leaves the number null when a listing gives no order (schemas.py). One show gets artists 5 (no
    number), 6 (2), 7 (1) and 4 (no number); expected by hand: 7, 6, then the unnumbered 4 and 5 by id.
    Catches mutation C2-M4.
    """
    show_id = await _add_show(
        db_session, venue_id=1, date=datetime.date(2026, 10, 21), lineup=[(5, None), (6, 2), (7, 1), (4, None)]
    )
    await _settle(db_session)

    lineup = (await sample_client.get(f"/shows/{show_id}")).json()["lineup"]
    assert [e["artist"]["id"] for e in lineup] == [7, 6, 4, 5]


async def test_lists_ignore_database_collation(sample_client: AsyncClient, db_session: AsyncSession) -> None:
    """Proves (C2-D5): /venues sorts by name ignoring case, whatever the database's collation does.

    Three venues are added whose order differs between a case-sensitive and a case-insensitive sort:
    "Zebra Room", "apple hall" and "Mortimer's". A codepoint sort puts the lowercase one last. Expected by
    hand, case-folded: apple hall, Mortimer's, Zebra Room.
    """
    for name in ("Zebra Room", "apple hall", "Mortimer's"):
        db_session.add(Venue(metro_id=1, name=name, calendar_url="https://example.com/x"))
    await _settle(db_session)

    names = [v["name"] for v in (await sample_client.get("/venues")).json()["venues"]]
    assert [n for n in names if n in ("Zebra Room", "apple hall", "Mortimer's")] == ["apple hall", "Mortimer's", "Zebra Room"]


# --- The clock ---------------------------------------------------------------


async def test_the_default_window_starts_at_the_metros_today(db_session: AsyncSession) -> None:
    """Proves (C2-D5, api-contract.md §3): the default window starts on the metro's local date, not the UTC date.

    At 03:30 UTC on September 29 it is 22:30 on September 28 in Minneapolis (CDT, UTC-5), so the echoed
    `start` is the 28th. A window starting on the UTC date would be a day ahead for every evening reader.
    Catches mutation C2-M3.
    """
    await data.load_sample_data(db_session)
    await _settle(db_session)
    async with api_client(db_session, datetime.datetime(2026, 9, 29, 3, 30, tzinfo=datetime.UTC)) as client:
        body = (await client.get("/shows")).json()
    assert body["start"] == "2026-09-28"
    assert body["end"] == "2026-10-25"


async def test_months_are_future_facing(db_session: AsyncSession) -> None:
    """Proves (requirements-initial.md, "months list is only future facing"; C2-D5): a month with no show on or
    after the metro's today is not offered, and the count covers only the shows still to come.

    The clock is October 20 (noon in Minneapolis). September's three shows are past, so it is gone. October's
    shows on or after the 20th, by hand from the sample rows: the three week-four rows (offsets 22, 23 and 24 are
    the 20th, 21st and 22nd... see below) and the 26th and the October 29 row. Offsets from 2026-09-28: 22 -> Oct 20,
    23 -> Oct 21, 24 -> Oct 22, 26 -> Oct 24, 31 -> Oct 29: five shows.
    """
    await data.load_sample_data(db_session)
    await _settle(db_session)
    async with api_client(db_session, datetime.datetime(2026, 10, 20, 17, 0, tzinfo=datetime.UTC)) as client:
        months = (await client.get("/calendar/months")).json()["months"]
    assert months == [{"year": 2026, "month": 10, "show_count": 5}]


async def test_the_window_crosses_the_year(db_session: AsyncSession) -> None:
    """Proves: a window that starts in one year and ends in the next works, and the months list orders December
    before January.

    The clock is December 28, 2026 (noon in Minneapolis, CST, UTC-6, so 18:00 UTC). Shows on December 30 and
    January 2 are inserted. The default window is 28 days from the 28th: it ends on 2027-01-24 (December 28 + 27
    days: 3 more December days to the 31st, then 24 of January). Both shows fall inside, and the months are
    [2026-12, 2027-01]. The sample rows are all in September and October, so they are past and play no part.
    """
    await data.load_sample_data(db_session)
    dec = await _add_show(db_session, venue_id=1, date=datetime.date(2026, 12, 30), lineup=[(1, 1)])
    jan = await _add_show(db_session, venue_id=1, date=datetime.date(2027, 1, 2), lineup=[(1, 1)])
    await _settle(db_session)
    async with api_client(db_session, datetime.datetime(2026, 12, 28, 18, 0, tzinfo=datetime.UTC)) as client:
        window = (await client.get("/shows")).json()
        months = (await client.get("/calendar/months")).json()["months"]
    assert (window["start"], window["end"]) == ("2026-12-28", "2027-01-24")
    assert [s["id"] for s in window["shows"]] == [dec, jan]
    assert [(m["year"], m["month"]) for m in months] == [(2026, 12), (2027, 1)]


# ---------------------------------------------------------------------
# The statement count (no N+1)
# ---------------------------------------------------------------------


async def test_the_statement_count_does_not_grow_with_the_number_of_shows(
    sample_client: AsyncClient, db_session: AsyncSession, db_conn: AsyncConnection
) -> None:
    """Proves (C2-K2): `GET /shows` runs the same number of SQL statements for 26 shows as for 226.

    A route that loads each show's venue or lineup one query at a time would run a statement per show. The
    count is taken with a cursor-level listener on the test's connection. With `lazy="raise"` (C2-D4) a missed
    eager load fails the first route test instead; this test pins the number itself, so a loader that
    eagerly loads in a loop (still correct, still slow) is caught too. Catches mutation C2-M6.
    """
    statements: list[str] = []

    def count(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    event.listen(db_conn.sync_connection, "before_cursor_execute", count)
    try:
        await sample_client.get("/shows")
        small = len(statements)

        for i in range(200):
            show_id = await _add_show(
                db_session,
                venue_id=1 + i % 4,
                date=data.START + datetime.timedelta(days=i % 20),
                start=datetime.time(20, 0),
                lineup=[(1 + i % 10, 1), (1 + (i + 3) % 10, 2)],
            )
            assert show_id
        await _settle(db_session)

        statements.clear()
        body = (await sample_client.get("/shows")).json()
        large = len(statements)
    finally:
        event.remove(db_conn.sync_connection, "before_cursor_execute", count)

    assert len(body["shows"]) > 200
    assert large == small


async def test_artists_are_global_not_metro_scoped(sample_client: AsyncClient, db_session: AsyncSession) -> None:
    """Proves (api-contract.md §2, /artists): the artist list is not filtered by metro, because acts tour.

    An artist is added with no show anywhere; it still appears in /artists. Expected: the new name is present.
    """
    db_session.add(Artist(name="Touring Act"))
    await _settle(db_session)
    names = [a["name"] for a in (await sample_client.get("/artists")).json()["artists"]]
    assert "Touring Act" in names
