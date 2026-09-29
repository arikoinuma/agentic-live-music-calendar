"""Venue routes.

TEMPORARY IMPLEMENTATION. These serve app/sample_data.py, not the
database. The point is that the *shape* is real — same URLs, same
response models, same error behavior the real API will have — so the
frontend can be built against actual HTTP now, and milestone A1 swaps
only the bodies of these functions for real queries. The signatures
shouldn't need to change.

Contract: docs/dev/api-contract.md section 2.
"""

from fastapi import APIRouter, HTTPException

from app import sample_data as data
from app.routers.common import NOT_FOUND
from app.schemas import VenueDetail, VenueListResponse

router = APIRouter(prefix="/venues", tags=["venues"])


@router.get("")
def list_venues() -> VenueListResponse:
    """Every venue, alphabetical.

    Serves both the /venues page and the calendar's venue filter — the
    filter narrows in the browser against this full list rather than
    hitting the server per keystroke.
    """
    return VenueListResponse(venues=sorted(data.VENUES, key=lambda v: v.name))


@router.get("/{venue_id}", responses=NOT_FOUND)
def get_venue(venue_id: int) -> VenueDetail:
    venue = data.venue_detail(venue_id)
    # `is None`, not `== None` and certainly not `== "None"` — None is a
    # singleton, so identity is both the correct test and the faster one.
    # Raising here also narrows the type from `VenueDetail | None` to
    # `VenueDetail`, which is what lets the return below typecheck.
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue
