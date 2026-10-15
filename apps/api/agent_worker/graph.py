from langgraph.graph import END, START, StateGraph

from agent_worker.constants import NodeNames, NodeOutcomes
from agent_worker.context import WorkerContext
from agent_worker.nodes import (
    commit_node,
    escalate_node,
    extract_node,
    fetch_node,
    reconcile_node,
    validate_node,
)
from agent_worker.policy import decide_route
from agent_worker.state import VenueGraphState
from agent_worker.trace import audited
from app.enums import StepType

# Confirmed directly against the pinned langgraph==1.2.11 (not assumed —
# the architecture doc specifically warns this library has a history of
# breaking changes between versions):
#   - A node can return either the full state object or a partial dict
#     of just the changed fields; langgraph treats them the same way.
#   - Each node receives a real VenueGraphState instance mid-graph, with
#     full attribute access (state.page_content, etc.) — the existing
#     node functions in nodes.py don't need any changes for this.
#   - compiled_graph.ainvoke(...)'s return value is a plain dict, not a
#     VenueGraphState — and it only contains fields that were explicitly
#     set at construction or touched by some node; anything left at its
#     class default is simply absent as a key, not present-with-default.
#     Whatever calls .ainvoke() should re-wrap the result —
#     VenueGraphState(**result) — before treating it as a full state
#     object again.
#
# A4 (docs/dev/implementations/a4-auditability.md, D1): every node is registered through `audited(...)`,
# which makes it `async` from LangGraph's point of view (it awaits the audit write on the event loop that
# owns the database and MongoDB clients) while the node body stays a plain sync function run in a
# thread. So this graph is `ainvoke`-only: LangGraph raises `TypeError: No synchronous function provided`
# on `invoke()`, which is how a stale caller announces itself. The stores reach the wrapper through the
# runtime context (`context_schema` below; `ainvoke(state, context=WorkerContext(...))`), not the state.

graph = StateGraph(VenueGraphState, context_schema=WorkerContext)

# One add_node per node function. The name each is registered under is what the conditional
# edges' path maps and the add_edge calls below refer to.
#
# A4 (code review #2): the node name and the audit step are the same six strings (`NodeNames` here,
# `StepType` in app/enums.py), so the step is DERIVED from the name, `StepType(name.value)`, instead of
# being paired by hand in six lines. A node added to this table without a matching `StepType` fails at
# import with a ValueError; test_graph_wiring.py pins the table to both enums.
NODE_FUNCTIONS = {
    NodeNames.FETCH: fetch_node,
    NodeNames.EXTRACT: extract_node,
    NodeNames.VALIDATE: validate_node,
    NodeNames.RECONCILE: reconcile_node,
    NodeNames.COMMIT: commit_node,
    NodeNames.ESCALATE: escalate_node,
}
for node_name, node_function in NODE_FUNCTIONS.items():
    graph.add_node(node_name, audited(StepType(node_name.value), node_function))

# The shape (docs/dev/implementations/a3-validation-and-retry.md, Design §4):
#
#   START -> fetch --ok--------------> extract -> validate --pass--------> reconcile -> commit -> END
#              |                          ^           |
#              +--fetch_error--> escalate +--retry----+
#                                  ^                  +--escalate--> escalate -> END
#
# The straight-line edges are the parts with no decision in them. Fetch and validate each have a
# conditional edge instead of a plain one.
graph.add_edge(START, NodeNames.FETCH)
graph.add_edge(NodeNames.EXTRACT, NodeNames.VALIDATE)
graph.add_edge(NodeNames.RECONCILE, NodeNames.COMMIT)
graph.add_edge(NodeNames.COMMIT, END)
graph.add_edge(NodeNames.ESCALATE, END)


def route_after_fetch(state: VenueGraphState) -> NodeOutcomes:
    """A page that couldn't be fetched (or came back empty) is escalated: there is nothing to
    extract from, and a model handed a blank page can answer "confirmed empty" (A3-D6)."""
    return NodeOutcomes.ESCALATE if state.fetch_error else NodeOutcomes.PASS


def route_after_validate(state: VenueGraphState) -> NodeOutcomes:
    """Read the verdict validate_node produced and the attempt count; nothing else.

    A thin reader of `policy.decide_route`, where the decision lives. It returns `NodeOutcomes`
    members only, and says so in its annotation (G6): the old router returned `NodeNames.ESCALATE`
    against a path map keyed on `NodeOutcomes.ESCALATE`, which worked only because two different
    StrEnums happen to share the string "escalate", and compared `state.confidence >= 0.8`
    where the field is `float | None`. The verdict is never None here, and confidence never
    reaches a comparison in this file.
    """
    verdict = state.validation.verdict if state.validation is not None else None
    return decide_route(verdict, state.attempt_count, state.policy)


graph.add_conditional_edges(
    NodeNames.FETCH,
    route_after_fetch,
    {
        NodeOutcomes.PASS: NodeNames.EXTRACT,
        NodeOutcomes.ESCALATE: NodeNames.ESCALATE,
    },
)

graph.add_conditional_edges(
    NodeNames.VALIDATE,
    route_after_validate,
    {
        NodeOutcomes.PASS: NodeNames.RECONCILE,
        NodeOutcomes.RETRY: NodeNames.EXTRACT,
        NodeOutcomes.ESCALATE: NodeNames.ESCALATE,
    },
)

# compile without a checkpointer, deliberately — graph.compile()
# with nothing else. Per the architecture doc, this job completes in one
# process invocation, so there's nothing to resume; a checkpointer would
# be solving a problem this pipeline doesn't have.
compiled_graph = graph.compile()
