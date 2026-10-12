"""Metro route — the one live metro's name and timezone.

TEMPORARY IMPLEMENTATION — see app/routers/venues.py. This serves
`sample_data.METRO`; A1b swaps the body for a query against the `metro`
table (seeded by scripts/seed.py) without changing the URL or the
response model.

Why it exists: before B2 the metro only appeared nested inside
VenueDetail, so the frontend's layout had no way to ask "what is this
calendar for?" without fetching an arbitrary venue. The layout's footer
and <meta description> read the name from here (v1-build-plan.md G24).

Contract: docs/dev/api-contract.md section 2.
"""

from fastapi import APIRouter

from app import sample_data as data
from app.schemas import MetroSummary

router = APIRouter(prefix="/metro", tags=["metro"])


@router.get("")
def get_metro() -> MetroSummary:
    """The single live metro. No id in the path: v1 has exactly one, and
    `arch-initial.md` §11 tracks multi-metro as deferred, so adding a
    `/metro/{id}` later is additive."""
    return data.METRO
