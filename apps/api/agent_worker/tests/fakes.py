"""A scripted stand-in for the `instructor` client, and page builders, for the A3 tests.

What this is: `test_extraction.FakeCompletions` answers every call the same way. The retry loop
needs the opposite — a model that fails once and then answers, or answers differently on the
second attempt — so `ScriptedCompletions` (built by `scripted_client()`) answers from an ordered script *per
response model*. It is the suite's fake model client for the graph tests (built in A3, extended in A5), and it raises
on a call nobody scripted. `test_extraction.py` and `test_prompts.py` keep their own, which deliberately answer every
call the same way (A7).

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

import httpx
import openai
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError

from agent_worker import act_split, artist_match, schemas, status_check

# The shapes the pipeline asks the model for, as the keys of a script.
PAGE = schemas.VenueListingsExtraction  # the title-split model route's page call (the adopted route)
SPLITTER = act_split.ActSplitAnswer
STATUS = status_check.StatusAnswer
ARTIST_MATCH = artist_match.ArtistMatchAnswer  # the ambiguous-artist question (A5)


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


class FakeReader:
    """A `CalendarReader` that returns the stored shows and artists it was given (A5), and records what it was asked.

    `fail=True` makes every read raise, to prove an unreadable calendar stops the run instead of looking empty.
    Typed loosely, like the fakes above, so this module does not import the reader.
    """

    def __init__(self, stored: list[Any] | None = None, artists: list[Any] | None = None, *, fail: bool = False) -> None:
        self.stored = stored or []
        self.known = artists or []
        self.fail = fail
        self.reads: list[tuple[int, datetime.date, datetime.date]] = []  # (venue_id, start, end) per stored_shows call

    async def stored_shows(self, venue_id: int, start: datetime.date, end: datetime.date) -> list[Any]:
        if self.fail:
            raise RuntimeError("the calendar is unreadable")
        self.reads.append((venue_id, start, end))
        return [s for s in self.stored if start <= s.date <= end]

    async def artists(self) -> list[Any]:
        if self.fail:
            raise RuntimeError("the calendar is unreadable")
        return list(self.known)


# ---------------------------------------------------------------------------
# A6: the calendar writer, recorded instead of written; and the errors a real database raises
# ---------------------------------------------------------------------------


class _DriverError(Exception):
    """Stands in for the exception the database driver wraps: it carries the `sqlstate` the dialect copies onto `orig`.

    On the real driver (SQLAlchemy 2.0 with asyncpg) this attribute is ALWAYS present: a server error has its five
    character SQLSTATE and a client-side error (a lost connection) has `None` (A6-PR2-1)."""

    def __init__(self, message: str, sqlstate: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


# The shapes below were measured against the installed driver (the A6 plan reviews), not guessed: only an integrity
# violation arrives as `IntegrityError`; an overflow is a plain `DBAPIError`; a real lost connection is an
# `InterfaceError` whose `orig.sqlstate` is None and whose `connection_invalidated` is True. Tests build every database
# error from these helpers so none invents a shape the driver never produces.


def connection_error() -> openai.APIConnectionError:
    """A real `openai` connection error, as the pipeline sees when the model server is unreachable.

    openai 2.x takes an `httpx.Request` and 3.x an `httpx2.Request`. The error only stores the request and the
    tests never read it, so it is passed as `Any` and one helper builds it for both versions, instead of every
    test choosing a library that the lockfile and a plain upgrade disagree on.
    """
    request: Any = httpx.Request("POST", "http://localhost:11434/v1")
    return openai.APIConnectionError(request=request)


def overflow() -> DBAPIError:
    """A price too large for `Numeric(10, 2)`: SQLSTATE 22003 (class 22, a data exception), a plain `DBAPIError`."""
    return DBAPIError("INSERT INTO show ...", {}, _DriverError("numeric field overflow", "22003"))


def check_violation() -> IntegrityError:
    """A CHECK constraint refusing a row: SQLSTATE 23514 (class 23), an `IntegrityError`."""
    return IntegrityError("INSERT INTO show ...", {}, _DriverError('violates check constraint "show_tmp_check"', "23514"))


def foreign_key_violation() -> IntegrityError:
    """A foreign key with no target (a lineup naming an artist that doesn't exist): SQLSTATE 23503."""
    return IntegrityError("INSERT INTO show_artist ...", {}, _DriverError("violates foreign key constraint", "23503"))


def lost_connection() -> InterfaceError:
    """What a dropped connection really is: an `InterfaceError` with `orig.sqlstate = None`, `connection_invalidated`."""
    return InterfaceError("SELECT 1", {}, _DriverError("connection is closed", None), connection_invalidated=True)


def client_side_error() -> InterfaceError:
    """A client-side driver error that is NOT an invalidated connection (for example a second operation started on a busy
    connection): an `InterfaceError` with `orig.sqlstate = None` and `connection_invalidated` False. It is not about a row
    either, and it exercises the SQLSTATE test on its own: with the invalidated flag clear, only `sqlstate or ""` stands
    between a `None` and a `None[:2]` crash."""
    return InterfaceError("SELECT 1", {}, _DriverError("another operation is in progress", None))


def connection_failure(sqlstate: str = "08006") -> DBAPIError:
    """A server-side connection error (class 08, or 57P01 for an admin shutdown): a `DBAPIError` that is NOT about a row."""
    return DBAPIError("SELECT 1", {}, _DriverError("connection failure", sqlstate))


class FakeWriter:
    """A `CalendarWriter` that records the operations it is given and writes nothing (A6).

    `fail` maps the position of a call (0 for the first operation) to the exception to raise for it, for the tests of
    the failure path. With an `audit` (a `RecordingAudit`) it also appends the rows a real write would, so a graph test
    can see the whole trail in order: one per artist it "created", then the show's. Ids are made up, counting up from
    values no real test row uses. Typed loosely and importing the audit builders only inside the method, like the other
    fakes, so this module stays loadable for tests that only need the model fakes.
    """

    def __init__(self, audit: Any = None, *, fail: dict[int, BaseException] | None = None) -> None:
        self.audit = audit
        self.fail = fail or {}
        self.ops: list[Any] = []  # every operation handed in, including ones made to fail
        self.artist_ids_seen: list[dict[str, int]] = []  # the `artist_ids` each call was given (a copy)
        self._next_show = 1000
        self._next_artist = 5000

    async def write_show(self, op: Any, artist_ids: Any, *, run_id: int | None, attempt_number: int) -> Any:
        from agent_worker.audit import artist_created_entry, show_write_entry
        from agent_worker.calendar_writer import ShowWritten

        position = len(self.ops)
        self.ops.append(op)
        self.artist_ids_seen.append(dict(artist_ids))
        if position in self.fail:
            raise self.fail[position]
        created: dict[str, int] = {}
        for key in op.new_artist_names:
            if key not in artist_ids:
                created[key] = self._next_artist
                self._next_artist += 1
        show_id = op.stored_id if op.stored_id is not None else self._next_show
        self._next_show += 1
        if self.audit is not None:
            for key, artist_id in created.items():
                await self.audit.record(artist_created_entry(
                    run_id=run_id, attempt_number=attempt_number, artist_id=artist_id, name=op.new_artist_names[key], key=key,
                ))
            await self.audit.record(show_write_entry(
                op, run_id=run_id, attempt_number=attempt_number, show_id=show_id,
                previous=None if op.stored_id is None else {"fake": True}, new={"fake": True},
            ))
        return ShowWritten(show_id, op.outcome, created)
