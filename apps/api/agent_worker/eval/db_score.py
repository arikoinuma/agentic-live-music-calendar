"""Score the database a graph run leaves behind: the rows, the scenarios that produce them, and what they should hold.

What this is: the "committed" half of the C5 harness. A page run through the graph ends with rows in Postgres; this module reads
them back as an extraction-shaped dict (so `scoring.score_page` scores them with the same tiers as the model's answer), runs the
two-run SCENARIOS the plan asks for, and states what the database SHOULD hold after each (`expected_rows`, C5-K3).

How to read it, top to bottom:
1. `committed_extraction`, `reset`, `ensure_venue`: reading the rows, clearing between independent pages, and the venue rows the
   harness needs (it runs in its own database, `scratch_db.py`).
2. `Scenario` and `run_scenario`: repeat (the same page twice), sequence (two captures of one venue), overlap (a second capture
   that repeats the first's dates, minus a show), perturbed (the database is damaged between two runs of one page). What each
   proves is in `run_scenario`'s docstring.
3. `expected_rows` (C5-K3) and `score_database`: what a perfect pipeline would leave, and the score of the actual rows against it.

docs/dev/implementations/c5-pipeline-eval-harness.md, Step 5 (C5-D2, C5-D6, C5-PR1-3, C5-PR1-4, C5-PR1-5).
"""

import datetime
import shutil
import tempfile
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.context import WorkerContext
from agent_worker.eval import scoring
from agent_worker.eval.graph_run import PageRun, run_page
from agent_worker.eval.labels import LabelledShow, PageLabel
from agent_worker.eval.labels import VenueFacts as LabelVenueFacts
from agent_worker.main import VenueFacts, load_venues
from agent_worker.policy import RetryPolicy
from app.db.models import Artist, Metro, Show, ShowArtist, Venue
from app.db.seed import METRO_NAME, METRO_TIMEZONE
from app.enums import FetchStrategy, ShowStatus

# ---------------------------------------------------------------------------
# 1. Reading and clearing the rows
# ---------------------------------------------------------------------------


async def committed_extraction(factory: async_sessionmaker[AsyncSession], venue_id: int) -> dict[str, Any]:
    """The venue's ACTIVE shows as an extraction-shaped dict, so `score_page` scores the rows unchanged.

    A removed show is not "left" (soft delete). Acts are in `sequence_number` order, as the reader's lineup query orders them.
    Dates and times are ISO text and prices are floats, so the dict is JSON-serialisable (a `Decimal` would not be) and a
    --rescore reads the same shape from a stored file (C5-PR1-12). The status is `scheduled`: the database cannot hold a
    cancelled show, which is why the committed column is scored against `scoring.scheduled_only` (C5-PR1-5).
    """
    async with factory() as session:
        shows = (
            await session.execute(
                select(Show).where(Show.venue_id == venue_id, Show.status == ShowStatus.ACTIVE).order_by(Show.date, Show.start_time, Show.id)
            )
        ).scalars().all()
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
    them. This is the one destructive statement the harness runs, and `scratch_db` has already proved the database is the scratch
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
            metro = Metro(name=METRO_NAME, timezone=METRO_TIMEZONE)
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


# ---------------------------------------------------------------------------
# 2. The scenarios
# ---------------------------------------------------------------------------


class Scenario(StrEnum):
    REPEAT = "repeat"  # the same page twice: the second run should change nothing
    SEQUENCE = "sequence"  # two captures of one venue: the second's window must not touch the first's rows
    OVERLAP = "overlap"  # a second capture repeating the first's dates, minus a show: only that show is removed
    PERTURBED = "perturbed"  # one page, with the database damaged in between: the second run repairs it


class ScenarioNotRunnable(ValueError):
    """The first run left the database in a state the scenario cannot build on (it escalated and committed nothing). That is an
    outcome of the model, not an infrastructure failure: the scenario is reported as not run (C5-CR1-2)."""


@dataclass(frozen=True)
class ScenarioPage:
    """A page to run: its label (hand-written truth) and the fixture file to feed the graph."""

    label: PageLabel
    fixture: Path


@dataclass
class ScenarioResult:
    """What a scenario did. `count_differences` is where reconcile's decisions on the second run departed from what the
    scenario implies; it is reported, never asserted by the harness (the tests assert it with a scripted model)."""

    scenario: str
    runs: list[PageRun]
    expected_counts: dict[str, int] | None
    count_differences: list[str]
    perturbation: dict[str, Any] | None
    not_run: str | None = None  # why the second run did not happen (C5-CR1-2); `runs` then holds the first run only


# A start time no listing uses, so the stale row can't be mistaken for a listed show.
_STALE_TIME = datetime.time(3, 33)


async def _perturb(factory: async_sessionmaker[AsyncSession], venue_id: int, last_date: datetime.date) -> dict[str, Any]:
    """Damage the venue's rows the way a stale or hand-edited database would be, in three independent ways.

    1. The first row with a start time gets that time set to NULL: the next run sees "a time that appears later", an UPDATE.
       (Changing a non-null time would be a remove plus an insert, A5-D3, and never measure an update.)
    2. The last other row is deleted, its lineup first (foreign key): the next run must INSERT it again.
    3. A stale row is added inside the window with no lineup: the next run must REMOVE it (soft delete).
    """
    async with factory() as session:
        rows = (
            await session.execute(
                select(Show).where(Show.venue_id == venue_id, Show.status == ShowStatus.ACTIVE).order_by(Show.date, Show.start_time, Show.id)
            )
        ).scalars().all()
        timed = next((s for s in rows if s.start_time is not None), None)
        others = [s for s in rows if timed is None or s.id != timed.id]
        if timed is None or not others:
            raise ScenarioNotRunnable("the perturbed scenario needs at least two active shows, one with a start time")
        victim = others[-1]
        details = {"time_nulled": timed.id, "deleted": victim.id}
        await session.execute(update(Show).where(Show.id == timed.id).values(start_time=None))
        await session.execute(delete(ShowArtist).where(ShowArtist.show_id == victim.id))
        await session.execute(delete(Show).where(Show.id == victim.id))
        stale = Show(venue_id=venue_id, date=last_date, start_time=_STALE_TIME, status=ShowStatus.ACTIVE, original_url="stale")
        session.add(stale)
        await session.flush()
        details["stale"] = stale.id
        await session.commit()
    return details


def _expected_counts(scenario: Scenario, label: PageLabel) -> dict[str, int] | None:
    """What reconcile should decide on the SECOND run, where the scenario implies it (None otherwise).

    A repeat: every live listing is a no-op. A perturbed run: one update, one insert, one remove, the rest no-ops. In both, each
    cancelled or postponed listing with nothing stored is a skip."""
    live = len(scoring.scheduled_only(label).shows)
    skipped = len(label.shows) - live
    if scenario is Scenario.REPEAT:
        return {"insert": 0, "update": 0, "no_op": live, "remove": 0, "skip": skipped}
    if scenario is Scenario.PERTURBED:
        return {"insert": 1, "update": 1, "no_op": live - 2, "remove": 1, "skip": skipped}
    return None


async def run_scenario(
    scenario: Scenario, *, first: ScenarioPage, second: ScenarioPage | None, venue: VenueFacts, ctx: WorkerContext,
    factory: async_sessionmaker[AsyncSession], policy: RetryPolicy | None = None,
) -> ScenarioResult:
    """Run a scenario's two graph runs on one venue, with no reset between them.

    repeat: `first` twice. sequence / overlap: `first`, then `second`. perturbed: `first`, damage the database, `first` again.
    """
    async def committed() -> dict[str, Any]:
        return await committed_extraction(factory, venue.id)

    # Every capture of a venue comes from ONE calendar URL, and the pipeline stores that URL on each show (`original_url`);
    # reconcile treats a changed `original_url` as an update. The harness feeds a fixture's path as that URL, so two capture
    # files would make every show they share look updated. Each run therefore reads its page from the same fixed path, copied in
    # just before it runs (the record still carries the capture's own name).
    with tempfile.TemporaryDirectory() as workdir:
        async def run(page: ScenarioPage) -> PageRun:
            staged = Path(workdir) / f"page{page.fixture.suffix}"
            shutil.copyfile(page.fixture, staged)
            return await run_page(
                label=page.label, fixture=staged, venue=venue, ctx=ctx, committed_rows=committed, policy=policy,
                name=page.fixture.name,
            )

        runs = [await run(first)]
        perturbation = None
        if scenario in (Scenario.SEQUENCE, Scenario.OVERLAP):
            if second is None:
                raise ValueError(f"the {scenario.value} scenario needs a second page")
            runs.append(await run(second))
        else:
            if scenario is Scenario.PERTURBED:
                last = max(s.date for s in first.label.shows)
                try:
                    perturbation = await _perturb(factory, venue.id, last)
                except ScenarioNotRunnable as err:
                    return ScenarioResult(scenario.value, runs, None, [], None, not_run=str(err))
            runs.append(await run(first))

    expected = _expected_counts(scenario, first.label)
    actual = runs[1].reconcile_counts
    differences = (
        [f"{action}: expected {want}, got {actual.get(action)}" for action, want in expected.items() if actual.get(action) != want]
        if expected is not None and actual is not None else (["the second run reached no reconcile decision"] if expected is not None else [])
    )
    return ScenarioResult(scenario.value, runs, expected, differences, perturbation)


# ---------------------------------------------------------------------------
# 3. What the database should hold, and how it scored
# ---------------------------------------------------------------------------


def expected_rows(scenario: Scenario, first: PageLabel, second: PageLabel | None) -> list[LabelledShow]:
    """The shows a perfect pipeline would leave in the database after the scenario's second run (from the LABELS, never from
    running the pipeline)."""
    # TODO(Ari) — Key point of interest (C5-K3): what should the database hold after the second run?
    #   Not "the second page's labels". Reconcile soft-deletes only inside the window the second fetch covered: from that
    #   fetch's date to the latest date the page evidences (A5-D1; reconcile.covered_window and removed_by_absence). So after
    #   a SEQUENCE the first page's shows OUTSIDE that window must SURVIVE, those INSIDE it that the second page no longer
    #   lists are gone, and a show both pages list is ONE row, not two. The window's end includes the dates of labelled
    #   non-shows, because an excluded no-act listing extends what the page evidences. After a PERTURBED run the stale row is
    #   gone and the rest equals the labels. A labelled cancelled or postponed show is ABSENT (ShowStatus has no such value and
    #   reconcile skips it, A2.1-D12 + reconcile.Action.SKIP): `scoring.scheduled_only`. The expected rows are what a perfect
    #   pipeline would leave, and they come from the LABELS, never from running the pipeline.
    # To align: copy the Code lines by hand, then run the Check.
    # Code:
    #   first_live = scoring.scheduled_only(first).shows
    #   if scenario in (Scenario.SEQUENCE, Scenario.OVERLAP) and second is not None:
    #       dates = [s.date for s in second.shows] + [n.date for n in second.non_shows if n.date]
    #       start, end = second.captured_on, max(dates)
    #       survivors = [s for s in first_live if not start <= s.date <= end]
    #       return [*survivors, *scoring.scheduled_only(second).shows]
    #   return list(first_live)        # REPEAT and PERTURBED: the one page's live shows
    # Check: uv run pytest agent_worker/tests/test_db_score.py -k expected_rows — the likeliest mistakes are returning only the
    #   second page's shows for a sequence (that scores the first page's surviving rows as invented shows), concatenating both
    #   pages (a show on both is listed twice), or leaving cancelled shows in the list.
    raise NotImplementedError("TODO(Ari)")


def score_database(
    scenario: Scenario, first: PageLabel, second: PageLabel | None, rows: dict[str, Any],
) -> dict[str, Any]:
    """The final rows scored against `expected_rows`, with the same scorer and tiers as the extraction (as `asdict(PageScore)`).

    The expected shows become a label of their own (the first page's venue and capture date, both pages' non-show entries, so a
    stray row that looks like a listed non-show is still a tolerated leak and not an invented show)."""
    expected = replace(
        first, shows=tuple(expected_rows(scenario, first, second)),
        non_shows=first.non_shows + (second.non_shows if second is not None else ()),
    )
    return asdict(scoring.score_page(expected, rows, "", f"database:{scenario.value}"))
