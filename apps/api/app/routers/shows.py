"""Show routes — the calendar itself.

TEMPORARY IMPLEMENTATION — see app/routers/venues.py. The filtering
below happens in Python over an in-memory list; A1 replaces it with a
WHERE clause. The query parameters and the response shape are the part
meant to survive that.

Contract: docs/dev/api-contract.md section 2.
"""

import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app import sample_data as data
from app.routers.common import NOT_FOUND
from app.schemas import ShowDetail, ShowListResponse, ShowSummary

router = APIRouter(prefix="/shows", tags=["shows"])

# How far past `start` the default window reaches: the home page's four
# weeks, counted inclusively (28 days = today plus 27).
DEFAULT_WINDOW = datetime.timedelta(days=27)

# Longest range a single request may ask for. Pointless against an
# in-memory list, and the reason it's here anyway: once this is a real
# query, an unbounded range is an unbounded scan, and an accidental
# ?start=2020-01-01&end=2030-01-01 from a buggy client shouldn't be able
# to ask Postgres for a decade. Cheaper to establish the bound now, while
# no client depends on its absence.
MAX_RANGE = datetime.timedelta(days=366)


@router.get("")
def list_shows(
    start: datetime.date | None = None,
    end: datetime.date | None = None,
    # A list-valued query parameter needs the explicit Query() marker.
    # Without it FastAPI sees a non-scalar type annotation and assumes
    # the value belongs in the request *body*, which for a GET means it
    # never arrives. This is the single most surprising thing about
    # FastAPI's parameter inference.
    #
    # Repeat the key to pass several: ?venue_id=1&venue_id=3
    venue_id: Annotated[list[int] | None, Query()] = None,
    artist_id: Annotated[list[int] | None, Query()] = None,
) -> ShowListResponse:
    """Shows in a date range, optionally filtered by venue and artist.

    Serves the home calendar, /day/[date], and the calendar embedded on
    venue and artist pages — one endpoint rather than four, because all
    four want the same rows and differ only in how they group them.
    Grouping is presentation and stays in the frontend; the day view
    needs three different groupings of identical data, which a
    pre-grouped response would have to serve as three separate shapes.

    Filters are AND-ed across types and OR-ed within one: two venue_ids
    means "either venue", which is what a multi-select visibly implies,
    while a venue_id plus an artist_id means both must hold.
    """
    # The server decides what "now" means, not the browser — its clock
    # and timezone aren't the metro's. Against sample data that's a
    # pinned constant; the real version reads the metro's local date.
    if start is None:
        start = data.START
    if end is None:
        end = start + DEFAULT_WINDOW

    if end < start:
        raise HTTPException(status_code=422, detail="`end` must be on or after `start`")
    if end - start > MAX_RANGE:
        raise HTTPException(
            status_code=422,
            detail=f"Date range too wide; maximum is {MAX_RANGE.days} days",
        )

    shows = [s for s in data.SHOWS if start <= s.date <= end]

    if venue_id:
        wanted = set(venue_id)
        shows = [s for s in shows if s.venue.id in wanted]

    if artist_id:
        wanted = set(artist_id)
        # A show matches if *any* act on its bill does — an artist's
        # page should show a festival slot where they're third on the
        # lineup, not only the nights they headline.
        shows = [s for s in shows if any(e.artist.id in wanted for e in s.lineup)]

    return ShowListResponse(start=start, end=end, shows=sorted(shows, key=_ordering))


def _ordering(show: ShowSummary) -> tuple[datetime.date, bool, datetime.time, str]:
    """Sort key: by date, then by start time, then by venue name.

    The `start_time is None` element is why this is a function and not a
    lambda. A show with no listed time can't be compared against one
    that has a time, and it shouldn't silently sort as midnight either —
    "time not stated" isn't "first thing in the morning". Sorting the
    None-valued ones to the end of their day is a real decision, and
    the frontend renders them differently for the same reason.
    """
    return (
        show.date,
        show.start_time is None,
        show.start_time or datetime.time.min,
        show.venue.name,
    )


@router.get("/{show_id}", responses=NOT_FOUND)
def get_show(show_id: int) -> ShowDetail:
    show = data.show_detail(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")
    return show
