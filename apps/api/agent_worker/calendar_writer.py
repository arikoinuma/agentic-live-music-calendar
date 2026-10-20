"""Writing the calendar: commit's writes to Postgres, one show per transaction, each with its audit row inside it.

HOW TO READ THIS
  `commit.py` (pure) decides WHICH writes a plan asks for (`ShowOp`s). This module does them. It mirrors
  `calendar_reader.py`: a protocol the graph depends on, a Postgres implementation, and the loop that drives it.

  * `CalendarWriter` is the interface the graph writes through (`context.py` holds it with the audit writer, the stager
    and the reader). `PostgresCalendarWriter` is the real one; the graph tests use `fakes.FakeWriter`.
  * `PostgresCalendarWriter.write_show` writes ONE show in ONE transaction: the artists it is first to need, the `show`
    row, its lineup, and the `audit_log` rows that record all of it, with the row's snapshots from before and after
    (**A6-K1**). Nothing is visible until the transaction commits; any error rolls all of it back.
  * `write_plan` is the loop over a plan's operations. A show the database refuses (**A6-D2**) is recorded and the loop
    goes on; a lost connection or a bug stops the run (**A6-K2**).

WHY IT'S SHAPED THIS WAY
  * **The audit row is in the write's own transaction.** `AuditWriter.record` opens its own session and commits on its
    own, so using it here would let a rolled-back write leave a row for something that never happened, or a committed one
    lose its record. The per-show rows are added to the same session as the change (`audit.audit_row`).
  * **Snapshots are read from the database, inside the transaction.** The plan's `StoredShow` lacks most columns and may
    be seconds stale; `previous_value` has to be the row as it really was, locked for the transaction, and `new_value`
    what it really is after the flush. They are plain dicts, built at once, so a later change to the ORM object can't
    alter one already taken.
  * **A failure about one show is not a failure of the run.** What separates them is what the DATABASE says about the
    row (SQLSTATE class 22 or 23), not which Python class the driver raised: with asyncpg only integrity violations
    arrive as `IntegrityError`, an overflow is a plain `DBAPIError`, and a real lost connection is an `InterfaceError`
    whose `sqlstate` is None (`is_decision_error`).
  * **Nothing outlives a transaction except the return value.** The ids of the artists a show created go back in
    `ShowWritten`; the loop passes them to later shows only once the write has returned.

docs/dev/implementations/a6-commit.md.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.audit import (
    AuditEntry,
    AuditWriter,
    artist_created_entry,
    audit_row,  # noqa: F401  (used by A6-K1's block; the noqa goes when the gap is filled)
    show_failure_entry,
    show_write_entry,
)
from agent_worker.commit import (
    SNAPSHOT_COLUMNS,
    CommitResult,
    ShowFailure,
    ShowOp,
    snapshot_of,
)
from agent_worker.reconcile import Action
from app.db.models import Artist, Show, ShowArtist
from app.enums import AuditOutcome

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# What counts as "this show's problem" (A6-D2)
# ---------------------------------------------------------------------------

# SQLSTATE classes that say the database refused THIS ROW: 22 (a data exception, such as a price that overflows
# Numeric(10, 2) or a character the column can't hold) and 23 (an integrity violation: the CHECK, a foreign key, a NOT
# NULL). Everything else (08 connection, 57 operator intervention, ...) is about the database, not the row.
DECISION_SQLSTATE_CLASSES = ("22", "23")


class ShowGone(LookupError):
    """The stored show an update or removal names isn't there any more (deleted by hand between reconcile and commit).
    Raised by the writer so a vanished row is one show's failure, not an `AttributeError` that would look like a bug."""


def is_decision_error(err: BaseException) -> bool:
    """A failure about ONE show (A6-D2): the show vanished, or the database rejected its row by SQLSTATE class 22 / 23.

    Decided by SQLSTATE, not by Python class: asyncpg maps only integrity violations to `IntegrityError`, and an overflow
    is a plain `DBAPIError` (A6-PR1-1). The expression is `getattr(err.orig, "sqlstate", None) or ""`, **not** a
    `getattr(..., "")` default: the dialect always SETS `sqlstate`, to `None` for an error asyncpg gives none (a real lost
    connection is an `InterfaceError` with `orig.sqlstate = None`), so a default is never used and `None[:2]` would raise a
    `TypeError` inside `write_plan`'s `except`, an exception outside `main.RUN_ERRORS` that crashes the whole worker
    (A6-PR2-1). An error with `connection_invalidated` set is False before the SQLSTATE is looked at. Everything else (a
    lost connection, an error outside classes 22 / 23, a bug that raises) is False.
    """
    if isinstance(err, ShowGone):
        return True
    if not isinstance(err, DBAPIError) or err.connection_invalidated:
        return False
    sqlstate = getattr(err.orig, "sqlstate", None) or ""
    return sqlstate[:2] in DECISION_SQLSTATE_CLASSES


def failure_for(op: ShowOp, err: BaseException) -> ShowFailure:
    """A failed write as data: which show (date, time, stored id), the SQLSTATE, and the error's type and first line.
    Never the SQL with its parameters, which can carry a whole page's worth of text."""
    wrapped = isinstance(err, DBAPIError)
    sqlstate = (getattr(err.orig, "sqlstate", None) or None) if isinstance(err, DBAPIError) else None
    message = str(err.orig if isinstance(err, DBAPIError) else err)
    first_line = message.splitlines()[0] if message else ""
    return ShowFailure(
        action=op.action.value, date=op.decision.date, time=op.decision.start_time, stored_id=op.stored_id,
        reconcile_reason=op.reconcile_reason, sqlstate=sqlstate if wrapped else None,
        error=f"{type(err).__name__}: {first_line}",
    )


async def record_failure(
    audit: AuditWriter, op: ShowOp, err: BaseException, run_id: int | None, attempt_number: int
) -> ShowFailure:
    """Write the failure row for a show whose write was refused, and return the failure for the summary.

    Through `AuditWriter.record` (its own session), because the transaction that would have held the row was rolled back.
    """
    failure = failure_for(op, err)
    await audit.record(show_failure_entry(failure, run_id=run_id, attempt_number=attempt_number))
    return failure


# ---------------------------------------------------------------------------
# The interface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShowWritten:
    """What `write_show` returns: the show's id, what happened to it, and the artists it created (key -> new id)."""

    show_id: int
    outcome: AuditOutcome
    created_artists: dict[str, int]


class CalendarWriter(Protocol):
    """Where the graph writes the calendar. The graph depends on this, not on Postgres."""

    async def write_show(
        self, op: ShowOp, artist_ids: Mapping[str, int], *, run_id: int | None, attempt_number: int
    ) -> ShowWritten:
        """Write one show, atomically, with its audit rows. `artist_ids` are the artists created earlier in this run
        (key -> id), for lineup entries that had no id when reconcile planned them."""
        ...


# ---------------------------------------------------------------------------
# The Postgres writer
# ---------------------------------------------------------------------------


class PostgresCalendarWriter:
    """Writes the calendar to Postgres, one show per transaction (see the module docstring)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def write_show(
        self, op: ShowOp, artist_ids: Mapping[str, int], *, run_id: int | None, attempt_number: int
    ) -> ShowWritten:
        # TODO(Ari) A6-K1 — Lesson: a write and its record are ONE unit (a6-commit.md, A6-K1; arch-initial.md §7). The audit
        #   rows go in the SAME session and transaction as the change, so they commit or roll back together: a rolled-back
        #   show leaves no audit row, and a committed one can't lose its record. The snapshots are taken in a deliberate
        #   order: `previous` BEFORE the change (the ORM hands back the same, mutated object after it), `new` AFTER the
        #   flush (so it holds what the database holds). They are what a future revert restores (data-model-initial.md §3).
        #   And nothing outlives the transaction except the return value: the artists this show created go back only in
        #   `ShowWritten`, and the lineup uses a fresh merge `{**artist_ids, **created}`, never a write into the caller's
        #   map or a cache on the writer (an id remembered from a transaction that rolls back is a lie the next show links to).
        # Code (the helpers are written; the gap is the block that orders them):
        #   async with self._session_factory() as session, session.begin():
        #       created = await self._create_artists(session, op, artist_ids)
        #       previous = await self._snapshot(session, op.stored_id, lock=True) if op.stored_id is not None else None
        #       show_id = await self._apply(session, op, {**artist_ids, **created})
        #       new = await self._snapshot(session, show_id)
        #       session.add_all(
        #           audit_row(e) for e in self._audit_rows(op, created, show_id, previous, new, run_id, attempt_number)
        #       )
        #   return ShowWritten(show_id, op.outcome, created)
        # Check: uv run pytest agent_worker/tests/test_calendar_writer.py -k "writes or previous or atomic or audit_rows or revert or remembered or one_session"
        #   The likeliest mistake is taking `previous` after `_apply` (it equals `new_value`: test_previous_value_is_the_row_before_the_change
        #   goes red). The second is writing the audit rows through another session or calling `session.commit()` before they
        #   are added (test_audit_rows_roll_back_with_the_write and test_a_write_uses_exactly_one_session go red; the
        #   foreign-key test fails earlier, before the audit rows exist, so it cannot see this). The third is keeping created
        #   ids anywhere but the return value (test_a_rolled_back_artist_is_not_remembered goes red).
        raise NotImplementedError("TODO(Ari)")

    async def _create_artists(self, session: AsyncSession, op: ShowOp, artist_ids: Mapping[str, int]) -> dict[str, int]:
        """Create the artists this show's lineup needs that don't exist yet: name only (requirements, "Agent Artist
        Creation & Matching"). Skips a key an earlier show in this run already created. Returns key -> new id."""
        created: dict[str, int] = {}
        for key, name in op.new_artist_names.items():
            if key in artist_ids:
                continue
            artist = Artist(name=name)
            session.add(artist)
            await session.flush()  # assigns the id the lineup links to
            created[key] = artist.id
        return created

    async def _snapshot(self, session: AsyncSession, show_id: int, *, lock: bool = False) -> dict[str, Any]:
        """The show as the database holds it right now, as a plain dict (`commit.snapshot_of`).

        A SELECT with `populate_existing`, not a read of the session's identity map, so it reports the database's values
        (the quantized price, the server's defaults). With `lock=True` it selects `FOR UPDATE`, holding the row for the
        transaction, and raises `ShowGone` if the row isn't there. The lineup is read as columns, not entities, so no
        `ShowArtist` object enters the identity map to collide with the rows `_apply` replaces.
        """
        query = select(Show).where(Show.id == show_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        row = (await session.execute(query)).scalar_one_or_none()
        if row is None:
            raise ShowGone(f"show {show_id} is not in the calendar")
        links = await session.execute(
            select(ShowArtist.artist_id, ShowArtist.start_time, ShowArtist.sequence_number)
            .where(ShowArtist.show_id == show_id)
        )
        lineup = [{"artist_id": a, "start_time": s, "sequence_number": n} for a, s, n in links.all()]
        return snapshot_of({column: getattr(row, column) for column in SNAPSHOT_COLUMNS}, lineup)

    async def _apply(self, session: AsyncSession, op: ShowOp, artist_ids: Mapping[str, int]) -> int:
        """Make the change: insert the show or set the changed columns, then replace the lineup if told to. Returns the
        show's id. `updated_at` is set explicitly so a lineup-only change still moves it (an ORM update that changes no
        `show` column would issue no UPDATE)."""
        if op.action is Action.INSERT:
            row = Show(**op.values)
            session.add(row)
        else:
            assert op.stored_id is not None
            found = await session.get(Show, op.stored_id)  # already in the session: the locked read loaded it
            if found is None:
                raise ShowGone(f"show {op.stored_id} is not in the calendar")
            row = found
            for column, value in op.values.items():
                setattr(row, column, value)
            row.updated_at = func.now()  # type: ignore[assignment]
        await session.flush()
        if op.lineup is not None:
            await session.execute(delete(ShowArtist).where(ShowArtist.show_id == row.id))
            session.add_all(
                ShowArtist(
                    show_id=row.id, artist_id=entry.artist_id if entry.artist_id is not None else artist_ids[entry.key],
                    start_time=entry.start_time, sequence_number=entry.sequence_number,
                )
                for entry in op.lineup
            )
            await session.flush()
        return row.id

    def _audit_rows(
        self, op: ShowOp, created: Mapping[str, int], show_id: int, previous: dict[str, Any] | None,
        new: dict[str, Any], run_id: int | None, attempt_number: int,
    ) -> list[AuditEntry]:
        """The rows that record this write: one per artist it created (they exist before the show), then the show's."""
        rows = [
            artist_created_entry(
                run_id=run_id, attempt_number=attempt_number, artist_id=artist_id, name=op.new_artist_names[key], key=key,
            )
            for key, artist_id in created.items()
        ]
        rows.append(show_write_entry(
            op, run_id=run_id, attempt_number=attempt_number, show_id=show_id, previous=previous, new=new,
        ))
        return rows


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


async def write_plan(
    ops: tuple[ShowOp, ...], writer: CalendarWriter, audit: AuditWriter, *, run_id: int | None, attempt_number: int
) -> CommitResult:
    """Do every operation, in order, each its own transaction; return what happened.

    A show the database refuses (`is_decision_error`) is recorded and skipped (A6-D2); the run goes on. Anything else
    propagates: a lost connection or a bug in our code is not about one show.
    """
    artist_ids: dict[str, int] = {}  # key -> id of artists created so far in this run, extended only after a write returns
    tally = {"inserted": 0, "updated": 0, "removed": 0}
    failures: list[ShowFailure] = []
    for op in ops:
        # TODO(Ari) A6-K2 — Lesson: a failure about ONE show is not a reason to stop, and a failure about the RUN is, and the
        #   line between them is what the DATABASE says about this row, not which Python class the driver raised (a6-commit.md,
        #   A6-K2, A6-D2). SQLSTATE class 22 (a data exception: the overflow) and 23 (an integrity violation) are about the
        #   row; a lost connection, or a bug in our code, must propagate. `is_decision_error` (written) holds that rule, so the
        #   `except` clause names the broad types and re-raises when the rule says no: never `except Exception`
        #   (apps/api/AGENTS.md), and never `except SQLAlchemyError` that swallows a dead connection. The artist map is
        #   extended only from what `write_show` returned, after the write, so a failed show contributes nothing to it.
        # Code:
        #   try:
        #       written = await writer.write_show(op, artist_ids, run_id=run_id, attempt_number=attempt_number)
        #   except (DBAPIError, ShowGone) as err:
        #       if not is_decision_error(err):
        #           raise
        #       failures.append(await record_failure(audit, op, err, run_id, attempt_number))
        #       continue
        #   artist_ids.update(written.created_artists)
        #   tally[written.outcome.value] += 1
        # Check: uv run pytest agent_worker/tests/test_calendar_writer.py -k "write_plan or overflowing or connection or created_once or all_failed or is_decision_error or failing_show"
        #   and agent_worker/tests/test_graph_commit.py -k failed. The likeliest mistake is catching `Exception`, `SQLAlchemyError`
        #   or any `DBAPIError` without the SQLSTATE test (test_a_connection_error_stops_the_run goes red, with `08006` and with
        #   the real lost-connection shape); the second is forgetting that the overflow is NOT an `IntegrityError` (catching
        #   only `IntegrityError` makes test_an_overflowing_price_fails_only_its_show, the A6-D2 scenario, go red).
        raise NotImplementedError("TODO(Ari)")
    result = CommitResult(tally, len(artist_ids), tuple(failures), len(ops))
    if result.all_failed:
        log.error(
            "every write in this commit failed; that looks like a bug in the writes, not bad listings",
            writes=len(ops), sqlstates=sorted({f.sqlstate or "none" for f in failures}),
        )
    return result
