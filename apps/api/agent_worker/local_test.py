"""Runs the White Squirrel fixture through the real worker cycle, for a human to look at.

What this is: the same `run_venue` the scheduled worker uses (agent_worker/main.py), pointed at a saved page
instead of the live URL. So it exercises everything the worker does, including opening an `agent_run`, writing
the audit trail to Postgres and staging each extraction in MongoDB.

Needs (A4): Postgres seeded (`make db-up && make migrate && make seed`), MongoDB up (`make db-up`),
`MONGODB_URI` set in `.env`, and Ollama serving the model. Run from `apps/api`:
`uv run python -m agent_worker.local_test`, optionally with `--fixture PATH --fetched-on YYYY-MM-DD` to replay another capture
(C2-D10: the White Squirrel has an August and an October one, `eval/labels.py`). (Not collected by pytest: its name does not match `python_files = ["test_*.py"]` in `pyproject.toml`, A7.)
"""

import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path

from pymongo import AsyncMongoClient

from agent_worker.audit import PostgresAuditWriter
from agent_worker.calendar_reader import PostgresCalendarReader
from agent_worker.calendar_writer import PostgresCalendarWriter
from agent_worker.context import WorkerContext
from agent_worker.main import load_venues, run_venue
from agent_worker.staging import COLLECTION, MongoStager
from app.config import settings
from app.db.session import SessionFactory, engine
from app.enums import RunTrigger
from app.log_config import configure_logging

FIXTURE = "agent_worker/eval/fixtures/Archives_ Events - The White Squirrel Bar.html"
# The fixture was saved on August 17, 2026; the year rule (A2.1-D13) reads this date, and today's would put
# its August shows a year ahead.
FETCHED_ON = datetime.date(2026, 8, 17)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """The capture to replay and the date it counts as fetched on; both default to the original August capture."""
    parser = argparse.ArgumentParser(description="Replay a saved White Squirrel capture through the real worker cycle.")
    parser.add_argument("--fixture", default=FIXTURE, help="path of the saved page, relative to apps/api")
    parser.add_argument(
        "--fetched-on", type=datetime.date.fromisoformat, default=FETCHED_ON,
        help="the date the capture was saved (YYYY-MM-DD): the year rule reads it, A2.1-D13",
    )
    return parser.parse_args(argv)


async def main(fixture: str = FIXTURE, fetched_on: datetime.date = FETCHED_ON) -> int:
    configure_logging()
    assert settings.mongodb_uri, "set MONGODB_URI in .env (docker compose's mongo is mongodb://localhost:27017)"
    mongo: AsyncMongoClient = AsyncMongoClient(settings.mongodb_uri)
    try:
        ctx = WorkerContext(
            audit=PostgresAuditWriter(SessionFactory),
            stager=MongoStager(mongo[settings.mongodb_database][COLLECTION]),
            reader=PostgresCalendarReader(SessionFactory),
            writer=PostgresCalendarWriter(SessionFactory),
        )
        async with SessionFactory() as session:
            [venue] = await load_venues(session, venue_id=1)  # The White Squirrel Bar (app/db/seed.py)
        state = await run_venue(
            venue, ctx, trigger=RunTrigger.MANUAL, calendar_url=fixture, fetched_on=fetched_on,
        )
    finally:
        await mongo.close()
        await engine.dispose()

    # page_content is only useful to a human when it's text; for an image fixture it's a giant base64 blob.
    # Truncate it for the file; everything else is written out completely, since that's worth inspecting.
    dump = state.model_dump()
    for key in ("page_content", "page_html"):
        if dump[key] and len(dump[key]) > 200:
            original_length = len(dump[key])
            dump[key] = dump[key][:200] + f"... (truncated, {original_length} chars total)"

    output_path = Path(__file__).parent / "local_test_output.json"
    output_path.write_text(json.dumps(dump, indent=2, default=str))
    print(f"Wrote result to {output_path}")

    # What validation decided, and what each attempt did. The same fields are in the JSON above
    # (`validation`, `attempt_history`); this is the part worth reading first.
    verdict = state.validation.verdict.value if state.validation and state.validation.verdict else "none"
    print(f"verdict: {verdict} after {state.attempt_count} attempt(s); source: {state.extraction_source}")
    for record in state.attempt_history:
        print(
            f"  attempt {record.attempt} [{record.tier}, {record.route}, {record.model}]: {record.verdict.value}"
            f"{' — ' + ', '.join(r.value for r in record.reasons) if record.reasons else ''}"
        )
    if state.escalation_reason:
        print(f"escalated: {state.escalation_reason}")

    # A5: what reconcile decided. Since A6 commit writes it, so a second run on the same page should find nothing left to
    # do (every show a no-op); change a stored show by hand (`make db-shell`) to see an update or a removal.
    if state.reconcile_plan is not None:
        plan = state.reconcile_plan
        window = f"{plan.coverage.start} to {plan.coverage.end}" if plan.coverage else "none (no dates on the page)"
        print(f"reconcile: {plan.counts()}; removals judged inside {window}; {len(plan.withheld)} withheld by the guard")
        for decision in plan.shows:
            flag = " (look at this one)" if decision.needs_review else ""
            print(f"  {decision.date} {decision.start_time or 'no time'}: {decision.action.value} - {decision.reason}{flag}")

    # A6: what commit wrote (shows by outcome, artists created) and which shows the database refused. Exits 1 when any
    # were refused, as the scheduled worker does (`main.run_all`), so a script running this can tell.
    failures = 0
    if state.commit_result is not None:
        result = state.commit_result
        failures = len(result.failures)
        print(f"commit: wrote {result.written}; created {result.artists_created} artist(s); {failures} show(s) refused")
        for failure in result.failures:
            print(f"  refused {failure.date} {failure.time or 'no time'} ({failure.action}): {failure.error}")

    # A4: the run is in the database now. These are the questions to ask it (docs/dev/audit-queries.sql).
    # Piped in from the host: psql runs inside the container, where the repo's files aren't visible, so `\i` can't find the file.
    print(f"\nrun {state.run_id} is in the audit trail. From the repo root (runs all six queries):")
    print(
        f"  cat docs/dev/audit-queries.sql | docker compose exec -T postgres psql -U postgres -d calendar_dev"
        f" -v run_id={state.run_id} -v show_id=0 -f -"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(main(args.fixture, args.fetched_on)))
