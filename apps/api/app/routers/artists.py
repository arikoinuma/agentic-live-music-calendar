"""Artist routes.

The bodies call `app.queries`, which reads Postgres (C2). Artists are global, so these routes
don't take the metro.

Contract: docs/dev/api-contract.md section 2.
"""

from fastapi import APIRouter, HTTPException

from app import queries
from app.dependencies import Db
from app.routers.common import NOT_FOUND
from app.schemas import ArtistDetail, ArtistListResponse

router = APIRouter(prefix="/artists", tags=["artists"])


@router.get("")
async def list_artists(session: Db) -> ArtistListResponse:
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
    return ArtistListResponse(artists=await queries.list_artists(session))


@router.get("/{artist_id}", responses=NOT_FOUND)
async def get_artist(artist_id: int, session: Db) -> ArtistDetail:
    artist = await queries.get_artist(session, artist_id)
    if artist is None:
        raise HTTPException(status_code=404, detail="Artist not found")
    return artist
