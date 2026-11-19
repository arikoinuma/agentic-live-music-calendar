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
  `MongoStager`. A5 added the `CalendarReader` (reconcile's read of the stored calendar); A6 added the `CalendarWriter` (commit's
  writes, each show in its own transaction with its audit row). C9 added the `SnapshotStore` (where a fetched page is
  kept) as the one field WITH a default, `NoSnapshotStore`, which writes nothing, so every place that builds a context
  without one (the eval harness, `local_test.py`, the tests) is unchanged.

docs/dev/implementations/a4-auditability.md, decision A4-D1; c9-r2-snapshots.md, C9-D2, C9-D6.
"""

from dataclasses import dataclass, field

from agent_worker.audit import AuditWriter
from agent_worker.calendar_reader import CalendarReader
from agent_worker.calendar_writer import CalendarWriter
from agent_worker.snapshots import NoSnapshotStore, SnapshotStore
from agent_worker.staging import Stager


@dataclass(frozen=True)
class WorkerContext:
    """The stores one worker process hands to every node of every venue's graph."""

    audit: AuditWriter
    stager: Stager
    reader: CalendarReader
    writer: CalendarWriter
    # A `default_factory`, not a shared `NoSnapshotStore()` instance as the default: every context then gets its own
    # store, and the field stays correct if `NoSnapshotStore` ever gains state or becomes a dataclass (whose instances
    # the dataclass machinery refuses as a plain default). Today it is a plain stateless class, so a plain default would
    # also build (C9-PR1-10, C9-CR1-2).
    snapshots: SnapshotStore = field(default_factory=NoSnapshotStore)
