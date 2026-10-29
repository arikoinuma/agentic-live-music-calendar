"""Tests for the graph-level harness's results file, aggregate, rescore and command line (`eval/graph_eval.py`).

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, Test approach §3). `graph_run.py` runs one page; this module
turns many `PageRun` records into the numbers the milestone reports (shows found, field accuracy, the retry loop, validation
recall, the database) and writes them to a file that can be re-scored without a model.

How to read it: records are built by hand (`record`) where a number is being pinned, so each expected value is worked out from
the case; one test runs real pages end to end through a real database with a scripted model. Two judgements are Ari's gaps:
`scoring.headline_rates` (C5-K2) and `validation_recall.coverage` (C5-K4). The `stub_judgements` fixture stands in for both so
the aggregate's arithmetic is tested on its own; the tests that exercise the REAL gaps are named for them and stay red until
they are filled.
"""

import dataclasses
import datetime
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker import nodes
from agent_worker.eval import db_score, graph_eval, labels, scoring, validation_recall
from agent_worker.eval.labels import LabelledShow, PageLabel
from agent_worker.eval.labels import VenueFacts as LabelVenueFacts
from agent_worker.tests.fakes import (
    SPLITTER,
    event,
    jsonld_page,
    scripted_client,
    split_answer,
)
from agent_worker.validation import Severity

D = datetime.date
T = datetime.time


@pytest.fixture
def stub_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for Ari's `headline_rates` (C5-K2) with the recommended definition, for tests about something else."""
    def rates(score: scoring.PageScore) -> scoring.Rates:
        found = score.labelled - score.missed - score.acts_wrong
        lenient_den = score.returned - score.leaks
        return scoring.Rates(
            found, score.labelled, score.returned, found / score.labelled if score.labelled else 1.0,
            found / score.returned if score.returned else 1.0, found / lenient_den if lenient_den else 1.0,
        )

    monkeypatch.setattr(scoring, "headline_rates", rates)


@pytest.fixture
def stub_judgements(monkeypatch: pytest.MonkeyPatch, stub_rates: None) -> None:
    """Stand in for both of Ari's judgement calls, so the arithmetic around them can be tested without them: the rates (above)
    and `coverage` (C5-K4) as recommended. Tests that mean to exercise the real functions don't use this fixture."""
    def coverage(error: scoring.ErrorItem, findings: Any) -> validation_recall.Coverage:
        covering = [f for f in findings if f.show_index == error.index or (f.show_index is None and error.index is None)]
        if any(f.severity is Severity.ERROR for f in covering):
            return validation_recall.Coverage.CAUGHT
        return validation_recall.Coverage.FLAGGED if covering else validation_recall.Coverage.SILENT

    monkeypatch.setattr(validation_recall, "coverage", coverage)


def score_dict(**counts: Any) -> dict[str, Any]:
    """A page score as a results file holds it, with the given counts (the rest zero)."""
    return dataclasses.asdict(scoring.PageScore(**counts))


def record(
    fixture: str = "page.html", *, run: int = 0, attempts: list[dict[str, Any]] | None = None, escalated: bool = False,
    raw: dict[str, Any] | None = None, seconds: float = 1.0, source: str = "jsonld", **scores: dict[str, Any],
) -> dict[str, Any]:
    """A run record as `graph_eval` stores it: `asdict(PageRun)` plus the run index. Only what a test pins is filled in."""
    attempts = attempts if attempts is not None else [{
        "attempt": 1, "tier": "initial", "route": source, "model": "m", "larger_model_used": False, "error": None,
        "verdict": "passed", "reasons": [], "score": score_dict(), "errors": [], "warnings": [], "recorded_errors": [],
    }]
    return {
        "fixture": fixture, "run": run, "venue_id": 1, "run_id": 1, "seconds": seconds, "source": source,
        "attempt_count": len(attempts), "retried": len(attempts) > 1,
        "recovered": len(attempts) > 1 and not escalated, "escalated": escalated, "escalation_reason": None,
        "final_verdict": "failed" if escalated else "passed", "policy": {}, "reconcile_counts": None, "commit_written": None,
        "raw": raw, "validated": raw, "committed": {"shows": []},
        "raw_score": scores.get("raw_score", score_dict()), "validated_score": scores.get("validated_score", score_dict()),
        "committed_score": scores.get("committed_score", score_dict()), "attempts": attempts, "staged_documents": [],
    }


FINDING = {"code": "splitter_dropped", "severity": "error", "message": "m", "show_index": 1}


def attempt(n: int, tier: str, *, missed: int = 0, errors: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    """One attempt entry with `missed` shows missed in its score."""
    return {
        "attempt": n, "tier": tier, "route": "jsonld", "model": "m", "larger_model_used": False, "error": None,
        "verdict": "failed" if errors else "passed", "reasons": [], "score": score_dict(labelled=2, missed=missed),
        "errors": errors or [], "warnings": [], "recorded_errors": errors or [], **extra,
    }


GATED = PageLabel(venue="v", gated=True, captured_on=D(2026, 10, 12), shows=(LabelledShow(D(2026, 10, 20), ("A",), "A"),))


# ---------------------------------------------------------------------------
# The aggregate
# ---------------------------------------------------------------------------


def test_rates_are_computed_from_summed_counts_not_averaged_per_page() -> None:
    # Proves: C5-M2, and C5-K2 through the aggregate (red until Ari fills `headline_rates`). Page 1 has 5 labelled shows and
    # finds 4; page 2 has 10 and finds 10. Summed: 14 found of 15 labelled, recall 14/15 = 0.9333. Averaging the two pages'
    # recalls (0.8 and 1.0) would give 0.9, which weights a 5-show page like a 10-show one. Worked by hand from the case.
    runs = [
        record("p1.html", raw_score=score_dict(labelled=5, returned=4, missed=1)),
        record("p2.html", raw_score=score_dict(labelled=10, returned=10)),
    ]
    raw = graph_eval.aggregate(runs, {"p1.html": GATED, "p2.html": GATED})["columns"]["raw"]
    assert raw["found"] == 14 and raw["labelled"] == 15
    assert raw["rates"]["recall"] == 14 / 15


@pytest.mark.usefixtures("stub_judgements")
def test_the_aggregate_counts_each_column_separately() -> None:
    # Proves: the three columns (raw, validated, committed) are summed on their own, so the differences between them (the
    # point of the harness) survive: here validation fixes one miss the model made, and commit loses one show.
    runs = [record(
        raw_score=score_dict(labelled=4, returned=3, missed=1), validated_score=score_dict(labelled=4, returned=4),
        committed_score=score_dict(labelled=4, returned=3, missed=1),
    )]
    columns = graph_eval.aggregate(runs, {"page.html": GATED})["columns"]
    assert (columns["raw"]["missed"], columns["validated"]["missed"], columns["committed"]["missed"]) == (1, 0, 1)


@pytest.mark.usefixtures("stub_judgements")
def test_the_retry_statistics_count_runs_attempts_and_outcomes() -> None:
    # Proves: the retry block. Three runs: 1 attempt, 2 attempts (recovered), 3 attempts (escalated). Retry rate 2/3, mean
    # attempts (1+2+3)/3 = 2.0, one escalated, one recovered, and attempts by tier counted across all runs: initial x3,
    # narrowed x2, larger_model x1. Worked by hand from the three records.
    runs = [
        record(run=0),
        record(run=1, attempts=[attempt(1, "initial", missed=1, errors=[FINDING]), attempt(2, "narrowed")]),
        record(run=2, escalated=True, attempts=[
            attempt(1, "initial", missed=1, errors=[FINDING]), attempt(2, "narrowed", missed=1, errors=[FINDING]),
            attempt(3, "larger_model", missed=1, errors=[FINDING]),
        ]),
    ]
    retry = graph_eval.aggregate(runs, {"page.html": GATED})["retry"]
    assert (retry["runs"], retry["retried"], retry["escalated"], retry["recovered"]) == (3, 2, 1, 1)
    assert retry["retry_rate"] == 2 / 3 and retry["mean_attempts"] == 2.0
    assert retry["attempts_by_tier"] == {"initial": 3, "narrowed": 2, "larger_model": 1}


@pytest.mark.usefixtures("stub_judgements")
def test_the_retry_block_says_what_the_retry_changed() -> None:
    # Proves: C5-D7. For the runs that retried, the errors of attempt 1 and of the last attempt are summed, so "did the retry
    # fix anything" is a number: here a run with 2 missed shows on attempt 1 and none on attempt 2 changed 2 errors to 0.
    runs = [record(attempts=[attempt(1, "initial", missed=2, errors=[FINDING]), attempt(2, "narrowed", missed=0)])]
    retry = graph_eval.aggregate(runs, {"page.html": GATED})["retry"]
    assert (retry["errors_first_attempt"], retry["errors_final_attempt"]) == (2, 0)


@pytest.mark.usefixtures("stub_judgements")
def test_validation_recall_is_tallied_over_every_attempt() -> None:
    # Proves: C5-D7 and C5-K4 wiring. Each attempt's errors are joined to THAT attempt's findings. Attempt 1 missed show 1
    # and carries an error finding on index 1 (caught); attempt 2 has an acts-wrong error on index 0 and no finding (silent).
    # Stubbed coverage = the recommended definition. Expected: 2 errors, 1 caught, 1 silent.
    finding = {"code": "splitter_dropped", "severity": "error", "message": "m", "show_index": 1}
    first = attempt(1, "initial", errors=[finding])
    first["score"]["items"] = [{"kind": "missed", "date": "2026-10-20", "index": 1, "field": None}]
    second = attempt(2, "narrowed")
    second["score"]["items"] = [{"kind": "acts_wrong", "date": "2026-10-21", "index": 0, "field": None}]
    runs = [record(attempts=[first, second])]
    recall = graph_eval.aggregate(runs, {"page.html": GATED})["validation"]
    assert (recall["total"], recall["caught"], recall["silent"]) == (2, 1, 1)
    assert recall["findings_fired"] == {"splitter_dropped": 1}


@pytest.mark.usefixtures("stub_judgements")
def test_a_disagreement_between_recorded_and_recomputed_findings_is_reported() -> None:
    # Proves: C5-PR1-6 at run time. The recomputed error findings should equal what the pipeline recorded; if they ever
    # differ the aggregate counts it, so a drifted recomputation is visible in the file and not silently trusted.
    drift = attempt(1, "initial", errors=[FINDING])
    drift["recorded_errors"] = []
    agg = graph_eval.aggregate([record(attempts=[drift])], {"page.html": GATED})
    assert agg["validation"]["findings_disagree"] == 1


@pytest.mark.usefixtures("stub_judgements")
def test_identical_runs_of_a_page_are_flagged_identical() -> None:
    # Proves: at temperature 0 repeated runs are one sample (A2.1's confirmation run), so the file says whether they were
    # identical (the same flag `run_eval` records), and says nothing when a page has a single run.
    same = {"shows": [{"date": "2026-10-20"}]}
    differ: dict[str, Any] = {"shows": []}
    both = graph_eval.aggregate([record(run=0, raw=same), record(run=1, raw=same)], {"page.html": GATED})
    assert both["per_fixture"]["page.html"]["runs_identical"] is True
    split = graph_eval.aggregate([record(run=0, raw=same), record(run=1, raw=differ)], {"page.html": GATED})
    assert split["per_fixture"]["page.html"]["runs_identical"] is False
    single = graph_eval.aggregate([record(run=0, raw=same)], {"page.html": GATED})
    assert single["per_fixture"]["page.html"]["runs_identical"] is None


@pytest.mark.usefixtures("stub_judgements")
def test_the_gate_is_applied_to_each_column_over_the_gated_pages_only() -> None:
    # Proves: the committed column answers "does the PIPELINE meet A2.1-D1", not just the model. A gated page with a missed
    # show in the committed column fails the committed gate while the raw column passes; an informational page's miss is not
    # counted at all (gates apply to gated pages, A2.1-D2).
    info = dataclasses.replace(GATED, gated=False)
    runs = [
        record("g.html", committed_score=score_dict(labelled=1, missed=1)),
        record("i.html", raw_score=score_dict(labelled=1, missed=1)),
    ]
    gate = graph_eval.aggregate(runs, {"g.html": GATED, "i.html": info})["gate"]
    assert (gate["raw"]["passed"], gate["committed"]["passed"]) == (True, False)


@pytest.mark.usefixtures("stub_judgements")
def test_the_committed_column_leaves_out_a_run_whose_rows_include_an_earlier_page() -> None:
    # Proves: C5-CR1-1. After a correct SEQUENCE the database still holds the first page's shows, so the second run's committed
    # rows scored against the second page's label alone would report them as invented. Such a run is flagged
    # `committed_scored: False` and left out of the committed column and gate (its raw and validated scores still count; the
    # scenario's own `database_score` is the right measure). Expected: the 2 "fabricated" in the flagged run are not summed.
    runs = [
        record("p.html", run=0, committed_score=score_dict(labelled=2, returned=2)),
        {**record("p.html", run=1, committed_score=score_dict(labelled=2, returned=4, fabricated=2)), "committed_scored": False},
    ]
    agg = graph_eval.aggregate(runs, {"p.html": GATED})
    assert agg["columns"]["committed"]["fabricated"] == 0
    assert agg["columns"]["committed"]["labelled"] == 2
    assert agg["gate"]["committed"]["passed"] is True
    assert agg["columns"]["raw"]["labelled"] == 0  # the other columns still count both runs (both have empty scores here)


@pytest.mark.usefixtures("stub_judgements")
def test_the_aggregate_counts_a_route_mismatch_between_the_document_and_the_extraction_source() -> None:
    # Proves: C5-CR1-6. Recomputing findings assumes the staged document's `route` is the source validation received; `run_page`
    # checks that on the final attempt and records `route_mismatch`, and the aggregate counts the runs where it did not hold, so a
    # drift is visible in the file instead of silently recomputing warnings under the wrong source.
    runs = [{**record(run=0), "route_mismatch": False}, {**record(run=1), "route_mismatch": True}]
    assert graph_eval.aggregate(runs, {"page.html": GATED})["validation"]["route_mismatches"] == 1


@pytest.mark.usefixtures("stub_rates")
def test_validation_recall_in_the_aggregate_follows_the_real_coverage_definition() -> None:
    # Proves: C5-PR1-12 / C5-CR1-9. The other aggregate tests stand in for Ari's `coverage`; this one does not, so his version of
    # C5-K4 reaches an aggregate-level test. One acts-wrong error on show 3 with an ERROR finding on show 3: caught (red until
    # the gap is filled). Expected by the C5-K4 definition, worked by hand.
    finding = {"code": "act_not_in_title", "severity": "error", "message": "m", "show_index": 3}
    a = attempt(1, "initial", errors=[finding])
    a["score"]["items"] = [{"kind": "acts_wrong", "date": "2026-10-11", "index": 3, "field": None}]
    recall = graph_eval.aggregate([record(attempts=[a])], {"page.html": GATED})["validation"]
    assert (recall["total"], recall["caught"]) == (1, 1)


# ---------------------------------------------------------------------------
# The file: labels hash, held-out, policy
# ---------------------------------------------------------------------------


def test_the_labels_hash_changes_when_a_label_does(tmp_path: Path) -> None:
    # Proves: a results file names the labels that scored it. Two label files that differ by one character hash differently,
    # and the same text hashes the same.
    one, two = tmp_path / "one.py", tmp_path / "two.py"
    one.write_text("PAGE_LABELS = {'a': 1}")
    two.write_text("PAGE_LABELS = {'a': 2}")
    assert graph_eval.labels_sha(one) != graph_eval.labels_sha(two)
    assert graph_eval.labels_sha(one) == graph_eval.labels_sha(one)


def test_the_file_records_whether_a_held_out_page_was_scored() -> None:
    # Proves: C5-D3. The first held-out scoring is C6's, so the file says outright whether any held-out page was scored here.
    held = dataclasses.replace(GATED, held_out=True)
    assert graph_eval.held_out_scored(["a.html"], {"a.html": GATED}) is False
    assert graph_eval.held_out_scored(["a.html", "b.html"], {"a.html": GATED, "b.html": held}) is True


def test_the_policy_flags_build_on_the_default_policy_so_the_escalation_model_survives() -> None:
    # Proves: C5-PR1-12 (c), C5-D5. `--threshold`/`--max-attempts` change only those fields of the default policy; a fresh
    # `RetryPolicy(...)` would drop the configured `escalation_model`. No flags means no policy (the default is used).
    from agent_worker.policy import DEFAULT_POLICY

    assert graph_eval.build_policy(None, None) is None
    policy = graph_eval.build_policy(0.99, 1)
    assert policy == dataclasses.replace(DEFAULT_POLICY, confidence_threshold=0.99, max_attempts=1)
    assert graph_eval.build_policy(None, 2) == dataclasses.replace(DEFAULT_POLICY, max_attempts=2)


# ---------------------------------------------------------------------------
# Scenario pairing and the command line
# ---------------------------------------------------------------------------


def test_scenario_pairs_are_consecutive_captures_of_one_venue_in_date_order() -> None:
    # Proves: the sequence and overlap scenarios need two captures of ONE venue, oldest first. A venue with one capture
    # yields no pair; two venues are paired separately. Expected: White Squirrel's August then October capture.
    pairs = graph_eval.scenario_pairs(sorted(labels.PAGE_LABELS))
    assert ("Archives_ Events - The White Squirrel Bar.html", "white_squirrel-2026-10-10.html") in pairs
    assert ("Terminal Bar – The Terminal Bar.html", "terminal-2026-10-10.html") in pairs
    assert all(labels.PAGE_LABELS[a].venue == labels.PAGE_LABELS[b].venue for a, b in pairs)
    assert all(labels.PAGE_LABELS[a].captured_on < labels.PAGE_LABELS[b].captured_on for a, b in pairs)
    assert not any("mortimers" in a for a, _ in pairs)  # one capture only


@pytest.mark.parametrize(("argv", "expected"), [
    (["--label", "x"], {"set": "all", "runs": 1, "scenario": None, "threshold": None, "max_attempts": None, "keep_db": False}),
    (["--label", "x", "--set", "held_out", "--runs", "2"], {"set": "held_out", "runs": 2}),
    (["--label", "x", "--scenario", "perturbed", "--threshold", "0.99", "--max-attempts", "2", "--keep-db"],
     {"scenario": "perturbed", "threshold": 0.99, "max_attempts": 2, "keep_db": True}),
    (["--rescore", "old"], {"rescore": "old"}),
    (["--compare", "a", "b"], {"compare": ["a", "b"]}),
])
def test_the_command_line(argv: list[str], expected: dict[str, Any]) -> None:
    # Proves: the flags the plan names (--label, --set, --runs, --scenario, --threshold, --max-attempts, --keep-db, --rescore,
    # --compare) parse to the values the run reads, with the plan's defaults (all pages, one run, no scenario, default policy).
    args = vars(graph_eval.parse_args(argv))
    for key, value in expected.items():
        assert args[key] == value


# ---------------------------------------------------------------------------
# Rescore: new scores from stored data, no model, the original untouched
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("stub_judgements")
def test_rescore_rebuilds_scores_from_the_stored_extractions_and_leaves_the_original_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: the A2.1-PR1-13 rule, for the graph file. A label corrected after a run (here: one more labelled show) changes
    # the scores on --rescore with no model call; the rescored data goes to a NEW file and the original is byte-identical.
    page = tmp_path / "page.html"
    page.write_text("<html></html>")
    monkeypatch.setattr(graph_eval, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(graph_eval.run_eval, "FIXTURES_DIR", tmp_path)
    extraction = {"page_readable": True, "shows": [{
        "venue": "V", "date": "2026-10-20", "time": None, "end_time": None, "acts": [{"name": "A"}],
        "admission_advance": None, "admission_day": None, "free_admission": None, "image_url": None,
    }]}
    original_label = PageLabel(venue="v", gated=True, captured_on=D(2026, 10, 12), shows=(LabelledShow(D(2026, 10, 20), ("A",), "A"),))
    run = record("page.html", raw=extraction)
    run["validated"], run["committed"] = extraction, extraction
    run["staged_documents"] = []
    source = tmp_path / "graph-old.json"
    source.write_text(json.dumps({"label": "old", "runs": [run], "aggregate": {}}))
    before = source.read_bytes()
    corrected = dataclasses.replace(original_label, shows=(*original_label.shows, LabelledShow(D(2026, 10, 21), ("B",), "B")))
    monkeypatch.setitem(labels.PAGE_LABELS, "page.html", corrected)
    out = graph_eval.rescore("old")
    assert source.read_bytes() == before
    rescored = json.loads(out.read_text())
    assert rescored["rescored_from"] == "old"
    assert rescored["aggregate"]["columns"]["raw"]["missed"] == 1  # the corrected label's second show was never found


# ---------------------------------------------------------------------------
# End to end on real pages, a real database and a scripted model
# ---------------------------------------------------------------------------


@pytest.fixture
def factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory on the test connection in savepoint mode (the writers commit; the outer rollback undoes it)."""
    return async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest.mark.usefixtures("stub_judgements")
async def test_run_pages_runs_each_page_alone_on_an_empty_calendar(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: C5-D2 and the reset between pages. Two independent pages of one venue are run in turn; the second page's committed
    # rows hold ONLY its own show, because the harness cleared the first page's before it ran (otherwise the second page's
    # committed column would also hold the first page's show, a fabrication). Records carry the run index and the scores.
    first, second = tmp_path / "one.html", tmp_path / "two.html"
    first.write_text(jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00")))
    second.write_text(jsonld_page(event("Lent", "2026-10-21T21:00:00-05:00")))
    facts = LabelVenueFacts("The Test Venue", "https://example.test/calendar")
    label_one = PageLabel(venue="v", gated=True, captured_on=D(2026, 10, 12), shows=(LabelledShow(D(2026, 10, 20), ("Nona",), "Nona", T(21, 0)),))
    label_two = dataclasses.replace(label_one, shows=(LabelledShow(D(2026, 10, 21), ("Lent",), "Lent", T(21, 0)),))
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [split_answer(("Nona", ["Nona"])), split_answer(("Lent", ["Lent"]))]}))
    records = await graph_eval.run_pages([(first, label_one, facts), (second, label_two, facts)], factory=factory, runs=1, policy=None)
    assert [(r["fixture"], r["run"]) for r in records] == [("one.html", 0), ("two.html", 0)]
    assert [len(r["committed"]["shows"]) for r in records] == [1, 1]
    assert records[1]["committed"]["shows"][0]["acts"] == [{"name": "Lent"}]
    assert records[1]["committed_score"]["fabricated"] == 0
    json.dumps(records)  # the whole record is plain data


def test_db_score_scenarios_are_the_ones_the_command_line_offers() -> None:
    # Proves: the CLI's --scenario choices are exactly the scenarios `db_score` defines, so a new scenario can't be added to one
    # and forgotten in the other.
    parser_choices = {s.value for s in db_score.Scenario}
    assert parser_choices == {"repeat", "sequence", "overlap", "perturbed"}
    assert set(graph_eval.SCENARIO_CHOICES) == parser_choices


@pytest.mark.usefixtures("stub_judgements")
def test_rescore_also_rescores_the_scenarios_database_score(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: C5-CR1-3. A corrected label must reach the scenario block too, or the rescored file contradicts itself: the
    # database score is recomputed from the last run's stored rows and the scenario's page labels. Here a corrected label adds
    # a show the stored rows never held, so the scenario's database score gains a miss (0 before, 1 after).
    monkeypatch.setattr(graph_eval, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(graph_eval.run_eval, "FIXTURES_DIR", tmp_path)
    (tmp_path / "page.html").write_text("<html></html>")
    rows = {"page_readable": True, "shows": [{
        "date": "2026-10-20", "time": None, "end_time": None, "acts": [{"name": "A"}], "admission_advance": None,
        "admission_day": None, "free_admission": None, "image_url": None, "status": "scheduled",
    }]}
    label = PageLabel(venue="v", gated=True, captured_on=D(2026, 10, 12), shows=(LabelledShow(D(2026, 10, 20), ("A",), "A"),))
    run = record("page.html", raw=rows)
    run["raw"] = run["validated"] = run["committed"] = rows
    scenario = {
        "pages": ["page.html"], "database_score": score_dict(labelled=1),
        "result": {"scenario": "repeat", "runs": [run, run], "expected_counts": None, "count_differences": [], "perturbation": None, "not_run": None},
    }
    (tmp_path / "graph-old.json").write_text(json.dumps({"label": "old", "scenario": "repeat", "runs": [run], "scenarios": [scenario]}))
    monkeypatch.setattr(db_score, "expected_rows", lambda sc, first, second: list(first.shows))
    corrected = dataclasses.replace(label, shows=(*label.shows, LabelledShow(D(2026, 10, 21), ("B",), "B")))
    monkeypatch.setitem(labels.PAGE_LABELS, "page.html", corrected)
    out = json.loads(graph_eval.rescore("old").read_text())
    assert out["scenarios"][0]["database_score"]["missed"] == 1
    assert out["scenarios"][0]["result"]["runs"][1]["raw_score"]["missed"] == 1
