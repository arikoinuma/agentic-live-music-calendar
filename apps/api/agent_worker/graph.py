from langgraph.graph import END, START, StateGraph

from agent_worker.constants import NodeNames, NodeOutcomes
from agent_worker.nodes import (
    commit_node,
    escalate_node,
    extract_node,
    fetch_node,
    reconcile_node,
    validate_node,
)
from agent_worker.state import VenueGraphState

# Confirmed directly against the pinned langgraph==1.2.11 (not assumed —
# the architecture doc specifically warns this library has a history of
# breaking changes between versions):
#   - A node can return either the full state object or a partial dict
#     of just the changed fields; langgraph treats them the same way.
#   - Each node receives a real VenueGraphState instance mid-graph, with
#     full attribute access (state.page_content, etc.) — the existing
#     node functions in nodes.py don't need any changes for this.
#   - compiled_graph.invoke(...)'s return value is a plain dict, not a
#     VenueGraphState — and it only contains fields that were explicitly
#     set at construction or touched by some node; anything left at its
#     class default is simply absent as a key, not present-with-default.
#     Whatever calls .invoke() should re-wrap the result —
#     VenueGraphState(**result) — before treating it as a full state
#     object again.

graph = StateGraph(VenueGraphState)

# add_node once for each of the six imported functions. The name
# you register each under (the first argument) is what
# add_conditional_edges' path_map, and add_edge calls below, need to
# reference — e.g. graph.add_node(NodeNames.FETCH, fetch_node).

graph.add_node(NodeNames.FETCH, fetch_node)
graph.add_node(NodeNames.EXTRACT, extract_node)
graph.add_node(NodeNames.VALIDATE, validate_node)
graph.add_node(NodeNames.RECONCILE, reconcile_node)
graph.add_node(NodeNames.COMMIT, commit_node)
graph.add_node(NodeNames.ESCALATE, escalate_node)

# the straight-line edges — the parts of the pipeline with no
# branching decision involved:
#   START -> fetch
#   fetch -> extract
#   extract -> validate
#   reconcile -> commit
#   commit -> END
#   escalate -> END
# (validate's outgoing edges are NOT in this list — see below, they're
# conditional, not straight-line.)
graph.add_edge(START, NodeNames.FETCH)
graph.add_edge(NodeNames.FETCH, NodeNames.EXTRACT)
graph.add_edge(NodeNames.EXTRACT, NodeNames.VALIDATE)
# Validate node will have a conditional edge below
graph.add_edge(NodeNames.RECONCILE, NodeNames.COMMIT)
graph.add_edge(NodeNames.COMMIT, END)
graph.add_edge(NodeNames.ESCALATE, END)

# the one real branch point. Per the architecture doc: validate
# passing routes to reconcile; a low-confidence/inconsistent result
# retries extract if attempts remain; retries exhausted routes to
# escalate. That's a function of state.confidence and state.attempt_count
# — both of which validate_node already sets — plus one more thing this
# scaffold deliberately leaves for you to decide: what confidence value
# actually counts as "passing"? Nothing in this codebase has picked a
# threshold yet.
#
# Shape to follow — a routing function returning a short string label,
# then add_conditional_edges mapping those labels to the real node names
# from your add_node calls above:
#
#   def route_after_validate(state: VenueGraphState) -> str:
#       if state.confidence >= SOME_THRESHOLD:
#           return node_outcomes.PASS
#       elif state.attempt_count < 3:
#           return node_outcomes.RETRY
#       else:
#           return NodeNames.ESCALATE
#
#   graph.add_conditional_edges(
#       NodeNames.VALIDATE,
#       route_after_validate,
#       {node_outcomes.PASS: NodeNames.RECONCILE, node_outcomes.RETRY: NodeNames.EXTRACT, NodeNames.ESCALATE: NodeNames.ESCALATE},
#   )

def route_after_validate(state: VenueGraphState) -> str:
    if state.confidence >= 0.8:
        return NodeOutcomes.PASS
    elif state.attempt_count < 3:
        return NodeOutcomes.RETRY
    else:
        return NodeNames.ESCALATE

graph.add_conditional_edges(
    NodeNames.VALIDATE,
    route_after_validate,
    {
        NodeOutcomes.PASS: NodeNames.RECONCILE, 
        NodeOutcomes.RETRY: NodeNames.EXTRACT, 
        NodeOutcomes.ESCALATE: NodeNames.ESCALATE
    },
)
    

# compile without a checkpointer, deliberately — graph.compile()
# with nothing else. Per the architecture doc, this job completes in one
# process invocation, so there's nothing to resume; a checkpointer would
# be solving a problem this pipeline doesn't have.
compiled_graph = graph.compile()
