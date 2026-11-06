"""Tests for the act-in-title measurement (`run_eval.act_title_check`).

Milestone C6, Step 10 (docs/dev/implementations/c6-hosted-inference.md, C6-D6). `validation.check_act_in_title`
(A2.1-E3) warns when an act name is not found in the verbatim title it was split from. C6-D6 asks how many of
the splitter's labeled mistakes that check would catch before it is promoted from a warning to an error.
`run_eval` runs no validation, so `act_title_check` replays the check over a saved results file.

How to read it: each test builds a tiny results file by hand and works out the expected counts from the case,
not from the function. A run's shows line up with its `notes["titles"]` by position only when the counts
match, which is the only case where "this show's title" is known; any other run is skipped and counted.
"""

from typing import Any

from agent_worker.model_eval import run_eval


def show(*names: str, date: str = "2026-10-10") -> dict[str, Any]:
    """One stored show, with just the fields the check reads."""
    return {
        "venue": "V",
        "date": date,
        "acts": [{"name": n} for n in names],
        "is_ambiguous": False,
        "confidence": 1.0,
    }


def run(titles: list[str], shows: list[dict[str, Any]], errors: list[str] | None = None) -> dict[str, Any]:
    """One stored run: the titles the splitter was given, the shows it produced, and the label errors scored."""
    return {
        "outcome": "ok",
        "notes": {"titles": titles},
        "extraction": {"shows": shows},
        "label_score": {"errors": errors or []},
    }


def test_a_typo_in_an_act_is_caught_and_counted_against_its_label_error() -> None:
    # Proves: an act the splitter mistyped ("Devilsoundguy" for a title that says "Evilsoundguy", the A3-CR1-9
    # case) produces one finding, and because the label scorer also reported "acts wrong" on that date it is
    # counted as caught. Expected: 1 finding, 1 label error, 1 caught, 0 false alarms.
    results = {
        "runs": [
            run(
                ["Evilsoundguy"],
                [show("Devilsoundguy")],
                ["acts wrong 2026-10-10: ['Devilsoundguy'] vs ['Evilsoundguy']"],
            )
        ]
    }
    out = run_eval.act_title_check(results)
    assert (out["flagged"], out["label_errors"], out["caught"], out["false_alarms"]) == (1, 1, 1, 0)


def test_a_convention_error_is_not_caught_because_the_name_is_in_the_title() -> None:
    # Proves: a wrong act that IS a substring of its title (an event name kept as an act) passes the check, so
    # it counts as a label error the check missed. This is the limit C6-D6 needs a number for: the check sees
    # typos and inventions, not convention mistakes. Expected: 0 findings, 1 label error, 0 caught.
    results = {
        "runs": [
            run(["Spring Bash with The Moths"], [show("Spring Bash", "The Moths")], ["acts wrong 2026-10-10: x vs y"])
        ]
    }
    out = run_eval.act_title_check(results)
    assert (out["flagged"], out["label_errors"], out["caught"]) == (0, 1, 0)


def test_a_finding_on_a_correctly_labeled_show_is_a_false_alarm() -> None:
    # Proves: a finding on a date the labels scored as correct is counted as a false alarm. This is what
    # stops C6-D6 promoting a check that would retry correct pages. Expected: 1 finding, 0 label errors, 1 false alarm.
    results = {"runs": [run(["Lent w. Gills"], [show("Gills Band")])]}
    out = run_eval.act_title_check(results)
    assert (out["flagged"], out["label_errors"], out["false_alarms"]) == (1, 0, 1)


def test_a_run_whose_titles_do_not_line_up_with_its_shows_is_skipped_and_counted() -> None:
    # Proves: when the title count differs from the show count (a title with no acts is dropped, or the model
    # route has no titles) there is no safe way to say which title a show came from, so the run is skipped
    # rather than guessed at. Expected: 1 skipped, 0 checked.
    results = {"runs": [run(["A", "B"], [show("A")])]}
    out = run_eval.act_title_check(results)
    assert (out["runs_checked"], out["runs_skipped"]) == (0, 1)


# ---------------------------------------------------------------------------
# --concurrency (C6 Step 11): runs in parallel, results in the order they were asked for
# ---------------------------------------------------------------------------


def test_map_runs_returns_results_in_submission_order_whatever_finishes_first() -> None:
    # Proves: with several worker threads, `map_runs` still returns each job's result in the order the jobs
    # were given, even when a later job finishes first. The saved results file and its gate lines list runs
    # in fixture/run order, so a reordering would change what a diff of two result files shows. The earlier
    # job sleeps longer so that a naive "append as finished" version would fail.
    import time

    def work(job: int) -> int:
        time.sleep(0.05 if job == 0 else 0)
        return job * 10

    assert run_eval.map_runs(work, [0, 1, 2, 3], concurrency=4) == [0, 10, 20, 30]


def test_map_runs_with_one_worker_runs_in_the_calling_thread() -> None:
    # Proves: concurrency 1 (the default) does not create threads, so a sequential run behaves exactly as it did
    # before the option existed. Expected: every job saw the calling thread's id.
    import threading

    def work(job: int) -> int:
        return threading.get_ident()

    assert set(run_eval.map_runs(work, [1, 2], concurrency=1)) == {threading.get_ident()}
