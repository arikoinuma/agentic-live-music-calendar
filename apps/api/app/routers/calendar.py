"""Calendar metadata routes — things about the calendar rather than the
shows in it.

Contract: docs/dev/api-contract.md section 2.
"""

from fastapi import APIRouter

from app import queries
from app.dependencies import Db, LiveMetro, Today
from app.schemas import CalendarMonthsResponse

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/months")
async def list_months(session: Db, metro: LiveMetro, today: Today) -> CalendarMonthsResponse:
    """Months available in the calendar's month dropdown.

    The requirements are specific that this list is future-facing and
    contains only months that actually have shows. Both halves of that
    make it a server concern: "future" depends on the metro's current
    local date, not the browser's, and "has shows" is a query. A client
    generating twelve months from today would get both wrong.
    """
    return CalendarMonthsResponse(months=await queries.list_months(session, metro, today))
