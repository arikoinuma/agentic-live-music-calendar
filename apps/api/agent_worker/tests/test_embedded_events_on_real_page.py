"""The embedded-events reader on the real Hook & Ladder page (C6.1), as a replay with no model.

What this is: the captured page `model_eval/captured_pages/hook_ladder-2026-11-04.html` is where the
problem was found (its visible dates are a day late for evening shows; its embedded events are right).
Like `test_validation_on_real_pages.py` it skips where the capture is absent (it is gitignored, so CI
never runs it) and needs no model: the act splitter is not called, only the code that reads dates,
times, status and the route.

How to read it: the reader's events against the hand-written labels (`labels.py`, which Ari wrote
from the live site, not from this code) -> the route and the verdict validation would give.
"""

import datetime
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent_worker import extraction, nodes, policy, validation
from agent_worker.extraction import clean_text
from agent_worker.model_eval import capture, labels
from agent_worker.schemas import ShowExtraction, VenuePageExtraction
from agent_worker.sources import embedded_events, jsonld
from agent_worker.state import VenueGraphState

PAGE_NAME = "hook_ladder-2026-11-04.html"
CHICAGO = "America/Chicago"
FETCHED = datetime.date(2026, 11, 4)

_PATH = capture.CAPTURED_PAGES_DIR / PAGE_NAME
pytestmark = pytest.mark.skipif(not _PATH.exists(), reason="the captured Hook & Ladder page is not on this machine")


def read_events() -> list[dict[str, object]]:
    return embedded_events.find_events(_PATH.read_text())


def test_the_reader_finds_every_event_and_the_labeled_dates() -> None:
    # Proves (C6.1): 41 events are on the page (counted by the plan reviewer from the island), and
    # every labeled show's date is one an embedded event carries. The expected dates come from Ari's
    # labels, written from the live site — not from this reader and not from the page's visible text,
    # which is the part that is wrong.
    events = read_events()
    assert len(events) == 41
    shows = [jsonld.to_structured_show(e, CHICAGO) for e in events]
    for labeled in labels.PAGE_LABELS[PAGE_NAME].shows:
        # The label's first act is a name the event's title contains (the event name may come first, as in
        # 'Sleepy Weekend with ...'), so pair on date AND that name, not on the date alone.
        first = labeled.acts[0].lower()
        same = [s for s in shows if s.date == labeled.date and first in s.title.lower()]
        assert same, f"{labeled.date} {labeled.acts[0]!r} has no embedded event"


def test_the_start_time_is_the_start_time_not_the_doors() -> None:
    # Proves (C6.1-D3): Paul Cebar & Tomorrow Sound is listed at 6:30 pm (doors) with a startTime of
    # 7:30 pm. The expected 19:30 is what the page's data says the show starts, by Ari's rule (use
    # startTime when present). The label still holds the printed 6:30 pm; relabeling is Ari's.
    events = [e for e in read_events() if str(e["name"]).startswith("Paul Cebar")]
    show = jsonld.to_structured_show(events[0], CHICAGO)
    assert (show.date, show.time) == (datetime.date(2026, 11, 6), datetime.time(19, 30))


def test_a_support_line_reaches_the_splitter() -> None:
    # Proves (C6.1-D8): Sleepy Weekend prints its nine acts in a "with" line the island's title lacks;
    # the reader's title includes them, so the splitter can return them.
    titles = [str(e["name"]) for e in read_events()]
    sleepy = next(t for t in titles if t.startswith("Sleepy Weekend"))
    assert "Sleeping Jesus" in sleepy and "DJ Sumthyn Sumthyn" in sleepy


def test_the_page_takes_the_structured_route_and_validation_does_not_send_it_to_the_model() -> None:
    # Proves (C6.1-D1, C6.1-D10, C6.1-PR1-1): the page routes as structured, and the visible (shifted)
    # dates do not make validation fail the attempt, so `route_falls_back` is false. Before the fix the
    # page named 10 upcoming dates with no event and the policy handed attempts 2 and 3 to the model.
    html = _PATH.read_text()
    events = extraction.usable_events(html)
    assert events and events[0]["_source"] == "astro-island"
    state = VenueGraphState(venue_id=1, venue_name="The Hook & Ladder", calendar_url="https://v.example/", metro_timezone=CHICAGO, page_html=html)
    assert nodes._route_for(state, SimpleNamespace(config=replace(extraction.PIPELINE_CONFIG, route="auto"))) == "structured"  # type: ignore[arg-type]
    shows = [jsonld.to_structured_show(e, CHICAGO) for e in events]
    page = VenuePageExtraction(page_readable=True, shows=[
        ShowExtraction.model_validate({
            "venue": "The Hook & Ladder", "date": s.date, "time": s.time, "end_time": None,
            "acts": [{"name": s.title}], "is_ambiguous": False, "confidence": 1.0, "status": s.status,
        }) for s in shows
    ])
    notes = {
        "structured_source": "astro-island", "titles": [s.title for s in shows],
        "slugs": [e.get("_slug") for e in events],
    }
    result, _ = validation.validate_extraction(
        page, source="structured", notes=notes, fetched_on=FETCHED, page_html=html,
        page_text=clean_text(html, keep_line_breaks=False),
    )
    assert validation.CheckCode.JSONLD_UNDER_REPORTED not in [f.code for f in result.findings]
    assert validation.CheckCode.SLUG_DATE_DISAGREES not in [f.code for f in result.findings]
    assert (result.visible_unmatched_dates or 0) >= 3  # the shift is real, and recorded rather than ignored
    verdict = policy.combine(result, policy.RetryPolicy())
    assert verdict.verdict is validation.Verdict.PASSED  # the attempt passes: it is not sent to the model route
    record = policy.AttemptRecord(
        attempt=1, tier="primary", model="m", route="structured", error=None, verdict=validation.Verdict.PASSED,
        reasons=verdict.reasons, findings=verdict.errors, confidence=None, error_count=len(verdict.errors),
        warning_count=len(verdict.warnings),
    )
    assert not policy.route_falls_back(record)
