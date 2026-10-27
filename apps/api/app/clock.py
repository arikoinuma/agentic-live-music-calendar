"""The API's clock: the one place the process clock is read (C2-D2).

Two pieces. `get_now` is a FastAPI dependency returning the current instant, so a test or the
end-to-end job can replace it with a fixed one through `app.dependency_overrides` instead of the
production process honouring a "freeze the clock" variable. `metro_today` turns an instant into the
date it is in the metro's timezone, which is what "today" means everywhere in the read API
(api-contract.md section 3, "The server owns now").
"""

import datetime
from zoneinfo import ZoneInfo


def get_now() -> datetime.datetime:
    """The current instant, timezone-aware (UTC). Override this dependency to fix the clock."""
    return datetime.datetime.now(datetime.UTC)


def metro_today(now: datetime.datetime, timezone: str) -> datetime.date:
    """The calendar date `now` falls on in `timezone` (an IANA name such as "America/Chicago").

    Not `now.date()`: at 22:30 in Minneapolis on October 7 it is already October 8 in UTC, and a window
    that starts on the UTC date shows tomorrow's shows to everyone planning the evening (C2-M3). The
    offset comes from the zone database, not a constant, so it also moves when daylight time ends.

    A naive datetime is refused: it carries no instant, and guessing UTC or local would be a silent bug.
    """
    if now.tzinfo is None:
        raise ValueError("metro_today needs a timezone-aware datetime")
    return now.astimezone(ZoneInfo(timezone)).date()
