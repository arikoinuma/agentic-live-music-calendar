"""Tests for the policy questions (`model_eval/saved_run_reports/policy_questions.py`): confidence against correctness, the threshold
sweep, and what a retry changed.

Milestone C7 (docs/dev/implementations/c7-pipeline-eval.md, Test approach §1 to §3). The module reads run records only, so every test
builds them by hand: attempts, confidences and the scorer's error items written in the test, with the answer that follows from them.
No test computes its expectation with the function it tests; where an expectation comes from a definition, the comment quotes it
from the plan's "The readings" section.

How to read it: the helpers first (`item`, `attempt_dict`, `run`), then one section per question. The rows marked C7-K1, C7-K2 and
C7-K3 test the three judgements at the heart of the module (which shows confidence is judged on, what another threshold would have
done, and when two attempts share an error).
"""

import dataclasses
from dataclasses import replace
from typing import Any

import pytest

from agent_worker.model_eval import scoring
from agent_worker.model_eval.saved_run_reports import policy_questions as pq
from agent_worker.model_eval.scoring import ErrorItem
from agent_worker.policy import DEFAULT_POLICY, combine
from agent_worker.tests.model_eval.test_aggregate_scores import GATED, score_dict
from agent_worker.validation import (
    CheckCode,
    FailureReason,
    Finding,
    PageOutcome,
    Severity,
    ValidationResult,
    Verdict,
)

INFORMATIONAL = dataclasses.replace(GATED, gated=False)


def item(kind: str, date: str | None = "2026-11-13", index: int | None = None, field: str | None = None) -> ErrorItem:
    """One scorer error item, as `scoring.ErrorItem` records it."""
    return ErrorItem(kind, date, index, field)


def attempt_dict(
    n: int = 1, *, route: str = "model", items: list[ErrorItem] | None = None, confidences: list[float | None] | None = None,
    judged: list[int] | None = None, excluded: list[int] | None = None, reasons: list[str] | None = None,
    confidence: float | None = None, score: dict[str, Any] | None = None, larger: bool = False, seconds: float | None = None,
    tokens: dict[str, int] | None = None, tier: str | None = None,
) -> dict[str, Any]:
    """One attempt as a results file stores it (`asdict(AttemptResult)`), with only the fields a test pins filled in."""
    confidences = confidences if confidences is not None else []
    stored = score if score is not None else score_dict()
    stored["items"] = [dataclasses.asdict(i) for i in (items or [])]
    return {
        "attempt": n, "tier": tier or {1: "initial", 2: "narrowed", 3: "larger_model"}.get(n, "larger_model"), "route": route,
        "model": "m", "larger_model_used": larger, "error": None, "verdict": "failed" if reasons else "passed",
        "reasons": reasons or [], "score": stored, "errors": [], "warnings": [], "recorded_errors": [],
        "confidence": confidence, "show_confidences": confidences,
        "judged_indices": judged if judged is not None else list(range(len(confidences))),
        "excluded_indices": excluded or [], "recorded_confidence": None, "seconds": seconds, "tokens": tokens,
    }


def run(fixture: str, attempts: list[dict[str, Any]], *, n: int = 0, escalation_model: str | None = None) -> dict[str, Any]:
    """A run record with the given attempts; `policy` carries the escalation model the report groups by."""
    return {
        "fixture": fixture, "run": n, "source": attempts[0]["route"], "attempts": attempts, "attempt_count": len(attempts),
        "policy": {"confidence_threshold": 0.8, "max_attempts": 3, "escalation_model": escalation_model},
    }


def errors_on(count: int, date_prefix: str = "2026-11-") -> list[ErrorItem]:
    """`count` wrong-acts errors on distinct dates, for tests that only need an error count."""
    return [item("acts_wrong", f"{date_prefix}{d:02d}") for d in range(1, count + 1)]


# ---------------------------------------------------------------------------
# §1 Confidence against correctness (C7-Q4; C7-K1, then the buckets and C7-R1)
# ---------------------------------------------------------------------------


def test_confidence_rows_are_the_judged_shows_and_only_errors_make_a_row_wrong() -> None:
    # Proves (C7-K1, C7-M1): the plan's §1 first row. Confidences 1.0, 0.9, 0.9, 0.5, 1.0 at indexes 0 to 4; show 3 was excluded
    # for no acts, so judged are 0, 1, 2, 4. `acts_wrong` at 1 makes that row wrong; `field_missing` at 2 does not (a missing field
    # is tolerated, A2.1-D1); the `missed` items, one at the excluded index 3 and one with no index, give no row. Expected rows are
    # read off that list.
    rows = pq.confidence_rows(
        "model", [1.0, 0.9, 0.9, 0.5, 1.0], [0, 1, 2, 4],
        [item("acts_wrong", index=1), item("field_missing", index=2, field="time"), item("missed", index=3), item("missed", index=None)],
    )
    assert rows == [(1.0, True), (0.9, False), (0.9, True), (1.0, True)]


def test_an_excluded_low_confidence_show_gives_no_row() -> None:
    # Proves (C7-K1, C7-M2, C7-PR1-1): the real 7th St Entry shape (C7-F3). Show 2 is a no-acts listing at 0.5 that no label expects,
    # so it has no error item at all; validation excluded it, so it never reached the record's confidence. Scoring it as a "correct"
    # 0.5 would fill the lowest bucket with shows the pipeline discards and invert C7-Q4. Expected: only shows 0 and 1.
    rows = pq.confidence_rows("model", [0.9, 1.0, 0.5], [0, 1], [])
    assert rows == [(0.9, True), (1.0, True)]


def test_a_status_merge_placeholder_gives_no_row() -> None:
    # Proves (C7-K1): a show the status merge added (`notes["added_indices"]`) carries a placeholder 1.0 that
    # `validation.aggregate_confidence` skips, so the harness leaves it out of `judged_indices` and C7-K1 gives it no row.
    rows = pq.confidence_rows("model", [0.9, 1.0], [0], [])
    assert rows == [(0.9, True)]


@pytest.mark.parametrize("kind", ["fabricated", "leak", "field_wrong", "image_wrong", "acts_wrong"])
def test_each_wrong_kind_makes_its_show_wrong(kind: str) -> None:
    # Proves (C7-K1): "a wrong show" in the plan's definitions is wrong acts, invented, a leak, a wrong field or image. A leak counts
    # here although the gate tolerates one a page: the question is whether THIS row is right as written.
    assert pq.confidence_rows("model", [0.9], [0], [item(kind, index=0)]) == [(0.9, False)]


@pytest.mark.parametrize("route", ["structured", "jsonld"])
def test_structured_route_shows_give_no_rows(route: str) -> None:
    # Proves (C7-K1, C7-M2, C7-PR1-3): the structured route stamps 1.0 on every show as a placeholder (`extraction._from_structured`)
    # and `aggregate_confidence` returns None for it. A file written before C6.1 stores the route as "jsonld", which C7-K1 reads through
    # `policy.stored_route`. Expected: no rows from either spelling.
    assert pq.confidence_rows(route, [1.0, 1.0], [0, 1], [item("acts_wrong", index=0)]) == []


def test_image_route_shows_give_rows() -> None:
    # Proves (C7-K1): a poster's confidence is the model's own, like the model route's.
    assert pq.confidence_rows("image", [0.8], [0], []) == [(0.8, True)]


def test_buckets_count_per_confidence_value_in_total_and_per_venue() -> None:
    # Proves: the bucket table C7-R1 reads. Rows from two venues: venue a has 12 at 0.9 (3 wrong) and 2 at 1.0 (0 wrong); venue b
    # has 10 at 1.0 (1 wrong). So 0.9 holds 12 (rate 0.25, compared), 1.0 holds 12 (rate 1/12, compared); with min_size 13 neither is
    # compared but both are shown. Worked from the rows.
    rows = {"a": [(0.9, False)] * 3 + [(0.9, True)] * 9 + [(1.0, True)] * 2, "b": [(1.0, False)] + [(1.0, True)] * 9}
    out = pq.buckets(rows)
    assert [(b.confidence, b.count, b.wrong, b.compared) for b in out] == [(0.9, 12, 3, True), (1.0, 12, 1, True)]
    assert out[0].wrong_rate == 0.25
    assert out[1].by_venue == {"a": (2, 0), "b": (10, 1)}
    assert [b.compared for b in pq.buckets(rows, min_size=13)] == [False, False]


def test_r1_needs_twenty_wrong_rows_outside_the_largest_venue() -> None:
    # Proves: C7-R1's "not enough evidence" when fewer than 20 wrong instances come from venues other than the largest contributor.
    # Icehouse holds 98 wrong rows at 1.0, Turf Club 2 at 0.9: only 2 outside Icehouse. This is the shape the saved hosted runs have
    # (C7-F4, C7-D9).
    rows = {"icehouse": [(1.0, False)] * 98 + [(1.0, True)] * 157, "turf": [(0.9, False)] * 2 + [(0.9, True)] * 15}
    verdict, _why = pq.r1_verdict(rows)
    assert verdict == "not enough evidence"


def test_r1_needs_two_compared_buckets() -> None:
    # Proves: C7-R1's other "not enough evidence": a single confidence value (or only one bucket of 10 or more) cannot show a slope.
    rows = {"a": [(1.0, False)] * 30 + [(1.0, True)] * 30, "b": [(1.0, False)] * 30 + [(0.5, True)] * 3}
    assert pq.r1_verdict(rows)[0] == "not enough evidence"


def two_buckets(low_wrong: int, high_wrong: int) -> list[tuple[float, bool]]:
    """One venue's rows: 20 at 0.5 with `low_wrong` wrong, and 20 at 1.0 with `high_wrong` wrong."""
    return (
        [(0.5, False)] * low_wrong + [(0.5, True)] * (20 - low_wrong)
        + [(1.0, False)] * high_wrong + [(1.0, True)] * (20 - high_wrong)
    )


def test_r1_reads_yes_only_when_the_low_bucket_is_twice_as_wrong_on_two_venues() -> None:
    # Proves: C7-R1's "yes". On each of three venues 0.5 is wrong 12 times in 20 and 1.0 four times in 20 (0.6 against 0.2, three
    # times as wrong); each venue has 16 wrong rows, so 32 come from outside whichever is "largest" (at least 20 needed). Then a
    # pattern where the slope holds on ONE venue only and the pooled slope fails (28/60 against 20/60, under twice) reads "no".
    assert pq.r1_verdict({v: two_buckets(12, 4) for v in "abc"})[0] == "yes"
    assert pq.r1_verdict({"a": two_buckets(12, 4), "b": two_buckets(8, 8), "c": two_buckets(8, 8)})[0] == "no"


def test_r1_reads_no_when_flat_or_inverted() -> None:
    # Proves: C7-R1's "no". Both buckets wrong 8 in 20 on every venue (flat), then the high bucket worse (2 against 14, inverted).
    assert pq.r1_verdict({v: two_buckets(8, 8) for v in "abc"})[0] == "no"
    assert pq.r1_verdict({v: two_buckets(2, 14) for v in "abc"})[0] == "no"


def test_rows_by_venue_reads_attempt_one_of_each_run_and_maps_fixtures_to_venues() -> None:
    # Proves (C7-K1 through the records): Q4 is read on attempt 1, the request production sends first. A forced attempt 2 at 0.5
    # (wrong) is not read. Expected: venue v's one row from attempt 1.
    records = [run("gated.html", [
        attempt_dict(1, confidences=[0.9], items=[]),
        attempt_dict(2, confidences=[0.5], items=[item("acts_wrong", index=0)]),
    ])]
    assert pq.rows_by_venue(records, {"gated.html": GATED}) == {"v": [(0.9, True)]}


def test_excluded_confidences_are_reported_apart_and_split_by_whether_the_exclusion_was_right() -> None:
    # Proves (C7-F3): where the model's low values actually go. Show 1 (0.5) was excluded and no label expected it: a correct
    # exclusion. Show 2 (0.8) was excluded and the scorer reports a labeled show `missed` at that index: a wrong one. Show 3 is a
    # status-merge placeholder (not judged, not excluded): not counted. Structured-route attempts give nothing.
    records = [
        run("gated.html", [attempt_dict(
            confidences=[0.9, 0.5, 0.8, 1.0], judged=[0], excluded=[1, 2], items=[item("missed", index=2)],
        )]),
        run("s.html", [attempt_dict(route="structured", confidences=[1.0], judged=[], excluded=[0])]),
    ]
    assert pq.excluded_confidences(records) == {0.5: {"correct": 1, "missed": 0}, 0.8: {"correct": 0, "missed": 1}}


def test_an_older_file_without_confidences_reads_as_not_recorded() -> None:
    # Proves: a results file written before C7 has no `show_confidences`; the section must say so instead of reporting zero rows.
    old = run("gated.html", [attempt_dict()])
    for key in ("show_confidences", "judged_indices", "excluded_indices", "confidence"):
        del old["attempts"][0][key]
    assert pq.confidence_recorded([old]) is False
    assert pq.confidence_recorded([run("gated.html", [attempt_dict(confidences=[0.9])])]) is True


# ---------------------------------------------------------------------------
# §2 The threshold sweep (C7-Q1; C7-K2)
# ---------------------------------------------------------------------------

PASSES = scoring.PageScore.from_dict(score_dict(labelled=2, returned=2))
FAILS = scoring.PageScore.from_dict(score_dict(labelled=2, returned=2, acts_wrong=1))


@pytest.mark.parametrize(("reasons", "confidence", "score", "at_095", "at_08"), [
    ([], 0.9, FAILS, "caught", "missed"),
    ([], 0.9, PASSES, "false_alarm", "quiet"),
    ([], None, FAILS, "missed", "missed"),
    (["check_errors"], 1.0, FAILS, "caught", "caught"),
    ([], 0.5, PASSES, "false_alarm", "false_alarm"),
])
def test_sweep_cells(reasons: list[str], confidence: float | None, score: scoring.PageScore, at_095: str, at_08: str) -> None:
    # Proves (C7-K2): the plan's §2 table. "Would retry" = failed for a reason other than low confidence, or confidence under t
    # (None never fails, A3-K4); "should retry" = attempt 1 fails the standard. The cells at t = 0.95 and t = 0.8 are worked by hand.
    assert pq.sweep_cell(reasons, confidence, score, 0.95) == at_095
    assert pq.sweep_cell(reasons, confidence, score, 0.8) == at_08


def test_sweep_should_retry_is_the_scorers_own_gate() -> None:
    # Proves (C7-K2, C7-PR1-2): "should retry" is `scoring.gate` on attempt 1, so the standard is not re-coded. Two leaks fail
    # (more than one a page); one leak alone passes; one wrong time fails (a wrong field, never allowed). A confidence of 1.0 and no
    # reasons make "would" false, so the cell is "missed" exactly when the gate fails.
    two_leaks = scoring.PageScore.from_dict(score_dict(labelled=2, returned=4, leaks=2))
    one_leak = scoring.PageScore.from_dict(score_dict(labelled=2, returned=3, leaks=1))
    wrong_time = scoring.PageScore.from_dict(score_dict(labelled=2, returned=2))
    wrong_time.fields["time"].wrong = 1
    assert [pq.sweep_cell([], 1.0, s, 0.8) for s in (two_leaks, one_leak, wrong_time)] == ["missed", "quiet", "missed"]


def test_sweep_recomputes_low_confidence_at_each_threshold() -> None:
    # Proves (C7-K2, C7-M4): the stored `low_confidence` reason says what 0.8 did; the sweep asks what ANOTHER threshold would have
    # done. A record failed at 0.8 only for low confidence (confidence 0.79) is quiet at t = 0.5 on a passing page.
    assert pq.would_fail(["low_confidence"], 0.79, 0.5) is False
    assert pq.sweep_cell(["low_confidence"], 0.79, PASSES, 0.5) == "quiet"


def _result(errors: bool, failed: bool, unreadable: bool, confidence: float | None) -> ValidationResult:
    """A `ValidationResult` with the given evidence, for the mirror test."""
    if failed:
        return ValidationResult.for_failed_extraction()
    findings = [Finding(CheckCode.FREE_WITH_PRICE, Severity.ERROR, "m", 0)] if errors else []
    outcome = PageOutcome.UNREADABLE if unreadable else PageOutcome.HAS_SHOWS
    return ValidationResult(outcome=outcome, findings=findings, confidence=confidence)


@pytest.mark.parametrize("errors", [False, True])
@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("unreadable", [False, True])
@pytest.mark.parametrize("confidence", [None, 0.79, 0.8, 0.81])
@pytest.mark.parametrize("t", [0.5, 0.8, 0.81, 1.01])
def test_sweep_mirror_agrees_with_combine(errors: bool, failed: bool, unreadable: bool, confidence: float | None, t: float) -> None:
    # Proves (C7-K2, C7-M3, C7-PR1-5): `would_fail` mirrors `policy.combine`, the production rule. The reasons `combine` gives at
    # threshold 0 never include low confidence (nothing is under 0), which is what a stored record looks like once that reason is set
    # aside; `would_fail` must then agree with `combine` at threshold t on every row. A `<=` in the mirror fails at confidence 0.8 and
    # t = 0.8.
    result = _result(errors, failed, unreadable, confidence)
    reasons = [r.value for r in combine(result, replace(DEFAULT_POLICY, confidence_threshold=0)).reasons]
    expected = combine(result, replace(DEFAULT_POLICY, confidence_threshold=t)).verdict is Verdict.FAILED
    assert pq.would_fail(reasons, result.confidence, t) is expected
    assert FailureReason.LOW_CONFIDENCE.value not in reasons


def test_the_sweep_keeps_gated_and_informational_pages_apart() -> None:
    # Proves (C7-K2 through the records; A2.1-D2): informational pages never gate, so their cells are counted on their own line.
    # Gated: attempt 1 at 0.9 with a wrong-acts error. Informational: the same. At t = 0.95 both are "caught", each in its own line.
    wrong = score_dict(labelled=1, returned=1, acts_wrong=1)
    records = [
        run("gated.html", [attempt_dict(confidence=0.9, score=dict(wrong))]),
        run("info.html", [attempt_dict(confidence=0.9, score=dict(wrong))]),
    ]
    out = pq.sweep(records, {"gated.html": GATED, "info.html": INFORMATIONAL}, thresholds=(0.95,))
    assert out["gated"][0.95]["caught"] == 1 and out["informational"][0.95]["caught"] == 1
    assert sum(out["gated"][0.95].values()) == 1


# ---------------------------------------------------------------------------
# §3 What a retry changed (C7-Q3, C7-Q2; C7-K3, the noise band, C7-R3 and C7-R4)
# ---------------------------------------------------------------------------


def test_transition_matches_errors_by_kind_date_and_field_not_index() -> None:
    # Proves (C7-K3, C7-M5): the plan's §3 first row. Attempt 1: acts wrong on the 13th and the 14th, missed the 20th. Attempt 2: acts
    # wrong on the 14th at a different index, and an invented show on the 22nd. Fixed 2 (the 13th, the 20th), introduced 1 (the 22nd),
    # kept 1 (the 14th, although its index moved).
    first = [item("acts_wrong", "2026-11-13", 3), item("acts_wrong", "2026-11-14", 4), item("missed", "2026-11-20")]
    second = [item("acts_wrong", "2026-11-14", 2), item("fabricated", "2026-11-22", 7)]
    assert pq.transition(first, second) == pq.Transition(fixed=2, introduced=1, kept=1)


def test_transition_is_a_multiset() -> None:
    # Proves (C7-K3, C7-M6): two shows on one date both wrong, then one of them fixed. A set would collapse the two into one error
    # and report nothing fixed.
    first = [item("acts_wrong", "2026-11-13", 0), item("acts_wrong", "2026-11-13", 1)]
    assert pq.transition(first, [item("acts_wrong", "2026-11-13", 0)]) == pq.Transition(fixed=1, introduced=0, kept=1)


def test_transition_ignores_missing_fields_and_counts_a_new_wrong_field() -> None:
    # Proves (C7-K3, C7-PR1-2): the error-count definition is every kind but `field_missing`; a retry that makes a time wrong hurt.
    first = [item("field_missing", field="time")]
    second = [item("field_missing", field="time"), item("field_wrong", field="time")]
    assert pq.transition(first, second) == pq.Transition(fixed=0, introduced=1, kept=0)


def test_churn_between_runs_is_the_mean_over_pairs() -> None:
    # Proves (C7-K3 between runs): three runs of one page, attempt 1 each, with errors A; A; A and B. Pairs (1,2) 0, (1,3) 1, (2,3) 1:
    # churn (0 + 1 + 1) / 3. It describes how much a resample moves (a hosted retry is also a resample).
    a, b = item("acts_wrong", "2026-11-13"), item("missed", "2026-11-14")
    records = [run("p.html", [attempt_dict(items=its)], n=i) for i, its in enumerate([[a], [a], [a, b]])]
    assert pq.churn(records) == {"p.html": pytest.approx(2 / 3)}


def test_error_count_is_every_kind_but_field_missing() -> None:
    # Proves: the plan's error-count definition, used by the noise band and C7-R3 (a plain count, not one of the three judgements).
    assert pq.error_count([item("missed"), item("leak"), item("field_missing"), item("field_wrong")]) == 3


def test_the_noise_band_and_the_per_page_rule() -> None:
    # Proves: C7-R3's per-page rule, worked from the plan's §3 numbers. Attempt-1 error counts 20, 18, 19, 21, 20: mean 19.6,
    # population sd sqrt(((0.4)^2 + (1.6)^2 + (0.6)^2 + (1.4)^2 + (0.4)^2) / 5) = sqrt(1.04) = 1.0198. Attempt-2 counts 19, 18, 20, 20,
    # 19 (mean 19.2, 0.4 lower): inside the band, so neither. Attempt-2 counts 17 each (mean 17, 2.6 lower): helps. 22 each: hurts.
    def page(second: list[int]) -> list[dict[str, Any]]:
        return [
            run("p.html", [attempt_dict(1, items=errors_on(a)), attempt_dict(2, items=errors_on(b))], n=i)
            for i, (a, b) in enumerate(zip([20, 18, 19, 21, 20], second, strict=True))
        ]

    assert pq.noise_band(page([0] * 5)) == {"p.html": pytest.approx(1.0198, abs=1e-4)}
    assert pq.page_effects(page([19, 18, 20, 20, 19]), 1, 2) == {"p.html": "neither"}
    assert pq.page_effects(page([17] * 5), 1, 2) == {"p.html": "helps"}
    assert pq.page_effects(page([22] * 5), 1, 2) == {"p.html": "hurts"}


def test_a_page_without_the_later_attempt_has_no_effect() -> None:
    # Proves: a structured page passes attempt 1 even in a forced run (C7-D3), so it has no attempt 2 and is not counted for or
    # against a tier.
    assert pq.page_effects([run("s.html", [attempt_dict(route="structured")])], 1, 2) == {}


def test_a_tier_helps_only_on_two_pages_and_hurting_on_none() -> None:
    # Proves: C7-R3's verdict over pages. One page helped is not enough (Icehouse cannot carry it alone, C7-PR1-10); two helped and
    # one hurt is not either; two helped and the rest neither is "helps".
    assert pq.tier_verdict({"icehouse": "helps", "turf": "neither"}) == "does not help"
    assert pq.tier_verdict({"a": "helps", "b": "helps", "c": "hurts"}) == "does not help"
    assert pq.tier_verdict({"a": "helps", "b": "helps", "c": "neither"}) == "helps"


def test_r4_keeps_three_unless_attempt_three_only_hurts() -> None:
    # Proves: C7-R4. Hurts on a page and helps on none: recommend 2 (the last attempt is pure cost). Helps on two pages: recommend 4.
    # Anything else: keep 3.
    assert pq.r4_verdict({"a": "hurts", "b": "neither"}).startswith("2")
    assert pq.r4_verdict({"a": "helps", "b": "helps"}).startswith("4")
    assert pq.r4_verdict({"a": "helps", "b": "neither"}).startswith("keep 3")
    assert pq.r4_verdict({}).startswith("keep 3")


def test_escalation_effects_compare_attempt_three_with_and_without_the_larger_model() -> None:
    # Proves: C7-R3's last clause, the escalated tier must beat the unescalated one by the same rule. Unescalated attempt 3 has 10
    # errors in every run (band 0 from attempt 1's constant 10); escalated attempt 3 has 8: helps on that page.
    def runs(third: int, model: str | None) -> list[dict[str, Any]]:
        return [run("p.html", [attempt_dict(1, items=errors_on(10)), attempt_dict(2, items=errors_on(10)),
                               attempt_dict(3, items=errors_on(third), larger=model is not None)], n=i, escalation_model=model)
                for i in range(3)]

    assert pq.escalation_effects(runs(10, None), runs(8, "big")) == {"p.html": "helps"}


def test_retry_effect_reports_each_transition_with_seconds_and_tokens() -> None:
    # Proves (C7-K3 through the records; C7-R3, C7-R4): one forced run, attempts initial, narrowed, larger_model (the larger model
    # used). 1 to 2 fixes the 13th; 2 to 3 introduces the 15th. Seconds and tokens are the later attempt's own. Expected rows are read
    # off the attempts.
    a, b, c = item("acts_wrong", "2026-11-13"), item("acts_wrong", "2026-11-14"), item("acts_wrong", "2026-11-15")
    records = [run("p.html", [
        attempt_dict(1, items=[a, b], seconds=10.0, tokens={"prompt": 100, "completion": 10}),
        attempt_dict(2, items=[b], seconds=12.0, tokens={"prompt": 120, "completion": 12}),
        attempt_dict(3, items=[b, c], seconds=20.0, tokens=None, larger=True),
    ])]
    rows = {r["transition"]: r for r in pq.retry_effect(records)}
    assert set(rows) == {"1 to 2", "2 to 3 (larger model)"}
    assert (rows["1 to 2"]["fixed"], rows["1 to 2"]["introduced"], rows["1 to 2"]["kept"]) == (1, 0, 1)
    assert rows["1 to 2"]["mean_seconds"] == 12.0 and rows["1 to 2"]["tokens"] == {"prompt": 120, "completion": 12}
    assert (rows["2 to 3 (larger model)"]["fixed"], rows["2 to 3 (larger model)"]["introduced"]) == (0, 1)
    assert rows["2 to 3 (larger model)"]["tokens"] is None  # no attempt in the row carried usage: unknown, never 0


def test_labels_map_fixtures_and_unknown_fixtures_are_skipped() -> None:
    # Proves: a run whose page is no longer in the labels is left out of the per-venue tables (it has no venue to count under).
    records = [run("gone.html", [attempt_dict(confidences=[0.9])])]
    assert pq.rows_by_venue(records, {}) == {}


# ---------------------------------------------------------------------------
# Code review round 1 (C7-CR1-1, C7-CR1-2, C7-CR1-4)
# ---------------------------------------------------------------------------


def two_attempt_runs(first: list[int], second: list[int | None]) -> list[dict[str, Any]]:
    """Runs of one page with the given attempt-1 and attempt-2 error counts; None means the run stopped after attempt 1."""
    return [
        run("p.html", [attempt_dict(1, items=errors_on(a)), *([attempt_dict(2, items=errors_on(b))] if b is not None else [])], n=i)
        for i, (a, b) in enumerate(zip(first, second, strict=True))
    ]


def test_a_quiet_page_needs_more_than_one_runs_flip_to_count() -> None:
    # Proves (C7-CR1-1): a page whose attempt 1 gives the same count in every run has a noise band of exactly 0, and without a floor
    # one run differing by one error (a mean move of 0.2 over five runs) would read as "helps" or "hurts", and one such flip would
    # disqualify a tier (R3's "hurts on none"). The floor is `MIN_EFFECT` (0.5 errors a run): one flip is "neither", a move of three
    # errors over five runs (0.6) counts. Expected values worked from the counts.
    assert pq.noise_band(two_attempt_runs([1] * 5, [1, 1, 1, 1, 0])) == {"p.html": 0.0}
    assert pq.page_effects(two_attempt_runs([1] * 5, [1, 1, 1, 1, 0]), 1, 2) == {"p.html": "neither"}
    assert pq.page_effects(two_attempt_runs([0] * 5, [0, 0, 0, 0, 1]), 1, 2) == {"p.html": "neither"}
    assert pq.page_effects(two_attempt_runs([0] * 5, [1, 1, 1, 0, 0]), 1, 2) == {"p.html": "hurts"}
    assert pq.MIN_EFFECT == 0.5


def test_an_attempt_is_compared_with_attempt_one_of_the_same_runs() -> None:
    # Proves (C7-CR1-2): the before-mean is taken over the runs that also reached the later attempt, so runs that stopped early do
    # not change the comparison. Four runs pass attempt 1 with 0 errors and stop; one run has 5 errors at attempts 1 and 2. Over the
    # same run, 5 against 5 is "neither"; comparing attempt 2 with attempt 1 over ALL runs (mean 1.0) would read "hurts" (4 over a
    # band of 2.0).
    assert pq.page_effects(two_attempt_runs([0, 0, 0, 0, 5], [None, None, None, None, 5]), 1, 2) == {"p.html": "neither"}


def test_the_sweep_puts_structured_route_pages_on_their_own_line() -> None:
    # Proves (C7-CR1-4): a structured page has no confidence (None never fails), so no threshold can catch its errors; counted with
    # the model-judged pages it would read as "the threshold missed these". It goes to its own line, whatever its gating.
    wrong = score_dict(labelled=1, returned=1, acts_wrong=1)
    records = [run("gated.html", [attempt_dict(route="structured", confidence=None, score=dict(wrong))])]
    out = pq.sweep(records, {"gated.html": GATED}, thresholds=(0.95,))
    assert out["structured"][0.95]["missed"] == 1 and sum(out["gated"][0.95].values()) == 0
