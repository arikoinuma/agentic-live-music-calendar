"""Tests for `agent_worker/policy.py`: the verdict, the router's decision, and what a retry changes.

Milestone A3 (docs/dev/implementations/a3-validation-and-retry.md, §1, §3, §4). These pin the decisions
that sit between the evidence (validation.py) and the graph (graph.py), as pure functions with no graph, no
model and no database. They stand in for the build plan's A7 item "unit tests for the routing function",
pulled forward because tests come first.

How to read it: verdict precedence (Gap D) -> the route table (Gap D) -> the route fallback rule ->
the retry hints -> the attempt plans (Gap E). Every expected value is a literal whose source is the
plan section named in the test: the precedence is plan §1, the cap of 3 is arch-initial.md §7, the tier
order is §3. Nothing is read from the code under test.
"""

from dataclasses import replace

import pytest

from agent_worker import extraction
from agent_worker.constants import NodeNames, NodeOutcomes
from agent_worker.policy import (
    DEFAULT_POLICY,
    AttemptRecord,
    RetryPolicy,
    combine,
    decide_route,
    plan_for_attempt,
    retry_hint,
    route_falls_back,
)
from agent_worker.validation import (
    CheckCode,
    FailureReason,
    Finding,
    PageOutcome,
    Severity,
    ValidationResult,
    Verdict,
)
from app.config import settings

BASE_CONFIG = extraction.PIPELINE_CONFIG
BASE_OPTIONS = extraction.PIPELINE_OPTIONS
POLICY = RetryPolicy(confidence_threshold=0.8, max_attempts=3, escalation_model="gemma-big")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def error(code: CheckCode, message: str = "an error") -> Finding:
    """An error-severity finding on show 0."""
    return Finding(code, Severity.ERROR, message, 0)


def evidence(
    *, outcome: PageOutcome | None = PageOutcome.HAS_SHOWS, errors: tuple[Finding, ...] = (),
    confidence: float | None = 0.95, extraction_failed: bool = False,
) -> ValidationResult:
    """A `ValidationResult` as `validate_extraction` would hand it to `combine`: an outcome, the given errors and confidence."""
    return ValidationResult(
        outcome=outcome, findings=list(errors), confidence=confidence, extraction_failed=extraction_failed,
    )


def record(
    attempt: int = 1, *, route: str | None = "model", verdict: Verdict = Verdict.FAILED,
    reasons: tuple[FailureReason, ...] = (FailureReason.CHECK_ERRORS,), findings: tuple[Finding, ...] = (),
) -> AttemptRecord:
    """An `AttemptRecord` for a failed attempt on the given route with the given reasons and findings; every other field is filler."""
    return AttemptRecord(
        attempt=attempt, tier="initial", model="m", route=route,  # type: ignore[arg-type]
        error=None, verdict=verdict, reasons=list(reasons), findings=list(findings),
        confidence=None, error_count=len(findings), warning_count=0,
    )


DATE = error(CheckCode.DATE_IMPLAUSIBLE, "show 0 is dated 2026-03-01, which is not plausible")
CONSISTENCY = error(CheckCode.FREE_WITH_PRICE, "show 1 is marked free but also has an admission price")
DROPPED = error(CheckCode.SPLITTER_DROPPED, "the act splitter returned no answer for listing 3")


# ---------------------------------------------------------------------------
# The verdict (Gap D)
# ---------------------------------------------------------------------------


def test_a_clean_record_passes() -> None:
    # Proves (Gap D): no errors, good confidence -> PASSED with no reasons.
    result = combine(evidence(), POLICY)
    assert result.verdict is Verdict.PASSED and result.reasons == []


def test_a_confirmed_empty_page_is_a_pass_with_its_own_verdict() -> None:
    # Proves (Gap D, G3): confirmed-empty is a *legitimate pass* (the venue lists nothing), and keeps
    # its own verdict so A5 can treat it with the care an empty list needs.
    result = combine(evidence(outcome=PageOutcome.CONFIRMED_EMPTY, confidence=None), POLICY)
    assert result.verdict is Verdict.CONFIRMED_EMPTY and result.reasons == []


def test_a_check_error_fails_a_record_whatever_the_confidence() -> None:
    # Proves (Gap D): a deterministic error is a fact about the record; a model that is 0.99 sure of a
    # wrong date is still wrong. Confidence does not outvote it (plan §1: evidence kinds don't mix).
    result = combine(evidence(errors=(DATE,), confidence=0.99), POLICY)
    assert result.verdict is Verdict.FAILED and result.reasons == [FailureReason.CHECK_ERRORS]


def test_low_confidence_fails_a_record_with_nothing_else_wrong() -> None:
    # Proves (Gap D): the threshold is the policy's (0.8 here), inclusive on the passing side.
    low = combine(evidence(confidence=0.79), POLICY)
    edge = combine(evidence(confidence=0.8), POLICY)
    assert low.verdict is Verdict.FAILED and low.reasons == [FailureReason.LOW_CONFIDENCE]
    assert edge.verdict is Verdict.PASSED


def test_the_threshold_is_read_from_the_policy_not_a_literal() -> None:
    # Proves (Gap D): "named configuration, so A8 can vary it" — the same 0.7 passes at 0.6 and fails at 0.9.
    assert combine(evidence(confidence=0.7), replace(POLICY, confidence_threshold=0.6)).verdict is Verdict.PASSED
    assert combine(evidence(confidence=0.7), replace(POLICY, confidence_threshold=0.9)).verdict is Verdict.FAILED


def test_no_confidence_is_no_evidence_not_zero() -> None:
    # Proves (Gap D, G6): None means "no model judged this" (the JSON-LD route, an all-excluded
    # page). It must not raise and must not fail the record — comparing None to a float was G6's bug.
    assert combine(evidence(confidence=None), POLICY).verdict is Verdict.PASSED


def test_a_failed_model_call_fails_with_its_own_reason() -> None:
    # Proves (Gap D, G2): an attempt whose model call raised arrives as `extraction_failed` and fails
    # with that reason, which the existing retry edge then handles.
    result = combine(ValidationResult.for_failed_extraction(), POLICY)
    assert result.verdict is Verdict.FAILED and result.reasons == [FailureReason.EXTRACT_FAILED]


def test_an_unreadable_page_fails() -> None:
    # Proves (Gap D, G3): unreadable is a failure worth a retry, even with a good confidence.
    result = combine(evidence(outcome=PageOutcome.UNREADABLE, confidence=0.99), POLICY)
    assert result.verdict is Verdict.FAILED and result.reasons == [FailureReason.UNREADABLE]


def test_every_applicable_reason_is_kept_strongest_first() -> None:
    # Proves (Gap D): the reasons list keeps *all* that apply, in the order of FailureReason
    # (plan §1: extraction failed -> unreadable -> check errors -> low confidence), so the retry
    # hint and the audit trail can say why.
    result = combine(evidence(outcome=PageOutcome.UNREADABLE, errors=(DATE,), confidence=0.2), POLICY)
    assert result.reasons == [FailureReason.UNREADABLE, FailureReason.CHECK_ERRORS, FailureReason.LOW_CONFIDENCE]


def test_an_empty_escalation_model_name_means_none_configured() -> None:
    # Proves (code review round 1, #3): `ESCALATION_MODEL_NAME=` left empty is read as "", which must not
    # make the audit record claim a larger model ran. Normalised to None when the policy is built.
    assert RetryPolicy(escalation_model="").escalation_model is None
    assert RetryPolicy(escalation_model="gemma-big").escalation_model == "gemma-big"


def test_default_policy_matches_the_documented_numbers() -> None:
    # Proves: 0.8 (the literal the old router used) and 3 attempts (arch-initial.md §7: "Retries are
    # capped (3 attempts)"), and that the escalation model is read from settings, so setting the
    # env var changes tier 3.
    assert RetryPolicy().confidence_threshold == 0.8 and RetryPolicy().max_attempts == 3
    assert DEFAULT_POLICY.escalation_model == settings.escalation_model_name


# ---------------------------------------------------------------------------
# The route (Gap D)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attempt_count", [1, 2, 3])
@pytest.mark.parametrize("verdict", [Verdict.PASSED, Verdict.CONFIRMED_EMPTY])
def test_a_passing_verdict_passes_at_every_attempt(verdict: Verdict, attempt_count: int) -> None:
    # Proves (Gap D): a pass is a pass whichever attempt it came on.
    assert decide_route(verdict, attempt_count, POLICY) is NodeOutcomes.PASS


@pytest.mark.parametrize(("attempt_count", "expected"), [
    (1, NodeOutcomes.RETRY), (2, NodeOutcomes.RETRY), (3, NodeOutcomes.ESCALATE), (4, NodeOutcomes.ESCALATE),
])
def test_a_failed_verdict_retries_until_the_cap_then_escalates(attempt_count: int, expected: NodeOutcomes) -> None:
    # Proves (Gap D): three attempts in total (arch-initial.md §7). Failed after the 1st and 2nd -> retry;
    # failed after the 3rd -> escalate.
    assert decide_route(Verdict.FAILED, attempt_count, POLICY) is expected


@pytest.mark.parametrize(("attempt_count", "expected"), [
    (4, NodeOutcomes.RETRY), (5, NodeOutcomes.ESCALATE),
])
def test_the_attempt_cap_is_read_from_the_policy_not_a_literal(attempt_count: int, expected: NodeOutcomes) -> None:
    # Proves (Gap D): "named configuration, so A8 can vary it" — with a cap of 5, attempt 4 still retries.
    assert decide_route(Verdict.FAILED, attempt_count, replace(POLICY, max_attempts=5)) is expected


@pytest.mark.parametrize("verdict", list(Verdict))
@pytest.mark.parametrize("attempt_count", [1, 2, 3, 4])
def test_the_router_returns_node_outcomes_members_only(verdict: Verdict, attempt_count: int) -> None:
    # Proves (Gap D, G6): the result is a NodeOutcomes, not a NodeNames that merely equals one — the old
    # router returned NodeNames.ESCALATE, which "works" only because two StrEnums share the string
    # "escalate". `==` can't tell them apart, so this checks the type.
    result = decide_route(verdict, attempt_count, POLICY)
    assert type(result) is NodeOutcomes
    assert type(result) is not type(NodeNames.ESCALATE)


def test_routing_before_validation_has_run_is_an_error_not_a_route() -> None:
    # Proves: a missing verdict means the graph was wired wrong; failing loudly beats routing it somewhere.
    with pytest.raises(ValueError, match="verdict"):
        decide_route(None, 1, POLICY)


# ---------------------------------------------------------------------------
# When the JSON-LD route gives up on itself
# ---------------------------------------------------------------------------


def test_a_failed_json_ld_attempt_falls_back_unless_the_failure_was_only_about_acts() -> None:
    # Proves (plan §2, round 2 #3): on the JSON-LD route the page hint has no consumer, so only a failure
    # that is solely about acts (and reaches the splitter's hint) is worth retrying there. Anything else
    # repeats byte for byte, so the next attempt reads the page text with the model route.
    assert route_falls_back(record(route="jsonld", findings=(DATE,)))
    assert route_falls_back(record(route="jsonld", findings=(CONSISTENCY,)))
    assert route_falls_back(record(route="jsonld", reasons=(FailureReason.EXTRACT_FAILED,)))  # a malformed date
    assert route_falls_back(record(route="jsonld", findings=(DROPPED, CONSISTENCY)))
    assert not route_falls_back(record(route="jsonld", findings=(DROPPED,)))


def test_only_a_failed_json_ld_attempt_falls_back() -> None:
    # Proves: the model route, the image route, and a JSON-LD attempt that passed never trigger it.
    assert not route_falls_back(record(route="model", findings=(DATE,)))
    assert not route_falls_back(record(route="image", findings=(DATE,)))
    assert not route_falls_back(record(route="jsonld", verdict=Verdict.PASSED, reasons=()))


# ---------------------------------------------------------------------------
# The retry hints
# ---------------------------------------------------------------------------


def test_a_date_problem_reaches_the_page_model_and_not_the_splitter() -> None:
    # Proves (round 1 #5): each finding goes to the call that produces the field. A date sentence sent
    # to the act splitter can't help and perturbs the call A2.1 found most sensitive.
    page_hint, splitter_hint = retry_hint([record(findings=(DATE,))])
    assert "2026-03-01" in page_hint and splitter_hint == ""


def test_a_dropped_listing_reaches_the_splitter_and_not_the_page_model() -> None:
    # Proves (round 1 #5): the reverse.
    page_hint, splitter_hint = retry_hint([record(findings=(DROPPED,))])
    assert "listing 3" in splitter_hint and page_hint == ""


def test_the_hint_is_empty_with_no_history_and_carries_every_attempts_findings() -> None:
    # Proves (round 2 #6): no history leaves the request untouched, and tier 3's hint is the union of
    # earlier attempts' findings, so attempt 1's reason isn't lost when attempt 2 failed for another.
    assert retry_hint([]) == ("", "")
    page_hint, _ = retry_hint([record(1, findings=(DATE,)), record(2, findings=(CONSISTENCY,))])
    assert "2026-03-01" in page_hint and "marked free" in page_hint


def test_a_repeated_finding_appears_once() -> None:
    # Proves: de-duplicated, so a failure that repeated on every attempt doesn't pad the prompt.
    page_hint, _ = retry_hint([record(1, findings=(DATE,)), record(2, findings=(DATE,))])
    assert page_hint.count("2026-03-01") == 1


def test_a_failed_model_call_and_low_confidence_get_a_generic_page_hint() -> None:
    # Proves: reasons with no finding (extract_failed, unreadable, low_confidence) still tell the page
    # model something, since at temperature 0 an unchanged request returns the same answer.
    page_hint, splitter_hint = retry_hint([record(reasons=(FailureReason.EXTRACT_FAILED, FailureReason.LOW_CONFIDENCE))])
    assert "valid JSON" in page_hint and "confidence" in page_hint.lower() and splitter_hint == ""


# ---------------------------------------------------------------------------
# What each attempt changes (Gap E)
# ---------------------------------------------------------------------------


def plan(attempt: int, history: list[AttemptRecord], policy: RetryPolicy = POLICY):  # type: ignore[no-untyped-def]
    return plan_for_attempt(attempt, policy, history, BASE_CONFIG, BASE_OPTIONS)


def test_the_first_attempt_is_the_pipeline_exactly() -> None:
    # Proves: attempt 1 changes nothing — the adopted configuration and options, no hint — so the
    # request is the one that scored 56/60 in A2.1.
    first = plan(1, [])
    assert first.tier == "initial" and first.config == BASE_CONFIG and first.options == BASE_OPTIONS


def test_the_second_attempt_narrows_with_a_hint_and_keeps_the_model() -> None:
    # Proves (Gap E, arch-initial.md §7): "narrow the task or address the specific ambiguity in the
    # prompt first" — the hint names what failed — and the larger model comes *second*, not here.
    second = plan(2, [record(findings=(DATE,))])
    assert second.tier == "narrowed" and "2026-03-01" in second.config.retry_hint
    assert second.config.splitter_hint == ""
    assert second.options.model == BASE_OPTIONS.model and not second.larger_model_used


def test_the_third_attempt_uses_the_larger_model_when_one_is_configured() -> None:
    # Proves (Gap E): "larger model second" — tier 3 swaps the model and says it did.
    third = plan(3, [record(1, findings=(DATE,)), record(2, findings=(CONSISTENCY,))])
    assert third.tier == "larger_model" and third.larger_model_used
    assert third.options.model == "gemma-big"
    assert "2026-03-01" in third.config.retry_hint and "marked free" in third.config.retry_hint


def test_the_third_attempt_with_an_empty_larger_model_name_says_it_did_not_escalate() -> None:
    # Proves (Gap E; code review round 1, #3): an empty name is "no larger model", so the record says
    # `larger_model_used` is False and the base model runs.
    third = plan(3, [record(1, findings=(DATE,)), record(2, findings=(DATE,))], RetryPolicy(escalation_model=""))
    assert not third.larger_model_used and third.options.model == BASE_OPTIONS.model


def test_the_third_attempt_without_a_larger_model_says_it_did_not_escalate() -> None:
    # Proves (Gap E, D5): on a laptop with no larger model tier 3 still runs, with the full hint, on the
    # same model, and the record must not claim a larger model ran (A8 would misreport).
    history = [record(1, findings=(DATE,)), record(2, findings=(DATE,))]
    third = plan(3, history, replace(POLICY, escalation_model=None))
    assert third.tier == "larger_model" and not third.larger_model_used
    assert third.options.model == BASE_OPTIONS.model


def test_the_last_attempt_differs_from_the_one_before_it_even_when_the_same_check_failed_twice() -> None:
    # Proves (Gap E; found by test_graph's different-request test): when attempt 2 fails the same check as
    # attempt 1, the union of findings is the SAME text, so without a sentence of its own attempt 3 on a
    # machine with no larger model is byte-identical to attempt 2 — an identical retry, which at
    # temperature 0 returns the identical answer. The last attempt adds its own conservative sentence.
    history = [record(1, findings=(DATE,)), record(2, findings=(DATE,))]
    no_larger_model = replace(POLICY, escalation_model=None)
    second = plan_for_attempt(2, no_larger_model, history[:1], BASE_CONFIG, BASE_OPTIONS)
    third = plan_for_attempt(3, no_larger_model, history, BASE_CONFIG, BASE_OPTIONS)
    assert third.config != second.config and third.options == second.options
    assert "last attempt" in third.config.retry_hint and "last attempt" not in second.config.retry_hint
    assert "last attempt" in third.config.splitter_hint  # both calls get it, so a JSON-LD page's splitter does too


def test_the_final_sentence_is_added_only_when_asked_for() -> None:
    # Proves: `retry_hint(history)` stays empty with no history (the first attempt's request is untouched)
    # and only `final=True` adds the last-attempt sentences.
    assert retry_hint([]) == ("", "")
    page_hint, splitter_hint = retry_hint([], final=True)
    assert "leave it null" in page_hint and "never add a name" in splitter_hint


def test_a_failed_json_ld_attempt_sends_the_next_attempt_to_the_model_route() -> None:
    # Proves (Gap E, round 1 #2): the route changes along with the hint when the JSON-LD route can't help.
    second = plan(2, [record(route="jsonld", findings=(DATE,))])
    assert second.config.route == "model"


def test_a_failed_model_route_attempt_keeps_the_configured_route() -> None:
    # Proves: the fallback is only for the JSON-LD route.
    assert plan(2, [record(route="model", findings=(DATE,))]).config.route == BASE_CONFIG.route


def test_the_route_fallback_is_sticky_across_later_failures() -> None:
    # Proves (Gap E, round 1 #1): attempt 1 failed on the JSON-LD route, attempt 2 (on the model route)
    # failed for a different reason; attempt 3 must stay on the model route. Decided from the previous
    # attempt only, it would go back to the JSON-LD route that already under-reported.
    history = [
        record(1, route="jsonld", findings=(error(CheckCode.JSONLD_UNDER_REPORTED),)),
        record(2, route="model", reasons=(FailureReason.LOW_CONFIDENCE,)),
    ]
    assert plan(3, history).config.route == "model"


def test_a_failure_about_acts_only_keeps_the_json_ld_route_and_hints_the_splitter() -> None:
    # Proves (Gap E): the splitter's hint has a consumer on the JSON-LD route, so a splitter-only failure
    # retries there — with the splitter hint set and the page hint empty.
    second = plan(2, [record(route="jsonld", findings=(DROPPED,))])
    assert second.config.route == BASE_CONFIG.route
    assert "listing 3" in second.config.splitter_hint and second.config.retry_hint == ""


def test_a_retry_always_differs_from_the_first_attempt() -> None:
    # Proves (Gap E): the whole point — at temperature 0 an identical retry returns the identical
    # answer, so attempts 2 and 3 must differ from attempt 1 in what they send, for every kind of failure.
    for history in (
        [record(findings=(DATE,))], [record(reasons=(FailureReason.LOW_CONFIDENCE,))],
        [record(reasons=(FailureReason.EXTRACT_FAILED,))], [record(reasons=(FailureReason.UNREADABLE,))],
        [record(route="jsonld", findings=(CONSISTENCY,))],
    ):
        second = plan(2, history)
        assert second.config != BASE_CONFIG, history
