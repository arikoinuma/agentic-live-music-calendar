"""Seed data: the Minneapolis/St. Paul metro and the four Phase 5 venues.

The logic lives here, in `app/`, rather than in scripts/seed.py so that it
takes a session as an argument (the tests hand it one inside a rolled-back
transaction), and so mypy covers it. scripts/seed.py is the CLI wrapper.

Only the metro and venues — no invented shows or artists. Real rows come
from the agent (docs/dev/alpha-build-plan.md, A1).

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

# Same four venues, in the same order, as app/sample_data.py — so on a fresh
# database the ids (1-4) line up with the frontend's generated fixtures
# (docs/dev/api-contract.md: both describe "one world"). Insert order is
# what assigns the ids, so don't reorder.
#
# URLs are each saved fixture's `saved from url` / canonical tag
# (agent_worker/eval/fixtures/).
#
# fetch_strategy is read off those same fixtures, not defaulted ("set
# appropriately", build plan A1). Only the HTTP path exists this phase
# (build plan section 8), so BROWSER here means "this venue will be
# under-extracted until Playwright lands", which is the honest state.
# Each entry: (venue name, URL of its live-music calendar page, how the agent
# should fetch that page). The comments above each entry say why the strategy
# was chosen.
VENUES: list[tuple[str, str, FetchStrategy]] = [
    # The Events Calendar plugin: "Next Events" is a plain URL link, so a
    # plain GET can follow the pagination.
    ("The White Squirrel Bar", "https://whitesquirrelbar.com/calendar/", FetchStrategy.HTTP),
    # No load-more or JS-pagination pattern found in the fixture. "Nothing
    # found", not proof: the fixtures are Chrome "save page" captures, i.e.
    # the DOM *after* JavaScript ran, so a page that renders only through JS
    # (this one is a Popmenu/React site) would look identical. Confirm with a
    # plain `httpx.get` when real fetching lands (A3/A4) and flip to BROWSER
    # if the shows aren't in the raw HTML.
    # Confirmed October 10, 2026 (A2.1): a plain GET gets HTTP 403 with a
    # Cloudflare "Enable JavaScript and cookies" challenge — a bot check this
    # project won't try to get past (A2.1-D3). BROWSER wouldn't be the
    # honest fix either, so the strategy is left as it is; until a sanctioned
    # route exists (asking the venue, a public feed) this venue extracts nothing.
    ("The Midway Saloon", "https://www.themidwaysaloon.com/events", FetchStrategy.HTTP),
    # A Dice widget with `<button type="button" class="dice_load-more">`:
    # click-driven, which is exactly the case FetchStrategy.BROWSER exists
    # for. Until Playwright lands only its first page is extractable.
    # Confirmed October 10, 2026 (A2.1): worse than that — a plain GET returns
    # no listings at all (314 characters of visible text). The widget draws
    # every listing, and its schema.org event data, client-side.
    ("Zhora Darling", "https://www.zhoradarling.com/events", FetchStrategy.BROWSER),
    # No pagination pattern, but the show information is inside images
    # embedded in the page. Detecting and downloading those is deferred
    # (build plan section 8). Confirmed October 10, 2026 (A2.1): the page TEXT
    # still lists each show's date and acts, so the model route extracts those;
    # only the times (in the posters) wait for the image path.
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
