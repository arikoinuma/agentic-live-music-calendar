"""The harness's reads and writes on the scratch calendar: read the rows a run left, clear them, and make the venue rows it needs.

What this is: the three database helpers the C5 harness uses around a graph run, in its own database (`scratch_database.py`).
`committed_extraction` reads the ACTIVE shows back as an extraction-shaped dict (so `scoring.score_page` scores the rows with the
same tiers as the model's answer), `reset` empties what a run writes between independent pages, and `ensure_venue` creates the
metro and venue rows a labelled page needs. `run_pages` (run_labeled_pages) and the scenarios (two_run_scenarios) both use them.

Why a module of its own: these change when the SCHEMA changes (Round 4: `ensure_venue` missed the `slug` column C4 made required),
which is unrelated to what a scenario does or what it should leave. It is not part of `scratch_database.py` on purpose: that module holds
the guard that refuses to touch any database but the scratch one and imports no ORM, which keeps it short enough to audit. `reset`
is destructive and relies on that guard having already run.

docs/dev/implementations/c5-pipeline-eval-harness.md, Step 5 (C5-D2, C5-PR1-5, C5-PR1-12); moved out of `two_run_scenarios.py` in code review
round 2 (C5-CR2-4).
"""

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.main import VenueFacts, load_venues
from agent_worker.model_eval.labels import VenueFacts as LabelVenueFacts
from app.db.models import Artist, Metro, Show, ShowArtist, Venue
from app.db.seed import METRO_NAME, METRO_SLUG, METRO_TIMEZONE
from app.enums import FetchStrategy, ShowStatus


async def committed_extraction(factory: async_sessionmaker[AsyncSession], venue_id: int) -> dict[str, Any]:
    """The venue's ACTIVE shows as an extraction-shaped dict, so `score_page` scores the rows unchanged.

    A removed show is not "left" (soft delete). Acts are in `sequence_number` order, as the reader's lineup query orders them.
    Dates and times are ISO text and prices are floats, so the dict is JSON-serialisable (a `Decimal` would not be) and a
    --rescore reads the same shape from a stored file (C5-PR1-12). The status is `scheduled`: the database cannot hold a
    cancelled show, which is why the committed column is scored against `scoring.scheduled_only` (C5-PR1-5).
    """
    async with factory() as session:
        shows = (
            (
                await session.execute(
                    select(Show)
                    .where(Show.venue_id == venue_id, Show.status == ShowStatus.ACTIVE)
                    .order_by(Show.date, Show.start_time, Show.id)
                )
            )
            .scalars()
            .all()
        )
        lineups: dict[int, list[str]] = {show.id: [] for show in shows}
        if shows:
            rows = await session.execute(
                select(ShowArtist.show_id, Artist.name)
                .join(Artist, Artist.id == ShowArtist.artist_id)
                .where(ShowArtist.show_id.in_(lineups))
                .order_by(ShowArtist.show_id, ShowArtist.sequence_number, ShowArtist.artist_id)
            )
            for show_id, name in rows.all():
                lineups[show_id].append(name)
        return {
            "page_readable": True,
            "shows": [
                {
                    "date": s.date.isoformat(),
                    "time": s.start_time.isoformat() if s.start_time else None,
                    "end_time": s.end_time.isoformat() if s.end_time else None,
                    "acts": [{"name": name} for name in lineups[s.id]],
                    "admission_advance": float(s.admission_advance) if s.admission_advance is not None else None,
                    "admission_day": float(s.admission_day) if s.admission_day is not None else None,
                    "free_admission": s.free_admission,
                    "image_url": s.image_url,
                    "status": "scheduled",
                }
                for s in shows
            ],
        }


async def reset(factory: async_sessionmaker[AsyncSession]) -> None:
    """Empty what a run writes: shows, lineups, artists, the audit trail and the runs. NEVER `venue` or `metro`.

    Run between INDEPENDENT pages, so one page's artists cannot change how the next page's artists are matched (reconcile
    resolves a name against every artist already stored). Scenarios do not reset between their two runs: that is the point of
    them. This is the one destructive statement the harness runs, and `scratch_database` has already proved the database is the scratch
    one.
    """
    async with factory() as session:
        await session.execute(text("TRUNCATE show_artist, show, artist, audit_log, agent_run RESTART IDENTITY CASCADE"))
        await session.commit()


async def ensure_venue(factory: async_sessionmaker[AsyncSession], facts: LabelVenueFacts) -> VenueFacts:
    """The venue row for a labelled venue (created, with the Minneapolis metro, if missing), as the worker sees it."""
    async with factory() as session:
        metro = (await session.execute(select(Metro).where(Metro.name == METRO_NAME))).scalar_one_or_none()
        if metro is None:
            metro = Metro(name=METRO_NAME, timezone=METRO_TIMEZONE, slug=METRO_SLUG)
            session.add(metro)
            await session.flush()
        venue_id = (
            await session.execute(select(Venue.id).where(Venue.metro_id == metro.id, Venue.name == facts.name))
        ).scalar_one_or_none()
        if venue_id is None:
            row = Venue(metro_id=metro.id, name=facts.name, calendar_url=facts.url, fetch_strategy=FetchStrategy.HTTP)
            session.add(row)
            await session.flush()
            venue_id = row.id
        await session.commit()
    async with factory() as session:
        [venue] = await load_venues(session, venue_id)
    return venue
