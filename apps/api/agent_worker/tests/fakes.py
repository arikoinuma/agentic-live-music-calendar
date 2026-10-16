"""A scripted stand-in for the `instructor` client, and page builders, for the A3 tests.

What this is: `test_extraction.FakeCompletions` answers every call the same way. The retry loop
needs the opposite — a model that fails once and then answers, or answers differently on the
second attempt — so `ScriptedClient` answers from an ordered script *per response model*. It is the
fake model client that milestone A7 plans, in the one shape A3 needs; `test_extraction.py` keeps
its own.

How to read it: a script is `{response_model_class: [step, step, ...]}`. Each call to
`client.chat.completions.create(response_model=X, ...)` takes the next step of X's list; the last
step repeats once the list runs out, so "always raises" is one step. A step is an exception (raised),
a dict (validated into the response model), or a ready model. Every call is recorded, including the
model name and the message text, so a test can assert what a retry actually sent.
"""

import datetime
import json
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from agent_worker import act_split, schemas, status_check

# The shapes the pipeline asks the model for, as the keys of a script.
PAGE = schemas.VenueListingsExtraction  # the title-split model route's page call (the adopted route)
SPLITTER = act_split.ActSplitAnswer
STATUS = status_check.StatusAnswer


class ScriptedCompletions:
    def __init__(self, script: dict[type[BaseModel], list[Any]]) -> None:
        self.script = script
        self.cursor: dict[type[BaseModel], int] = {}
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        model = kwargs["response_model"]
        steps = self.script.get(model)
        if not steps:
            raise AssertionError(f"unscripted call for {model.__name__}: the test didn't expect it")
        at = self.cursor.get(model, 0)
        step = steps[min(at, len(steps) - 1)]
        self.cursor[model] = at + 1
        if isinstance(step, BaseException):
            raise step
        return model.model_validate(step) if isinstance(step, dict) else step

    def calls_for(self, model: type[BaseModel]) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["response_model"] is model]


def scripted_client(script: dict[type[BaseModel], list[Any]]) -> SimpleNamespace:
    """A stand-in for the `instructor` client that answers from `script` (see the module docstring)."""
    return SimpleNamespace(chat=SimpleNamespace(completions=ScriptedCompletions(script)))


def completions(client: SimpleNamespace) -> ScriptedCompletions:
    """The client's recorder, typed, so a test can read `.calls` and `.calls_for(...)`."""
    done: ScriptedCompletions = client.chat.completions
    return done


def message_text(call: dict[str, Any]) -> str:
    """The text of the first (user) message of one recorded call."""
    content = call["messages"][0]["content"]
    assert isinstance(content, str)
    return content


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


def split_answer(*titles_and_acts: tuple[str, list[str]]) -> dict[str, Any]:
    """The act splitter's answer for numbered titles, in order."""
    return {"items": [{"id": i, "title": t, "acts": a} for i, (t, a) in enumerate(titles_and_acts)]}


def listing(day: str, title: str, *, time: str | None = None, confidence: float = 0.95, **extra: Any) -> dict[str, Any]:
    """One listing as the title-split page call returns it."""
    return {
        "venue": "The Venue", "date": day, "time": time, "title": title, "is_ambiguous": False,
        "confidence": confidence, **extra,
    }


def listings_answer(*items: dict[str, Any], readable: bool = True) -> dict[str, Any]:
    """The title-split page call's whole answer: its readability flag and its listings."""
    return {"page_readable": readable, "listings": list(items)}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def jsonld_page(*events: dict[str, Any], body: str = "Listings") -> str:
    """A page carrying the given events as one ld+json list block, like White Squirrel's."""
    block = json.dumps([{"@type": "WebSite", "name": "Site"}, *events])
    return f'<html><head><script type="application/ld+json">{block}</script></head><body>{body}</body></html>'


def event(name: str, start: str, **extra: Any) -> dict[str, Any]:
    """A White Squirrel-shaped schema.org Event."""
    return {"@type": "Event", "name": name, "startDate": start, **extra}


def text_page(*lines: str) -> str:
    """A plain page with no JSON-LD: the model route."""
    return "<html><body>" + "".join(f"<p>{line}</p>" for line in lines) + "</body></html>"


FETCHED = datetime.date(2026, 10, 12)


# ---------------------------------------------------------------------------
# A4: the stores the graph writes to, recorded instead of written
# ---------------------------------------------------------------------------
#
# The graph writes its audit trail through `WorkerContext.audit` and its raw staging record through
# `WorkerContext.stager` (agent_worker/context.py). These two stand in for Postgres and MongoDB so the
# graph tests need neither; the tests against the real stores are test_audit_writer.py and
# test_staging_mongo.py. They are typed loosely (`Any`) so this module does not import `agent_worker.audit`
# and stay loadable for tests that only need the model fakes above.


class RecordingAudit:
    """An `AuditWriter` that keeps what it was asked to write, in order, in memory."""

    def __init__(self) -> None:
        self.runs: list[tuple[int, Any]] = []  # (venue_id, trigger) per start_run
        self.entries: list[Any] = []  # AuditEntry, in the order written
        self.finished: list[int] = []

    async def start_run(self, venue_id: int, trigger: Any) -> int:
        self.runs.append((venue_id, trigger))
        return len(self.runs)

    async def record(self, entry: Any) -> int:
        self.entries.append(entry)
        return len(self.entries)

    async def finish_run(self, run_id: int) -> None:
        self.finished.append(run_id)

    def steps(self) -> list[tuple[str, int]]:
        """(step, attempt) per row, the shape most graph tests assert on."""
        return [(e.step_type.value, e.attempt_number) for e in self.entries]


class RecordingStager:
    """A `Stager` that keeps the documents it was given; `fail=True` makes every write raise."""

    def __init__(self, *, fail: bool = False) -> None:
        self.documents: list[dict[str, Any]] = []
        self.fail = fail

    async def stage(self, document: dict[str, Any]) -> str:
        if self.fail:
            raise RuntimeError("the staging store is down")
        self.documents.append(document)
        return f"doc-{len(self.documents)}"
