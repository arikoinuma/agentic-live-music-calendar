"""Tests for `PostgresCalendarReader` against a real database: what reconcile is given to compare the page with.

Milestone A5 (docs/dev/implementations/a5-reconcile.md, Test approach §4, step 4 of the design). The reader is the
only code that reads the stored calendar for reconcile, so its contract is checked against real rows: shows in a
date range of EVERY status (a returning show is found among the removed ones), each with its lineup in performance
order, for one venue only, plus every artist.

How to read it: `calendar` seeds the four starting venues, a handful of artists and five shows (some for another
venue, some out of range, one removed), using `polyfactory` for the columns nobody asserts on (photo and website
links, image URLs: filler) and explicit values for everything a test checks (names, dates, times, statuses). Random
names or dates would make the expected values depend on the seed rather than on the requirements (A5-PR1-15). Expected values are the literal rows seeded here, and the contract in `calendar_reader.py`.
"""

import datetime
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker.artist_match import KnownArtist
from agent_worker.calendar_reader import PostgresCalendarReader
from agent_worker.main import load_venues
from agent_worker.reconcile import Action
from agent_worker.tests.reconcile_support import listed, plan_for
from app.db.models import Artist, Show, ShowArtist
from app.db.seed import seed
from app.enums import ShowStatus


class ArtistFactory(SQLAlchemyFactory[Artist]):
    __model__ = Artist
    __set_relationships__ = False
    __set_foreign_keys__ = False
    __random_seed__ = 11


class ShowFactory(SQLAlchemyFactory[Show]):
    __model__ = Show
    __set_relationships__ = False
    __set_foreign_keys__ = False
    __random_seed__ = 11


def make_artist(name: str) -> Artist:
    """An artist with this name; the links and other columns are filler."""
    return ArtistFactory.build(
        id=None, name=name, format=None, repertoire=None, extra_metadata=None,
    )


def make_show(
    venue_id: int, date: datetime.date, start: datetime.time | None, status: ShowStatus = ShowStatus.ACTIVE, **fields: Any
) -> Show:
    """A show with these facts; the poster link is filler. Everything the CHECK constraint or a test reads is explicit."""
    values: dict[str, Any] = {
        "id": None, "event_id": None, "venue_id": venue_id, "date": date, "start_time": start, "end_time": None,
        "age_restriction": None, "serves_alcohol": None, "setting": None, "seating": None,
        "admission_advance": None, "admission_day": None, "free_admission": None, "status": status,
        "original_url": "https://venue.example/events",
    }
    values.update(fields)
    return ShowFactory.build(**values)


@pytest.fixture
def factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory on the test connection in savepoint mode (see test_run_venue.py), so the reader's own sessions
    see the rows seeded here and nothing outlives the test."""
    return async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


Seeder = Callable[[], Awaitable[dict[str, Any]]]


@pytest_asyncio.fixture(loop_scope="session")
async def calendar(factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """Venue A (the first seeded venue) has: Oct 20 20:00 (Nona then Zhora), Oct 21 untimed (removed, Prince), Oct 25 20:00 (no lineup),
    Nov 20 20:00 (out of the range the tests read). Venue B has Oct 20 20:00 (Zhora). Returns the ids by name."""
    async with factory() as session:
        await seed(session)
        # The seeded venues' ids, not 1 and 2: sequences don't reset when a test's transaction rolls back.
        venue_a, venue_b, venue_c, *_ = [v.id for v in await load_venues(session)]
        nona, zhora, prince = make_artist("Nona"), make_artist("Zhora"), make_artist("Prince")
        session.add_all([nona, zhora, prince])
        await session.flush()
        shows = {
            "first": make_show(venue_a, datetime.date(2026, 10, 20), datetime.time(20, 0)),
            "removed": make_show(venue_a, datetime.date(2026, 10, 21), None, ShowStatus.REMOVED, free_admission=True),
            "empty": make_show(venue_a, datetime.date(2026, 10, 25), datetime.time(20, 0)),
            "later": make_show(venue_a, datetime.date(2026, 11, 20), datetime.time(20, 0)),
            "other_venue": make_show(venue_b, datetime.date(2026, 10, 20), datetime.time(20, 0)),
        }
        session.add_all(shows.values())
        await session.flush()
        session.add_all([
            # Added out of performance order on purpose: the reader must order the lineup, not the insert.
            ShowArtist(show_id=shows["first"].id, artist_id=zhora.id, start_time=datetime.time(21, 0), sequence_number=2),
            ShowArtist(show_id=shows["first"].id, artist_id=nona.id, start_time=None, sequence_number=1),
            ShowArtist(show_id=shows["removed"].id, artist_id=prince.id, sequence_number=1),
            ShowArtist(show_id=shows["other_venue"].id, artist_id=zhora.id, sequence_number=1),
        ])
        await session.commit()
        return {
            "venues": {"a": venue_a, "b": venue_b, "c": venue_c},
            "shows": {name: show.id for name, show in shows.items()},
            "artists": {"Nona": nona.id, "Zhora": zhora.id, "Prince": prince.id},
        }


async def test_it_returns_this_venues_shows_in_the_range_of_every_status(
    factory: async_sessionmaker[AsyncSession], calendar: dict[str, Any]
) -> None:
    # Proves: the range is inclusive, only the asked-for venue's shows come back, and a REMOVED show is among them
    # (reconcile needs it to bring a returning show back instead of duplicating it, A5-D7). Venue B's show and the
    # November show are not returned.
    reader = PostgresCalendarReader(factory)
    shows = await reader.stored_shows(calendar["venues"]["a"], datetime.date(2026, 10, 20), datetime.date(2026, 10, 25))
    ids = calendar["shows"]
    assert [s.id for s in shows] == [ids["first"], ids["removed"], ids["empty"]]
    assert [s.status for s in shows] == [ShowStatus.ACTIVE, ShowStatus.REMOVED, ShowStatus.ACTIVE]


async def test_it_returns_each_shows_columns_and_lineup_in_performance_order(
    factory: async_sessionmaker[AsyncSession], calendar: dict[str, Any]
) -> None:
    # Proves: the columns reconcile compares (date, time, URL) arrive as stored, and the lineup is ordered by
    # `sequence_number`, with each artist's name and own set time, though it was inserted out of order.
    [first, *_] = await PostgresCalendarReader(factory).stored_shows(calendar["venues"]["a"], datetime.date(2026, 10, 20), datetime.date(2026, 10, 20))
    assert (first.date, first.start_time, first.original_url) == (
        datetime.date(2026, 10, 20), datetime.time(20, 0), "https://venue.example/events",
    )
    a = calendar["artists"]
    assert [(e.artist_id, e.artist_name, e.start_time, e.sequence_number) for e in first.lineup] == [
        (a["Nona"], "Nona", None, 1), (a["Zhora"], "Zhora", datetime.time(21, 0), 2),
    ]


async def test_a_show_with_no_lineup_comes_back_with_an_empty_one(
    factory: async_sessionmaker[AsyncSession], calendar: dict[str, Any]
) -> None:
    # Proves: a show nobody is linked to (the lineup is written by commit, after the show) is not dropped by the
    # lineup join.
    shows = await PostgresCalendarReader(factory).stored_shows(calendar["venues"]["a"], datetime.date(2026, 10, 25), datetime.date(2026, 10, 25))
    assert [(s.id, s.lineup) for s in shows] == [(calendar["shows"]["empty"], ())]


async def test_an_empty_range_returns_nothing(factory: async_sessionmaker[AsyncSession], calendar: dict[str, Any]) -> None:
    # Proves: a range with no shows is an empty list (not an error), and the venue filter holds: venue C has none.
    reader = PostgresCalendarReader(factory)
    assert await reader.stored_shows(calendar["venues"]["c"], datetime.date(2026, 10, 1), datetime.date(2026, 12, 31)) == []


async def test_it_returns_every_artist(factory: async_sessionmaker[AsyncSession], calendar: dict[str, Any]) -> None:
    # Proves: artists are global (not metro-scoped; requirements, "Agent Artist Creation & Matching"), so every artist
    # comes back, as (id, name), whatever venue the run is for.
    a = calendar["artists"]
    assert await PostgresCalendarReader(factory).artists() == [
        KnownArtist(a["Nona"], "Nona"), KnownArtist(a["Zhora"], "Zhora"), KnownArtist(a["Prince"], "Prince"),
    ]


@pytest.mark.parametrize("name", ["first", "removed"])
async def test_the_returned_show_round_trips_through_reconcile_unchanged(
    name: str, factory: async_sessionmaker[AsyncSession], calendar: dict[str, Any]
) -> None:
    # Proves: what the reader returns is in the shape reconcile reads, with nothing lost: a listing identical to the
    # stored show (same time, same acts) comes out as a no-op when the show is active, and as a reactivation when
    # it was removed. Run against the stored rows themselves, not hand-built dataclasses.
    [show] = [
        s for s in await PostgresCalendarReader(factory).stored_shows(calendar["venues"]["a"], datetime.date(2026, 10, 20), datetime.date(2026, 10, 21))
        if s.id == calendar["shows"][name]
    ]
    acts = [e.artist_name for e in show.lineup]
    known = await PostgresCalendarReader(factory).artists()
    plan = plan_for([listed(0, show.date, show.start_time, acts=acts)], [show], known)
    expected = Action.NO_OP if name == "first" else Action.UPDATE
    assert plan.shows[0].action is expected
