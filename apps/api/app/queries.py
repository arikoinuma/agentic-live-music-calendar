"""The read API's queries: ORM rows in, `schemas.py` models out (C2).

Read this first. Each public function answers one route (`app/routers/`) and returns the response models
the contract defines (`docs/dev/api-contract.md`), so the routers stay thin: they check the request
(a 422 for a bad range), call one function here, and turn a miss into a 404. This module is where a
database row becomes a response, in one place per shape: `_summary` for a show, `_venue_detail`,
`_artist_detail`.

Three rules shape every query (C2-D5, `docs/dev/implementations/c2-api-reads-database.md`):

* **Scoped to the live metro.** Venues, shows and months belong to one metro; artists are global. The
  routes pass the metro in, so a second metro's rows never appear.
* **Removed shows never appear.** `status = 'removed'` is the soft delete (data-model-initial.md); the
  status column exists for reconcile and the audit trail, not for the reader.
* **Ordering is done in Python, not by the database.** Postgres collation differs between a laptop's
  Docker image, CI, the cloud sandbox and Neon, and none of them is verified to sort like the rule the
  tests state. A key written in Python is the same everywhere, and the row counts are bounded (a range is
  at most `MAX_RANGE` days; the lists are tens to hundreds of rows). This departs from the style guide's
  "SQL-first, Pydantic-second" on purpose.

Nothing here lazy-loads. The relationships on the models are `lazy="raise"` (C2-D4), so each query names
what it loads, and a missed load is an error in the first test instead of a `MissingGreenlet` in
production. `_show_loads` and `_apply_filters` below are where that lesson and the filter rule live (C2-K2, C2-K1).
"""

import datetime
from collections.abc import Sequence

from sqlalchemy import Select, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.db.models import Artist, Metro, Show, ShowArtist, Venue
from app.enums import ShowStatus
from app.schemas import (
    ArtistDetail,
    ArtistSummary,
    CalendarMonth,
    EventSummary,
    LineupEntry,
    MetroSummary,
    ShowDetail,
    ShowSummary,
    VenueDetail,
    VenueSummary,
)

# ---------------------------------------------------------------------
# The two helpers that carry a lesson (C2-K1, C2-K2)
# ---------------------------------------------------------------------


def _show_loads() -> Sequence[ExecutableOption]:
    """What every show query loads along with the show, so nothing is fetched lazily afterwards.

    `Show.venue`, `Show.event` and `Show.lineup` (and each entry's `artist`) are `lazy="raise"`: touching one
    that wasn't loaded raises, which under asyncio is the difference between a clear error in a test and a
    `MissingGreenlet` in production. This is the one place a show query says what it needs (C2-K2).
    """
    # Under asyncio a relationship cannot load itself on access (C2-D4, lazy="raise"), so each query names
    # what it loads. A to-one side (venue, event, an entry's artist) is a joinedload: one query with a join.
    # A to-many side (the lineup) is a selectinload: a second query for the whole batch, because a join on the
    # many side would repeat each show once per act (and SQLAlchemy then demands `.unique()` on the result).
    # The statement count therefore does not grow with the number of shows.
    return (
        joinedload(Show.venue),
        joinedload(Show.event),
        selectinload(Show.lineup).joinedload(ShowArtist.artist),
    )


def _apply_filters(
    stmt: Select[tuple[Show]], venue_ids: Sequence[int] | None, artist_ids: Sequence[int] | None
) -> Select[tuple[Show]]:
    """Narrow a show query by the `venue_id` / `artist_id` parameters.

    The rule is the contract's (`api-contract.md` section 2, "Filtering"): several ids of one kind mean
    "any of these" (OR), different kinds must both hold (AND), and an artist matches if *any* act on the
    bill is that artist, not only the headliner (C2-K1). Called only when at least one is given.
    """
    # OR within one filter type, AND across types: each `.where()` adds an AND, and `in_()` is the OR within a
    # type. The artist test is an EXISTS over the lineup, not a join: joining `show_artist` would repeat a show
    # once per matching act, so a bill with two requested artists would be returned twice.
    if venue_ids:
        stmt = stmt.where(Show.venue_id.in_(venue_ids))
    if artist_ids:
        stmt = stmt.where(Show.lineup.any(ShowArtist.artist_id.in_(artist_ids)))
    return stmt


# ---------------------------------------------------------------------
# Shapes: ORM row -> response model
# ---------------------------------------------------------------------


def _inherit[T](own: T | None, inherited: T | None) -> T | None:
    """A show's own value if it set one, else its venue's (`api-contract.md` section 5).

    `is None`, not truthiness: `serves_alcohol=False` is a real answer that must beat the venue's `True`, and
    `show.x or venue.x` would throw it away because False is falsy (C2-M2, C2-D6).
    """
    return own if own is not None else inherited


def _lineup_key(entry: ShowArtist) -> tuple[bool, int, int]:
    """Performance order: numbered acts by number, then unnumbered ones, ties by artist id.

    The worker leaves `sequence_number` null when a listing gives no order (schemas.py), and Python's sort
    can't compare None with an int, hence the leading flag.
    """
    return (entry.sequence_number is None, entry.sequence_number or 0, entry.artist_id)


def _summary(show: Show) -> ShowSummary:
    """One show as a calendar block. Needs `venue` and `lineup` (with each `artist`) already loaded."""
    return ShowSummary(
        id=show.id,
        date=show.date,
        start_time=show.start_time,
        end_time=show.end_time,
        venue=VenueSummary(id=show.venue.id, name=show.venue.name),
        lineup=[
            LineupEntry(
                artist=ArtistSummary(id=entry.artist.id, name=entry.artist.name),
                start_time=entry.start_time,
                sequence_number=entry.sequence_number,
            )
            for entry in sorted(show.lineup, key=_lineup_key)
        ],
        admission_advance=show.admission_advance,
        admission_day=show.admission_day,
        free_admission=show.free_admission,
        image_url=show.image_url,
    )


def _ordering(show: ShowSummary) -> tuple[datetime.date, bool, datetime.time, str, int]:
    """Sort key: by date, then by start time, then by venue name, then by id.

    The `start_time is None` element is why this is a function and not a lambda. A show with no listed time
    can't be compared against one that has a time, and it shouldn't silently sort as midnight either --
    "time not stated" isn't "first thing in the morning". Sorting the None-valued ones to the end of their
    day is a real decision, and the frontend renders them differently for the same reason. The id is the last
    tie-break so two otherwise identical shows come back in a stable order.
    """
    return (
        show.date,
        show.start_time is None,
        show.start_time or datetime.time.min,
        show.venue.name,
        show.id,
    )


def _venue_detail(venue: Venue) -> VenueDetail:
    """A venue's page. Needs `metro` loaded. NULL arrays and metadata become the empty values the model defaults to."""
    return VenueDetail(
        id=venue.id,
        metro=MetroSummary(id=venue.metro.id, name=venue.metro.name, timezone=venue.metro.timezone),
        name=venue.name,
        calendar_url=venue.calendar_url,
        photo_url=venue.photo_url,
        address=venue.address,
        phone_numbers=venue.phone_numbers or [],
        emails=venue.emails or [],
        website=venue.website,
        age_restriction=venue.age_restriction,
        serves_alcohol=venue.serves_alcohol,
        venue_type=venue.venue_type,
        setting=venue.setting,
        seating=venue.seating,
        extra_metadata=venue.extra_metadata or {},
    )


def _artist_detail(artist: Artist) -> ArtistDetail:
    return ArtistDetail(
        id=artist.id,
        name=artist.name,
        photo_url=artist.photo_url,
        website=artist.website,
        hometown=artist.hometown,
        format=artist.format,
        repertoire=artist.repertoire,
        extra_metadata=artist.extra_metadata or {},
    )


# ---------------------------------------------------------------------
# Shows
# ---------------------------------------------------------------------


def _visible_shows(metro_id: int) -> Select[tuple[Show]]:
    """Shows a reader may see: active, at a venue in this metro. The base of every show query (C2-M1, C2-M5)."""
    return select(Show).where(
        Show.status == ShowStatus.ACTIVE,
        Show.venue.has(Venue.metro_id == metro_id),
    )


async def list_shows(
    session: AsyncSession,
    metro: Metro,
    start: datetime.date,
    end: datetime.date,
    venue_ids: Sequence[int] | None,
    artist_ids: Sequence[int] | None,
) -> list[ShowSummary]:
    """Active shows in this metro from `start` to `end` inclusive, filtered, in calendar order."""
    stmt = _visible_shows(metro.id).where(Show.date >= start, Show.date <= end).options(*_show_loads())
    if venue_ids or artist_ids:
        stmt = _apply_filters(stmt, venue_ids, artist_ids)
    shows = (await session.execute(stmt)).scalars().all()
    return sorted((_summary(show) for show in shows), key=_ordering)


async def get_show(session: AsyncSession, metro: Metro, show_id: int) -> ShowDetail | None:
    """One show's page, or None if there is no such active show in this metro (a removed show is a miss too)."""
    stmt = _visible_shows(metro.id).where(Show.id == show_id).options(*_show_loads())
    show = (await session.execute(stmt)).scalar_one_or_none()
    if show is None:
        return None
    return ShowDetail(
        **_summary(show).model_dump(),
        event=EventSummary(id=show.event.id, name=show.event.name) if show.event is not None else None,
        original_url=show.original_url,
        age_restriction=_inherit(show.age_restriction, show.venue.age_restriction),
        serves_alcohol=_inherit(show.serves_alcohol, show.venue.serves_alcohol),
        setting=_inherit(show.setting, show.venue.setting),
        seating=_inherit(show.seating, show.venue.seating),
    )


async def list_months(session: AsyncSession, metro: Metro, today: datetime.date) -> list[CalendarMonth]:
    """Months with at least one show on or after `today`, oldest first; the count is those upcoming shows.

    Future-facing and only months that have shows (requirements-initial.md), which is why it is a query and
    why `today` is the metro's, not the browser's.
    """
    year = extract("year", Show.date)
    month = extract("month", Show.date)
    stmt = (
        select(year, month, func.count())
        .select_from(Show)
        .where(
            Show.status == ShowStatus.ACTIVE,
            Show.date >= today,
            Show.venue.has(Venue.metro_id == metro.id),
        )
        .group_by(year, month)
        .order_by(year, month)
    )
    rows = (await session.execute(stmt)).all()
    return [CalendarMonth(year=int(y), month=int(m), show_count=count) for y, m, count in rows]


# ---------------------------------------------------------------------
# Venues and artists
# ---------------------------------------------------------------------


async def list_venues(session: AsyncSession, metro: Metro) -> list[VenueSummary]:
    """Every venue in this metro, alphabetical (case-insensitive, then id)."""
    venues = (await session.execute(select(Venue).where(Venue.metro_id == metro.id))).scalars().all()
    return [
        VenueSummary(id=v.id, name=v.name) for v in sorted(venues, key=lambda v: (v.name.casefold(), v.id))
    ]


async def get_venue(session: AsyncSession, metro: Metro, venue_id: int) -> VenueDetail | None:
    """One venue's page, or None if it isn't in this metro."""
    stmt = select(Venue).where(Venue.id == venue_id, Venue.metro_id == metro.id).options(joinedload(Venue.metro))
    venue = (await session.execute(stmt)).scalar_one_or_none()
    return _venue_detail(venue) if venue is not None else None


async def list_artists(session: AsyncSession) -> list[ArtistSummary]:
    """Every artist, alphabetical. Artists are global, not metro-scoped: acts tour between markets."""
    artists = (await session.execute(select(Artist))).scalars().all()
    return [
        ArtistSummary(id=a.id, name=a.name) for a in sorted(artists, key=lambda a: (a.name.casefold(), a.id))
    ]


async def get_artist(session: AsyncSession, artist_id: int) -> ArtistDetail | None:
    artist = (await session.execute(select(Artist).where(Artist.id == artist_id))).scalar_one_or_none()
    return _artist_detail(artist) if artist is not None else None
