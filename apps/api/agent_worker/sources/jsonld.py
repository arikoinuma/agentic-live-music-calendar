"""Read a venue's own schema.org event data (JSON-LD) instead of asking a model to read the page.

Many venue sites embed their listings as schema.org `Event` objects inside
`<script type="application/ld+json">` blocks — White Squirrel's calendar plugin does, in the
page the pipeline actually fetches (verified October 10, 2026). Where they exist, dates,
times, end times, prices and images can be read exactly, with no model involved (D4 of
docs/dev/implementations/a2.1-extraction-reliability.md). The model is still needed for one
thing JSON-LD doesn't say — which performing acts a title names — and that is `act_split.py`.

Field names are schema.org's published vocabulary (`name`, `startDate`, `endDate`,
`eventStatus`, `offers`, `image`), not each site's own, so they are mapped here in code. What
varies between sites is *shape* — an object or a list, `image` as a string or an object, `Z` or
an offset — and each function below handles the shapes the fixtures actually use. A site whose
events lack `name` or `startDate` isn't usable here and falls back to the model route.

How to read it: `find_events` pulls Event objects out of a page; `local_wall_clock` turns a
schema.org date-time into the metro's local date and time (Gap A); `to_structured_show`
maps one event to a `StructuredShow`, the route's intermediate record.
"""

import datetime
import html as html_lib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from agent_worker.normalize import fold_text

# A show belongs to the night the venue lists it under; a time before this is after midnight of that
# night (Ari, October 11, 2026; requirements-initial.md, Show, "Times after midnight").
NIGHT_CUTOFF = datetime.time(5, 0)

# An end more than this long after the start isn't a stated end time: DICE-backed pages emit
# endDates 3-15 hours after the start that no page states (A2.1 plan, D10).
_MAX_SHOW_LENGTH = datetime.timedelta(hours=6)


@dataclass(frozen=True)
class StructuredShow:
    """One event as read from JSON-LD, before its title is split into acts. Every optional
    field is None when the event doesn't state it — "not stated", never a guess."""

    title: str
    date: datetime.date
    time: datetime.time | None
    end_time: datetime.time | None
    image_url: str | None
    admission_advance: float | None
    admission_day: float | None
    free_admission: bool | None
    status: str


# ---------------------------------------------------------------------------
# Finding events
# ---------------------------------------------------------------------------


def _is_event(item: Any) -> bool:
    """True for a schema.org Event or a subtype (MusicEvent, ComedyEvent…), with `@type`
    given as a string or a list."""
    if not isinstance(item, dict):
        return False
    types = item.get("@type")
    names = types if isinstance(types, list) else [types]
    return any(isinstance(t, str) and t.endswith("Event") for t in names)


def find_events(html: str) -> list[dict[str, Any]]:
    """Every schema.org Event object on the page, in document order.

    A block may hold one object, a list of objects, or an `@graph` (White Squirrel uses a list
    block next to an `@graph` of WebSite/CollectionPage). An unparseable block is skipped, not
    raised: one malformed block must not cost a page its other events.
    """
    soup = BeautifulSoup(html, "html.parser")
    events: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                events.extend(i for i in item["@graph"] if _is_event(i))
            elif _is_event(item):
                events.append(item)
    return events


# ---------------------------------------------------------------------------
# Wall clock
# ---------------------------------------------------------------------------


def _is_date_only(value: str) -> bool:
    """True for "2026-10-09"; False for any date-time, whether written with "T" or with the
    space ISO 8601 also allows (code review #6a)."""
    return len(value.strip()) == 10


def local_wall_clock(value: str, metro_timezone: str) -> tuple[datetime.date, datetime.time | None]:
    """A schema.org date or date-time -> the metro's local date and (naive) time.

    A date-only value ("2026-10-09") states no time. `datetime.fromisoformat` would read it as
    midnight, which the eval would score as an invented 00:00 start, so it is handled first.
    """
    if _is_date_only(value):
        return datetime.date.fromisoformat(value), None

    # Convert, don't drop. A2 Decision #3 drops a zone suffix from a *model's* time, because a
    # model's "Z" is noise. A structured source's offset is information: DICE's "2026-08-17T23:00:00Z"
    # IS 18:00 in Minneapolis, and after the November 1 change a UTC evening is the PREVIOUS local day
    # ("2026-11-06T02:00:00Z" is Nov 5, 20:00). So an aware value is converted into the metro's zone
    # (`metro.timezone`, data-model-initial.md, the source of truth for which clock a show's time is
    # on). A naive value is already local. The date is taken AFTER converting.
    parsed = datetime.datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo(metro_timezone))
    return parsed.date(), parsed.time().replace(tzinfo=None)


# ---------------------------------------------------------------------------
# One event -> one structured show
# ---------------------------------------------------------------------------

_STATUS = {"EventCancelled": "cancelled", "EventPostponed": "postponed"}


_STATUS_IN_TITLE = re.compile(r"\b(cancell?ed|postponed)\b", re.IGNORECASE)


def _status(event: dict[str, Any]) -> str:
    """schema.org eventStatus (a full URL or the bare name) -> D12's show status. A status
    written in the event's own name ("CANCELLED: …") counts too, for sites that leave eventStatus
    at Scheduled or omit it (code review round 2, #8)."""
    raw = event.get("eventStatus")
    name = raw.rsplit("/", 1)[-1] if isinstance(raw, str) else ""
    status = _STATUS.get(name, "scheduled")
    if status == "scheduled":
        found = _STATUS_IN_TITLE.search(html_lib.unescape(str(event.get("name", ""))))
        if found:
            return "postponed" if found.group(1).lower() == "postponed" else "cancelled"
    return status


def _image(event: dict[str, Any]) -> str | None:
    """The first image URL, whether `image` is a string, a list, or an ImageObject."""
    image = event.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    return image if isinstance(image, str) and image else None


def _offer_price(event: dict[str, Any]) -> float | None:
    """The first offer's price, as a float; None if there is no priced offer."""
    offers = event.get("offers")
    for offer in offers if isinstance(offers, list) else [offers]:
        if isinstance(offer, dict) and offer.get("price") not in (None, ""):
            try:
                return float(offer["price"])
            except (TypeError, ValueError):
                continue
    return None


def _end_time(event: dict[str, Any], metro_timezone: str, start: str) -> datetime.time | None:
    """The end's clock time, only when it is a plausible stated end (D10): within six hours
    after the start. Its date is ignored — "9:00 pm - 12:00 am" ends the next day, and A3's
    consistency check allows an end earlier than the start."""
    end = event.get("endDate")
    if not isinstance(end, str) or _is_date_only(end) or _is_date_only(start):
        return None
    start_at = datetime.datetime.fromisoformat(start)
    end_at = datetime.datetime.fromisoformat(end)
    if (start_at.tzinfo is None) != (end_at.tzinfo is None):
        return None
    if not datetime.timedelta(0) <= end_at - start_at <= _MAX_SHOW_LENGTH:
        return None
    return local_wall_clock(end, metro_timezone)[1]


def end_time_is_stated(
    end: datetime.time, page_text: str, title: str | None = None, other_titles: Sequence[str] = ()
) -> bool:
    """True when the page's visible text states this clock time, in any common spelling:
    "8:00 pm", "8pm", "8 p.m.", "20:00", "12:00 am" / "midnight" for 00:00.

    D10 as revised under D1 (Ari, October 10, 2026): an end time no page states is a wrong
    value, never acceptable — and platforms such as DICE emit an endDate 3-15 hours after the
    start that the venue never wrote. A JSON-LD end time is kept only when the page says it —
    and, given the event's `title`, only in the text that follows that title (code review round
    2, #7: anywhere on the page, another listing's "11:00 pm" would vouch for a default end of
    23:00). The listing's text runs from its title to the next other title (`other_titles`, the
    page's other events), capped at 300 characters past the title. A title the text doesn't
    contain vouches for nothing.
    """
    text = fold_text(page_text)
    if title is not None:
        key = fold_text(title)[:40]
        at = text.find(key)
        if not key or at < 0:
            return False
        # This listing's own text: from its title to wherever the next listing's title begins
        # (or 300 characters on, whichever is first) — where its date and time line is.
        stop = at + len(key) + 300
        for other in other_titles:
            other_key = fold_text(other)[:40]
            nxt = text.find(other_key, at + len(key)) if other_key and other_key != key else -1
            if nxt >= 0:
                stop = min(stop, nxt)
        text = text[at:stop]
    hour12, minute = end.hour % 12 or 12, f"{end.minute:02d}"
    meridiem = "a" if end.hour < 12 else "p"
    clock = rf"{hour12}(?::{minute})?" if end.minute == 0 else rf"{hour12}:{minute}"
    patterns = [
        rf"(?<![\d:]){clock}\s*{meridiem}\.?m?\.?(?![a-z])",  # 12-hour with a meridiem
        rf"(?<![\d:]){end.hour:02d}:{minute}(?![\d])",  # 24-hour, zero-padded
        rf"(?<![\d:]){end.hour}:{minute}(?!\d)(?!\s*[ap]\.?m)",  # 24-hour, not padded
    ]
    if (end.hour, end.minute) == (0, 0):
        patterns.append(r"\bmidnight\b")
    return any(re.search(p, text) for p in patterns)


def to_structured_show(
    event: dict[str, Any], metro_timezone: str, page_text: str | None = None,
    other_titles: Sequence[str] = (),
) -> StructuredShow:
    """Map one schema.org Event to a StructuredShow.

    `page_text` (the page's visible text) turns on D10's check: an end time the page doesn't
    state near this event's title, before `other_titles` (the page's other event names) take over,
    is dropped. Without it — as in the unit tests of the mapping alone — no check runs.

    Prices: an Offer is an online ticket price, so it goes in admission_advance (D7, decided by
    Ari: a price shown as a "buy" ticket price is the advance price); a price of 0 is an explicit
    "free". No offer leaves all three admission fields null — absence is "not stated", never
    false (requirements-initial.md, Show: Free Admission).
    """
    start = str(event["startDate"])
    show_date, show_time = local_wall_clock(start, metro_timezone)
    # A local 00:00:00 start is how many event plugins write an all-day or untimed event: read it
    # as "no time stated" (a tolerated missing value), not as a show after midnight, which the
    # cutoff below would move to the previous day (code review round 2, #6).
    if show_time == datetime.time(0, 0):
        show_time = None
    # A structured source states the calendar date; a start before the cutoff belongs to the
    # previous night, which is the date the calendar shows it under.
    if show_time is not None and show_time < NIGHT_CUTOFF:
        show_date -= datetime.timedelta(days=1)
    end_time = _end_time(event, metro_timezone, start)
    # D10: keep a structured end time only if the page itself states it (see end_time_is_stated).
    title = html_lib.unescape(str(event.get("name", ""))).strip()
    if end_time is not None and page_text is not None and not end_time_is_stated(
        end_time, page_text, title, other_titles
    ):
        end_time = None
    price = _offer_price(event)
    return StructuredShow(
        title=title,
        date=show_date,
        time=show_time,
        end_time=end_time,
        image_url=_image(event),
        admission_advance=price if price else None,
        admission_day=None,
        free_admission=True if price == 0 else None,
        status=_status(event),
    )
