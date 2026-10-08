import base64
from pathlib import Path

import httpx
import instructor
from bs4 import BeautifulSoup
from instructor import Mode
from openai import OpenAI

from agent_worker.schemas import VenuePageExtraction
from agent_worker.state import VenueGraphState
from app.config import settings

# Same client setup proven in eval/run_eval.py, but living here for real
# this time — that script is explicitly throwaway (see its own
# docstring), so production pipeline code shouldn't import from it.
# Mode.JSON, num_ctx override, and max_tokens are all carried forward
# from what was confirmed working there; see docs/dev/env-setup.md
# Phase 5's final bullet for why each of those specific choices matters.
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
instructor_client = instructor.from_openai(client, mode=Mode.JSON)

def html_clean(html: str):
    cleaned_page = BeautifulSoup(html, "html.parser")
    for tag in cleaned_page(["script", "style"]):
        tag.decompose()
    return cleaned_page.get_text(separator=" ", strip=True)


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

    if (is_url):
        http_response = httpx.get(state.calendar_url)
        http_response.raise_for_status()
        state.page_content = html_clean(http_response.text)
    else:
        # Step 3 (the existing local-path branch): unchanged from before —
        # this is the code already here, doing Path-based reading with the
        # is_image suffix check. Keep it working exactly as it already does.
        path = Path(state.calendar_url)
        is_image = path.suffix in (".jpg", ".jpeg", ".png", ".webp")
        if is_image:
            binary_image = path.read_bytes()
            base64_bytes = base64.b64encode(binary_image)
            state.page_content = base64_bytes.decode()
        else:
            html = path.read_text()
            state.page_content = html_clean(html)

    # Step 4: whichever branch ran, the function still ends the same
    # way it already does — state.page_content gets set, and the
    # function returns state.
    return state

    

def extract_node(state: VenueGraphState) -> VenueGraphState:
    """Calls the model against state.page_content, populating
    state.extraction. This is the same call proven working in
    eval/run_eval.py's extract() — reuse that shape, don't redesign it.

    Not yet handled here, deliberately deferred: the MongoDB raw-staging
    write the architecture doc calls for ("Extract --> Staging[('MongoDB
    — raw staging doc')]") and this node's own audit trail write. Same
    reasoning as fetch_node — add once the graph's shape is proven.
    """
    # build the instruction text and messages list (text vs image
    # content block, exactly like eval/run_eval.py's extract() step 1-3),
    # then call instructor_client.chat.completions.create(...) with
    # response_model=VenuePageExtraction, max_tokens=16000, and
    # extra_body={"options": {"num_ctx": 32768}} — all three of those
    # specific values were load-bearing fixes discovered in Phase 5, not
    # arbitrary defaults; dropping any of them risks reintroducing the
    # IncompleteOutputException failures documented there.
    #
    # Increment state.attempt_count in the returned copy — this is what
    # the retry cap (3 attempts, per the architecture doc) checks against
    # once the graph is wired with conditional edges.

    # same check exists in fetch_node, this should be refactored in future
    is_image = Path(state.calendar_url).suffix in (".jpg", ".jpeg", ".png", ".webp")

    instruction = """
        If given a calendar page html, extract every show listed.
        If given an image, extract a show that the image is depicting based
        on the text you can find on the image.
        For each show, identify the venue, date, time, performing act(s),
        whether the listing was ambiguous, any ticket info, and
        your confidence.

        Also set page_readable: true if you could understand this page well
        enough to reliably tell whether it lists any shows, even if your
        answer is that it lists zero shows right now — a page that's
        genuinely empty is still readable. Set page_readable: false only if
        the content itself was broken, garbled, an error page, or otherwise
        not something you could meaningfully interpret as a venue's show
        listings — regardless of how many shows you end up returning.

    """

    if is_image: 
        content = [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{state.page_content}"
                }
            },
        ]
    else: 
        content = instruction + state.page_content

    messages = [
        {
            "role": "user",
            "content":  content
        }
    ]

    # TODO: we should catch any errors of the operation below
    state.extraction = instructor_client.chat.completions.create(
        model=settings.model_name,
        response_model=VenuePageExtraction,
        messages=messages,
        # Raise this further if IncompleteOutputException recurs on a
        # busier fixture (a page with many shows needs a genuinely large
        # structured response).
        max_tokens=16000,
        # Ollama silently defaults num_ctx to 4096 regardless of what
        # max_tokens requests — confirmed directly: even with a small,
        # already-cleaned fixture, output was still getting cut off,
        # because max_tokens can't exceed what's left in the context
        # window once the input and instructor's schema-following prompt
        # are already counted against it. Without this override, every
        # fixture would be silently truncated the same way White Squirrel
        # was, not just the largest ones.
        extra_body={"options": {"num_ctx": 32768}},
    )

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
