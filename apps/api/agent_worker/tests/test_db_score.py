"""Tests for scoring the database a graph run leaves behind (`eval/db_score.py`), against a real Postgres.

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, Test approach §5). The harness runs the graph on a page, then
again, and holds the rows left behind to what a perfect pipeline would have left. These tests use the real reader, writer and
audit writer on the `calendar_test` database (the savepoint pattern of test_run_venue.py), the real compiled graph, and a
scripted model: JSON-LD pages, so the act splitter is the only call.

How to read it, in four sections:
  1. `committed_extraction`: rows into the extraction shape the scorer reads.
  2. The scenarios' MECHANICS (repeat, sequence, overlap, perturbed): what the pipeline did, asserted on the rows directly and
     on reconcile's decisions. These pass without Ari's gap.
  3. `reset`, the one destructive statement the harness runs.
  4. `expected_rows` (C5-K3): what the database SHOULD hold after the second run. Red until Ari fills the TODO.

Expected values are the literal pages, the scripted answers, and the rules of reconcile (docs/dev/implementations/a5-reconcile.md:
the window is the second fetch's date to the latest date the page evidences; a changed non-null time is a remove plus an insert;
a time that appears later is an update). Dates are 2026; JSON-LD events are 9 PM Central.
"""

import datetime
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker import nodes
from agent_worker.audit import PostgresAuditWriter
from agent_worker.calendar_reader import PostgresCalendarReader
from agent_worker.calendar_writer import PostgresCalendarWriter
from agent_worker.context import WorkerContext
from agent_worker.eval import db_score
from agent_worker.eval.db_score import Scenario, ScenarioPage
from agent_worker.eval.graph_run import InMemoryStager
from agent_worker.eval.labels import LabelledShow, NonShow, PageLabel
from agent_worker.eval.labels import VenueFacts as LabelVenueFacts
from agent_worker.main import VenueFacts
from agent_worker.tests.fakes import (
    SPLITTER,
    event,
    jsonld_page,
    scripted_client,
    split_answer,
)
from app.db.models import Artist, AuditLog, Show, ShowArtist, Venue
from app.enums import ShowStatus

D = datetime.date
T = datetime.time


@pytest.fixture
def factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory on the test connection, in savepoint mode: the writers `commit()` as in production, and the outer
    rollback (app/testing/db.py) leaves nothing behind."""
    return async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest.fixture
def ctx(factory: async_sessionmaker[AsyncSession]) -> WorkerContext:
    """The real Postgres stores, and the in-memory stager the harness uses in place of MongoDB (C5-D2)."""
    return WorkerContext(
        audit=PostgresAuditWriter(factory), stager=InMemoryStager(),
        reader=PostgresCalendarReader(factory), writer=PostgresCalendarWriter(factory),
    )


@pytest_asyncio.fixture(loop_scope="session")
async def venue(factory: async_sessionmaker[AsyncSession]) -> VenueFacts:
    """A venue row made by the harness's own `ensure_venue` (and the metro it needs)."""
    return await db_score.ensure_venue(factory, LabelVenueFacts("The Test Venue", "https://example.test/calendar"))


def page(
    tmp_path: Path, name: str, days: list[tuple[str, str]], captured_on: datetime.date, *, extra: list[dict[str, Any]] | None = None,
) -> ScenarioPage:
    """A JSON-LD fixture file with one 9 PM event per (date, act) and its label. `extra` events are added to the page only
    (not labelled as shows), for a case like a cancelled listing, which the caller labels itself."""
    events = [event(act, f"{day}T21:00:00-05:00") for day, act in days] + (extra or [])
    path = tmp_path / f"{name}.html"
    path.write_text(jsonld_page(*events))
    shows = tuple(LabelledShow(D.fromisoformat(day), (act,), act, T(21, 0)) for day, act in days)
    label = PageLabel(venue="test_venue", gated=True, captured_on=captured_on, shows=shows)
    return ScenarioPage(label=label, fixture=path)


def script_for(*pages: ScenarioPage) -> Any:
    """The act splitter's answer for each page, in the order the pages run: one call per page, each title splitting to itself.
    The script repeats its last step, so a scenario that runs one page twice needs one answer."""
    return {SPLITTER: [split_answer(*[(s.acts[0], [s.acts[0]]) for s in p.label.shows]) for p in pages]}


async def active_rows(factory: async_sessionmaker[AsyncSession], venue_id: int) -> list[tuple[datetime.date, datetime.time | None]]:
    """The venue's active shows as (date, start time), oldest first, read straight from the table."""
    async with factory() as session:
        rows = await session.execute(
            select(Show.date, Show.start_time).where(Show.venue_id == venue_id, Show.status == ShowStatus.ACTIVE)
            .order_by(Show.date, Show.start_time)
        )
        return [(d, t) for d, t in rows.all()]


# ---------------------------------------------------------------------------
# 1. committed_extraction: rows into the shape the scorer reads
# ---------------------------------------------------------------------------


async def test_committed_extraction_reads_active_shows_with_acts_in_sequence_order(
    factory: async_sessionmaker[AsyncSession], venue: VenueFacts,
) -> None:
    # Proves: C5-M5 and the lineup order. The rows left are the venue's ACTIVE shows (a removed show is not "left"), each with
    # its acts in `sequence_number` order, times as ISO text and prices as floats, so the dict goes through `score_page` and
    # `json.dumps` unchanged (a Decimal would not). Expected values are the literal rows inserted here.
    async with factory() as session:
        opener, headliner = Artist(name="Opener"), Artist(name="Headliner")
        live = Show(
            venue_id=venue.id, date=D(2026, 10, 20), start_time=T(21, 0), admission_day=Decimal("12.50"),
            status=ShowStatus.ACTIVE,
        )
        gone = Show(venue_id=venue.id, date=D(2026, 10, 21), status=ShowStatus.REMOVED)
        session.add_all([opener, headliner, live, gone])
        await session.flush()
        session.add_all([
            ShowArtist(show_id=live.id, artist_id=headliner.id, sequence_number=2),
            ShowArtist(show_id=live.id, artist_id=opener.id, sequence_number=1),
        ])
        await session.commit()
    extraction = await db_score.committed_extraction(factory, venue.id)
    [show] = extraction["shows"]
    assert (show["date"], show["time"], show["admission_day"]) == ("2026-10-20", "21:00:00", 12.5)
    assert [a["name"] for a in show["acts"]] == ["Opener", "Headliner"]
    import json

    json.dumps(extraction)  # serialisable as is


# ---------------------------------------------------------------------------
# 2. The scenarios' mechanics
# ---------------------------------------------------------------------------


async def test_the_same_page_twice_changes_nothing_the_second_time(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: the REPEAT scenario (A5 idempotence; local_test.py's stated expectation). Run 1 inserts every show; run 2 finds
    # every one already stored and does nothing: all no-ops, the same rows, and `count_differences` (the harness's report of
    # where reality departs from this expectation) is empty.
    first = page(tmp_path, "a", [("2026-10-20", "Nona"), ("2026-10-21", "Lent"), ("2026-10-22", "Chicken Wire")], D(2026, 10, 12))
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script_for(first)))
    result = await db_score.run_scenario(Scenario.REPEAT, first=first, second=None, venue=venue, ctx=ctx, factory=factory)
    run1, run2 = result.runs
    assert run1.reconcile_counts is not None and run2.reconcile_counts is not None
    assert (run1.reconcile_counts["insert"], run2.reconcile_counts["insert"]) == (3, 0)
    assert run2.reconcile_counts["no_op"] == 3
    assert result.count_differences == []
    assert run1.committed == run2.committed


async def test_a_second_page_in_a_later_month_leaves_the_first_pages_rows_alone(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: the SEQUENCE scenario, the "a page listing two weeks must not remove week three" case. Page A lists October 20
    # and 21 (fetched Oct 12); page B lists November 20 and 21 (fetched Nov 19). B's window starts at ITS fetch date, Nov 19,
    # after A's last date, so A's rows are neither read nor removed: four active rows. Pinned to this shape because with B's
    # dates before A's the window would cover A (reconcile.covered_window starts at fetched_on).
    first = page(tmp_path, "a", [("2026-10-20", "Nona"), ("2026-10-21", "Lent")], D(2026, 10, 12))
    second = page(tmp_path, "b", [("2026-11-20", "Sunny Day"), ("2026-11-21", "Poliça")], D(2026, 11, 19))
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script_for(first, second)))
    await db_score.run_scenario(Scenario.SEQUENCE, first=first, second=second, venue=venue, ctx=ctx, factory=factory)
    assert [d for d, _ in await active_rows(factory, venue.id)] == [D(2026, 10, 20), D(2026, 10, 21), D(2026, 11, 20), D(2026, 11, 21)]


async def test_a_second_page_that_drops_a_show_inside_its_window_removes_only_that_show(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: the OVERLAP scenario. Both pages are fetched Oct 12; A lists the 20th, 21st and 22nd, B only the 20th and 22nd.
    # The 21st is inside B's window (Oct 12 to Oct 22) and no longer listed, so it is soft-deleted (`removed`); the shared
    # shows are no-ops and nothing appears twice. One removal is below the mass-removal guard (A5-D10: at least 3).
    first = page(tmp_path, "a", [("2026-10-20", "Nona"), ("2026-10-21", "Lent"), ("2026-10-22", "Chicken Wire")], D(2026, 10, 12))
    second = page(tmp_path, "b", [("2026-10-20", "Nona"), ("2026-10-22", "Chicken Wire")], D(2026, 10, 12))
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script_for(first, second)))
    result = await db_score.run_scenario(Scenario.OVERLAP, first=first, second=second, venue=venue, ctx=ctx, factory=factory)
    assert [d for d, _ in await active_rows(factory, venue.id)] == [D(2026, 10, 20), D(2026, 10, 22)]
    counts = result.runs[1].reconcile_counts
    assert counts is not None and (counts["remove"], counts["no_op"], counts["insert"]) == (1, 2, 0)
    async with factory() as session:
        removed = (await session.execute(select(func.count()).select_from(Show).where(Show.status == ShowStatus.REMOVED))).scalar_one()
    assert removed == 1


async def test_a_perturbed_database_is_repaired_by_the_next_run_with_an_update_a_remove_and_an_insert(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: C5-PR1-3. After run 1 the harness sets one row's start time to NULL, deletes another row, and adds a stale row
    # inside the window; run 2 on the same page then does exactly: 1 UPDATE (a time that appears later is an update, A5), 1
    # INSERT (the deleted row comes back), 1 REMOVE (the stale row) and a no-op for the rest. A changed non-null time would be a
    # remove plus an insert (A5-D3) and never exercise an update, which is why the perturbation is "time to NULL". The rows
    # after run 2 are the rows after run 1.
    first = page(tmp_path, "a", [("2026-10-20", "Nona"), ("2026-10-21", "Lent"), ("2026-10-22", "Chicken Wire")], D(2026, 10, 12))
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script_for(first)))
    result = await db_score.run_scenario(Scenario.PERTURBED, first=first, second=None, venue=venue, ctx=ctx, factory=factory)
    counts = result.runs[1].reconcile_counts
    assert counts is not None
    assert (counts["update"], counts["insert"], counts["remove"], counts["no_op"]) == (1, 1, 1, 1)
    assert result.count_differences == []
    assert await active_rows(factory, venue.id) == [(D(2026, 10, 20), T(21, 0)), (D(2026, 10, 21), T(21, 0)), (D(2026, 10, 22), T(21, 0))]


async def test_a_cancelled_listing_is_not_in_the_rows_and_is_not_counted_missed(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: C5-PR1-5 and C5-M6. A page lists one live show and one cancelled one (labelled with its status, A2.1-D12).
    # Reconcile skips the cancelled listing with nothing stored, and `ShowStatus` has no cancelled value, so the database holds
    # one row. Scored against the full label that would be a missed show on every run; the committed column is scored against
    # `scheduled_only(label)`, so it is 0 missed.
    cancelled = event("Gone Band", "2026-10-21T21:00:00-05:00", eventStatus="https://schema.org/EventCancelled")
    first = page(tmp_path, "a", [("2026-10-20", "Nona")], D(2026, 10, 12), extra=[cancelled])
    label = replace(first.label, shows=(
        *first.label.shows, LabelledShow(D(2026, 10, 21), ("Gone Band",), "Gone Band", T(21, 0), status="cancelled"),
    ))
    first = ScenarioPage(label=label, fixture=first.fixture)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [split_answer(("Nona", ["Nona"]), ("Gone Band", ["Gone Band"]))]}))
    result = await db_score.run_scenario(Scenario.REPEAT, first=first, second=None, venue=venue, ctx=ctx, factory=factory)
    run1 = result.runs[0]
    assert len(run1.committed["shows"]) == 1
    assert run1.committed_score["missed"] == 0
    assert run1.reconcile_counts is not None and run1.reconcile_counts["skip"] == 1


# ---------------------------------------------------------------------------
# 3. The reset between independent pages
# ---------------------------------------------------------------------------


async def test_reset_empties_the_calendar_and_audit_tables_but_keeps_venues_and_the_metro(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: C5-PR1-12 (e). Between independent pages the harness truncates what a run writes (shows, lineups, artists, the
    # audit trail and runs) so one page's artists cannot change how the next page's artists are matched; it must never touch
    # `venue` or `metro`, which are the harness's own setup. This is the one destructive statement the harness runs.
    first = page(tmp_path, "a", [("2026-10-20", "Nona")], D(2026, 10, 12))
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script_for(first)))
    await db_score.run_scenario(Scenario.REPEAT, first=first, second=None, venue=venue, ctx=ctx, factory=factory)
    await db_score.reset(factory)
    async with factory() as session:
        for model in (Show, ShowArtist, Artist, AuditLog):
            assert (await session.execute(select(func.count()).select_from(model))).scalar_one() == 0, model.__name__
        assert (await session.execute(select(func.count()).select_from(Venue).where(Venue.id == venue.id))).scalar_one() == 1


# ---------------------------------------------------------------------------
# 4. C5-K3: what the database SHOULD hold (red until Ari fills expected_rows)
# ---------------------------------------------------------------------------


def labelled_page(captured_on: datetime.date, *days: str, status: str = "scheduled", non_show_days: tuple[str, ...] = ()) -> PageLabel:
    """A label with one show per ISO date (acts named for the day), all with the given status."""
    return PageLabel(
        venue="test_venue", gated=True, captured_on=captured_on,
        shows=tuple(LabelledShow(D.fromisoformat(d), (f"Act {d}",), d, status=status) for d in days),
        non_shows=tuple(NonShow(f"Open mic {d}", D.fromisoformat(d), None, "open mic") for d in non_show_days),
    )


def dates(shows: list[LabelledShow]) -> list[str]:
    return sorted(s.date.isoformat() for s in shows)


def test_expected_rows_for_a_repeat_or_perturbed_run_are_the_one_pages_scheduled_shows() -> None:
    # Proves: C5-K3, the simple half. A repeat and a perturbed run both converge on the single page's live shows, and a
    # labelled cancelled or postponed show is ABSENT (ShowStatus has no such value; reconcile skips it, A2.1-D12 +
    # Action.SKIP). Expected: the page's three scheduled dates.
    first = replace(labelled_page(D(2026, 10, 12), "2026-10-20", "2026-10-21"), shows=(
        *labelled_page(D(2026, 10, 12), "2026-10-20", "2026-10-21").shows,
        *labelled_page(D(2026, 10, 12), "2026-10-22", status="cancelled").shows,
    ))
    for scenario in (Scenario.REPEAT, Scenario.PERTURBED):
        assert dates(db_score.expected_rows(scenario, first, None)) == ["2026-10-20", "2026-10-21"]


def test_expected_rows_after_pages_a_month_apart_hold_both_pages() -> None:
    # Proves: C5-K3, the window rule. The second fetch's window starts at ITS date (Nov 19), after the first page's last date,
    # so the first page's shows survive and the database holds both pages' shows. The likeliest mistake is returning only the
    # second page's shows, which scores the first page's surviving rows as invented shows.
    first = labelled_page(D(2026, 10, 12), "2026-10-20", "2026-10-21")
    second = labelled_page(D(2026, 11, 19), "2026-11-20", "2026-11-21")
    assert dates(db_score.expected_rows(Scenario.SEQUENCE, first, second)) == [
        "2026-10-20", "2026-10-21", "2026-11-20", "2026-11-21",
    ]


def test_expected_rows_after_overlapping_pages_drop_what_the_window_removes_and_list_shared_shows_once() -> None:
    # Proves: C5-K3, the overlap case. The second page (fetched Oct 12) lists the 20th and 22nd; its window is Oct 12 to Oct 22,
    # so the first page's show on the 21st is removed, and a show on both pages is ONE row, not two. A first-page show on Oct 10,
    # before the window starts, survives. The likeliest mistake is concatenating both lists (the shared dates would appear
    # twice and score as missing rows).
    first = labelled_page(D(2026, 10, 12), "2026-10-10", "2026-10-20", "2026-10-21", "2026-10-22")
    second = labelled_page(D(2026, 10, 12), "2026-10-20", "2026-10-22")
    rows = db_score.expected_rows(Scenario.OVERLAP, first, second)
    assert dates(rows) == ["2026-10-10", "2026-10-20", "2026-10-22"]


def test_expected_rows_window_end_includes_the_dates_of_listed_non_shows() -> None:
    # Proves: C5-K3. A listing the pipeline leaves out (an open mic, a cancelled night) still evidences how far the page
    # reaches (reconcile's `excluded_listing_dates`), so it extends the window: the second page lists shows on the 20th and a
    # non-show on the 25th, so a first-page show on the 24th is INSIDE the window and removed; without the non-show date the
    # window would end on the 20th and the 24th would survive.
    first = labelled_page(D(2026, 10, 12), "2026-10-20", "2026-10-24")
    second = labelled_page(D(2026, 10, 12), "2026-10-20", non_show_days=("2026-10-25",))
    assert dates(db_score.expected_rows(Scenario.OVERLAP, first, second)) == ["2026-10-20"]


# ---------------------------------------------------------------------------
# Code review round 1 (C5-CR1-2): a scenario that cannot be perturbed is reported, not fatal
# ---------------------------------------------------------------------------


async def test_a_perturbed_scenario_whose_first_run_left_nothing_to_perturb_is_reported_not_raised(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: C5-CR1-2. When the first run escalates (here the splitter drops a title on every attempt) it commits nothing, so
    # there are no rows to damage. That is an OUTCOME of the model, not an infrastructure failure, so the scenario returns with
    # `not_run` set and the first run's record, instead of raising and losing every page already run in the invocation.
    first = page(tmp_path, "a", [("2026-10-20", "Nona"), ("2026-10-21", "Lent")], D(2026, 10, 12))
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [split_answer(("Nona", ["Nona"]))]}))
    result = await db_score.run_scenario(Scenario.PERTURBED, first=first, second=None, venue=venue, ctx=ctx, factory=factory)
    assert result.not_run is not None and "perturbed" in result.not_run
    assert len(result.runs) == 1 and result.runs[0].escalated
    assert result.perturbation is None


async def test_the_runner_skips_the_database_score_of_a_scenario_that_was_not_run(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: C5-CR1-2 through `graph_eval.run_scenarios`: the instance is recorded with its reason, has no database score
    # (there is nothing to score against an expectation), and the loop goes on to the next page.
    from agent_worker.eval import graph_eval

    page_a = page(tmp_path, "a", [("2026-10-20", "Nona"), ("2026-10-21", "Lent")], D(2026, 10, 12))
    monkeypatch.setattr(graph_eval, "PAGE_LABELS", {"a.html": page_a.label})
    monkeypatch.setattr(graph_eval.run_eval, "FIXTURES_DIR", tmp_path)
    monkeypatch.setattr(graph_eval, "VENUE_FACTS", {"test_venue": LabelVenueFacts("The Test Venue", "https://example.test/calendar")})
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [split_answer(("Nona", ["Nona"]))]}))
    out = await graph_eval.run_scenarios(Scenario.PERTURBED, ["a.html"], factory=factory, policy=None)
    assert out[0]["database_score"] is None
    assert out[0]["result"]["not_run"] is not None
