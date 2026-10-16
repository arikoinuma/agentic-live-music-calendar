"""The one test against a real MongoDB: `MongoStager` writes a document and the id finds it again.

Milestone A4 (docs/dev/implementations/a4-auditability.md, Test approach §3, A4-D3). Everything else about
staging is tested with the recording fake; this proves the real driver accepts what `document_for`
builds and that the id `stage` returns is the one the audit row will store. It runs against the
`mongo` service in docker-compose.yml (or CI's), at `MONGODB_TEST_URI` (default `mongodb://localhost:27017`;
a shell/CI variable, never `.env`, which `Settings` forbids unknown keys in).

Skips when no server answers within a second, like the DB tests skip without Postgres, except under CI,
where a missing service is a failure and not a quiet skip. The cloud sandbox has no Docker, so it skips there.
It writes to a database named `calendar_staging_test` and drops it afterwards.
"""

import datetime
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from agent_worker import extraction
from agent_worker.policy import AttemptPlan
from agent_worker.staging import MongoStager, document_for
from agent_worker.state import VenueGraphState

URI = os.environ.get("MONGODB_TEST_URI", "mongodb://localhost:27017")
TEST_DATABASE = "calendar_staging_test"


@pytest_asyncio.fixture(loop_scope="session")
async def client() -> AsyncIterator[AsyncMongoClient]:
    """A connected client, or a skip (a failure under CI) when no server answers."""
    mongo: AsyncMongoClient = AsyncMongoClient(URI, serverSelectionTimeoutMS=1000)
    try:
        await mongo.admin.command("ping")
    except PyMongoError as err:
        await mongo.close()
        if os.environ.get("CI"):
            pytest.fail(f"CI requires MongoDB at {URI}: {err}")
        pytest.skip(f"no MongoDB at {URI} (start it with `make db-up`)")
    yield mongo
    await mongo.drop_database(TEST_DATABASE)
    await mongo.close()


async def test_stage_returns_the_id_of_the_stored_document(client: AsyncMongoClient) -> None:
    # Proves: `stage` inserts the document `document_for` builds (including a note holding a `date`, which
    # BSON could not encode unconverted) and returns the `_id` as a string: the same string the extract row
    # stores as `detail.staging_id`, so a person can paste it into `db.extraction_staging.findOne(...)`.
    state = VenueGraphState(
        venue_id=4, calendar_url="https://venue.example/events", venue_name="The Venue",
        metro_timezone="America/Chicago", run_id=9, attempt_count=1, route_attempted="model",
        last_plan=AttemptPlan(tier="initial", config=extraction.PIPELINE_CONFIG, options=extraction.PIPELINE_OPTIONS),
        extraction_notes={"seen": datetime.date(2026, 10, 12)}, extract_error="ValueError: bad json",
    )
    collection = client[TEST_DATABASE]["extraction_staging"]
    staging_id = await MongoStager(collection).stage(document_for(state))
    assert isinstance(staging_id, str)

    from bson import ObjectId

    stored = await collection.find_one({"_id": ObjectId(staging_id)})
    assert stored is not None
    assert (stored["run_id"], stored["venue_id"], stored["attempt"]) == (9, 4, 1)
    assert stored["error"] == "ValueError: bad json"
    assert stored["notes"] == {"seen": "2026-10-12"}
    assert isinstance(stored["staged_at"], datetime.datetime)
