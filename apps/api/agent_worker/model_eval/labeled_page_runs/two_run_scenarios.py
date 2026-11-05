"""The two-run database scenarios and what the database should hold after them (the "committed" half of the C5 harness).

What this is: a page run through the graph ends with rows in Postgres. This module runs the two-run SCENARIOS the plan asks for,
states what the database SHOULD hold after each (`expected_rows`, C5-K3), and scores the rows actually left against that
(`score_database`). Reading and clearing those rows is `scratch_calendar_rows.py` (the helpers here call it); the runners that drive many
pages are `run_labeled_pages.py`.

How to read it, top to bottom:
1. `Scenario` and `run_scenario`: repeat (the same page twice), sequence (two captures of one venue), overlap (a second capture
   that repeats the first's dates, minus a show), perturbed (the database is damaged between two runs of one page). What each
   proves is in `run_scenario`'s docstring.
2. `expected_rows` (C5-K3) and `score_database`: what a perfect pipeline would leave, and the score of the actual rows against it.
   They stay in this file beside the scenarios on purpose: `_perturb`'s three damages and `_expected_counts`' "one insert, one
   update, one remove" are two halves of one rule, and change together.

docs/dev/implementations/c5-pipeline-eval-harness.md, Step 5 (C5-D2, C5-D6, C5-PR1-3, C5-PR1-4, C5-PR1-5).
"""

import datetime
import shutil
import tempfile
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.context import WorkerContext
from agent_worker.main import VenueFacts
from agent_worker.model_eval import scoring
from agent_worker.model_eval.labeled_page_runs import scratch_calendar_rows
from agent_worker.model_eval.labeled_page_runs.run_one_page import PageRun, run_page
from agent_worker.model_eval.labels import LabelledShow, PageLabel
from agent_worker.policy import RetryPolicy
from app.db.models import Show, ShowArtist
from app.enums import ShowStatus

# ---------------------------------------------------------------------------
# 1. The scenarios
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
    model_changed: bool = False  # the model read the page differently on run 2, so its counts are not a reconcile check


# A start time no listing uses, so the stale row can't be mistaken for a listed show.
_STALE_TIME = datetime.time(3, 33)


async def _perturb(factory: async_sessionmaker[AsyncSession], venue_id: int) -> dict[str, Any]:
    """Damage the venue's rows the way a stale or hand-edited database would be, in three independent ways.

    1. The first row with a start time gets that time set to NULL: the next run sees "a time that appears later", an UPDATE.
       (Changing a non-null time would be a remove plus an insert, A5-D3, and never measure an update.)
    2. The last other row is deleted, its lineup first (foreign key): the next run must INSERT it again.
    3. A stale row is added inside the window with no lineup: the next run must REMOVE it (soft delete). It goes on the latest date
       the model actually listed (taken from the stored rows, not the label): reconcile never removes a row on a date where a
       listing was left out, so a date the model skipped would make the stale row survive for a reason that is not a fault.
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
        stale = Show(venue_id=venue_id, date=max(s.date for s in rows), start_time=_STALE_TIME, status=ShowStatus.ACTIVE, original_url="stale")
        session.add(stale)
        await session.flush()
        details["stale"] = stale.id
        await session.commit()
    return details


def _kept(counts: dict[str, int]) -> int:
    """The listings a run kept: those it inserted, updated or left alone (not the removals, and not the skipped cancellations)."""
    return counts["insert"] + counts["update"] + counts["no_op"]


def _expected_counts(scenario: Scenario, first_run: dict[str, int]) -> dict[str, int] | None:
    """What reconcile should decide on the SECOND run IF the model reads the page as it did the first time (None where the
    scenario implies nothing).

    Built from what run 1 actually extracted, not from the label: on an empty database every kept listing of run 1 is an insert,
    so its insert count is how many shows the model found. The label says how many it SHOULD have found, which is the database
    score's question; reconcile's question is only whether it is stable given what it was handed. A repeat: every listing is a
    no-op. A perturbed run: one update, one insert (the deleted row), one remove (the stale row), the rest no-ops. In both, each
    cancelled or postponed listing with nothing stored is a skip.
    """
    found, skipped = first_run["insert"], first_run["skip"]
    if scenario is Scenario.REPEAT:
        return {"insert": 0, "update": 0, "no_op": found, "remove": 0, "skip": skipped}
    if scenario is Scenario.PERTURBED:
        return {"insert": 1, "update": 1, "no_op": found - 2, "remove": 1, "skip": skipped}
    return None


def _extracted_shows(run: PageRun) -> Any:
    """What the model said the page lists, as the run recorded it (None when the model produced nothing)."""
    return (run.raw or {}).get("shows")


def _compare_counts(
    scenario: Scenario, first: PageRun, second: PageRun,
) -> tuple[dict[str, int] | None, list[str], bool]:
    """`(expected counts, differences, whether the model changed its answer)` for a scenario's second run.

    Reconcile is held to the counts below only when the model gave the same shows both times. If it did not, run 2's counts
    differ for a reason that is the model's, and listing them as mismatches would read like reconcile faults, so the one
    difference reported says the extraction changed.

    "The model gave the same shows" is decided by comparing the two extractions' shows, NOT by counting them: a model that keeps
    three shows but names one act differently has changed its answer, and reconcile rightly updates that show (Ari's review of
    PR 78). Whether a model repeats itself is a measurement, not an assumption: the local model did not at temperature 0 (White
    Squirrel's October page gave 10, 11, 10, 10 and 11 shows in five extractions); a hosted model is unmeasured, and a model that
    does repeat is simply held to the counts every time."""
    if scenario not in (Scenario.REPEAT, Scenario.PERTURBED):
        return None, [], False
    first_run, second_run = first.reconcile_counts, second.reconcile_counts
    if first_run is None or second_run is None:
        return None, ["a run reached no reconcile decision"], False
    expected = _expected_counts(scenario, first_run)
    assert expected is not None
    if _extracted_shows(first) != _extracted_shows(second):
        if _kept(second_run) != first_run["insert"] or second_run["skip"] != first_run["skip"]:
            what = (
                f"the model extracted {first_run['insert']} shows on run 1 and {_kept(second_run)} on run 2 "
                f"(skipped {first_run['skip']} then {second_run['skip']})"
            )
        else:
            what = f"the model extracted {first_run['insert']} shows both times, but not the same ones (an act or a field differs)"
        return expected, [f"{what}, so run 2's counts reflect a changed extraction, not reconcile"], True
    return expected, [f"{action}: expected {want}, got {second_run.get(action)}" for action, want in expected.items() if second_run.get(action) != want], False


async def run_scenario(
    scenario: Scenario, *, first: ScenarioPage, second: ScenarioPage | None, venue: VenueFacts, ctx: WorkerContext,
    factory: async_sessionmaker[AsyncSession], policy: RetryPolicy | None = None,
) -> ScenarioResult:
    """Run a scenario's two graph runs on one venue, with no reset between them.

    repeat: `first` twice. sequence / overlap: `first`, then `second`. perturbed: `first`, damage the database, `first` again.
    """
    async def committed() -> dict[str, Any]:
        return await scratch_calendar_rows.committed_extraction(factory, venue.id)

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
                try:
                    perturbation = await _perturb(factory, venue.id)
                except ScenarioNotRunnable as err:
                    return ScenarioResult(scenario.value, runs, None, [], None, not_run=str(err))
            runs.append(await run(first))

    expected, differences, model_changed = _compare_counts(scenario, runs[0], runs[1])
    return ScenarioResult(scenario.value, runs, expected, differences, perturbation, model_changed=model_changed)


# ---------------------------------------------------------------------------
# 2. What the database should hold, and how it scored
# ---------------------------------------------------------------------------


def expected_rows(scenario: Scenario, first: PageLabel, second: PageLabel | None) -> list[LabelledShow]:
    """The shows a perfect pipeline would leave in the database after the scenario's second run (from the LABELS, never from
    running the pipeline)."""
    # What the database should hold after the second run is not "the second page's labels" (C5-K3). Reconcile soft-deletes only
    # inside the window the second fetch covered: from that fetch's date to the latest date the page evidences (A5-D1;
    # `reconcile.covered_window` and `removed_by_absence`). So after a SEQUENCE or OVERLAP the first page's shows outside that
    # window survive, those inside it that the second page no longer lists are gone, and a show both pages list is one row, not
    # two. The window's end counts the dates of labelled non-shows too, because an excluded no-act listing extends what the page
    # evidences. After a PERTURBED run the stale row is gone and the rest equals the labels. A labelled cancelled or postponed
    # show is absent, since `ShowStatus` has no such value and reconcile skips it (A2.1-D12, `reconcile.Action.SKIP`), which is
    # what `scoring.scheduled_only` removes. Everything here comes from the LABELS, never from running the pipeline, so the
    # expectation cannot inherit a bug from the code it checks.
    first_live = scoring.scheduled_only(first).shows
    if scenario in (Scenario.SEQUENCE, Scenario.OVERLAP) and second is not None:
        dates = [s.date for s in second.shows] + [n.date for n in second.non_shows if n.date]
        start, end = second.captured_on, max(dates)
        survivors = [s for s in first_live if not start <= s.date <= end]
        return [*survivors, *scoring.scheduled_only(second).shows]
    return list(first_live)        # REPEAT and PERTURBED: the one page's live shows


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
    # The database holds rows from several pages, so there is no single page to check an image link against, and scoring them
    # against an empty page would call every stored link invented. Links are checked per run, on the page each came from
    # (`PageRun.committed_score`); this score is about which shows and acts are left, so the links are set aside.
    no_links = {**rows, "shows": [{**show, "image_url": None} for show in rows["shows"]]}
    return asdict(scoring.score_page(expected, no_links, "", f"database:{scenario.value}"))
