"""Runs the White Squirrel fixture through the real worker cycle, for a human to look at.

What this is: the same `run_venue` the scheduled worker uses (agent_worker/main.py), pointed at a saved page
instead of the live URL. So it exercises everything the worker does, including opening an `agent_run`, writing
the audit trail to Postgres and staging each extraction in MongoDB.

Needs (A4): Postgres seeded (`make db-up && make migrate && make seed`), MongoDB up (`make db-up`),
`MONGODB_URI` set in `.env`, and Ollama serving the model. Run from `apps/api`:
`uv run python -m agent_worker.local_test`. (Not collected by pytest: `pyproject.toml` scopes `testpaths`.)
"""

import asyncio
import datetime
import json
from pathlib import Path

from pymongo import AsyncMongoClient

from agent_worker.audit import PostgresAuditWriter
from agent_worker.context import WorkerContext
from agent_worker.main import load_venues, run_venue
from agent_worker.staging import COLLECTION, MongoStager
from app.config import settings
from app.db.session import SessionFactory, engine
from app.enums import RunTrigger
from app.log_config import configure_logging

FIXTURE = "agent_worker/eval/fixtures/Archives_ Events - The White Squirrel Bar.html"
# The fixture was saved on August 17, 2026; the year rule (A2.1, D13) reads this date, and today's would put
# its August shows a year ahead.
FETCHED_ON = datetime.date(2026, 8, 17)


async def main() -> None:
    configure_logging()
    assert settings.mongodb_uri, "set MONGODB_URI in .env (docker compose's mongo is mongodb://localhost:27017)"
    mongo: AsyncMongoClient = AsyncMongoClient(settings.mongodb_uri)
    try:
        ctx = WorkerContext(
            audit=PostgresAuditWriter(SessionFactory),
            stager=MongoStager(mongo[settings.mongodb_database][COLLECTION]),
        )
        async with SessionFactory() as session:
            [venue] = await load_venues(session, venue_id=1)  # The White Squirrel Bar (app/db/seed.py)
        state = await run_venue(
            venue, ctx, trigger=RunTrigger.MANUAL, calendar_url=FIXTURE, fetched_on=FETCHED_ON,
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

    # A4: the run is in the database now. These are the questions to ask it (docs/dev/audit-queries.sql).
    # Piped in from the host: psql runs inside the container, where the repo's files aren't visible, so `\i` can't find the file.
    print(f"\nrun {state.run_id} is in the audit trail. From the repo root (runs all four queries):")
    print(
        f"  cat docs/dev/audit-queries.sql | docker compose exec -T postgres psql -U postgres -d calendar_dev"
        f" -v run_id={state.run_id} -v show_id=0 -f -"
    )


if __name__ == "__main__":
    asyncio.run(main())
