"""Reading the calendar the worker already stored: the shows reconcile compares the page against, and the artists.

HOW TO READ THIS
  `CalendarReader` is the interface the graph reads through, as `AuditWriter` and `Stager` are the interfaces it
  writes through (context.py holds all three). `PostgresCalendarReader` is the real one; the graph tests use
  `fakes.FakeReader`.

  The read happens in `trace.audited`, before the reconcile node runs, not inside the node (a5-reconcile.md,
  "Settled details"; A4-D1 already put async database work in the wrapper and kept node bodies plain functions).
  That keeps `reconcile_node` testable with a hand-written list of stored shows and no database.

  **A read that fails stops the run.** The exception propagates out of the graph and `run_venue` closes the run.
  The alternative, treating an unreadable calendar as an empty one, would turn every listing into an insert: a
  duplicate of every show.

WHAT IT RETURNS
  Shows in a date range of every status (`removed` included: a returning show is found among them, A5-D7), each with
  its lineup, and every artist as (id, name). One short, read-only session per call, like the audit writer's.

docs/dev/implementations/a5-reconcile.md.
"""

import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.artist_match import KnownArtist
from agent_worker.reconcile import StoredLineupEntry, StoredShow
from app.db.models import Artist, Show, ShowArtist


class CalendarReader(Protocol):
    """Where the graph reads the stored calendar from. The graph depends on this, not on Postgres."""

    async def stored_shows(self, venue_id: int, start: datetime.date, end: datetime.date) -> list[StoredShow]:
        """The venue's shows dated `start` to `end` inclusive, every status, each with its lineup."""
        ...

    async def artists(self) -> list[KnownArtist]:
        """Every artist (artists are global, not metro-scoped)."""
        ...


class PostgresCalendarReader:
    """Reads the calendar from Postgres with a short session per call."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def stored_shows(self, venue_id: int, start: datetime.date, end: datetime.date) -> list[StoredShow]:
        async with self._session_factory() as session:
            shows = (
                await session.execute(
                    select(Show)
                    .where(Show.venue_id == venue_id, Show.date.between(start, end))
                    .order_by(Show.date, Show.start_time, Show.id)
                )
            ).scalars().all()
            lineups: dict[int, list[StoredLineupEntry]] = {show.id: [] for show in shows}
            if shows:
                rows = await session.execute(
                    select(ShowArtist, Artist.name)
                    .join(Artist, Artist.id == ShowArtist.artist_id)
                    .where(ShowArtist.show_id.in_(lineups))
                    .order_by(ShowArtist.show_id, ShowArtist.sequence_number, ShowArtist.artist_id)
                )
                for link, name in rows.all():
                    lineups[link.show_id].append(
                        StoredLineupEntry(link.artist_id, name, link.start_time, link.sequence_number)
                    )
            return [
                StoredShow(
                    id=s.id, date=s.date, start_time=s.start_time, end_time=s.end_time, status=s.status,
                    admission_advance=s.admission_advance, admission_day=s.admission_day,
                    free_admission=s.free_admission, image_url=s.image_url, original_url=s.original_url,
                    lineup=tuple(lineups[s.id]),
                )
                for s in shows
            ]

    async def artists(self) -> list[KnownArtist]:
        async with self._session_factory() as session:
            rows = await session.execute(select(Artist.id, Artist.name).order_by(Artist.id))
            return [KnownArtist(artist_id, name) for artist_id, name in rows.all()]
