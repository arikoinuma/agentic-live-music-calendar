"""The sample world's loader, against a real Postgres (C2-D1).

`load_sample_data` writes the sample world (app/testing/sample_data.py) into an empty, migrated database
for the route tests and the end-to-end job. Expected counts and ids are worked out from the sample's rows
(26 shows, 36 lineup entries, 4 venues, 10 artists, 1 metro), not read back from the loader.
"""

import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artist, Metro, Show, ShowArtist, Venue
from app.enums import AgeRestriction
from app.testing.sample_data import NotAnEmptyDatabaseError, load_sample_data


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one()


async def test_the_loader_writes_every_row(db_session: AsyncSession) -> None:
    # Proves: the whole world arrives: one metro, 4 venues, 10 artists, 26 shows and 36 lineup entries. A loader that
    # skipped the lineups would leave every show with an empty bill and the route tests would still pass the shape checks.
    await load_sample_data(db_session)
    counts = [await _count(db_session, m) for m in (Metro, Venue, Artist, Show, ShowArtist)]
    assert counts == [1, 4, 10, 26, 36]


async def test_ids_match_the_samples(db_session: AsyncSession) -> None:
    # Proves: rows keep the ids the sample gives them, because the fixtures and the browser specs name them (venue 3 is
    # Zhora Darling; show 2 is its 2026-09-30 show).
    await load_sample_data(db_session)
    venue = await db_session.get(Venue, 3)
    show = await db_session.get(Show, 2)
    assert venue is not None and venue.name == "Zhora Darling"
    assert show is not None and (show.venue_id, show.date) == (3, datetime.date(2026, 9, 30))


async def test_sequences_move_past_the_loaded_ids(db_session: AsyncSession) -> None:
    # Proves (C2-M8): inserting one more row after the load gets the next id, not a unique violation on 1. Explicit ids
    # do not advance a sequence, so without the reset the first row the worker inserted into a loaded database would
    # collide. Expected next ids: metro 2, venue 5, artist 11, show 27.
    await load_sample_data(db_session)
    metro = Metro(name="Next", timezone="UTC", slug="nxt")
    artist = Artist(name="Next Act")
    db_session.add_all([metro, artist])
    await db_session.flush()
    venue = Venue(metro_id=1, name="Next Hall", calendar_url="https://example.com/next")
    db_session.add(venue)
    await db_session.flush()
    show = Show(venue_id=venue.id, date=datetime.date(2026, 11, 1))
    db_session.add(show)
    await db_session.flush()
    assert (metro.id, venue.id, artist.id, show.id) == (2, 5, 11, 27)


async def test_detail_fields_arrive(db_session: AsyncSession) -> None:
    # Proves: venue 3 and artist 1 carry the detail the sample writes out, and venue 1 the values it invents on the fly
    # (`https://example.com/1/calendar`, no address), so the detail routes have something real to return.
    await load_sample_data(db_session)
    zhora = await db_session.get(Venue, 3)
    squirrel = await db_session.get(Venue, 1)
    parr = await db_session.get(Artist, 1)
    assert zhora is not None and squirrel is not None and parr is not None
    assert zhora.address == "1010 Washington Ave N, Minneapolis, MN 55401"
    assert zhora.age_restriction == AgeRestriction.TWENTY_ONE_PLUS
    assert squirrel.calendar_url == "https://example.com/1/calendar"
    assert squirrel.address is None
    assert parr.hometown == "Duluth, MN"


async def test_a_show_remembers_the_page_it_came_from(db_session: AsyncSession) -> None:
    # Proves: each show's `original_url` is its venue's calendar page, as the sample's show detail returns it, so the
    # "source" link on a show's page has a target. Show 2 is at venue 3.
    await load_sample_data(db_session)
    show = await db_session.get(Show, 2)
    assert show is not None and show.original_url == "https://www.zhoradarling.com/events"


async def test_the_loader_refuses_a_database_that_has_rows(db_session: AsyncSession) -> None:
    # Proves: the loader cannot top up a real database. A second load, and a load after only a metro exists, both raise
    # before writing anything. The loader runs only against throwaway databases, and this is the second line of defence
    # behind their names (app/testing/db.py, e2e_database.py).
    await load_sample_data(db_session)
    with pytest.raises(NotAnEmptyDatabaseError):
        await load_sample_data(db_session)


async def test_the_loader_refuses_even_a_lone_metro(db_session: AsyncSession) -> None:
    # Proves: one pre-existing metro row is enough to refuse (the check covers each of metro, venue, artist and show).
    db_session.add(Metro(name="Already Here", timezone="UTC", slug="her"))
    await db_session.flush()
    with pytest.raises(NotAnEmptyDatabaseError, match="metro"):
        await load_sample_data(db_session)
