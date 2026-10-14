"""Tests for `staging.document_for`: the raw record of one extract attempt, as plain data.

Milestone A4 (docs/dev/implementations/a4-auditability.md, step 5; D4; plan review #1 and #6). The document
is what lands in MongoDB before validation judges the attempt, and it is A2.1's E17 record: the route, the
text sent, the route's notes, the raw model output and the request configuration. It must be BSON-encodable:
BSON cannot encode a `datetime.date` (confirmed with `bson.encode`, plan review #1). So these tests encode the
document with `bson.encode`, the driver's own encoder: if that accepts it, the real write will.

How to read it: states are built by hand to look like what `extract_node` leaves behind, a successful
attempt and a failed one. Expected keys and values are the plan's list; no part of the test reads them from
the code under test.
"""

import datetime
from typing import Any

import bson

from agent_worker import extraction
from agent_worker.policy import AttemptPlan
from agent_worker.schemas import VenuePageExtraction
from agent_worker.staging import MongoStager, document_for
from agent_worker.state import VenueGraphState

PLAN = AttemptPlan(tier="narrowed", config=extraction.PIPELINE_CONFIG, options=extraction.PIPELINE_OPTIONS)


def state_with(**changes: Any) -> VenueGraphState:
    fields: dict[str, Any] = {
        "venue_id": 4, "calendar_url": "https://venue.example/events", "venue_name": "The Venue",
        "metro_timezone": "America/Chicago", "run_id": 9, "attempt_count": 2, "last_plan": PLAN,
        "route_attempted": "model", "page_content": "Nona\nOct 20",
    }
    fields.update(changes)
    return VenueGraphState(**fields)


def test_a_successful_attempts_document_has_the_e17_record() -> None:
    # Proves: the document holds what A2.1's eval records per page so a production run can be audited the
    # same way (E17): who and when (run, venue, attempt), how (tier, route, model, request options,
    # configuration), what was sent, the route's notes, and the raw model output.
    extracted = VenuePageExtraction(page_readable=True, shows=[])
    doc = document_for(state_with(
        extraction=extracted, extraction_source="model", extraction_sent_text="Nona\nOct 20",
        extraction_notes={"route": "model", "titles": ["Nona"]},
    ))
    assert (doc["run_id"], doc["venue_id"], doc["attempt"]) == (9, 4, 2)
    assert (doc["tier"], doc["route"], doc["model"]) == ("narrowed", "model", extraction.PIPELINE_OPTIONS.model)
    assert doc["request_options"]["model"] == extraction.PIPELINE_OPTIONS.model
    assert "route" in doc["extraction_config"]
    assert doc["sent_text"] == "Nona\nOct 20" and doc["notes"]["titles"] == ["Nona"]
    assert doc["raw_extraction"] == {"page_readable": True, "shows": []}
    assert doc["error"] is None and isinstance(doc["staged_at"], datetime.datetime)
    assert doc["staged_at"].tzinfo is not None


def test_a_failed_attempts_document_keeps_the_error_and_the_page_it_started_from() -> None:
    # Proves (plan review #6): a failed call has no `sent_text` (`extract_page` raised before returning it)
    # and no raw extraction, but the document still exists, with the error and the cleaned page text the
    # route started from: the record a person debugging an escalation needs most.
    doc = document_for(state_with(extract_error="ValueError: bad json"))
    assert doc["error"] == "ValueError: bad json"
    assert doc["sent_text"] is None and doc["raw_extraction"] is None
    assert doc["page_text"] == "Nona\nOct 20"


def test_a_failed_poster_attempt_does_not_store_the_base64_image_as_page_text() -> None:
    # Proves: on the image route `page_content` is the poster as base64 (megabytes, against MongoDB's 16 MB
    # document limit), so it is never copied into the document as "page text".
    doc = document_for(state_with(extract_error="OpenAIError", route_attempted="image", page_content="AAAA" * 1000))
    assert doc["page_text"] is None


def test_notes_holding_dates_enums_and_tuples_become_plain_data() -> None:
    # Proves (plan review #1): `notes` is an untyped dict, so a date, a StrEnum or a tuple can appear in it.
    # BSON cannot encode `datetime.date` (confirmed with `bson.encode`), so `document_for` converts first
    # and the finished document encodes. Without the conversion `bson.encode` raises `InvalidDocument` here,
    # and in production Gap C would propagate it and halt the run.
    state = state_with(
        extraction_notes={"seen": datetime.date(2026, 10, 12), "pair": ("a", "b"), "route": extraction.PIPELINE_CONFIG.route},
    )
    doc = document_for(state)
    assert doc["notes"]["seen"] == "2026-10-12"
    bson.encode(doc)  # raises InvalidDocument if anything non-BSON got through


def test_a_state_with_no_plan_still_produces_a_document() -> None:
    # Proves: a document is still written if extract_node failed before a plan existed (it sets one first,
    # but staging must not be the thing that hides a different bug behind an AttributeError).
    doc = document_for(state_with(last_plan=None, extract_error="boom"))
    assert doc["tier"] is None and doc["model"] is None and doc["error"] == "boom"


async def test_mongo_stager_inserts_the_document_and_returns_the_id_as_a_string() -> None:
    # Proves: `MongoStager.stage` calls `insert_one` once with the document it was given and returns
    # `str(inserted_id)`, the string that goes on the audit row. A stub collection stands in for the server
    # (the cloud sandbox has none); the real driver is exercised by test_staging_mongo.py where a server exists.
    class StubCollection:
        def __init__(self) -> None:
            self.inserted: list[dict[str, Any]] = []

        async def insert_one(self, document: dict[str, Any]) -> Any:
            self.inserted.append(document)
            return type("Result", (), {"inserted_id": bson.ObjectId("65f0c0ffee0123456789abcd")})()

    stub = StubCollection()
    staging_id = await MongoStager(stub).stage({"run_id": 1})  # type: ignore[arg-type]
    assert staging_id == "65f0c0ffee0123456789abcd"
    assert stub.inserted == [{"run_id": 1}]
