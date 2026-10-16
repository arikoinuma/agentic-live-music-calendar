"""Tests for the retry loop through the real compiled graph, with a scripted model client.

Milestone A3 (docs/dev/implementations/a3-validation-and-retry.md, "test_graph.py"). The unit tests prove each
decision on its own; these prove the pieces are wired so that a failure becomes a retry, a retry
becomes a different request, and a cap becomes an escalation — end to end through `compiled_graph`,
with no model server and no network. The page is a file in `tmp_path` (fetch_node's local-file branch)
and the model is `fakes.ScriptedClient`, swapped in for `nodes.instructor_client`.

How to read it: each test names the situation (a model call that raises, an empty page, a bad record at
high confidence…), scripts what the model returns on each call, runs the graph, and asserts on the
state it ends in: how many attempts, which route each used, the verdict, and which node it finished at.
The finishing node is read from side effects the stub nodes leave: `reconcile_decision` is set only by
reconcile_node, `escalation_reason` only by escalate_node.

Expected values come from the plan, not from the code under test: the cap of 3 attempts is
arch-initial.md §7; which route each attempt uses is plan §2-§3; the dates are literals.
"""

from pathlib import Path
from typing import Any

import httpx
import openai
import pytest

from agent_worker import extraction, nodes
from agent_worker.graph import compiled_graph
from agent_worker.policy import RetryPolicy
from agent_worker.state import VenueGraphState
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    PAGE,
    SPLITTER,
    completions,
    event,
    jsonld_page,
    listing,
    listings_answer,
    message_text,
    scripted_client,
    split_answer,
    text_page,
)
from agent_worker.validation import FailureReason, Verdict

MODEL = extraction.PIPELINE_OPTIONS.model


def run_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, html: str | None, script: dict[Any, list[Any]],
    policy: RetryPolicy | None = None, url: str | None = None,
) -> tuple[VenueGraphState, Any]:
    """Write `html` to a file (or use `url`), swap the model for the scripted client, run the real
    graph, and return the final state and the client (for its recorded calls)."""
    if url is None:
        assert html is not None
        path = tmp_path / "page.html"
        path.write_text(html)
        url = str(path)
    client = scripted_client(script)
    monkeypatch.setattr(nodes, "instructor_client", client)
    state = VenueGraphState(
        venue_id=1, calendar_url=url, venue_name="The Venue", metro_timezone="America/Chicago",
        fetched_on=fakes.FETCHED, **({"policy": policy} if policy else {}),
    )
    return VenueGraphState(**compiled_graph.invoke(state)), client


def reached_reconcile(state: VenueGraphState) -> bool:
    """True when reconcile_node ran: it is the only node that sets `reconcile_decision`."""
    return state.reconcile_decision is not None


def reached_escalate(state: VenueGraphState) -> bool:
    """True when escalate_node ran: it is the only node that sets `escalation_reason`."""
    return state.escalation_reason is not None


GOOD_PAGE = text_page("Nona", "Oct 20", "8 pm")
GOOD_LISTING = listing("2026-10-20", "Nona", time="20:00")
NONA = split_answer(("Nona", ["Nona"]))
BAD_LISTING = listing("2026-10-20", "Nona", time="20:00", confidence=0.99, free_admission=True, admission_day=10.0)


# ---------------------------------------------------------------------------
# Every node hands the state on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("node_name", ["fetch_node", "extract_node", "validate_node", "escalate_node"])
def test_every_node_returns_the_state_it_was_given(
    node_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: a node that forgets `return state` returns None, and LangGraph then drops the node's
    # changes: the attempt count never advances and a retrying graph loops until its recursion limit
    # (10,007 steps, about a minute). It happened once, when the A3-K1 code was replaced and the line below
    # it went with it; only the whole-graph tests noticed, and they were red for other reasons at the
    # time. Calling each node directly makes the failure immediate and says what is wrong.
    path = tmp_path / "page.html"
    path.write_text(GOOD_PAGE)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({PAGE: [listings_answer(GOOD_LISTING)], SPLITTER: [NONA]}))
    state = VenueGraphState(
        venue_id=1, calendar_url=str(path), venue_name="The Venue", metro_timezone="America/Chicago",
        fetched_on=fakes.FETCHED,
    )
    # validate and escalate read what fetch and extract produce, so run the real ones first.
    for earlier in ("fetch_node", "extract_node", "validate_node", "escalate_node"):
        returned = getattr(nodes, earlier)(state)
        assert returned is state, f"{earlier} returned {returned!r}, not the state"
        if earlier == node_name:
            break


# ---------------------------------------------------------------------------
# The paths through the graph
# ---------------------------------------------------------------------------


def test_a_clean_json_ld_page_passes_on_the_first_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: the happy path on the adopted JSON-LD route — one attempt, a PASSED verdict, reconcile
    # reached, one history row. The confidence is None, not 1.0: the route stamps a placeholder that is
    # not evidence (A3-D9), and a None here must not crash the router (v0.1-G6). Only the splitter calls a model.
    page = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))
    state, client = run_graph(tmp_path, monkeypatch, page, {SPLITTER: [NONA]})
    assert state.attempt_count == 1 and len(state.attempt_history) == 1
    assert state.validation is not None and state.validation.verdict is Verdict.PASSED
    assert state.confidence is None and state.extraction_source == "jsonld"
    assert reached_reconcile(state) and not reached_escalate(state)
    assert len(completions(client).calls) == 1


def test_a_model_call_that_raises_once_is_a_recorded_failed_attempt_and_the_retry_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A3-K1, v0.1-G2): the failure Phase 5 documented (a model call that errors) no longer kills the
    # graph: attempt 1 is recorded as `extract_failed`, the existing retry edge fires, attempt 2
    # succeeds. The attempt was counted (attempt_count == 2, not 1) and attempt 1's error didn't
    # outlive it (the per-attempt reset). RED today: the exception escapes `invoke`.
    state, _ = run_graph(
        tmp_path, monkeypatch, GOOD_PAGE,
        {PAGE: [ValueError("the model server went away"), listings_answer(GOOD_LISTING)], SPLITTER: [NONA]},
    )
    assert state.attempt_count == 2
    first, second = state.attempt_history
    assert first.reasons == [FailureReason.EXTRACT_FAILED] and "went away" in (first.error or "")
    assert second.verdict is Verdict.PASSED
    assert state.extract_error is None and reached_reconcile(state)


def test_a_model_call_that_always_raises_escalates_after_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A3-K1, v0.1-G2): a real `openai` connection error on every attempt is retried to the cap (3
    # attempts, arch-initial.md §7) and then escalated, never retried forever and never crashing; the
    # escalation reason says what failed.
    boom = openai.APIConnectionError(request=httpx.Request("POST", "http://localhost:11434/v1"))
    state, client = run_graph(tmp_path, monkeypatch, GOOD_PAGE, {PAGE: [boom]})
    assert len(completions(client).calls_for(PAGE)) == 3
    assert state.attempt_count == 3 and len(state.attempt_history) == 3
    assert reached_escalate(state) and not reached_reconcile(state)
    assert "APIConnectionError" in (state.escalation_reason or "")


def test_a_page_with_nothing_listed_is_a_confirmed_empty_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (v0.1-G3): `page_readable: true, shows: []` on a page that names no dates is a legitimate
    # pass on the first attempt — it does not burn three retries and escalate, which was the bug.
    state, _ = run_graph(
        tmp_path, monkeypatch, text_page("No events scheduled right now."), {PAGE: [listings_answer()]},
    )
    assert state.attempt_count == 1
    assert state.validation is not None and state.validation.verdict is Verdict.CONFIRMED_EMPTY
    assert reached_reconcile(state)


def test_an_unreadable_page_retries_and_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (v0.1-G3): `page_readable: false` is a failure worth a retry, twice here, and the third attempt
    # (the last the cap allows) recovers.
    state, _ = run_graph(
        tmp_path, monkeypatch, GOOD_PAGE,
        {PAGE: [listings_answer(readable=False), listings_answer(readable=False), listings_answer(GOOD_LISTING)],
         SPLITTER: [NONA]},
    )
    assert [r.verdict for r in state.attempt_history] == [Verdict.FAILED, Verdict.FAILED, Verdict.PASSED]
    assert state.attempt_history[0].reasons == [FailureReason.UNREADABLE]
    assert reached_reconcile(state)


def test_a_check_error_retries_even_at_high_confidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A3-K4, end to end): free admission together with a price is a deterministic error; the
    # model's 0.99 confidence does not outvote it. Attempt 1 fails with CHECK_ERRORS (not
    # low_confidence) and the page is retried.
    state, _ = run_graph(
        tmp_path, monkeypatch, GOOD_PAGE,
        {PAGE: [listings_answer(BAD_LISTING), listings_answer(GOOD_LISTING)], SPLITTER: [NONA]},
    )
    first = state.attempt_history[0]
    assert first.confidence == pytest.approx(0.99) and first.reasons == [FailureReason.CHECK_ERRORS]
    assert state.attempt_history[1].verdict is Verdict.PASSED and reached_reconcile(state)


def test_low_confidence_on_the_model_route_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: low confidence fails a model-route record (below 0.8, plan A3-D9) when nothing deterministic
    # has, and the retry recovers.
    unsure = listing("2026-10-20", "Nona", time="20:00", confidence=0.5)
    state, _ = run_graph(
        tmp_path, monkeypatch, GOOD_PAGE, {PAGE: [listings_answer(unsure), listings_answer(GOOD_LISTING)], SPLITTER: [NONA]},
    )
    assert state.attempt_history[0].reasons == [FailureReason.LOW_CONFIDENCE]
    assert state.attempt_history[1].verdict is Verdict.PASSED


# ---------------------------------------------------------------------------
# A retry changes the request (A3-K5)
# ---------------------------------------------------------------------------


def test_a_retry_sends_a_different_request_and_the_last_one_uses_the_larger_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A3-K5, v0.1-G5): at temperature 0 an identical retry returns an identical answer (A2.1's
    # confirmation run: five byte-identical runs), so each retry must change what is sent. Attempt 2's
    # message is not attempt 1's and names the problem; attempt 3 runs the configured larger model.
    # THIS is the test that fails if someone reverts to identical re-calls. Every attempt here fails the
    # same check, so the loop runs to its cap.
    policy = RetryPolicy(escalation_model="gemma-big")
    state, client = run_graph(
        tmp_path, monkeypatch, GOOD_PAGE, {PAGE: [listings_answer(BAD_LISTING)], SPLITTER: [NONA]}, policy=policy,
    )
    calls = completions(client).calls_for(PAGE)
    assert len(calls) == 3 and reached_escalate(state)
    first, second, third = (message_text(c) for c in calls)
    assert first != second != third and first != third
    assert "marked free" in second and "marked free" not in first
    assert "last attempt" in third and "last attempt" not in second
    assert [c["model"] for c in calls] == [MODEL, MODEL, "gemma-big"]
    assert [r.tier for r in state.attempt_history] == ["initial", "narrowed", "larger_model"]
    assert [r.larger_model_used for r in state.attempt_history] == [False, False, True]


def test_the_first_attempts_page_request_is_the_pipelines_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: attempt 1 carries no hint — its instruction is exactly what the eval measured (plan §3).
    state, client = run_graph(tmp_path, monkeypatch, GOOD_PAGE, {PAGE: [listings_answer(GOOD_LISTING)], SPLITTER: [NONA]})
    first = message_text(completions(client).calls_for(PAGE)[0])
    assert first.startswith(extraction.instruction_for(extraction.PIPELINE_CONFIG))
    assert "earlier attempt" not in first and reached_reconcile(state)


# ---------------------------------------------------------------------------
# The JSON-LD route gives way to the model route
# ---------------------------------------------------------------------------

UNDER_REPORTED = jsonld_page(
    event("Nona", "2026-10-20T21:00:00-05:00"), body="Nona Oct 20 8 pm Oct 21 Oct 22 Oct 23 Oct 24 Oct 25",
)


def test_a_json_ld_page_that_under_reports_falls_back_to_the_model_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A2.1-E16, plan §2): the text names five upcoming dates the one JSON-LD event doesn't cover, so
    # attempt 1 fails `jsonld_under_reported`; attempt 2 reads the page text with the model route (a page
    # call that attempt 1 never made) and passes. A JSON-LD retry would have been byte-identical.
    state, client = run_graph(
        tmp_path, monkeypatch, UNDER_REPORTED, {PAGE: [listings_answer(GOOD_LISTING)], SPLITTER: [NONA]},
    )
    assert [r.route for r in state.attempt_history] == ["jsonld", "model"]
    assert state.attempt_history[0].reasons == [FailureReason.CHECK_ERRORS]
    assert len(completions(client).calls_for(PAGE)) == 1 and len(completions(client).calls_for(SPLITTER)) == 2
    assert reached_reconcile(state)


def test_the_route_fallback_is_sticky_and_an_escalation_names_both_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A3-PR1-1): attempt 1 under-reports on JSON-LD, attempt 2 (model route) fails low
    # confidence, and attempt 3 STAYS on the model route instead of going back to the JSON-LD route that
    # already failed. The escalation reason says both routes failed — what a human needs to know.
    unsure = listing("2026-10-20", "Nona", time="20:00", confidence=0.5)
    state, _ = run_graph(
        tmp_path, monkeypatch, UNDER_REPORTED, {PAGE: [listings_answer(unsure)], SPLITTER: [NONA]},
    )
    assert [r.route for r in state.attempt_history] == ["jsonld", "model", "model"]
    assert reached_escalate(state)
    assert "jsonld and model" in (state.escalation_reason or "")


def test_a_malformed_json_ld_date_is_recorded_and_the_retry_uses_the_model_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A3-K1, A3-PR2-3): a deterministic ValueError from `fromisoformat` is a failed attempt that
    # records the route it used (`jsonld`, even though `extraction_source` is None for a failed attempt),
    # and — because a JSON-LD retry would raise identically — attempt 2 runs the model route.
    page = jsonld_page(event("Nona", "not-a-date"), body="Nona Oct 20 8 pm")
    state, client = run_graph(
        tmp_path, monkeypatch, page, {PAGE: [listings_answer(GOOD_LISTING)], SPLITTER: [NONA]},
    )
    first, second = state.attempt_history
    assert first.route == "jsonld" and first.reasons == [FailureReason.EXTRACT_FAILED]
    assert second.route == "model" and second.verdict is Verdict.PASSED
    assert len(completions(client).calls_for(PAGE)) == 1


def test_a_far_future_json_ld_event_is_excluded_and_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A3-D13): a stale or far-future event is excluded with a warning in ONE attempt; the page passes
    # and nothing is retried (the model route's year rule would have re-dated it into a wrong date).
    page = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"), event("Far Away", "2028-03-01T20:00:00-06:00"))
    state, _ = run_graph(
        tmp_path, monkeypatch, page, {SPLITTER: [split_answer(("Nona", ["Nona"]), ("Far Away", ["Far Away"]))]},
    )
    assert state.attempt_count == 1 and reached_reconcile(state)
    assert state.validation is not None and state.validation.excluded == [1]
    assert state.validated_extraction is not None and len(state.validated_extraction.shows) == 1


def test_a_json_ld_page_of_only_stale_events_is_excluded_not_sent_to_the_model_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A3-CR1-1; A3-D13): every event is more than 31 days back, so each is excluded
    # with a warning. The page's text names those same dates, which `upcoming_dates` places in NEXT year;
    # the empty-page guard must not read them as dates the extraction ignored. It did, sent the page to
    # the model route, and the year rule committed the shows as 2027-08-01..03 with a clean pass. The
    # script has no PAGE answer: any model-route call would fail the test. Ends in ONE attempt, on the
    # JSON-LD route, nothing kept, three exclusions on record.
    page = jsonld_page(
        event("A", "2026-08-01T20:00:00-05:00"), event("B", "2026-08-02T20:00:00-05:00"),
        event("C", "2026-08-03T20:00:00-05:00"), body="A Aug 1 8 pm B Aug 2 8 pm C Aug 3 8 pm",
    )
    answer = split_answer(("A", ["A"]), ("B", ["B"]), ("C", ["C"]))
    state, client = run_graph(tmp_path, monkeypatch, page, {SPLITTER: [answer]})
    assert state.attempt_count == 1 and [r.route for r in state.attempt_history] == ["jsonld"]
    assert state.validation is not None and state.validation.excluded == [0, 1, 2] and state.validation.errors == []
    assert state.validated_extraction is not None and state.validated_extraction.shows == []
    assert completions(client).calls_for(PAGE) == [] and reached_reconcile(state)


def test_an_end_time_equal_to_the_start_is_repaired_and_the_json_ld_route_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A3-PR2-4): a plugin that writes endDate == startDate does not send the page to the model
    # route on every run: the end time is dropped as a repair, the page passes on attempt 1.
    page = jsonld_page(
        event("Nona", "2026-10-20T20:00:00-05:00", endDate="2026-10-20T20:00:00-05:00"), body="Nona 8:00 pm",
    )
    state, _ = run_graph(tmp_path, monkeypatch, page, {SPLITTER: [NONA]})
    assert state.attempt_count == 1 and state.attempt_history[0].route == "jsonld"
    assert state.validation is not None and [r.field for r in state.validation.repairs] == ["end_time"]
    assert state.validated_extraction is not None and state.validated_extraction.shows[0].end_time is None


def test_a_page_whose_every_show_is_excluded_and_undated_passes_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A3-PR1-4): the splitter says the only event isn't music. Nothing is kept, confidence is
    # None (not `min([])`, which would raise in validate_node), the page passes, and the exclusion is on record.
    page = jsonld_page(event("Karaoke Night", "2026-10-20T21:00:00-05:00"), body="Karaoke Night")
    state, _ = run_graph(tmp_path, monkeypatch, page, {SPLITTER: [split_answer(("Karaoke Night", []))]})
    assert state.attempt_count == 1 and reached_reconcile(state)
    assert state.validation is not None and state.validation.excluded == [0]
    assert state.confidence is None


# ---------------------------------------------------------------------------
# Fetch failures
# ---------------------------------------------------------------------------


def test_a_page_that_cannot_be_read_escalates_without_calling_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A3-D6): a fetch failure is recorded and routed to escalate (arch-initial.md §7 names it as the
    # other failure mode), instead of raising out of the graph. The empty script asserts no model call.
    state, client = run_graph(tmp_path, monkeypatch, None, {}, url=str(tmp_path / "missing.html"))
    assert reached_escalate(state) and state.attempt_count == 0
    assert (state.escalation_reason or "").startswith("the page could not be fetched")
    assert completions(client).calls == []


def test_an_empty_page_escalates_instead_of_reaching_the_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A3-PR1-3): arch-initial.md §7 counts an "empty response" as a fetch failure. A model handed
    # a blank page can answer `page_readable: true, shows: []`, which would pass as a confirmed-empty
    # calendar. The empty script asserts the model is never called.
    state, client = run_graph(tmp_path, monkeypatch, "<html><body>  </body></html>", {})
    assert reached_escalate(state) and "nothing to read" in (state.fetch_error or "")
    assert completions(client).calls == []
