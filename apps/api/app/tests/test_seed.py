"""The seed script's logic, against a real Postgres.

WHAT THIS COVERS
  `seed()` (app/db/seed.py) creates the Minneapolis/St. Paul metro and the
  four starting venues. These tests check that it creates the right rows and
  that running it again is harmless. Run against a real database because the
  interesting behaviour is "look up, then insert if missing", which only
  means something with real rows to find.

Written before the seed (docs/dev/implementations/a1-data-layer.md, layer 3).
`seed(session)` takes the session as an argument precisely so this test can
hand it one inside a rolled-back transaction — if it reached for the
module-level SessionFactory it would write to calendar_dev.

Never asserts on ids: sequences don't roll back, so ids depend on what ran
before. The frontend-fixture id alignment (docs/dev/api-contract.md: "one
world") holds on a fresh database and is checked by hand in the A1
verification steps instead.
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Metro, Venue
from app.db.seed import seed

# What the seed must produce, in insert order: (name, calendar URL,
# fetch_strategy). Typed out here rather than imported from seed.py so the
# test is an independent statement of the expectation.
# From each saved fixture's `saved from url` / canonical tag; fetch_strategy
# from the pagination patterns found in those fixtures (see seed.py).
EXPECTED_VENUES = [
    ("The White Squirrel Bar", "https://whitesquirrelbar.com/calendar/", "http"),
    ("The Midway Saloon", "https://www.themidwaysaloon.com/events", "http"),
    ("Zhora Darling", "https://www.zhoradarling.com/events", "browser"),
    ("The Terminal Bar", "https://terminalbarmn.com/live-music/", "http"),
]


async def _counts(session: AsyncSession) -> tuple[int, int]:
    """(number of metro rows, number of venue rows) currently in the database."""
    metros = (await session.execute(sa.select(sa.func.count()).select_from(Metro))).scalar_one()
    venues = (await session.execute(sa.select(sa.func.count()).select_from(Venue))).scalar_one()
    return metros, venues


async def test_seed_creates_the_metro_and_four_venues(db_session: AsyncSession) -> None:
    # Proves: one seed run produces the one metro (with its timezone, which
    # drives how the calendar renders dates) and the four venues, each linked
    # to that metro, with the expected URL and fetch strategy.
    await seed(db_session)

    metro = (await db_session.execute(sa.select(Metro))).scalar_one()
    assert metro.name == "Minneapolis/St. Paul"
    assert metro.timezone == "America/Chicago"

    # Ordered by id = insertion order, which is what makes ids line up with
    # the frontend fixtures on a fresh database.
    venues = (await db_session.execute(sa.select(Venue).order_by(Venue.id))).scalars().all()
    assert [(v.name, v.calendar_url, v.fetch_strategy.value) for v in venues] == EXPECTED_VENUES
    assert all(v.metro_id == metro.id for v in venues)


async def test_seeding_twice_changes_nothing(db_session: AsyncSession) -> None:
    # Proves: the seed is idempotent. `make setup` and `make db-reset` both
    # run it, and developers will run it again by hand; it must never
    # duplicate the metro or the venues.
    await seed(db_session)
    await seed(db_session)
    assert await _counts(db_session) == (1, 4)
