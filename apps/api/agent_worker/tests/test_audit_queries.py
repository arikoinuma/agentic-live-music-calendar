"""Executes every query in `docs/dev/audit-queries.sql` against real audit data.

Milestone A4 (docs/dev/implementations/a4-auditability.md, step 10; build plan A4: "being able to run
these is the real test of whether point 3 in §2 is met"). A saved query nobody runs rots. This test runs
two scripted pipeline runs through `run_venue` (one that retries once and passes, one that exhausts the cap
and escalates), then runs each saved query with its parameters bound and asserts the rows answer the
question the query is named for.

How to read it: `queries` parses the SQL file into `{name: text}` (comment lines dropped, since a `:word` in
a comment would be read as a bind parameter); `two_runs` creates the data; each test then asks one question.
Expected rows come from the scripts (what the fake model was told to do), never from the audit code. The
file's stability matters: the tests fail if a query is renamed or breaks, which is the point.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker import nodes
from agent_worker.artist_match import KnownArtist
from agent_worker.audit import PostgresAuditWriter
from agent_worker.calendar_writer import PostgresCalendarWriter
from agent_worker.context import WorkerContext
from agent_worker.main import VenueFacts, load_venues, run_venue
from agent_worker.state import VenueGraphState
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    ARTIST_MATCH,
    PAGE,
    SPLITTER,
    FakeReader,
    FakeWriter,
    RecordingStager,
    event,
    jsonld_page,
    listings_answer,
    scripted_client,
    split_answer,
)
from agent_worker.tests.test_graph import GOOD_LISTING, GOOD_PAGE, NONA
from app.db.models import AuditLog
from app.db.seed import seed
from app.enums import AuditOutcome, AuditSource, EntityType, StepType

SQL_FILE = Path(__file__).resolve().parents[4] / "docs" / "dev" / "audit-queries.sql"


def parse_queries(sql: str) -> dict[str, str]:
    """`-- name: x` starts a query; comment lines are dropped; a query runs to the next name."""
    queries: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in sql.splitlines():
        header = re.match(r"--\s*name:\s*(\w+)\s*$", line)
        if header:
            current = queries.setdefault(header.group(1), [])
        elif current is not None and not line.strip().startswith("--"):
            current.append(line)
    return {name: "\n".join(body).strip() for name, body in queries.items()}


@pytest.fixture(scope="module")
def queries() -> dict[str, str]:
    """The saved queries from docs/dev/audit-queries.sql, parsed once per module: name -> runnable SQL."""
    return parse_queries(SQL_FILE.read_text())


@pytest.fixture
def factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory on the test connection (`db_conn`, app/testing/db.py), in savepoint mode.

    The worker's writer opens its own session per call and `commit()`s each one. Here every such commit only
    releases a savepoint inside `db_conn`'s outer transaction, which the fixture rolls back at the end of the
    test, so the writes are real (visible to the next session on this connection) and leave nothing behind.
    """
    return async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def two_runs(
    factory: async_sessionmaker[AsyncSession], db_conn: AsyncConnection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[VenueGraphState, VenueGraphState, VenueFacts]:
    """Run 1 retries once and passes; run 2 fails all three attempts and escalates (venues 1 and 2)."""
    async with factory() as session:
        await seed(session)
        await session.commit()
        venues = await load_venues(session)
    ctx = WorkerContext(
        audit=PostgresAuditWriter(factory), stager=RecordingStager(), reader=FakeReader(),
        writer=PostgresCalendarWriter(factory),  # a real commit, so the trail holds real commit rows (A6)
    )
    page = tmp_path / "page.html"
    page.write_text(GOOD_PAGE)

    monkeypatch.setattr(nodes, "instructor_client", scripted_client({
        PAGE: [ValueError("the model server went away"), listings_answer(GOOD_LISTING)], SPLITTER: [NONA],
    }))
    passed = await run_venue(venues[0], ctx, calendar_url=str(page), fetched_on=fakes.FETCHED)

    monkeypatch.setattr(nodes, "instructor_client", scripted_client({PAGE: [ValueError("still down")]}))
    escalated = await run_venue(venues[1], ctx, calendar_url=str(page), fetched_on=fakes.FETCHED)
    return passed, escalated, venues[1]


async def run(conn: AsyncConnection, sql: str, **params: Any) -> list[Any]:
    """Execute a saved query with only the parameters it names (extra binds would be an error)."""
    wanted = set(re.findall(r":(\w+)", sql))
    result = await conn.execute(text(sql), {k: v for k, v in params.items() if k in wanted})
    return list(result.mappings())


def test_the_file_has_the_six_named_queries(queries: dict[str, str]) -> None:
    # Proves: the plan's four questions (A4), A5's fifth (the model's artist decisions) and A6's sixth (the shows the
    # database refused) are all present under the names the plans give them.
    assert set(queries) == {
        "run_history", "escalated_runs", "show_history", "unfinished_runs", "artist_match_decisions", "failed_commits",
    }


async def test_run_history_lists_a_runs_steps_in_order_with_the_retry(
    db_conn: AsyncConnection, queries: dict[str, str], two_runs: Any,
) -> None:
    # Proves: "show me everything that happened in run N": one row per step in order, the retry as its own
    # rows (extract and validate for attempts 1 and 2), the failed attempt's error and verdict visible
    # without opening JSON by hand, and the staging id there to look up the raw record.
    passed, _, _ = two_runs
    rows = await run(db_conn, queries["run_history"], run_id=passed.run_id)
    assert [(r["step_type"], r["attempt_number"]) for r in rows] == [
        ("fetch", 1), ("extract", 1), ("validate", 1), ("extract", 2), ("validate", 2), ("reconcile", 2),
        ("commit", 2), ("commit", 2), ("commit", 2),  # A6: the new artist (Nona), the show, then the run's summary
    ]
    extract1, validate1, validate2 = rows[1], rows[2], rows[4]
    assert "went away" in extract1["error"] and extract1["staging_id"] == "doc-1"
    assert validate1["verdict"] == "failed" and validate1["reasons"] == '["extract_failed"]'
    assert validate2["verdict"] == "passed"


async def test_run_history_only_returns_that_run(
    db_conn: AsyncConnection, queries: dict[str, str], two_runs: Any,
) -> None:
    # Proves: the :run_id filter works: the escalated run's history has no commit step.
    _, escalated, _ = two_runs
    rows = await run(db_conn, queries["run_history"], run_id=escalated.run_id)
    assert "commit" not in [r["step_type"] for r in rows] and rows[-1]["step_type"] == "escalate"


async def test_escalated_runs_names_the_run_the_venue_and_the_reason(
    db_conn: AsyncConnection, queries: dict[str, str], two_runs: Any,
) -> None:
    # Proves: "which runs escalated and why": exactly the escalated run (the passing one is absent), with
    # its venue's name, three attempts, and a reason that says what failed.
    _, escalated, venue = two_runs
    rows = await run(db_conn, queries["escalated_runs"])
    assert [r["run_id"] for r in rows] == [escalated.run_id]
    assert rows[0]["venue"] == venue.name and rows[0]["attempts"] == 3
    assert "still down" in rows[0]["reason"]


async def test_show_history_finds_a_shows_rows_and_nothing_else(
    db_conn: AsyncConnection, queries: dict[str, str], two_runs: Any,
) -> None:
    # Proves: "what changed about this show and when", against the row A6's commit really wrote (the passing run
    # inserted Nona's show on October 20 at 8 PM): one row, an insert, no previous value and the snapshot as the new
    # one, and no row for a show that doesn't exist. A hand-inserted row for another show must not appear.
    passed, _, _ = two_runs
    show_id = (await db_conn.execute(text(
        "SELECT entity_id FROM audit_log WHERE run_id = :r AND step_type = 'commit' AND entity_type = 'show'"),
        {"r": passed.run_id})).scalar_one()
    await db_conn.execute(insert(AuditLog).values(
        run_id=passed.run_id, step_type=StepType.COMMIT, source=AuditSource.AGENT, entity_type=EntityType.SHOW,
        entity_id=show_id + 1, outcome=AuditOutcome.UPDATED, previous_value={"time": "20:00"}, new_value={"time": "21:00"},
    ))
    rows = await run(db_conn, queries["show_history"], show_id=show_id)
    assert len(rows) == 1 and rows[0]["outcome"] == "inserted" and rows[0]["previous_value"] is None
    assert rows[0]["new_value"]["date"] == "2026-10-20" and rows[0]["new_value"]["start_time"] == "20:00:00"
    assert rows[0]["new_value"]["status"] == "active" and len(rows[0]["new_value"]["lineup"]) == 1
    assert await run(db_conn, queries["show_history"], show_id=999_999) == []


async def test_unfinished_runs_finds_open_runs_and_closed_runs_that_never_ended_properly(
    db_conn: AsyncConnection, queries: dict[str, str], two_runs: Any,
) -> None:
    # Proves: neither scripted run is "unfinished" (the passing one reached commit, the other escalate,
    # and both closed). Then an open run (no finished_at) and a closed run with only a fetch row are added,
    # and both are found, each with its furthest step: the crash signature A4-D8 describes.
    passed, _, venue = two_runs
    assert await run(db_conn, queries["unfinished_runs"]) == []
    open_id = (await db_conn.execute(text(
        "INSERT INTO agent_run (venue_id, trigger) VALUES (:v, 'manual') RETURNING id"), {"v": venue.id})).scalar_one()
    crashed_id = (await db_conn.execute(text(
        "INSERT INTO agent_run (venue_id, trigger, finished_at) VALUES (:v, 'manual', now()) RETURNING id"),
        {"v": venue.id})).scalar_one()
    await db_conn.execute(text(
        "INSERT INTO audit_log (run_id, step_type, source) VALUES (:r, 'fetch', 'agent')"), {"r": crashed_id})
    rows = await run(db_conn, queries["unfinished_runs"])
    assert {r["run_id"]: r["furthest_step"] for r in rows} == {open_id: None, crashed_id: "fetch"}
    assert passed.run_id not in {r["run_id"] for r in rows}


async def test_artist_match_decisions_lists_what_the_model_decided_and_nothing_else(
    db_conn: AsyncConnection, factory: async_sessionmaker[AsyncSession], queries: dict[str, str], two_runs: Any,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A5-D11): after a run in which the model decided one artist ("Zhora Band" is the stored "Zhora", 0.9),
    # the query returns exactly that decision, with the venue, the artist it linked, the model, the confidence and the
    # reason, and none of the rows from the two earlier runs (which asked the model nothing). The expected row is the
    # script: what the fake model was told to say.
    async with factory() as session:
        venues = await load_venues(session)
    ctx = WorkerContext(
        audit=PostgresAuditWriter(factory), stager=RecordingStager(),
        reader=FakeReader(artists=[KnownArtist(8, "Zhora")]), writer=FakeWriter(),
    )
    page = tmp_path / "zhora.html"
    page.write_text(jsonld_page(event("Zhora Band", "2026-10-20T20:00:00-05:00")))
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({
        SPLITTER: [split_answer(("Zhora Band", ["Zhora Band"]))],
        ARTIST_MATCH: [{"matched_artist_id": 8, "confidence": 0.9, "reason": "same band, longer name"}],
    }))
    state = await run_venue(venues[2], ctx, calendar_url=str(page), fetched_on=fakes.FETCHED)
    [row] = await run(db_conn, queries["artist_match_decisions"])
    assert (row["run_id"], row["venue"], row["artist_id"]) == (state.run_id, venues[2].name, 8)
    assert (row["incoming_name"], row["outcome"], row["reason"]) == ("Zhora Band", "matched_by_model", "same band, longer name")
    assert row["model_used"] and float(row["confidence"]) == pytest.approx(0.9)
    assert "Zhora" in row["candidates"]


async def test_a_run_that_crashed_mid_commit_is_unfinished(
    db_conn: AsyncConnection, queries: dict[str, str], two_runs: Any,
) -> None:
    # Proves (A6-M5): `unfinished_runs` counts only commit's SUMMARY row (the venue-level one) as "reached the end of
    # commit". A run that wrote one show and then died has a per-show `commit` row but no summary, and must still be
    # listed, with `commit` as its furthest step. If the query counted any `commit` row (as it did before A6), the
    # crashed run would read as finished and this test would fail.
    _, _, venue = two_runs
    run_id = (await db_conn.execute(text(
        "INSERT INTO agent_run (venue_id, trigger, finished_at) VALUES (:v, 'manual', now()) RETURNING id"),
        {"v": venue.id})).scalar_one()
    await db_conn.execute(text(
        "INSERT INTO audit_log (run_id, step_type, source, entity_type, entity_id, outcome) "
        "VALUES (:r, 'commit', 'agent', 'show', 1, 'inserted')"), {"r": run_id})
    rows = await run(db_conn, queries["unfinished_runs"])
    assert {r["run_id"]: r["furthest_step"] for r in rows} == {run_id: "commit"}


async def test_failed_commits_says_which_show_failed_and_why(
    db_conn: AsyncConnection, factory: async_sessionmaker[AsyncSession], queries: dict[str, str], two_runs: Any,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A6-D2, A6-PR2-3): after a run whose only write was refused (an overflowing price, SQLSTATE 22003), the query
    # returns that show's failure row with its date, time and SQLSTATE: enough to tell WHICH show failed even though an
    # insert has no id. The two earlier runs (a clean commit and an escalation) contribute nothing. The expected row is
    # the scripted failure: what the fake writer was told to raise, on the page's only show (October 20, 9 PM).
    async with factory() as session:
        venues = await load_venues(session)
    ctx = WorkerContext(
        audit=PostgresAuditWriter(factory), stager=RecordingStager(), reader=FakeReader(),
        writer=FakeWriter(fail={0: fakes.overflow()}),
    )
    page = tmp_path / "page.html"
    page.write_text(jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00")))
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [NONA]}))
    state = await run_venue(venues[2], ctx, calendar_url=str(page), fetched_on=fakes.FETCHED)
    assert state.commit_result is not None and len(state.commit_result.failures) == 1
    [row] = await run(db_conn, queries["failed_commits"])
    assert (row["run_id"], row["venue"], row["action"]) == (state.run_id, venues[2].name, "insert")
    assert (str(row["show_date"]), str(row["show_time"]), row["sqlstate"]) == ("2026-10-20", "21:00:00", "22003")
    assert "numeric field overflow" in row["error"]
