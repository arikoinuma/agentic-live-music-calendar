"""The shape the extraction model is asked to fill in, per venue page.

What this is: `VenuePageExtraction` (a whole page: a readability flag and a list of shows)
and the models nested in it, `ShowExtraction` and `ActExtraction`. `instructor` turns these
into a JSON schema that is sent to the local model with every request, and validates the
model's answer against them — a failure makes it re-ask. So two things here are
*instructions to the model*, not documentation: the field types (which decide what is
required) and each `Field(description=…)` text.

Where the field list comes from: docs/arch/requirements-initial.md "Agent Extraction:
Fields". (docs/arch/arch-initial.md §7's shorter list is superseded by it; A2 closed the
gaps G7/G8 between the two — docs/dev/implementations/a2-extraction-schema.md.)

How to read it, and the conventions that hold throughout:

* Only `venue`, `date`, `acts`, `is_ambiguous` and `confidence` are required. Date is the
  one field the requirements make mandatory; a required `time` would leave a model facing
  a page that states no time no way to say so except by inventing one.
* In Pydantic v2, `X | None` **without `= None` is still required**. Every optional field
  below therefore has an explicit default.
* Every optional field's description ends with the phrase "otherwise null" — how the model
  is told to express "the page doesn't say". A test enforces the exact phrase.
* Time fields use `ModelTime`: the schema *asks* for 24-hour `HH:MM`, and a normalizer
  (`normalize.py`) converts the sloppy formats a model actually produces, so one "7pm"
  doesn't fail a whole page.
* A time with no AM/PM on the page is PM (Ari, October 10, 2026: live music is
  overwhelmingly afternoon and evening, and a morning listing says AM). Every time
  description says so, because the model does the 12-to-24-hour conversion itself and the
  normalizer can't tell a converted "10:30" from a copied one.
"""

import datetime
import functools
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, create_model

from agent_worker.normalize import false_to_none, normalize_time

# A clock time, as read from a page. `datetime.time | None` is what Pydantic validates
# (and what the model's JSON schema shows: a time string or null); the BeforeValidator
# runs first and turns "7pm" / "7:30 PM" / "19:30:00Z" / "N/A" into a proper value or
# None — or refuses an ambiguous one such as "7:30". The `| None` sits *inside* the
# Annotated so the validator sees the string "n/a" before the None branch decides; the
# other nesting rejects it. See normalize.py for the rules.
ModelTime = Annotated[datetime.time | None, BeforeValidator(normalize_time)]


class ActExtraction(BaseModel):
    """One performing act within a show, in the order the page lists them."""

    # name — the act as written. Reconciling it against an Artist row is later work
    # (requirements "Agent Artist Creation & Matching"); this is just what was read.
    name: str = Field(description="The act's name as it appears on the page")

    # start_time — this act's own set time. Many listings give only the show's time, so
    # null is the normal case.
    start_time: ModelTime = Field(
        default=None,
        description=(
            "This act's own set time as 24-hour HH:MM (if the page gives no AM/PM, "
            "assume PM), only if the page states a time for this specific act; "
            "otherwise null"
        ),
    )

    # sequence_number — only if the page STATES a performance order. When it doesn't,
    # A5 derives the order from list position (requirements: "make an assumption … based
    # on the order in which the artists are listed"). Code can compute that exactly; a
    # model asked to number the acts can only get it wrong (0-based, duplicates, gaps —
    # each a validation error and a full-page re-ask).
    sequence_number: int | None = Field(
        default=None,
        ge=1,
        description=(
            "This act's position in the performance order, starting at 1, only if the "
            "page explicitly states an order; otherwise null"
        ),
    )


class ShowExtraction(BaseModel):
    """One show, as extracted from a single venue page."""

    # venue — the venue name as the model read it off the page. Not a database foreign
    # key at this stage; matching it to a Venue row is the reconcile step's job.
    venue: str = Field(description="The venue name as it appears on the page")

    # date — the `date` type, not `str`: a malformed date becomes a validation error
    # `instructor` can retry on, and the retry rate is something the eval observes.
    # The one field the requirements mark required.
    date: datetime.date = Field(description="The date of the show")

    # time — (G8).
    # A show's start time is optional: the requirements make Date the only required field, and a
    # required `time` leaves the model no honest answer for a page that states none (it invents one:
    # the Terminal Bar page has no times at all). In Pydantic v2 `datetime.time | None` WITHOUT
    # `= None` is still *required*, so the fix is a default as well as the type. And the
    # `description` is not documentation: `instructor` sends it to the model, so it must say the
    # format (24-hour HH:MM), which time counts (when the music starts, not doors — "Doors 7 / Show
    # 8" is common and an undecided choice flips between runs, which reconcile reads as a time
    # change), and how to say "not stated" (the fixed phrase "otherwise null").
    # Cite: a2-extraction-schema.md (Design › Schema, plan-review findings 10 and 11),
    # requirements-initial.md "Agent Extraction: Fields".
    time: ModelTime = Field(
        default=None,
        description=(
            "The time the music starts, as 24-hour HH:MM (if the page gives no AM/PM, "
            "assume PM) — not when doors open; otherwise null"
        ),
    )

    # end_time — requirements: "End Time: leave blank if unclear". Optional, and the eval
    # measures whether offering it tempts the model to invent end times.
    end_time: ModelTime = Field(
        default=None,
        description=(
            "The time the show ends, as 24-hour HH:MM (if the page gives no AM/PM, "
            "assume PM), only if the page states an end time; otherwise null"
        ),
    )

    # acts — (G7).
    # Changing `list[str]` to `list[ActExtraction]` is a SHAPE change, not a type tweak: the JSON
    # schema `instructor` sends the model becomes nested (gaining a `$defs` section), the model's
    # output nests, and every reader of `.acts` must change from a string to an object. Nothing read
    # `.acts` when this changed (verified by grep), which is why it was cheap then and would not be
    # after A5 writes `show_artist` rows. The point of the nesting: each act can carry its own start
    # time and order.
    # Cite: a2-extraction-schema.md (Design › Schema, "Consequences"), build plan G7.
    acts: list[ActExtraction] = Field(
        description="The act(s) performing, in the order the page lists them"
    )

    # is_ambiguous — true when the page's own listing order or timing wasn't clear enough
    # to be confident about. Meaning unchanged by A2; note that because most multi-act
    # listings state no order, it may now fire often — the eval records how often.
    is_ambiguous: bool = Field(
        description="True if the page's listing order or timing was unclear or ambiguous"
    )

    # Admission, replacing the old untyped `ticket_info` string (G7). Rules from
    # requirements-initial.md: a single price shown is the Day price (advance stays null);
    # free admission is true only when the listing explicitly says free; it is fine for
    # all three to be empty. Floats, not Decimal, at this layer: nothing here needs exact
    # money, and Decimal would put a regex-string branch into the schema the model reads
    # (twice per show). A6 converts with Decimal(str(value)) at the database write.
    admission_advance: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Advance-purchase admission price in dollars, only if the page labels one "
            "as advance; otherwise null"
        ),
    )
    admission_day: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Day-of-show (door) admission price in dollars. If the page shows a single "
            "price with no label, put it here; otherwise null"
        ),
    )
    # null, NOT false, when the page doesn't say: "free" is a positive claim, and the data
    # model's CHECK treats absence as not-stated (absence of a price never implies free).
    # `false` is folded into None by `false_to_none` (A2.1, F1): the model wrote `false` for
    # "not stated" on 56 shows in A2's eval. The schema the model sees is unchanged.
    free_admission: Annotated[bool | None, BeforeValidator(false_to_none)] = Field(
        default=None,
        description="True only if the listing explicitly says the show is free; otherwise null",
    )

    # image_url — the show's poster, never an artist photo (requirements: "Do not populate
    # Artist image link"). Plain `str`, not a URL type: a URL type would turn a model typo
    # into a full-page retry. html_clean keeps only visible text, so on text pages this is
    # null in practice until cleaning preserves image links (build plan G25); the guard
    # against invention is the verbatim rule here plus the eval's substring check.
    image_url: str | None = Field(
        default=None,
        description=(
            "URL of the show's poster image, copied only if it appears verbatim in the "
            "page text — never an artist photo; otherwise null"
        ),
    )

    # confidence — the model's own self-reported confidence, used downstream by the
    # Validate step. `ge=0, le=1` makes an out-of-range value a validation error, and the
    # description is part of what the model is sent.
    confidence: float = Field(
        ge=0,
        le=1,
        description="Model's self-reported confidence in this extraction, from 0 to 1",
    )


class VenuePageExtraction(BaseModel):
    """The full result of extracting one fetched venue page.

    A venue's calendar page almost always lists many shows, not one — this is the shape
    you'll actually ask `instructor` for per page: a list of ShowExtraction records, not a
    single one.
    """

    # page_readable — a page-level signal, separate from each show's own confidence, that
    # exists specifically to disambiguate two situations that would otherwise both show up
    # as `shows: []`: a page that genuinely has nothing on it right now (a confirmed empty
    # result, safe to trust) versus a page that couldn't be meaningfully understood at all
    # (a broken fetch, an error page, garbled content — not safe to trust as "confirmed
    # empty"). Without this, validate_node would have no way to tell those two apart from
    # the extraction result alone.
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


# ---------------------------------------------------------------------------
# A2.1 schema variants — one per experiment switch
# ---------------------------------------------------------------------------
# A2.1 measures one change per eval label (docs/dev/implementations/a2.1-extraction-reliability.md,
# "Experiment protocol"). Two of its changes are to the schema the model is sent, so the
# schema has to be switchable: `page_model(status=…, split_acts=…)` builds the variant a
# configuration asks for, as a subclass of the classes above, with the same class names so
# the JSON schema the model reads differs only by the change itself. With both switches off
# it returns `VenuePageExtraction` unchanged (today's behaviour). When a rung is adopted, its
# switch is turned on in the pipeline's configuration (`extraction.PIPELINE_CONFIG`).

ShowStatus = Literal["scheduled", "cancelled", "postponed"]

# D12 (decided by Ari, October 10): a cancelled or postponed listing is still extracted, with
# its status, because reconcile must match it to a show stored before it was cancelled.
STATUS_DESCRIPTION = (
    "Whether the listing says the show is cancelled or postponed; otherwise scheduled"
)

# F9 (A2's act-splitting regression): the pre-A2 description said "The name(s) of the act(s)";
# A2's lost the plural and the model stopped splitting. This says it outright. Rung
# `a21-acts-desc`.
SPLIT_ACTS_DESCRIPTION = (
    "Each performing act as its own separate entry, in the order the page lists them: split "
    "a listing such as 'A w. B, C' or 'A / B' into separate acts; an '&' inside one act's "
    "name stays (for example 'Jenny Lake & Friends')"
)


@functools.cache
def show_model(*, status: bool, split_acts: bool) -> type[ShowExtraction]:
    """The show schema with the requested A2.1 changes applied (or `ShowExtraction` itself)."""
    if not (status or split_acts):
        return ShowExtraction
    fields: dict[str, Any] = {}
    if status:
        fields["status"] = (ShowStatus, Field(default="scheduled", description=STATUS_DESCRIPTION))
    if split_acts:
        fields["acts"] = (list[ActExtraction], Field(description=SPLIT_ACTS_DESCRIPTION))
    # `__doc__` passed on: create_model drops a class docstring otherwise, and the docstring is
    # the schema's description, which the model is sent (code review #2).
    return create_model("ShowExtraction", __base__=ShowExtraction, __doc__=ShowExtraction.__doc__, **fields)


@functools.cache
def page_model(*, status: bool, split_acts: bool) -> type[VenuePageExtraction]:
    """The page schema whose shows use `show_model(...)` (or `VenuePageExtraction` itself)."""
    shows = show_model(status=status, split_acts=split_acts)
    if shows is ShowExtraction:
        return VenuePageExtraction
    description = VenuePageExtraction.model_fields["shows"].description
    return create_model(
        "VenuePageExtraction",
        __base__=VenuePageExtraction,
        __doc__=VenuePageExtraction.__doc__,
        shows=(list[shows], Field(description=description)),  # type: ignore[valid-type]
    )


# ---------------------------------------------------------------------------
# The title-split route's schema (A2.1, S6, October 11, 2026)
# ---------------------------------------------------------------------------
# On the JSON-LD route the model is asked only to split one title at a time, and it got White
# Squirrel's acts right 23 of 23. The title-split route brings that to pages without JSON-LD: the
# full-page model returns each listing with its performer text copied verbatim (`title`) and NO act
# list, and the act splitter (act_split.py) turns every title into acts. Every other field means
# what it means on ShowExtraction, so their descriptions are reused, not restated. The verbatim
# title is also the listing's display text that D5's artist-display idea would store.

_SHOW = ShowExtraction.model_fields


class ListingExtraction(BaseModel):
    # The docstring is model-facing: instructor sends it as the schema's description (code
    # review round 1, #2; round 2, #9). Which route uses this class is said in the comment above.
    """One listing on a venue's calendar page: its date, time and prices, and its performer
    text copied exactly as the page writes it."""

    venue: str = Field(description=_SHOW["venue"].description)
    date: datetime.date = Field(description=_SHOW["date"].description)
    time: ModelTime = Field(default=None, description=_SHOW["time"].description)
    end_time: ModelTime = Field(default=None, description=_SHOW["end_time"].description)
    title: str = Field(
        description=(
            "The listing's performer text exactly as the page writes it, including every line "
            "of it under its date, with any 'w.', '/', '+', tour or series names — copied "
            "verbatim, not split, shortened or reworded"
        )
    )
    is_ambiguous: bool = Field(description=_SHOW["is_ambiguous"].description)
    admission_advance: float | None = Field(default=None, ge=0, description=_SHOW["admission_advance"].description)
    admission_day: float | None = Field(default=None, ge=0, description=_SHOW["admission_day"].description)
    free_admission: Annotated[bool | None, BeforeValidator(false_to_none)] = Field(
        default=None, description=_SHOW["free_admission"].description
    )
    image_url: str | None = Field(default=None, description=_SHOW["image_url"].description)
    confidence: float = Field(ge=0, le=1, description=_SHOW["confidence"].description)


class VenueListingsExtraction(BaseModel):
    # Model-facing docstring, like ListingExtraction's.
    """Every listing on a venue's calendar page."""

    page_readable: bool = Field(description=VenuePageExtraction.model_fields["page_readable"].description)
    listings: list[ListingExtraction] = Field(description="Every listing found on this venue's page")

