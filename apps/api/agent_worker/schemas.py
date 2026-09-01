import datetime

from pydantic import BaseModel, Field


class ShowExtraction(BaseModel):
    """One show, as extracted from a single venue page.

    Field list per docs/arch/arch-initial.md Section 7: "Extraction
    produces a structured record against a fixed schema (venue, date,
    time, act name(s), a flag for ambiguous ordering/timing, ticket info
    if present, confidence), using the model provider's structured-output
    mode rather than free-text parsing."
    """

    # venue — the venue name as the model read it off the page. Not a
    # database foreign key at this stage; reconciling this string against
    # an actual Venue row happens later, in the reconcile step — this
    # schema only describes what got extracted, not what it means.
    venue: str = Field(description="The venue name as it appears on the page")

    # date — uses the `date` type (from datetime), not `str`. Reason this
    # matters for the evaluation script's second axis ("does the model
    # follow the schema reliably, or does `instructor` need to retry it
    # often"): a typed field makes Pydantic actually validate the model's
    # output shape — a malformed date becomes a validation error
    # `instructor` can catch and retry on, whereas a plain `str` field
    # would silently accept anything, including garbage, and you'd never
    # observe how often the model struggles with this field.
    date: datetime.date = Field(description="The date of the show")

    # time — same reasoning as date, using the `time` type.
    time: datetime.time = Field(description="The start time of the show")

    # acts — a list, not a single str. "act name(s)" in the architecture
    # doc is plural because a show's lineup can have more than one act.
    acts: list[str] = Field(
        description="The name(s) of the act(s) performing, in listed order"
    )

    # is_ambiguous — true when the page's own listing order or timing
    # information wasn't clear enough to be confident about, e.g.
    # multiple acts listed with no indication of set order.
    is_ambiguous: bool = Field(
        description="True if the page's listing order or timing was unclear or ambiguous"
    )

    # ticket_info — genuinely optional, not just possibly an empty
    # string, since page formats vary widely ("$15 adv / $20 door",
    # "Free", "Sold Out", or nothing at all).
    ticket_info: str | None = Field(
        default=None, description="Ticket price or purchase info, if present on the page"
    )

    # confidence — the model's own self-reported confidence in this
    # extraction, used downstream by the Validate step to decide
    # pass/retry/escalate. `ge=0, le=1` makes Pydantic reject an
    # out-of-range value as a validation error instead of silently
    # accepting it, and the `description` text becomes part of what gets
    # sent to the model via `instructor`'s structured-output mode, i.e.
    # it's not just a comment for humans — it actually shapes what the
    # model produces.
    confidence: float = Field(
        ge=0,
        le=1,
        description="Model's self-reported confidence in this extraction, from 0 to 1",
    )


class VenuePageExtraction(BaseModel):
    """The full result of extracting one fetched venue page.

    A venue's calendar page almost always lists many shows, not one — this
    is the shape you'll actually ask `instructor` for per page: a list of
    ShowExtraction records, not a single one.
    """

    # page_readable — a page-level signal, separate from each show's own
    # confidence, that exists specifically to disambiguate two situations
    # that would otherwise both show up as `shows: []`: a page that
    # genuinely has nothing on it right now (a confirmed empty result,
    # safe to trust) versus a page that couldn't be meaningfully
    # understood at all (a broken fetch, an error page, garbled
    # content — not safe to trust as "confirmed empty"). Without this,
    # validate_node would have no way to tell those two apart from the
    # extraction result alone.
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
