"""Throwaway evaluation script — see docs/dev/env-setup.md Phase 5.

Not part of the app. Nothing here needs to be production-quality; the
point is to look at raw output by hand and decide which model to use,
per the doc's three comparison axes (schema match, retry frequency,
confidence calibration). Delete or keep around for future model swaps —
either is fine.

Fetch is deliberately not part of this script. Fixtures are already-saved
static files (per the doc's fixture-collection step) standing in for a
real Fetch step — this script only exercises Extract, the one part of
the pipeline that's actually in question at this phase.
"""

import base64
from pathlib import Path

import instructor
from bs4 import BeautifulSoup
from instructor import Mode
from openai import OpenAI

from agent_worker.schemas import VenuePageExtraction

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# the model(s) to evaluate. qwen3-vl:4b was the original candidate but
# is out — confirmed (see below) that it never reliably completes
# structured extraction against this schema via instructor, regardless
# of Mode or max_tokens, despite answering correctly in plain chat.
# gemma4:e4b is the fallback the doc anticipated for exactly this case.
MODELS = ["gemma4:e4b"]

# point an OpenAI-SDK client at Ollama's local endpoint rather than
# OpenAI's own API. Ollama exposes an OpenAI-compatible API at
# http://localhost:11434/v1 — the api_key argument is required by the SDK's
# constructor but ignored by Ollama, so any placeholder string works.
#   client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

# wrap that client with instructor, so response_model= becomes available
# on chat completion calls and output gets validated against your
# Pydantic schema (retrying automatically on a validation failure).
#
# Mode.JSON, not Mode.TOOLS: confirmed directly against this model —
# qwen3-vl:4b puts its "thinking" output in a separate `reasoning` field
# distinct from `content` (visible in the raw Ollama response), and in
# Mode.TOOLS it was never reliably completing an actual tool call even
# with a very high max_tokens, raising IncompleteOutputException every
# time. Mode.JSON only needs the model to eventually emit valid JSON in
# `content`, which doesn't depend on tool-calling working correctly on
# top of a model that's already spending a lot of its output on
# reasoning — much more reliable in practice for this model/backend.
instructor_client = instructor.from_openai(client, mode=Mode.JSON)


def load_text_fixture(path: Path) -> str:
    # Read a saved HTML/text fixture and return its *visible text*, not
    # the raw file. Confirmed directly on the White Squirrel fixture: a
    # 93KB "Save As" HTML dump was 97% <script>/markup noise around just
    # 2.7KB of actual content — handing the model the raw file wastes
    # nearly all of a already-small context window on tags and inline JS
    # it doesn't need. This is also a preview of a real Phase 6
    # requirement: the actual Fetch/Extract pipeline shouldn't hand raw
    # HTML to the model either.
    html = path.read_text()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def load_image_fixture(path: Path) -> str:
    # read a saved image fixture (the flyer-image case) and return
    # it base64-encoded. Multimodal chat messages take an image as a
    # data URL: f"data:image/png;base64,{encoded}" (adjust the mime type
    # to match the actual file, e.g. image/jpeg) inside an
    # {"type": "image_url", "image_url": {"url": ...}} content block.
    binary_image = path.read_bytes()
    base64_bytes = base64.b64encode(binary_image)
    return base64_bytes.decode()



def extract(model: str, fixture_path: Path) -> VenuePageExtraction:
    # Step 1: determine whether the later steps will have to go down
    # text path or image path
    is_image = fixture_path.suffix in (".jpg", ".jpeg", ".png", ".webp")

    # Step 2: write the instruction text — a plain string telling the
    # model what it's looking at and what to do, e.g. "Extract every live
    # music show listed on this venue page. For each show, identify the
    # venue, date, time, performing act(s), whether the listing was
    # ambiguous, any ticket info, and your confidence." You don't need to
    # describe the output *shape* in this instruction — response_model
    # (step 4) already tells the model that separately.
    instruction = """
        If given a calendar page html, extract every show listed.
        If given an image, extract a show that the image is depicting based 
        on the text you can find on the image. 
        For each show, identify the venue, date, time, performing act(s), 
        whether the listing was ambiguous, any ticket info, and 
        your confidence.

"""

    # Step 3: build `messages`, the list the chat API expects — a list of
    # dicts, each with "role" and "content". You only need one message
    # here, role "user". The shape of "content" differs by fixture type:
    #   - text fixture: content can just be a single string — combine
    #     the step-2 instruction and the step-1 loaded text together,
    #     e.g. an f-string with both.
    #   - image fixture: content must be a LIST of content blocks
    #     instead of a plain string:
    #       [
    #           {"type": "text", "text": <step-2 instruction>},
    #           {"type": "image_url", "image_url": {"url": <the data URL from load_image_fixture, see its own comment for the exact f-string shape>}},
    #       ]

    if is_image: 
        content = [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{load_image_fixture(fixture_path)}"
                }
            },
        ]
    else: 
        content = instruction + load_text_fixture(fixture_path)

    messages = [
        {
            "role": "user",
            "content":  content
        }
    ]

    # Step 4: call the model and return its result — this is the one
    # piece that's the same regardless of fixture type:
    #   return instructor_client.chat.completions.create(
    #       model=model,
    #       response_model=VenuePageExtraction,
    #       messages=messages,
    #   )
    #
    # Don't add your own retry/error-handling logic around this call —
    # letting it fail loudly on a fixture is the point right now. How
    # often it needs instructor's built-in retries, and how often it
    # fails outright, is itself one of the three things you're comparing.
    return instructor_client.chat.completions.create(
        model=model,
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


def main() -> None:
    # Step 1: iterate FIXTURES_DIR (the module-level constant already
    # defined above — not a new hardcoded path). Skip anything that
    # isn't an actual fixture file: `.gitkeep`, and — this is the
    # non-obvious one — the "..._files" folders that came along with
    # each saved .html page (a browser's "Save As → Complete Webpage"
    # saves every asset the page loaded into a sibling folder, not just
    # the HTML). `item.is_file()` filters out those folders; a plain
    # name check filters out `.gitkeep`.
    for item in FIXTURES_DIR.iterdir():
        if not item.is_file() or item.name == ".gitkeep":
            continue

        # Step 2: nested loop over MODELS — for every fixture file, try
        # every model in the list. Right now that's just one model, but
        # the loop shape should still support more being added later.
        for model in MODELS:
            # Step 3: call extract(), capturing its return value — that's
            # your VenuePageExtraction object, not something printed
            # inside extract() itself.
            #
            # Wrap this specific call in a try/except, catching Exception
            # broadly, and print the error rather than re-raising. This
            # is different advice than inside extract() itself: there,
            # letting failures happen loudly was the point, mid-attempt.
            # Here, one fixture failing outright shouldn't stop the loop
            # from finishing the rest — and a caught, printed failure is
            # itself a result worth recording (it's the "fails outright"
            # half of the retry-frequency axis you're comparing).
            #
            # On success, print something identifying which fixture and
            # model produced this result, then the result itself (either
            # `result` directly, or `result.model_dump_json(indent=2)`
            # for more readable formatting).
            print(f"--- {item.name} / {model} ---")
            try:
                output = extract(model, item)
                print(output.model_dump_json(indent=2))
            except Exception as err:
                print(f"FAILED: {item.name} / {model} — {err}")
            print()




if __name__ == "__main__":
    main()
