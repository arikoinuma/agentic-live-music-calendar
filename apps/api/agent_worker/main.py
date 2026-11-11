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
  * `main` wires the stores (Postgres engine, MongoDB client), configures logging, applies the scheduled-run gate
    (a `--trigger scheduled` run exits 0 when the feature flag `worker.scheduled_runs` is off, C3.1-D1), and calls `run_all`.
    A run that does work logs one start line (after MongoDB has answered) and one finish line, so a run on Railway can
    be read from its log without a database query (C8-D8's wording for an unreachable MongoDB is `mongo_unreachable_message`).

THE EVENT LOOP
  Everything here runs on ONE event loop, created by `asyncio.run(main())`. The shared pooled engine
  (`app.db.session.engine`) and the one `AsyncMongoClient` are created on it and used by every node's audit
  write; asyncpg connections and the Mongo client are bound to the loop that created them, which is why the
  graph is `ainvoke`-only (plan A4-D1; graph.py).

docs/dev/implementations/a4-auditability.md, A4-D1, A4-D3, A4-D6, A4-D7, A4-D8; c3.1-feature-flags.md, C3.1-D1, C3.1-D13, C3.1-D14, C3.1-D15;
c8-worker-on-railway.md, C8-D6, C8-D8.
"""

import argparse
import asyncio
import datetime
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import structlog
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.audit import PostgresAuditWriter
from agent_worker.calendar_reader import PostgresCalendarReader
from agent_worker.calendar_writer import PostgresCalendarWriter
from agent_worker.context import WorkerContext
from agent_worker.graph import (
    compiled_graph,
)
from agent_worker.policy import RetryPolicy
from agent_worker.staging import COLLECTION, MongoStager
from agent_worker.state import VenueGraphState
from app.config import AppEnv, settings
from app.db.models import Metro, Venue
from app.db.session import SessionFactory, engine
from app.enums import RunTrigger
from app.flags import effective_flags, env_key, is_enabled
from app.log_config import configure_logging

log = structlog.get_logger()

# The feature flag that gates a `--trigger scheduled` run (C3.1-D1). Named once for the log line and the help text;
# the call in `main` repeats the literal on purpose (see there).
SCHEDULED_RUNS_FLAG = "worker.scheduled_runs"

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
    venue: VenueFacts,
    ctx: WorkerContext,
    *,
    trigger: RunTrigger = RunTrigger.MANUAL,
    calendar_url: str | None = None,
    fetched_on: datetime.date | None = None,
    policy: RetryPolicy | None = None,
) -> VenueGraphState:
    """One venue's processing cycle: open a run, run the graph, close the run. Returns the final state.

    `calendar_url` and `fetched_on` override the venue's URL and the fetch date; `local_test.py` uses them to
    run a saved fixture through the real cycle. `policy` replaces the default retry policy for this run (the eval harness
    varies the confidence threshold and the attempt cap this way, C5-D5); None keeps `DEFAULT_POLICY`, so the scheduled
    worker is unchanged. Exceptions propagate (after the run is closed).
    """
    initial = VenueGraphState(
        venue_id=venue.id,
        calendar_url=calendar_url or venue.calendar_url,
        venue_name=venue.name,
        metro_timezone=venue.metro_timezone,
        fetched_on=fetched_on,
    )
    if policy is not None:
        initial = initial.model_copy(update={"policy": policy})

    #   The run is the parent of every audit row (arch-initial.md §7,
    #   `parent_run_id`). Its id travels IN THE STATE, not in a module global, so each node's row points at
    #   the run that produced it and two runs could never cross. It is closed in a `finally`, because a run
    #   that crashes must still end (plan A4-D8): otherwise it looks "in progress" forever, and the
    #   `unfinished_runs` query can't tell a crash from a run that is still going. The structlog binding is
    #   what puts `run_id` and `venue_id` on every log line of the run (A4-D7).
    run_id = await ctx.audit.start_run(venue.id, trigger)
    structlog.contextvars.bind_contextvars(run_id=run_id, venue_id=venue.id)
    try:
        result = await compiled_graph.ainvoke(initial.model_copy(update={"run_id": run_id}), context=ctx)
        return VenueGraphState(**result)
    finally:
        await ctx.audit.finish_run(run_id)
        structlog.contextvars.unbind_contextvars("run_id", "venue_id")


async def run_all(
    session_factory: async_sessionmaker[AsyncSession],
    ctx: WorkerContext,
    *,
    venue_id: int | None = None,
    trigger: RunTrigger = RunTrigger.MANUAL,
) -> int:
    """Process the venues one after another. Returns how many failed: with an infrastructure error, or with a show
    commit could not write (A6-D2).

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
        if state.commit_result is not None and state.commit_result.failures:
            # Some shows were refused by the database (A6-D2): the others were written, but a person should look (the
            # `failed_commits` saved query lists them), so the venue counts as failed and the process exits non-zero.
            failed += 1
            log.error(
                "venue commit had failures",
                venue=venue.name,
                failures=len(state.commit_result.failures),
                all_failed=state.commit_result.all_failed,
            )
        log.info(
            "venue run finished",
            venue=venue.name,
            escalated=state.escalation_reason is not None,
            attempts=state.attempt_count,
        )
    return failed


def model_endpoint_problem(app_env: AppEnv, provider: str, base_url: str | None, api_key: str) -> str | None:
    """What is wrong with the worker's model endpoint, as a sentence, or `None` when it can be used (C6-PR1-1).

    Three mistakes this stops before the first model call turns them into a confusing failure:
      * no endpoint at all: `MODEL_BASE_URL` has no default in code (Ari's comment on PR 80), so a worker started without one
        would have nowhere to send its calls;
      * a HOSTED worker pointing at localhost. A laptop's `.env` points at its Ollama, and `localhost:11434` doesn't
        exist on Railway (`env-setup.md` Phase 8), so a hosted service that copies it would fail every call with a
        connection error;
      * a hosted (`openai_compatible`) endpoint with the placeholder key `"ollama"`, which the provider answers
        with a 401 on the first call.
    A laptop (`local`) may point at a hosted endpoint: that is how the hosted parity run and the accuracy work
    are done from the development machine. This is a worker check, not a `Settings` validator, because the
    hosted API builds `Settings` too and never sets a model endpoint.
    """
    if not base_url:
        return "MODEL_BASE_URL is not set: the model endpoint comes only from the environment (see .env.example)"
    host = urlparse(base_url).hostname or ""
    if app_env != "local" and host in ("localhost", "127.0.0.1", "::1"):
        return f"APP_ENV={app_env} but MODEL_BASE_URL points at {host!r}, which does not exist on a hosted service"
    if provider == "openai_compatible" and api_key == "ollama":
        return "MODEL_PROVIDER=openai_compatible but MODEL_API_KEY is unset (still the Ollama placeholder)"
    return None


def mongo_unreachable_message(app_env: AppEnv) -> str:
    """What to tell whoever reads the log when MongoDB does not answer, by environment (C8-D8).

    A laptop's cause is a stopped Docker container, so it is sent to `make db-up`. A hosted worker has no Docker to
    start: the causes are a PAUSED Atlas free cluster (C1 found one and had to restart it by hand: nothing connects to
    Atlas between C8 and C11 except manual runs, so it can pause unnoticed), a wrong `MONGODB_URI`, or Atlas's
    Network Access list not allowing Railway, which has no fixed outbound address (C8-U5, C8-U6).
    """
    if app_env == "local":
        return "MongoDB did not answer; start it with `make db-up` or check MONGODB_URI"
    return (
        "MongoDB did not answer (Atlas): in the Atlas console check that the cluster is not paused (a free cluster "
        "pauses after weeks without a connection and has to be resumed by hand), that this service's MONGODB_URI is "
        "right, and that the Network Access list allows Railway"
    )


async def main(argv: list[str] | None = None) -> int:
    """Parse arguments, wire the stores, run, and return the process exit status."""
    parser = argparse.ArgumentParser(description="Run the agent worker over the venue list.")
    parser.add_argument("--venue", type=int, help="process only this venue id")
    parser.add_argument(
        "--trigger",
        type=RunTrigger,
        # Only the two triggers something starts today (C3.1-D13). `submission` and `flag_threshold` are real
        # `RunTrigger` values with no starter yet, and accepting them here would run every venue with the
        # scheduled-run gate below skipped; widen this list when something starts them, deliberately.
        choices=[RunTrigger.SCHEDULED, RunTrigger.MANUAL],
        default=RunTrigger.MANUAL,
        help=(
            "why this run started. `scheduled` (a cron job passes it) is gated by the feature flag "
            f"worker.scheduled_runs ({env_key(SCHEDULED_RUNS_FLAG)}); `manual` ignores the flag"
        ),
    )
    args = parser.parse_args(argv)

    configure_logging()
    # Fail fast on a model endpoint that cannot work here, before any venue's fetch (C6-PR1-1).
    endpoint_problem = model_endpoint_problem(
        settings.app_env, settings.model_provider, settings.model_base_url, settings.model_api_key.get_secret_value()
    )
    if endpoint_problem:
        log.error(endpoint_problem)
        return 2
    # Fail fast (plan A4-D3): an audit trail that silently skips its raw record isn't auditable.
    if not settings.mongodb_uri:
        log.error("MONGODB_URI is not set; the worker stages every extraction in MongoDB (see .env.example)")
        return 2

    # The scheduled-run gate (C3.1-D1, C3.1-D13, C3.1-D14), AFTER the two checks above and BEFORE the Atlas ping:
    # a skipped run then proves the configuration is complete without opening Neon or Atlas (C8-D6), and a
    # misconfigured service still fails loudly instead of "skipping" its way past the mistake. The skip opens no
    # run (`agent_run.venue_id` is non-null, so there is no row to write for a run with no venue) and exits 0:
    # a non-zero exit may be retried by Railway's restart policy (C8-U2). `manual` is never gated (Dep-D12). The
    # flag name is a string literal because the hygiene check finds reads by scanning for it (C3.1-D18).
    if args.trigger is RunTrigger.SCHEDULED and not is_enabled("worker.scheduled_runs"):
        log.info(
            "scheduled run skipped: feature flag worker.scheduled_runs is off",
            flag=SCHEDULED_RUNS_FLAG,
            variable=env_key(SCHEDULED_RUNS_FLAG),
        )
        return 0

    # A short server-selection timeout: the driver connects lazily, so without the ping below an unreachable
    # server would only show up at the first staging write, after the venue's fetch and model call, and
    # after a 30 s wait (A4-CR1-3).
    mongo: AsyncMongoClient = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    try:
        try:
            await mongo.admin.command("ping")
        except PyMongoError as err:
            log.error(mongo_unreachable_message(settings.app_env), error=str(err))
            return 2
        # The start line comes only once the run is certain to do work: a skipped run (the gate above) and a run that
        # stops at the ping log nothing else, which `test_main_gate.py` pins (C3.1-T11). One line says what this run is,
        # so a deployment's log is readable without opening the database (C8-D6).
        log.info(
            "worker run started",
            trigger=args.trigger.value,
            app_env=settings.app_env,
            model=settings.model_name,
            venue=args.venue,
        )
        started = time.monotonic()
        ctx = WorkerContext(
            # One snapshot of the feature flags, taken now, goes on every run this process opens (C3.1-D15): the
            # environment cannot change under a running process, so it is the run's value.
            audit=PostgresAuditWriter(SessionFactory, app_env=settings.app_env, feature_flags=effective_flags()),
            stager=MongoStager(mongo[settings.mongodb_database][COLLECTION]),
            reader=PostgresCalendarReader(SessionFactory),
            writer=PostgresCalendarWriter(SessionFactory),
        )
        failed = await run_all(SessionFactory, ctx, venue_id=args.venue, trigger=args.trigger)
        # `run_all` returns only how many venues failed (each venue already logged its own "venue run finished"), so
        # the finish line carries the failure count and the duration, which is what Railway's log view needs.
        log.info("worker run finished", failed=failed, seconds=round(time.monotonic() - started, 1))
    finally:
        await mongo.close()
        await engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
