"""Tests that the graph's nodes and the audit trail's steps are the same six things, paired correctly.

Milestone A4, code review round 1 #2. `NodeNames` (agent_worker/constants.py) names the graph's nodes and
`StepType` (app/enums.py) names the `audit_log.step_type` values; they are deliberately the same six strings,
and A1 left A4 the job of making them unable to drift apart ("import one from the other or assert they agree in
a test", `StepType`'s docstring). A drift would write rows under the wrong `step_type`, and every saved query
reads that column.

How to read it: the graph module exposes `NODE_FUNCTIONS` (node name -> function), from which it derives each
node's audit step with `StepType(name.value)`. These tests pin that table to both enums. Expected values are
the six names in `data-model-initial.md` §3 (`step_type`), spelled out here, not read from either enum.
"""

from agent_worker.constants import NodeNames
from agent_worker.graph import NODE_FUNCTIONS, compiled_graph
from app.enums import StepType

SIX = {"fetch", "extract", "validate", "reconcile", "commit", "escalate"}


def test_the_two_enums_hold_the_same_six_values() -> None:
    # Proves: `NodeNames` and `StepType` agree with each other and with the spec's six steps. A seventh node
    # added to one and not the other fails here, instead of crashing at import or writing a wrong row later.
    assert {n.value for n in NodeNames} == SIX
    assert {s.value for s in StepType} == SIX


def test_each_node_name_is_paired_with_the_function_of_that_name() -> None:
    # Proves: the table pairs each name with its own function (`extract` -> `extract_node`). Because the audit
    # step is derived from the name, a copy-paste pairing like `EXTRACT -> validate_node` (which would write
    # validate's evidence under the extract step) is caught here.
    assert {name.value for name in NODE_FUNCTIONS} == SIX
    for name, function in NODE_FUNCTIONS.items():
        assert function.__name__ == f"{name.value}_node"


def test_the_compiled_graph_registers_exactly_those_nodes() -> None:
    # Proves: every table entry is a node of the compiled graph and the graph has no others (LangGraph adds
    # the `__start__` pseudo-node, ignored).
    registered = {name for name in compiled_graph.nodes if not name.startswith("__")}
    assert registered == SIX
