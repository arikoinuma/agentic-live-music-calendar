from enum import StrEnum


class NodeNames(StrEnum):
    """ 
        Creating an enum to store node names so 
        we are not passing plain strings to identify nodes
    """
    FETCH = "fetch"
    EXTRACT = "extract"
    VALIDATE = "validate"
    RECONCILE = "reconcile"
    COMMIT = "commit"
    ESCALATE = "escalate"

class NodeOutcomes(StrEnum):
    """ 
        Same as above but for what happens when a node
        finishes
    """
    PASS = "pass"
    RETRY = "retry"
    ESCALATE = "escalate"