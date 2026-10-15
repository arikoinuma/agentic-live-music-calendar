"""The raw staging record of one extract attempt, and where it is kept (MongoDB).

HOW TO READ THIS
  Every extract attempt, successful or not, produces one *staging document*: what the model was asked, how, and
  what it answered, **before validation has judged it**. That is the "raw" in raw staging (arch-initial.md §6,
  "bronze before silver"): Postgres holds only what passed, MongoDB holds everything that was tried. For an
  escalated venue it is the record of what went wrong on each attempt.

  It is also the record A2.1-E17 asked for: the route taken, the text actually sent, the route's notes, the raw model output and
  the request configuration, the same things the eval harness records per page, so a production run can be
  audited the way the eval runs were.

  * `document_for(state)` builds the document from the state *after* `extract_node` ran. Pure.
  * `Stager` is the interface the graph writes through; `MongoStager` is the real one (`pymongo`'s
    `AsyncMongoClient`, not Motor, which MongoDB deprecated; arch-initial.md §6). Tests use
    `fakes.RecordingStager`.
  * The id `stage` returns is stored on the extract audit row as `detail.staging_id`, which is how the two
    stores join (plan A4-D4).

docs/dev/implementations/a4-auditability.md, decisions A4-D3 and A4-D4; A4-R1-1 and A4-R1-6.
"""

import dataclasses
import datetime
from typing import Any, Protocol

from pydantic_core import to_jsonable_python
from pymongo.asynchronous.collection import AsyncCollection

from agent_worker.state import VenueGraphState

# The collection documents go to. One collection, one document per extract attempt.
COLLECTION = "extraction_staging"


class Stager(Protocol):
    """Where staging documents are written. Returns the stored document's id as a string."""

    async def stage(self, document: dict[str, Any]) -> str: ...


def document_for(state: VenueGraphState) -> dict[str, Any]:
    """The staging document for the extract attempt that just ran, as plain BSON-safe data.

    Everything except `staged_at` goes through `to_jsonable_python` first: `notes` is an untyped dict and
    BSON cannot encode a `datetime.date` (nor a dataclass), so a date in a route's notes would otherwise
    raise `InvalidDocument` inside the staging write, which halts the run (A4-R1-1).
    `staged_at` stays a timezone-aware `datetime`, which BSON stores natively.
    """
    plan = state.last_plan
    # A failed call never returned its `sent_text` (extract_page raised first), but the page it started
    # from is in the state, so keep that: the record a person debugging an escalation wants most (review
    # #6). Not for the poster route, where `page_content` is the image as base64: megabytes, against
    # MongoDB's 16 MB document limit, and not text.
    failed = state.extract_error is not None
    page_text = state.page_content if failed and state.route_attempted != "image" else None

    body: dict[str, Any] = {
        "run_id": state.run_id,
        "venue_id": state.venue_id,
        "attempt": state.attempt_count,
        "tier": plan.tier if plan else None,
        "route": state.route_attempted,
        "model": plan.options.model if plan else None,
        "larger_model_used": plan.larger_model_used if plan else False,
        "request_options": dataclasses.asdict(plan.options) if plan else None,
        "extraction_config": dataclasses.asdict(plan.config) if plan else None,
        "sent_text": state.extraction_sent_text,
        "page_text": page_text,
        "notes": state.extraction_notes,
        "raw_extraction": state.extraction.model_dump(mode="json") if state.extraction else None,
        "error": state.extract_error,
    }
    document: dict[str, Any] = to_jsonable_python(body)
    document["staged_at"] = datetime.datetime.now(datetime.UTC)
    return document


class MongoStager:
    """Writes staging documents to a MongoDB collection with the async PyMongo driver."""

    def __init__(self, collection: AsyncCollection[dict[str, Any]]) -> None:
        self._collection = collection

    async def stage(self, document: dict[str, Any]) -> str:
        result = await self._collection.insert_one(document)
        return str(result.inserted_id)
