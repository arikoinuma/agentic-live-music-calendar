"""Venue routes.

The bodies call `app.queries`, which reads Postgres (C2); the URLs, response models and error
behavior are the ones the frontend was built against while this served sample data.

Contract: docs/dev/api-contract.md section 2.
"""

from fastapi import APIRouter, HTTPException

from app import queries
from app.dependencies import Db, DbId, LiveMetro
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
async def get_venue(venue_id: DbId, session: Db, metro: LiveMetro) -> VenueDetail:
    venue = await queries.get_venue(session, metro, venue_id)
    # A miss is a 404, declared in the route's `responses` so the generated TypeScript knows it can happen.
    # Raising also narrows `VenueDetail | None` to `VenueDetail` for the return below.
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue
