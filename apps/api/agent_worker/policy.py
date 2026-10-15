"""The retry policy: how evidence becomes a verdict, a verdict becomes a route, and a retry changes.

What this is: the decisions around validation, kept out of the nodes so they can be tested without a
graph (docs/dev/implementations/a3-validation-and-retry.md, Design §1, §3, §4). `validation.py`
gathers the evidence and decides nothing; this module decides.

How to read it, top to bottom:
1. `RetryPolicy` — the named, injectable settings (the confidence threshold and the attempt cap
   used to be literals inside the routing function). A8 varies them by passing a different policy.
2. `AttemptRecord` / `AttemptPlan` — what one attempt did, and what the next one will change.
3. `combine` (A3-Gap-D) — evidence + confidence -> one verdict, and `decide_route` — verdict
   + attempt count -> the graph's next step.
4. `retry_hint` and `plan_for_attempt` (A3-Gap-E) — what makes a retry different from the
   call before it. At temperature 0 an unchanged retry returns the same answer (A2.1's confirmation
   run: five runs, byte-identical output), so without this the retry loop is a loop, not a retry.

Import order, so the stubs import cleanly: `validation.py` <- `policy.py` <- `state.py` <- the
nodes and the graph. Nothing here imports from `state.py`.
"""

from dataclasses import (
    dataclass,
    replace,
)
from typing import Literal

from agent_worker.constants import NodeOutcomes
from agent_worker.extraction import ExtractionConfig
from agent_worker.llm import RequestOptions
from agent_worker.validation import (
    CheckCode,
    FailureReason,
    Finding,
    PageOutcome,
    Target,
    ValidationResult,
    Verdict,
)
from app.config import settings

# The route an attempt *used*: recorded even when the attempt failed, because `extraction_source`
# is None for a failed attempt and the sticky route fallback must still see a failed JSON-LD one.
Route = Literal["jsonld", "model", "image"]

# ---------------------------------------------------------------------------
# The settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    """Frozen, like `ExtractionConfig`, so a run's policy can't change halfway through it."""

    # Low confidence fails a record only when nothing deterministic has (A3-D9). 0.8 was the literal in
    # the old router; A8 checks whether the number is right.
    confidence_threshold: float = 0.8
    # Total extract attempts, the first included ("Retries are capped (3 attempts)", arch §7).
    max_attempts: int = 3
    # The larger model tier 3 uses (arch §7: "larger model second"). Unset until H1 provides a hosted
    # model: the development laptop can't run one (A3-D5). Unset = tier 3 runs the same model with
    # the full hint and the record says so. Must be an Ollama model name until H1 makes endpoints
    # per call, because `instructor_client` is bound to Ollama.
    escalation_model: str | None = None

    def __post_init__(self) -> None:
        # `ESCALATION_MODEL_NAME=` (uncommented, left empty) is read as "" and not None, which would
        # make A3-Gap-E record `larger_model_used=True` while the same model runs — the misreport A3-D5
        # exists to stop (code review round 1, #3). An empty name means "none configured".
        if not self.escalation_model:
            object.__setattr__(self, "escalation_model", None)


DEFAULT_POLICY = RetryPolicy(escalation_model=settings.escalation_model_name)


# ---------------------------------------------------------------------------
# What an attempt did, and what the next one will change
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptPlan:
    """How one attempt will run: the tier's name, the extraction configuration (which carries the
    retry hints and the route), and the request options (which carry the model)."""

    tier: Literal["initial", "narrowed", "larger_model"]
    config: ExtractionConfig
    options: RequestOptions
    # False when tier 3 was planned but no escalation model is configured — the audit record
    # must not claim a larger model ran when it didn't (A3-D5).
    larger_model_used: bool = False


@dataclass(frozen=True)
class AttemptRecord:
    """One row of `state.attempt_history`, appended by `validate_node`: what A4 will persist and
    A8 will measure. Retries add rows; nothing is overwritten (the same idea as `audit_log`)."""

    attempt: int
    tier: str
    model: str
    route: Route | None
    error: str | None
    verdict: Verdict
    reasons: list[FailureReason]
    # The error findings themselves, not just their codes: the retry hints are built from the
    # messages (plan, §3).
    findings: list[Finding]
    confidence: float | None
    error_count: int
    warning_count: int
    larger_model_used: bool = False


# ---------------------------------------------------------------------------
# One verdict, not one float (A3-Gap-D)
# ---------------------------------------------------------------------------


def combine(result: ValidationResult, policy: RetryPolicy) -> ValidationResult:
    """Turn the evidence into a verdict and the ordered reasons for a failure."""
    # A deterministic error ("free admission AND a $15 price") and a model's self-reported confidence
    # are different KINDS of evidence, so the router is given a verdict, not a float. Errors fail the
    # record whatever the confidence (a model that is 0.99 sure of a past date is still wrong). Low
    # confidence fails it only when nothing else has. A confidence of None means "no model judged
    # this": no evidence, not zero, which is why the `is not None` guard below matters (comparing
    # None would raise on every JSON-LD page, G6's original bug). The reasons keep everything that
    # applies, strongest first, so the retry hint and the audit trail can say why (alpha-build-plan.md
    # A3: "collapsing both into one float may be losing information").
    reasons = []
    if result.extraction_failed:
        reasons.append(FailureReason.EXTRACT_FAILED)
    if result.outcome is PageOutcome.UNREADABLE:
        reasons.append(FailureReason.UNREADABLE)
    if result.errors:
        reasons.append(FailureReason.CHECK_ERRORS)
    if result.confidence is not None and result.confidence < policy.confidence_threshold:
        reasons.append(FailureReason.LOW_CONFIDENCE)
    if reasons:
        return result.with_verdict(Verdict.FAILED, reasons)
    if result.outcome is PageOutcome.CONFIRMED_EMPTY:
        return result.with_verdict(Verdict.CONFIRMED_EMPTY, [])
    return result.with_verdict(Verdict.PASSED, [])


def decide_route(verdict: Verdict | None, attempt_count: int, policy: RetryPolicy) -> NodeOutcomes:
    """The graph's next step after validate: pass on, run extract again, or give up."""
    if verdict is None:
        # validate_node always sets one; None means the graph was wired wrong. Loud, not routed.
        raise ValueError("decide_route called before validation produced a verdict")
    # The router reads the verdict and the attempt count only, and returns `NodeOutcomes` members
    # only (G6). The old router returned `NodeNames.ESCALATE` against a path map keyed on
    # `NodeOutcomes.ESCALATE`; it worked only because two different StrEnums share the string
    # "escalate". The cap comes from the policy, not a literal 3, so A8 can vary it.
    if verdict is not Verdict.FAILED:
        return NodeOutcomes.PASS
    if attempt_count < policy.max_attempts:
        return NodeOutcomes.RETRY
    return NodeOutcomes.ESCALATE


# ---------------------------------------------------------------------------
# A retry that changes the request (A3-Gap-E)
# ---------------------------------------------------------------------------

# One fixed sentence per check code: what to look at again. Used beside the finding's own message,
# never instead of it, and never quoting a labelled answer (a test scans for that).
_ADVICE: dict[CheckCode, str] = {
    CheckCode.DATE_IMPLAUSIBLE: "Check each show's date against the page; read the month and day carefully.",
    CheckCode.FREE_WITH_PRICE: "Only mark a show free if the listing says so, and then give it no price.",
    CheckCode.EMPTY_BUT_DATED: "The page names dates; make sure every listed show is returned.",
    CheckCode.JSONLD_UNDER_REPORTED: "The page lists more shows than its structured data does; read the page text.",
    CheckCode.BLANK_ACT_NAME: "Every act needs a name as written in the listing.",
    CheckCode.SPLITTER_DROPPED: "Return an entry for every id you were given, with an empty list for a non-music title.",
}

_REASON_ADVICE: dict[FailureReason, str] = {
    FailureReason.EXTRACT_FAILED: "The earlier answer could not be used; reply with valid JSON in the requested shape.",
    FailureReason.UNREADABLE: "The page was judged unreadable before; re-read it, and set page_readable accordingly.",
    FailureReason.LOW_CONFIDENCE: "Confidence was low on some shows; return only what the page states.",
}


# What the last attempt adds beyond the findings (A3, found by test_graph's different-request test):
# when attempt 2 failed the same check as attempt 1, the union of findings is the same text, so
# without this attempt 3 on a machine with no larger model would be byte-identical to attempt 2 — G5
# again. It also states Ari's tiered standard to the model: a missing field is tolerated, a wrong one
# is not.
_FINAL_PAGE_ADVICE = (
    "This is the last attempt. If the page doesn't clearly state a field, leave it null rather than guess."
)
_FINAL_SPLITTER_ADVICE = (
    "This is the last attempt. Copy each act's name exactly as the title writes it; never add a name the title doesn't contain."
)


def retry_hint(history: list[AttemptRecord], final: bool = False) -> tuple[str, str]:
    """The text to add to the next attempt's requests: (for the page model, for the act splitter).

    `final` marks the last attempt, which always adds its own sentence to both parts (see above).

    Built from the error findings of every earlier attempt, de-duplicated, so an earlier attempt's
    reason isn't lost when a later one failed for another. Each finding goes to the call that
    produces the field it is about (`Finding.target`): a date problem must not disturb the act
    splitter, which A2.1 found to be the most sensitive call. Either part may be empty, and both
    are empty with no history, which leaves the request byte-identical to the first attempt's.
    """
    lines: dict[Target, list[str]] = {Target.PAGE: [], Target.SPLITTER: []}

    def add(target: Target, line: str) -> None:
        if line not in lines[target]:
            lines[target].append(line)

    for record in history:
        for reason in record.reasons:
            if reason in _REASON_ADVICE:
                add(Target.PAGE, f"- {_REASON_ADVICE[reason]}")
        for finding in record.findings:
            add(finding.target, f"- {finding.message}")
            if finding.code in _ADVICE:
                add(finding.target, f"- {_ADVICE[finding.code]}")
    if final:
        add(Target.PAGE, f"- {_FINAL_PAGE_ADVICE}")
        add(Target.SPLITTER, f"- {_FINAL_SPLITTER_ADVICE}")
    return "\n".join(lines[Target.PAGE]), "\n".join(lines[Target.SPLITTER])


def route_falls_back(record: AttemptRecord) -> bool:
    """True when this attempt used the JSON-LD route and failed for a reason a retry on that route
    can't change.

    On the JSON-LD route dates, times and prices come from code and the page hint has no consumer
    (only the act splitter calls a model), so only a failure that is *solely* about acts — and so
    reaches the splitter's hint — is worth retrying on the same route. Anything else (an
    under-report, an unreadable or empty-but-dated page, a malformed date that raised) repeats
    byte for byte, so the next attempt reads the page text with the model route instead. An
    out-of-window date isn't here on purpose: it is excluded, not failed (A3-D13), because the model
    route's year rule would re-date it into a plausible, wrong date.
    """
    if record.route != "jsonld" or record.verdict is not Verdict.FAILED:
        return False
    splitter_only = (
        record.reasons == [FailureReason.CHECK_ERRORS]
        and bool(record.findings)
        and all(f.target is Target.SPLITTER for f in record.findings)
    )
    return not splitter_only


def plan_for_attempt(
    attempt: int, policy: RetryPolicy, history: list[AttemptRecord],
    base_config: ExtractionConfig, base_options: RequestOptions,
) -> AttemptPlan:
    """How attempt number `attempt` (1-based) should run, given the attempts before it."""
    if attempt <= 1:
        # Nothing changes on the first attempt: the pipeline's own configuration, no hint. A test
        # pins that the request is byte-identical to today's, so A2.1's 56/60 stays valid.
        return AttemptPlan("initial", base_config, base_options)
    # A retry must change the request, or it is a loop: at temperature 0 an identical call returns an
    # identical answer. arch-initial.md §7 gives the order: narrow the task or name the ambiguity in
    # the prompt first (tier 2), a larger model second (tier 3). The hints come from what failed
    # (`retry_hint(history)`). The last attempt adds a sentence of its own, so it differs from
    # attempt 2 even when the same check failed twice and there is no larger model to swap in. The
    # route fallback is decided from the WHOLE history, so it is sticky: if attempt 2 failed for
    # another reason, attempt 3 must not go back to the JSON-LD route that already failed. Without a
    # configured escalation model, tier 3 still runs (with the full hint) and says it didn't escalate
    # the model (A3-D5).
    page_hint, splitter_hint = retry_hint(history, final=attempt >= 3)
    fell_back = any(route_falls_back(r) for r in history)
    config = replace(
        base_config, retry_hint=page_hint, splitter_hint=splitter_hint,
        route="model" if fell_back else base_config.route,
    )
    if attempt >= 3:
        model = policy.escalation_model
        options = replace(base_options, model=model) if model else base_options
        return AttemptPlan("larger_model", config, options, larger_model_used=bool(model))
    return AttemptPlan("narrowed", config, base_options)


__all__ = [
    "DEFAULT_POLICY", "AttemptPlan", "AttemptRecord", "RetryPolicy", "Route", "combine",
    "decide_route", "plan_for_attempt", "retry_hint", "route_falls_back",
]
