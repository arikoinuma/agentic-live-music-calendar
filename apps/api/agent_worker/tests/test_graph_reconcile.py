"""Tests for reconcile inside the real compiled graph: what it reads, what it decides, and what the trail records.

Milestone A5 (docs/dev/implementations/a5-reconcile.md, Test approach §4). The pure rules are tested in
test_reconcile_shows.py, test_reconcile_removal.py and test_artist_match.py; these prove the pieces are wired: the
wrapper reads the stored calendar before the node runs, the plan reaches the state, the audit rows are the ones A5-D11
describes, and an unreadable calendar stops the run instead of looking empty. The model is `fakes.scripted_client`; the
stores are the recording fakes plus `fakes.FakeReader`, so no database is involved (test_reconcile_db.py is the
real-database layer).

Expected values come from the plan (A5-D1, A5-D2, A5-D6, A5-D9, A5-D11 and "Settled details") and the literal page: the one event is
"Nona" at 8 PM Central on October 20, 2026, fetched October 12.
"""

import datetime
from pathlib import Path
from typing import Any

import pytest

from agent_worker import extraction, nodes
from agent_worker.artist_match import KnownArtist
from agent_worker.context import WorkerContext
from agent_worker.graph import compiled_graph
from agent_worker.reconcile import Action, StoredShow
from agent_worker.state import VenueGraphState
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    ARTIST_MATCH,
    PAGE,
    SPLITTER,
    FakeReader,
    FakeWriter,
    RecordingAudit,
    RecordingStager,
    event,
    jsonld_page,
    listings_answer,
    scripted_client,
    split_answer,
    text_page,
)
from agent_worker.tests.reconcile_support import at, stored
from app.enums import EntityType, StepType

RUN_ID = 5
NONA_PAGE = jsonld_page(event("Nona", "2026-10-20T20:00:00-05:00"))
NONA = split_answer(("Nona", ["Nona"]))
WINDOW = {"start": "2026-10-12", "end": "2026-10-20"}


async def run_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, html: str, script: dict[Any, list[Any]], reader: FakeReader,
) -> tuple[VenueGraphState, RecordingAudit]:
    """Run the real graph on `html` with a scripted model and `reader` as the stored calendar."""
    page = tmp_path / "page.html"
    page.write_text(html)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script))
    audit = RecordingAudit()
    state = VenueGraphState(
        venue_id=1, calendar_url=str(page), venue_name="The Venue", metro_timezone="America/Chicago",
        fetched_on=fakes.FETCHED, run_id=RUN_ID,
    )
    context = WorkerContext(audit=audit, stager=RecordingStager(), reader=reader, writer=FakeWriter())
    return VenueGraphState(**await compiled_graph.ainvoke(state, context=context)), audit


def stored_nona(tmp_path: Path, **fields: Any) -> StoredShow:
    """The stored twin of the page's one show, as a previous run would have left it. `original_url` is the page's
    own path, because that is what reconcile compares against (the calendar URL of the run)."""
    return stored(
        1, datetime.date(2026, 10, 20), at(20), acts=[(7, "Nona")], original_url=str(tmp_path / "page.html"), **fields
    )


def reconcile_rows(audit: RecordingAudit) -> list[Any]:
    return [e for e in audit.entries if e.step_type is StepType.RECONCILE]


async def test_the_first_run_over_an_empty_calendar_inserts_and_records_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves: a calendar with nothing stored turns the page's one show into one insert. The reconcile row is
    # venue-level (A5-D11) and its detail carries the counts and the window (A5-D1): the fetch date to the last date the
    # page lists. The reader was asked for exactly that range.
    reader = FakeReader()
    state, audit = await run_reconcile(tmp_path, monkeypatch, NONA_PAGE, {SPLITTER: [NONA]}, reader)
    assert state.reconcile_plan is not None and [d.action for d in state.reconcile_plan.shows] == [Action.INSERT]
    [row] = reconcile_rows(audit)
    assert (row.entity_type, row.entity_id, row.run_id) == (EntityType.VENUE, 1, RUN_ID)
    assert row.detail["counts"] == {"insert": 1, "update": 0, "no_op": 0, "remove": 0, "skip": 0}
    assert row.detail["coverage"] == WINDOW
    assert reader.reads == [(1, datetime.date(2026, 10, 12), datetime.date(2026, 10, 20))]


async def test_a_second_run_over_what_the_first_wrote_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves: with the show stored as the first run would have left it, reconcile finds one no-op and nothing
    # else: it is stable run to run (and reads the stored lineup, so the artist Nona is found exactly).
    reader = FakeReader([stored_nona(tmp_path)], [KnownArtist(7, "Nona")])
    state, audit = await run_reconcile(tmp_path, monkeypatch, NONA_PAGE, {SPLITTER: [NONA]}, reader)
    assert state.reconcile_plan is not None and [d.action for d in state.reconcile_plan.shows] == [Action.NO_OP]
    assert reconcile_rows(audit)[0].detail["counts"]["no_op"] == 1


async def test_a_cancelled_listing_removes_the_stored_show(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A5-D6) through the whole pipeline: the venue marks the show cancelled in its structured data
    # (schema.org `eventStatus`, read by the JSON-LD route), and the stored show it matches is removed with the
    # reason `cancelled`.
    page = jsonld_page(event("Nona", "2026-10-20T20:00:00-05:00", eventStatus="https://schema.org/EventCancelled"))
    reader = FakeReader([stored_nona(tmp_path)], [KnownArtist(7, "Nona")])
    state, _ = await run_reconcile(tmp_path, monkeypatch, page, {SPLITTER: [NONA]}, reader)
    assert state.reconcile_plan is not None
    [decision] = state.reconcile_plan.shows
    assert (decision.action, decision.reason, decision.stored_id) == (Action.REMOVE, "cancelled", 1)


async def test_a_model_decision_about_an_artist_gets_its_own_audit_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (A5-D9, A5-D11): "Zhora Band" is similar to the stored artist "Zhora" (id 8), so the model is asked and says
    # same, 0.9. The summary row comes first, then a second `reconcile` row for the decision: entity = that artist,
    # `model_used`, the confidence as a Decimal, and the reason and candidates in `detail`. This is "the one place
    # a model makes a database decision", and the reason it needs its own row.
    page = jsonld_page(event("Zhora Band", "2026-10-20T20:00:00-05:00"))
    script = {
        SPLITTER: [split_answer(("Zhora Band", ["Zhora Band"]))],
        ARTIST_MATCH: [{"matched_artist_id": 8, "confidence": 0.9, "reason": "same band, longer name"}],
    }
    state, audit = await run_reconcile(tmp_path, monkeypatch, page, script, FakeReader(artists=[KnownArtist(8, "Zhora")]))
    assert audit.steps() == [
        ("fetch", 1), ("extract", 1), ("validate", 1), ("reconcile", 1), ("reconcile", 1), ("commit", 1),
    ]
    summary, decision = reconcile_rows(audit)
    assert summary.entity_type is EntityType.VENUE and summary.detail["model_decisions"] == 1
    assert (decision.entity_type, decision.entity_id) == (EntityType.ARTIST, 8)
    assert decision.model_used == extraction.PIPELINE_OPTIONS.model and str(decision.confidence) == "0.900"
    assert decision.detail["reason"] == "same band, longer name" and decision.detail["outcome"] == "matched_by_model"
    assert decision.detail["candidates"] == [{"id": 8, "name": "Zhora"}]
    assert state.reconcile_plan is not None and state.reconcile_plan.shows[0].lineup[0].artist_id == 8


async def test_an_unreadable_calendar_stops_the_run_with_no_reconcile_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves ("Settled details"): when the stored calendar can't be read, the error propagates and the run stops.
    # Treating it as empty would turn every listing into an insert, a duplicate of every show. No reconcile row is
    # written for a step that never ran, and commit never runs.
    page = tmp_path / "page.html"
    page.write_text(NONA_PAGE)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [NONA]}))
    audit = RecordingAudit()
    state = VenueGraphState(
        venue_id=1, calendar_url=str(page), venue_name="The Venue", metro_timezone="America/Chicago",
        fetched_on=fakes.FETCHED, run_id=RUN_ID,
    )
    context = WorkerContext(audit=audit, stager=RecordingStager(), reader=FakeReader(fail=True), writer=FakeWriter())
    with pytest.raises(RuntimeError, match="unreadable"):
        await compiled_graph.ainvoke(state, context=context)
    assert [step for step, _ in audit.steps()] == ["fetch", "extract", "validate"]


async def test_a_confirmed_empty_page_reads_nothing_and_removes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (A5-D2, decided A): the model reads the page and says it lists no shows. A stored show is untouched, the
    # reader was never asked for shows (there is no window to read), and the reconcile row says `coverage: None`.
    reader = FakeReader([stored_nona(tmp_path)], [KnownArtist(7, "Nona")])
    state, audit = await run_reconcile(
        tmp_path, monkeypatch, text_page("Nothing is scheduled right now."), {PAGE: [listings_answer()]}, reader
    )
    assert state.reconcile_plan is not None and state.reconcile_plan.shows == ()
    assert reader.reads == []
    row = reconcile_rows(audit)[0]
    assert row.detail["coverage"] is None and row.detail["counts"]["remove"] == 0
