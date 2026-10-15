"""The worker's entry point: process every venue, one after another, each as an audited run.

HOW TO READ THIS
  `python -m agent_worker.main [--venue ID] [--trigger scheduled|manual]` (or `make worker`) does, for each venue
  in Postgres:

      open an agent_run  ->  run the graph with the run's id in the state  ->  close the run

  * `load_venues` reads the venue list and each venue's metro timezone from the database, so the worker no
    longer needs a caller to supply them (build plan A4; a small piece of A5's "read the venue list from
    Postgres on every run", arch-initial.md §7).
  * `run_venue` is one venue's cycle: **A4-K1** lives in it.
  * `run_all` loops the venues sequentially, as arch-initial.md §7 says (one process, every venue, no
    per-venue scheduling), and keeps going when one venue hits an infrastructure error.
  * `main` wires the stores (Postgres engine, MongoDB client), configures logging, and calls `run_all`.

THE EVENT LOOP
  Everything here runs on ONE event loop, created by `asyncio.run(main())`. The shared pooled engine
  (`app.db.session.engine`) and the one `AsyncMongoClient` are created on it and used by every node's audit
  write; asyncpg connections and the Mongo client are bound to the loop that created them, which is why the
  graph is `ainvoke`-only (plan A4-D1; graph.py).

docs/dev/implementations/a4-auditability.md, A4-D1, A4-D3, A4-D6, A4-D7, A4-D8.
"""

import argparse
import asyncio
import datetime
import sys
from dataclasses import dataclass

import structlog
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.audit import PostgresAuditWriter
from agent_worker.context import WorkerContext
from agent_worker.graph import (
    compiled_graph,
)
from agent_worker.staging import COLLECTION, MongoStager
from agent_worker.state import VenueGraphState
from app.config import settings
from app.db.models import Metro, Venue
from app.db.session import SessionFactory, engine
from app.enums import RunTrigger
from app.log_config import configure_logging

log = structlog.get_logger()

# What one venue's run is allowed to fail with and still let the next venue run: the database or the
# staging store is unreachable, or a file/socket error. A named tuple, never a bare `Exception`
# (apps/api/AGENTS.md): a KeyError or AttributeError in OUR code is a bug and should stop the process with a
# traceback and a non-zero exit, not be filed as "venue failed". The run row is closed either way
# (`run_venue`'s finally).
RUN_ERRORS = (SQLAlchemyError, PyMongoError, OSError)


@dataclass(frozen=True)
class VenueFacts:
    """What the worker needs to know about a venue, read from its database row and its metro's."""

    id: int
    name: str
    calendar_url: str
    metro_timezone: str


async def load_venues(session: AsyncSession, venue_id: int | None = None) -> list[VenueFacts]:
    """Every venue (or just `venue_id`), oldest id first, with the timezone of its metro.

    `metro.timezone` is the source of truth for the wall-clock times extraction reads
    (data-model-initial.md); the worker takes it from here rather than from the caller.
    """
    query = (
        select(Venue.id, Venue.name, Venue.calendar_url, Metro.timezone)
        .join(Metro, Venue.metro_id == Metro.id)
        .order_by(Venue.id)
    )
    if venue_id is not None:
        query = query.where(Venue.id == venue_id)
    return [VenueFacts(*row) for row in (await session.execute(query)).all()]


async def run_venue(
    venue: VenueFacts, ctx: WorkerContext, *, trigger: RunTrigger = RunTrigger.MANUAL,
    calendar_url: str | None = None, fetched_on: datetime.date | None = None,
) -> VenueGraphState:
    """One venue's processing cycle: open a run, run the graph, close the run. Returns the final state.

    `calendar_url` and `fetched_on` override the venue's URL and the fetch date; `local_test.py` uses them to
    run a saved fixture through the real cycle. Exceptions propagate (after the run is closed).
    """
    initial = VenueGraphState(
        venue_id=venue.id, calendar_url=calendar_url or venue.calendar_url,
        venue_name=venue.name, metro_timezone=venue.metro_timezone, fetched_on=fetched_on,
    )

    #   The run is the parent of every audit row (arch-initial.md §7,
    #   `parent_run_id`). Its id travels IN THE STATE, not in a module global, so each node's row points at
    #   the run that produced it and two runs could never cross. It is closed in a `finally`, because a run
    #   that crashes must still end (plan A4-D8): otherwise it looks "in progress" forever, and the
    #   `unfinished_runs` query can't tell a crash from a run that is still going. The structlog binding is
    #   what puts `run_id` and `venue_id` on every log line of the run (A4-D7).
    run_id = await ctx.audit.start_run(venue.id, trigger)
    structlog.contextvars.bind_contextvars(run_id=run_id, venue_id=venue.id)
    try:
        result = await compiled_graph.ainvoke(
            initial.model_copy(update={"run_id": run_id}), context=ctx
        )
        return VenueGraphState(**result)
    finally:
        await ctx.audit.finish_run(run_id)
        structlog.contextvars.unbind_contextvars("run_id", "venue_id")


async def run_all(
    session_factory: async_sessionmaker[AsyncSession], ctx: WorkerContext, *,
    venue_id: int | None = None, trigger: RunTrigger = RunTrigger.MANUAL,
) -> int:
    """Process the venues one after another. Returns how many failed with an infrastructure error.

    Raises `LookupError` before opening any run when `venue_id` names no venue: an `agent_run` needs a real
    venue, and a silent no-op would look like a successful empty cycle.
    """
    async with session_factory() as session:
        venues = await load_venues(session, venue_id)
    if venue_id is not None and not venues:
        raise LookupError(f"no venue with id {venue_id}")

    failed = 0
    for venue in venues:
        try:
            state = await run_venue(venue, ctx, trigger=trigger)
        except RUN_ERRORS:
            failed += 1
            # `log.exception` records the traceback. The run is already closed by run_venue's finally.
            log.exception("venue run failed", venue=venue.name)
            continue
        log.info(
            "venue run finished", venue=venue.name, escalated=state.escalation_reason is not None,
            attempts=state.attempt_count,
        )
    return failed


async def main(argv: list[str] | None = None) -> int:
    """Parse arguments, wire the stores, run, and return the process exit status."""
    parser = argparse.ArgumentParser(description="Run the agent worker over the venue list.")
    parser.add_argument("--venue", type=int, help="process only this venue id")
    parser.add_argument(
        "--trigger", type=RunTrigger, choices=list(RunTrigger), default=RunTrigger.MANUAL,
        help="why this run started (a cron job passes `scheduled`)",
    )
    args = parser.parse_args(argv)

    configure_logging()
    # Fail fast (plan A4-D3): an audit trail that silently skips its raw record isn't auditable.
    if not settings.mongodb_uri:
        log.error("MONGODB_URI is not set; the worker stages every extraction in MongoDB (see .env.example)")
        return 2

    # A short server-selection timeout: the driver connects lazily, so without the ping below an unreachable
    # server would only show up at the first staging write, after the venue's fetch and model call, and
    # after a 30 s wait (A4-R2-3).
    mongo: AsyncMongoClient = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    try:
        try:
            await mongo.admin.command("ping")
        except PyMongoError as err:
            log.error("MongoDB did not answer; start it with `make db-up` or check MONGODB_URI", error=str(err))
            return 2
        ctx = WorkerContext(
            audit=PostgresAuditWriter(SessionFactory),
            stager=MongoStager(mongo[settings.mongodb_database][COLLECTION]),
        )
        failed = await run_all(SessionFactory, ctx, venue_id=args.venue, trigger=args.trigger)
    finally:
        await mongo.close()
        await engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
