"""The sample world: one small, deterministic calendar that tests and the end-to-end job share.

What this is (C2-D1). Four venues, ten artists and 26 invented shows, written once as `schemas.py`
objects. Three things read it, and nothing under `app/` outside this package may (a test enforces it):

  * `scripts/generate_fixtures.py` turns it into the frontend's JSON fixtures, with no database
    (`fixture_payloads`).
  * The route tests and the end-to-end job load it into Postgres (`load_sample_data`) and call the
    real routes, so what they assert is the API reading a database, not this module answering.
  * `test_fixtures_agree.py` pins the two together: the routes over the loaded world must return what
    the fixtures hold, so neither can drift without a red test.

Until C2 this module stood in for the database and the routers served it directly; it was
"TEMPORARY" and was to be deleted. It is not deleted because a calendar test needs a known answer
before it runs, which a live scrape cannot give, and CI has no route to venue sites.

The data is invented but deliberately not tidy. It includes the cases a real venue calendar produces
and a demo dataset usually omits: shows with no listed start time, multi-act bills, a free show, a
day with nothing on it, and one artist playing two venues. A calendar UI built against only clean
rows gets built assuming clean rows. New awkward cases belong in the test that finds them, as rows
that test inserts itself, not here: this world is the shared baseline and changing it moves the
fixtures and the browser specs.

Deterministic on purpose: a fixed START date rather than date.today(), and `FIXED_NOW` for the clock
the API reads (C2-D2), so the generated JSON fixtures produce an empty diff unless the contract
actually changed.
"""

import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artist, Metro, Show, ShowArtist, Venue
from app.enums import (
    AgeRestriction,
    ArtistFormat,
    ArtistRepertoire,
    Seating,
    Setting,
    VenueType,
)
from app.schemas import (
    ArtistDetail,
    ArtistListResponse,
    ArtistSummary,
    CalendarMonth,
    CalendarMonthsResponse,
    LineupEntry,
    MetroSummary,
    ShowDetail,
    ShowListResponse,
    ShowSummary,
    VenueDetail,
    VenueListResponse,
    VenueSummary,
)

# The window the home page covers: a pinned date plus four weeks.
START = datetime.date(2026, 9, 28)
END = START + datetime.timedelta(days=27)

# The instant the API's clock reads in tests that want the sample's window: noon in Minneapolis
# (CDT, UTC-5) on START. Noon rather than midnight so no timezone arithmetic can push the metro's
# date to the neighbouring day (C2-D2). With the API's clock here, the default window is exactly
# START..END, which is what lib/fixtures/shows.json claims.
FIXED_NOW = datetime.datetime(2026, 9, 28, 17, 0, tzinfo=datetime.UTC)

METRO = MetroSummary(id=1, name="Minneapolis/St. Paul", timezone="America/Chicago")

VENUES: list[VenueSummary] = [
    VenueSummary(id=1, name="The White Squirrel Bar"),
    VenueSummary(id=2, name="The Midway Saloon"),
    VenueSummary(id=3, name="Zhora Darling"),
    VenueSummary(id=4, name="The Terminal Bar"),
]

ARTISTS: list[ArtistSummary] = [
    ArtistSummary(id=1, name="Charlie Parr"),
    ArtistSummary(id=2, name="Nooky Jones"),
    ArtistSummary(id=3, name="The Cactus Blossoms"),
    ArtistSummary(id=4, name="Lanue"),
    ArtistSummary(id=5, name="Dead Man Winter"),
    ArtistSummary(id=6, name="Jaedyn James"),
    ArtistSummary(id=7, name="Humbird"),
    ArtistSummary(id=8, name="Pert Near Sandstone"),
    ArtistSummary(id=9, name="Beasthead"),
    ArtistSummary(id=10, name="Tarnation"),
]

_A = {a.name: a for a in ARTISTS}
_V = {v.name: v for v in VENUES}


def _lineup(*names: str, times: tuple[str | None, ...] = ()) -> list[LineupEntry]:
    """Build a lineup, numbering acts in the order given.

    Sequence numbers are always filled in because the agent assumes an
    order from the listing order when the page doesn't state one — so a
    null sequence_number is rarer in practice than a null time.
    """
    entries = []
    for i, name in enumerate(names):
        raw = times[i] if i < len(times) else None
        entries.append(
            LineupEntry(
                artist=_A[name],
                start_time=datetime.time.fromisoformat(raw) if raw else None,
                sequence_number=i + 1,
            )
        )
    return entries


def _day(offset: int) -> datetime.date:
    return START + datetime.timedelta(days=offset)


# (day offset, venue, start, end, lineup, advance, day-of, free, image)
_SHOW_ROWS: list[tuple] = [
    # Week 1
    (0, "The White Squirrel Bar", "20:00", None, _lineup("Charlie Parr"), None, "10.00", None, None),
    (2, "Zhora Darling", "21:00", "23:30", _lineup("Nooky Jones", "Beasthead", times=("21:00", "22:30")), "18.00", "22.00", None, "https://example.com/posters/nooky.jpg"),
    (2, "The Midway Saloon", None, None, _lineup("Tarnation"), None, None, True, None),
    (3, "The Terminal Bar", "19:30", None, _lineup("Humbird"), "15.00", "18.00", None, None),
    (4, "The White Squirrel Bar", "22:00", None, _lineup("Dead Man Winter", "Lanue"), None, "12.00", None, None),
    (5, "Zhora Darling", "20:00", None, _lineup("The Cactus Blossoms"), "25.00", "30.00", None, None),
    # day 6 deliberately empty — the calendar has to render a date with
    # no shows, and a fixture where every day is full never exercises it

    # Week 2
    (7, "The Midway Saloon", "20:30", None, _lineup("Pert Near Sandstone"), None, "15.00", None, None),
    (9, "The Terminal Bar", "21:00", None, _lineup("Jaedyn James", "Tarnation", "Beasthead"), "12.00", "15.00", None, None),
    (10, "The White Squirrel Bar", None, None, _lineup("Charlie Parr"), None, None, None, None),
    (11, "Zhora Darling", "19:00", "22:00", _lineup("Lanue"), "20.00", None, None, None),
    (12, "The Midway Saloon", "21:00", None, _lineup("Humbird", "Beasthead"), None, None, True, None),
    (13, "The Terminal Bar", "20:00", None, _lineup("The Cactus Blossoms"), "28.00", "32.00", None, "https://example.com/posters/cactus.jpg"),

    # Week 3
    (15, "The White Squirrel Bar", "20:00", None, _lineup("Nooky Jones"), None, "10.00", None, None),
    (16, "Zhora Darling", "21:30", None, _lineup("Dead Man Winter"), "16.00", "20.00", None, None),
    (17, "The Midway Saloon", "20:00", None, _lineup("Jaedyn James"), None, "8.00", None, None),
    (18, "The Terminal Bar", "19:00", None, _lineup("Pert Near Sandstone", "Tarnation", times=("19:00", "20:30")), "14.00", "18.00", None, None),
    (20, "The White Squirrel Bar", "22:00", None, _lineup("Beasthead"), None, None, True, None),

    # Week 4
    (22, "Zhora Darling", "20:00", None, _lineup("Humbird", "Lanue", "Charlie Parr"), "22.00", "26.00", None, None),
    (23, "The Midway Saloon", None, None, _lineup("Tarnation"), None, "5.00", None, None),
    (24, "The Terminal Bar", "21:00", None, _lineup("Nooky Jones"), "18.00", None, None, None),
    (26, "The White Squirrel Bar", "20:00", "23:00", _lineup("The Cactus Blossoms", "Dead Man Winter"), "24.00", "28.00", None, None),

    # Added for B3 (docs/dev/implementations/b3-the-calendar.md, B3-D5), and
    # appended so ids 1-21 don't change. The rows above never put two
    # shows at one venue on one date, never run past midnight and never
    # put more than two venues on a date, so the calendar's hardest cases
    # had no data. All four land on 2026-10-07 (offset 9), which already
    # has The Terminal Bar at 21:00 (Jaedyn James, Tarnation, Beasthead —
    # none of them reused here, so nobody is double-booked), giving that
    # one date all four venues.
    #   - two shows at one venue, the early one with no admission info at
    #     all (renders nothing — not "Free"):
    (9, "The White Squirrel Bar", "18:00", None, _lineup("Lanue"), None, None, None, None),
    #   - the late one ends after midnight, has per-act times, and an
    #     unlabelled (so day-of-show) price:
    (9, "The White Squirrel Bar", "22:00", "00:30", _lineup("Nooky Jones", "Pert Near Sandstone", times=("22:00", "23:15")), None, "10.00", None, None),
    #   - an artist who also plays another venue on another date, for the
    #     artist filter:
    (9, "Zhora Darling", "20:00", None, _lineup("Charlie Parr"), "20.00", "25.00", None, None),
    #   - a show listed under the 7th at 1:00 AM: after midnight, so it
    #     belongs to the 7th's night and displays as the 8th ("1:00 AM
    #     Thu"), sorting after the evening's shows (requirements-initial.md,
    #     "Times after midnight"):
    (9, "The Midway Saloon", "01:00", None, _lineup("Dead Man Winter"), None, None, True, None),

    # Added for B4 (B4-D2, docs/dev/implementations/b4-detail-pages.md), and
    # appended so ids 1-25 don't change. Every show above sits inside the
    # 28-day default window (START..END), so against this data
    # `GET /shows?artist_id=1&upcoming=true` and the plain default window
    # return the same rows and nothing could tell them apart. This one is
    # deliberately OUTSIDE the window: Thursday 2026-10-29 (offset 31),
    # Charlie Parr again, at a venue he has played in the window, so the
    # artist page lists five shows while the default window holds four.
    # The generator keeps it out of shows.json (see generate_fixtures.py).
    (31, "The White Squirrel Bar", "20:00", None, _lineup("Charlie Parr"), None, "10.00", None, None),
]


def _build_shows() -> list[ShowSummary]:
    shows = []
    for i, (offset, venue, start, end, acts, adv, day_of, free, image) in enumerate(_SHOW_ROWS, start=1):
        shows.append(
            ShowSummary(
                id=i,
                date=_day(offset),
                start_time=datetime.time.fromisoformat(start) if start else None,
                end_time=datetime.time.fromisoformat(end) if end else None,
                venue=_V[venue],
                lineup=acts,
                admission_advance=Decimal(adv) if adv else None,
                admission_day=Decimal(day_of) if day_of else None,
                free_admission=free,
                image_url=image,
            )
        )
    return shows


SHOWS: list[ShowSummary] = _build_shows()

# Only one venue and one artist have full detail records invented for
# them; the rest are generated from their summary below. Enough to build
# a detail page against without inventing forty fields forty times.
VENUE_DETAILS: dict[int, VenueDetail] = {
    3: VenueDetail(
        id=3,
        metro=METRO,
        name="Zhora Darling",
        calendar_url="https://www.zhoradarling.com/events",
        photo_url="https://example.com/photos/zhora-darling.jpg",
        address="1010 Washington Ave N, Minneapolis, MN 55401",
        phone_numbers=["+1-612-555-0142"],
        emails=["booking@example.com"],
        website="https://www.zhoradarling.com",
        age_restriction=AgeRestriction.TWENTY_ONE_PLUS,
        serves_alcohol=True,
        venue_type=VenueType.BAR,
        setting=Setting.INDOOR,
        seating=Seating.STANDING,
        extra_metadata={"has_green_room": True},
    ),
}

ARTIST_DETAILS: dict[int, ArtistDetail] = {
    1: ArtistDetail(
        id=1,
        name="Charlie Parr",
        photo_url="https://example.com/photos/charlie-parr.jpg",
        website="https://charlieparr.com",
        hometown="Duluth, MN",
        format=ArtistFormat.SOLO,
        repertoire=ArtistRepertoire.ORIGINAL,
        extra_metadata={},
    ),
}


def venue_detail(venue_id: int) -> VenueDetail | None:
    """A venue's detail record, invented on the fly if not written out.

    Returns None for an unknown id so the caller decides what a miss
    means — a router turns it into a 404, a test might assert on it.
    Raising from here would take that choice away.
    """
    if venue_id in VENUE_DETAILS:
        return VENUE_DETAILS[venue_id]
    summary = next((v for v in VENUES if v.id == venue_id), None)
    if summary is None:
        return None
    return VenueDetail(
        id=summary.id,
        metro=METRO,
        name=summary.name,
        calendar_url=f"https://example.com/{summary.id}/calendar",
    )


def artist_detail(artist_id: int) -> ArtistDetail | None:
    """Same pattern as venue_detail."""
    if artist_id in ARTIST_DETAILS:
        return ARTIST_DETAILS[artist_id]
    summary = next((a for a in ARTISTS if a.id == artist_id), None)
    if summary is None:
        return None
    return ArtistDetail(id=summary.id, name=summary.name)


def show_detail(show_id: int) -> ShowDetail | None:
    """A show's detail record, built from its summary.

    The four inherited fields are the venue's values, resolved — which
    is what the real endpoint will do too, just by reading the venue row
    instead of guessing. See docs/dev/api-contract.md section 5.
    """
    summary = next((s for s in SHOWS if s.id == show_id), None)
    if summary is None:
        return None
    venue = venue_detail(summary.venue.id)
    return ShowDetail(
        **summary.model_dump(),
        event=None,
        original_url=venue.calendar_url if venue else None,
        age_restriction=venue.age_restriction if venue else None,
        serves_alcohol=venue.serves_alcohol if venue else None,
        setting=venue.setting if venue else None,
        seating=venue.seating if venue else None,
    )


def calendar_months() -> list[CalendarMonth]:
    """Future-facing months that actually have shows, per the
    requirements — derived from the data, not from a date range.
    """
    counts: dict[tuple[int, int], int] = {}
    for show in SHOWS:
        key = (show.date.year, show.date.month)
        counts[key] = counts.get(key, 0) + 1
    return [
        CalendarMonth(year=year, month=month, show_count=count)
        for (year, month), count in sorted(counts.items())
    ]


# ---------------------------------------------------------------------
# The fixtures' bodies (C2-D1)
# ---------------------------------------------------------------------


def _api_order(show: ShowSummary) -> tuple[datetime.date, bool, datetime.time, str, int]:
    """The order `GET /shows` answers in: date, then no-time last, then time, then venue, then id.

    Written out here separately from the router's own key on purpose (C2-PR1-1): a fixture is a
    response body, so it is stored in the order the API returns, and `test_fixtures_agree.py` compares
    the two strictly. If both sides shared one function, a change to the ordering would move both and
    nothing would notice.
    """
    return (show.date, show.start_time is None, show.start_time or datetime.time.min, show.venue.name, show.id)


def fixture_payloads() -> dict[str, BaseModel]:
    """The eight frontend fixtures, by file name: the bodies `scripts/generate_fixtures.py` writes.

    Pure (no database), so `make fixtures` and the `contract` CI job need no Postgres.
    """
    # shows.json is a DEFAULT-WINDOW response, so it holds only the shows inside START..END -- what
    # GET /shows returns with no parameters. Not `SHOWS` wholesale: B4 appended one show past END (to
    # make `?upcoming=true` observable), and a fixture claiming END while holding a later show would
    # be lying about its own range.
    in_window = sorted((s for s in SHOWS if START <= s.date <= END), key=_api_order)
    detail = show_detail(2)
    venue = venue_detail(3)
    artist = artist_detail(1)
    assert detail is not None and venue is not None and artist is not None  # ids written out above
    return {
        "metro.json": METRO,
        "shows.json": ShowListResponse(start=START, end=END, shows=in_window),
        "show-detail.json": detail,
        "venues.json": VenueListResponse(venues=sorted(VENUES, key=lambda v: v.name)),
        "venue-detail.json": venue,
        "artists.json": ArtistListResponse(artists=sorted(ARTISTS, key=lambda a: a.name)),
        "artist-detail.json": artist,
        "calendar-months.json": CalendarMonthsResponse(months=calendar_months()),
    }


# ---------------------------------------------------------------------
# Loading the world into Postgres (C2-D1)
# ---------------------------------------------------------------------


class NotAnEmptyDatabaseError(RuntimeError):
    """The sample world was asked to load into a database that already holds calendar rows."""


async def load_sample_data(session: AsyncSession) -> None:
    """Write the sample world into an empty, migrated database. Flushes; the caller commits.

    Ids are written explicitly, not left to the sequences, because the fixtures and the browser specs
    name them (venue 3 is Zhora Darling, show 2 its September 30 show). Explicit ids do not advance a
    sequence, so each is moved past the highest id afterwards; otherwise the next row the worker
    inserts would collide with id 1 (C2-M8).

    Refuses a database with any metro, venue, artist or show row in it: this must never top up a real
    database, and the e2e database and the test database are the only places it is meant to run.
    """
    for model in (Metro, Venue, Artist, Show):
        if (await session.execute(select(func.count()).select_from(model))).scalar_one():
            raise NotAnEmptyDatabaseError(
                f"refusing to load the sample world: {model.__tablename__} already has rows"
            )

    # Metro first: venues point at it.
    session.add(Metro(id=METRO.id, name=METRO.name, timezone=METRO.timezone))
    await session.flush()

    # Venues and artists, each with the detail the sample writes out or invents on the fly.
    for summary in VENUES:
        v = venue_detail(summary.id)
        assert v is not None
        session.add(
            Venue(
                id=v.id, metro_id=v.metro.id, name=v.name, calendar_url=v.calendar_url,
                photo_url=v.photo_url, address=v.address, phone_numbers=v.phone_numbers,
                emails=v.emails, website=v.website, age_restriction=v.age_restriction,
                serves_alcohol=v.serves_alcohol, venue_type=v.venue_type, setting=v.setting,
                seating=v.seating, extra_metadata=v.extra_metadata,
            )
        )
    for artist_summary in ARTISTS:
        a = artist_detail(artist_summary.id)
        assert a is not None
        session.add(
            Artist(
                id=a.id, name=a.name, photo_url=a.photo_url, website=a.website, hometown=a.hometown,
                format=a.format, repertoire=a.repertoire, extra_metadata=a.extra_metadata,
            )
        )
    await session.flush()

    # Shows, then their lineups. The four inherited fields stay NULL: the sample's shows inherit
    # everything from the venue, and the API resolves that (api-contract.md section 5).
    calendar_urls: dict[int, str] = {}
    for summary in VENUES:
        detail = venue_detail(summary.id)
        assert detail is not None  # every VENUES id has a detail record (written out or invented on the fly)
        calendar_urls[summary.id] = detail.calendar_url
    for s in SHOWS:
        session.add(
            Show(
                id=s.id, venue_id=s.venue.id, date=s.date, start_time=s.start_time, end_time=s.end_time,
                admission_advance=s.admission_advance, admission_day=s.admission_day,
                free_admission=s.free_admission, image_url=s.image_url,
                original_url=calendar_urls[s.venue.id],
            )
        )
    await session.flush()
    for s in SHOWS:
        for entry in s.lineup:
            session.add(
                ShowArtist(
                    show_id=s.id, artist_id=entry.artist.id, start_time=entry.start_time,
                    sequence_number=entry.sequence_number,
                )
            )
    await session.flush()

    # Move every sequence past the ids just written.
    for table in ("metro", "venue", "artist", "show"):
        await session.execute(
            text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT max(id) FROM {table}))")
        )
