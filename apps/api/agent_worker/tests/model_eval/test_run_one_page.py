"""Tests for running one labelled page through the real graph and reading what came out (`model_eval/labeled_page_runs/run_one_page.py`).

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, Test approach §2). The graph is the real compiled graph,
the model is `fakes.scripted_client` (the test decides what the splitter says, so each failure is exact), and the stores are the
recording fakes, so no database is involved. What the committed rows hold is a database question, answered in
test_two_run_scenarios.py; here `committed_rows` is a stub.

How to read it: `run_scripted` is the helper (it is also used by test_validation_recall.py); the pages are two-event JSON-LD
pages, so the act splitter is the only model call. Expected values come from the literal page (Nona and Lent, October 20 and 21,
2026, 9 PM Central), the scripted answers, and the label written beside them, never from the scorer's output on the thing under
test.
"""

import datetime
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_worker import nodes
from agent_worker.context import WorkerContext
from agent_worker.main import VenueFacts
from agent_worker.model_eval.labeled_page_runs import run_labeled_pages
from agent_worker.model_eval.labeled_page_runs.run_one_page import (
    InMemoryStager,
    PageRun,
    column_scores,
    run_page,
)
from agent_worker.model_eval.labels import LabelledShow, PageLabel
from agent_worker.model_eval.saved_run_reports.policy_questions import FORCED_THRESHOLD
from agent_worker.policy import DEFAULT_POLICY
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    SPLITTER,
    FakeReader,
    FakeWriter,
    RecordingAudit,
    event,
    jsonld_page,
    scripted_client,
    split_answer,
)

D = datetime.date
T = datetime.time

VENUE = VenueFacts(id=1, name="The Test Venue", calendar_url="unused", metro_timezone="America/Chicago")
TWO_EVENTS = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"), event("Lent", "2026-10-21T21:00:00-05:00"))
LABEL = PageLabel(
    venue="test_venue",
    gated=True,
    captured_on=fakes.FETCHED,
    shows=(
        LabelledShow(D(2026, 10, 20), ("Nona",), "Nona", T(21, 0)),
        LabelledShow(D(2026, 10, 21), ("Lent",), "Lent", T(21, 0)),
    ),
)
FULL = split_answer(("Nona", ["Nona"]), ("Lent", ["Lent"]))
DROPS_LENT = split_answer(("Nona", ["Nona"]))  # no answer for the second title: `splitter_dropped`, an error


async def no_rows() -> dict[str, Any]:
    """Stands in for the database read: these tests don't ask what was committed."""
    return {"shows": []}


async def run_scripted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    label: PageLabel,
    script: dict[Any, list[Any]],
    *,
    policy: Any = None,
) -> PageRun:
    """Write `html` as the fixture, script the model, and run the page through the real graph with recording stores."""
    page = tmp_path / "page.html"
    page.write_text(html)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script))
    audit = RecordingAudit()
    ctx = WorkerContext(audit=audit, stager=InMemoryStager(), reader=FakeReader(), writer=FakeWriter(audit))
    return await run_page(
        label=label,
        fixture=page,
        venue=VENUE,
        ctx=ctx,
        committed_rows=no_rows,
        policy=policy if policy is not None else fakes.THREE_ATTEMPTS,
    )


async def test_a_clean_page_is_one_attempt_with_nothing_wrong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: the plain case end to end. Two events, a splitter that answers for both: one attempt, no retry, the JSON-LD route,
    # the raw and the validated extraction both hold the two shows and score with no error.
    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [FULL]})
    assert (run.attempt_count, run.retried, run.recovered, run.escalated) == (1, False, False, False)
    assert run.source == "structured"
    assert run.route_mismatch is False  # the staged document's route is the source validation received (C5-CR1-6)
    assert run.raw is not None and run.validated is not None
    assert len(run.raw["shows"]) == 2 and len(run.validated["shows"]) == 2
    for column in (run.raw_score, run.validated_score):
        assert (column["missed"], column["acts_wrong"], column["fabricated"], column["items"]) == (0, 0, 0, [])


async def test_a_retry_that_recovers_is_scored_attempt_by_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves: C5-D7 and C5-M4. Attempt 1's splitter drops Lent (an error, so a retry); attempt 2 answers in full. The run is
    # two attempts, retried and recovered; attempt 2 is the 'narrowed' tier; and the PER-ATTEMPT scores differ: attempt 1 missed
    # Lent, attempt 2 missed nothing. If only the last attempt were scored, "did the retry fix it" could not be asked.
    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [DROPS_LENT, FULL]})
    assert (run.attempt_count, run.retried, run.recovered, run.escalated) == (2, True, True, False)
    first, second = run.attempts
    assert (first.tier, second.tier) == ("initial", "narrowed")
    assert first.verdict == "failed" and second.verdict == "passed"
    assert first.score is not None and second.score is not None
    assert (first.score["missed"], second.score["missed"]) == (1, 0)
    assert len(run.staged_documents) == 2  # one staging document per attempt (A4)


async def test_a_page_that_never_validates_escalates_at_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves: the escalation path. The splitter drops Lent on every attempt: three attempts (`THREE_ATTEMPTS`, the cap this helper passes), escalated, no
    # validated extraction (nothing reaches reconcile), and every labelled show Lent... is counted missed in the validated column.
    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [DROPS_LENT]})
    assert (run.attempt_count, run.escalated, run.retried, run.recovered) == (3, True, True, False)
    assert run.validated is None
    assert run.validated_score["missed"] == 2  # an escalated run commits nothing, so both labelled shows are missed
    assert run.escalation_reason is not None


async def test_a_policy_passed_to_the_harness_is_the_policy_the_run_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves: C5-D5. `run_page(policy=...)` reaches the graph's routers: with a cap of 1 the same always-failing page makes
    # ONE attempt, not three. The expectation is the cap we passed.
    run = await run_scripted(
        tmp_path,
        monkeypatch,
        TWO_EVENTS,
        LABEL,
        {SPLITTER: [DROPS_LENT]},
        policy=replace(DEFAULT_POLICY, max_attempts=1),
    )
    assert (run.attempt_count, run.escalated, run.retried) == (1, True, False)
    assert run.policy["max_attempts"] == 1


async def test_the_run_record_is_plain_json_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: a `PageRun` goes into the results file as is, and comes back: `dataclasses.asdict` of it survives `json.dumps`
    # (dates are strings, not `datetime.date`; prices are floats, not Decimal), so a --rescore can rebuild every score from the
    # stored data with no model call.
    import dataclasses
    import json

    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [DROPS_LENT, FULL]})
    stored = json.loads(json.dumps(dataclasses.asdict(run)))
    assert stored["attempt_count"] == 2
    assert stored["attempts"][0]["errors"][0]["code"] == "splitter_dropped"


# ---------------------------------------------------------------------------
# Code review round 2 (C5-CR2-3): one function scores a run's columns, for a fresh run and for --rescore
# ---------------------------------------------------------------------------


def test_the_committed_column_is_held_to_the_scheduled_shows_but_raw_and_validated_are_not() -> None:
    # Proves: the column rule `run_page` and `--rescore` now share. The database cannot hold a cancelled show (reconcile skips
    # it), so with a cancelled show labelled, the raw and validated columns that return nothing miss both labelled shows while the
    # committed column that returns nothing misses only the scheduled one. Expected counts are read off the label below.
    label = PageLabel(
        venue="v",
        gated=True,
        captured_on=datetime.date(2026, 10, 12),
        shows=(
            LabelledShow(datetime.date(2026, 10, 20), ("Nona",), "Nona"),
            LabelledShow(datetime.date(2026, 10, 21), ("Lent",), "Lent", status="cancelled"),
        ),
    )
    scores = column_scores(label, raw=None, validated=None, committed={"shows": []}, page_html="", fixture="p.html")
    assert set(scores) == {"raw_score", "validated_score", "committed_score"}
    assert (
        scores["raw_score"]["missed"],
        scores["validated_score"]["missed"],
        scores["committed_score"]["missed"],
    ) == (2, 2, 1)


# ---------------------------------------------------------------------------
# C7 (docs/dev/implementations/c7-pipeline-eval.md, Test approach §4): what the policy questions read from each attempt
# ---------------------------------------------------------------------------

# A model-route page with a show and a no-acts listing, the real 7th St Entry shape (C7-F3): the model gives the no-acts listing a
# lower confidence, the splitter returns no act for it, and validation excludes it before taking the record's minimum.
MODEL_PAGE = fakes.text_page("Nona", "Oct 20", "8 pm", "Private event", "Oct 21")
MODEL_LABEL = PageLabel(
    venue="test_venue",
    gated=True,
    captured_on=fakes.FETCHED,
    shows=(LabelledShow(D(2026, 10, 20), ("Nona",), "Nona", T(20, 0)),),
)
MODEL_SCRIPT: dict[Any, list[Any]] = {
    fakes.PAGE: [
        fakes.listings_answer(
            fakes.listing("2026-10-20", "Nona", time="20:00", confidence=0.9),
            fakes.listing("2026-10-21", "Private event", confidence=0.5),
        )
    ],
    SPLITTER: [split_answer(("Nona", ["Nona"]), ("Private event", []))],
    fakes.STATUS: [{"items": []}],
}


class CountingCompletions(fakes.ScriptedCompletions):
    """The scripted model, plus what instructor does after every call: fire the `completion:response` hooks with the response's
    token `usage` (10 prompt and 2 completion tokens a call), or with no usage at all when `usage` is False."""

    def __init__(self, script: dict[Any, list[Any]], *, usage: bool = True) -> None:
        super().__init__(script)
        self.usage = usage
        self.handlers: dict[str, list[Any]] = {}

    def create(self, **kwargs: Any) -> Any:
        answer = super().create(**kwargs)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=2) if self.usage else None
        for handler in self.handlers.get("completion:response", []):
            handler(SimpleNamespace(usage=usage))
        return answer


def counting_client(script: dict[Any, list[Any]], *, usage: bool = True) -> SimpleNamespace:
    """A scripted client that takes hooks the way instructor's does (`client.on(event, handler)`)."""
    completions = CountingCompletions(script, usage=usage)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        on=lambda event, handler: completions.handlers.setdefault(event, []).append(handler),
    )


async def test_each_attempt_records_its_confidence_and_which_shows_it_covers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (C7-F3, C7-PR1-1): the fields C7-K1 reads. The model gave 0.9 and 0.5; the no-acts listing (index 1) is excluded, so the
    # record's confidence is 0.9 (the minimum over the judged show only), `show_confidences` keeps both values as the model gave
    # them, and `judged_indices` is [0]. The recomputed confidence equals the one `validate_node` recorded (the self-check).
    run = await run_scripted(tmp_path, monkeypatch, MODEL_PAGE, MODEL_LABEL, MODEL_SCRIPT)
    (only,) = run.attempts
    assert run.source == "model"
    assert (only.confidence, only.show_confidences, only.judged_indices, only.excluded_indices) == (
        0.9,
        [0.9, 0.5],
        [0],
        [1],
    )
    assert only.recorded_confidence == 0.9


async def test_a_structured_route_attempt_has_no_confidence_but_keeps_the_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (C7-F5, C7-PR1-3): the structured route has no confidence (`aggregate_confidence` returns None), and the recorder still
    # stores its placeholder 1.0s as they are; dropping the route is C7-K1's job, so a mutation there can fail a test.
    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [FULL]})
    (only,) = run.attempts
    assert (only.confidence, only.show_confidences, only.recorded_confidence) == (None, [1.0, 1.0], None)


async def test_each_attempt_records_its_seconds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C7-PR1-6): per-attempt seconds exist and fit inside the run: attempt 1 from the run's start to its staging, attempt 2
    # from staging 1 to staging 2, so their sum is at most the run's seconds (rounded to 0.1 there, hence the slack).
    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [DROPS_LENT, FULL]})
    seconds = [a.seconds for a in run.attempts]
    assert all(s is not None and s >= 0 for s in seconds)
    assert sum(s or 0 for s in seconds) <= run.seconds + 0.1


async def test_tokens_are_recorded_per_attempt_and_sum_to_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (C7-D6): the counting hooks are attached to the client the graph's nodes call, and each attempt's tokens are its own.
    # Attempt 1 makes one splitter call (it drops Lent), attempt 2 one more: 10 prompt and 2 completion tokens each. Nothing runs
    # after the last staging (no ambiguous artist), so the remainder is 0, and the three sum to the run's 20 and 4.
    page = tmp_path / "page.html"
    page.write_text(TWO_EVENTS)
    monkeypatch.setattr(nodes, "instructor_client", counting_client({SPLITTER: [DROPS_LENT, FULL]}))
    audit = RecordingAudit()
    run = await run_page(
        label=LABEL,
        fixture=page,
        venue=VENUE,
        committed_rows=no_rows,
        ctx=WorkerContext(audit=audit, stager=InMemoryStager(), reader=FakeReader(), writer=FakeWriter(audit)),
    )
    assert [a.tokens for a in run.attempts] == [{"prompt": 10, "completion": 2}, {"prompt": 10, "completion": 2}]
    assert run.tokens_after_last_attempt == {"prompt": 0, "completion": 0}


async def test_tokens_are_none_not_zero_when_no_response_carries_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (C7-D6): a provider that reports no usage is an unknown cost, never 0 tokens.
    page = tmp_path / "page.html"
    page.write_text(TWO_EVENTS)
    monkeypatch.setattr(nodes, "instructor_client", counting_client({SPLITTER: [FULL]}, usage=False))
    audit = RecordingAudit()
    run = await run_page(
        label=LABEL,
        fixture=page,
        venue=VENUE,
        committed_rows=no_rows,
        ctx=WorkerContext(audit=audit, stager=InMemoryStager(), reader=FakeReader(), writer=FakeWriter(audit)),
    )
    assert [a.tokens for a in run.attempts] == [None]
    assert run.tokens_after_last_attempt is None


async def test_forced_retries_run_every_tier_on_a_model_route_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (C7-D3): with the forced threshold every model-judged attempt fails for low confidence, so a clean model-route page
    # makes the cap's three attempts, one per tier, every one scored, and escalates. The threshold the record carries is the
    # forced one, which is how the report knows to say "forced retries".
    policy = run_labeled_pages.build_policy(None, 3, force=True)
    run = await run_scripted(tmp_path, monkeypatch, MODEL_PAGE, MODEL_LABEL, MODEL_SCRIPT, policy=policy)
    assert [a.tier for a in run.attempts] == ["initial", "narrowed", "larger_model"]
    assert all(a.reasons == ["low_confidence"] and a.score is not None for a in run.attempts)
    assert run.escalated and run.policy["confidence_threshold"] == FORCED_THRESHOLD


async def test_forced_retries_leave_a_structured_page_at_one_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (C7-D3's limit): the structured route has no confidence, so there is nothing to force; it passes on attempt 1.
    policy = run_labeled_pages.build_policy(None, 3, force=True)
    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [FULL]}, policy=policy)
    assert (run.attempt_count, run.attempts[0].verdict) == (1, "passed")


async def test_an_escalation_model_runs_every_call_of_attempt_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (C6-D4, C7-D2): `--escalation-model X` puts X on attempt 3's page, splitter and status calls, and the attempt records
    # `larger_model_used`. Attempts 1 and 2 keep the configured model. The expectation is the name passed in.
    page = tmp_path / "page.html"
    page.write_text(MODEL_PAGE)
    client = fakes.scripted_client(MODEL_SCRIPT)
    monkeypatch.setattr(nodes, "instructor_client", client)
    audit = RecordingAudit()
    run = await run_page(
        label=MODEL_LABEL,
        fixture=page,
        venue=VENUE,
        committed_rows=no_rows,
        ctx=WorkerContext(audit=audit, stager=InMemoryStager(), reader=FakeReader(), writer=FakeWriter(audit)),
        policy=run_labeled_pages.build_policy(None, 3, force=True, escalation_model="bigger-model"),
    )
    assert [a.larger_model_used for a in run.attempts] == [False, False, True]
    calls = fakes.completions(client)
    for kind in (fakes.PAGE, SPLITTER):
        models = [c["model"] for c in calls.calls_for(kind)]
        assert models[-1] == "bigger-model" and "bigger-model" not in models[:-1]
