"""Tests for running one labelled page through the real graph and reading what came out (`eval/graph_run.py`).

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, Test approach §2). The graph is the real compiled graph,
the model is `fakes.scripted_client` (the test decides what the splitter says, so each failure is exact), and the stores are the
recording fakes, so no database is involved. What the committed rows hold is a database question, answered in
test_db_score.py; here `committed_rows` is a stub.

How to read it: `run_scripted` is the helper (it is also used by test_validation_recall.py); the pages are two-event JSON-LD
pages, so the act splitter is the only model call. Expected values come from the literal page (Nona and Lent, October 20 and 21,
2026, 9 PM Central), the scripted answers, and the label written beside them, never from the scorer's output on the thing under
test.
"""

import datetime
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_worker import nodes
from agent_worker.context import WorkerContext
from agent_worker.eval.graph_run import InMemoryStager, PageRun, run_page
from agent_worker.eval.labels import LabelledShow, PageLabel
from agent_worker.main import VenueFacts
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
    venue="test_venue", gated=True, captured_on=fakes.FETCHED, shows=(
        LabelledShow(D(2026, 10, 20), ("Nona",), "Nona", T(21, 0)), LabelledShow(D(2026, 10, 21), ("Lent",), "Lent", T(21, 0)),
    ),
)
FULL = split_answer(("Nona", ["Nona"]), ("Lent", ["Lent"]))
DROPS_LENT = split_answer(("Nona", ["Nona"]))  # no answer for the second title: `splitter_dropped`, an error


async def no_rows() -> dict[str, Any]:
    """Stands in for the database read: these tests don't ask what was committed."""
    return {"shows": []}


async def run_scripted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, html: str, label: PageLabel, script: dict[Any, list[Any]],
    *, policy: Any = None,
) -> PageRun:
    """Write `html` as the fixture, script the model, and run the page through the real graph with recording stores."""
    page = tmp_path / "page.html"
    page.write_text(html)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script))
    audit = RecordingAudit()
    ctx = WorkerContext(audit=audit, stager=InMemoryStager(), reader=FakeReader(), writer=FakeWriter(audit))
    return await run_page(
        label=label, fixture=page, venue=VENUE, ctx=ctx, committed_rows=no_rows, policy=policy,
    )


async def test_a_clean_page_is_one_attempt_with_nothing_wrong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: the plain case end to end. Two events, a splitter that answers for both: one attempt, no retry, the JSON-LD route,
    # the raw and the validated extraction both hold the two shows and score with no error.
    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [FULL]})
    assert (run.attempt_count, run.retried, run.recovered, run.escalated) == (1, False, False, False)
    assert run.source == "jsonld"
    assert run.route_mismatch is False  # the staged document's route is the source validation received (C5-CR1-6)
    assert run.raw is not None and run.validated is not None
    assert len(run.raw["shows"]) == 2 and len(run.validated["shows"]) == 2
    for column in (run.raw_score, run.validated_score):
        assert (column["missed"], column["acts_wrong"], column["fabricated"], column["items"]) == (0, 0, 0, [])


async def test_a_retry_that_recovers_is_scored_attempt_by_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


async def test_a_page_that_never_validates_escalates_at_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: the escalation path. The splitter drops Lent on every attempt: three attempts (the default cap), escalated, no
    # validated extraction (nothing reaches reconcile), and every labelled show Lent... is counted missed in the validated column.
    run = await run_scripted(tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [DROPS_LENT]})
    assert (run.attempt_count, run.escalated, run.retried, run.recovered) == (3, True, True, False)
    assert run.validated is None
    assert run.validated_score["missed"] == 2  # an escalated run commits nothing, so both labelled shows are missed
    assert run.escalation_reason is not None


async def test_a_policy_passed_to_the_harness_is_the_policy_the_run_uses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: C5-D5. `run_page(policy=...)` reaches the graph's routers: with a cap of 1 the same always-failing page makes
    # ONE attempt, not three. The expectation is the cap we passed.
    run = await run_scripted(
        tmp_path, monkeypatch, TWO_EVENTS, LABEL, {SPLITTER: [DROPS_LENT]}, policy=replace(DEFAULT_POLICY, max_attempts=1),
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
