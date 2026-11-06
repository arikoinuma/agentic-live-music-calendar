"""Tests for the aggregate: the numbers the C5 report is built from (`model_eval/saved_run_reports/aggregate_scores.py`).

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, Test approach §3). `run_one_page.py` runs one page; the aggregate
turns many `PageRun` records into the numbers the milestone reports (shows found, field accuracy, the retry loop, validation recall,
repeatability, the gate). No database, model or file is involved.

How to read it: records are built by hand (`record`) where a number is being pinned, so each expected value is worked out from the
case. The aggregate calls two of Ari's judgements, `scoring.headline_rates` (C5-K2) and `validation_recall.coverage` (C5-K4), and
these tests use the real ones. The helpers at the top (`record`, `attempt`, `score_dict`, `GATED`) are imported by the other
graph-eval test modules, which need run records of the same shape.
"""

import dataclasses
import datetime
from typing import Any

from agent_worker.model_eval import scoring
from agent_worker.model_eval.labels import LabelledShow, PageLabel
from agent_worker.model_eval.saved_run_reports import aggregate_scores

D = datetime.date
T = datetime.time


def score_dict(**counts: Any) -> dict[str, Any]:
    """A page score as a results file holds it, with the given counts (the rest zero)."""
    return dataclasses.asdict(scoring.PageScore(**counts))


def record(
    fixture: str = "page.html",
    *,
    run: int = 0,
    attempts: list[dict[str, Any]] | None = None,
    escalated: bool = False,
    raw: dict[str, Any] | None = None,
    seconds: float = 1.0,
    source: str = "jsonld",
    **scores: dict[str, Any],
) -> dict[str, Any]:
    """A run record as `run_labeled_pages` stores it: `asdict(PageRun)` plus the run index. Only what a test pins is filled in."""
    attempts = (
        attempts
        if attempts is not None
        else [
            {
                "attempt": 1,
                "tier": "initial",
                "route": source,
                "model": "m",
                "larger_model_used": False,
                "error": None,
                "verdict": "passed",
                "reasons": [],
                "score": score_dict(),
                "errors": [],
                "warnings": [],
                "recorded_errors": [],
            }
        ]
    )
    return {
        "fixture": fixture,
        "run": run,
        "venue_id": 1,
        "run_id": 1,
        "seconds": seconds,
        "source": source,
        "attempt_count": len(attempts),
        "retried": len(attempts) > 1,
        "recovered": len(attempts) > 1 and not escalated,
        "escalated": escalated,
        "escalation_reason": None,
        "final_verdict": "failed" if escalated else "passed",
        "policy": {},
        "reconcile_counts": None,
        "commit_written": None,
        "raw": raw,
        "validated": raw,
        "committed": {"shows": []},
        "raw_score": scores.get("raw_score", score_dict()),
        "validated_score": scores.get("validated_score", score_dict()),
        "committed_score": scores.get("committed_score", score_dict()),
        "attempts": attempts,
        "staged_documents": [],
    }


FINDING = {"code": "splitter_dropped", "severity": "error", "message": "m", "show_index": 1}


def attempt(
    n: int, tier: str, *, missed: int = 0, errors: list[dict[str, Any]] | None = None, **extra: Any
) -> dict[str, Any]:
    """One attempt entry with `missed` shows missed in its score."""
    return {
        "attempt": n,
        "tier": tier,
        "route": "jsonld",
        "model": "m",
        "larger_model_used": False,
        "error": None,
        "verdict": "failed" if errors else "passed",
        "reasons": [],
        "score": score_dict(labelled=2, missed=missed),
        "errors": errors or [],
        "warnings": [],
        "recorded_errors": errors or [],
        **extra,
    }


GATED = PageLabel(
    venue="v", gated=True, captured_on=D(2026, 10, 12), shows=(LabelledShow(D(2026, 10, 20), ("A",), "A"),)
)


# ---------------------------------------------------------------------------
# The aggregate
# ---------------------------------------------------------------------------


def test_rates_are_computed_from_summed_counts_not_averaged_per_page() -> None:
    # Proves: C5-M2, and C5-K2 through the aggregate. Page 1 has 5 labelled shows and
    # finds 4; page 2 has 10 and finds 10. Summed: 14 found of 15 labelled, recall 14/15 = 0.9333. Averaging the two pages'
    # recalls (0.8 and 1.0) would give 0.9, which weights a 5-show page like a 10-show one. Worked by hand from the case.
    runs = [
        record("p1.html", raw_score=score_dict(labelled=5, returned=4, missed=1)),
        record("p2.html", raw_score=score_dict(labelled=10, returned=10)),
    ]
    raw = aggregate_scores.aggregate(runs, {"p1.html": GATED, "p2.html": GATED})["columns"]["raw"]
    assert raw["found"] == 14 and raw["labelled"] == 15
    assert raw["rates"]["recall"] == 14 / 15


def test_the_aggregate_counts_each_column_separately() -> None:
    # Proves: the three columns (raw, validated, committed) are summed on their own, so the differences between them (the
    # point of the harness) survive: here validation fixes one miss the model made, and commit loses one show.
    runs = [
        record(
            raw_score=score_dict(labelled=4, returned=3, missed=1),
            validated_score=score_dict(labelled=4, returned=4),
            committed_score=score_dict(labelled=4, returned=3, missed=1),
        )
    ]
    columns = aggregate_scores.aggregate(runs, {"page.html": GATED})["columns"]
    assert (columns["raw"]["missed"], columns["validated"]["missed"], columns["committed"]["missed"]) == (1, 0, 1)


def test_the_retry_statistics_count_runs_attempts_and_outcomes() -> None:
    # Proves: the retry block. Three runs: 1 attempt, 2 attempts (recovered), 3 attempts (escalated). Retry rate 2/3, mean
    # attempts (1+2+3)/3 = 2.0, one escalated, one recovered, and attempts by tier counted across all runs: initial x3,
    # narrowed x2, larger_model x1. Worked by hand from the three records.
    runs = [
        record(run=0),
        record(run=1, attempts=[attempt(1, "initial", missed=1, errors=[FINDING]), attempt(2, "narrowed")]),
        record(
            run=2,
            escalated=True,
            attempts=[
                attempt(1, "initial", missed=1, errors=[FINDING]),
                attempt(2, "narrowed", missed=1, errors=[FINDING]),
                attempt(3, "larger_model", missed=1, errors=[FINDING]),
            ],
        ),
    ]
    retry = aggregate_scores.aggregate(runs, {"page.html": GATED})["retry"]
    assert (retry["runs"], retry["retried"], retry["escalated"], retry["recovered"]) == (3, 2, 1, 1)
    assert retry["retry_rate"] == 2 / 3 and retry["mean_attempts"] == 2.0
    assert retry["attempts_by_tier"] == {"initial": 3, "narrowed": 2, "larger_model": 1}


def test_the_retry_block_says_what_the_retry_changed() -> None:
    # Proves: C5-D7. For the runs that retried, the errors of attempt 1 and of the last attempt are summed, so "did the retry
    # fix anything" is a number: here a run with 2 missed shows on attempt 1 and none on attempt 2 changed 2 errors to 0.
    runs = [record(attempts=[attempt(1, "initial", missed=2, errors=[FINDING]), attempt(2, "narrowed", missed=0)])]
    retry = aggregate_scores.aggregate(runs, {"page.html": GATED})["retry"]
    assert (retry["errors_first_attempt"], retry["errors_final_attempt"]) == (2, 0)


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
    recall = aggregate_scores.aggregate(runs, {"page.html": GATED})["validation"]
    assert (recall["total"], recall["caught"], recall["silent"]) == (2, 1, 1)
    assert recall["findings_fired"] == {"splitter_dropped": 1}


def test_a_disagreement_between_recorded_and_recomputed_findings_is_reported() -> None:
    # Proves: C5-PR1-6 at run time. The recomputed error findings should equal what the pipeline recorded; if they ever
    # differ the aggregate counts it, so a drifted recomputation is visible in the file and not silently trusted.
    drift = attempt(1, "initial", errors=[FINDING])
    drift["recorded_errors"] = []
    agg = aggregate_scores.aggregate([record(attempts=[drift])], {"page.html": GATED})
    assert agg["validation"]["findings_disagree"] == 1


def test_identical_runs_of_a_page_are_flagged_identical() -> None:
    # Proves: at temperature 0 repeated runs are one sample (A2.1's confirmation run), so the file says whether they were
    # identical (the same flag `run_eval` records), and says nothing when a page has a single run.
    same = {"shows": [{"date": "2026-10-20"}]}
    differ: dict[str, Any] = {"shows": []}
    both = aggregate_scores.aggregate([record(run=0, raw=same), record(run=1, raw=same)], {"page.html": GATED})
    assert both["per_fixture"]["page.html"]["runs_identical"] is True
    split = aggregate_scores.aggregate([record(run=0, raw=same), record(run=1, raw=differ)], {"page.html": GATED})
    assert split["per_fixture"]["page.html"]["runs_identical"] is False
    single = aggregate_scores.aggregate([record(run=0, raw=same)], {"page.html": GATED})
    assert single["per_fixture"]["page.html"]["runs_identical"] is None


def test_the_gate_is_applied_to_each_column_over_the_gated_pages_only() -> None:
    # Proves: the committed column answers "does the PIPELINE meet A2.1-D1", not just the model. A gated page with a missed
    # show in the committed column fails the committed gate while the raw column passes; an informational page's miss is not
    # counted at all (gates apply to gated pages, A2.1-D2).
    info = dataclasses.replace(GATED, gated=False)
    runs = [
        record("g.html", committed_score=score_dict(labelled=1, missed=1)),
        record("i.html", raw_score=score_dict(labelled=1, missed=1)),
    ]
    gate = aggregate_scores.aggregate(runs, {"g.html": GATED, "i.html": info})["gate"]
    assert (gate["raw"]["passed"], gate["committed"]["passed"]) == (True, False)


def test_the_committed_column_leaves_out_a_run_whose_rows_include_an_earlier_page() -> None:
    # Proves: C5-CR1-1. After a correct SEQUENCE the database still holds the first page's shows, so the second run's committed
    # rows scored against the second page's label alone would report them as invented. Such a run is flagged
    # `committed_scored: False` and left out of the committed column and gate (its raw and validated scores still count; the
    # scenario's own `database_score` is the right measure). Expected: the 2 "fabricated" in the flagged run are not summed.
    runs = [
        record("p.html", run=0, committed_score=score_dict(labelled=2, returned=2)),
        {
            **record("p.html", run=1, committed_score=score_dict(labelled=2, returned=4, fabricated=2)),
            "committed_scored": False,
        },
    ]
    agg = aggregate_scores.aggregate(runs, {"p.html": GATED})
    assert agg["columns"]["committed"]["fabricated"] == 0
    assert agg["columns"]["committed"]["labelled"] == 2
    assert agg["gate"]["committed"]["passed"] is True
    assert (
        agg["columns"]["raw"]["labelled"] == 0
    )  # the other columns still count both runs (both have empty scores here)


def test_the_aggregate_counts_a_route_mismatch_between_the_document_and_the_extraction_source() -> None:
    # Proves: C5-CR1-6. Recomputing findings assumes the staged document's `route` is the source validation received; `run_page`
    # checks that on the final attempt and records `route_mismatch`, and the aggregate counts the runs where it did not hold, so a
    # drift is visible in the file instead of silently recomputing warnings under the wrong source.
    runs = [{**record(run=0), "route_mismatch": False}, {**record(run=1), "route_mismatch": True}]
    assert aggregate_scores.aggregate(runs, {"page.html": GATED})["validation"]["route_mismatches"] == 1


def test_validation_recall_in_the_aggregate_follows_the_real_coverage_definition() -> None:
    # Proves: C5-PR1-12 / C5-CR1-9. This pins the real `coverage` at the aggregate level, so a later edit to C5-K4's definition can turn a test red here. One acts-wrong error on show 3 with an ERROR finding on show 3: caught. Expected by the
    # C5-K4 definition, worked by hand.
    finding = {"code": "act_not_in_title", "severity": "error", "message": "m", "show_index": 3}
    a = attempt(1, "initial", errors=[finding])
    a["score"]["items"] = [{"kind": "acts_wrong", "date": "2026-10-11", "index": 3, "field": None}]
    recall = aggregate_scores.aggregate([record(attempts=[a])], {"page.html": GATED})["validation"]
    assert (recall["total"], recall["caught"]) == (1, 1)


def test_a_saved_gate_keyed_with_the_old_route_name_is_read_as_structured() -> None:
    # Proves (C6.1-D1): a results file written before the rename keys its per-route gate "jsonld"; the
    # comparison asks for "structured" and must still find it, or every C5 and C6 baseline would show "-" for that
    # row. The file's shape is the one `run_eval.aggregate` writes (gate -> scope -> passed/failures/pages).
    from agent_worker.model_eval import run_eval

    old = {"aggregate": {"gate": {"jsonld": {"passed": True, "failures": [], "pages": 3}}}}
    new = {"aggregate": {"gate": {"structured": {"passed": False, "failures": ["x"], "pages": 3}}}}
    assert run_eval._gate_line(old, "structured") == "PASS"
    assert run_eval._gate_line(new, "structured") == "FAIL (1)"
    assert run_eval._gate_line({"aggregate": {"gate": {}}}, "structured") == "-"


def test_the_cost_by_route_reads_a_stored_old_route_name_as_structured() -> None:
    # Proves (C6.1-CR1-2): `mean_seconds_by_route` is keyed by route, so a baseline written when the route was
    # called "jsonld" must land under "structured" with the runs that say so, or a cost comparison across the
    # rename splits into two rows. The records are written by `record()` in the stored (old) shape.
    old = record(source="jsonld", seconds=10.0)
    new = record(source="structured", seconds=20.0)
    cost = aggregate_scores.aggregate([old, new], {})["cost"]["mean_seconds_by_route"]
    assert cost == {"structured": 15.0}


# ---------------------------------------------------------------------------
# C7 (docs/dev/implementations/c7-pipeline-eval.md, Step 2): `stopped` (C7-D8, C5-F14) and the confidence self-check (C7-PR1-4)
# ---------------------------------------------------------------------------


def test_an_error_on_an_attempt_failed_for_low_confidence_is_silent_and_stopped() -> None:
    # Proves (C7-D8): a forced run fails every model-judged attempt for low confidence, which is no finding, so the error below is
    # "silent" (no finding covers it) yet the attempt did stop it: `stopped` counts errors on an attempt that failed for any reason.
    # The same error on a passed attempt is silent and not stopped. Worked from the two records.
    def wrong_attempt(verdict: str) -> dict[str, Any]:
        a = attempt(1, "initial")
        a["score"]["items"] = [{"kind": "acts_wrong", "date": "2026-10-20", "index": 0, "field": None}]
        a["verdict"], a["reasons"] = verdict, (["low_confidence"] if verdict == "failed" else [])
        return a

    failed = aggregate_scores.aggregate([record(attempts=[wrong_attempt("failed")])], {})["validation"]
    passed = aggregate_scores.aggregate([record(attempts=[wrong_attempt("passed")])], {})["validation"]
    assert (failed["silent"], failed["stopped"]) == (1, 1)
    assert (passed["silent"], passed["stopped"]) == (1, 0)


def test_the_confidence_self_check_counts_only_where_a_confidence_was_recorded() -> None:
    # Proves (C7-PR1-4): the recomputed confidence is compared with `AttemptRecord.confidence` only where the record holds one. A
    # rescored file has none (the staging document does not carry it), and counting those would report a drift that is not there.
    agree = attempt(1, "initial", confidence=0.9, recorded_confidence=0.9)
    drift = attempt(1, "initial", confidence=0.8, recorded_confidence=0.9)
    rescored = attempt(1, "initial", confidence=0.9)
    validation = aggregate_scores.aggregate([record(attempts=[a]) for a in (agree, drift, rescored)], {})["validation"]
    assert validation["confidence_disagree"] == 1


def test_a_confidence_recorded_as_none_is_still_compared() -> None:
    # Proves (C7-CR1-7): a fresh run's attempt always carries `recorded_confidence` (None on the structured route, where production
    # records no confidence), so None there is a recorded value and a recompute that gives a number is a drift. Only an attempt
    # with no `recorded_confidence` key at all (a file recorded before C7, rescored) is skipped.
    drift = attempt(1, "initial", confidence=0.9, recorded_confidence=None)
    agree = attempt(1, "initial", confidence=None, recorded_confidence=None)
    validation = aggregate_scores.aggregate([record(attempts=[a]) for a in (drift, agree)], {})["validation"]
    assert validation["confidence_disagree"] == 1
