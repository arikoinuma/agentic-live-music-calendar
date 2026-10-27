"""Show routes — the calendar itself.

The request rules live here (a range must be ordered and no wider than `MAX_RANGE`; `upcoming` can't be
combined with a range); the data comes from `app.queries`, which reads Postgres (C2).

Contract: docs/dev/api-contract.md section 2.
"""

import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app import queries
from app.dependencies import Db, LiveMetro, Today
from app.routers.common import NOT_FOUND
from app.schemas import ShowDetail, ShowListResponse

router = APIRouter(prefix="/shows", tags=["shows"])

# How far past `start` the default window reaches: the home page's four
# weeks, counted inclusively (28 days = today plus 27).
DEFAULT_WINDOW = datetime.timedelta(days=27)

# Longest range a single request may ask for. The query behind this is a real
# one, so an unbounded range is an unbounded scan: an accidental
# ?start=2020-01-01&end=2030-01-01 from a buggy client shouldn't be able
# to ask Postgres for a decade. The bound was set before the routes read the
# database (C2) so that no client ever came to depend on its absence.
MAX_RANGE = datetime.timedelta(days=366)


@router.get("")
async def list_shows(
    session: Db,
    metro: LiveMetro,
    today: Today,
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
    # "Every show from today on, however far out" -- the artist page's
    # "upcoming shows" (B4-D2). A client can't ask for that with
    # dates: the server owns "now" (api-contract.md section 3), and an
    # open-ended range has no end date to send. A plain bool needs no
    # Query() marker, unlike the list parameters above.
    upcoming: bool = False,
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

    `upcoming=true` replaces the date range with "from the server's today,
    no upper limit". It is refused (422) when combined with `start` or
    `end` -- the two contradict each other, and silently preferring one
    would hide a client bug -- and when neither `venue_id` nor `artist_id`
    is given: every show in the metro with no upper bound is exactly the
    unbounded scan MAX_RANGE exists to prevent, while one artist or venue
    is bounded by what they can play. The response keeps its shape:
    `start` is today and `end` is the date of the last show returned (or
    `start` when there is none), so the echoed range is always valid.
    """
    # The server decides what "now" means, not the browser — its clock
    # and timezone aren't the metro's. `today` is the metro's local date, from
    # the injected clock (app/clock.py, C2-D2).
    if upcoming:
        if start is not None or end is not None:
            raise HTTPException(
                status_code=422,
                detail="`upcoming` cannot be combined with `start` or `end`",
            )
        if not venue_id and not artist_id:
            raise HTTPException(
                status_code=422,
                detail="`upcoming` needs a `venue_id` or `artist_id`; "
                "without one it would be an unbounded scan of every show",
            )
        # Open-ended: from today with no upper bound. `end` is filled in
        # below from what was actually returned. MAX_RANGE doesn't apply --
        # there is no client-supplied range to bound -- so this branch
        # stays out of the range checks that follow.
        start = today
        end = datetime.date.max
    else:
        if start is None:
            start = today
        if end is None:
            end = start + DEFAULT_WINDOW

        if end < start:
            raise HTTPException(status_code=422, detail="`end` must be on or after `start`")
        if end - start > MAX_RANGE:
            raise HTTPException(
                status_code=422,
                detail=f"Date range too wide; maximum is {MAX_RANGE.days} days",
            )

    shows = await queries.list_shows(session, metro, start, end, venue_id, artist_id)

    if upcoming:
        # Echo the range actually covered: today to the last show returned,
        # or just today when nothing matched, so end >= start always holds.
        end = max((s.date for s in shows), default=start)

    return ShowListResponse(start=start, end=end, shows=shows)


@router.get("/{show_id}", responses=NOT_FOUND)
async def get_show(show_id: int, session: Db, metro: LiveMetro) -> ShowDetail:
    show = await queries.get_show(session, metro, show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")
    return show
