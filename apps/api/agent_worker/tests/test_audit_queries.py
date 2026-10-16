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
from agent_worker.audit import PostgresAuditWriter
from agent_worker.context import WorkerContext
from agent_worker.main import VenueFacts, load_venues, run_venue
from agent_worker.state import VenueGraphState
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    PAGE,
    SPLITTER,
    RecordingStager,
    listings_answer,
    scripted_client,
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
    ctx = WorkerContext(audit=PostgresAuditWriter(factory), stager=RecordingStager())
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


def test_the_file_has_the_four_named_queries(queries: dict[str, str]) -> None:
    # Proves: the plan's four questions are all present under the names the plan gives them.
    assert set(queries) == {"run_history", "escalated_runs", "show_history", "unfinished_runs"}


async def test_run_history_lists_a_runs_steps_in_order_with_the_retry(
    db_conn: AsyncConnection, queries: dict[str, str], two_runs: Any,
) -> None:
    # Proves: "show me everything that happened in run N": one row per step in order, the retry as its own
    # rows (extract and validate for attempts 1 and 2), the failed attempt's error and verdict visible
    # without opening JSON by hand, and the staging id there to look up the raw record.
    passed, _, _ = two_runs
    rows = await run(db_conn, queries["run_history"], run_id=passed.run_id)
    assert [(r["step_type"], r["attempt_number"]) for r in rows] == [
        ("fetch", 1), ("extract", 1), ("validate", 1), ("extract", 2), ("validate", 2), ("reconcile", 2), ("commit", 2),
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
    # Proves: "what changed about this show and when". Nothing writes per-show rows until A6, so one is
    # inserted by hand, with a before and an after, for show 12; a row for show 13 must not appear.
    passed, _, _ = two_runs
    for show_id, new in ((12, {"time": "21:00"}), (13, {"time": "20:00"})):
        await db_conn.execute(insert(AuditLog).values(
            run_id=passed.run_id, step_type=StepType.COMMIT, source=AuditSource.AGENT,
            entity_type=EntityType.SHOW, entity_id=show_id, outcome=AuditOutcome.UPDATED,
            previous_value={"time": "20:00"}, new_value=new,
        ))
    rows = await run(db_conn, queries["show_history"], show_id=12)
    assert len(rows) == 1
    assert rows[0]["previous_value"] == {"time": "20:00"} and rows[0]["new_value"] == {"time": "21:00"}
    assert rows[0]["outcome"] == "updated"
    assert await run(db_conn, queries["show_history"], show_id=999) == []


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
