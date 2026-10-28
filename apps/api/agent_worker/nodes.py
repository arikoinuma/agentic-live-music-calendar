"""The six nodes of the per-venue graph: fetch, extract, validate, reconcile, commit, escalate.

Each is a plain function of `VenueGraphState` (state.py); graph.py wires them. A3 made the first three
real: fetch records a failure instead of raising, extract records a failed model call as an attempt
instead of crashing the graph (v0.1-G2), and validate reads the evidence from validation.py and the
policy from policy.py to produce a verdict. A5 made reconcile real (its rules are in reconcile.py and
artist_match.py; this file's node only wires them to the state). A6 made commit real: its rules are in commit.py, the
writes in calendar_writer.py; this file's node only turns the plan into operations.

A4 writes the audit trail around these functions, not inside them: `graph.py` registers each through
`trace.audited`, which runs the node and then appends its `audit_log` row (what each step records is
`audit.entry_for`). So a node here only has to leave the evidence in the state (`extraction_source`,
`extraction_notes`, `validation`, `attempt_history`, `escalation_reason`, `extraction_sent_text`).
"""

import base64
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from agent_worker.commit import build_ops
from agent_worker.extraction import (
    PIPELINE_CONFIG,
    PIPELINE_OPTIONS,
    PageExtractionResult,
    clean_text,
    extract_image,
    extract_page,
    usable_events,
)
from agent_worker.llm import EXTRACTION_ERRORS, instructor_client
from agent_worker.policy import (
    AttemptPlan,
    AttemptRecord,
    Route,
    combine,
    plan_for_attempt,
)
from agent_worker.reconcile import build_plan, prepare_inputs
from agent_worker.schemas import ShowExtraction
from agent_worker.state import VenueGraphState
from agent_worker.validation import ValidationResult, Verdict, validate_extraction

# The model client, the request options (Mode.JSON, max_tokens, num_ctx, max_retries) and
# the page cleaning used to live here. A2.1 moved them to `llm.py` and `extraction.py`,
# which the eval harness calls too, so the eval measures exactly what this pipeline sends
# (docs/dev/implementations/a2.1-extraction-reliability.md, Design §1). `instructor_client`
# is imported by name so a test can swap it for a fake.

log = structlog.get_logger()

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

# `EXTRACTION_ERRORS` (what a failed model call is allowed to be) lives in llm.py since A5, because
# artist_match.py needs it too and sits below state.py in the import order (a5-reconcile.md, Design).

# What a failed fetch is allowed to be: any HTTP error (transport failure or an error status), a
# file that can't be read, or a page with nothing on it.
FETCH_ERRORS = (httpx.HTTPError, OSError, UnicodeDecodeError)


class EmptyResponse(Exception):
    """A page that came back with no visible text and no usable structured events.

    arch-initial.md §7 counts an empty response as a fetch failure, not an extraction: a model handed
    a blank page can answer `page_readable: true, shows: []`, which would pass as a confirmed-empty
    calendar and (once A5 exists) soft-delete a venue's whole schedule.
    """


def metro_today(metro_timezone: str) -> datetime.date:
    """Today's date on the metro's clock, not the machine's: a worker running in UTC late on a
    Chicago evening is already on tomorrow's date, which would shift the year rule's window
    (A2.1-D13)."""
    return datetime.datetime.now(ZoneInfo(metro_timezone)).date()


def _is_transient(error: BaseException) -> bool:
    """Worth another try: the network failed, the server errored (5xx), or the body was empty (which
    can be a transient blank). A 4xx is the venue's answer, not a glitch, so it is not retried."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    return isinstance(error, httpx.TransportError | EmptyResponse)


def _nothing_to_read(html: str) -> bool:
    """True when a text page has no visible text and no usable JSON-LD events. A script shell whose
    events live in JSON-LD is *not* empty: the JSON-LD route can serve it."""
    return not clean_text(html, False).strip() and not usable_events(html)


@retry(
    retry=retry_if_exception(_is_transient), stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True,
)
def fetch_html(url: str, *, reject_empty: bool = False) -> str:
    """Fetch a page the way the pipeline does: one plain GET, an error status raised, and (A3) the
    transient failures retried with backoff — three attempts, as arch-initial.md §7 says a fetch
    failure should be (retry Fetch directly, with backoff).

    Shared with eval/capture.py, so a captured fixture is exactly what production fetches —
    A2's fixtures were browser "Save As" captures, which run JavaScript and so showed the
    model pages the pipeline never sees (A2.1 plan, Context). `reject_empty` makes a body with
    nothing to read an `EmptyResponse` (the pipeline's fetch node asks for it; the capture
    script doesn't, since saving what a venue serves is its job).
    """
    http_response = httpx.get(url)
    http_response.raise_for_status()
    if reject_empty and _nothing_to_read(http_response.text):
        raise EmptyResponse(f"{url} returned a page with nothing to read")
    return http_response.text


def fetch_node(state: VenueGraphState) -> VenueGraphState:
    """Reads a venue's page: over HTTP when calendar_url is an actual URL, from a local file
    otherwise (local_test.py and the tests depend on that path).

    A3-D6: a failure to read the page — a network error that survived the retries, an error
    status, an unreadable file, an empty page — is recorded in `state.fetch_error` and routed to
    escalate by `route_after_fetch`, instead of raising out of the graph. An empty text page is
    treated the same way (see `EmptyResponse`).

    Deliberately out of scope, not silently dropped: only the plain-text/HTML case is handled. A
    page like terminalbarmn.com, where the actual show info is inside images embedded in the HTML,
    needs its own detection-and-download logic (arch-initial.md §11), and Playwright waits for a
    venue that needs click-driven pagination. The R2 snapshot write the architecture doc calls
    for ("each page traversed gets its own R2 snapshot") is deferred (alpha-deployment-plan.md C9, formerly H3);
    `audit_log.snapshot_key` stays NULL until then.
    """
    state.fetch_error = None
    # The raw HTML is kept in `page_html` (the JSON-LD route needs the <script> blocks that cleaning
    # strips), and the date is recorded for the year rule (A2.1-D13). A caller that knows when the
    # page was captured (local_test's August fixture) passes it; otherwise it is today on the metro's clock.
    state.fetched_on = state.fetched_on or metro_today(state.metro_timezone)
    try:
        if state.calendar_url.startswith("http"):
            state.page_html = fetch_html(state.calendar_url, reject_empty=True)
            state.page_content = clean_text(state.page_html, PIPELINE_CONFIG.keep_line_breaks)
        else:
            path = Path(state.calendar_url)
            if path.suffix in IMAGE_SUFFIXES:
                state.page_content = base64.b64encode(path.read_bytes()).decode()
            else:
                state.page_html = path.read_text()
                if _nothing_to_read(state.page_html):
                    raise EmptyResponse(f"{path.name} has nothing to read")
                state.page_content = clean_text(state.page_html, PIPELINE_CONFIG.keep_line_breaks)
    except (*FETCH_ERRORS, EmptyResponse) as err:
        state.fetch_error = f"{type(err).__name__}: {err}"
    return state


def _run_extraction(state: VenueGraphState, plan: AttemptPlan) -> PageExtractionResult:
    """The model call for one attempt: the poster image path or the page path, each configured by the
    attempt's plan. The same functions the eval harness calls, so what is measured is what runs."""
    fetched_on = state.fetched_on or metro_today(state.metro_timezone)
    if Path(state.calendar_url).suffix in IMAGE_SUFFIXES:
        return extract_image(
            state.page_content or "", mime="image/png", fetch_date=fetched_on,
            client=instructor_client, options=plan.options, config=plan.config,
        )
    return extract_page(
        state.page_html or "", venue_name=state.venue_name,
        metro_timezone=state.metro_timezone, fetch_date=fetched_on,
        client=instructor_client, options=plan.options, config=plan.config,
    )


def _route_for(state: VenueGraphState, plan: AttemptPlan) -> Route:
    """Which route this attempt will use, decided before the call so a failed attempt still has it:
    the poster path, JSON-LD (the config allows it and the page has usable events), or the model."""
    if Path(state.calendar_url).suffix in IMAGE_SUFFIXES:
        return "image"
    if plan.config.route == "auto" and usable_events(state.page_html or ""):
        return "jsonld"
    return "model"


def extract_node(state: VenueGraphState) -> VenueGraphState:
    """One extraction attempt: plan it (policy.plan_for_attempt: each retry changes the request),
    run it via extraction.extract_page / extract_image, and keep the result in state.extraction.

    Every per-attempt field is assigned on every attempt, to None where nothing was produced:
    LangGraph keeps a field's old value when a node leaves it alone, so without the reset an
    attempt-2 success would still carry attempt 1's error.

    The MongoDB raw-staging write the architecture doc calls for ("Extract --> Staging[('MongoDB —
    raw staging doc')]") and this node's audit row are written by `trace.audited` after this function
    returns (A4-D1), from what it leaves in the state; nothing here touches a store.
    """
    plan = plan_for_attempt(
        state.attempt_count + 1, state.policy, state.attempt_history, PIPELINE_CONFIG, PIPELINE_OPTIONS,
    )
    state.last_plan = plan
    state.route_attempted = _route_for(state, plan)
    state.extraction = None
    state.extraction_source = None
    state.extraction_notes = {}
    state.extraction_sent_text = None
    state.extract_error = None

    # A failed model call is an OUTCOME, not a crash. The retry loop exists for exactly this failure
    # (a thinking model exhausting its budget on a judgment call, env-setup.md Phase 5). Two things
    # make it work. The attempt is COUNTED before the call, so an exception can't skip the increment
    # and kill the graph (alpha-build-plan.md v0.1-G2; arch-initial.md §7). And only a NAMED tuple of
    # expected errors (`EXTRACTION_ERRORS`, above) is caught, never `Exception`. A failed attempt
    # leaves `extraction` None, and validate_node fails it with reason `extract_failed`, so the
    # existing `retry` edge handles it with no new edge.
    state.attempt_count += 1
    try:
        result = _run_extraction(state, plan)
        state.extraction = result.extraction
        state.extraction_source = result.source
        state.extraction_notes = result.notes
        state.extraction_sent_text = result.sent_text
    except EXTRACTION_ERRORS as err:
        state.extract_error = f"{type(err).__name__}: {err}"
    return state


def validate_node(state: VenueGraphState) -> VenueGraphState:
    """Checks the extraction, decides a verdict, and records the attempt.

    The checks (validation.validate_extraction) gather evidence and decide nothing; `policy.combine`
    turns the evidence and the model's confidence into a verdict; the routing decision itself (pass
    to reconcile, retry extract, or escalate) is `route_after_validate` reading that verdict in
    graph.py, not this node deciding its own routing.

    A failed model call arrives here as `extraction is None` and fails with reason `extract_failed`.
    `state.extraction` stays the model's raw answer (the audit record); `validated_extraction` holds
    the shows to commit, repairs applied and excluded shows removed.

    This node's audit row is written by `trace.audited` after it returns (A4).
    """
    if state.extraction is None:
        result = ValidationResult.for_failed_extraction()
        kept: list[ShowExtraction] = []
    else:
        assert state.extraction_source is not None  # set together with the extraction
        page_html = state.page_html or ""
        result, kept = validate_extraction(
            state.extraction, source=state.extraction_source, notes=state.extraction_notes,
            fetched_on=state.fetched_on or metro_today(state.metro_timezone),
            page_html=page_html, page_text=clean_text(page_html, False) if page_html else "",
        )
    result = combine(result, state.policy)
    assert result.verdict is not None  # combine always sets one
    state.validation = result
    state.confidence = result.confidence
    state.validated_extraction = (
        state.extraction.model_copy(update={"shows": kept}) if state.extraction is not None else None
    )
    plan = state.last_plan
    state.attempt_history = [*state.attempt_history, AttemptRecord(
        attempt=state.attempt_count,
        tier=plan.tier if plan else "initial",
        model=plan.options.model if plan else "",
        route=state.route_attempted,
        error=state.extract_error,
        verdict=result.verdict,
        reasons=result.reasons,
        findings=result.errors,
        confidence=result.confidence,
        error_count=len(result.errors),
        warning_count=len(result.warnings),
        larger_model_used=plan.larger_model_used if plan else False,
    )]
    return state


def reconcile_node(state: VenueGraphState) -> VenueGraphState:
    """Decides what should happen to the calendar and sets `state.reconcile_plan`. Writes nothing: `commit_node`
    executes the plan, and the two are kept apart so a bad decision and a failed write are different failures in
    the audit trail (arch-initial.md §7).

    The stored calendar arrives in `state.stored_shows` / `state.known_artists`, put there by `trace.audited`
    before this runs (it awaits the database; this body stays a plain function, A4-D1). The ambiguous-artist
    question is a branch inside `reconcile.build_plan`, not a node: it is still reconcile deciding, with a model
    involved for that one case. The rules are in reconcile.py and artist_match.py.
    """
    inputs = prepare_inputs(
        state.extraction, state.validated_extraction, state.validation,
        state.fetched_on or metro_today(state.metro_timezone),
    )
    state.reconcile_plan = build_plan(
        inputs, state.stored_shows, state.known_artists,
        original_url=state.calendar_url, client=instructor_client, options=PIPELINE_OPTIONS,
    )
    log.info(
        "reconcile decided", venue_id=state.venue_id, counts=state.reconcile_plan.counts(),
        withheld=len(state.reconcile_plan.withheld),
    )
    return state


def commit_node(state: VenueGraphState) -> VenueGraphState:
    """Turns reconcile_node's plan into the writes to make: `state.commit_ops`. Kept separate from reconcile_node
    because "decide what should happen" and "make it happen" are different failure modes worth attributing separately
    in the audit trail — a bad reconcile decision is a logic bug, a failed commit is a database/connectivity problem.

    This body is a plain function and touches no database (A4-D1): the writes are awaited by `trace.audited` right
    after it returns, through the `CalendarWriter` on the worker context, one transaction per show with its audit row
    inside it. What counts as a write, and what its columns are, is `commit.build_ops` (A6-D1).
    """
    plan = state.reconcile_plan
    state.commit_ops = build_ops(plan, state.venue_id, state.calendar_url) if plan else ()
    log.info(
        "commit prepared", venue_id=state.venue_id, writes=len(state.commit_ops),
        counts=plan.counts() if plan else None,
    )
    return state


def escalation_reason(state: VenueGraphState) -> str:
    """A plain-English account of why the pipeline gave up on this venue, for the person who will
    look at it (and for A6 to write as the escalation's audit row)."""
    if state.fetch_error:
        return f"the page could not be fetched: {state.fetch_error}"
    parts = [f"validation failed after {state.attempt_count} attempt(s)"]
    last = state.attempt_history[-1] if state.attempt_history else None
    if last is not None:
        if last.reasons:
            parts.append("reasons: " + ", ".join(r.value for r in last.reasons))
        if last.error:
            parts.append(f"the last model call failed with {last.error}")
        if last.findings:
            parts.append("errors: " + "; ".join(f.message for f in last.findings[:5]))
    failed_routes = sorted({r.route for r in state.attempt_history if r.verdict is Verdict.FAILED and r.route})
    if len(failed_routes) > 1:
        parts.append("it failed on the " + " and ".join(failed_routes) + " routes both")
    return "; ".join(parts)


def escalate_node(state: VenueGraphState) -> VenueGraphState:
    """Reached when a fetch fails or validate_node's retry cap is exhausted (3 attempts, per the
    architecture doc) — flags the run for human review rather than looping indefinitely.

    A3 composes `state.escalation_reason`; A4's `trace.audited` writes the audit row marking the run for
    human review (`outcome='escalated'`) from it. No retry, no further LLM calls here either way — this node's
    entire job is recording that the pipeline gave up, not trying again itself.
    """
    state.escalation_reason = escalation_reason(state)
    log.warning("venue flagged for human review", venue_id=state.venue_id, reason=state.escalation_reason)
    return state
