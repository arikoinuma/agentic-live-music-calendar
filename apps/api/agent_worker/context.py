"""What the graph's nodes are given besides the state: the stores they write to.

HOW TO READ THIS
  `VenueGraphState` (state.py) is what flows from node to node and is plain data. The two *stores* the audit
  trail needs, Postgres (the audit rows) and MongoDB (the raw staging documents), are live clients bound to
  an event loop, so they do not belong in the state: they are not serialisable, and a test would have to
  build them to build a state. LangGraph's runtime context is the place for them. `graph.py` declares
  `context_schema=WorkerContext`; the caller passes `context=WorkerContext(...)` to `ainvoke`; and
  `trace.audited` reads it from the `runtime` argument LangGraph injects.

  The fields are the `AuditWriter` and `Stager` protocols (audit.py, staging.py), not the concrete classes, so
  the graph tests hand in recording fakes and the real worker hands in `PostgresAuditWriter` and
  `MongoStager`. A5 added the `CalendarReader` (reconcile's read of the stored calendar); A6 adds what commit needs to write.

docs/dev/implementations/a4-auditability.md, decision A4-D1.
"""

from dataclasses import dataclass

from agent_worker.audit import AuditWriter
from agent_worker.calendar_reader import CalendarReader
from agent_worker.staging import Stager


@dataclass(frozen=True)
class WorkerContext:
    """The stores one worker process hands to every node of every venue's graph."""

    audit: AuditWriter
    stager: Stager
    reader: CalendarReader
