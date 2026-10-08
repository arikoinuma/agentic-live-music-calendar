"""Artist routes.

TEMPORARY IMPLEMENTATION — same note as app/routers/venues.py: these
serve app/sample_data.py, and milestone A1b replaces the bodies with real
queries without changing the signatures.

Contract: docs/dev/api-contract.md section 2.
"""

from fastapi import APIRouter, HTTPException

from app import sample_data as data
from app.routers.common import NOT_FOUND
from app.schemas import ArtistDetail, ArtistListResponse

router = APIRouter(prefix="/artists", tags=["artists"])


@router.get("")
def list_artists() -> ArtistListResponse:
    """Every artist, alphabetical.

    Serves the /artists page and the calendar's artist filter. Artists
    are global rather than metro-scoped — acts tour between markets —
    so this list is deliberately not filtered by metro.

    Unpaginated, like /venues. This is the list most likely to outgrow
    that: every act the agent has ever seen on any venue's calendar
    lands here, including one-off openers, so it grows with time rather
    than with the venue count. The response envelope leaves room to
    paginate without a breaking change.
    """
    return ArtistListResponse(artists=sorted(data.ARTISTS, key=lambda a: a.name))


@router.get("/{artist_id}", responses=NOT_FOUND)
def get_artist(artist_id: int) -> ArtistDetail:
    artist = data.artist_detail(artist_id)
    if artist is None:
        raise HTTPException(status_code=404, detail="Artist not found")
    return artist
