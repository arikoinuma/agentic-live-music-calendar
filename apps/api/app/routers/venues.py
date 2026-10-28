"""Venue routes.

The bodies call `app.queries`, which reads Postgres (C2); the URLs, response models and error
behavior are the ones the frontend was built against while this served sample data.

Contract: docs/dev/api-contract.md section 2.
"""

from fastapi import APIRouter, HTTPException

from app import queries
from app.dependencies import Db, LiveMetro
from app.routers.common import NOT_FOUND
from app.schemas import VenueDetail, VenueListResponse

router = APIRouter(prefix="/venues", tags=["venues"])


@router.get("")
async def list_venues(session: Db, metro: LiveMetro) -> VenueListResponse:
    """Every venue, alphabetical.

    Serves both the /venues page and the calendar's venue filter — the
    filter narrows in the browser against this full list rather than
    hitting the server per keystroke.
    """
    return VenueListResponse(venues=await queries.list_venues(session, metro))


@router.get("/{venue_id}", responses=NOT_FOUND)
async def get_venue(venue_id: int, session: Db, metro: LiveMetro) -> VenueDetail:
    venue = await queries.get_venue(session, metro, venue_id)
    # `is None`, not `== None` and certainly not `== "None"` — None is a
    # singleton, so identity is both the correct test and the faster one.
    # Raising here also narrows the type from `VenueDetail | None` to
    # `VenueDetail`, which is what lets the return below typecheck.
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue
