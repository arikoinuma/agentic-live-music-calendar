"""The pre-A2 extraction schema and prompt, frozen, so the `baseline` label can be re-run.

Why this exists: A2 changes the live schema (`agent_worker/schemas.py`) and prompt
(`agent_worker/prompts.py`), and its measurement compares against what came *before*. Once
the live files move on, that "before" is reachable only through git history — and a result
you can't regenerate isn't a baseline. Decision #6 in docs/dev/implementations/a2-extraction-schema.md
(re-run the baseline under a fixed Ollama context window) needs exactly that. Run it with
`--legacy`. Delete this file when A2's measurement is no longer needed.

How to read it: a verbatim copy of the schema as of commit 283564e (field descriptions are
what the model was sent, so they are kept exactly; the explanatory comments were dropped), and
the instruction text exactly as `prompts.extraction_instruction()` returned it at step 0. The
classes keep the names `ShowExtraction` / `VenuePageExtraction` because the names appear in
the JSON schema sent to the model.
"""

import datetime

from pydantic import BaseModel, Field


class ShowExtraction(BaseModel):
    venue: str = Field(description="The venue name as it appears on the page")
    date: datetime.date = Field(description="The date of the show")
    time: datetime.time = Field(description="The start time of the show")
    acts: list[str] = Field(
        description="The name(s) of the act(s) performing, in listed order"
    )
    is_ambiguous: bool = Field(
        description="True if the page's listing order or timing was unclear or ambiguous"
    )
    ticket_info: str | None = Field(
        default=None, description="Ticket price or purchase info, if present on the page"
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Model's self-reported confidence in this extraction, from 0 to 1",
    )


class VenuePageExtraction(BaseModel):
    page_readable: bool = Field(
        description=(
            "True if this page's content was understandable enough to "
            "reliably determine whether it lists any shows — even if that "
            "determination is 'zero shows currently listed'. False if the "
            "content looks broken, empty, an error page, or otherwise not "
            "something you could meaningfully read as a venue's show "
            "listings."
        )
    )

    shows: list[ShowExtraction] = Field(description="Every show found on this venue's page")


# The instruction exactly as the `baseline` label sent it (step 0 of A2): the pre-A2 base
# paragraph, a blank line, the page_readable paragraph, a trailing newline.
LEGACY_INSTRUCTION = """\
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
