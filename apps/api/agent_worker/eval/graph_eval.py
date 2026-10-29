"""The graph-level evaluation harness: run labelled pages through the real pipeline and report what it got right.

What this is: C5's counterpart to `run_eval.py`. `run_eval` asks whether the MODEL can read a page (it calls `extract_page`
only). This asks whether the PIPELINE puts correct data in the calendar: it runs each labelled page through the compiled graph
(`graph_run.run_page`: fetch, extract, validate, retry, reconcile, commit) against a scratch Postgres database, and scores the
model's raw answer, the validated extraction and the rows left behind with the same scorer and the same labels (`scoring.py`).
It reports precision and recall on shows found, field accuracy, the retry loop, validation recall, and (with `--scenario`) what
the database holds after two runs. It needs the local model and the gitignored fixtures, so it is not part of `make check`.

    make eval-graph LABEL=c5-baseline SET=all
    make eval-graph LABEL=c5-seq SCENARIO=sequence
    make eval-graph LABEL=c5-retry THRESHOLD=0.99          # provoke the retry loop (model-route and image pages only)
    uv run python -m agent_worker.eval.graph_eval --rescore c5-baseline
    uv run python -m agent_worker.eval.graph_eval --compare c5-baseline c5-retry

How to read it, top to bottom: the pure parts (`aggregate` and the helpers it uses, `build_policy`, `scenario_pairs`, `rescore`,
`compare`) are first and are what the tests cover; then the runners (`run_pages`, `run_scenarios`) that need a database; then
`evaluate`, which wires them to the command line. The results file (`eval/results/graph-<label>.json`, gitignored) keeps every
raw extraction, finding and staged document, so any score can be recomputed without a model (`--rescore`).

docs/dev/implementations/c5-pipeline-eval-harness.md, Steps 3, 5 and 6 (C5-D1 to C5-D7).
"""

import argparse
import asyncio
import dataclasses
import datetime
import hashlib
import itertools
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.audit import PostgresAuditWriter
from agent_worker.calendar_reader import PostgresCalendarReader
from agent_worker.calendar_writer import PostgresCalendarWriter
from agent_worker.context import WorkerContext
from agent_worker.eval import db_score, run_eval, scoring, scratch_db, validation_recall
from agent_worker.eval.graph_run import NOTHING, InMemoryStager, PageRun, run_page
from agent_worker.eval.labels import PAGE_LABELS, VENUE_FACTS, PageLabel
from agent_worker.eval.labels import VenueFacts as LabelVenueFacts
from agent_worker.policy import DEFAULT_POLICY, RetryPolicy
from app.config import settings

RESULTS_DIR = run_eval.RESULTS_DIR
LABELS_FILE = Path(run_eval.__file__).parent / "labels.py"
COLUMNS = ("raw", "validated", "committed")
SCENARIO_CHOICES = tuple(s.value for s in db_score.Scenario)
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def labels_sha(path: Path = LABELS_FILE) -> str:
    """The SHA-256 of the label file, so a results file names the exact labels that scored it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def held_out_scored(fixtures: list[str], labels: Mapping[str, PageLabel]) -> bool:
    """Whether any held-out page was scored in this run. The first such scoring is C6's, so the file says so outright (C5-D3)."""
    return any(labels[name].held_out for name in fixtures if name in labels)


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


def _score_dict(label: PageLabel, extraction_dump: dict[str, Any] | None, page_html: str, fixture: str) -> dict[str, Any]:
    """`score_page` as a plain dict; a missing extraction is scored as nothing returned (every labelled show missed)."""
    return asdict(scoring.score_page(label, extraction_dump or NOTHING, page_html, fixture))


# ---------------------------------------------------------------------------
# The aggregate
# ---------------------------------------------------------------------------


def _summed(scores: list[scoring.PageScore]) -> scoring.PageScore:
    """One score holding the sum of the counts and field tallies of many pages: rates are divided ONCE from this, never averaged
    per page (a 5-show page must not weigh as much as a 10-show one; C5-M2)."""
    total = scoring.PageScore()
    for name in ("labelled", "returned", "dropped_empty", "missed", "acts_wrong", "fabricated", "leaks", "unsplit", "order_differs"):
        setattr(total, name, sum(getattr(s, name) for s in scores))
    for field_name, tally in total.fields.items():
        for s in scores:
            theirs = s.fields[field_name]
            tally.stated += theirs.stated
            tally.correct += theirs.correct
            tally.missing += theirs.missing
            tally.wrong += theirs.wrong
    return total


def _column(scores: list[scoring.PageScore]) -> dict[str, Any]:
    """The counts, headline rates and field accuracy of one column (raw, validated or committed) over all runs."""
    total = _summed(scores)
    rates = scoring.headline_rates(total)
    return {
        **{k: getattr(total, k) for k in ("labelled", "returned", "dropped_empty", "missed", "acts_wrong", "fabricated", "leaks")},
        "found": rates.found,
        "rates": asdict(rates),
        "fields": {
            name: {**asdict(t), "missing_rate": round(t.missing / t.stated, 3) if t.stated else None}
            for name, t in total.fields.items()
        },
    }


def _scored_in(records: list[dict[str, Any]], column: str) -> list[dict[str, Any]]:
    """The runs a column is scored over. The committed column leaves out a run flagged `committed_scored: False`: the second run
    of a SEQUENCE or OVERLAP scenario, whose rows include an earlier page's shows (correctly), which scored against the second
    page's label alone would all be invented shows. The scenario's own `database_score` is the right measure for those (C5-CR1-1)."""
    if column != "committed":
        return records
    return [r for r in records if r.get("committed_scored", True)]


def _gate(records: list[dict[str, Any]], labels: Mapping[str, PageLabel], column: str) -> dict[str, Any]:
    """Ari's standard (`scoring.gate`) over the GATED pages of one column, every run counted (A2.1-D1: every run must pass)."""
    by_run: dict[int, list[scoring.PageScore | scoring.PageFailure]] = {}
    for r in _scored_in(records, column):
        label = labels.get(r["fixture"])
        if label is None or not label.gated:
            continue
        score = scoring.PageScore.from_dict(r[f"{column}_score"])
        score.route = r.get("source") or "model"
        by_run.setdefault(r["run"], []).append(score)
    result = scoring.gate(by_run)
    return {"passed": result.passed, "failures": result.failures, "pages": result.pages}


def _errors_of(score: dict[str, Any] | None) -> int:
    """The errors in one attempt's score that retrying could fix: missed, wrong acts and invented shows."""
    return 0 if score is None else score["missed"] + score["acts_wrong"] + score["fabricated"]


def _retry(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The retry loop over all runs: how often it fired, what it did, and (for runs that retried) what it changed."""
    n = len(records)
    retried = [r for r in records if r["retried"]]
    return {
        "runs": n,
        "retried": len(retried),
        "retry_rate": len(retried) / n if n else 0.0,
        "mean_attempts": sum(r["attempt_count"] for r in records) / n if n else 0.0,
        "escalated": sum(r["escalated"] for r in records),
        "recovered": sum(r["recovered"] for r in records),
        "attempts_by_tier": dict(Counter(a["tier"] for r in records for a in r["attempts"])),
        "reasons": dict(Counter(reason for r in records for a in r["attempts"] for reason in a["reasons"])),
        # C5-D7: for the runs that retried, the errors of attempt 1 against the errors of the last attempt.
        "errors_first_attempt": sum(_errors_of(r["attempts"][0]["score"]) for r in retried if r["attempts"]),
        "errors_final_attempt": sum(_errors_of(r["attempts"][-1]["score"]) for r in retried if r["attempts"]),
    }


def _validation(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Validation recall over EVERY attempt (C5-D7): each attempt's errors joined to that attempt's own findings."""
    pairs = []
    fired: Counter[str] = Counter()
    disagree = 0
    for r in records:
        for a in r["attempts"]:
            findings = validation_recall.findings_from_dicts([*a["errors"], *a["warnings"]])
            fired.update(f.code.value for f in findings)
            if a["errors"] != a["recorded_errors"]:
                disagree += 1
            if a["score"] is not None:
                pairs += [(scoring.ErrorItem(**item), findings) for item in a["score"].get("items", [])]
    tally = validation_recall.tally(pairs)
    return {
        "total": tally.total, "caught": tally.caught, "flagged": tally.flagged, "silent": tally.silent,
        "recall": tally.recall, "by_kind": tally.by_kind, "findings_fired": dict(fired),
        # C5-PR1-6: the recomputed error findings should equal the recorded ones; any attempt where they don't is counted.
        "findings_disagree": disagree,
        # C5-CR1-6: runs where the staged route was not the source validation received (findings may not be the pipeline's).
        "route_mismatches": sum(1 for r in records if r.get("route_mismatch", False)),
    }


def _per_fixture(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per page: how many runs, how long they took, and whether the runs agreed (None unless there were two or more)."""
    out: dict[str, Any] = {}
    for name in sorted({r["fixture"] for r in records}):
        mine = [r for r in records if r["fixture"] == name]
        out[name] = {
            "runs": len(mine), "seconds": [r["seconds"] for r in mine],
            "runs_identical": all(r["raw"] == mine[0]["raw"] for r in mine) if len(mine) >= 2 else None,
        }
    return out


def aggregate(records: list[dict[str, Any]], labels: Mapping[str, PageLabel]) -> dict[str, Any]:
    """Everything the milestone reports, from the run records and the labels they were scored against."""
    seconds_by_source: dict[str, list[float]] = {}
    for r in records:
        seconds_by_source.setdefault(r.get("source") or "none", []).append(r["seconds"])
    return {
        "runs": len(records),
        "columns": {c: _column([scoring.PageScore.from_dict(r[f"{c}_score"]) for r in _scored_in(records, c)]) for c in COLUMNS},
        "gate": {c: _gate(records, labels, c) for c in COLUMNS},
        "retry": _retry(records),
        "validation": _validation(records),
        "per_fixture": _per_fixture(records),
        "cost": {
            "mean_seconds": round(sum(r["seconds"] for r in records) / len(records), 1) if records else 0.0,
            "mean_seconds_by_route": {k: round(sum(v) / len(v), 1) for k, v in seconds_by_source.items()},
        },
    }


# ---------------------------------------------------------------------------
# Rescore and compare (no model, no database)
# ---------------------------------------------------------------------------


def rescore(label: str) -> Path:
    """Recompute a saved run's scores from its stored extractions, into a NEW file; the original stays byte-identical.

    The model output (`raw`, `validated`, `committed`, and each staged document's `raw_extraction`) is the raw data and doesn't
    change, so a corrected label or a fixed scorer can be applied without a model call (A2.1-PR1-13, the rule `run_eval`
    follows). Needs the fixtures only to check image links against the page.
    """
    source = RESULTS_DIR / f"graph-{label}.json"
    data = json.loads(source.read_text())
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
                entry["database_score"] = db_score.score_database(
                    db_score.Scenario(entry["result"]["scenario"]), PAGE_LABELS[first_name],
                    PAGE_LABELS[rest[0]] if rest else None, entry["result"]["runs"][-1]["committed"],
                )
    data["aggregate"] = aggregate(data["runs"], PAGE_LABELS)
    data["rescored_from"] = label
    data["labels_sha"] = labels_sha()
    out = RESULTS_DIR / f"graph-rescore-{label}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return out


def _rescore_run(run: dict[str, Any]) -> None:
    """Recompute one run record's scores (raw, validated, committed, and each attempt's) from its stored extractions."""
    page_label = PAGE_LABELS.get(run["fixture"])
    if page_label is None:
        return
    fixture = run_eval.FIXTURES_DIR / run["fixture"]
    page_html = fixture.read_text() if fixture.suffix not in IMAGE_SUFFIXES and fixture.is_file() else ""
    run["raw_score"] = _score_dict(page_label, run["raw"], page_html, run["fixture"])
    run["validated_score"] = _score_dict(page_label, run["validated"], page_html, run["fixture"])
    run["committed_score"] = _score_dict(scoring.scheduled_only(page_label), run["committed"], page_html, run["fixture"])
    documents = {d["attempt"]: d for d in run["staged_documents"]}
    for attempt in run["attempts"]:
        document = documents.get(attempt["attempt"])
        if document is not None and document["raw_extraction"] is not None:
            attempt["score"] = _score_dict(page_label, document["raw_extraction"], page_html, run["fixture"])


def compare(labels: list[str]) -> None:
    """Print the headline numbers of saved runs side by side."""
    files = {name: json.loads((RESULTS_DIR / f"graph-{name}.json").read_text()) for name in labels}
    width = 26
    print("".ljust(width) + "".join(name.ljust(22) for name in labels))
    rows: list[tuple[str, Any]] = [("labels_sha", lambda f: str(f.get("labels_sha"))[:10]), ("started_at", lambda f: f.get("started_at"))]
    for column in COLUMNS:
        rows += [
            (f"{column}: recall", lambda f, c=column: round(f["aggregate"]["columns"][c]["rates"]["recall"], 3)),
            (f"{column}: precision", lambda f, c=column: round(f["aggregate"]["columns"][c]["rates"]["precision"], 3)),
            (f"{column}: gate", lambda f, c=column: "PASS" if f["aggregate"]["gate"][c]["passed"] else "FAIL"),
        ]
    rows += [
        ("retry rate", lambda f: round(f["aggregate"]["retry"]["retry_rate"], 3)),
        ("escalated", lambda f: f["aggregate"]["retry"]["escalated"]),
        ("validation recall", lambda f: round(f["aggregate"]["validation"]["recall"], 3)),
    ]
    for name, getter in rows:
        print(name.ljust(width) + "".join(str(getter(files[label])).ljust(22) for label in labels))


# ---------------------------------------------------------------------------
# Runners (these need a database)
# ---------------------------------------------------------------------------


def _context(factory: async_sessionmaker[AsyncSession]) -> WorkerContext:
    """The real Postgres stores and the in-memory stager (C5-D2: MongoDB is not what is being evaluated)."""
    return WorkerContext(
        audit=PostgresAuditWriter(factory), stager=InMemoryStager(),
        reader=PostgresCalendarReader(factory), writer=PostgresCalendarWriter(factory),
    )


async def run_pages(
    items: list[tuple[Path, PageLabel, LabelVenueFacts]], *, factory: async_sessionmaker[AsyncSession], runs: int,
    policy: RetryPolicy | None,
) -> list[dict[str, Any]]:
    """Run each page `runs` times, each on an empty calendar, and return the run records.

    The calendar is cleared before every run (`db_score.reset`), so one page's artists cannot change how the next page's artists
    are matched and every page starts from the same empty state. Infrastructure errors propagate: a database that fails is not a
    result, unlike a model that does (the graph records those itself)."""
    records = []
    for fixture, label, facts in items:
        for run_index in range(runs):
            await db_score.reset(factory)
            venue = await db_score.ensure_venue(factory, facts)

            async def committed(venue_id: int = venue.id) -> dict[str, Any]:
                return await db_score.committed_extraction(factory, venue_id)

            page_run: PageRun = await run_page(
                label=label, fixture=fixture, venue=venue, ctx=_context(factory), committed_rows=committed, policy=policy,
            )
            records.append({**asdict(page_run), "run": run_index})
            print(
                f"{fixture.name[:40]:40} | run {run_index} | attempts {page_run.attempt_count} | "
                f"escalated {page_run.escalated} | {page_run.seconds}s", flush=True,
            )
    return records


async def run_scenarios(
    scenario: db_score.Scenario, names: list[str], *, factory: async_sessionmaker[AsyncSession], policy: RetryPolicy | None,
) -> list[dict[str, Any]]:
    """Run `scenario` over the selected captures: one page each (repeat, perturbed) or each consecutive pair of one venue
    (sequence, overlap). Each instance starts from an empty calendar; its two runs do not reset between them."""
    if scenario in (db_score.Scenario.SEQUENCE, db_score.Scenario.OVERLAP):
        instances: list[tuple[str, str | None]] = [(a, b) for a, b in scenario_pairs(names)]
    else:
        instances = [(n, None) for n in names if n in PAGE_LABELS and not n.lower().endswith(IMAGE_SUFFIXES)]
    out = []
    for first_name, second_name in instances:
        await db_score.reset(factory)
        first = db_score.ScenarioPage(PAGE_LABELS[first_name], run_eval.FIXTURES_DIR / first_name)
        second = db_score.ScenarioPage(PAGE_LABELS[second_name], run_eval.FIXTURES_DIR / second_name) if second_name else None
        venue = await db_score.ensure_venue(factory, VENUE_FACTS[first.label.venue])
        result = await db_score.run_scenario(
            scenario, first=first, second=second, venue=venue, ctx=_context(factory), factory=factory, policy=policy,
        )
        rows = await db_score.committed_extraction(factory, venue.id)
        # A scenario whose first run left nothing to build on is reported with its reason and has no database score (C5-CR1-2).
        out.append({
            "pages": [first_name, *([second_name] if second_name else [])],
            "result": asdict(result),
            "database_score": (
                None if result.not_run else db_score.score_database(scenario, first.label, second.label if second else None, rows)
            ),
        })
        note = f"NOT RUN: {result.not_run}" if result.not_run else f"differences {result.count_differences}"
        print(f"{scenario.value}: {first_name} {'-> ' + second_name if second_name else ''} | {note}")
    return out


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", help="name for this run; results go to eval/results/graph-<label>.json")
    parser.add_argument(
        "--set", choices=["gated", "informational", "held_out", "all"], default="all",
        help="which labelled pages to run; 'all' is gated + informational and never includes held_out (C5-D3)",
    )
    parser.add_argument("--only", help="only fixtures whose file name contains this text")
    parser.add_argument("--runs", type=int, default=1, help="runs per page (default 1: at temperature 0 repeats are one sample)")
    parser.add_argument("--scenario", choices=SCENARIO_CHOICES, help="run a two-run database scenario instead of single pages")
    parser.add_argument("--threshold", type=float, help="the retry policy's confidence threshold (default: the pipeline's)")
    parser.add_argument("--max-attempts", type=int, help="the retry policy's attempt cap (default: the pipeline's)")
    parser.add_argument("--keep-db", action="store_true", help="leave the scratch database in place afterwards, to read the rows")
    parser.add_argument("--rescore", metavar="LABEL", help="rescore a saved run into graph-rescore-<LABEL>.json (no model)")
    parser.add_argument("--compare", nargs="+", metavar="LABEL", help="print saved runs side by side")
    return parser.parse_args(argv)


def _git_commit() -> str | None:
    """The commit the harness ran at, for the record; None outside a git checkout."""
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


async def evaluate(args: argparse.Namespace) -> int:
    """Create the scratch database, run the pages (or the scenario), write the results file, drop the database."""
    options, config = run_eval.configure({})
    policy = build_policy(args.threshold, args.max_attempts)
    fixtures = run_eval.select_fixtures(args.set, args.only)
    if not fixtures:
        print("no labelled fixtures to run (they are gitignored; capture them with eval/capture.py)")
        return 2
    names = [p.name for p in fixtures]
    started_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")

    url = scratch_db.eval_database_url(os.environ.get("EVAL_DATABASE_URL") or settings.database_url)
    scratch_db.check_eval_database_url(url)
    await scratch_db.create(url)
    await scratch_db.migrate(url)
    engine, factory = scratch_db.session_factory(url)
    try:
        records: list[dict[str, Any]] = []
        scenarios: list[dict[str, Any]] = []
        if args.scenario:
            scenarios = await run_scenarios(db_score.Scenario(args.scenario), names, factory=factory, policy=policy)
            # The second run of a sequence or overlap leaves another page's rows in the database, so its committed column is not
            # scored against its own page's label (see `_scored_in`); the scenario's database score covers it.
            records = [
                {
                    **run, "run": i, "scenario": s["result"]["scenario"],
                    "committed_scored": not (s["result"]["scenario"] in ("sequence", "overlap") and i == 1),
                }
                for s in scenarios for i, run in enumerate(s["result"]["runs"])
            ]
        else:
            items = [(p, PAGE_LABELS[p.name], VENUE_FACTS[PAGE_LABELS[p.name].venue]) for p in fixtures]
            records = await run_pages(items, factory=factory, runs=args.runs, policy=policy)
    finally:
        await engine.dispose()
        if not args.keep_db:
            await scratch_db.drop(url)

    try:
        provenance: dict[str, Any] | None = {options.model: run_eval.model_provenance(options.model, options.num_ctx)}
    except (httpx.HTTPError, OSError):
        provenance = None  # a hosted model has none to read here (C6 adds it); a local one that doesn't answer is noted, not fatal
    summary = aggregate(records, PAGE_LABELS)
    out_path = RESULTS_DIR / f"graph-{args.label}.json"
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path.write_text(json.dumps({
        "label": args.label, "started_at": started_at, "set": args.set, "scenario": args.scenario,
        "labels_sha": labels_sha(), "held_out_scored": held_out_scored(names, PAGE_LABELS), "harness_commit": _git_commit(),
        "config": dataclasses.asdict(config), "request_options": dataclasses.asdict(options),
        "request": run_eval.request_record(config, False),
        "policy": dataclasses.asdict(policy or DEFAULT_POLICY), "provenance": provenance,
        "aggregate": summary, "scenarios": scenarios, "runs": records,
    }, indent=2, ensure_ascii=False, default=str))
    print(f"\nwrote {out_path}")
    for column in COLUMNS:
        rates = summary["columns"][column]["rates"]
        gate = summary["gate"][column]
        print(f"{column:10} recall {rates['recall']:.3f}  precision {rates['precision']:.3f}  gate {'PASS' if gate['passed'] else 'FAIL'}")
    print(f"retry rate {summary['retry']['retry_rate']:.3f}; escalated {summary['retry']['escalated']}; "
          f"validation recall {summary['validation']['recall']:.3f} ({summary['validation']['silent']} silent)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.compare:
        compare(args.compare)
        return 0
    if args.rescore:
        print(f"wrote {rescore(args.rescore)}")
        return 0
    if not args.label:
        print("--label is required unless --compare or --rescore is given", file=sys.stderr)
        return 2
    return asyncio.run(evaluate(args))


if __name__ == "__main__":
    sys.exit(main())
