"""Read-API response models — the contract between FastAPI and Next.js.

These are the source of truth for the shapes the frontend consumes. No
route returns them yet (the endpoints land in milestone A2/B2 of
docs/dev/v1-build-plan.md); they exist first, on purpose, so the two
tracks have something fixed to build against. The JSON fixtures under
apps/calendar/lib/fixtures/ are generated to match these exactly, which
is what lets the calendar UI be built before the backend serves real
rows. See docs/dev/api-contract.md for the reasoning behind the shapes.

Three deliberate conventions, explained once here rather than repeated
at every model:

1.  **Summary vs. Detail.** A `*Summary` is what a link or a list row
    needs — enough to render and navigate, nothing more. A `*Detail` is
    a whole entity page. The calendar renders hundreds of shows at once,
    so ShowSummary embedding full VenueDetail for each one would be
    mostly duplicated payload nobody reads.

2.  **Envelopes, not bare arrays.** List endpoints return
    `{"shows": [...]}` rather than `[...]`. A bare top-level array has
    nowhere to put pagination, a total count, or the echoed query range
    without a breaking change. Nothing needs those yet; the envelope is
    what keeps adding them cheap.

3.  **These are read shapes only.** Write/edit shapes are a separate
    concern and deliberately not modeled yet — see the note on
    inherited fields in ShowDetail for the one place where read and
    write genuinely need different shapes.
"""

import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.enums import (
    AgeRestriction,
    ArtistFormat,
    ArtistRepertoire,
    Seating,
    Setting,
    VenueType,
)

# ---------------------------------------------------------------------
# Summaries — the shapes that appear inside other shapes
# ---------------------------------------------------------------------


class MetroSummary(BaseModel):
    id: int
    name: str
    # IANA timezone name, e.g. "America/Chicago". The frontend needs this
    # to render dates in the metro's local time rather than the
    # browser's — a venue's Friday show is Friday in Minneapolis
    # regardless of where the person reading the page happens to be.
    timezone: str


class VenueSummary(BaseModel):
    id: int
    name: str


class ArtistSummary(BaseModel):
    id: int
    name: str


class EventSummary(BaseModel):
    id: int
    name: str


# ---------------------------------------------------------------------
# Shows
# ---------------------------------------------------------------------


class LineupEntry(BaseModel):
    """One artist's slot in one show — the `show_artist` join row.

    This is a model rather than a bare ArtistSummary because the join
    carries its own data: per the requirements, each artist can have
    their own start time and a performance order distinct from the
    show's overall start time.
    """

    artist: ArtistSummary

    # This artist's own set time, distinct from the show's start_time.
    # Null is common and correct — most venue calendars list a single
    # door/show time for the whole bill and nothing per act.
    start_time: datetime.time | None = None

    # Performance order within the show, 1-based. Null when the source
    # listing gave no order at all; where the listing implies one by the
    # order acts are printed in, the agent assumes that order and fills
    # this in (requirements-initial.md, Agent Extraction: Fields).
    sequence_number: int | None = None


class ShowSummary(BaseModel):
    """One show as a calendar block.

    Per requirements-initial.md the block's focus is the venue and the
    artist names, so those are embedded rather than referenced by id —
    the calendar would otherwise need a second round trip, or a
    client-side join, to render anything readable.
    """

    id: int
    date: datetime.date
    start_time: datetime.time | None = None
    end_time: datetime.time | None = None

    venue: VenueSummary
    lineup: list[LineupEntry]

    # Admission. Three separate fields rather than one price, because
    # they answer different questions and the requirements treat them
    # differently: `free_admission` is true only when the listing says
    # so explicitly. All three null means the page didn't say — which is
    # NOT the same as free, and the UI shouldn't render it as such.
    #
    # Note these arrive in JSON as strings ("15.00"), not numbers.
    # Pydantic serializes Decimal that way on purpose, to avoid the
    # float rounding that makes money arithmetic wrong. The frontend
    # should format them as strings, not parseFloat them.
    admission_advance: Decimal | None = None
    admission_day: Decimal | None = None
    free_admission: bool | None = None

    # Poster image for the show, hosted elsewhere. Not the artist's
    # photo — the agent is explicitly told not to populate that.
    image_url: str | None = None


class ShowDetail(ShowSummary):
    """A show's own page. Everything in the summary, plus the fields
    that only matter once you're looking at the show itself.
    """

    event: EventSummary | None = None

    # The venue page this show was most recently extracted from. Shown
    # as a "source" link — part of making the agent's work visible to
    # the reader, not just to the audit trail.
    original_url: str | None = None

    # The four fields a show inherits from its venue unless overridden.
    #
    # These are the RESOLVED values: if the show's own column is null,
    # the API substitutes the venue's. The read API deliberately does
    # not expose which of the two a given value came from, because
    # nothing that renders a show cares — an all-ages show is all-ages
    # whether that was set on the show or on the venue.
    #
    # The edit API will care, because "clear this override" and "set
    # this to the same value the venue happens to have" are different
    # actions with different future behavior. That's a genuine reason
    # for the write shape to differ from this read shape, and a good
    # argument against reflexively reusing one model for both.
    age_restriction: AgeRestriction | None = None
    serves_alcohol: bool | None = None
    setting: Setting | None = None
    seating: Seating | None = None


class ShowListResponse(BaseModel):
    """Response for the calendar and day views.

    `start` and `end` echo back the range actually served rather than
    trusting the client to remember what it asked for. That matters for
    the four-week home page: the server, not the browser, decides what
    "the next four weeks" means, because the browser's clock and
    timezone aren't the metro's.
    """

    start: datetime.date
    end: datetime.date
    shows: list[ShowSummary]


class CalendarMonth(BaseModel):
    """One entry in the calendar's month dropdown.

    The requirements are specific that this list is future-facing and
    contains only months that actually have shows — so it's derived from
    the data, not generated from a date range, and it has to come from
    the server.
    """

    year: int
    month: int = Field(ge=1, le=12)
    show_count: int


class CalendarMonthsResponse(BaseModel):
    months: list[CalendarMonth]


# ---------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------


class VenueDetail(BaseModel):
    id: int
    metro: MetroSummary
    name: str
    calendar_url: str

    photo_url: str | None = None
    address: str | None = None
    # Arrays rather than child tables: a venue can list several of
    # each, and an entry carries no metadata of its own worth a row.
    phone_numbers: list[str] = []
    emails: list[str] = []
    website: str | None = None

    age_restriction: AgeRestriction | None = None
    serves_alcohol: bool | None = None
    venue_type: VenueType | None = None
    setting: Setting | None = None
    seating: Seating | None = None

    # Speculative or newly-requested fields land here before graduating
    # to a real column (arch-initial.md Section 6). Passed through to
    # the frontend as-is; nothing renders it generically yet.
    extra_metadata: dict[str, object] = {}

    # Deliberately absent: `socials`. The venue_social table is deferred
    # (v1-build-plan.md section 8), and shipping a field that is always
    # [] is worse than not shipping it — a consumer can't tell "this
    # venue has no Instagram" from "this feature doesn't exist yet".
    # Adding the field later is backward-compatible; removing it isn't.
    #
    # Also absent: `map_url`. The Google Maps link is constructed from
    # `address` by the frontend rather than the API, because it's a link
    # format rather than data — changing it shouldn't need a backend
    # deploy. See arch-initial.md Section 4.


class VenueListResponse(BaseModel):
    """The /venues page and the calendar's venue filter both read this.

    One endpoint for both because both want the same thing — every
    venue, alphabetical — and the filter's type-to-narrow behavior
    happens in the browser against the full list rather than as a
    server round trip per keystroke. That holds while a metro has tens
    of venues, which is the v1 case; it's the assumption to revisit
    first if the list ever gets long.
    """

    venues: list[VenueSummary]


# ---------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------


class ArtistDetail(BaseModel):
    id: int
    name: str
    photo_url: str | None = None
    website: str | None = None
    # Free text, deliberately not a foreign key to metro — an artist's
    # hometown is a similar concept to a metro but isn't one of ours.
    hometown: str | None = None
    format: ArtistFormat | None = None
    repertoire: ArtistRepertoire | None = None
    extra_metadata: dict[str, object] = {}

    # Deliberately absent, same reasoning as VenueDetail.socials: the
    # genre, member, and instrumentation vocabulary tables are deferred.


class ArtistListResponse(BaseModel):
    artists: list[ArtistSummary]
