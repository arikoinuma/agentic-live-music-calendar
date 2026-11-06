"""The graph-level evaluation harness's runner and command line: run labelled pages through the real pipeline and store the result.

What this is: C5's counterpart to `run_eval.py`. `run_eval` asks whether the MODEL can read a page (it calls `extract_page`
only). This asks whether the PIPELINE puts correct data in the calendar: it runs each labelled page through the compiled graph
(`run_one_page.run_page`: fetch, extract, validate, retry, reconcile, commit) against a scratch Postgres database, and scores the
model's raw answer, the validated extraction and the rows left behind with the same scorer and the same labels (`scoring.py`).
With `--scenario` it runs the two-run database scenarios (`two_run_scenarios.py`). It needs the local model and the gitignored fixtures, so
it is not part of `make check`.

    make eval-graph LABEL=c5-baseline SET=all
    make eval-graph LABEL=c5-seq SCENARIO=sequence
    make eval-graph LABEL=c5-retry THRESHOLD=0.99          # provoke the retry loop (model-route and image pages only)
    uv run python -m agent_worker.model_eval.labeled_page_runs --rescore c5-baseline
    uv run python -m agent_worker.model_eval.labeled_page_runs --compare c5-baseline c5-retry

Where the rest lives (this file is only the part that RUNS things): `aggregate_scores` (the numbers computed from the run
records), `results_file` (the results file: its shape, its paths, loading and the committable snapshot), `markdown_report` (Markdown
report, comparison table and closing summary), `scratch_calendar_rows` (reading and clearing the scratch calendar), `two_run_scenarios` (scenarios
and what they should leave), `run_one_page` (one page through the graph).

How to read it, top to bottom: the flag helpers (`build_policy`, `scenario_pairs`, `scenario_records`); `rescore`, which recomputes
a saved run's scores with no model and no database; the runners (`run_pages`, `run_scenarios`), which print progress as they go
because a run takes an hour; then `evaluate`, which wires them to the command line, and `main`, which dispatches the subcommands.
The results file (`model_eval/results/graph-<label>.json`, gitignored) keeps every raw extraction, finding and staged document, so any
score can be recomputed without a model (`--rescore`).

docs/dev/implementations/c5-pipeline-eval-harness.md, Steps 3, 5 and 6 (C5-D1 to C5-D7); split into the modules above in code
review round 2 (C5-CR2-1 to C5-CR2-6).
"""

import argparse
import asyncio
import dataclasses
import datetime
import itertools
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.audit import PostgresAuditWriter
from agent_worker.calendar_reader import PostgresCalendarReader
from agent_worker.calendar_writer import PostgresCalendarWriter
from agent_worker.context import WorkerContext
from agent_worker.extraction import PIPELINE_ROLES
from agent_worker.main import model_endpoint_problem
from agent_worker.model_eval import run_eval
from agent_worker.model_eval.labeled_page_runs import (
    scratch_calendar_rows,
    scratch_database,
    two_run_scenarios,
)
from agent_worker.model_eval.labeled_page_runs.run_one_page import (
    InMemoryStager,
    PageRun,
    column_scores,
    run_page,
    score_dict,
)
from agent_worker.model_eval.labels import PAGE_LABELS, VENUE_FACTS, PageLabel
from agent_worker.model_eval.labels import VenueFacts as LabelVenueFacts
from agent_worker.model_eval.saved_run_reports import (
    aggregate_scores,
    markdown_report,
    results_file,
)
from agent_worker.nodes import IMAGE_SUFFIXES
from agent_worker.policy import DEFAULT_POLICY, RetryPolicy
from app.config import settings

SCENARIO_CHOICES = tuple(s.value for s in two_run_scenarios.Scenario)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def build_policy(threshold: float | None, max_attempts: int | None) -> RetryPolicy | None:
    """The policy the flags ask for, built on the DEFAULT policy so the configured escalation model is kept (a fresh
    `RetryPolicy(...)` would drop it); None when no flag was given, so the run uses the default (C5-D5)."""
    if threshold is None and max_attempts is None:
        return None
    changes: dict[str, Any] = {}
    if threshold is not None:
        changes["confidence_threshold"] = threshold
    if max_attempts is not None:
        changes["max_attempts"] = max_attempts
    return dataclasses.replace(DEFAULT_POLICY, **changes)


def scenario_pairs(names: list[str]) -> list[tuple[str, str]]:
    """Consecutive captures of one venue, oldest first: the pairs the sequence and overlap scenarios run.

    Only labelled text pages count (a poster image is not a capture of the calendar page), and only a strictly later capture
    pairs with an earlier one, so two files saved the same day are never a sequence."""
    by_venue: dict[str, list[tuple[datetime.date, str]]] = {}
    for name in names:
        label = PAGE_LABELS.get(name)
        if label is None or name.lower().endswith(IMAGE_SUFFIXES):
            continue
        by_venue.setdefault(label.venue, []).append((label.captured_on, name))
    pairs = []
    for captures in by_venue.values():
        captures.sort()
        pairs += [(a, b) for (da, a), (db, b) in itertools.pairwise(captures) if da < db]
    return pairs


def scenario_records(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The run records of a scenario run, flattened, each tagged with its scenario and whether its committed column is scored.

    The second run of a SEQUENCE or OVERLAP leaves another page's rows in the database, so its committed column is not scored
    against its own page's label (`aggregate_scores._scored_in`); the scenario's own database score covers it (C5-CR1-1)."""
    return [
        {
            **run,
            "run": i,
            "scenario": s["result"]["scenario"],
            "committed_scored": not (
                s["result"]["scenario"] in (two_run_scenarios.Scenario.SEQUENCE, two_run_scenarios.Scenario.OVERLAP)
                and i == 1
            ),
        }
        for s in scenarios
        for i, run in enumerate(s["result"]["runs"])
    ]


# ---------------------------------------------------------------------------
# Rescore (no model, no database)
# ---------------------------------------------------------------------------


def rescore(label: str) -> Path:
    """Recompute a saved run's scores from its stored extractions, into a NEW file; the original stays byte-identical.

    The model output (`raw`, `validated`, `committed`, and each staged document's `raw_extraction`) is the raw data and doesn't
    change, so a corrected label or a fixed scorer can be applied without a model call (A2.1-PR1-13, the rule `run_eval`
    follows). Needs the fixtures only to check image links against the page.
    """
    data = json.loads(results_file.results_path(label).read_text())
    for run in data["runs"]:
        _rescore_run(run)
    # The scenario block holds its own copy of each run and a database score; both are recomputed, or a corrected label would
    # reach the top-level numbers and leave these contradicting them (C5-CR1-3). The database score is rebuilt from the last
    # run's stored rows, which are the rows the scenario ended with.
    for entry in data.get("scenarios", []):
        for run in entry["result"]["runs"]:
            _rescore_run(run)
        if entry["result"].get("not_run") is None and entry["database_score"] is not None:
            first_name, *rest = entry["pages"]
            if first_name in PAGE_LABELS and all(n in PAGE_LABELS for n in rest):
                entry["database_score"] = two_run_scenarios.score_database(
                    two_run_scenarios.Scenario(entry["result"]["scenario"]),
                    PAGE_LABELS[first_name],
                    PAGE_LABELS[rest[0]] if rest else None,
                    entry["result"]["runs"][-1]["committed"],
                )
    data["aggregate"] = aggregate_scores.aggregate(data["runs"], PAGE_LABELS)
    data["rescored_from"] = label
    data["labels_sha"] = results_file.labels_sha()
    return results_file.write_results(results_file.rescore_path(label), data)


def _rescore_run(run: dict[str, Any]) -> None:
    """Recompute one run record's scores (raw, validated, committed, and each attempt's) from its stored extractions.

    Uses `run_one_page`'s own scoring functions, so a rescore applies exactly the column rules a fresh run does."""
    page_label = PAGE_LABELS.get(run["fixture"])
    if page_label is None:
        return
    fixture = run_eval.CAPTURED_PAGES_DIR / run["fixture"]
    page_html = fixture.read_text() if fixture.suffix not in IMAGE_SUFFIXES and fixture.is_file() else ""
    run.update(
        column_scores(
            page_label,
            raw=run["raw"],
            validated=run["validated"],
            committed=run["committed"],
            page_html=page_html,
            fixture=run["fixture"],
        )
    )
    documents = {d["attempt"]: d for d in run["staged_documents"]}
    for attempt in run["attempts"]:
        document = documents.get(attempt["attempt"])
        if document is not None and document["raw_extraction"] is not None:
            attempt["score"] = score_dict(page_label, document["raw_extraction"], page_html, run["fixture"])


# ---------------------------------------------------------------------------
# Runners (these need a database)
# ---------------------------------------------------------------------------


def _context(factory: async_sessionmaker[AsyncSession]) -> WorkerContext:
    """The real Postgres stores and the in-memory stager (C5-D2: MongoDB is not what is being evaluated)."""
    return WorkerContext(
        audit=PostgresAuditWriter(factory),
        stager=InMemoryStager(),
        reader=PostgresCalendarReader(factory),
        writer=PostgresCalendarWriter(factory),
    )


async def run_pages(
    items: list[tuple[Path, PageLabel, LabelVenueFacts]],
    *,
    factory: async_sessionmaker[AsyncSession],
    runs: int,
    policy: RetryPolicy | None,
) -> list[dict[str, Any]]:
    """Run each page `runs` times, each on an empty calendar, and return the run records.

    The calendar is cleared before every run (`scratch_calendar_rows.reset`), so one page's artists cannot change how the next page's artists
    are matched and every page starts from the same empty state. Infrastructure errors propagate: a database that fails is not a
    result, unlike a model that does (the graph records those itself)."""
    records = []
    for fixture, label, facts in items:
        for run_index in range(runs):
            await scratch_calendar_rows.reset(factory)
            venue = await scratch_calendar_rows.ensure_venue(factory, facts)

            async def committed(venue_id: int = venue.id) -> dict[str, Any]:
                return await scratch_calendar_rows.committed_extraction(factory, venue_id)

            page_run: PageRun = await run_page(
                label=label,
                fixture=fixture,
                venue=venue,
                ctx=_context(factory),
                committed_rows=committed,
                policy=policy,
            )
            records.append({**asdict(page_run), "run": run_index})
            print(
                f"{fixture.name[:40]:40} | run {run_index} | attempts {page_run.attempt_count} | "
                f"escalated {page_run.escalated} | {page_run.seconds}s",
                flush=True,
            )
    return records


async def run_scenarios(
    scenario: two_run_scenarios.Scenario,
    names: list[str],
    *,
    factory: async_sessionmaker[AsyncSession],
    policy: RetryPolicy | None,
) -> list[dict[str, Any]]:
    """Run `scenario` over the selected captures: one page each (repeat, perturbed) or each consecutive pair of one venue
    (sequence, overlap). Each instance starts from an empty calendar; its two runs do not reset between them."""
    if scenario in (two_run_scenarios.Scenario.SEQUENCE, two_run_scenarios.Scenario.OVERLAP):
        instances: list[tuple[str, str | None]] = [(a, b) for a, b in scenario_pairs(names)]
    else:
        instances = [(n, None) for n in names if n in PAGE_LABELS and not n.lower().endswith(IMAGE_SUFFIXES)]
    out = []
    for first_name, second_name in instances:
        await scratch_calendar_rows.reset(factory)
        first = two_run_scenarios.ScenarioPage(PAGE_LABELS[first_name], run_eval.CAPTURED_PAGES_DIR / first_name)
        second = (
            two_run_scenarios.ScenarioPage(PAGE_LABELS[second_name], run_eval.CAPTURED_PAGES_DIR / second_name)
            if second_name
            else None
        )
        venue = await scratch_calendar_rows.ensure_venue(factory, VENUE_FACTS[first.label.venue])
        result = await two_run_scenarios.run_scenario(
            scenario,
            first=first,
            second=second,
            venue=venue,
            ctx=_context(factory),
            factory=factory,
            policy=policy,
        )
        rows = await scratch_calendar_rows.committed_extraction(factory, venue.id)
        # A scenario whose first run left nothing to build on is reported with its reason and has no database score (C5-CR1-2).
        database: dict[str, Any] | None = (
            None
            if result.not_run
            else two_run_scenarios.score_database(scenario, first.label, second.label if second else None, rows)
        )
        out.append(
            {
                "pages": [first_name, *([second_name] if second_name else [])],
                "result": asdict(result),
                "database_score": database,
            }
        )
        note = f"NOT RUN: {result.not_run}" if result.not_run else f"differences {result.count_differences}"
        print(f"{scenario.value}: {first_name} {'-> ' + second_name if second_name else ''} | {note}")
        if database is not None:
            print(
                f"  database vs expected: labelled {database['labelled']}, returned {database['returned']}, "
                f"missed {database['missed']}, wrong acts {database['acts_wrong']}, invented {database['fabricated']}"
            )
    return out


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", help="name for this run; results go to model_eval/results/graph-<label>.json")
    parser.add_argument(
        "--set",
        choices=["gated", "informational", "held_out", "all"],
        default="all",
        help="which labelled pages to run; 'all' is gated + informational and never includes held_out (C5-D3)",
    )
    parser.add_argument("--only", help="only fixtures whose file name contains this text")
    parser.add_argument(
        "--runs", type=int, default=1, help="runs per page (default 1: at temperature 0 repeats are one sample)"
    )
    parser.add_argument(
        "--scenario", choices=SCENARIO_CHOICES, help="run a two-run database scenario instead of single pages"
    )
    parser.add_argument(
        "--threshold", type=float, help="the retry policy's confidence threshold (default: the pipeline's)"
    )
    parser.add_argument("--max-attempts", type=int, help="the retry policy's attempt cap (default: the pipeline's)")
    parser.add_argument(
        "--keep-db", action="store_true", help="leave the scratch database in place afterwards, to read the rows"
    )
    parser.add_argument(
        "--rescore", metavar="LABEL", help="rescore a saved run into graph-rescore-<LABEL>.json (no model)"
    )
    parser.add_argument("--compare", nargs="+", metavar="LABEL", help="print saved runs side by side")
    parser.add_argument(
        "--snapshot",
        metavar="LABEL",
        help="write a slim, committable summary of a saved run to docs/dev/eval-baselines/",
    )
    parser.add_argument(
        "--report", metavar="LABEL", help="print a readable Markdown report of a saved run (markdown_report.py)"
    )
    parser.add_argument("--errors", action="store_true", help="with --report: also list every error string in full")
    parser.add_argument(
        "--out", metavar="FILE", help="with --report: write the report to this file instead of printing it"
    )
    return parser.parse_args(argv)


async def evaluate(args: argparse.Namespace) -> int:
    """Create the scratch database, run the pages (or the scenario), write the results file, drop the database."""
    options, config = run_eval.configure({})
    policy = build_policy(args.threshold, args.max_attempts)
    fixtures = run_eval.select_fixtures(args.set, args.only)
    if not fixtures:
        print("no labelled fixtures to run (they are gitignored; capture them with model_eval/capture.py)")
        return 2
    names = [p.name for p in fixtures]
    started_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")

    url = scratch_database.eval_database_url(os.environ.get("EVAL_DATABASE_URL") or settings.database_url)
    scratch_database.check_eval_database_url(url)
    await scratch_database.create(url)
    await scratch_database.migrate(url)
    engine, factory = scratch_database.session_factory(url)
    try:
        records: list[dict[str, Any]] = []
        scenarios: list[dict[str, Any]] = []
        if args.scenario:
            scenarios = await run_scenarios(
                two_run_scenarios.Scenario(args.scenario), names, factory=factory, policy=policy
            )
            records = scenario_records(scenarios)
        else:
            items = [(p, PAGE_LABELS[p.name], VENUE_FACTS[PAGE_LABELS[p.name].venue]) for p in fixtures]
            records = await run_pages(items, factory=factory, runs=args.runs, policy=policy)
    finally:
        await engine.dispose()
        if not args.keep_db:
            await scratch_database.drop(url)

    try:
        # One entry per distinct model the pipeline's roles use (C6-D2), the page model first. A hosted provider makes
        # no request here (C6 Test 3); a local one that doesn't answer is noted, not fatal.
        roles = PIPELINE_ROLES
        provenance: dict[str, Any] | None = {
            m: run_eval.model_provenance(dataclasses.replace(options, model=m), settings.model_base_url)
            for m in dict.fromkeys([options.model, roles.splitter.model, roles.status.model, roles.matcher.model])
        }
    except (httpx.HTTPError, OSError):
        provenance = None
    summary = aggregate_scores.aggregate(records, PAGE_LABELS)
    record = results_file.build_record(
        label=args.label,
        started_at=started_at,
        set_name=args.set,
        scenario=args.scenario,
        fixture_names=names,
        page_labels=PAGE_LABELS,
        config=config,
        options=options,
        request=run_eval.request_record(config, False),
        policy=policy or DEFAULT_POLICY,
        provenance=provenance,
        aggregate=summary,
        scenarios=scenarios,
        runs=records,
    )
    out_path = results_file.write_results(results_file.results_path(args.label), record)
    print(f"\nwrote {out_path}")
    print(markdown_report.summary(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.compare:
        print(markdown_report.compare_table({name: results_file.load_results(name) for name in args.compare}))
        return 0
    if args.snapshot:
        print(f"wrote {results_file.snapshot(args.snapshot)}")
        return 0
    if args.report:
        text = markdown_report.render(results_file.load_results(args.report), PAGE_LABELS, show_errors=args.errors)
        if args.out:
            Path(args.out).write_text(text)
            print(f"wrote {args.out}")
        else:
            print(text)
        return 0
    if args.rescore:
        print(f"wrote {rescore(args.rescore)}")
        return 0
    if not args.label:
        print("--label is required unless --compare or --rescore is given", file=sys.stderr)
        return 2
    # The worker's start-up rule applies here too: no endpoint, or a hosted one with the placeholder key, would
    # otherwise build the scratch database and then fail every page on a connection error or a 401.
    options, _ = run_eval.configure({})
    problem = model_endpoint_problem(
        settings.app_env, options.provider, settings.model_base_url, settings.model_api_key.get_secret_value()
    )
    if problem:
        print(problem, file=sys.stderr)
        return 2
    return asyncio.run(evaluate(args))


if __name__ == "__main__":
    sys.exit(main())
