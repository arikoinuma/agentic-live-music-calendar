"""Dependencies the read routes share: the database session, the live metro and its "today", and the id types.

Each is exposed as an `Annotated` alias (`Db`, `LiveMetro`, `Today`) so a route declares what it needs in
its signature and FastAPI supplies it (docs/references/fastapi-style-guide.md, "Use Annotated, not
default-arg Depends"). They are resolved once per request even when several depend on each other.

`DbId` and `IdFilter` are not dependencies but parameter types, kept here so every route that takes a database id
bounds it the same way (see their comments).
"""

import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import get_now, metro_today
from app.db.models import Metro
from app.db.session import get_db

Db = Annotated[AsyncSession, Depends(get_db)]

# The largest id a row can have: every primary and foreign key is a Postgres `integer` (int32). asyncpg refuses a bigger
# value with a `DBAPIError`, which nothing catches, so before PQR1-5 `GET /shows/99999999999` was a 500. Bounding the
# parameter makes it a 422 at the edge, and the same limits as the Next.js app, which already refuses ids outside this
# range before it calls the API (`MAX_ID` in apps/calendar/lib/params.ts).
MAX_DB_ID = 2**31 - 1

# A path id: `/shows/{show_id}`, `/venues/{venue_id}`, `/artists/{artist_id}`. Ids start at 1, so 0 and negatives are
# refused too (a 422, where they used to be a 404; the frontend never sends them).
DbId = Annotated[int, Path(ge=1, le=MAX_DB_ID)]

# A repeatable id filter: `?venue_id=1&venue_id=3`. The bounds sit on each item (`Field`), NOT on `Query(ge=..., le=...)`:
# on a `list[int]`, `Query(ge=1)` registers without complaint and then answers 500 to every request that supplies a value
# (`TypeError: Unable to apply constraint 'ge'`). The list itself has no length cap, by decision (PQR1-5-D2): the metro
# is nowhere near a size where one is needed, and the URL length already limits a request.
IdFilter = Annotated[list[Annotated[int, Field(ge=1, le=MAX_DB_ID)]] | None, Query()]


async def current_metro(session: Db) -> Metro:
    """The one live metro: the lowest-id `metro` row (C2-D5; v1 has exactly one, api-contract.md section 2).

    Every venue, show and month query is scoped to it, so a second metro's rows never leak into this
    one's responses and a slug lookup can later replace this function instead of every query. C4 did not
    replace it (C4-D9): the metro now has a slug, but the host's slug is checked in the Next.js proxy and does not
    reach the API, because scoping queries by metro is deferred until a second metro exists (arch-initial.md
    section 11).

    A migrated but unseeded database has no metro. That is an operational failure, not something the
    frontend can answer differently, so it is a 503 whose `detail` names the fix, and it is deliberately
    not declared in the routes' `responses` (C2-D3): declaring it would change the OpenAPI document and
    the generated TypeScript for no consumer.
    """
    metro = (await session.execute(select(Metro).order_by(Metro.id).limit(1))).scalar_one_or_none()
    if metro is None:
        raise HTTPException(
            status_code=503,
            detail="No metro in the database: run the seed (`make seed`) before serving the calendar",
        )
    return metro


LiveMetro = Annotated[Metro, Depends(current_metro)]


async def today(metro: LiveMetro, now: Annotated[datetime.datetime, Depends(get_now)]) -> datetime.date:
    """The metro's local date right now: the start of the default window and of `upcoming`."""
    return metro_today(now, metro.timezone)


Today = Annotated[datetime.date, Depends(today)]
