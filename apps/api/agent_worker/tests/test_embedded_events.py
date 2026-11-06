"""Tests for the embedded-events reader (`agent_worker/sources/embedded_events.py`) and its wiring (C6.1).

Some venue sites (Hook & Ladder is the first) render their listing with Astro: one `<astro-island>`
element carries every event as JSON in its `props` attribute. The page's visible dates can be a day
off (a UTC rendering that a script corrects in the browser), but the embedded events carry the
right ones, with the metro's offset. C6.1 reads them like JSON-LD: code for dates, times and status,
the act splitter for acts (C6.1-D1, C6.1-D2).

How to read it: the page builders (they write Astro's `[0, value]` / `[1, list]` wrapping by hand,
with invented venues and artists) -> finding events -> the start-time rule (C6.1-D3) -> the title
the splitter is shown (C6.1-D8) -> no price, status, end time -> shapes the reader must survive ->
the slug date -> routing (C6.1-D2) -> the route's notes. Expected clock times come from
America/Chicago's 2026 rules (CDT until Sunday November 1, CST after), not from the code under test.
The captured Hook & Ladder page is never read here (see `test_embedded_events_on_real_page.py`).
"""

import datetime
import html as html_lib
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from agent_worker import act_split, extraction, nodes
from agent_worker.sources import embedded_events, jsonld
from agent_worker.tests.test_extraction import fake_client

CHICAGO = "America/Chicago"
FETCHED = datetime.date(2026, 11, 4)

# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def astro(value: Any) -> Any:
    """A value in Astro's island encoding: a list is `[1, [items]]`, an object `[0, {key: encoded}]`,
    anything else `[0, value]`. The shape the real page uses (checked on the captured page)."""
    if isinstance(value, list):
        return [1, [astro(v) for v in value]]
    if isinstance(value, dict):
        return [0, {k: astro(v) for k, v in value.items()}]
    return [0, value]


def island(events: list[dict[str, Any]], key: str = "events") -> str:
    """One `<astro-island>` whose props hold `events` under `key`, HTML-escaped as the site writes it."""
    props = {key: astro(events)}
    return f'<astro-island uid="X" props="{html_lib.escape(json.dumps(props), quote=True)}"></astro-island>'


def page_of(*islands: str, text: str = "Shows") -> str:
    """An HTML page with the given islands and some visible text."""
    return f"<html><body><p>{text}</p>{''.join(islands)}</body></html>"


def event(title: str = "Mara Lind", date: str = "2026-11-06T19:00:00.000-06:00", **extra: Any) -> dict[str, Any]:
    """One embedded event in the site's shape (only the fields the reader may use, plus a slug)."""
    return {
        "title": title,
        "date": date,
        "showSlug": "mara-lind-november-06-2026-100",
        "image": "https://example.test/a.jpg",
        "priceRange": "$20.00",
        "canceledAt": None,
        "performers": [{"name": title, "actType": "headline"}],
        **extra,
    }


def structured(ev: dict[str, Any]) -> jsonld.StructuredShow:
    """An embedded event mapped to a show by the same function the JSON-LD route uses."""
    events = embedded_events.find_events(page_of(island([ev])))
    assert len(events) == 1
    return jsonld.to_structured_show(events[0], CHICAGO)


# ---------------------------------------------------------------------------
# Finding events
# ---------------------------------------------------------------------------


def test_finds_the_events_in_an_island_in_page_order() -> None:
    # Proves: the reader decodes Astro's wrapping and returns one schema.org-shaped dict per event, in
    # document order, so the JSON-LD mapper can run on them unchanged. A reader that returned the
    # raw props would hand `to_structured_show` dicts with no `name` or `startDate`.
    events = embedded_events.find_events(page_of(island([event("A Band"), event("B Band")])))
    assert [e["name"] for e in events] == ["A Band", "B Band"]
    assert all(e["_source"] == "astro-island" for e in events)
    assert events[0]["_slug"] == "mara-lind-november-06-2026-100"


def test_reads_events_whatever_the_prop_is_called() -> None:
    # Proves: the reader keys on the shape (a list of objects with a title and a date), not on the
    # prop's name, so a site that calls the list `shows` is read the same way.
    assert len(embedded_events.find_events(page_of(island([event()], key="shows")))) == 1


def test_skips_islands_it_cannot_read_and_keeps_the_rest() -> None:
    # Proves: one bad island must not cost a page its other events (the rule `jsonld.find_events`
    # follows). Covers: invalid JSON, an Astro type tag the reader does not know, a prop that is not
    # a list of events, and an event with no title or no date.
    broken = '<astro-island props="{not json"></astro-island>'
    unknown_tag = '<astro-island props="{&quot;events&quot;:[9,[]]}"></astro-island>'
    not_events = f'<astro-island props="{html_lib.escape(json.dumps({"menu": [1, [[0, "Lunch"]]]}))}"></astro-island>'
    no_title = {k: v for k, v in event().items() if k != "title"}
    no_date = {k: v for k, v in event("Dateless").items() if k != "date"}
    html = page_of(broken, unknown_tag, not_events, island([no_title, no_date, event("Kept")]))
    assert [e["name"] for e in embedded_events.find_events(html)] == ["Kept"]


def test_a_page_with_no_island_has_no_events() -> None:
    # Proves: a page without an island yields nothing and never raises (most venues).
    assert embedded_events.find_events("<html><body>Hello</body></html>") == []


# ---------------------------------------------------------------------------
# The start time and what a timestamp means (C6.1-D3)
# ---------------------------------------------------------------------------


def test_a_start_time_wins_over_the_listed_date() -> None:
    # Proves (C6.1-D3, Ari's rule 1): when the event has a `startTime`, that is the start. The listed
    # `date` here is the doors (6:30 pm), the start 7:30 pm. Using `date` would store doors, against
    # data-model-initial.md ("time is not when doors open").
    show = structured(event(date="2026-11-06T18:30:00.000-06:00", startTime="2026-11-06T19:30:00.000-06:00"))
    assert (show.date, show.time) == (datetime.date(2026, 11, 6), datetime.time(19, 30))


def test_without_a_start_time_an_evening_date_is_the_start() -> None:
    # Proves (C6.1-D3, rule 2): no `startTime`, and the `date` timestamp points at the evening of
    # the metro's clock, so it is the start.
    show = structured(event(date="2026-11-06T20:00:00.000-06:00"))
    assert (show.date, show.time) == (datetime.date(2026, 11, 6), datetime.time(20, 0))


def test_a_date_at_midnight_is_only_a_date() -> None:
    # Proves (C6.1-D3): a timestamp that reads midnight in its own offset is how the feed writes a
    # date, not a show after midnight: no time, and the date is the one written. The failure it
    # prevents: reading it as 00:00 and then as the previous night (A2.1-CR2-6).
    show = structured(event(date="2026-11-06T00:00:00.000-06:00"))
    assert (show.date, show.time) == (datetime.date(2026, 11, 6), None)


def test_a_utc_midnight_is_only_a_date_and_is_not_moved_to_the_previous_evening() -> None:
    # Proves (C6.1-D3): "2026-11-06T00:00:00Z" is the date 6 November. Converting it to Chicago would
    # make it 5 November, 18:00 CST — exactly the one-day error this milestone exists to remove.
    show = structured(event(date="2026-11-06T00:00:00.000Z"))
    assert (show.date, show.time) == (datetime.date(2026, 11, 6), None)


def test_a_utc_evening_is_converted_to_the_metro_clock() -> None:
    # Proves (the generic UTC handling Ari asked for): a start written in UTC converts through
    # `local_wall_clock`. After the November 1 change, 02:00Z on the 6th is 20:00 CST on the 5th.
    show = structured(event(date="2026-11-06T02:00:00.000Z"))
    assert (show.date, show.time) == (datetime.date(2026, 11, 5), datetime.time(20, 0))


def test_a_start_time_at_midnight_falls_back_to_a_date_only() -> None:
    # Proves (C6.1-D3): the midnight rule applies to whichever field is the start, so a feed that
    # fills `startTime` with a bare date reads as "no time stated", never as 00:00.
    show = structured(event(date="2026-11-06T00:00:00.000-06:00", startTime="2026-11-06T00:00:00.000-06:00"))
    assert (show.date, show.time) == (datetime.date(2026, 11, 6), None)


# ---------------------------------------------------------------------------
# What the splitter is shown (C6.1-D8)
# ---------------------------------------------------------------------------


def named(title: str, *support: str) -> str:
    """The title the reader hands the splitter for an event with the given support performers."""
    performers = [{"name": title, "actType": "headline"}] + [{"name": n, "actType": "support"} for n in support]
    return structured(event(title, performers=performers)).title


def test_the_support_line_is_part_of_the_title_the_splitter_sees() -> None:
    # Proves (C6.1-D8): the page prints "with A, B" under the title and the island's `title` omits it;
    # without it the splitter is given a bare event name and the support acts are lost.
    assert named("Winter Weekend", "Ada Fox", "The Moths") == "Winter Weekend with Ada Fox, The Moths"


def test_a_support_act_the_title_already_names_is_not_repeated() -> None:
    # Proves (C6.1-D8): "Mara Lind with The Moths" already names The Moths; adding it again would show
    # the splitter the same act twice.
    assert named("Mara Lind with The Moths", "The Moths") == "Mara Lind with The Moths"


def test_headliners_are_not_taken_from_performers() -> None:
    # Proves (C6.1-D8): the title stays the headliner's; `performers` supplies only the support line.
    # The headliner entry can be a mangled copy of the title (punctuation stripped).
    performers = [{"name": "Mara Lind Moths", "actType": "headline"}]
    assert structured(event("Mara Lind & The Moths", performers=performers)).title == "Mara Lind & The Moths"


# ---------------------------------------------------------------------------
# Price, status, end time, image
# ---------------------------------------------------------------------------


def test_no_price_is_read_from_this_source() -> None:
    # Proves (C6.1-D5): the visible page states no price and the labels hold none, so a price mapped
    # from `priceRange` would score as invented. All three admission fields stay "not stated".
    for price in ("$22.65", "$18.11 to $22.65", "FREE", None):
        show = structured(event(priceRange=price))
        assert (show.admission_advance, show.admission_day, show.free_admission) == (None, None, None)


def test_a_cancelled_event_keeps_its_status() -> None:
    # Proves: `canceledAt` set means cancelled (A2.1-D12), the same as JSON-LD's eventStatus.
    assert structured(event(canceledAt="2026-11-01T10:00:00.000-05:00")).status == "cancelled"
    assert structured(event()).status == "scheduled"


def test_the_image_comes_through() -> None:
    # Proves: the image URL is mapped, as for JSON-LD.
    assert structured(event()).image_url == "https://example.test/a.jpg"


def test_an_end_time_is_read_but_dropped_when_the_page_does_not_state_it() -> None:
    # Proves (C6.1-D4): `endTime` goes through the JSON-LD rules unchanged. Plausible (4 h after the
    # start) so kept by the mapper; A2.1-D10 then drops it unless the visible text states it.
    ev = event(
        date="2026-11-06T18:30:00.000-06:00",
        startTime="2026-11-06T19:30:00.000-06:00",
        endTime="2026-11-06T22:30:00.000-06:00",
    )
    events = embedded_events.find_events(page_of(island([ev])))
    assert jsonld.to_structured_show(events[0], CHICAGO).end_time == datetime.time(22, 30)
    assert jsonld.to_structured_show(events[0], CHICAGO, "Mara Lind doors 6:30 pm").end_time is None


# ---------------------------------------------------------------------------
# The slug's date (C6.1-D6)
# ---------------------------------------------------------------------------


def test_slug_date_reads_the_date_a_slug_names() -> None:
    # Proves (C6.1-D6): the venue's own URL names the local date in words; the expected dates are
    # written by hand from the slugs, which is how Hook & Ladder writes them.
    assert embedded_events.slug_date("paul-cebar-tomorrow-sound-november-06-2026-730408") == datetime.date(2026, 11, 6)
    assert embedded_events.slug_date("a-b-c-january-24-2027-9") == datetime.date(2027, 1, 24)


def test_slug_date_is_none_for_a_slug_without_one() -> None:
    # Proves (C6.1-D6): a slug that names no date (or an impossible one) gives None, so the check
    # stays silent rather than guessing.
    assert embedded_events.slug_date("just-a-title-123") is None
    assert embedded_events.slug_date("band-february-30-2026-1") is None
    assert embedded_events.slug_date(None) is None


# ---------------------------------------------------------------------------
# Routing (C6.1-D1, C6.1-D2)
# ---------------------------------------------------------------------------


def one_act(name: str) -> Any:
    """A fake model client whose act splitter answers that the single listing is one act, `name`."""
    return fake_client(
        split_answer=act_split.ActSplitAnswer(
            items=[
                act_split.ActSplitItem(id=0, title=name, acts=[name]),
            ]
        )
    )


def jsonld_block(name: str) -> str:
    """A page fragment carrying one JSON-LD Event."""
    ev = {"@type": "Event", "name": name, "startDate": "2026-11-07T20:00:00-06:00"}
    return f'<script type="application/ld+json">{json.dumps(ev)}</script>'


def test_json_ld_wins_when_a_page_has_both() -> None:
    # Proves (C6.1-D2): the same events appear twice on such a page; one source avoids duplicates and
    # keeps every JSON-LD page exactly as it was measured. The events are tagged with their source.
    events = extraction.usable_events(page_of(jsonld_block("Ld Band"), island([event("Island Band")])))
    assert [(e["name"], e["_source"]) for e in events] == [("Ld Band", "json-ld")]


def test_an_island_alone_makes_the_page_usable() -> None:
    # Proves (C6.1-D2): with no JSON-LD the embedded events are the structured source.
    events = extraction.usable_events(page_of(island([event("Island Band")])))
    assert [(e["name"], e["_source"]) for e in events] == [("Island Band", "astro-island")]


def test_a_page_with_neither_still_goes_to_the_model() -> None:
    # Proves: a page with no structured events is unchanged, and route and extraction agree because
    # both go through `usable_events`.
    assert extraction.usable_events("<html><body>Hi</body></html>") == []


def test_a_script_shell_with_only_an_island_is_not_nothing_to_read() -> None:
    # Proves (C6.1-PR1-6): the fetch's empty-page guard must not reject a page whose only content is
    # an island; the structured route can serve it, exactly as for a JSON-LD shell.
    shell = "<html><body>" + island([event()]) + "</body></html>"
    assert extraction.clean_text(shell, False).strip() == ""
    assert nodes._nothing_to_read(shell) is False


def test_the_route_is_structured_and_the_notes_name_the_source_and_slugs() -> None:
    # Proves (C6.1-D1): an island-only page takes the structured route (named for what it does, not
    # for JSON-LD), the notes say which reader supplied the events, and the slugs are kept in show
    # order for the date cross-check.
    html = page_of(island([event("Ada Fox")]))
    client = one_act("Ada Fox")
    result = extraction.extract_page(
        html,
        venue_name="The Hook",
        metro_timezone=CHICAGO,
        fetch_date=FETCHED,
        client=client,
        options=extraction.PIPELINE_OPTIONS,
        config=replace(extraction.PIPELINE_CONFIG, route="auto"),
    )
    assert result.source == "structured"
    assert result.notes["structured_source"] == "astro-island"
    assert result.notes["slugs"] == ["mara-lind-november-06-2026-100"]
    assert [s.date for s in result.extraction.shows] == [datetime.date(2026, 11, 6)]


def test_json_ld_pages_report_json_ld_as_their_source() -> None:
    # Proves (C6.1-D1): the new note is set on the existing source too, so an audit can tell the two apart.
    client = one_act("Ada Fox")
    result = extraction.extract_page(
        page_of(jsonld_block("Ada Fox")),
        venue_name="V",
        metro_timezone=CHICAGO,
        fetch_date=FETCHED,
        client=client,
        options=extraction.PIPELINE_OPTIONS,
        config=replace(extraction.PIPELINE_CONFIG, route="auto"),
    )
    assert result.source == "structured"
    assert result.notes["structured_source"] == "json-ld"
    assert "slugs" not in result.notes


def test_a_midnight_start_time_with_an_evening_date_uses_the_date() -> None:
    # Proves (C6.1-D3, C6.1-CR1-3): a `startTime` that reads midnight states no time, so rule 2 applies and the
    # evening `date` is the start. Without this a feed that fills `startTime` with a bare date would lose a real time.
    show = structured(event(date="2026-11-06T18:30:00.000-06:00", startTime="2026-11-06T00:00:00.000-06:00"))
    assert (show.date, show.time) == (datetime.date(2026, 11, 6), datetime.time(18, 30))


def test_when_both_are_midnight_the_date_field_names_the_day() -> None:
    # Proves (C6.1-CR1-3): with both at midnight the date-only fallback takes `date`'s written day, never
    # `startTime`'s, and never converts. Here `startTime` is a day later and in UTC, and is ignored.
    show = structured(event(date="2026-11-06T00:00:00.000-06:00", startTime="2026-11-07T00:00:00.000Z"))
    assert (show.date, show.time) == (datetime.date(2026, 11, 6), None)


def test_route_for_agrees_with_the_extraction_route() -> None:
    # Proves (C6.1-CR1-4): `nodes._route_for` (which records the route an attempt used even when it fails) says
    # "structured" for an island-only page and "model" for a page with no events, the same decision `extract_page` makes.
    from agent_worker.state import VenueGraphState

    def route(html: str) -> str:
        state = VenueGraphState(
            venue_id=1, venue_name="V", calendar_url="https://v.example/", metro_timezone=CHICAGO, page_html=html
        )
        return nodes._route_for(state, SimpleNamespace(config=replace(extraction.PIPELINE_CONFIG, route="auto")))  # type: ignore[arg-type]

    assert route(page_of(island([event()]))) == "structured"
    assert route("<html><body>Hi</body></html>") == "model"
