"""Tests for the calendar writer: one show per transaction, with its audit rows inside it, and what survives a failure.

Milestone A6 (docs/dev/implementations/a6-commit.md, Test approach §3). `PostgresCalendarWriter.write_show` is the only
code that writes `show`, `show_artist` and `artist`, so it is tested against the real `calendar_test` schema rather than
a mock (style guide: "Mocking the database in integration tests" is an anti-pattern). Each test rides on the rolled-back
transaction of `db_conn` (app/testing/db.py); a session factory bound to that connection in savepoint mode makes the
writer's `begin()` a savepoint, so a rolled-back write is really rolled back while the outer rollback still undoes
everything. `write_plan` (the loop) is tested here too, with the real writer where the database matters and with
`fakes.FakeWriter` where only the loop does.

How to read it, top to bottom:
  1. Setup: `world` seeds a venue, two artists (Nona, Zhora) and an open run; `ops_for` builds the operations the way the
     pipeline does (the real reader, `reconcile` and `commit.build_ops`), so a test states only the listing it is about.
  2. The writes (A6-K1): insert, update, remove, the snapshots, atomicity, the errors the database raises, revert.
  3. `write_plan` and failures (A6-K2): a shared new artist, a rolled-back artist, one bad show, a lost connection.
  4. `is_decision_error` on the shapes the driver really produces.

Expected values come from `data-model-initial.md` (columns, §3 snapshots), the A5 and A6 decisions, and the literal inputs,
never from the code under test. The helpers use `polyfactory` for filler columns only (names, dates and times are explicit,
so the expected values do not depend on a random seed: A5-PR1-15). Rows that are updated are seeded with a literal past
`updated_at`, because inside the test transaction `now()` is the transaction's start and never moves (A6-PR1-3).
"""

import dataclasses
import datetime
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker.audit import PostgresAuditWriter
from agent_worker.calendar_reader import PostgresCalendarReader
from agent_worker.calendar_writer import (
    PostgresCalendarWriter,
    ShowGone,
    is_decision_error,
    write_plan,
)
from agent_worker.commit import SNAPSHOT_COLUMNS, ShowOp, build_ops, snapshot_of
from agent_worker.reconcile import LineupEntry
from agent_worker.tests import fakes
from agent_worker.tests.fakes import FakeWriter, RecordingAudit
from agent_worker.tests.reconcile_support import URL, at, day, listed, plan_for
from agent_worker.tests.test_calendar_reader import make_artist, make_show
from app.db.models import Artist, AuditLog, Show, ShowArtist, Venue
from app.db.seed import seed
from app.enums import AuditOutcome, EntityType, RunTrigger, ShowStatus, StepType

# The literal `updated_at` every show that gets updated is seeded with: any real "now" is after it.
LONG_AGO = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


@pytest.fixture
def factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory on the test connection in savepoint mode (see test_audit_writer.py): the writer's `begin()`
    becomes a savepoint, so a rollback inside it is real and the outer test transaction still ends everything."""
    return async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


@dataclass(frozen=True)
class World:
    """What every test starts from: one venue, two stored artists and an open run (the FK `audit_log.run_id` needs)."""

    venue_id: int
    artists: dict[str, int]
    run_id: int


@pytest_asyncio.fixture(loop_scope="session")
async def world(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[World]:
    async with factory() as session:
        await seed(session)
        venue_id = (await session.execute(select(Venue.id).order_by(Venue.id).limit(1))).scalar_one()
        stored = {name: make_artist(name) for name in ("Nona", "Zhora")}
        session.add_all(stored.values())
        await session.flush()
        ids = {name: artist.id for name, artist in stored.items()}
        await session.commit()
    run_id = await PostgresAuditWriter(factory).start_run(venue_id, RunTrigger.MANUAL)
    yield World(venue_id, ids, run_id)


async def seed_show(
    factory: async_sessionmaker[AsyncSession], w: World, date: datetime.date, start: datetime.time | None,
    acts: tuple[str, ...] = ("Nona",), status: ShowStatus = ShowStatus.ACTIVE, **fields: Any,
) -> int:
    """Store a show the way an earlier run would have, with `acts` (names from `world.artists`) as its lineup in order.
    `updated_at` is the literal past value so a test can see it move."""
    fields.setdefault("updated_at", LONG_AGO)
    async with factory() as session:
        show = make_show(w.venue_id, date, start, status, **fields)
        session.add(show)
        await session.flush()
        session.add_all(
            ShowArtist(show_id=show.id, artist_id=w.artists[name], sequence_number=i) for i, name in enumerate(acts, start=1)
        )
        await session.commit()
        return show.id


async def ops_for(factory: async_sessionmaker[AsyncSession], w: World, *listings: Any) -> tuple[ShowOp, ...]:
    """The operations the pipeline would make for these page listings against what is stored now: the real reader, the
    real reconcile and `build_ops`, so a test states only the listings it is about."""
    reader = PostgresCalendarReader(factory)
    stored = await reader.stored_shows(w.venue_id, datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
    plan = plan_for(list(listings), stored, await reader.artists())
    return build_ops(plan, w.venue_id, URL)


def writer_for(factory: async_sessionmaker[AsyncSession]) -> PostgresCalendarWriter:
    return PostgresCalendarWriter(factory)


async def show_row(factory: async_sessionmaker[AsyncSession], show_id: int) -> Show:
    async with factory() as session:
        row = await session.get(Show, show_id)
        assert row is not None
        return row


async def lineup_of(factory: async_sessionmaker[AsyncSession], show_id: int) -> list[tuple[int, int | None]]:
    """A show's lineup as (artist id, sequence number), in performance order."""
    async with factory() as session:
        rows = await session.execute(
            select(ShowArtist.artist_id, ShowArtist.sequence_number)
            .where(ShowArtist.show_id == show_id).order_by(ShowArtist.sequence_number)
        )
        return [(a, n) for a, n in rows.all()]


async def audit_of(factory: async_sessionmaker[AsyncSession], run_id: int) -> list[AuditLog]:
    async with factory() as session:
        return list((await session.execute(select(AuditLog).where(AuditLog.run_id == run_id).order_by(AuditLog.id))).scalars())


async def count(factory: async_sessionmaker[AsyncSession], model: Any, *where: Any) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


# ---------------------------------------------------------------------------
# The writes (A6-K1)
# ---------------------------------------------------------------------------


async def test_an_insert_writes_the_show_its_lineup_a_name_only_artist_and_two_audit_rows(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (build plan A6; data-model-initial.md §2, §3): a new show with one known act (Nona) and one new act (Sunny
    # Day) writes one `show` row with the listing's facts, its lineup in `show_artist` in order with sequence numbers, ONE
    # new `artist` row with only a name, and exactly two audit rows in order: the artist's (it exists before the show) and
    # the show's (previous null, new the snapshot a revert restores).
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Nona", "Sunny Day"], end_time=at(23)))
    written = await writer_for(factory).write_show(op, {}, run_id=world.run_id, attempt_number=1)

    show = await show_row(factory, written.show_id)
    assert (show.venue_id, show.date, show.start_time, show.end_time) == (world.venue_id, day(20), at(20), at(23))
    assert (show.status, show.original_url) == (ShowStatus.ACTIVE, URL)
    [new_artist_id] = written.created_artists.values()
    assert list(written.created_artists) == ["sunny day"]
    assert await lineup_of(factory, show.id) == [(world.artists["Nona"], 1), (new_artist_id, 2)]
    async with factory() as session:
        artist = await session.get(Artist, new_artist_id)
    assert artist is not None and artist.name == "Sunny Day"
    assert (artist.photo_url, artist.website, artist.hometown, artist.format, artist.repertoire) == (None,) * 5

    rows = await audit_of(factory, world.run_id)
    assert [(r.step_type, r.entity_type, r.entity_id, r.outcome) for r in rows] == [
        (StepType.COMMIT, EntityType.ARTIST, new_artist_id, AuditOutcome.INSERTED),
        (StepType.COMMIT, EntityType.SHOW, show.id, AuditOutcome.INSERTED),
    ]
    assert rows[0].new_value == {"id": new_artist_id, "name": "Sunny Day"} and rows[0].previous_value is None
    snap = rows[1].new_value
    assert rows[1].previous_value is None and snap is not None
    assert (snap["id"], snap["date"], snap["start_time"], snap["end_time"], snap["status"]) == (
        show.id, "2026-10-20", "20:00:00", "23:00:00", "active",
    )
    assert [(e["artist_id"], e["sequence_number"]) for e in snap["lineup"]] == [(world.artists["Nona"], 1), (new_artist_id, 2)]


async def test_an_update_changes_only_the_named_columns_and_leaves_the_lineup_alone(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A5-D4): an update sets the changed columns (a new end time and a day price) and nothing else: the lineup is
    # untouched (same rows), the start time stays, and `updated_at` moves from its seeded literal.
    show_id = await seed_show(factory, world, day(20), at(20), end_time=None)
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Nona"], end_time=at(23), admission_day=20.0))
    assert op.action.value == "update"
    await writer_for(factory).write_show(op, {}, run_id=world.run_id, attempt_number=1)

    show = await show_row(factory, show_id)
    assert (show.end_time, show.admission_day, show.start_time, show.admission_advance) == (at(23), Decimal("20.00"), at(20), None)
    assert await lineup_of(factory, show_id) == [(world.artists["Nona"], 1)]
    assert show.updated_at > LONG_AGO


async def test_a_lineup_only_update_replaces_the_lineup_and_still_moves_updated_at(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A6 "Settled details"): an opener added to a stored show replaces the lineup (both acts, in order) and no
    # `show` column changes, yet `updated_at` moves: an ORM update that changed no column would issue no UPDATE, so the
    # writer sets it explicitly. Asserted against the literal past value the row was seeded with (A6-PR1-3).
    show_id = await seed_show(factory, world, day(20), at(20))
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Zhora", "Nona"]))
    assert op.values == {} and op.lineup is not None
    await writer_for(factory).write_show(op, {}, run_id=world.run_id, attempt_number=1)

    assert await lineup_of(factory, show_id) == [(world.artists["Zhora"], 1), (world.artists["Nona"], 2)]
    assert (await show_row(factory, show_id)).updated_at > LONG_AGO


async def test_a_removal_keeps_the_row_and_its_lineup_and_a_return_sets_it_back_to_active(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A5-D6, A5-D7; data-model-initial.md §2 "Soft delete"): a removed show is `status = removed` with its row and
    # lineup still there, and the same show listed again is the same row back to `active`.
    show_id = await seed_show(factory, world, day(20), at(20))
    # The page lists a different show on the 24th, so the stored show on the 20th is absent from it (inside the window):
    # the plan has an insert for the new show and a removal of the stored one; only the removal is written here.
    [removal] = [op for op in await ops_for(factory, world, listed(0, day(24), at(20), acts=["Zhora"])) if op.stored_id == show_id]
    assert (removal.action.value, removal.reconcile_reason) == ("remove", "absent from the page")
    await writer_for(factory).write_show(removal, {}, run_id=world.run_id, attempt_number=1)
    assert (await show_row(factory, show_id)).status is ShowStatus.REMOVED
    assert await lineup_of(factory, show_id) == [(world.artists["Nona"], 1)]

    [back] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Nona"]))
    assert back.reconcile_reason == "reappeared"
    await writer_for(factory).write_show(back, {}, run_id=world.run_id, attempt_number=1)
    assert (await show_row(factory, show_id)).status is ShowStatus.ACTIVE


async def test_previous_value_is_the_row_before_the_change(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A6-K1, A6-M1): the snapshot taken BEFORE the write shows the old values and the one taken after shows the
    # new ones. The ORM hands back the same, mutated object after a change, so a `previous` read after the write would
    # equal `new_value`; here the end time is None before and 23:00 after, in the two columns of the same audit row.
    show_id = await seed_show(factory, world, day(20), at(20), end_time=None)
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Nona"], end_time=at(23)))
    await writer_for(factory).write_show(op, {}, run_id=world.run_id, attempt_number=1)
    [row] = [r for r in await audit_of(factory, world.run_id) if r.entity_id == show_id]
    assert row.outcome is AuditOutcome.UPDATED
    assert row.previous_value is not None and row.new_value is not None
    assert row.previous_value["end_time"] is None and row.new_value["end_time"] == "23:00:00"
    assert row.previous_value != row.new_value


async def test_a_failed_write_rolls_back_the_show_the_artist_and_the_audit_row(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A6-K1): a write that fails after its show was inserted leaves NOTHING. The lineup names an artist id that
    # does not exist, so the foreign key fails at the lineup flush, after the show insert and after a new artist
    # ("Sunny Day") was created. Afterwards there is no show, no new artist and no audit row. (This proves the DATA rolls
    # back; the failure comes before the audit rows are added, so the next test is the one about the audit rows.)
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Sunny Day"]))
    broken = dataclasses.replace(op, lineup=(LineupEntry("sunny day", None, "Sunny Day", None, 1), LineupEntry("x", 999_999, "x", None, 2)))
    with pytest.raises(IntegrityError):
        await writer_for(factory).write_show(broken, {}, run_id=world.run_id, attempt_number=1)
    assert await count(factory, Show, Show.venue_id == world.venue_id) == 0
    assert await count(factory, Artist, Artist.name == "Sunny Day") == 0
    assert await audit_of(factory, world.run_id) == []


class CountingFactory:
    """A session factory that counts how many sessions it hands out (wrapping the real one)."""

    def __init__(self, inner: async_sessionmaker[AsyncSession]) -> None:
        self.inner = inner
        self.sessions = 0

    def __call__(self) -> AsyncSession:
        self.sessions += 1
        return self.inner()


async def test_a_write_uses_exactly_one_session(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A6-K1, A6-M2): everything about one show, its audit rows included, goes through ONE session and so one
    # transaction. In these tests every session shares the test connection in savepoint mode, so a second session's
    # savepoint is nested inside the first and rolls back with it: a writer that wrote its audit rows through a second
    # session (`AuditWriter.record`) would look atomic here by accident. Counting the sessions is what catches it.
    counting = CountingFactory(factory)
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Nona"]))
    await PostgresCalendarWriter(counting).write_show(op, {}, run_id=world.run_id, attempt_number=1)  # type: ignore[arg-type]
    assert counting.sessions == 1


class FailsAfterTheAuditRows(PostgresCalendarWriter):
    """A writer whose audit rows are produced and THEN a database error is raised: the case a failure before the audit
    rows cannot reach. The correct writer has only added the rows to its transaction by then, so they roll back with it."""

    def _audit_rows(self, *args: Any, **kwargs: Any) -> Iterator[Any]:  # type: ignore[override]
        yield from super()._audit_rows(*args, **kwargs)
        raise fakes.check_violation()


async def test_audit_rows_roll_back_with_the_write(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A6-K1, A6-M2): the audit rows are in the SAME transaction as the change. The writer here raises right after
    # producing the real audit rows; with the rows only added to the transaction nothing survives (no show, no artist,
    # no audit row). A writer that wrote its audit rows through `AuditWriter.record` (its own session, committed at
    # once) or committed before adding them would leave rows for a show that was never written, and this test would fail.
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Sunny Day"]))
    with pytest.raises(IntegrityError):
        await FailsAfterTheAuditRows(factory).write_show(op, {}, run_id=world.run_id, attempt_number=1)
    assert await count(factory, Show, Show.venue_id == world.venue_id) == 0
    assert await count(factory, Artist, Artist.name == "Sunny Day") == 0
    assert await audit_of(factory, world.run_id) == []


async def test_a_check_constraint_violation_is_an_integrity_error_that_leaves_nothing(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (data-model-initial.md §2, `show_free_admission_check`): a show that is free AND priced is refused by the
    # table (reconcile and validation prevent it; this is the net under them). It is a class-23 integrity violation, a
    # decision error, and nothing is written.
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Nona"], free_admission=True, admission_day=10.0))
    with pytest.raises(IntegrityError) as caught:
        await writer_for(factory).write_show(op, {}, run_id=world.run_id, attempt_number=1)
    assert caught.value.orig.sqlstate == "23514" and is_decision_error(caught.value)  # type: ignore[union-attr]
    assert await count(factory, Show, Show.venue_id == world.venue_id) == 0


async def test_an_overflowing_price_is_a_plain_dbapi_error_with_a_class_22_sqlstate(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A6-PR1-1): a price that does not fit `Numeric(10, 2)` raises a plain `DBAPIError` (NOT `IntegrityError`, and
    # `DataError` never occurs on this driver) with SQLSTATE 22003, and `is_decision_error` calls it one show's problem.
    # Measured against the installed asyncpg dialect by the plan review, asserted here so a driver change is noticed.
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Nona"], admission_day=99_999_999_999.0))
    with pytest.raises(DBAPIError) as caught:
        await writer_for(factory).write_show(op, {}, run_id=world.run_id, attempt_number=1)
    assert not isinstance(caught.value, IntegrityError)
    assert caught.value.orig.sqlstate == "22003" and is_decision_error(caught.value)  # type: ignore[union-attr]
    assert await count(factory, Show, Show.venue_id == world.venue_id) == 0


async def test_a_vanished_show_is_a_show_gone_failure_not_an_attribute_error(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A6-PR1-7): an update naming a stored show that was deleted by hand between reconcile and commit raises
    # `ShowGone` from the FIRST (locked) read, which `is_decision_error` calls one show's failure, instead of a
    # `NoResultFound` or `AttributeError` that would look like a bug and stop the run.
    show_id = await seed_show(factory, world, day(20), at(20), end_time=None)
    [op] = await ops_for(factory, world, listed(0, day(20), at(20), acts=["Nona"], end_time=at(23)))
    async with factory() as session:
        await session.execute(delete(ShowArtist).where(ShowArtist.show_id == show_id))
        await session.execute(delete(Show).where(Show.id == show_id))
        await session.commit()
    with pytest.raises(ShowGone) as caught:
        await writer_for(factory).write_show(op, {}, run_id=world.run_id, attempt_number=1)
    assert is_decision_error(caught.value)


def restore_value(column: str, value: Any) -> Any:
    """A snapshot value back to the Python value its column holds (a test-only piece of what a revert would do): ISO
    strings to dates and times, the decimal string to a `Decimal`, the enum value to the enum."""
    if value is None:
        return None
    python_type = Show.__table__.c[column].type.python_type
    if python_type is datetime.date:
        return datetime.date.fromisoformat(value)
    if python_type is datetime.time:
        return datetime.time.fromisoformat(value)
    if python_type is Decimal:
        return Decimal(value)
    if python_type is ShowStatus:
        return ShowStatus(value)
    return value


async def restore(session: AsyncSession, snapshot: dict[str, Any]) -> None:
    """Test-only revert: put a show and its lineup back from a snapshot. The revert ACTION is deferred (arch-initial.md §7);
    this only proves a snapshot is enough to do it."""
    row = await session.get(Show, snapshot["id"])
    assert row is not None
    for column in SNAPSHOT_COLUMNS:
        if column != "id":
            setattr(row, column, restore_value(column, snapshot[column]))
    await session.flush()
    await session.execute(delete(ShowArtist).where(ShowArtist.show_id == row.id))
    session.add_all(
        ShowArtist(
            show_id=row.id, artist_id=e["artist_id"], sequence_number=e["sequence_number"],
            start_time=datetime.time.fromisoformat(e["start_time"]) if e["start_time"] else None,
        )
        for e in snapshot["lineup"]
    )
    await session.flush()


async def test_restoring_previous_value_reproduces_the_row_as_it_was(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (build plan A6: "those are what a future revert restores"): the snapshot is SUFFICIENT. A show with a price
    # and one act is updated (new end time, a different price, an opener added); restoring the audit row's
    # `previous_value` puts the columns and the lineup back, and a fresh snapshot equals `previous_value` exactly.
    show_id = await seed_show(factory, world, day(20), at(20), admission_day=Decimal("15.00"), end_time=None)
    [op] = await ops_for(
        factory, world, listed(0, day(20), at(20), acts=["Zhora", "Nona"], end_time=at(23), admission_day=18.5),
    )
    await writer_for(factory).write_show(op, {}, run_id=world.run_id, attempt_number=1)
    [row] = [r for r in await audit_of(factory, world.run_id) if r.entity_id == show_id]
    assert row.previous_value is not None
    assert row.new_value != row.previous_value
    async with factory() as session:
        await restore(session, row.previous_value)
        await session.commit()
    async with factory() as session:
        current = await session.get(Show, show_id)
        assert current is not None
        links = await session.execute(
            select(ShowArtist.artist_id, ShowArtist.start_time, ShowArtist.sequence_number).where(ShowArtist.show_id == show_id)
        )
        again = snapshot_of(
            {c: getattr(current, c) for c in SNAPSHOT_COLUMNS},
            [{"artist_id": a, "start_time": s, "sequence_number": n} for a, s, n in links.all()],
        )
    assert again == row.previous_value


# ---------------------------------------------------------------------------
# write_plan and failures (A6-K2)
# ---------------------------------------------------------------------------


async def test_a_new_artist_named_by_two_shows_is_created_once_and_both_link_to_it(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (requirements, "Agent Artist Creation & Matching"; A6-K2): "Sunny Day" on two shows is ONE artist row, and
    # the second show links to the id the first created (the loop hands the first show's created ids to the second).
    ops = await ops_for(
        factory, world, listed(0, day(20), at(20), acts=["Sunny Day"]), listed(1, day(21), at(20), acts=["Sunny Day"]),
    )
    result = await write_plan(ops, writer_for(factory), PostgresAuditWriter(factory), run_id=world.run_id, attempt_number=1)
    assert result.written == {"inserted": 2, "updated": 0, "removed": 0} and result.artists_created == 1
    assert await count(factory, Artist, Artist.name == "Sunny Day") == 1
    async with factory() as session:
        artist_ids = set((await session.execute(
            select(ShowArtist.artist_id).join(Show, Show.id == ShowArtist.show_id).where(Show.venue_id == world.venue_id)
        )).scalars())
    assert len(artist_ids) == 1


class FailsTheFirstWriteAfterCreatingItsArtist(PostgresCalendarWriter):
    """Fails its first write at the lineup step, AFTER the new artist was created in the transaction, with a database
    error that rolls the whole transaction back; later writes behave normally."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(factory)
        self.calls = 0

    async def _apply(self, session: AsyncSession, op: ShowOp, artist_ids: Any) -> int:
        self.calls += 1
        if self.calls == 1:
            raise fakes.check_violation()
        return await super()._apply(session, op, artist_ids)


async def test_a_rolled_back_artist_is_not_remembered(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A6-K1, A6-M3): the first show names a new artist and its write fails AFTER the artist was created; the
    # transaction rolls the artist back. The second show names the same artist, so it must create it AGAIN and link to
    # the new id. A writer that remembered the first, rolled-back id (a cache that outlives the transaction) would link
    # the second show to an artist that does not exist and fail on the foreign key.
    ops = await ops_for(
        factory, world, listed(0, day(20), at(20), acts=["Sunny Day"]), listed(1, day(21), at(20), acts=["Sunny Day"]),
    )
    result = await write_plan(
        ops, FailsTheFirstWriteAfterCreatingItsArtist(factory), PostgresAuditWriter(factory),
        run_id=world.run_id, attempt_number=1,
    )
    assert result.written["inserted"] == 1 and len(result.failures) == 1 and result.artists_created == 1
    assert await count(factory, Artist, Artist.name == "Sunny Day") == 1
    assert await count(factory, Show, Show.venue_id == world.venue_id) == 1
    [second_show] = (await PostgresCalendarReader(factory).stored_shows(world.venue_id, day(1), day(31)))
    assert second_show.date == day(21) and [e.artist_name for e in second_show.lineup] == ["Sunny Day"]


async def test_an_overflowing_price_fails_only_its_show(
    factory: async_sessionmaker[AsyncSession], world: World,
) -> None:
    # Proves (A6-D2; the A6-D2 scenario): of three new shows, the middle one has a price that overflows `Numeric(10, 2)`.
    # The other two are written, the bad one is not, and it is recorded: a failure row (no outcome, no snapshots) that says
    # WHICH show (October 21, 8 PM, an insert has no id), the SQLSTATE and the error; and the result has one failure.
    ops = await ops_for(
        factory, world,
        listed(0, day(20), at(20), acts=["Nona"]),
        listed(1, day(21), at(20), acts=["Zhora"], admission_day=99_999_999_999.0),
        listed(2, day(22), at(20), acts=["Nona"]),
    )
    result = await write_plan(ops, writer_for(factory), PostgresAuditWriter(factory), run_id=world.run_id, attempt_number=1)
    assert result.written["inserted"] == 2 and len(result.failures) == 1 and not result.all_failed
    stored = await PostgresCalendarReader(factory).stored_shows(world.venue_id, day(1), day(31))
    assert sorted(s.date.day for s in stored) == [20, 22]

    [failure_row] = [r for r in await audit_of(factory, world.run_id) if r.detail and r.detail.get("error")]
    assert (failure_row.step_type, failure_row.entity_type, failure_row.entity_id, failure_row.outcome) == (
        StepType.COMMIT, EntityType.SHOW, None, None,
    )
    assert failure_row.previous_value is None and failure_row.new_value is None
    assert failure_row.detail is not None
    assert (failure_row.detail["date"], failure_row.detail["time"], failure_row.detail["sqlstate"]) == (
        "2026-10-21", "20:00:00", "22003",
    )
    assert failure_row.detail["action"] == "insert" and "overflow" in failure_row.detail["error"]


@pytest.mark.parametrize(
    "error",
    [fakes.lost_connection(), fakes.connection_failure("08006"), fakes.connection_failure("57P01"), ValueError("a bug")],
    ids=["lost_connection", "08006", "57P01", "bug"],
)
async def test_a_connection_error_stops_the_run(error: BaseException) -> None:
    # Proves (A6-D2, A6-M6): a failure that is not about one row propagates and nothing after it is attempted. The first
    # write succeeds, the second raises, and the third is never tried. The errors are the real shapes the driver produces
    # (`fakes.lost_connection()` is an `InterfaceError` with `orig.sqlstate = None`: the shape a `getattr(..., "")[:2]`
    # implementation crashes on), plus a server-side connection error and a bare bug (a `ValueError`, not a `RuntimeError`: the scaffold's
    # `NotImplementedError` is a `RuntimeError`, which would be swallowed by `pytest.raises(RuntimeError)`).
    plan = plan_for([listed(i, day(20 + i), at(20), acts=["Nona"]) for i in range(3)])
    writer = FakeWriter(fail={1: error})
    with pytest.raises(type(error)):
        await write_plan(build_ops(plan, 1, URL), writer, RecordingAudit(), run_id=1, attempt_number=1)
    assert len(writer.ops) == 2


async def test_a_failing_show_is_recorded_and_skipped_and_the_loop_goes_on() -> None:
    # Proves (A6-D2): with a fake writer, a class-23 failure on the second of three operations is recorded (one failure
    # row through the audit writer, which identifies the show) and the first and third are still written.
    plan = plan_for([listed(i, day(20 + i), at(20), acts=["Nona"]) for i in range(3)])
    writer, audit = FakeWriter(fail={1: fakes.check_violation()}), RecordingAudit()
    result = await write_plan(build_ops(plan, 1, URL), writer, audit, run_id=1, attempt_number=1)
    assert result.written["inserted"] == 2 and len(writer.ops) == 3
    [failure] = result.failures
    assert (failure.date, failure.sqlstate, failure.action) == (day(21), "23514", "insert")
    [row] = audit.entries
    assert row.detail["date"] == "2026-10-21" and row.detail["sqlstate"] == "23514" and row.outcome is None


async def test_a_show_gone_error_in_the_loop_is_recorded_and_skipped_like_a_refused_row() -> None:
    # Proves (A6-D2, A6-PR1-7, A6-CR1-1): a stored show deleted by hand between reconcile and commit raises `ShowGone`
    # from the writer, which is one show's problem, not the run's: the other two writes happen, the failure is recorded
    # with no SQLSTATE (it is not a database error) and an error that names `ShowGone`, and one failure row says which
    # show. An A6-K2 that catches only `DBAPIError` lets it escape and stops the venue's run, and this test fails.
    plan = plan_for([listed(i, day(20 + i), at(20), acts=["Nona"]) for i in range(3)])
    writer, audit = FakeWriter(fail={1: ShowGone("show 3 is not in the calendar")}), RecordingAudit()
    result = await write_plan(build_ops(plan, 1, URL), writer, audit, run_id=1, attempt_number=1)
    assert result.written["inserted"] == 2 and len(writer.ops) == 3
    [failure] = result.failures
    assert (failure.date, failure.sqlstate) == (day(21), None) and failure.error.startswith("ShowGone:")
    [row] = audit.entries
    assert row.detail["sqlstate"] is None and row.detail["error"].startswith("ShowGone:") and row.outcome is None


async def test_an_all_failed_run_is_flagged() -> None:
    # Proves (A6-PR2-2): three operations that all fail set `all_failed` (it looks like a bug in the writes, not three bad
    # listings); two that all fail do not (too few to say).
    three = plan_for([listed(i, day(20 + i), at(20), acts=["Nona"]) for i in range(3)])
    result = await write_plan(
        build_ops(three, 1, URL), FakeWriter(fail={i: fakes.overflow() for i in range(3)}), RecordingAudit(),
        run_id=1, attempt_number=1,
    )
    assert result.all_failed and len(result.failures) == 3 and result.written["inserted"] == 0
    two = plan_for([listed(i, day(20 + i), at(20), acts=["Nona"]) for i in range(2)])
    result = await write_plan(
        build_ops(two, 1, URL), FakeWriter(fail={i: fakes.overflow() for i in range(2)}), RecordingAudit(),
        run_id=1, attempt_number=1,
    )
    assert len(result.failures) == 2 and not result.all_failed


async def test_the_artists_created_so_far_are_passed_to_each_later_write() -> None:
    # Proves (A6-K2): after a show creates "Sunny Day", the NEXT write is handed that artist's id (so it links instead of
    # creating again); the first write was handed none.
    plan = plan_for([listed(0, day(20), at(20), acts=["Sunny Day"]), listed(1, day(21), at(20), acts=["Sunny Day"])])
    writer = FakeWriter()
    await write_plan(build_ops(plan, 1, URL), writer, RecordingAudit(), run_id=1, attempt_number=1)
    assert writer.artist_ids_seen[0] == {} and list(writer.artist_ids_seen[1]) == ["sunny day"]


# ---------------------------------------------------------------------------
# is_decision_error, on the shapes the driver really produces (A6-PR2-1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (fakes.check_violation(), True),
        (fakes.foreign_key_violation(), True),
        (fakes.overflow(), True),
        (ShowGone("show 3 is not in the calendar"), True),
        (fakes.lost_connection(), False),
        (fakes.client_side_error(), False),
        (fakes.connection_failure("08006"), False),
        (fakes.connection_failure("57P01"), False),
        (RuntimeError("a bug"), False),
        (LookupError("not ours"), False),
    ],
    ids=["check", "fk", "overflow", "show_gone", "lost_connection", "client_side", "08006", "57P01", "bug", "lookup"],
)
def test_is_decision_error_on_the_real_shapes(error: BaseException, expected: bool) -> None:
    # Proves (A6-D2, A6-PR1-1, A6-PR2-1): the rule is the SQLSTATE class, 22 or 23, of the error's `orig`. The real lost
    # connection (an `InterfaceError` whose `orig.sqlstate` is `None` and which is `connection_invalidated`) is False AND
    # does not raise (a `getattr(err.orig, "sqlstate", "")[:2]` implementation raises `TypeError` on it); the same for a
    # client-side error with `sqlstate = None` that is NOT an invalidated connection (the case that tests the SQLSTATE
    # expression alone, since the invalidated flag is checked first: A6-PR2-1); a server-side
    # connection error (08006, 57P01), a bare bug and an unrelated `LookupError` are False; a vanished show is True.
    assert is_decision_error(error) is expected


def test_the_lost_connection_shape_is_what_the_driver_really_gives() -> None:
    # Proves: the helper's lost-connection error has the shape the plan review measured (an `InterfaceError`,
    # `orig.sqlstate` None, `connection_invalidated` True), so the tests above exercise the real case.
    error = fakes.lost_connection()
    assert isinstance(error, InterfaceError) and error.orig.sqlstate is None and error.connection_invalidated  # type: ignore[union-attr]
