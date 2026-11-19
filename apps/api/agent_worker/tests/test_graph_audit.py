"""Tests that the real compiled graph writes the audit trail and the staging records.

Milestone A4 (docs/dev/implementations/a4-auditability.md, Test approach §2). The graph is the real one
(`compiled_graph`), the model is `fakes.scripted_client()`, and the stores are the recording fakes
(`fakes.RecordingAudit`, `fakes.RecordingStager`), so no Postgres or MongoDB is involved. What these prove is
the wiring: every node's run is followed by one audit row, every extract attempt (failed ones too) by one
staging document, retries add rows instead of replacing them, and a store that fails stops the run.

How to read it: each test scripts the model, runs the graph with `run_id=7` in the state, and asserts on
the recorded `(step, attempt)` sequence, the entries' fields, and the staged documents. The expected
sequences come from the graph's shape (`graph.py` diagram) and the 3-attempt cap (arch-initial.md §7; passed in
explicitly, since the shipped default became 2 after C7), not from the code under test.

Until Ari fills A4-K3 (the staging write in `trace.audited`) every test here that reaches `extract` is red,
by design; the two fetch-failure tests, which never reach extract, are green.
"""

from pathlib import Path
from typing import Any

import pytest

from agent_worker import nodes
from agent_worker.context import WorkerContext
from agent_worker.graph import compiled_graph
from agent_worker.snapshots import SnapshotError
from agent_worker.state import VenueGraphState
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    PAGE,
    SPLITTER,
    FakeReader,
    FakeWriter,
    RecordingAudit,
    RecordingSnapshots,
    RecordingStager,
    event,
    jsonld_page,
    listings_answer,
    scripted_client,
)
from agent_worker.tests.test_graph import BAD_LISTING, GOOD_LISTING, GOOD_PAGE, NONA
from app.enums import AuditOutcome, StepType

RUN_ID = 7


async def run_traced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    html: str | None,
    script: dict[Any, list[Any]],
    *,
    url: str | None = None,
    stager: RecordingStager | None = None,
    audit: RecordingAudit | None = None,
    snapshots: RecordingSnapshots | None = None,
) -> tuple[VenueGraphState, RecordingAudit, RecordingStager]:
    """Run the real graph on `html` (or `url`) with the scripted model and recording stores.

    `audit` and `snapshots` are passed in by the tests that need to inspect them even when the run raises (C9): the
    return value is never reached then. Without `snapshots` the context's default store is used (writes nothing).
    """
    if url is None:
        assert html is not None
        path = tmp_path / "page.html"
        path.write_text(html)
        url = str(path)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client(script))
    audit, stager = audit or RecordingAudit(), stager or RecordingStager()
    state = VenueGraphState(
        venue_id=1,
        calendar_url=url,
        venue_name="The Venue",
        metro_timezone="America/Chicago",
        fetched_on=fakes.FETCHED,
        run_id=RUN_ID,
        policy=fakes.THREE_ATTEMPTS,
    )
    extra: dict[str, Any] = {"snapshots": snapshots} if snapshots is not None else {}
    result = await compiled_graph.ainvoke(
        state, context=WorkerContext(audit=audit, stager=stager, reader=FakeReader(), writer=FakeWriter(), **extra)
    )
    return VenueGraphState(**result), audit, stager


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_a_clean_page_writes_one_row_per_node_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: build plan A4, "an `audit_log` write from each of the six nodes" (five run on a pass): one
    # row each for fetch, extract, validate, reconcile, commit, in graph order, all attempt 1, all carrying
    # the run id from the state. The row order is what makes `ORDER BY id` read as a timeline.
    page = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))
    _, audit, stager = await run_traced(tmp_path, monkeypatch, page, {SPLITTER: [NONA]})
    assert audit.steps() == [("fetch", 1), ("extract", 1), ("validate", 1), ("reconcile", 1), ("commit", 1)]
    assert {e.run_id for e in audit.entries} == {RUN_ID}
    assert len(stager.documents) == 1


async def test_the_extract_row_links_to_its_staging_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A4-D4): `detail.staging_id` on the extract row is the id the stager returned, and the document
    # behind it is that attempt's (its attempt number and run id), so the two stores join.
    page = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))
    _, audit, stager = await run_traced(tmp_path, monkeypatch, page, {SPLITTER: [NONA]})
    extract_row = next(e for e in audit.entries if e.step_type is StepType.EXTRACT)
    assert extract_row.detail["staging_id"] == "doc-1"
    assert (stager.documents[0]["attempt"], stager.documents[0]["run_id"]) == (1, RUN_ID)


async def test_non_extract_rows_have_no_staging_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: only extract stages. Other rows must not carry a `staging_id`, or a query joining on it would
    # chase a document that was never written.
    page = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))
    _, audit, _ = await run_traced(tmp_path, monkeypatch, page, {SPLITTER: [NONA]})
    for entry in audit.entries:
        if entry.step_type is not StepType.EXTRACT:
            assert "staging_id" not in entry.detail


# ---------------------------------------------------------------------------
# Retries add rows (append-only)
# ---------------------------------------------------------------------------


async def test_a_retry_adds_rows_and_a_document_per_attempt_failed_one_included(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A4-K3, "append-only", A4-D4): the attempt whose model call raised is staged too, with its error,
    # so a person debugging an escalation has the failed attempt's record. Attempt 2 adds its own extract
    # and validate rows next to attempt 1's instead of replacing them: the retry history survives. Each
    # document carries its own attempt number and error (which also catches staging before the node runs,
    # when a document would carry the previous attempt's fields).
    script: dict[Any, list[Any]] = {
        PAGE: [ValueError("the model server went away"), listings_answer(GOOD_LISTING)],
        SPLITTER: [NONA],
    }
    _, audit, stager = await run_traced(tmp_path, monkeypatch, GOOD_PAGE, script)
    assert audit.steps() == [
        ("fetch", 1),
        ("extract", 1),
        ("validate", 1),
        ("extract", 2),
        ("validate", 2),
        ("reconcile", 2),
        ("commit", 2),
    ]
    assert [(d["attempt"], d["error"] is not None) for d in stager.documents] == [(1, True), (2, False)]
    assert "went away" in stager.documents[0]["error"]
    ids = [e.detail["staging_id"] for e in audit.entries if e.step_type is StepType.EXTRACT]
    assert ids == ["doc-1", "doc-2"]


async def test_the_failed_attempts_rows_say_it_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: attempt 1's extract row carries the error and its validate row a failed verdict with the
    # `extract_failed` reason, and the passing attempt 2's validate row says passed.
    script: dict[Any, list[Any]] = {
        PAGE: [ValueError("the model server went away"), listings_answer(GOOD_LISTING)],
        SPLITTER: [NONA],
    }
    _, audit, _ = await run_traced(tmp_path, monkeypatch, GOOD_PAGE, script)
    validates = [e for e in audit.entries if e.step_type is StepType.VALIDATE]
    assert validates[0].detail["verdict"] == "failed" and validates[0].detail["reasons"] == ["extract_failed"]
    assert validates[1].detail["verdict"] == "passed"
    extracts = [e for e in audit.entries if e.step_type is StepType.EXTRACT]
    assert "went away" in extracts[0].detail["error"] and extracts[1].detail["error"] is None


async def test_a_check_error_at_high_confidence_is_recorded_with_its_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: a deterministic check failure at 0.99 model confidence (A3-D9) leaves a validate row with a
    # failed verdict, the check-errors reason, and the 0.990 confidence, so A8 can see a confident model
    # being wrong. Three attempts at the cap, then escalate.
    script = {PAGE: [listings_answer(BAD_LISTING)], SPLITTER: [NONA]}
    _, audit, _ = await run_traced(tmp_path, monkeypatch, GOOD_PAGE, script)
    first = next(e for e in audit.entries if e.step_type is StepType.VALIDATE)
    assert first.detail["reasons"] == ["check_errors"] and str(first.confidence) == "0.990"


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


async def test_exhausting_the_cap_ends_with_one_escalate_row_and_its_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A4-D5, Departure 1): three failed attempts, then one `escalate` row with outcome 'escalated'
    # and the same reason text as `state.escalation_reason`, entity = the venue. No reconcile or commit.
    boom = fakes.connection_error()
    state, audit, stager = await run_traced(tmp_path, monkeypatch, GOOD_PAGE, {PAGE: [boom]})
    assert audit.steps() == [
        ("fetch", 1),
        ("extract", 1),
        ("validate", 1),
        ("extract", 2),
        ("validate", 2),
        ("extract", 3),
        ("validate", 3),
        ("escalate", 3),
    ]
    escalate = audit.entries[-1]
    assert escalate.outcome is AuditOutcome.ESCALATED
    assert escalate.detail["reason"] == state.escalation_reason
    assert len(stager.documents) == 3


async def test_an_unreadable_page_writes_fetch_then_escalate_and_never_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: a fetch failure leaves the fetch row (with the error) and the escalate row, no extract row,
    # and no staging document (nothing was extracted). Green even while A4-K3 is open.
    state, audit, stager = await run_traced(
        tmp_path,
        monkeypatch,
        None,
        {},
        url=str(tmp_path / "missing.html"),
    )
    assert audit.steps() == [("fetch", 1), ("escalate", 1)]
    assert audit.entries[0].detail["error"] is not None and audit.entries[1].outcome is AuditOutcome.ESCALATED
    assert stager.documents == [] and state.escalation_reason is not None


async def test_an_empty_page_is_a_fetch_row_with_the_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: the empty-page rule (arch-initial.md §7) shows in the trail as a fetch error, not as a
    # confirmed-empty extraction. Green even while A4-K3 is open.
    _, audit, _ = await run_traced(tmp_path, monkeypatch, "<html><body>  </body></html>", {})
    # The stored text starts with the exception's class name (`f"{type(err).__name__}: ..."` in `fetch_node`), so a
    # rename of that class (PQR1-17) shows up here instead of silently changing the trail.
    assert audit.entries[0].detail["error"].startswith("EmptyPageError:")
    assert "nothing to read" in audit.entries[0].detail["error"]


# ---------------------------------------------------------------------------
# A store that fails stops the run
# ---------------------------------------------------------------------------


async def test_a_staging_write_that_fails_stops_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A4-D3): a run whose raw record can't be kept does not continue unaudited. The stager's error
    # propagates out of `ainvoke`, and no validate row exists for the attempt that could not be staged.
    page = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))
    path = tmp_path / "page.html"
    path.write_text(page)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [NONA]}))
    audit = RecordingAudit()
    state = VenueGraphState(
        venue_id=1,
        calendar_url=str(path),
        venue_name="The Venue",
        metro_timezone="America/Chicago",
        fetched_on=fakes.FETCHED,
        run_id=RUN_ID,
    )
    with pytest.raises(RuntimeError, match="staging store is down"):
        await compiled_graph.ainvoke(
            state,
            context=WorkerContext(
                audit=audit, stager=RecordingStager(fail=True), reader=FakeReader(), writer=FakeWriter()
            ),
        )
    assert StepType.VALIDATE.value not in [s for s, _ in audit.steps()]


# ---------------------------------------------------------------------------
# The page snapshot (C9-T11, C9-D1, C9-D4, C9-D6)
# ---------------------------------------------------------------------------

ONE_SHOW_PAGE = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))


async def test_the_fetch_row_carries_the_key_the_store_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (C9-T11, C9-D6, C9-D4): after a clean fetch the page goes to the snapshot store, EXACTLY the page's text,
    # once, and the fetch row carries the key (and the size and hash) the store returned. No other step's row carries a
    # key: only a fetch has a page behind it. This is the deployment plan's first C9 test (a fake object store receives
    # the page and its key lands on the audit row). The fake returns a recognizable key, so a row that carried
    # a recomputed or empty key would fail here.
    audit = RecordingAudit()
    snapshots = RecordingSnapshots(audit=audit)
    _, audit, _ = await run_traced(
        tmp_path, monkeypatch, ONE_SHOW_PAGE, {SPLITTER: [NONA]}, audit=audit, snapshots=snapshots
    )
    assert snapshots.pages == [ONE_SHOW_PAGE]
    assert snapshots.calls == [{"venue_id": 1, "fetched_on": fakes.FETCHED, "run_id": RUN_ID}]
    fetch = audit.entries[0]
    assert fetch.step_type is StepType.FETCH
    assert fetch.snapshot_key == "fake/1/1.html"
    assert fetch.detail["snapshot"] == {"bytes": len(ONE_SHOW_PAGE.encode()), "sha256": "f" * 64}
    assert [e.snapshot_key for e in audit.entries[1:]] == [None] * (len(audit.entries) - 1)


async def test_the_snapshot_is_written_before_the_fetch_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C9-D6, mutation C9-M2): the put happens BEFORE the fetch row is appended, because the row records the key
    # and so the object must exist first; a row written first and a put after it could leave a row pointing at nothing.
    # The fake counts the audit rows that existed when the put arrived: none yet.
    audit = RecordingAudit()
    snapshots = RecordingSnapshots(audit=audit)
    await run_traced(tmp_path, monkeypatch, ONE_SHOW_PAGE, {SPLITTER: [NONA]}, audit=audit, snapshots=snapshots)
    assert snapshots.rows_at_put == [0]


async def test_a_failed_fetch_stores_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C9-T11, C9-D4, C9-D6): a fetch that failed (an empty page) never calls the store and its row has no key. The
    # trap: `fetch_node` assigns `page_html` BEFORE it raises `EmptyPageError`, so `page_html` alone is not the test
    # (C9-PR1-3); a write that checked only `page_html` would store an empty page and the row would claim a snapshot.
    snapshots = RecordingSnapshots()
    _, audit, _ = await run_traced(tmp_path, monkeypatch, "<html><body>  </body></html>", {}, snapshots=snapshots)
    assert snapshots.calls == []
    assert audit.entries[0].snapshot_key is None


async def test_a_store_that_raises_leaves_the_fetch_row_then_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (C9-D1, C9-D14, C9-T11): when the page cannot be stored, the fetch row is STILL written, with a NULL key and
    # `detail.snapshot_error` holding the failure's kind, code and message (so the audit trail says what R2 refused, and
    # the log is not the only record), and THEN the run stops with the `SnapshotError`: no extract row, no staging
    # document, nothing committed for that venue that day. A page that cannot be audited does not proceed.
    audit = RecordingAudit()
    stager = RecordingStager()
    error = SnapshotError("could not store venues/1/x.html: refused", kind="transient", code="SlowDown")
    with pytest.raises(SnapshotError):
        await run_traced(
            tmp_path,
            monkeypatch,
            ONE_SHOW_PAGE,
            {SPLITTER: [NONA]},
            audit=audit,
            stager=stager,
            snapshots=RecordingSnapshots(audit=audit, fail=error),
        )
    assert audit.steps() == [("fetch", 1)]
    row = audit.entries[0]
    assert row.snapshot_key is None
    assert row.detail["snapshot_error"] == {
        "kind": "transient",
        "code": "SlowDown",
        "message": "could not store venues/1/x.html: refused",
    }
    assert "snapshot" not in row.detail
    assert stager.documents == []


async def test_the_default_store_lets_a_state_with_no_run_id_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves (C9-D4, C9-D6): with the default store (writes nothing) a hand-built state whose `run_id` is None still runs
    # to the end and leaves a fetch row with no key. The `ValueError` for a missing run id belongs to the REAL store only
    # (`test_snapshots.py`), so the many existing tests and `local_test.py`, which build states without a run id, are
    # unaffected by C9.
    path = tmp_path / "page.html"
    path.write_text(ONE_SHOW_PAGE)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [NONA]}))
    audit = RecordingAudit()
    state = VenueGraphState(
        venue_id=1,
        calendar_url=str(path),
        venue_name="The Venue",
        metro_timezone="America/Chicago",
        fetched_on=fakes.FETCHED,
        run_id=None,
    )
    await compiled_graph.ainvoke(
        state,
        context=WorkerContext(audit=audit, stager=RecordingStager(), reader=FakeReader(), writer=FakeWriter()),
    )
    assert audit.entries[0].step_type is StepType.FETCH and audit.entries[0].snapshot_key is None


# ---------------------------------------------------------------------------
# The wrapper keeps the runtime parameter
# ---------------------------------------------------------------------------


async def test_the_context_reaches_the_audited_nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: the known gotcha (plan, "Known gotchas"): LangGraph injects `runtime` by inspecting the node's
    # signature, so a wrapper built with `functools.wraps` (which copies the inner node's signature, with no
    # `runtime`) makes LangGraph skip the injection and the call fail with a `TypeError` about the missing
    # `runtime` argument (verified). Here the recorders are populated, so the context arrived.
    page = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))
    _, audit, _ = await run_traced(tmp_path, monkeypatch, page, {SPLITTER: [NONA]})
    assert audit.entries, "no audit rows: the WorkerContext never reached the wrapper"
