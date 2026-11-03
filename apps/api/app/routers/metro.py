"""Metro route — the one live metro's name and timezone.

Why it exists: before B2 the metro only appeared nested inside VenueDetail, so the frontend's layout had
no way to ask "what is this calendar for?" without fetching an arbitrary venue. The layout's footer and
<meta description> read the name from here (alpha-build-plan.md v0.1-G24). Since C2 it is the lowest-id
row of the `metro` table (app/dependencies.py, `current_metro`).

Contract: docs/dev/api-contract.md section 2.
"""

from fastapi import APIRouter

from app.dependencies import LiveMetro
from app.schemas import MetroSummary

router = APIRouter(prefix="/metro", tags=["metro"])


@router.get("")
async def get_metro(metro: LiveMetro) -> MetroSummary:
    """The single live metro. No id in the path: v1 has exactly one, and
    `arch-initial.md` §11 tracks multi-metro as deferred, so adding a
    `/metro/{id}` later is additive."""
    return MetroSummary(id=metro.id, name=metro.name, timezone=metro.timezone, slug=metro.slug)
