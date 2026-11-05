"""Tests for the graph-level harness's runner and command line (`model_eval/labeled_page_runs/run_labeled_pages.py`): flags, scenarios, rescore, running pages.

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, Test approach §3). The numbers themselves are tested in
`test_aggregate_scores.py`, the results file in `test_results_file.py`, the report in `test_markdown_report.py`. This module covers
what is left in `run_labeled_pages`: how flags become a policy and a list of scenario pairs, how a saved run is rescored with no model, and
one test that runs real pages end to end through a real database with a scripted model.

How to read it: run records come from `test_aggregate_scores.record`. Tests that rescore redirect `results_file.RESULTS_DIR` to a
temporary folder (the code reads it as a module attribute at call time, so the patch reaches it).
"""

import dataclasses
import datetime
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker import nodes
from agent_worker.model_eval import labels
from agent_worker.model_eval.labeled_page_runs import (
    run_labeled_pages,
    two_run_scenarios,
)
from agent_worker.model_eval.labels import LabelledShow, PageLabel
from agent_worker.model_eval.labels import VenueFacts as LabelVenueFacts
from agent_worker.model_eval.saved_run_reports import results_file
from agent_worker.tests.fakes import (
    SPLITTER,
    event,
    jsonld_page,
    scripted_client,
    split_answer,
)
from agent_worker.tests.model_eval.test_aggregate_scores import record, score_dict

D = datetime.date
T = datetime.time

def test_the_policy_flags_build_on_the_default_policy_so_the_escalation_model_survives() -> None:
    # Proves: C5-PR1-12 (c), C5-D5. `--threshold`/`--max-attempts` change only those fields of the default policy; a fresh
    # `RetryPolicy(...)` would drop the configured `escalation_model`. No flags means no policy (the default is used).
    from agent_worker.policy import DEFAULT_POLICY

    assert run_labeled_pages.build_policy(None, None) is None
    policy = run_labeled_pages.build_policy(0.99, 1)
    assert policy == dataclasses.replace(DEFAULT_POLICY, confidence_threshold=0.99, max_attempts=1)
    assert run_labeled_pages.build_policy(None, 2) == dataclasses.replace(DEFAULT_POLICY, max_attempts=2)


# ---------------------------------------------------------------------------
# Scenario pairing and the command line
# ---------------------------------------------------------------------------


def test_scenario_pairs_are_consecutive_captures_of_one_venue_in_date_order() -> None:
    # Proves: the sequence and overlap scenarios need two captures of ONE venue, oldest first. A venue with one capture
    # yields no pair; two venues are paired separately. Expected: White Squirrel's August then October capture.
    pairs = run_labeled_pages.scenario_pairs(sorted(labels.PAGE_LABELS))
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
    args = vars(run_labeled_pages.parse_args(argv))
    for key, value in expected.items():
        assert args[key] == value


# ---------------------------------------------------------------------------
# Rescore: new scores from stored data, no model, the original untouched
# ---------------------------------------------------------------------------


def test_rescore_rebuilds_scores_from_the_stored_extractions_and_leaves_the_original_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: the A2.1-PR1-13 rule, for the graph file. A label corrected after a run (here: one more labelled show) changes
    # the scores on --rescore with no model call; the rescored data goes to a NEW file and the original is byte-identical.
    page = tmp_path / "page.html"
    page.write_text("<html></html>")
    monkeypatch.setattr(results_file, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_labeled_pages.run_eval, "CAPTURED_PAGES_DIR", tmp_path)
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
    out = run_labeled_pages.rescore("old")
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
    records = await run_labeled_pages.run_pages([(first, label_one, facts), (second, label_two, facts)], factory=factory, runs=1, policy=None)
    assert [(r["fixture"], r["run"]) for r in records] == [("one.html", 0), ("two.html", 0)]
    assert [len(r["committed"]["shows"]) for r in records] == [1, 1]
    assert records[1]["committed"]["shows"][0]["acts"] == [{"name": "Lent"}]
    assert records[1]["committed_score"]["fabricated"] == 0
    json.dumps(records)  # the whole record is plain data


def test_two_run_scenarios_are_the_ones_the_command_line_offers() -> None:
    # Proves: the CLI's --scenario choices are exactly the scenarios `two_run_scenarios` defines, so a new scenario can't be added to one
    # and forgotten in the other.
    parser_choices = {s.value for s in two_run_scenarios.Scenario}
    assert parser_choices == {"repeat", "sequence", "overlap", "perturbed"}
    assert set(run_labeled_pages.SCENARIO_CHOICES) == parser_choices


def test_rescore_also_rescores_the_scenarios_database_score(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: C5-CR1-3. A corrected label must reach the scenario block too, or the rescored file contradicts itself: the
    # database score is recomputed from the last run's stored rows and the scenario's page labels. Here a corrected label adds
    # a show the stored rows never held, so the scenario's database score gains a miss (0 before, 1 after).
    monkeypatch.setattr(results_file, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_labeled_pages.run_eval, "CAPTURED_PAGES_DIR", tmp_path)
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
    monkeypatch.setattr(two_run_scenarios, "expected_rows", lambda sc, first, second: list(first.shows))
    corrected = dataclasses.replace(label, shows=(*label.shows, LabelledShow(D(2026, 10, 21), ("B",), "B")))
    monkeypatch.setitem(labels.PAGE_LABELS, "page.html", corrected)
    out = json.loads(run_labeled_pages.rescore("old").read_text())
    assert out["scenarios"][0]["database_score"]["missed"] == 1
    assert out["scenarios"][0]["result"]["runs"][1]["raw_score"]["missed"] == 1


def test_the_snapshot_flag() -> None:
    # Proves: `--snapshot LABEL` parses (and sits beside --report and --compare).
    assert run_labeled_pages.parse_args(["--snapshot", "x"]).snapshot == "x"


def test_only_the_second_run_of_a_sequence_or_overlap_is_left_out_of_the_committed_column() -> None:
    # Proves: C5-CR1-1, the rule that was a string comparison inside `evaluate` and is now a function. The second run of a
    # sequence or overlap leaves an earlier page's rows too, so its committed column is not scored against its own label; every
    # other run (the first of those scenarios, and both runs of a repeat or perturbed one) is scored. Expected flags are the rule.
    def scenario(kind: str) -> dict[str, Any]:
        return {"result": {"scenario": kind, "runs": [record("a.html"), record("b.html")]}}

    flags = {kind: [r["committed_scored"] for r in run_labeled_pages.scenario_records([scenario(kind)])] for kind in
             ("repeat", "sequence", "overlap", "perturbed")}
    assert flags == {"repeat": [True, True], "sequence": [True, False], "overlap": [True, False], "perturbed": [True, True]}
    tagged = run_labeled_pages.scenario_records([scenario("sequence")])
    assert [(r["run"], r["scenario"]) for r in tagged] == [(0, "sequence"), (1, "sequence")]
