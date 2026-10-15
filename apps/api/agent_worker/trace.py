"""The wrapper that makes a graph node leave an audit row (and, for extract, a staging document).

HOW TO READ THIS
  A graph node (nodes.py) is a plain synchronous `state -> state` function. `audited(step, node)` returns a
  new node, `async` from LangGraph's point of view, that does three things in order:

    1. runs the sync node in a worker thread (`asyncio.to_thread`), so the blocking model call and HTTP fetch
       don't stall the event loop that the database and MongoDB clients live on (plan D1);
    2. for an extract step, stages the attempt's raw record in MongoDB (**Gap C**, below);
    3. appends this step's audit row through the context's writer.

  Keeping this apart from the node bodies is the point of D1: "do the step" stays a pure state transform that
  existing tests call directly, and "record the step" lives here, one wrapper for all six nodes. The row's
  contents are decided by `audit.entry_for` (pure), not here.

  It lives in its own module, not `audit.py`, to keep the imports one-way: audit <- context <- trace <- graph
  (`WorkerContext` holds an `AuditWriter`, so `audit` cannot import `context`).

THE TRAP
  LangGraph injects `runtime` into a node by looking at the node function's own signature. Do not build
  the wrapper with `functools.wraps`: it makes the wrapper report the inner node's signature (which has no
  `runtime` parameter), so LangGraph doesn't inject one and the call fails with
  `TypeError: inner() missing 1 required positional argument: 'runtime'` (verified against langgraph 1.2.11).
  It fails loudly, but the message names the inner node and not the cause.

docs/dev/implementations/a4-auditability.md, D1; Gap C.
"""

import asyncio
from collections.abc import Awaitable, Callable

from langgraph.runtime import Runtime

from agent_worker import staging
from agent_worker.audit import entry_for
from agent_worker.context import WorkerContext
from agent_worker.state import VenueGraphState
from app.enums import StepType

Node = Callable[[VenueGraphState], VenueGraphState]


def audited(step: StepType, node: Node) -> Callable[..., Awaitable[VenueGraphState]]:
    """Wrap `node` so that its run is followed by its audit row (see the module docstring).

    The return type is `Callable[..., ...]`, not the precise `(state, runtime) -> state` signature, because
    LangGraph's own node protocol (`_NodeWithRuntime`) wants `runtime` keyword-only and mypy rejects the
    positional form at `add_node`. LangGraph calls it by parameter name either way; the test
    `test_the_context_reaches_the_audited_nodes` is what proves the injection works.
    """

    async def run(state: VenueGraphState, runtime: Runtime[WorkerContext]) -> VenueGraphState:
        # (1) The step itself, off the event loop. `state` here is rebound to what the node returned: the
        # node mutates and returns the same object, and everything below describes what it produced.
        state = await asyncio.to_thread(node, state)

        # (2) Raw staging, extract only.
        staging_id = None
        if step is StepType.EXTRACT:
            #   Raw staging is the record of what the model was asked and what it
            #   said, BEFORE anyone judged it (arch-initial.md §6, bronze before silver), so it is written
            #   on EVERY attempt, unconditionally, failed ones included. A failed call's document (its
            #   error, route and request configuration) is exactly what a person debugging an escalation
            #   needs, and its id goes into this step's audit row, which is what joins the two stores
            #   (plan D4). `state` is the one the node just returned (line above), because the document
            #   describes what that attempt produced.
            staging_id = await runtime.context.stager.stage(staging.document_for(state))

        # (3) The audit row. If the stager above raised, we never get here: a run whose raw record can't be
        # kept stops, it doesn't continue unaudited.
        await runtime.context.audit.record(entry_for(step, state, staging_id))
        return state

    return run
