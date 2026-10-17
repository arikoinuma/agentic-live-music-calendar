"""Reconcile's decisions against a database seeded the way a venue looks after weeks of runs.

Milestone A5 (docs/dev/implementations/a5-reconcile.md; the build plan's A7 item "unit tests for reconcile's decision
logic against a seeded database", pulled forward). One venue has stored shows in every state reconcile cares about, and
one page is run through the REAL graph with the real `PostgresCalendarReader`, so the stored rows, the reader, the
wrapper that loads them and the decision logic are all exercised together; only the model is scripted.

Nothing here writes to the calendar (that is A6), so this proves the plan, not its effect.

The stored calendar (venue A; the page is fetched October 12, 2026 and reaches October 31):
    Oct 20 20:00  Nona               active, same as the page            -> no-op
    Oct 22 20:00  Zhora              active, the page adds an opener     -> update (lineup)
    Oct 23 20:00  Prince             active, not on the page             -> removed (absent, inside the window)
    Oct 24 20:00  Nona               REMOVED, the page lists it again    -> update back to active (reappeared)
    Nov 20 20:00  Prince             active, beyond the page's reach     -> not in the plan at all
The page also lists a new show with an artist stored under a different spelling ("Poliça" for "Polica": linked, no model
call) and one with an artist nobody has stored ("Sunny Day": a new artist).
Expected values are the requirements' rules (see test_reconcile_shows.py) applied to this table by hand.
"""

import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker import nodes
from agent_worker.audit import PostgresAuditWriter
from agent_worker.calendar_reader import PostgresCalendarReader
from agent_worker.context import WorkerContext
from agent_worker.main import VenueFacts, load_venues, run_venue
from agent_worker.reconcile import Action
from agent_worker.state import VenueGraphState
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    SPLITTER,
    RecordingStager,
    event,
    jsonld_page,
    scripted_client,
    split_answer,
)
from agent_worker.tests.test_calendar_reader import make_artist, make_show
from app.db.models import Artist, ShowArtist
from app.db.seed import seed
from app.enums import ShowStatus

PAGE = jsonld_page(
    event("Nona", "2026-10-20T20:00:00-05:00"),
    event("Zhora w. Prince", "2026-10-22T20:00:00-05:00"),
    event("Nona", "2026-10-24T20:00:00-05:00"),
    event("Poliça", "2026-10-28T20:00:00-05:00"),
    event("Sunny Day", "2026-10-31T20:00:00-05:00"),
)
ACTS = split_answer(
    ("Nona", ["Nona"]), ("Zhora w. Prince", ["Zhora", "Prince"]), ("Nona", ["Nona"]),
    ("Poliça", ["Poliça"]), ("Sunny Day", ["Sunny Day"]),
)


@pytest.fixture
def factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory on the test connection in savepoint mode (see test_run_venue.py)."""
    return async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def venue_run(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[VenueGraphState, dict[str, int], VenueFacts]:
    """Seed the calendar above, run venue A through the real graph on the page, return the final state, the artists'
    ids and the venue."""
    page = tmp_path / "page.html"
    page.write_text(PAGE)
    url = str(page)  # reconcile compares each show's stored `original_url` with this
    async with factory() as session:
        await seed(session)
        venue = (await load_venues(session))[0]
        artists = {n: make_artist(n) for n in ("Nona", "Zhora", "Prince", "Polica")}
        session.add_all(artists.values())
        await session.flush()
        ids = {n: a.id for n, a in artists.items()}

        def show(day: int, month: int, status: ShowStatus = ShowStatus.ACTIVE):
            return make_show(
                venue.id, datetime.date(2026, month, day), datetime.time(20, 0), status, original_url=url
            )

        shows = {
            "nona": show(20, 10), "zhora": show(22, 10), "prince": show(23, 10),
            "back": show(24, 10, ShowStatus.REMOVED), "later": show(20, 11),
        }
        session.add_all(shows.values())
        await session.flush()
        session.add_all([
            ShowArtist(show_id=shows["nona"].id, artist_id=ids["Nona"], sequence_number=1),
            ShowArtist(show_id=shows["zhora"].id, artist_id=ids["Zhora"], sequence_number=1),
            ShowArtist(show_id=shows["prince"].id, artist_id=ids["Prince"], sequence_number=1),
            ShowArtist(show_id=shows["back"].id, artist_id=ids["Nona"], sequence_number=1),
            ShowArtist(show_id=shows["later"].id, artist_id=ids["Prince"], sequence_number=1),
        ])
        await session.commit()
        ids.update({f"show_{k}": s.id for k, s in shows.items()})
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [ACTS]}))
    ctx = WorkerContext(
        audit=PostgresAuditWriter(factory), stager=RecordingStager(), reader=PostgresCalendarReader(factory)
    )
    state = await run_venue(venue, ctx, calendar_url=url, fetched_on=fakes.FETCHED)
    return state, ids, venue


async def test_each_stored_state_gets_the_decision_the_requirements_give_it(
    venue_run: tuple[VenueGraphState, dict[str, int], VenueFacts],
) -> None:
    # Proves: insert, update, no-op, soft delete and reactivation in one plan over real rows, in calendar order, and
    # that the November show beyond the page's reach is not touched.
    state, ids, _ = venue_run
    assert state.reconcile_plan is not None
    decisions = [(d.date.day, d.action, d.stored_id, d.reason) for d in state.reconcile_plan.shows]
    assert decisions == [
        (20, Action.NO_OP, ids["show_nona"], "unchanged"),
        (22, Action.UPDATE, ids["show_zhora"], "details changed"),
        (23, Action.REMOVE, ids["show_prince"], "absent from the page"),
        (24, Action.UPDATE, ids["show_back"], "reappeared"),
        (28, Action.INSERT, None, "new show"),
        (31, Action.INSERT, None, "new show"),
    ]
    assert ids["show_later"] not in {d.stored_id for d in state.reconcile_plan.shows}


async def test_the_added_opener_is_a_lineup_change_and_the_artists_resolve_without_the_model(
    venue_run: tuple[VenueGraphState, dict[str, int], VenueFacts],
) -> None:
    # Proves: the Oct 22 update is a lineup change (Prince added after Zhora), "Poliça" is linked to the stored "Polica"
    # by exact match (accents tidied, D8) and "Sunny Day" is a new artist. The model script has no artist-match
    # answer, so a model call for any of them would have failed the run.
    state, ids, _ = venue_run
    assert state.reconcile_plan is not None
    by_day = {d.date.day: d for d in state.reconcile_plan.shows}
    assert [e.artist_id for e in by_day[22].lineup] == [ids["Zhora"], ids["Prince"]] and "lineup" in by_day[22].changes
    assert [e.artist_id for e in by_day[28].lineup] == [ids["Polica"]]
    assert [(e.artist_id, e.name) for e in by_day[31].lineup] == [(None, "Sunny Day")]
    assert {r.outcome for r in state.reconcile_plan.artists} == {"exact", "new"}


async def test_the_window_runs_from_the_fetch_date_to_the_last_listed_date(
    venue_run: tuple[VenueGraphState, dict[str, int], VenueFacts],
) -> None:
    # Proves (D1): the plan's window is October 12 (the fetch date) to October 31 (the page's last listing), which is
    # why the November 20 show was outside it.
    state, _, _ = venue_run
    assert state.reconcile_plan is not None and state.reconcile_plan.coverage is not None
    assert (state.reconcile_plan.coverage.start, state.reconcile_plan.coverage.end) == (
        datetime.date(2026, 10, 12), datetime.date(2026, 10, 31),
    )


async def test_the_artists_table_is_unchanged_by_reconcile(
    venue_run: tuple[VenueGraphState, dict[str, int], VenueFacts], factory: async_sessionmaker[AsyncSession],
) -> None:
    # Proves: reconcile decides and writes nothing to the calendar (arch-initial.md §7: commit writes). Even for
    # "Sunny Day", a new artist, no `artist` row exists afterwards.
    async with factory() as session:
        names = sorted((await session.execute(select(Artist.name))).scalars().all())
    assert names == ["Nona", "Polica", "Prince", "Zhora"]
