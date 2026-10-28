"""Seed data: the Minneapolis/St. Paul metro and the starting venue list.

The logic lives here, in `app/`, rather than in scripts/seed.py so that it
takes a session as an argument (the tests hand it one inside a rolled-back
transaction), and so mypy covers it. scripts/seed.py is the CLI wrapper.

Only the metro and venues — no invented shows or artists. Real rows come
from the agent (docs/dev/alpha-build-plan.md, A1). The sample world the tests
and the end-to-end job use is a separate thing, loaded into its own databases
(app/testing/sample_data.py); this seed is what a real environment gets.

The seed only inserts: running it again adds a venue that is new to the list
and leaves the rest alone, and it never removes one. A database seeded before
C2 therefore still has the Midway Saloon and Zhora Darling after `make seed`
(and the worker still fetches them); `make db-reset` is how a developer gets
the new list (C2-PR1-12).

Flushes but does not commit: the caller owns the transaction, so the seed can
be part of a larger one (and the tests can roll it back). scripts/seed.py
commits.

Idempotent by lookup, not by constraint: the metro is found by name and a
venue by (metro, name), and inserted only if missing. Adding a unique
constraint purely to make a seed script simple isn't a schema decision
worth making here.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Metro, Venue
from app.enums import FetchStrategy

# The one metro this app serves in v1. The timezone is an IANA name; it is
# what makes the calendar show a 7pm show as 7pm in Minneapolis rather than
# in the viewer's browser's zone (alpha-build-plan.md, B3).
METRO_NAME = "Minneapolis/St. Paul"
METRO_TIMEZONE = "America/Chicago"

# One venue list for every environment (Dep-D16, C2-D8): production's, and dev and
# staging hold a copy of it. Insert order assigns the ids, so don't reorder;
# append new venues at the end.
#
# The Midway Saloon and Zhora Darling are out until they have a route: the venue
# table has no active flag, so a seeded venue is fetched by the worker and listed by
# the API. The Midway's page answers a bot check this project won't pass (A2.1-D3) and
# Zhora Darling's widget draws its listings client-side, so neither extracts anything
# today. Add a venue by adding a row here and running `make seed` against each database.
#
# URLs are each saved fixture's `saved from url` / canonical tag
# (agent_worker/eval/fixtures/), except 7th St Entry's and Mortimer's, which are
# agent_worker/eval/labels.py's.
#
# fetch_strategy: only the HTTP path exists this phase (build plan section 8). The
# two new rows are `http` as an ASSUMPTION, not a check (C2-D8): nobody has made a
# plain GET to either page from a machine that can reach them. Confirm that the shows
# are in the raw HTML, as the Midway comment did, and flip to BROWSER if they aren't.
# Each entry: (venue name, URL of its live-music calendar page, how the agent
# should fetch that page).
VENUES: list[tuple[str, str, FetchStrategy]] = [
    # The Events Calendar plugin: "Next Events" is a plain URL link, so a
    # plain GET can follow the pagination.
    ("The White Squirrel Bar", "https://whitesquirrelbar.com/calendar/", FetchStrategy.HTTP),
    # First Avenue's site lists the 7th St Entry's shows under one venue id. Unverified: see above.
    ("7th St Entry", "https://first-avenue.com/shows/?venues=59161", FetchStrategy.HTTP),
    # Weekly comedy and karaoke between the music shows (labels.py); unverified: see above.
    ("Mortimer's", "https://www.mortimerscalendar.com/", FetchStrategy.HTTP),
    # No pagination pattern, but the show information is inside images
    # embedded in the page. Detecting and downloading those is deferred
    # (build plan section 8). Confirmed October 10, 2026 (A2.1): the page TEXT
    # still lists each show's date and acts, so the model route extracts those;
    # only the times (in the posters) wait for the image path. Terminal Bar stays
    # in the list until Ari decides otherwise (Dep-D16).
    ("The Terminal Bar", "https://terminalbarmn.com/live-music/", FetchStrategy.HTTP),
]


async def seed(session: AsyncSession) -> None:
    """Insert the metro and venues that don't exist yet.

    Safe to call any number of times. Does not commit; the caller does.
    """
    # Step 1: find the metro, or create it. (Looked up by name because the
    # metro table has no other natural key.)
    metro = (
        await session.execute(select(Metro).where(Metro.name == METRO_NAME))
    ).scalar_one_or_none()
    if metro is None:
        metro = Metro(name=METRO_NAME, timezone=METRO_TIMEZONE)
        session.add(metro)
        await session.flush()  # assigns metro.id, needed by the venues below

    # Step 2: for each venue, insert it only if this metro doesn't already
    # have a venue of that name. That check is what makes re-running a no-op.
    for name, calendar_url, strategy in VENUES:
        existing = (
            await session.execute(
                select(Venue.id).where(Venue.metro_id == metro.id, Venue.name == name)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Venue(
                    metro_id=metro.id,
                    name=name,
                    calendar_url=calendar_url,
                    fetch_strategy=strategy,
                )
            )
            # Flush per venue so ids are assigned in list order.
            await session.flush()
