"""Tests for the reusable results report (`model_eval/saved_run_reports/markdown_report.py`, `run_labelled_pages --report`).

Milestone C5 follow-up (docs/dev/evaluating-model-performance.md). Reading a results file used to mean writing a throwaway script
each time; the report is that script, written once and run on any label, so the same questions get asked of the local model, of the
hosted model in C6, and of every later run (`--compare` then lines the labels up). It is a pure function from the stored file to
Markdown, so it is tested on small hand-built files.

How to read it: `make_results` builds a results dict the way `run_labelled_pages.evaluate` stores one (reusing the record helpers of
test_aggregate_scores.py); each test then pins one section of the report. Expected text is what the section is specified to show, worked
from the hand-built counts, never from the report's own output.
"""

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from agent_worker.model_eval import labels
from agent_worker.model_eval.labelled_page_runs import run_labelled_pages
from agent_worker.model_eval.labels import LabelledShow, PageLabel
from agent_worker.model_eval.saved_run_reports import (
    aggregate_scores,
    markdown_report,
    results_file,
)
from agent_worker.tests.model_eval.test_aggregate_scores import (
    FINDING,
    GATED,
    D,
    attempt,
    record,
    score_dict,
)

INFORMATIONAL = dataclasses.replace(GATED, gated=False)
LABELS = {"gated.html": GATED, "info.html": INFORMATIONAL}


def make_results(runs: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    """A results dict shaped like the one `evaluate` writes, with the aggregate computed from the runs by the real code."""
    return {
        "label": "demo", "started_at": "2026-11-04T17:00:00+00:00", "set": "all", "scenario": None, "labels_sha": "abcdef0123456789",
        "held_out_scored": False, "harness_commit": "0123456789abcdef", "request_options": {"model": "gemma-test"},
        "policy": {"confidence_threshold": 0.8, "max_attempts": 3},
        "provenance": {"gemma-test": {"model_digest": "deadbeefcafe", "ollama_version": "0.99"}},
        "request": {"instruction": "long prompt text", "instruction_sha": "1234abcd56", "response_schema_sha": "9999aaaa00", "response_schema_chars": 4000},
        "aggregate": aggregate_scores.aggregate(runs, LABELS), "scenarios": [], "runs": runs, **extra,
    }


def clean_and_bad() -> list[dict[str, Any]]:
    """Two runs: a gated page with one wrong-acts error nobody noticed, and an informational page that was retried, got worse, and escalated."""
    bad = score_dict(labelled=4, returned=4, acts_wrong=1)
    bad["items"] = [{"kind": "acts_wrong", "date": "2026-10-20", "index": 0, "field": None}]
    retried = [
        attempt(1, "initial", missed=0, errors=[]),
        attempt(2, "narrowed", missed=0, errors=[]),
        attempt(3, "larger_model", missed=0, errors=[]),
    ]
    for a, state in zip(retried, ("failed", "failed", "failed"), strict=True):
        a["verdict"], a["reasons"] = state, ["low_confidence"]
    return [
        record("gated.html", raw_score=bad, validated_score=bad, committed_score=bad, seconds=12.3),
        record("info.html", attempts=retried, escalated=True, seconds=99.9),
    ]


def test_the_header_names_what_produced_the_numbers() -> None:
    # Proves: a report says which labels, policy and model it came from, because a number without them cannot be compared with
    # another run's (the local baseline against the hosted one, C6). Expected: the values written into the hand-built file.
    text = markdown_report.render(make_results(clean_and_bad()), LABELS)
    for needle in ("demo", "abcdef0123", "0123456789", "gemma-test", "deadbeefcafe", "0.8", "held-out scored: no", "prompt sha: 1234abcd"):
        assert needle in text, needle


def test_the_headline_table_has_one_row_per_column() -> None:
    # Proves: raw, validated and committed each get a row of recall, precision and gate, so which layer helped or hurt is one glance.
    # Expected: the gated page (4 labelled, 1 wrong-acts) puts the gate at FAIL in every column.
    text = markdown_report.render(make_results(clean_and_bad()), LABELS)
    for column in ("raw", "validated", "committed"):
        assert f"| {column} |" in text
    assert text.count("FAIL") >= 3


def test_every_page_gets_a_row_with_its_counts_and_its_gating() -> None:
    # Proves: the per-page table that used to be a hand-written script. Gated pages are marked G and informational ones i; the counts
    # are missed/wrong/invented/leaks; attempts, escalation and seconds are beside them. Expected: the values of the two records.
    text = markdown_report.render(make_results(clean_and_bad()), LABELS)
    gated_row = next(line for line in text.splitlines() if "gated.html" in line and "|" in line)
    info_row = next(line for line in text.splitlines() if "info.html" in line and "|" in line)
    assert "| G |" in gated_row and "0/1/0/0" in gated_row and "12.3" in gated_row
    assert "| i |" in info_row and "yes" in info_row and "99.9" in info_row


def test_validation_recall_is_shown_by_error_kind_with_its_caveat() -> None:
    # Proves: the by-kind table (caught / flagged / silent) and the reading note. When pages were retried, an attempt failed for low
    # confidence is not a finding, so the note says the silent count can include errors that a retry did stop; without it the number
    # is misread (the retry baseline's "51 silent"). Expected: the one wrong-acts error is silent.
    text = markdown_report.render(make_results(clean_and_bad()), LABELS)
    assert "acts_wrong" in text and "silent" in text
    assert "low confidence is a verdict reason, not a finding" in text


def test_the_retry_section_lists_each_attempt_of_a_retried_page() -> None:
    # Proves: the attempt table that answers "did the retry fix anything": tier, verdict, reason and errors for every attempt of every
    # page that needed more than one, so a retry that made things worse is visible. Expected: info.html's three failed attempts.
    text = markdown_report.render(make_results(clean_and_bad()), LABELS)
    assert "info.html" in text and "larger_model" in text and "low_confidence" in text
    assert "escalated" in text


def test_a_single_attempt_page_is_not_listed_in_the_retry_section() -> None:
    # Proves: the retry section stays short: only pages that needed more than one attempt appear in it.
    text = markdown_report.render(make_results([record("gated.html")]), LABELS)
    assert "No page needed a second attempt" in text


def test_scenarios_report_the_database_score_and_a_changed_extraction() -> None:
    # Proves: scenario results are readable without a script: the pages, each run's reconcile counts, the database score against what
    # a perfect pipeline would leave, and the model-changed line when run 2 read the page differently. Expected: the hand-built values.
    scenario = {
        "pages": ["a.html", "b.html"], "database_score": score_dict(labelled=23, returned=22, missed=1),
        "result": {
            "scenario": "sequence", "not_run": None, "model_changed": True,
            "count_differences": ["the model extracted 10 shows on run 1 and 11 on run 2 (skipped 0 then 0), so run 2's counts reflect a changed extraction, not reconcile"],
            "runs": [{**record("a.html"), "reconcile_counts": {"insert": 12}}, {**record("b.html"), "reconcile_counts": {"insert": 10}}],
        },
    }
    text = markdown_report.render(make_results([record("a.html")], scenarios=[scenario]), LABELS)
    assert "sequence" in text and "a.html" in text and "b.html" in text
    assert "labelled 23, returned 22, missed 1" in text
    assert "10 shows on run 1 and 11 on run 2" in text


def test_a_scenario_that_was_not_run_says_why() -> None:
    # Proves: a scenario whose first run left nothing to build on is reported with its reason, not silently absent.
    scenario = {"pages": ["a.html"], "database_score": None, "result": {
        "scenario": "perturbed", "not_run": "the perturbed scenario needs at least two active shows", "model_changed": False,
        "count_differences": [], "runs": [{**record("a.html"), "reconcile_counts": None}]}}
    text = markdown_report.render(make_results([record("a.html")], scenarios=[scenario]), LABELS)
    assert "NOT RUN" in text and "at least two active shows" in text


def test_errors_are_listed_in_full_only_when_asked() -> None:
    # Proves: `--errors` adds each run's error strings, untruncated. A long line must reach the file whole: a very long error line was
    # once mangled by a terminal's wrapping when copied. Without the flag the report stays short.
    long_error = "acts wrong 2026-11-28: " + ", ".join(f"Act Number {i}" for i in range(60))
    runs = clean_and_bad()
    runs[0]["raw_score"]["errors"] = [long_error]
    data = make_results(runs)
    assert long_error in markdown_report.render(data, LABELS, show_errors=True)
    assert long_error not in markdown_report.render(data, LABELS, show_errors=False)


def test_a_page_missing_from_the_labels_is_still_reported() -> None:
    # Proves: a results file from before a label was renamed still renders; the page is marked "?" for gating instead of crashing.
    text = markdown_report.render(make_results(clean_and_bad()), {})
    assert "| ? |" in text


def test_the_command_line_prints_or_writes_the_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # Proves: `--report LABEL` reads graph-<LABEL>.json and prints it; `--out FILE` writes it instead, which is how a long report gets
    # into the plan's log without a terminal in between.
    monkeypatch.setattr(results_file, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(labels, "PAGE_LABELS", LABELS)
    monkeypatch.setattr(run_labelled_pages, "PAGE_LABELS", LABELS)
    (tmp_path / "graph-demo.json").write_text(json.dumps(make_results(clean_and_bad())))
    assert run_labelled_pages.main(["--report", "demo"]) == 0
    assert "# Report: demo" in capsys.readouterr().out
    target = tmp_path / "out.md"
    assert run_labelled_pages.main(["--report", "demo", "--out", str(target)]) == 0
    assert "# Report: demo" in target.read_text()


@pytest.mark.parametrize(("argv", "expected"), [
    (["--report", "x"], {"report": "x", "errors": False, "out": None}),
    (["--report", "x", "--errors", "--out", "r.md"], {"errors": True, "out": "r.md"}),
])
def test_the_report_flags(argv: list[str], expected: dict[str, Any]) -> None:
    # Proves: the flags parse to the values the report reads.
    args = vars(run_labelled_pages.parse_args(argv))
    for key, value in expected.items():
        assert args[key] == value


def test_a_results_file_from_an_older_harness_still_renders() -> None:
    # Proves: the report reads any file the harness has written. Fields added later (the recompute self-checks `findings_disagree`
    # and `route_mismatches`) are absent from older files; they print as n/a instead of raising, so last week's baseline can be
    # compared with today's.
    data = make_results(clean_and_bad())
    del data["aggregate"]["validation"]["route_mismatches"]
    del data["aggregate"]["validation"]["findings_disagree"]
    assert "route_mismatches n/a" in markdown_report.render(data, LABELS)


def test_repeatability_is_reported_when_a_page_was_run_more_than_once() -> None:
    # Proves: the model is not repeatable at temperature 0 (the baseline's finding), so whenever a page has two or more runs the
    # report says whether they agreed. Expected: two runs with different extractions are DIFFERENT, two equal ones identical, and a
    # page run once is not mentioned (nothing to compare).
    same = {"shows": [{"date": "2026-10-20"}]}
    runs = [
        record("gated.html", run=0, raw=same), record("gated.html", run=1, raw={"shows": []}),
        record("info.html", run=0, raw=same), record("info.html", run=1, raw=same),
    ]
    text = markdown_report.render(make_results(runs), LABELS)
    assert "gated.html: DIFFERENT across 2 runs" in text
    assert "info.html: identical across 2 runs" in text
    assert "Repeatability" not in markdown_report.render(make_results([record("gated.html")]), LABELS)


def fields_file() -> dict[str, Any]:
    """A results file whose raw column has one field inside the standard, one over the missing limit and one with a wrong value."""
    score = score_dict(labelled=10, returned=10)
    score["fields"]["time"] = {"stated": 80, "correct": 78, "missing": 2, "wrong": 0}
    score["fields"]["end_time"] = {"stated": 25, "correct": 20, "missing": 5, "wrong": 0}
    score["fields"]["admission_day"] = {"stated": 12, "correct": 11, "missing": 0, "wrong": 1}
    score["fields"]["image_url"] = {"stated": 0, "correct": 40, "missing": 0, "wrong": 0}
    return make_results([record("gated.html", raw_score=score, validated_score=score, committed_score=score)])


def test_the_fields_table_applies_the_standard_to_every_field() -> None:
    # Proves: field-level accuracy, the last "done when" item of C5, is printed and judged by Ari's standard (A2.1-D1): other fields
    # may be missing at most 10% of the values the page states, and a wrong value is never allowed. Expected, worked from the
    # hand-built tallies: time 2 of 80 missing = 2.5% (ok); end_time 5 of 25 = 20% (over the limit); admission_day has one wrong
    # value (WRONG, whatever the missing rate); image_url states nothing to be missing, 40 correct (ok).
    text = markdown_report.render(fields_file(), LABELS)
    rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line.startswith("| ") and "|" in line}
    assert "2.5%" in rows["time"] and rows["time"].rstrip().endswith("ok |")
    assert "20.0%" in rows["end_time"] and "over 10% missing" in rows["end_time"]
    assert "WRONG" in rows["admission_day"]
    assert rows["image_url"].rstrip().endswith("ok |")


def test_the_fields_table_says_what_it_sums_over() -> None:
    # Proves: the tallies are summed over every run in the file (a RUNS=3 file counts each page three times), and the table says so,
    # so a reader does not mistake the counts for a single run's.
    assert "summed over all 3 runs" in markdown_report.render(
        make_results([record("gated.html", run=i) for i in range(3)]), LABELS,
    )


# keep names imported for the helper signatures above
_ = (D, LabelledShow, PageLabel, FINDING)


# ---------------------------------------------------------------------------
# Code review round 2 (C5-CR2-6): the console views of an aggregate
# ---------------------------------------------------------------------------


def test_the_comparison_table_lines_runs_up_in_the_order_given() -> None:
    # Proves: `compare_table` prints one column per run in the order the labels were given, with the same rows for each, so two
    # runs can be read down a row. Expected text is the specified layout: a 26-wide row name, then 22-wide cells.
    runs = clean_and_bad()
    first, second = make_results(runs, labels_sha="1111111111aaaa"), make_results(runs, labels_sha="2222222222bbbb")
    lines = markdown_report.compare_table({"one": first, "two": second}).split("\n")
    assert lines[0] == "".ljust(26) + "one".ljust(22) + "two".ljust(22)
    assert lines[1] == "labels_sha".ljust(26) + "1111111111".ljust(22) + "2222222222".ljust(22)
    assert [line.split()[0] for line in lines[3:6]] == ["raw:", "raw:", "raw:"]
    assert lines[-1].startswith("validation recall")


def test_the_closing_summary_has_a_line_per_column_and_the_retry_loop() -> None:
    # Proves: `summary` is what a finished run prints: recall, precision and the gate for raw, validated and committed, then the
    # retry rate, escalations and validation recall. Checked against the aggregate's own numbers, formatted to three places.
    aggregate = make_results(clean_and_bad())["aggregate"]
    lines = markdown_report.summary(aggregate).split("\n")
    assert len(lines) == 4
    for line, column in zip(lines, ("raw", "validated", "committed"), strict=False):
        rates = aggregate["columns"][column]["rates"]
        assert line.startswith(f"{column:10} recall {rates['recall']:.3f}  precision {rates['precision']:.3f}  gate ")
    assert lines[3].startswith(f"retry rate {aggregate['retry']['retry_rate']:.3f}; escalated {aggregate['retry']['escalated']}; ")


def test_the_missing_value_limit_is_the_standards_not_a_second_copy() -> None:
    # Proves: C5-CR2-7. The report's "over 10% missing" verdict follows `scoring.MISSING_TOLERANCE`, so changing the standard
    # moves the gate and the report together.
    from agent_worker.model_eval import scoring

    assert markdown_report.MISSING_LIMIT == scoring.MISSING_TOLERANCE
