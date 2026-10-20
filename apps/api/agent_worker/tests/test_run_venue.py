"""Tests for the worker's entry point: loading venues, and `run_venue`'s run lifecycle.

Milestone A4 (docs/dev/implementations/a4-auditability.md, step 7, A4-D6 and A4-D8; A4-K1). `run_venue` opens an
`agent_run`, runs the graph with the run's id in the state, and closes the run in a `finally`. These tests use
the real Postgres writer (so the rows are real), the real graph, the scripted model, and a recording stager.

How to read it: `ctx` builds a `WorkerContext` on the test connection; `setup` seeds the venues and returns
the first as `VenueFacts`. Expected values are the seed's literals (`app/db/seed.py`: venue 1 is The White
Squirrel Bar, in the America/Chicago metro) and the plan's rules. The tests marked (A4-K1) pin the run lifecycle that
`main.run_venue` implements.
"""

import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from pymongo.errors import ServerSelectionTimeoutError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from agent_worker import main, nodes
from agent_worker.audit import PostgresAuditWriter
from agent_worker.commit import CommitResult, ShowFailure
from agent_worker.context import WorkerContext
from agent_worker.main import VenueFacts, load_venues, run_all, run_venue
from agent_worker.state import VenueGraphState
from agent_worker.tests import fakes
from agent_worker.tests.fakes import (
    SPLITTER,
    FakeReader,
    FakeWriter,
    RecordingStager,
    event,
    jsonld_page,
    scripted_client,
)
from agent_worker.tests.test_graph import NONA
from app.db.models import AgentRun, AuditLog
from app.db.seed import seed
from app.enums import RunTrigger, StepType

PAGE_WITH_ONE_SHOW = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))


@pytest.fixture
def factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A session factory on the test connection (`db_conn`, app/testing/db.py), in savepoint mode.

    The worker's writer opens its own session per call and `commit()`s each one. Here every such commit only
    releases a savepoint inside `db_conn`'s outer transaction, which the fixture rolls back at the end of the
    test, so the writes are real (visible to the next session on this connection) and leave nothing behind.
    """
    return async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest.fixture
def ctx(factory: async_sessionmaker[AsyncSession]) -> WorkerContext:
    """What the worker hands every node: the real Postgres audit writer (on the test connection) and a
    recording stager standing in for MongoDB."""
    return WorkerContext(
        audit=PostgresAuditWriter(factory), stager=RecordingStager(), reader=FakeReader(), writer=FakeWriter(),
    )


@pytest_asyncio.fixture(loop_scope="session")
async def venue(factory: async_sessionmaker[AsyncSession]) -> VenueFacts:
    """The seeded venues' first row, as the worker sees it (loaded through `load_venues`)."""
    async with factory() as session:
        await seed(session)
        await session.commit()
    async with factory() as session:
        return (await load_venues(session))[0]


async def count(factory: async_sessionmaker[AsyncSession], model: type) -> int:
    """How many rows `model`'s table holds right now (used to assert a call opened no run)."""
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


# ---------------------------------------------------------------------------
# Loading venues
# ---------------------------------------------------------------------------


async def test_load_venues_returns_each_venue_with_its_metros_timezone(
    factory: async_sessionmaker[AsyncSession], venue: VenueFacts,
) -> None:
    # Proves (A4-D6, Departure 2): the worker takes its venue facts from the database row, not from the caller:
    # id, name, calendar URL, and the timezone of the venue's metro (`metro.timezone` is the source of truth,
    # data-model-initial.md). The seed has four venues; the first is The White Squirrel Bar, in Chicago time.
    async with factory() as session:
        venues = await load_venues(session)
    assert len(venues) == 4
    assert venues[0].name == "The White Squirrel Bar" and venues[0].metro_timezone == "America/Chicago"
    assert venues[0].calendar_url.startswith("http") and venues[0].id == venue.id
    assert [v.id for v in venues] == sorted(v.id for v in venues)


async def test_load_venues_can_pick_one_and_an_unknown_id_is_empty(
    factory: async_sessionmaker[AsyncSession], venue: VenueFacts,
) -> None:
    # Proves: `--venue N` selects exactly that venue, and an id that does not exist selects none.
    async with factory() as session:
        assert [v.id for v in await load_venues(session, venue_id=venue.id)] == [venue.id]
        assert await load_venues(session, venue_id=999_999) == []


async def test_run_all_on_an_unknown_venue_raises_before_opening_any_run(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts,
) -> None:
    # Proves: asking for a venue the database does not have fails loudly and opens no run: an `agent_run`
    # needs a real `venue_id` (FK), and a silent no-op would look like a successful empty cycle.
    before = await count(factory, AgentRun)
    with pytest.raises(LookupError, match="999999"):
        await run_all(factory, ctx, venue_id=999_999)
    assert await count(factory, AgentRun) == before


async def test_run_all_continues_after_one_venue_hits_an_infrastructure_error(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: one venue's database or network failure is logged and counted, and the loop moves on to the
    # next venue (arch-initial.md §7: every venue, every run). The exit status the caller sees is the number
    # of failed venues. A programming error is not in the caught set (see `RUN_ERRORS`) and would propagate.
    seen: list[int] = []

    async def flaky(v: VenueFacts, *_: Any, **__: Any) -> VenueGraphState:
        seen.append(v.id)
        if len(seen) == 1:
            raise OSError("the network dropped")
        return VenueGraphState(
            venue_id=v.id, calendar_url=v.calendar_url, venue_name=v.name, metro_timezone=v.metro_timezone,
        )

    monkeypatch.setattr(main, "run_venue", flaky)
    failed = await run_all(factory, ctx)
    assert failed == 1 and len(seen) == 4


async def test_run_all_counts_a_venue_whose_commit_had_a_refused_show_as_failed(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A6-D2): a venue run that returns normally but with a show the database refused counts as failed, so the
    # process exits non-zero and a person looks (`failed_commits`); a venue whose commit was clean does not. The venues are
    # the seeded ones in id order; only the first returns a failure.
    seen: list[int] = []

    async def commit_with_one_refusal(v: VenueFacts, *_: Any, **__: Any) -> VenueGraphState:
        seen.append(v.id)
        failures = (
            ShowFailure("insert", datetime.date(2026, 10, 20), None, None, "new show", "22003", "boom"),
        ) if len(seen) == 1 else ()
        return VenueGraphState(
            venue_id=v.id, calendar_url=v.calendar_url, venue_name=v.name, metro_timezone=v.metro_timezone,
            commit_result=CommitResult(failures=failures, total_ops=1),
        )

    monkeypatch.setattr(main, "run_venue", commit_with_one_refusal)
    assert await run_all(factory, ctx) == 1 and len(seen) == 4


# ---------------------------------------------------------------------------
# The run's lifecycle (A4-K1)
# ---------------------------------------------------------------------------


async def test_run_venue_opens_a_run_carries_its_id_and_closes_it(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A4-K1): the `agent_run` is the parent of every row. Its id travels in the state, so every
    # audit row of the run has that `run_id`; the run is stamped finished; and the venue facts in the state
    # came from the database row (name and timezone), with only the URL overridden for the test.
    page = tmp_path / "page.html"
    page.write_text(PAGE_WITH_ONE_SHOW)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [NONA]}))
    state = await run_venue(venue, ctx, trigger=RunTrigger.MANUAL, calendar_url=str(page), fetched_on=fakes.FETCHED)
    assert state.run_id is not None
    async with factory() as session:
        run = await session.get(AgentRun, state.run_id)
        row_runs = {r for (r,) in await session.execute(select(AuditLog.run_id))}
    assert run is not None and run.finished_at is not None
    assert (run.venue_id, run.trigger) == (venue.id, RunTrigger.MANUAL)
    assert row_runs == {state.run_id}
    assert (state.venue_name, state.metro_timezone) == ("The White Squirrel Bar", "America/Chicago")


async def test_a_run_that_crashes_is_still_closed_and_the_error_still_propagates(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A4-K1, A4-D8): a graph that raises leaves the run with a `finished_at` (so it does not look
    # "in progress" forever) and the exception reaches the caller, neither swallowed nor replaced. Without
    # the `finally`, `finished_at` stays NULL and a crash is indistinguishable from a run still going.
    async def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("the graph blew up")

    monkeypatch.setattr(main, "compiled_graph", SimpleNamespace(ainvoke=boom))
    with pytest.raises(RuntimeError, match="the graph blew up"):
        await run_venue(venue, ctx, trigger=RunTrigger.MANUAL)
    async with factory() as session:
        runs = list((await session.execute(select(AgentRun))).scalars())
    assert len(runs) == 1 and runs[0].finished_at is not None


async def test_run_venue_binds_the_run_id_for_log_lines_and_unbinds_it_after(
    ctx: WorkerContext, venue: VenueFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves (A4-K1, A4-D7): while the graph runs, structlog's context carries `run_id` and `venue_id`, so every
    # log line of the run joins to its audit rows; afterwards they are gone, so the next venue's lines are
    # not tagged with the previous run's id.
    import structlog

    seen: dict[str, Any] = {}

    async def spy(state: Any, **_: Any) -> dict[str, Any]:
        seen.update(structlog.contextvars.get_contextvars())
        return state.model_dump()

    monkeypatch.setattr(main, "compiled_graph", SimpleNamespace(ainvoke=spy))
    result = await run_venue(venue, ctx, trigger=RunTrigger.MANUAL)
    assert seen == {"run_id": result.run_id, "venue_id": venue.id}
    assert structlog.contextvars.get_contextvars() == {}


async def test_a_passing_run_leaves_the_five_steps_a_pass_visits(
    factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, venue: VenueFacts,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: end to end through Postgres, a passing run leaves the five steps a pass visits, as rows of
    # `audit_log` in step order (the enum labels are the Python values).
    page = tmp_path / "page.html"
    page.write_text(PAGE_WITH_ONE_SHOW)
    monkeypatch.setattr(nodes, "instructor_client", scripted_client({SPLITTER: [NONA]}))
    state = await run_venue(venue, ctx, calendar_url=str(page), fetched_on=fakes.FETCHED)
    async with factory() as session:
        steps = [s for (s,) in await session.execute(
            select(AuditLog.step_type).where(AuditLog.run_id == state.run_id).order_by(AuditLog.id)
        )]
    assert steps == [StepType.FETCH, StepType.EXTRACT, StepType.VALIDATE, StepType.RECONCILE, StepType.COMMIT]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def test_main_refuses_to_start_without_a_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A4-D3): the worker fails fast, with a non-zero status, when MONGODB_URI is unset. An audit trail
    # that silently skipped its raw record would not be auditable. Nothing is connected to: `main` returns
    # before it builds a client or reads the database.
    monkeypatch.setattr(main.settings, "mongodb_uri", None)
    assert await main.main([]) == 2


async def test_main_refuses_to_start_when_mongodb_does_not_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A4-CR1-3, A4-D3): "fail fast" covers a MongoDB that is configured but not running, not only
    # one that is unset. The driver connects lazily, so without a ping at startup each venue would do its
    # fetch and a full model call, then wait ~30 s for server selection and fail. A stand-in client whose
    # ping raises `ServerSelectionTimeoutError` makes `main` return 2 before any venue is touched.
    class DeadClient:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.admin = SimpleNamespace(command=self._ping)

        async def _ping(self, *_: Any, **__: Any) -> None:
            raise ServerSelectionTimeoutError("no server")

        async def close(self) -> None:
            pass

    async def must_not_run(*_: Any, **__: Any) -> int:
        raise AssertionError("run_all was reached with MongoDB down")

    monkeypatch.setattr(main.settings, "mongodb_uri", "mongodb://localhost:1")
    monkeypatch.setattr(main, "AsyncMongoClient", DeadClient)
    monkeypatch.setattr(main, "run_all", must_not_run)
    assert await main.main([]) == 2
