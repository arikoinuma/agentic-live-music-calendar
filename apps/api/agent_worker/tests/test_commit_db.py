"""The whole loop against a real database: fetch to commit, with the real reader and the real writer; only the model is scripted.

Milestone A6 (docs/dev/implementations/a6-commit.md, Test approach §5). This is the test A5 could not write ("a real
database round trip is A6's test"): reconcile's plan is committed for real, then read back, and a second run proves the
property that stops a show flipping every night. It uses the seeded calendar of test_reconcile_db.py, a venue "after
weeks of runs": an unchanged show (Oct 20), a show that gains an opener (Oct 22), one absent from the page (Oct 23), a
removed one the page lists again (Oct 24), a new show with an artist stored under another spelling (Oct 28, "Poliça" for
"Polica"), a new show with a new artist (Oct 31, "Sunny Day"), and a November show beyond the page's reach.

Sections:
  1. Run 1 against the seeded calendar: the simulator's prediction (`reconcile_support.apply_plan`) against the real rows.
  2. Run 2 on the same page: all no-ops, nothing rewritten (A6-M4).
  3. Run 3 on an edited page, and the saved queries over the result.
  4. A run in which one show is refused, and a run that dies mid-commit (A6-D2, A6-M5).

Expected values are the requirements' rules applied to the seeded table by hand (as test_reconcile_db.py does) and the literal
pages. Dates are October 2026, fetched October 12.
"""

import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import InterfaceError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker import nodes
from agent_worker.artist_match import artist_key
from agent_worker.audit import PostgresAuditWriter
from agent_worker.calendar_reader import PostgresCalendarReader
from agent_worker.calendar_writer import PostgresCalendarWriter
from agent_worker.context import WorkerContext
from agent_worker.main import VenueFacts, load_venues, run_venue
from agent_worker.reconcile import Action, ReconcilePlan, StoredShow
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
from agent_worker.tests.reconcile_support import apply_plan
from agent_worker.tests.test_audit_queries import SQL_FILE, parse_queries, run
from agent_worker.tests.test_reconcile_db import ACTS, PAGE, seed_calendar
from app.db.models import Artist, AuditLog, Show, ShowArtist
from app.db.seed import seed
from app.enums import AuditOutcome, EntityType, ShowStatus, StepType

LONG_AGO = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
RANGE = (datetime.date(2026, 10, 1), datetime.date(2026, 12, 31))  # wide enough to read every seeded show back


@pytest.fixture
def factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory on the test connection in savepoint mode (see test_audit_writer.py)."""
    return async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


def real_context(factory: async_sessionmaker[AsyncSession], writer: Any = None) -> WorkerContext:
    """Everything real except MongoDB: the Postgres audit writer, reader and calendar writer on the test connection."""
    return WorkerContext(
        audit=PostgresAuditWriter(factory), stager=RecordingStager(), reader=PostgresCalendarReader(factory),
        writer=writer or PostgresCalendarWriter(factory),
    )


async def run_page(
    factory: async_sessionmaker[AsyncSession], venue: VenueFacts, page: Path, html: str, answer: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch, writer: Any = None,
) -> VenueGraphState:
    """Run the real graph on `html` (written to `page`) with the act splitter scripted to `answer`."""
    page.write_text(html)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [answer]}))
    return await run_venue(venue, real_context(factory, writer), calendar_url=str(page), fetched_on=fakes.FETCHED)


class Committed:
    """What run 1 left: the state, the seeded ids, the venue, and what the calendar was BEFORE the run (for the simulator)."""

    def __init__(
        self, state: VenueGraphState, ids: dict[str, int], venue: VenueFacts, before: list[StoredShow], known: list[Any],
        page: Path,
    ) -> None:
        self.state, self.ids, self.venue, self.before, self.known, self.page = state, ids, venue, before, known, page

    @property
    def plan(self) -> ReconcilePlan:
        assert self.state.reconcile_plan is not None
        return self.state.reconcile_plan


@pytest_asyncio.fixture(loop_scope="session")
async def run1(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Committed:
    """Seed the calendar, remember it, and commit the page of test_reconcile_db.py for real."""
    page = tmp_path / "page.html"
    venue, ids = await seed_calendar(factory, str(page))
    reader = PostgresCalendarReader(factory)
    before = await reader.stored_shows(venue.id, *RANGE)
    known = await reader.artists()
    state = await run_page(factory, venue, page, PAGE, ACTS, monkeypatch)
    return Committed(state, ids, venue, before, known, page)


async def commit_rows(factory: async_sessionmaker[AsyncSession], run_id: int | None = None) -> list[AuditLog]:
    """The `commit` audit rows (of one run, or all), oldest first, read through a fresh ORM session."""
    query = select(AuditLog).where(AuditLog.step_type == StepType.COMMIT).order_by(AuditLog.id)
    if run_id is not None:
        query = query.where(AuditLog.run_id == run_id)
    async with factory() as session:
        return list((await session.execute(query)).scalars())


def comparable(shows: list[StoredShow]) -> list[tuple[Any, ...]]:
    """Stored shows reduced to what the simulator and the real write must agree on, ignoring ids and the spelling of
    artist names (the simulator keeps the page's spelling, the database the stored one): the date, times, status, prices,
    free flag, poster, and the lineup as (tidied name, own time, sequence). `original_url` is left out: the simulator's
    is a constant, the real one the page's path."""
    return sorted(
        (
            s.date, s.start_time, s.end_time, s.status.value, s.admission_advance, s.admission_day, s.free_admission,
            s.image_url, tuple((artist_key(e.artist_name), e.start_time, e.sequence_number) for e in s.ordered_lineup()),
        )
        for s in shows
    )


# ---------------------------------------------------------------------------
# 1. Run 1: the simulator against the real rows
# ---------------------------------------------------------------------------


async def test_the_real_commit_leaves_the_calendar_the_simulator_predicted(
    run1: Committed, factory: async_sessionmaker[AsyncSession],
) -> None:
    # Proves (A5 "Departures", A6): `reconcile_support.apply_plan`, which A5's idempotency test relies on, is a faithful
    # mirror of the real write. The plan is committed for real, the stored shows are read back, and they equal what the
    # simulator predicted for the same plan and the same starting calendar: so A5's evidence about idempotency is
    # evidence about the real thing, not only about a model of it.
    predicted, predicted_artists = apply_plan(run1.plan, run1.before, run1.known)
    reader = PostgresCalendarReader(factory)
    actual = await reader.stored_shows(run1.venue.id, *RANGE)
    assert comparable(actual) == comparable(predicted)
    assert sorted(artist_key(a.name) for a in await reader.artists()) == sorted(artist_key(a.name) for a in predicted_artists)


async def test_each_decision_was_written_as_the_requirements_say(
    run1: Committed, factory: async_sessionmaker[AsyncSession],
) -> None:
    # Proves (A5-D6, A5-D7, A6-D1): after run 1, by the seeded table worked by hand: the Oct 23 show is removed, the
    # Oct 24 show is back to active, the Oct 22 show has both acts in order, the November show is untouched, Oct 28 and 31
    # are new rows, and Oct 20 (a no-op) was not rewritten (its `original_url` and lineup are as seeded).
    by_date = {s.date: s for s in await PostgresCalendarReader(factory).stored_shows(run1.venue.id, *RANGE)}
    assert by_date[datetime.date(2026, 10, 23)].status is ShowStatus.REMOVED
    assert by_date[datetime.date(2026, 10, 24)].status is ShowStatus.ACTIVE
    assert by_date[datetime.date(2026, 10, 24)].id == run1.ids["show_back"]  # the same row came back (A5-D7)
    assert [e.artist_name for e in by_date[datetime.date(2026, 10, 22)].ordered_lineup()] == ["Zhora", "Prince"]
    assert by_date[datetime.date(2026, 11, 20)].status is ShowStatus.ACTIVE and by_date[datetime.date(2026, 11, 20)].id == run1.ids["show_later"]
    assert {d.day for d in by_date if d.month == 10} == {20, 22, 23, 24, 28, 31}
    assert [e.artist_id for e in by_date[datetime.date(2026, 10, 28)].lineup] == [run1.ids["Polica"]]  # linked, not duplicated


async def test_an_unchanged_show_gets_no_audit_row_and_every_write_gets_one(
    run1: Committed, factory: async_sessionmaker[AsyncSession],
) -> None:
    # Proves (A6-D1): run 1 wrote four shows (an update, a removal, a reactivation, two inserts: five writes), so five
    # show rows plus one artist row (Sunny Day) plus the summary; the unchanged Oct 20 show has none. Every show row has the
    # outcome of its decision.
    rows = await commit_rows(factory, run1.state.run_id)
    show_rows = [r for r in rows if r.entity_type is EntityType.SHOW]
    assert sorted(r.outcome.value for r in show_rows if r.outcome) == ["inserted", "inserted", "removed", "updated", "updated"]
    assert run1.ids["show_nona"] not in {r.entity_id for r in show_rows}
    assert [r.entity_type for r in rows if r.entity_type is EntityType.ARTIST] == [EntityType.ARTIST]
    assert rows[-1].entity_type is EntityType.VENUE and rows[-1].detail["counts"] == {
        "inserted": 2, "updated": 2, "removed": 1, "no_op": 1, "skip": 0,
    }


async def test_the_artists_table_holds_the_old_artists_plus_the_new_one_once(
    run1: Committed, factory: async_sessionmaker[AsyncSession],
) -> None:
    # Proves (A5-D8, A6): the four artists seeded plus "Sunny Day", each once: "Poliça" matched the stored "Polica"
    # instead of becoming a second row, and nothing else was created.
    async with factory() as session:
        names = sorted((await session.execute(select(Artist.name))).scalars().all())
    assert names == ["Nona", "Polica", "Prince", "Sunny Day", "Zhora"]


# ---------------------------------------------------------------------------
# 2. Run 2: the same page again
# ---------------------------------------------------------------------------


async def counts_and_stamps(factory: async_sessionmaker[AsyncSession]) -> tuple[Any, ...]:
    """Row counts of the three tables commit writes, and every show's `updated_at`, to compare before and after."""
    async with factory() as session:
        shows = (await session.execute(select(func.count()).select_from(Show))).scalar_one()
        links = (await session.execute(select(func.count()).select_from(ShowArtist))).scalar_one()
        artists = (await session.execute(select(func.count()).select_from(Artist))).scalar_one()
        stamps = sorted((await session.execute(select(Show.id, Show.updated_at))).all())
    return shows, links, artists, stamps


async def test_the_second_run_is_all_no_ops(
    run1: Committed, factory: async_sessionmaker[AsyncSession], db_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A6-M4; the property that stops a show flipping every night): run the same page again and the plan is all
    # no-ops (and the shows past the window untouched), no row is added or rewritten, and no per-show commit row is added,
    # only the summary. Every show's `updated_at` is first set to a literal past time: inside the test transaction `now()`
    # never moves, so a rewritten row would get the transaction's start, a different value, while comparing two `now()`s
    # would prove nothing (A6-PR1-3). Skipping the price conversion would make `20.0` compare unequal to the stored
    # Decimal("20.00") and fail this test.
    await db_conn.execute(update(Show).values(updated_at=LONG_AGO))
    before = await counts_and_stamps(factory)
    state = await run_page(factory, run1.venue, run1.page, PAGE, ACTS, monkeypatch)

    assert state.reconcile_plan is not None
    assert {d.action for d in state.reconcile_plan.shows if d.date.month == 10} <= {Action.NO_OP}
    assert await counts_and_stamps(factory) == before
    rows = await commit_rows(factory, state.run_id)
    assert [r.entity_type for r in rows] == [EntityType.VENUE]
    # five no-ops: Oct 20, 22, 24, 28 and 31 (the removed Oct 23 show is not listed; the November show is beyond the window)
    assert rows[0].detail["counts"]["inserted"] == 0 and rows[0].detail["counts"]["no_op"] == 5


async def test_a_price_round_trips_exactly_and_a_second_run_does_not_rewrite_it(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (build plan A6, the [written] price item, end to end): a model-route listing with an advance price of 19.99 and
    # a day price of 25.0 is stored as exactly Decimal("19.99") and Decimal("25.00") (the columns are Numeric(10, 2)), and
    # the second run compares them equal, so it is a no-op and not an update. (That the write converts through
    # `to_price` and not `Decimal(float)` is pinned in test_commit_ops.py: Postgres rounds to two places, so the
    # database alone would hide the difference.)
    venue = await bare_venue(factory)
    page = tmp_path / "page.html"
    page.write_text(fakes.text_page("Nona", "Oct 20", "8 pm"))
    answer = fakes.listings_answer(
        fakes.listing("2026-10-20", "Nona", time="20:00", admission_advance=19.99, admission_day=25.0)
    )
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({fakes.PAGE: [answer], SPLITTER: [split_answer(("Nona", ["Nona"]))]}))
    first = await run_venue(venue, real_context(factory), calendar_url=str(page), fetched_on=fakes.FETCHED)
    assert first.commit_result is not None and first.commit_result.written["inserted"] == 1
    [shown] = await PostgresCalendarReader(factory).stored_shows(venue.id, *RANGE)
    assert (shown.admission_advance, shown.admission_day) == (Decimal("19.99"), Decimal("25.00"))
    assert str(shown.admission_advance) == "19.99"

    monkeypatch.setattr(nodes, "instructor_client", scripted_client({fakes.PAGE: [answer], SPLITTER: [split_answer(("Nona", ["Nona"]))]}))
    second = await run_venue(venue, real_context(factory), calendar_url=str(page), fetched_on=fakes.FETCHED)
    assert second.reconcile_plan is not None and [d.action for d in second.reconcile_plan.shows] == [Action.NO_OP]
    assert second.commit_result is not None and second.commit_result.written["updated"] == 0


# ---------------------------------------------------------------------------
# 3. Run 3: an edited page, and the saved queries
# ---------------------------------------------------------------------------

# The page after the venue dropped the Oct 24 show and the Oct 22 opener: Nona (Oct 20), Zhora alone (Oct 22), Poliça
# (Oct 28), Sunny Day (Oct 31).
PAGE3 = jsonld_page(
    event("Nona", "2026-10-20T20:00:00-05:00"), event("Zhora", "2026-10-22T20:00:00-05:00"),
    event("Poliça", "2026-10-28T20:00:00-05:00"), event("Sunny Day", "2026-10-31T20:00:00-05:00"),
)
ACTS3 = split_answer(("Nona", ["Nona"]), ("Zhora", ["Zhora"]), ("Poliça", ["Poliça"]), ("Sunny Day", ["Sunny Day"]))


async def test_an_edited_page_writes_exactly_its_changes_and_show_history_tells_the_story(
    run1: Committed, factory: async_sessionmaker[AsyncSession], db_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A6-D1, saved query `show_history`): the third run changes only what the page changed: the Oct 22 show loses its
    # opener (an update, lineup only) and the Oct 24 show is gone (a removal); everything else is a no-op. And
    # `show_history` for the Oct 22 show returns its two writes in order, the run-1 update (opener added) then the run-3
    # update (opener dropped), each with before and after: "what changed about this show, and when".
    queries = parse_queries(SQL_FILE.read_text())
    state = await run_page(factory, run1.venue, run1.page, PAGE3, ACTS3, monkeypatch)
    assert state.reconcile_plan is not None
    changed = {d.date.day: d.action for d in state.reconcile_plan.shows if d.action is not Action.NO_OP}
    assert changed == {22: Action.UPDATE, 24: Action.REMOVE}

    history = await run(db_conn, queries["show_history"], show_id=run1.ids["show_zhora"])
    assert [r["run_id"] for r in history] == [run1.state.run_id, state.run_id]
    assert [r["outcome"] for r in history] == ["updated", "updated"]
    first, second = history
    assert [e["artist_id"] for e in first["new_value"]["lineup"]] == [run1.ids["Zhora"], run1.ids["Prince"]]
    assert [e["artist_id"] for e in second["previous_value"]["lineup"]] == [run1.ids["Zhora"], run1.ids["Prince"]]
    assert [e["artist_id"] for e in second["new_value"]["lineup"]] == [run1.ids["Zhora"]]
    assert first["previous_value"]["status"] == second["new_value"]["status"] == "active"


# ---------------------------------------------------------------------------
# 4. A show the database refuses; a run that dies mid-commit
# ---------------------------------------------------------------------------


async def bare_venue(factory: async_sessionmaker[AsyncSession]) -> VenueFacts:
    """A seeded venue with nothing stored (no shows, no artists)."""
    async with factory() as session:
        await seed(session)
        venue = (await load_venues(session))[0]
        await session.commit()
    return venue


# The first show has an end time (refused below). The JSON-LD route keeps a structured end time only when the page's own
# text states it after the show's title (A2.1-D10), so the body says "11:00 pm" right after "Nona".
TWO_NEW = jsonld_page(
    event("Nona", "2026-10-20T20:00:00-05:00", endDate="2026-10-20T23:00:00-05:00"),
    event("Zhora", "2026-10-21T20:00:00-05:00"),
    body="Nona Oct 20 8:00 pm - 11:00 pm. Zhora Oct 21 8:00 pm.",
)
TWO_NEW_ACTS = split_answer(("Nona", ["Nona"]), ("Zhora", ["Zhora"]))


async def test_a_run_with_one_refused_show_writes_the_rest_and_is_not_unfinished(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_conn: AsyncConnection,
) -> None:
    # Proves (A6-D2): a constraint added for this test, inside the test transaction (DDL is transactional, so the outer
    # rollback removes it), refuses any show that has an end time. Of two new shows the first has one: it is refused
    # (a class-23 `IntegrityError`) and the second is written. The failure is a row that says which show (October 20, 8 PM),
    # `failed_commits` returns it, the summary was written so `unfinished_runs` does not list the run, and the result
    # carries the failure for `run_all` to count.
    venue = await bare_venue(factory)
    await db_conn.execute(text("ALTER TABLE show ADD CONSTRAINT tmp_no_end_time CHECK (end_time IS NULL) NOT VALID"))
    queries = parse_queries(SQL_FILE.read_text())
    state = await run_page(factory, venue, tmp_path / "page.html", TWO_NEW, TWO_NEW_ACTS, monkeypatch)

    assert state.commit_result is not None and state.commit_result.written["inserted"] == 1
    [failure] = state.commit_result.failures
    assert (failure.date, failure.time, failure.sqlstate) == (datetime.date(2026, 10, 20), datetime.time(20, 0), "23514")
    stored = await PostgresCalendarReader(factory).stored_shows(venue.id, *RANGE)
    assert [s.date.day for s in stored] == [21]
    [row] = await run(db_conn, queries["failed_commits"])
    assert (row["run_id"], row["show_date"], row["show_time"], row["sqlstate"]) == (state.run_id, "2026-10-20", "20:00:00", "23514")
    assert state.run_id not in {r["run_id"] for r in await run(db_conn, queries["unfinished_runs"])}


class LosesTheConnectionOnTheSecondWrite(PostgresCalendarWriter):
    """Writes the first show for real, then loses the database: the crash `unfinished_runs` exists to find."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(factory)
        self.calls = 0

    async def write_show(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls == 2:
            raise fakes.lost_connection()
        return await super().write_show(*args, **kwargs)


async def test_a_run_that_crashed_mid_commit_is_unfinished(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_conn: AsyncConnection,
) -> None:
    # Proves (A6-M5, A6-PR2-4): the writer delegates to the real one for the FIRST operation, then raises the real lost-
    # connection shape on the second. Exactly one per-show `commit` row exists (the first show was written), NO summary row
    # exists, and `unfinished_runs` lists the run with `commit` as its furthest step. (A writer that raised on the first
    # operation would leave no commit row at all, and a query that counted any commit row as "finished" would still list
    # the run: the check would prove nothing.) The run was closed by `run_venue`'s finally, so it has a `finished_at`.
    venue = await bare_venue(factory)
    queries = parse_queries(SQL_FILE.read_text())
    with pytest.raises(InterfaceError):
        await run_page(
            factory, venue, tmp_path / "page.html", TWO_NEW, TWO_NEW_ACTS, monkeypatch,
            writer=LosesTheConnectionOnTheSecondWrite(factory),
        )
    rows = await commit_rows(factory)
    assert [(r.entity_type, r.outcome) for r in rows if r.entity_type is EntityType.SHOW] == [
        (EntityType.SHOW, AuditOutcome.INSERTED),
    ]
    assert not [r for r in rows if r.entity_type is EntityType.VENUE]
    [unfinished] = await run(db_conn, queries["unfinished_runs"])
    assert unfinished["furthest_step"] == "commit" and unfinished["finished_at"] is not None

