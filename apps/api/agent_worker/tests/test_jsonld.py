"""Tests for the schema.org JSON-LD reader (`agent_worker/sources/jsonld.py`).

The JSON-LD route (A2.1-D4 of docs/dev/implementations/a2.1-extraction-reliability.md) reads a
venue's own structured event data instead of asking a model to read the page. Field names are
schema.org's published vocabulary, so they are mapped in code; what varies between sites is
the *shape* (an object or a list, `image` as a string or an object, `Z` or an offset), and
that is what these tests pin.

How to read it: sections run finding events -> wall-clock conversion (A2.1-K1) ->
mapping one event to a show. The HTML snippets are written here in the shapes the saved
fixtures actually use (White Squirrel: a list block with `-05:00` offsets and HTML entities in
names; DICE-backed pages: `Z` times and `offers`). Fixtures themselves are never read (they
are git-ignored and absent in CI). Expected times come from America/Chicago's 2026 rules (CDT,
UTC-5, until Sunday November 1; CST, UTC-6, after), not from the code.
"""

import datetime
import json
from typing import Any

import pytest

from agent_worker.sources import jsonld

CHICAGO = "America/Chicago"


def page(*blocks: Any, raw: str = "") -> str:
    """An HTML page whose <head> carries each block as its own ld+json script, plus any raw
    extra markup (used to slip an unparseable block in between good ones)."""
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks
    )
    return f"<html><head>{scripts}{raw}</head><body><p>Visible text</p></body></html>"


def event(name: str = "Lent w. Gills, Boomdagger", **extra: Any) -> dict[str, Any]:
    """A minimal schema.org Event; keyword args override or add. The default start is
    date-only so the mapping tests (names, images, prices, status) don't depend on the
    wall-clock conversion, which is A2.1-K1 and is tested on its own."""
    base = {"@type": "Event", "name": name, "startDate": "2026-08-20"}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Finding events
# ---------------------------------------------------------------------------


def test_events_are_found_in_every_shape_the_fixtures_use() -> None:
    # Proves: a single-object block, a list block, an @graph, and @type given as a list
    # (with a subtype like MusicEvent) are all read; WebSite / Restaurant are not events.
    # White Squirrel uses a list block plus an @graph of WebSite/CollectionPage; Zhora's
    # browser capture uses one MusicEvent object per block.
    html = page(
        event("Single object"),
        [event("In a list"), {"@type": "WebSite", "name": "Site"}],
        {"@context": "https://schema.org", "@graph": [event("In a graph"), {"@type": "Restaurant"}]},
        event("Typed as a list", **{"@type": ["Event", "MusicEvent"]}),
        event("A subtype", **{"@type": "MusicEvent"}),
    )
    names = [e["name"] for e in jsonld.find_events(html)]
    assert names == ["Single object", "In a list", "In a graph", "Typed as a list", "A subtype"]


def test_an_unparseable_block_is_skipped_not_fatal() -> None:
    # Proves: one malformed block can't cost a page its other events, and document order is
    # kept (the splitter and the eval both rely on it).
    bad = '<script type="application/ld+json">{"@type": "Event", "name": </script>'
    html = page(event("First"), raw=bad + page(event("Second")))
    assert [e["name"] for e in jsonld.find_events(html)] == ["First", "Second"]


def test_a_page_without_json_ld_has_no_events() -> None:
    # Proves: the common case (Terminal Bar, Mortimer's, 7th St Entry) returns nothing, so
    # routing falls back to the model route.
    assert jsonld.find_events("<html><body>Friday October 2nd Griffin / Alec C</body></html>") == []


# ---------------------------------------------------------------------------
# Wall clock: convert, don't drop (A2.1-K1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected_date", "expected_time"),
    [
        # White Squirrel's own form: an offset that is already Chicago's.
        ("2026-08-17T18:00:00-05:00", datetime.date(2026, 8, 17), datetime.time(18, 0)),
        # DICE's form: UTC. 23:00Z in August is 18:00 CDT.
        ("2026-08-17T23:00:00Z", datetime.date(2026, 8, 17), datetime.time(18, 0)),
        # After the Nov 1 change a UTC evening is the PREVIOUS local day: 02:00Z = 20:00 CST.
        ("2026-11-06T02:00:00Z", datetime.date(2026, 11, 5), datetime.time(20, 0)),
        # No offset: already local wall clock.
        ("2026-10-09T21:00:00", datetime.date(2026, 10, 9), datetime.time(21, 0)),
    ],
)
def test_local_wall_clock_converts_offsets_into_the_metro_zone(
    value: str, expected_date: datetime.date, expected_time: datetime.time
) -> None:
    # Proves: a structured source's offset is information and is CONVERTED into the metro's
    # zone (A2-D3: only a model's zone suffix is noise to drop) — across a DST
    # boundary, and including the date change a UTC evening carries.
    result_date, result_time = jsonld.local_wall_clock(value, CHICAGO)
    assert result_date == expected_date
    assert result_time == expected_time
    assert result_time is not None and result_time.tzinfo is None


def test_a_date_only_start_has_no_time() -> None:
    # Proves: "2026-10-09" is a date with no stated time, not a show at midnight
    # (`datetime.fromisoformat` would read it as 00:00, which A2.1-D1 would score as invented).
    assert jsonld.local_wall_clock("2026-10-09", CHICAGO) == (datetime.date(2026, 10, 9), None)


# ---------------------------------------------------------------------------
# One event -> one structured show
# ---------------------------------------------------------------------------


def test_a_white_squirrel_event_maps_to_a_show() -> None:
    # Proves: the common case end to end, with the past-midnight end White Squirrel really
    # lists ("9:00 pm - 12:00 am"): the end keeps its clock time, its date is ignored.
    show = jsonld.to_structured_show(
        event(
            "Nona",
            startDate="2026-08-17T21:00:00-05:00",
            endDate="2026-08-18T00:00:00-05:00",
            image="https://whitesquirrelbar.com/wp-content/uploads/nona.png",
        ),
        CHICAGO,
    )
    assert show.title == "Nona"
    assert show.date == datetime.date(2026, 8, 17)
    assert show.time == datetime.time(21, 0)
    assert show.end_time == datetime.time(0, 0)
    assert show.image_url == "https://whitesquirrelbar.com/wp-content/uploads/nona.png"
    assert show.status == "scheduled"


def test_an_end_more_than_six_hours_after_the_start_is_not_taken() -> None:
    # Proves: A2.1-D10. DICE-backed pages emit endDates 3-15 hours after the start that no page
    # states; 15 hours is invented, so end_time stays null ("leave blank if unclear").
    show = jsonld.to_structured_show(
        event(startDate="2026-09-05T01:00:00Z", endDate="2026-09-05T16:00:00Z"), CHICAGO
    )
    assert show.end_time is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Martin Devaney &#038; Friends", "Martin Devaney & Friends"),
        ("Aaron James w. Bury &#8216;Em Deep", "Aaron James w. Bury ‘Em Deep"),
    ],
)
def test_names_are_html_unescaped(raw: str, expected: str) -> None:
    # Proves: the entities White Squirrel's JSON-LD really carries don't reach act names.
    assert jsonld.to_structured_show(event(raw), CHICAGO).title == expected


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("https://x.example/a.png", "https://x.example/a.png"),
        (["https://x.example/a.png", "https://x.example/b.png"], "https://x.example/a.png"),
        ({"@type": "ImageObject", "url": "https://x.example/a.png"}, "https://x.example/a.png"),
        (None, None),
    ],
)
def test_image_shapes(image: Any, expected: str | None) -> None:
    # Proves: `image` as a string, a list or an ImageObject all yield one URL; absent is null.
    extra = {} if image is None else {"image": image}
    assert jsonld.to_structured_show(event(**extra), CHICAGO).image_url == expected


@pytest.mark.parametrize(
    ("offers", "advance", "free"),
    [
        ({"@type": "Offer", "price": 15.24}, 15.24, None),
        ([{"@type": "Offer", "price": "12.70"}], 12.7, None),
        ({"@type": "Offer", "price": 0}, None, True),
        (None, None, None),
    ],
)
def test_offer_prices(offers: Any, advance: float | None, free: bool | None) -> None:
    # Proves: an offer is an online ticket price, so it goes in admission_advance (A2.1-D7); a
    # zero price is explicitly free; no offer leaves every admission field null — absence
    # is "not stated", never false (requirements-initial.md, Show: Free Admission).
    extra = {} if offers is None else {"offers": offers}
    show = jsonld.to_structured_show(event(**extra), CHICAGO)
    assert show.admission_advance == advance
    assert show.admission_day is None
    assert show.free_admission is free


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("https://schema.org/EventCancelled", "cancelled"),
        ("EventPostponed", "postponed"),
        ("https://schema.org/EventScheduled", "scheduled"),
        (None, "scheduled"),
    ],
)
def test_event_status_maps_to_show_status(status: str | None, expected: str) -> None:
    # Proves: A2.1-D12 on the deterministic route. A cancelled show is kept, with its status, so
    # reconcile can match and update the stored record.
    extra = {} if status is None else {"eventStatus": status}
    assert jsonld.to_structured_show(event(**extra), CHICAGO).status == expected


def test_a_space_separated_date_time_is_a_time_not_a_date() -> None:
    # Proves: A2.1-CR1-6a. ISO 8601 allows a space instead of "T"; it must not take the
    # date-only branch (which would raise and fail the page).
    assert jsonld.local_wall_clock("2026-10-09 21:00:00", CHICAGO) == (
        datetime.date(2026, 10, 9), datetime.time(21, 0)
    )


@pytest.mark.parametrize(
    ("end", "page_text", "stated"),
    [
        (datetime.time(20, 0), "Monday August 17 @ 6:00 pm - 8:00 pm", True),  # White Squirrel's form
        (datetime.time(0, 0), "Monday August 17 @ 9:00 pm - 12:00 am", True),  # midnight
        (datetime.time(2, 0), "10pm - 2am", True),
        (datetime.time(23, 30), "doors 19:00, ends 23:30", True),
        (datetime.time(22, 0), "Mon 17 Aug ― 6:00pm / Buy now $15.24", False),  # DICE: no end stated
        (datetime.time(20, 0), "6:00 pm - 8:30 pm", False),  # a different end
        (datetime.time(20, 0), "18:00 - 20:00", True),
    ],
)
def test_an_end_time_counts_as_stated_only_if_the_page_text_says_it(
    end: datetime.time, page_text: str, stated: bool
) -> None:
    # Proves: A2.1-D10 as revised under A2.1-D1 (Ari, October 10). A structured end time no page states
    # is a wrong value, never acceptable; so the reader keeps an endDate only when the visible
    # text states that clock time, in any of the common spellings. White Squirrel's real end
    # times pass; DICE's platform defaults (3-15 hours after the start) don't.
    assert jsonld.end_time_is_stated(end, page_text) is stated


def test_an_unstated_json_ld_end_time_is_dropped() -> None:
    # Proves: the check is applied when page text is given, and an end the page states is kept.
    ev = event("Nona", startDate="2026-08-17T18:00:00-05:00", endDate="2026-08-17T20:00:00-05:00")
    assert jsonld.to_structured_show(ev, CHICAGO, page_text="Nona 6:00 pm - 8:00 pm").end_time == datetime.time(20, 0)
    assert jsonld.to_structured_show(ev, CHICAGO, page_text="Nona 6:00 pm").end_time is None


@pytest.mark.parametrize(
    ("start", "night", "time"),
    [
        # A 1:00 AM start on the calendar's Oct 11 is Oct 10's night (Ari, Oct 11: 5:00 AM cutoff).
        ("2026-10-11T01:00:00-05:00", datetime.date(2026, 10, 10), datetime.time(1, 0)),
        # 4:59 AM is still the previous night; 5:00 AM is the new day.
        ("2026-10-11T04:59:00-05:00", datetime.date(2026, 10, 10), datetime.time(4, 59)),
        ("2026-10-11T05:00:00-05:00", datetime.date(2026, 10, 11), datetime.time(5, 0)),
        # A UTC start converted into the zone first: 06:30Z on Oct 11 is 1:30 AM CDT -> Oct 10's night.
        ("2026-10-11T06:30:00Z", datetime.date(2026, 10, 10), datetime.time(1, 30)),
        # An ordinary evening show is unaffected.
        ("2026-10-10T21:00:00-05:00", datetime.date(2026, 10, 10), datetime.time(21, 0)),
    ],
)
def test_a_start_after_midnight_belongs_to_the_previous_night(
    start: str, night: datetime.date, time: datetime.time
) -> None:
    # Proves: requirements-initial.md (Show, "Times after midnight"), decided by Ari on October 11,
    # 2026 — a show belongs to the night the venue lists it under, and a time before 5:00 AM is
    # after midnight of that night. A structured source states the CALENDAR date, so the reader
    # moves a pre-5 AM start back to its night; the clock time is kept.
    show = jsonld.to_structured_show(event(startDate=start), CHICAGO)
    assert (show.date, show.time) == (night, time)


def test_a_local_midnight_start_means_no_time_stated() -> None:
    # Proves: A2.1-CR2-6 — many event plugins write T00:00:00 for an all-day or
    # untimed event. Read as a real start, the 5:00 AM cutoff would move it to the previous day
    # (a missed show plus an invented one); read as "no time stated", the date is kept and the
    # time is a tolerated missing value.
    show = jsonld.to_structured_show(event(startDate="2026-10-09T00:00:00-05:00"), CHICAGO)
    assert (show.date, show.time) == (datetime.date(2026, 10, 9), None)


def test_an_end_time_must_be_stated_near_its_own_title() -> None:
    # Proves: A2.1-CR2-7 — a platform-default end time is not "stated" just because
    # some other listing on the page shows that clock time: the check looks only at the text that
    # follows the event's own title, up to the next event's title (the page's event names are
    # passed in, as `_from_jsonld` does).
    ev = event("Band A", startDate="2026-10-09T19:00:00-05:00", endDate="2026-10-09T23:00:00-05:00")
    names = ["Band A", "Band B"]
    other = "Band A Friday 7:00 pm. Band B Friday 11:00 pm."
    own = "Band A Friday 7:00 pm - 11:00 pm. Band B Saturday 8:00 pm."
    assert jsonld.to_structured_show(ev, CHICAGO, page_text=other, other_titles=names).end_time is None
    assert jsonld.to_structured_show(ev, CHICAGO, page_text=own, other_titles=names).end_time == datetime.time(23, 0)
    # A title the page text doesn't contain vouches for nothing.
    assert jsonld.to_structured_show(ev, CHICAGO, page_text="Band C 11:00 pm", other_titles=names).end_time is None


@pytest.mark.parametrize(
    ("name", "status"),
    [("CANCELLED: Robert Ellis", "cancelled"), ("Baby Bugs (Postponed)", "postponed"), ("Lent", "scheduled")],
)
def test_a_status_written_in_the_title_counts_on_the_json_ld_route(name: str, status: str) -> None:
    # Proves: A2.1-CR2-8 — a site that writes "CANCELLED" in the event's name but
    # leaves eventStatus at Scheduled (or absent) still gets the right status (A2.1-D12: a wrong
    # status is never acceptable).
    assert jsonld.to_structured_show(event(name), CHICAGO).status == status
