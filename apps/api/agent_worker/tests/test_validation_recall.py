"""Tests for validation recall: of the errors the labels reveal, which did validation catch (C5-K4).

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, Test approach §4). An extraction error is `caught` when an
ERROR-severity finding covers it (that is what fails the record and triggers a retry, A3-K4), `flagged` when only a warning does
(recorded, changes nothing), and `silent` when nothing does.

How to read it: the first section tests `coverage` on constructed `(ErrorItem, [Finding])` pairs, because the definition is what
is under test; the expected class is the definition in the plan's C5-K4 block, worked by hand from each case. Those tests stay
red until Ari fills the `TODO(Ari)` in `validation_recall.coverage`. The second section tests the recomputation of an
attempt's findings against a real graph run on a scripted model (green: no gap involved).
"""

import datetime
from pathlib import Path
from typing import Any

import pytest

from agent_worker.eval import validation_recall as recall
from agent_worker.eval.labels import LabelledShow, PageLabel
from agent_worker.eval.scoring import ErrorItem
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    SPLITTER,
    event,
    jsonld_page,
    split_answer,
)
from agent_worker.tests.test_graph_run import run_scripted
from agent_worker.validation import CheckCode, Finding, Severity

# ---------------------------------------------------------------------------
# C5-K4: when does a finding cover an error (red until Ari fills coverage)
# ---------------------------------------------------------------------------


def finding(code: CheckCode, severity: Severity, index: int | None) -> Finding:
    """A finding as validation produces it; the message is irrelevant to coverage."""
    return Finding(code, severity, "a message", index)


def test_coverage_an_error_finding_on_the_same_show_is_a_catch() -> None:
    # Proves: C5-K4. An acts-wrong error on returned show 3 and an ERROR finding on show 3: validation fails the record and
    # the pipeline retries, so the error was caught. Expected class: the definition in the plan.
    error = ErrorItem("acts_wrong", "2026-10-11", 3)
    assert recall.coverage(error, [finding(CheckCode.ACT_NOT_IN_TITLE, Severity.ERROR, 3)]) is recall.Coverage.CAUGHT


def test_coverage_a_warning_alone_is_flagged_not_caught() -> None:
    # Proves: C5-K4. A warning is recorded and changes nothing (`Severity`), so "validation noticed" is not "validation
    # stopped it". The likeliest mistake is counting a warning as a catch.
    error = ErrorItem("acts_wrong", "2026-10-11", 3)
    assert recall.coverage(error, [finding(CheckCode.POSSIBLE_MERGE, Severity.WARNING, 3)]) is recall.Coverage.FLAGGED


def test_coverage_a_finding_on_another_show_does_not_cover_it() -> None:
    # Proves: C5-K4. Findings join to errors by position; one on show 4 says nothing about show 3.
    error = ErrorItem("acts_wrong", "2026-10-11", 3)
    assert recall.coverage(error, [finding(CheckCode.ACT_NOT_IN_TITLE, Severity.ERROR, 4)]) is recall.Coverage.SILENT


def test_coverage_a_page_level_error_covers_a_show_nothing_was_returned_for() -> None:
    # Proves: C5-K4. A missed show with no returned show (index None) can only be noticed by a page-level finding
    # (`show_index` None), such as the JSON-LD under-report check.
    error = ErrorItem("missed", "2026-10-11", None)
    assert recall.coverage(error, [finding(CheckCode.JSONLD_UNDER_REPORTED, Severity.ERROR, None)]) is recall.Coverage.CAUGHT


def test_coverage_a_missed_show_with_no_page_level_finding_is_silent() -> None:
    # Proves: C5-K4. Nothing at page level, nothing returned: the pipeline never knew the show existed.
    error = ErrorItem("missed", "2026-10-11", None)
    assert recall.coverage(error, [finding(CheckCode.ACT_NOT_IN_TITLE, Severity.ERROR, 3)]) is recall.Coverage.SILENT


def test_coverage_a_show_the_splitter_dropped_is_caught_by_the_finding_on_its_real_index() -> None:
    # Proves: C5-K4 and C5-PR1-2. The commonest real error: the act splitter drops a show, which stays in the dump with no
    # acts. The missed item carries that show's raw index (2), where validation put `splitter_dropped` (an error) and
    # `excluded_no_acts` (a warning). Both sit on index 2, so the error is caught.
    error = ErrorItem("missed", "2026-10-11", 2)
    findings = [
        finding(CheckCode.SPLITTER_DROPPED, Severity.ERROR, 2), finding(CheckCode.EXCLUDED_NO_ACTS, Severity.WARNING, 2),
    ]
    assert recall.coverage(error, findings) is recall.Coverage.CAUGHT


def test_coverage_a_fabricated_show_with_a_warning_is_flagged() -> None:
    # Proves: C5-K4. A fabricated show WITH acts can't carry `excluded_no_acts` (an excluded show has no acts, so the scorer
    # never counts it as fabricated); the realistic warning is `act_not_in_title`. Warning only: flagged.
    error = ErrorItem("fabricated", "2026-10-15", 5)
    assert recall.coverage(error, [finding(CheckCode.ACT_NOT_IN_TITLE, Severity.WARNING, 5)]) is recall.Coverage.FLAGGED


def test_tally_counts_each_class_and_reports_flagged_beside_caught() -> None:
    # Proves: C5-K4. Recall is caught / total errors, with flagged reported beside it and never folded in. Three errors:
    # one caught, one flagged, one silent -> recall 1/3, flagged 1, silent 1. Per error kind, so "which layer catches which
    # failure" can be read off the table.
    pairs = [
        (ErrorItem("acts_wrong", "2026-10-11", 0), [finding(CheckCode.ACT_NOT_IN_TITLE, Severity.ERROR, 0)]),
        (ErrorItem("acts_wrong", "2026-10-12", 1), [finding(CheckCode.POSSIBLE_MERGE, Severity.WARNING, 1)]),
        (ErrorItem("fabricated", "2026-10-13", 2), []),
    ]
    result = recall.tally(pairs)
    assert (result.total, result.caught, result.flagged, result.silent) == (3, 1, 1, 1)
    assert result.recall == 1 / 3
    assert result.by_kind["acts_wrong"] == {"caught": 1, "flagged": 1, "silent": 0}
    assert result.by_kind["fabricated"] == {"caught": 0, "flagged": 0, "silent": 1}


def test_tally_of_no_errors_has_a_perfect_recall_not_a_division_error() -> None:
    # Proves: no errors means nothing was missed: recall is defined (1.0), not a ZeroDivisionError. Needs no gap filled.
    result = recall.tally([])
    assert (result.total, result.recall) == (0, 1.0)


# ---------------------------------------------------------------------------
# Recomputing an attempt's findings (C5-PR1-6)
# ---------------------------------------------------------------------------

D = datetime.date
T = datetime.time
TWO_EVENTS = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"), event("Lent", "2026-10-21T21:00:00-05:00"))
LABEL = PageLabel(
    venue="test_venue", gated=True, captured_on=fakes.FETCHED, shows=(
        LabelledShow(D(2026, 10, 20), ("Nona",), "Nona", T(21, 0)), LabelledShow(D(2026, 10, 21), ("Lent",), "Lent", T(21, 0)),
    ),
)


async def test_recomputed_error_findings_equal_the_recorded_ones_on_every_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: C5-PR1-6. `AttemptRecord.findings` holds the error findings only and nothing stores an earlier attempt's
    # warnings, so the harness recomputes every attempt's findings with the pure `validate_extraction` from the staged
    # document and the fixture. This pins the equivalence: for a two-attempt run (attempt 1: the splitter drops a title,
    # attempt 2: a full answer) the recomputed errors equal the recorded ones for BOTH attempts, and attempt 1's warning
    # (`excluded_no_acts`) is the recomputed extra. If the recomputation drifted from `validate_node`, recall would be
    # measured on findings the pipeline never saw.
    dropping = split_answer(("Nona", ["Nona"]))
    full = split_answer(("Nona", ["Nona"]), ("Lent", ["Lent"]))
    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [dropping, full]})
    assert [a.attempt for a in run.attempts] == [1, 2]
    for attempt in run.attempts:
        assert attempt.errors == attempt.recorded_errors
    first = run.attempts[0]
    assert [f["code"] for f in first.errors] == [CheckCode.SPLITTER_DROPPED.value]
    assert [f["code"] for f in first.warnings] == [CheckCode.EXCLUDED_NO_ACTS.value]
    assert first.errors[0]["show_index"] == first.warnings[0]["show_index"] == 1
    assert run.attempts[1].errors == [] and run.attempts[1].warnings == []


def test_a_findings_dict_round_trips_to_a_finding() -> None:
    # Proves: the results file stores findings as plain dicts (JSON); `findings_from_dicts` turns them back into `Finding`s
    # so a --rescore can compute coverage from a stored file with no model and no fixture.
    stored: list[dict[str, Any]] = [
        {"code": "splitter_dropped", "severity": "error", "message": "m", "show_index": 1},
        {"code": "excluded_no_acts", "severity": "warning", "message": "m", "show_index": 1},
    ]
    assert recall.findings_from_dicts(stored) == [
        Finding(CheckCode.SPLITTER_DROPPED, Severity.ERROR, "m", 1),
        Finding(CheckCode.EXCLUDED_NO_ACTS, Severity.WARNING, "m", 1),
    ]
