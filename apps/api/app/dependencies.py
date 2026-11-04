"""Dependencies the read routes share: the database session, the live metro and its "today".

Each is exposed as an `Annotated` alias (`Db`, `LiveMetro`, `Today`) so a route declares what it needs in
its signature and FastAPI supplies it (docs/references/fastapi-style-guide.md, "Use Annotated, not
default-arg Depends"). They are resolved once per request even when several depend on each other.
"""

import datetime
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import get_now, metro_today
from app.db.models import Metro
from app.db.session import get_db

Db = Annotated[AsyncSession, Depends(get_db)]


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
