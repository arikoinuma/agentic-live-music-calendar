"""Tests for commit inside the real compiled graph: what it is given, what the trail records, and how a failure ends.

Milestone A6 (docs/dev/implementations/a6-commit.md, Test approach §4). The rules for WHAT to write are tested in
test_commit_ops.py and the writes themselves in test_calendar_writer.py; these prove the pieces are wired: the node turns
reconcile's plan into operations, `trace.audited` awaits them through the context's writer, the per-show rows and the run's
summary row come out in the order the plan says, and a failed show or a lost connection ends the run the way A6-D2 says.
The model is `fakes.scripted_client`; the stores are the recording fakes, `fakes.FakeReader` and `fakes.FakeWriter` (which
appends to the same `RecordingAudit` the rows a real write would, so the whole trail is observable in order), so no database
is involved (test_commit_db.py is the real-database layer).

Expected values come from the plan (A6-D1, A6-D2, "Audit rows", "Settled details") and the literal page: the one event is
"Nona" at 8 PM Central on October 20, 2026, fetched October 12.
"""

import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import InterfaceError

from agent_worker import nodes
from agent_worker.artist_match import KnownArtist
from agent_worker.context import WorkerContext
from agent_worker.graph import compiled_graph
from agent_worker.reconcile import Action, StoredShow
from agent_worker.state import VenueGraphState
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    SPLITTER,
    FakeReader,
    FakeWriter,
    RecordingAudit,
    RecordingStager,
    event,
    jsonld_page,
    scripted_client,
    split_answer,
)
from agent_worker.tests.reconcile_support import at, stored
from app.enums import AuditOutcome, EntityType, StepType

RUN_ID = 5
NONA_PAGE = jsonld_page(event("Nona", "2026-10-20T20:00:00-05:00"))
NONA = split_answer(("Nona", ["Nona"]))
TWO_SHOWS = jsonld_page(event("Nona", "2026-10-20T20:00:00-05:00"), event("Nona", "2026-10-21T20:00:00-05:00"))
TWO_NONAS = split_answer(("Nona", ["Nona"]), ("Nona", ["Nona"]))


async def run_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, html: str, script: dict[Any, list[Any]], reader: FakeReader,
    writer: FakeWriter | None = None,
) -> tuple[VenueGraphState, RecordingAudit, FakeWriter]:
    """Run the real graph on `html`, with `reader` as the stored calendar and a fake writer that appends to the audit."""
    page = tmp_path / "page.html"
    page.write_text(html)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script))
    audit = RecordingAudit()
    writer = writer or FakeWriter(audit)
    writer.audit = writer.audit or audit
    state = VenueGraphState(
        venue_id=1, calendar_url=str(page), venue_name="The Venue", metro_timezone="America/Chicago",
        fetched_on=fakes.FETCHED, run_id=RUN_ID,
    )
    context = WorkerContext(audit=audit, stager=RecordingStager(), reader=reader, writer=writer)
    return VenueGraphState(**await compiled_graph.ainvoke(state, context=context)), audit, writer


def stored_nona(tmp_path: Path, day: int = 20, show_id: int = 1, **fields: Any) -> StoredShow:
    """A stored twin of a page show, as a previous run would have left it. `original_url` is the page's own path,
    because that is what reconcile compares against (the calendar URL of the run)."""
    return stored(
        show_id, datetime.date(2026, 10, day), at(20), acts=[(7, "Nona")], original_url=str(tmp_path / "page.html"), **fields
    )


def commit_rows(audit: RecordingAudit) -> list[Any]:
    return [e for e in audit.entries if e.step_type is StepType.COMMIT]


async def test_the_first_run_hands_the_writer_an_insert_and_writes_the_artist_the_show_and_the_summary_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (A6 "The wiring"): over an empty calendar the page's one show becomes one insert operation (handed to the
    # writer, with the new artist's name), and the trail ends reconcile, then the artist's commit row, the show's commit
    # row and, LAST, the run's summary row (venue-level, `inserted: 1`). The summary comes last because it is the sign
    # that commit reached its end (`unfinished_runs`).
    state, audit, writer = await run_commit(tmp_path, monkeypatch, NONA_PAGE, {SPLITTER: [NONA]}, FakeReader())
    [op] = writer.ops
    assert op.action is Action.INSERT and op.new_artist_names == {"nona": "Nona"}
    rows = commit_rows(audit)
    assert [(r.entity_type, r.outcome) for r in rows] == [
        (EntityType.ARTIST, AuditOutcome.INSERTED), (EntityType.SHOW, AuditOutcome.INSERTED), (EntityType.VENUE, None),
    ]
    assert audit.entries[-1] is rows[-1]
    summary = rows[-1].detail
    assert summary["counts"] == {"inserted": 1, "updated": 0, "removed": 0, "no_op": 0, "skip": 0}
    assert summary["artists_created"] == 1 and summary["failed"] == [] and summary["all_failed"] is False
    assert state.commit_result is not None and state.commit_result.written["inserted"] == 1


async def test_a_second_run_over_what_the_first_wrote_makes_no_writes_and_one_summary_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (A6-D1): with the show stored as the first run left it, reconcile decides one no-op, so commit hands the
    # writer NOTHING and writes exactly one row, the summary, counting the no-op. An unchanged show leaves no row of its own.
    reader = FakeReader([stored_nona(tmp_path)], [KnownArtist(7, "Nona")])
    state, audit, writer = await run_commit(tmp_path, monkeypatch, NONA_PAGE, {SPLITTER: [NONA]}, reader)
    assert writer.ops == []
    [row] = commit_rows(audit)
    assert (row.entity_type, row.outcome) == (EntityType.VENUE, None)
    assert row.detail["counts"] == {"inserted": 0, "updated": 0, "removed": 0, "no_op": 1, "skip": 0}
    assert state.commit_result is not None and state.commit_result.failures == ()


async def test_a_cancelled_listing_becomes_one_removal_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (A5-D6, A6): a venue that marks the stored show cancelled produces one remove operation whose reason is
    # `cancelled`, and its row is outcome `removed`.
    page = jsonld_page(event("Nona", "2026-10-20T20:00:00-05:00", eventStatus="https://schema.org/EventCancelled"))
    reader = FakeReader([stored_nona(tmp_path)], [KnownArtist(7, "Nona")])
    _, audit, writer = await run_commit(tmp_path, monkeypatch, page, {SPLITTER: [NONA]}, reader)
    [op] = writer.ops
    assert (op.action, op.reconcile_reason, op.stored_id) == (Action.REMOVE, "cancelled", 1)
    assert [r.outcome for r in commit_rows(audit)] == [AuditOutcome.REMOVED, None]


async def test_a_withheld_removal_is_not_written_and_the_summary_counts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (A5-D10, A6): four stored shows in the window that the page does not list are all withheld by the guard; commit
    # writes only the page's own new show, and the summary says four removals were held back.
    reader = FakeReader(
        [stored_nona(tmp_path, day=d, show_id=d) for d in (13, 14, 15, 16)], [KnownArtist(7, "Nona")],
    )
    state, audit, writer = await run_commit(tmp_path, monkeypatch, NONA_PAGE, {SPLITTER: [NONA]}, reader)
    assert [op.action for op in writer.ops] == [Action.INSERT]
    assert commit_rows(audit)[-1].detail["withheld"] == 4 and state.reconcile_plan is not None
    assert len(state.reconcile_plan.withheld) == 4


async def test_one_failing_show_is_recorded_the_others_are_written_and_the_run_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (A6-D2): of two new shows the first is refused by the database (an overflow, SQLSTATE 22003). The second is
    # still written, the refusal is a failure row (through the audit writer, saying which show) and a `failed` entry in the
    # summary, and `ainvoke` returns normally with `commit_result.failures` for the caller to count.
    writer = FakeWriter(fail={0: fakes.overflow()})
    state, audit, _ = await run_commit(tmp_path, monkeypatch, TWO_SHOWS, {SPLITTER: [TWO_NONAS]}, FakeReader(), writer)
    assert len(writer.ops) == 2
    assert state.commit_result is not None and len(state.commit_result.failures) == 1
    [failure] = state.commit_result.failures
    assert (failure.date, failure.sqlstate, failure.stored_id) == (datetime.date(2026, 10, 20), "22003", None)
    failure_rows = [r for r in commit_rows(audit) if r.detail.get("error")]
    assert len(failure_rows) == 1 and failure_rows[0].outcome is None and failure_rows[0].detail["date"] == "2026-10-20"
    summary = commit_rows(audit)[-1].detail
    assert summary["counts"]["inserted"] == 1 and len(summary["failed"]) == 1 and summary["all_failed"] is False


async def test_a_lost_connection_propagates_and_no_summary_row_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (A6-D2, A6 "The wiring"): a failure that is not about one show raises out of `ainvoke`, and because the
    # summary row is written only after every write, there is NO summary row: the run reads as unfinished
    # (`unfinished_runs`). The first show was written before the connection dropped, so its row exists.
    writer = FakeWriter(fail={1: fakes.lost_connection()})
    audit_holder = RecordingAudit()
    writer.audit = audit_holder
    page = tmp_path / "page.html"
    page.write_text(TWO_SHOWS)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [TWO_NONAS]}))
    state = VenueGraphState(
        venue_id=1, calendar_url=str(page), venue_name="The Venue", metro_timezone="America/Chicago",
        fetched_on=fakes.FETCHED, run_id=RUN_ID,
    )
    context = WorkerContext(audit=audit_holder, stager=RecordingStager(), reader=FakeReader(), writer=writer)
    with pytest.raises(InterfaceError):
        await compiled_graph.ainvoke(state, context=context)
    rows = commit_rows(audit_holder)
    assert [r.entity_type for r in rows] == [EntityType.ARTIST, EntityType.SHOW]  # the first show only; no venue-level summary
    assert len(writer.ops) == 2


async def test_an_escalated_run_never_reaches_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: a run that escalates (every model attempt fails) has no reconcile and no commit: the writer is never called
    # and no commit row is written. Commit is reached only through a passed or confirmed-empty validation.
    state, audit, writer = await run_commit(
        tmp_path, monkeypatch, fakes.text_page("Nona", "Oct 20", "8 pm"), {fakes.PAGE: [ValueError("still down")]},
        FakeReader(),
    )
    assert state.escalation_reason is not None and writer.ops == [] and commit_rows(audit) == []
