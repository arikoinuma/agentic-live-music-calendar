"""Read the events a venue page embeds in its own markup (an Astro `<astro-island>`), instead of asking a model to read the page.

Hook & Ladder's site is the first one that needs this (C6.1, `docs/dev/implementations/c6.1-embedded-events-reader.md`).
The page the worker fetches shows each evening show's date one day late in its visible text (a UTC
rendering that a script corrects in the live browser), so no model can read the right date from that text.
The same page carries the right ones, with the metro's offset, in one `<astro-island>` element whose `props`
attribute holds every event as JSON, and in each event's URL slug (`...-november-06-2026-730408`).

This is the second source for the structured route that `sources/jsonld.py` started (C6.1-D1): it returns events
in schema.org's shape (`name`, `startDate`, `endDate`, `image`, `eventStatus`), so `jsonld.to_structured_show`
maps them unchanged, and `jsonld.local_wall_clock` is still the one place a timestamp with an offset or a `Z`
becomes the metro's clock (A2.1-K1). A model is still needed for one thing: which acts a title names.

What it does not do, on purpose: it reads no price (C6.1-D5: the visible page states none and the labels hold none),
and it does not use `performers` as the acts list (C6.1-D8: only the support names are added to the title, because
the page prints them and the island's `title` omits them).

If the island's shape is not one this module understands it returns nothing, and the page falls back to the
model route, which is the behaviour before C6.1. That is quiet by design; the slug cross-check
(`validation.check_slug_dates`) and the evaluation are what would show the old date errors coming back.

How to read it: `find_events` (island -> events) -> `_decode` (Astro's wrapping) -> `_event` (one item -> one
schema.org-shaped dict, with the start-time rule of C6.1-D3) -> `slug_date`.
"""

import calendar
import datetime
import json
import re
from typing import Any

from bs4 import BeautifulSoup

from agent_worker.normalize import fold_text

SOURCE = "astro-island"


class _UnknownEncoding(ValueError):
    """An Astro value type this reader does not know (dates, maps, sets, ...): the island is skipped."""


def _decode(value: Any) -> Any:
    """Undo Astro's island encoding: `[0, v]` is a value (an object's members are encoded too) and
    `[1, [...]]` a list. Any other type tag raises, so an island holding something unfamiliar is skipped
    whole rather than half-read."""
    if not isinstance(value, list) or len(value) != 2:
        raise _UnknownEncoding(f"not an encoded value: {value!r}")
    tag, payload = value
    if tag == 0:
        if isinstance(payload, dict):
            return {key: _decode(member) for key, member in payload.items()}
        return payload
    if tag == 1 and isinstance(payload, list):
        return [_decode(item) for item in payload]
    raise _UnknownEncoding(f"unknown type tag {tag!r}")


def _parse(value: Any) -> datetime.datetime | None:
    """An ISO date-time as written, or None if it is not one."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def _start(item: dict[str, Any]) -> str | None:
    """The start, as a string `jsonld.local_wall_clock` can read (C6.1-D3, Ari's rule).

    `startTime` if the event has one; otherwise the listed `date`, but only when it points at a time: a
    timestamp is not a start time merely because it is a timestamp. One that reads midnight *in its own
    offset* (`...T00:00:00.000-06:00`, or `...T00:00:00Z`) is how a feed writes a date, so it becomes a
    date-only value (the written calendar date, no time, no conversion). Converting it would move a UTC
    midnight to the previous evening in Chicago, the one-day error this reader exists to remove. A `startTime`
    that reads midnight is skipped like any other non-time; when both fields read midnight the day is `date`'s,
    never `startTime`'s (C6.1-CR1-3).
    """
    for key in ("startTime", "date"):
        parsed = _parse(item.get(key))
        if parsed is not None and parsed.time() != datetime.time(0, 0):
            return str(item[key])
    parsed = _parse(item.get("date"))
    return parsed.date().isoformat() if parsed is not None else None


def _displayed_title(item: dict[str, Any]) -> str:
    """The title as the page shows the listing: the island's `title`, then ` with ` and the support
    performers' names when there are any (C6.1-D8). The visible page prints that line under the title and the
    island's `title` omits it; without it the act splitter would be given a bare event name. A support name the
    title already contains is not repeated."""
    title = str(item["title"]).strip()
    performers = item.get("performers")
    support = (
        [
            str(p["name"]).strip()
            for p in performers
            if isinstance(p, dict)
            and p.get("actType") == "support"
            and isinstance(p.get("name"), str)
            and p["name"].strip()
        ]
        if isinstance(performers, list)
        else []
    )
    folded = fold_text(title)
    new = [name for name in support if fold_text(name) not in folded]
    return f"{title} with {', '.join(new)}" if new else title


def _event(item: dict[str, Any]) -> dict[str, Any] | None:
    """One embedded event as a schema.org-shaped dict, or None if it cannot make a show (no title, or no
    readable start). `_source` and `_slug` are this module's own keys, carried for the route's notes and for the
    slug cross-check."""
    start = _start(item)
    if not isinstance(item.get("title"), str) or not item["title"].strip() or start is None:
        return None
    event: dict[str, Any] = {
        "@type": "Event",
        "name": _displayed_title(item),
        "startDate": start,
        # A cancelled event keeps its status (A2.1-D12), the way JSON-LD's eventStatus does.
        "eventStatus": "https://schema.org/EventCancelled"
        if item.get("canceledAt")
        else "https://schema.org/EventScheduled",
        "_source": SOURCE,
        "_slug": item.get("showSlug") if isinstance(item.get("showSlug"), str) else None,
    }
    if isinstance(item.get("endTime"), str):
        event["endDate"] = item["endTime"]
    if isinstance(item.get("image"), str) and item["image"]:
        event["image"] = item["image"]
    return event


def find_events(html: str) -> list[dict[str, Any]]:
    """Every event embedded in the page's islands, in document order.

    An island's props are a mapping from a name to an encoded value; a value that is a list of objects with a
    string `title` and a string `date` is a list of events, whatever the site calls it. An island that cannot be
    read is skipped, not raised: one bad island must not cost a page its other events.
    """
    soup = BeautifulSoup(html, "html.parser")
    events: list[dict[str, Any]] = []
    for island in soup.find_all("astro-island"):
        try:
            props = _decode([0, json.loads(str(island.get("props") or ""))])
        except (json.JSONDecodeError, _UnknownEncoding):
            continue
        for value in props.values() if isinstance(props, dict) else []:
            if not isinstance(value, list):
                continue
            for item in value:
                if not (
                    isinstance(item, dict) and isinstance(item.get("title"), str) and isinstance(item.get("date"), str)
                ):
                    continue
                if (event := _event(item)) is not None:
                    events.append(event)
    return events


# ---------------------------------------------------------------------------
# The slug's date
# ---------------------------------------------------------------------------

_MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
_SLUG_DATE = re.compile(r"-(" + "|".join(_MONTHS) + r")-(\d{1,2})-(\d{4})(?:-\d+)?$")


def slug_date(slug: str | None) -> datetime.date | None:
    """The local date a venue URL slug names in words (`...-november-06-2026-730408` -> 2026-11-06), or None
    if it names none or an impossible one. The venue wrote this for people, in its own time, so it is evidence
    for `validation.check_slug_dates` that does not depend on any timestamp (C6.1-D6)."""
    match = _SLUG_DATE.search(slug or "")
    if match is None:
        return None
    try:
        return datetime.date(int(match.group(3)), _MONTHS[match.group(1)], int(match.group(2)))
    except ValueError:
        return None
