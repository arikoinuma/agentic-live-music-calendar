import base64
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from agent_worker.extraction import (
    PIPELINE_CONFIG,
    PIPELINE_OPTIONS,
    clean_text,
    extract_image,
    extract_page,
)
from agent_worker.llm import instructor_client
from agent_worker.state import VenueGraphState

# The model client, the request options (Mode.JSON, max_tokens, num_ctx, max_retries) and
# the page cleaning used to live here. A2.1 moved them to `llm.py` and `extraction.py`,
# which the eval harness calls too, so the eval measures exactly what this pipeline sends
# (docs/dev/implementations/a2.1-extraction-reliability.md, Design §1). `instructor_client`
# is imported by name so a test can swap it for a fake.

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def metro_today(metro_timezone: str) -> datetime.date:
    """Today's date on the metro's clock, not the machine's: a worker running in UTC late on a
    Chicago evening is already on tomorrow's date, which would shift the year rule's window
    (A2.1 plan, D13)."""
    return datetime.datetime.now(ZoneInfo(metro_timezone)).date()


def fetch_html(url: str) -> str:
    """Fetch a page the way the pipeline does: one plain GET, an error status raised.

    Shared with eval/capture.py, so a captured fixture is exactly what production fetches —
    A2's fixtures were browser "Save As" captures, which run JavaScript and so showed the
    model pages the pipeline never sees (A2.1 plan, Context).
    """
    http_response = httpx.get(url)
    http_response.raise_for_status()
    return http_response.text


def fetch_node(state: VenueGraphState) -> VenueGraphState:
    """Reads a venue's page — now for real, via httpx, when calendar_url
    is an actual URL. Still falls back to the local-fixture-reading
    behavior below when it isn't, since local_test.py's manual testing
    depends on that path continuing to work.

    Deliberately out of scope for this pass, not silently dropped: a
    live fetch here only handles the plain-text/HTML case. A page like
    terminalbarmn.com, where the actual show info is inside images
    embedded in the HTML (not in the URL itself, the way the local image
    fixtures were), needs its own detection-and-download logic that
    doesn't exist yet — this step doesn't add it. Also out of scope:
    Playwright, for whatever venue turns out to need JS-rendered
    pagination — httpx only for now.

    Not yet handled here, deliberately deferred past "prove the shape
    works": the R2 snapshot write the architecture doc calls for
    ("Fetch -.writes.-> Audit", "each page traversed gets its own R2
    snapshot"). Add that once the graph runs cleanly, not before.
    """

    # Step 1: decide which branch this call needs — a real URL, or a
    # local fixture path (what every test so far has used). A simple,
    # good-enough check: does state.calendar_url start with "http://" or
    # "https://"? Store the result in a variable; you'll need it below
    # to pick which branch runs, and it reads more clearly at the
    # if/else than repeating the same startswith() check twice.

    is_url = state.calendar_url.startswith("http")

    # Step 2 (the new, real-URL branch): fetch it with httpx.
    #   response = httpx.get(state.calendar_url)
    #   response.raise_for_status()
    # That second line matters, not just boilerplate: without it, a 404
    # or 500 response doesn't raise — httpx just hands you back whatever
    # error-page HTML the server sent, and it would silently flow into
    # extract_node as if it were real page content. Given the whole
    # page_readable discussion from earlier — the point was distinguishing
    # a genuinely empty result from a broken one — raise_for_status()
    # is what stops a broken *fetch* from masquerading as content in the
    # first place, one layer before that.
    #
    # Once you have response.text (the fetched HTML), it needs the exact
    # same BeautifulSoup cleanup already happening in the local-path
    # branch below — strip script/style, then get_text(). Don't
    # duplicate that logic by retyping it; reuse it (however you think
    # is cleanest — a small helper function is a reasonable option).

    # A2.1: the raw HTML is kept in `page_html` (the JSON-LD route needs the <script>
    # blocks that cleaning strips), and the date is recorded for the year rule (D13).
    # A caller that knows when the page was captured (local_test's August fixture) passes it;
    # otherwise it is today on the metro's clock (code review #7).
    state.fetched_on = state.fetched_on or metro_today(state.metro_timezone)
    if (is_url):
        state.page_html = fetch_html(state.calendar_url)
        state.page_content = clean_text(state.page_html, PIPELINE_CONFIG.keep_line_breaks)
    else:
        # Step 3 (the existing local-path branch): unchanged from before —
        # this is the code already here, doing Path-based reading with the
        # is_image suffix check. Keep it working exactly as it already does.
        path = Path(state.calendar_url)
        is_image = path.suffix in IMAGE_SUFFIXES
        if is_image:
            binary_image = path.read_bytes()
            base64_bytes = base64.b64encode(binary_image)
            state.page_content = base64_bytes.decode()
        else:
            state.page_html = path.read_text()
            state.page_content = clean_text(state.page_html, PIPELINE_CONFIG.keep_line_breaks)

    # Step 4: whichever branch ran, the function still ends the same
    # way it already does — state.page_content gets set, and the
    # function returns state.
    return state

    

def extract_node(state: VenueGraphState) -> VenueGraphState:
    """Extracts the shows on the fetched page into state.extraction, via
    extraction.extract_page (or extract_image for a poster) — the same
    functions the eval harness calls, so what is measured is what runs.

    Not yet handled here, deliberately deferred: the MongoDB raw-staging
    write the architecture doc calls for ("Extract --> Staging[('MongoDB
    — raw staging doc')]") and this node's own audit trail write. Same
    reasoning as fetch_node — add once the graph's shape is proven.
    """
    # Increment state.attempt_count in the returned copy — this is what
    # the retry cap (3 attempts, per the architecture doc) checks against
    # once the graph is wired with conditional edges.

    # same check exists in fetch_node, this should be refactored in future
    is_image = Path(state.calendar_url).suffix in IMAGE_SUFFIXES
    fetched_on = state.fetched_on or metro_today(state.metro_timezone)

    # A2.1: the request is built in extraction.py, from the pipeline's configuration, so the
    # eval harness (which calls the same functions) measures exactly this. extract_page also
    # chooses the route — the venue's JSON-LD when it has usable events, the full-page model
    # extraction otherwise (A2.1 plan, D4). Same three load-bearing request values as before
    # (max_tokens, num_ctx, max_retries), now in llm.RequestOptions.
    # TODO: we should catch any errors of the operation below (A3, G2)
    if is_image:
        result = extract_image(
            state.page_content or "", mime="image/png", fetch_date=fetched_on,
            client=instructor_client, options=PIPELINE_OPTIONS, config=PIPELINE_CONFIG,
        )
    else:
        result = extract_page(
            state.page_html or "", venue_name=state.venue_name,
            metro_timezone=state.metro_timezone, fetch_date=fetched_on,
            client=instructor_client, options=PIPELINE_OPTIONS, config=PIPELINE_CONFIG,
        )
    state.extraction = result.extraction

    # increment the attempt count whether it succeeds or not
    state.attempt_count = state.attempt_count+1
    return state





def validate_node(state: VenueGraphState) -> VenueGraphState:
    """Computes state.confidence from state.extraction, and is where the
    open design question flagged in state.py's own comment actually gets
    decided: is this an aggregate (min? average?) across
    state.extraction.shows, or something else. Decide it here, now that
    there's a real extraction to test it against.

    Not yet handled here, deliberately deferred: the completeness/
    plausibility/internal-consistency checks the architecture doc
    describes beyond just a confidence number, and this node's audit
    trail write.
    """
    # compute state.confidence from state.extraction.shows, and
    # return the updated state. The routing decision itself (pass to
    # reconcile_node vs. retry extract_node vs. escalate once retries
    # are exhausted) doesn't belong in this function — that's
    # add_conditional_edges reading this node's output, in the next
    # checklist step, not this node deciding its own routing.

    # initial decision: "compute" here means find the lowest
    # score among the shows found

    # Deferred decision: We may need to do more work to differentiate
    # "valid pages with empty results" vs "page error that needs retry"
    
    lowest = 1 # start with the highest possible score and go lower

    if not state.extraction.shows: # list of shows is empty
        lowest = 0
    else:
        for show in state.extraction.shows:
            lowest = min(lowest, show.confidence)

    state.confidence = lowest
                
    return state


def reconcile_node(state: VenueGraphState) -> VenueGraphState:
    """Decides the CRUD outcome (no-op / delete / insert / update /
    ambiguous-match, per the architecture doc's table) and sets
    state.reconcile_decision. Does NOT write to Postgres — that's
    commit_node's job, kept separate deliberately (see the "Reconcile"
    section of docs/arch/arch-initial.md Section 7 for why).

    The ambiguous-artist-match case is a conditional branch inside this
    function, not its own graph node — it still ends with
    reconcile_node setting state.reconcile_decision, just with an LLM
    call involved in reaching that decision for that one case.

    PLACEHOLDER: the real version needs to match state.extraction's
    shows against existing Postgres records (composite key: venue,
    date, time, for shows; fuzzy name match for artists) — deferred
    because there's no `show` table or ORM models to query yet (see
    docs/arch/data-model-initial.md). This stub exists so the graph has
    all six nodes and can run end to end; it always decides "insert",
    which is only correct the very first time a show is ever seen.
    """
    print(f"[reconcile_node] PLACEHOLDER — would reconcile venue_id={state.venue_id}")
    state.reconcile_decision = "insert"
    return state


def commit_node(state: VenueGraphState) -> VenueGraphState:
    """Writes reconcile_node's decision to Postgres. Kept separate from
    reconcile_node because "decide what should happen" and "make it
    happen" are different failure modes worth attributing separately in
    the audit trail — a bad reconcile decision is a logic bug, a failed
    commit is a database/connectivity problem.

    PLACEHOLDER: the real version needs SQLAlchemy (async, matching
    app/main.py's engine pattern) writing to the `show` table — deferred
    for the same reason as reconcile_node, that table doesn't exist yet.
    This stub just logs what it would have written, so the graph's
    shape is provable end to end without the DB work being done first.
    """
    print(
        f"[commit_node] PLACEHOLDER — would commit decision="
        f"{state.reconcile_decision!r} for venue_id={state.venue_id}"
    )
    return state


def escalate_node(state: VenueGraphState) -> VenueGraphState:
    """Reached when validate_node's retry cap is exhausted (3 attempts,
    per the architecture doc) — flags the run for human review rather
    than looping indefinitely.

    PLACEHOLDER: the real version needs to write an audit trail entry
    marking this run for human review — deferred along with the other
    two Postgres-writing nodes above, same reason. No retry, no further
    LLM calls here either way — this node's entire job is recording that
    the pipeline gave up, not trying again itself.
    """
    print(
        f"[escalate_node] PLACEHOLDER — venue_id={state.venue_id} exhausted "
        f"retries (attempt_count={state.attempt_count}), flagged for human review"
    )
    return state
