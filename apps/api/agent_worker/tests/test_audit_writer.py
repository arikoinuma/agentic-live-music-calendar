"""Tests for `PostgresAuditWriter` against a real Postgres: runs open and close, audit rows only append.

Milestone A4 (docs/dev/implementations/a4-auditability.md, Test approach §3). The writer is the one place
the audit trail touches the database, so it is tested against the real `calendar_test` schema rather than a
mock (style guide: "Mocking the database in integration tests" is an anti-pattern). Each test rides on the
rolled-back transaction of `db_conn` (app/testing/db.py), so nothing persists; a session factory bound to
that connection in savepoint mode lets the writer `commit()` as it does in production while the outer
rollback still undoes everything.

How to read it: `writer` is the object under test, `venue_id` a seeded venue (the FK target), and each test
reads rows back through a fresh session, the way the saved queries will. Expected values are literals from
`data-model-initial.md` §3.
"""

import decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker.audit import AuditEntry, PostgresAuditWriter
from app.db.models import AgentRun, AuditLog, Venue
from app.db.seed import seed
from app.enums import AuditOutcome, AuditSource, EntityType, RunTrigger, StepType


@pytest.fixture
def factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory on the test connection: `commit()` releases a savepoint, the outer rollback wins."""
    return async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def venue_id(factory: async_sessionmaker[AsyncSession]) -> int:
    """The first seeded venue's id (the FK `agent_run.venue_id` points at)."""
    async with factory() as session:
        await seed(session)
        await session.commit()
        return (await session.execute(select(Venue.id).order_by(Venue.id).limit(1))).scalar_one()


def entry(run_id: int, **changes: Any) -> AuditEntry:
    """An extract-step `AuditEntry` for `run_id` with sensible defaults; a test overrides what it cares about."""
    fields: dict[str, Any] = {
        "run_id": run_id, "attempt_number": 1, "step_type": StepType.EXTRACT, "source": AuditSource.AGENT,
        "entity_type": EntityType.VENUE, "entity_id": 1, "outcome": None, "model_used": "m",
        "confidence": None, "detail": {"route": "model"},
    }
    fields.update(changes)
    return AuditEntry(**fields)


async def rows(factory: async_sessionmaker[AsyncSession], run_id: int) -> list[AuditLog]:
    """The `audit_log` rows of one run, oldest first, read through a fresh session (as a query would)."""
    async with factory() as session:
        return list((await session.execute(select(AuditLog).where(AuditLog.run_id == run_id).order_by(AuditLog.id))).scalars())


async def test_start_run_inserts_an_open_run(factory: async_sessionmaker[AsyncSession], venue_id: int) -> None:
    # Proves: `start_run` creates the `agent_run` (the `parent_run_id`) with its trigger and `started_at`
    # set and `finished_at` NULL: "NULL while the run is in progress" (data-model-initial.md §3).
    run_id = await PostgresAuditWriter(factory).start_run(venue_id, RunTrigger.MANUAL)
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
    assert run is not None
    assert (run.venue_id, run.trigger) == (venue_id, RunTrigger.MANUAL)
    assert run.started_at is not None and run.finished_at is None


async def test_finish_run_sets_finished_at(factory: async_sessionmaker[AsyncSession], venue_id: int) -> None:
    # Proves: closing a run stamps `finished_at`, so "in progress" and "ended" are distinguishable.
    writer = PostgresAuditWriter(factory)
    run_id = await writer.start_run(venue_id, RunTrigger.SCHEDULED)
    await writer.finish_run(run_id)
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
    assert run is not None and run.finished_at is not None


async def test_record_appends_one_row_per_call_and_never_updates(
    factory: async_sessionmaker[AsyncSession], venue_id: int,
) -> None:
    # Proves: append-only (arch-initial.md §7): two writes of the same step and attempt make two rows with
    # distinct ids, and the first row is untouched by the second. A writer that upserted on
    # (run, step, attempt) would pass a single-write test and lose the retry history here.
    writer = PostgresAuditWriter(factory)
    run_id = await writer.start_run(venue_id, RunTrigger.MANUAL)
    first = await writer.record(entry(run_id, detail={"n": 1}))
    second = await writer.record(entry(run_id, detail={"n": 2}))
    assert first != second
    stored = await rows(factory, run_id)
    assert [r.detail for r in stored] == [{"n": 1}, {"n": 2}]


async def test_record_stores_every_field_including_jsonb_and_numeric(
    factory: async_sessionmaker[AsyncSession], venue_id: int,
) -> None:
    # Proves: each AuditEntry field lands in its column: the enums as their labels, `detail` round-trips as
    # JSONB (nested values intact), and `Decimal("0.857")` fits `Numeric(4, 3)` unchanged.
    writer = PostgresAuditWriter(factory)
    run_id = await writer.start_run(venue_id, RunTrigger.MANUAL)
    await writer.record(entry(
        run_id, attempt_number=3, step_type=StepType.ESCALATE, outcome=AuditOutcome.ESCALATED,
        model_used="gemma", confidence=decimal.Decimal("0.857"),
        detail={"reason": "x", "nested": {"reasons": ["a", "b"]}, "none": None},
    ))
    [row] = await rows(factory, run_id)
    assert (row.attempt_number, row.step_type, row.source) == (3, StepType.ESCALATE, AuditSource.AGENT)
    assert (row.entity_type, row.entity_id, row.outcome) == (EntityType.VENUE, 1, AuditOutcome.ESCALATED)
    assert row.model_used == "gemma" and row.confidence == decimal.Decimal("0.857")
    assert row.detail == {"reason": "x", "nested": {"reasons": ["a", "b"]}, "none": None}
    assert row.previous_value is None and row.new_value is None and row.snapshot_key is None


async def test_a_null_confidence_is_stored_as_null(factory: async_sessionmaker[AsyncSession], venue_id: int) -> None:
    # Proves: the A3-D9 rule survives the database: a None confidence is NULL in the row, not 0.000.
    writer = PostgresAuditWriter(factory)
    run_id = await writer.start_run(venue_id, RunTrigger.MANUAL)
    await writer.record(entry(run_id, confidence=None))
    [row] = await rows(factory, run_id)
    assert row.confidence is None


async def test_each_call_commits_so_a_later_failure_cannot_undo_it(
    factory: async_sessionmaker[AsyncSession], venue_id: int,
) -> None:
    # Proves: the writer commits per call (its docstring's reason: a crash later in the run must not roll
    # back the record of what led up to it). A second session, opened after the writer's own session
    # closed, sees the row; an uncommitted write would be invisible to it. (Visible here through the
    # shared test connection only because the writer released its savepoint.)
    writer = PostgresAuditWriter(factory)
    run_id = await writer.start_run(venue_id, RunTrigger.MANUAL)
    await writer.record(entry(run_id))
    async with factory() as other:
        count = (await other.execute(select(func.count()).select_from(AuditLog).where(AuditLog.run_id == run_id))).scalar_one()
    assert count == 1


def test_the_writer_has_no_method_that_changes_an_audit_row() -> None:
    # Proves: append-only by construction: the only mutating method on the writer other than inserts is
    # `finish_run`, which touches `agent_run`. There is no update/delete/replace of an audit row to call.
    names = {n for n in dir(PostgresAuditWriter) if not n.startswith("_")}
    assert names == {"start_run", "record", "finish_run"}


async def test_the_writer_works_with_a_default_session_factory(db_conn: AsyncConnection, venue_id: int) -> None:
    # Proves (A4-R2-4): the writer does not depend on the factory being built with
    # `expire_on_commit=False`. It reads each new row's id before committing, so a factory with SQLAlchemy's
    # default (`True`) works too. Reading `run.id` after `commit()` on such a factory raises `MissingGreenlet`,
    # an error that does not point at the cause; the next milestone to build its own factory would hit it.
    default_factory = async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint")
    writer = PostgresAuditWriter(default_factory)
    run_id = await writer.start_run(venue_id, RunTrigger.MANUAL)
    entry_id = await writer.record(entry(run_id))
    assert isinstance(run_id, int) and isinstance(entry_id, int)


async def test_finished_at_is_after_started_at_on_the_databases_own_clock(
    factory: async_sessionmaker[AsyncSession], venue_id: int,
) -> None:
    # Proves (A4-R2-5): both timestamps come from Postgres, so a run's duration is one clock's
    # difference and cannot go negative under worker/database clock skew. Inside the tests' one rolled-back
    # transaction `now()` is frozen at the transaction's start; `clock_timestamp()` (what `finish_run` uses)
    # is the real time, so it is strictly later than `started_at`. (This passes on the earlier Python-clock
    # version too, since the worker's clock is also later than the transaction start; the property it pins
    # is "after", the single-clock point is in `finish_run`'s comment.)
    writer = PostgresAuditWriter(factory)
    run_id = await writer.start_run(venue_id, RunTrigger.MANUAL)
    await writer.finish_run(run_id)
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
    assert run is not None and run.finished_at is not None and run.finished_at > run.started_at
