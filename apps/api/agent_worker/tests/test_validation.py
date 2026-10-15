"""Tests for `agent_worker/validation.py`: the pure checks on an extraction.

Milestone A3 (docs/dev/implementations/a3-validation-and-retry.md, §2). These are the highest-value tests
in the worker: pure functions that encode real business rules, with no model, no database and no
clock — the date is always passed in. They also stand in for the "unit tests for the validation
checks" the build plan filed under A7, pulled forward because tests come first.

How to read it: sections follow the order in validation.py. Every expectation is a literal whose source
is named in the test: the 31/366-day window is plan decision A3-D2, the dates in the "Nona" case are
White Squirrel's own listing ("9:00 pm - 12:00 am", requirements-initial.md Show), the verdict table
is plan §1. Nothing reads its expectation from the code under test. The pages are small synthetic
HTML in the shapes of the fixtures (which are gitignored, so CI has none); the real-page layer is
`test_validation_on_real_pages.py`.
"""

import datetime
from typing import Any

import pytest

from agent_worker import validation
from agent_worker.normalize import infer_year
from agent_worker.schemas import ShowExtraction, VenuePageExtraction
from agent_worker.validation import CheckCode, PageOutcome, Severity, Target

FETCHED = datetime.date(2026, 10, 12)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def show(
    day: datetime.date = datetime.date(2026, 10, 20), *acts: str, time: str | None = None,
    end: str | None = None, **extra: Any,
) -> ShowExtraction:
    """A show naming `acts` (one act "The Band" if none given) on `day`, with the optional fields
    given; confidence 0.9 unless overridden."""
    names = acts if acts else ("The Band",)
    return ShowExtraction.model_validate({
        "venue": "The Venue", "date": day, "time": time, "end_time": end,
        "acts": [{"name": n} for n in names], "is_ambiguous": False, "confidence": 0.9, **extra,
    })


def page(*shows: ShowExtraction, readable: bool = True) -> VenuePageExtraction:
    """A page extraction (readable by default) holding the given shows."""
    return VenuePageExtraction(page_readable=readable, shows=list(shows))


def validate(
    extraction: VenuePageExtraction, *, source: validation.Source = "model", notes: dict[str, Any] | None = None,
    fetched_on: datetime.date = FETCHED, html: str = "", text: str = "",
) -> tuple[validation.ValidationResult, list[ShowExtraction]]:
    """Run `validate_extraction` with defaults for everything a test doesn't care about (the fetch date, no notes, no page)."""
    return validation.validate_extraction(
        extraction, source=source, notes=notes or {}, fetched_on=fetched_on, page_html=html, page_text=text,
    )


def codes(result: validation.ValidationResult, severity: Severity | None = None) -> list[CheckCode]:
    """The codes of a result's findings, optionally only those of one severity."""
    return [f.code for f in result.findings if severity is None or f.severity is severity]


# ---------------------------------------------------------------------------
# Page outcome (A3-Gap-B)
# ---------------------------------------------------------------------------


def test_page_outcome_has_shows() -> None:
    # Proves (A3-Gap-B): a readable page with shows is the normal case.
    assert validation.classify_page(page(show())) is PageOutcome.HAS_SHOWS


def test_page_outcome_confirmed_empty() -> None:
    # Proves (A3-Gap-B): `page_readable` true with no shows is a *confirmed empty* calendar — a
    # legitimate pass, the field's whole reason for existing (G3).
    assert validation.classify_page(page()) is PageOutcome.CONFIRMED_EMPTY


def test_page_outcome_unreadable() -> None:
    # Proves (A3-Gap-B): an unreadable page with no shows is a failure, not an empty calendar.
    assert validation.classify_page(page(readable=False)) is PageOutcome.UNREADABLE


def test_page_outcome_unreadable_wins_over_returned_shows() -> None:
    # Proves (A3-Gap-B): readability is asked first. A model that says "I couldn't read this" and then
    # returns a show anyway is not trusted on the show; testing `shows` first would read it as normal.
    assert validation.classify_page(page(show(), readable=False)) is PageOutcome.UNREADABLE


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------


def test_a_show_with_no_acts_is_excluded_not_failed_and_is_reported() -> None:
    # Proves: "never silently dropped" (requirements, Agent Validation) without failing the page. A
    # show naming no act isn't a show (Show: "Artists — one or more"), and both routes hand these
    # over on purpose (non-music entries), so it is excluded with a warning that names it — not an
    # error, which would retry a page for a karaoke night. Excluded is not "confirmed non-music": the
    # splitter also returns [] for real shows (Mortimer's, two every run in a21-confirm).
    extraction = page(show(), ShowExtraction.model_validate({
        "venue": "The Venue", "date": datetime.date(2026, 10, 21), "acts": [], "is_ambiguous": False, "confidence": 0.9,
    }))
    result, kept = validate(extraction, notes={"titles": ["The Band", "Karaoke Night"]})
    assert result.excluded == [1]
    assert len(kept) == 1
    assert codes(result, Severity.ERROR) == []
    [warning] = [f for f in result.findings if f.code is CheckCode.EXCLUDED_NO_ACTS]
    assert warning.show_index == 1
    assert "Karaoke Night" in warning.message  # the title reaches the record, for a human to look at


def test_a_blank_act_name_is_an_error() -> None:
    # Proves: an act with no name can't become an Artist row; it is an error aimed at the splitter.
    result, _ = validate(page(show(datetime.date(2026, 10, 20), "  ")))
    [finding] = [f for f in result.errors if f.code is CheckCode.BLANK_ACT_NAME]
    assert finding.target is Target.SPLITTER


def test_a_listing_the_splitter_left_out_is_an_error_not_an_exclusion() -> None:
    # Proves: `missing_ids` (a title the splitter's answer skipped) is told apart from a genuine
    # exclusion — act_split.split_titles gives both acts: [], so without this a dropped real show
    # looks like a karaoke night. Source: act_split.py `missing_ids`; A3-PR1-8.
    result, _ = validate(page(show()), notes={"missing_ids": [0]})
    [finding] = [f for f in result.errors if f.code is CheckCode.SPLITTER_DROPPED]
    assert finding.target is Target.SPLITTER and finding.show_index == 0


def test_an_act_not_in_its_title_is_a_warning_not_an_error() -> None:
    # Proves (A2.1-E3): an invented act name is flagged, and flagged only as a warning (the
    # splitter legitimately drops parentheticals and "w." markers, so the guard can't be an error).
    extraction = page(show(datetime.date(2026, 10, 20), "Devilsoundguy"))
    result, _ = validate(extraction, notes={"titles": ["Dave Wilson w. Gills"]})
    assert CheckCode.ACT_NOT_IN_TITLE in codes(result, Severity.WARNING)
    assert result.errors == []


def test_an_act_inside_its_title_raises_nothing() -> None:
    # Proves: the check doesn't fire on a name taken from the title ("w." and a typographic quote
    # folded, as fold_text does everywhere).
    extraction = page(show(datetime.date(2026, 10, 20), "Dave Wilson", "Gills’ Band"))
    result, _ = validate(extraction, notes={"titles": ["Dave Wilson w. Gills' Band"]})
    assert CheckCode.ACT_NOT_IN_TITLE not in codes(result)


def test_the_title_checks_are_skipped_when_titles_and_shows_do_not_line_up() -> None:
    # Proves: the status merge can add a show, so 29 titles against 30 shows (7th St Entry) must not
    # pair the wrong title with a show. Source: round 2 replay of a21-confirm.
    extraction = page(show(datetime.date(2026, 10, 20), "Invented"), show())
    result, _ = validate(extraction, notes={"titles": ["Only One Title"]})
    assert CheckCode.ACT_NOT_IN_TITLE not in codes(result)


def test_when_every_show_is_excluded_a_dated_page_is_not_a_confirmed_empty_pass() -> None:
    # Proves (A3-PR1-4): the empty-page guard keys on *kept* shows, so a dated page whose every
    # show was excluded can't slip past the guard that exists for an empty list.
    extraction = page(ShowExtraction.model_validate({
        "venue": "V", "date": datetime.date(2026, 10, 20), "acts": [], "is_ambiguous": False, "confidence": 0.9,
    }))
    text = "Oct 20 Oct 21 Oct 22 Oct 23 something"
    result, kept = validate(extraction, text=text)
    assert kept == []
    assert CheckCode.EMPTY_BUT_DATED in codes(result, Severity.ERROR)
    assert result.confidence is None  # and min([]) did not raise


def test_when_every_show_is_excluded_an_undated_page_passes_with_no_confidence() -> None:
    # Proves: nothing to commit and nothing dated is not a failure; each excluded show already
    # carries its warning.
    extraction = page(ShowExtraction.model_validate({
        "venue": "V", "date": datetime.date(2026, 10, 20), "acts": [], "is_ambiguous": False, "confidence": 0.9,
    }))
    result, _ = validate(extraction, text="Karaoke night")
    assert result.errors == []
    assert result.confidence is None


# ---------------------------------------------------------------------------
# Plausibility (A3-Gap-C)
# ---------------------------------------------------------------------------


def test_the_date_window_boundaries_on_the_model_route() -> None:
    # Proves (A3-Gap-C): the window is 31 days back to 366 days ahead of the FETCH date (plan A3-D2, from
    # the year rule's lookback and the build plan's "a month past, a year out"). 2026-09-11 is 31
    # days before 2026-10-12 and passes; 09-10 is 32 and fails. 2027-10-13 is 366 ahead and passes;
    # 10-14 is 367 and fails. On the model route an out-of-window date is an error (a retry can re-read).
    for day, bad in [
        (datetime.date(2026, 9, 11), False), (datetime.date(2026, 9, 10), True),
        (datetime.date(2027, 10, 13), False), (datetime.date(2027, 10, 14), True),
    ]:
        result, _ = validate(page(show(day)), source="model")
        assert (CheckCode.DATE_IMPLAUSIBLE in codes(result, Severity.ERROR)) is bad, day


def test_an_out_of_window_json_ld_event_is_excluded_with_a_warning_not_failed() -> None:
    # Proves (A3-D13): on the JSON-LD route the date is the source's own and no retry changes it; the
    # model route's year rule would re-date it into a plausible, wrong date. So the show is left out,
    # visibly, and the page still passes.
    extraction = page(show(datetime.date(2026, 10, 20)), show(datetime.date(2027, 11, 30), "Festival Act"))
    result, kept = validate(extraction, source="jsonld")
    assert result.excluded == [1] and len(kept) == 1
    assert CheckCode.DATE_OUT_OF_WINDOW in codes(result, Severity.WARNING)
    assert result.errors == []


def test_a_feb_29_that_the_year_rule_leaves_alone_is_caught_by_the_window() -> None:
    # Proves: the backstop infer_year names. Its docstring: a Feb 29 in a year with none "returns the
    # date unchanged (A3's plausibility check is the backstop)". The premise is checked first so the
    # test can't pass for the wrong reason.
    unchanged = infer_year(datetime.date(2024, 2, 29), FETCHED)
    assert unchanged == datetime.date(2024, 2, 29)
    result, _ = validate(page(show(unchanged)), source="model")
    assert CheckCode.DATE_IMPLAUSIBLE in codes(result, Severity.ERROR)


def test_an_end_time_earlier_than_the_start_is_the_next_morning_and_raises_nothing() -> None:
    # Proves (A3-Gap-C): White Squirrel lists "Nona ... 9:00 pm - 12:00 am", which extracts correctly as
    # start 21:00, end 00:00 (requirements, Show: "an end time earlier than its start is the next
    # morning"). A naive `end <= start` check would flag or repair a correct record.
    result, kept = validate(page(show(time="21:00", end="00:00")), source="jsonld")
    assert result.findings == [] and result.repairs == []
    assert str(kept[0].end_time) == "00:00:00"


@pytest.mark.parametrize("source", ["jsonld", "model", "image"])
def test_an_end_time_equal_to_the_start_is_dropped_as_a_repair_never_a_failure(source: validation.Source) -> None:
    # Proves (A3-PR2-4): a zero-length show is repaired on every source, not failed and not a reason
    # to change route. jsonld._end_time accepts it and end_time_is_stated is satisfied by the stated
    # *start*, so a plugin that writes endDate == startDate would otherwise fail on every run.
    result, kept = validate(page(show(time="20:00", end="20:00")), source=source)
    assert result.errors == []
    [repair] = result.repairs
    assert repair.field == "end_time" and "equals the start" in repair.reason
    assert kept[0].end_time is None and str(kept[0].time) == "20:00:00"


def test_an_end_time_with_no_start_is_dropped_as_a_repair() -> None:
    # Proves (A3-D4): A2's eval showed the poster route putting a start in `end_time` with `time` null
    # (terminal_bar_show_2, 21:00 on every seed). The code can't know which it is, so it drops the end:
    # missing is tolerated (about 1 in 10), a wrong value never. Not moved into `time` — a guess.
    result, kept = validate(page(show(end="21:00")), source="image")
    [repair] = result.repairs
    assert repair.field == "end_time" and "no start" in repair.reason
    assert kept[0].end_time is None and kept[0].time is None


def test_a_morning_start_is_a_warning_and_an_after_midnight_start_is_not() -> None:
    # Proves: 05:00-10:59 is "unusual for live music" (a likely mis-converted PM) but a warning —
    # brunch music exists — and 01:00 is normal (a time before 05:00 is after midnight of the listed
    # night, requirements Show). Never an error: "when in doubt, include it".
    morning, _ = validate(page(show(time="07:00")))
    late, _ = validate(page(show(time="01:00")))
    assert codes(morning, Severity.WARNING) == [CheckCode.UNUSUAL_START_TIME] and morning.errors == []
    assert late.findings == []


# ---------------------------------------------------------------------------
# Consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("price", [{"admission_advance": 15.0}, {"admission_day": 10.0}])
def test_free_together_with_a_price_is_an_error(price: dict[str, float]) -> None:
    # Proves: requirements, Validation: "Free Admission cannot be true at the same time as an
    # Admission Advance or Admission Day price being set".
    result, _ = validate(page(show(free_admission=True, **price)))
    assert CheckCode.FREE_WITH_PRICE in codes(result, Severity.ERROR)
    # The message is sent to the model as a retry hint, and the model was never shown a "show 0": it
    # names the show by its date (A3-CR1-5a).
    assert "2026-10-20" in next(f for f in result.errors if f.code is CheckCode.FREE_WITH_PRICE).message


def test_free_alone_and_a_price_alone_are_consistent() -> None:
    # Proves: "the absence of a price does not by itself imply free admission" and the converse — a
    # price with free_admission null is fine. Only the contradiction fails.
    free, _ = validate(page(show(free_admission=True)))
    priced, _ = validate(page(show(admission_advance=15.0, admission_day=20.0)))
    assert free.errors == [] and priced.errors == []


# ---------------------------------------------------------------------------
# Repairs: what each source verifies
# ---------------------------------------------------------------------------


def test_an_image_url_on_the_page_is_kept_and_one_that_is_not_is_dropped_and_recorded() -> None:
    # Proves (A2-F6, A3-D4): a poster URL must appear verbatim in the page, or it is dropped — a Repair
    # records it. A model can invent a plausible URL; only the page can vouch for one.
    html = '<img src="https://v.example/uploads/poster.png">'
    kept_url, _ = validate(page(show(image_url="https://v.example/uploads/poster.png")), html=html)
    assert kept_url.repairs == []
    result, kept = validate(page(show(image_url="https://v.example/uploads/made-up.png")), html=html)
    [repair] = result.repairs
    assert repair.field == "image_url" and kept[0].image_url is None


def test_an_image_url_with_an_escaped_ampersand_in_the_page_is_still_verbatim() -> None:
    # Proves: an attribute `src="…?a=1&amp;b=2"` parses to `…?a=1&b=2`, so a naive `url in page_html`
    # is false for a URL copied correctly. The check compares against the unescaped HTML.
    html = '<img src="https://v.example/p.jpg?a=1&amp;b=2">'
    result, kept = validate(page(show(image_url="https://v.example/p.jpg?a=1&b=2")), html=html)
    assert result.repairs == [] and kept[0].image_url is not None


@pytest.mark.parametrize("source", ["jsonld", "image"])
def test_the_image_url_check_runs_on_the_model_route_only(source: validation.Source) -> None:
    # Proves: the URL on a JSON-LD show came from structured data, not a model (the eval's 225
    # "invented" URLs in a21-confirm were all this false alarm), and an image run has no page HTML at
    # all. Checking either would drop every correct URL.
    result, kept = validate(page(show(image_url="https://v.example/from-the-source.png")), source=source)
    assert result.repairs == [] and kept[0].image_url is not None


def test_a_model_route_end_time_the_page_does_not_state_is_dropped() -> None:
    # Proves (A2.1-D10 for the model route): an end time must be one the page states. "8pm - 11pm" in
    # the text vouches for 23:00; "8pm" alone does not.
    stated, _ = validate(page(show(time="20:00", end="23:00")), text="The Band Oct 20 8pm - 11pm")
    unstated, kept = validate(page(show(time="20:00", end="23:00")), text="The Band Oct 20 8pm")
    assert stated.repairs == []
    [repair] = unstated.repairs
    assert "doesn't state" in repair.reason and kept[0].end_time is None


def test_the_end_time_check_is_scoped_to_the_listings_own_title_when_titles_line_up() -> None:
    # Proves (A3-PR1-14): A2.1's own docstring says page-wide lets "another listing's '11:00 pm'
    # vouch for a default end". With titles aligned to shows, Alpha's end of 23:00 is checked only in
    # Alpha's slice of the text (up to Beta's title), where nothing states it; Beta's own is stated.
    text = "Alpha Band Oct 15 8:00 pm Beta Group Oct 16 8:00 pm - 11:00 pm"
    extraction = page(show(datetime.date(2026, 10, 15), "Alpha Band", time="20:00", end="23:00"),
                      show(datetime.date(2026, 10, 16), "Beta Group", time="20:00", end="23:00"))
    result, kept = validate(extraction, text=text, notes={"titles": ["Alpha Band", "Beta Group"]})
    assert [r.show_index for r in result.repairs] == [0]
    assert kept[0].end_time is None and kept[1].end_time is not None
    # Without titles the page-wide check lets Beta's "11:00 pm" vouch for Alpha's end: the weakness.
    wide, _ = validate(extraction, text=text)
    assert wide.repairs == []


def test_a_poster_run_keeps_its_end_time_when_it_has_a_start() -> None:
    # Proves (A3-PR1-6): the image route has no page text, so the page-reading repairs must not run
    # on it — an `source != "jsonld"` implementation would drop every poster's valid end time.
    result, kept = validate(page(show(time="20:00", end="23:00")), source="image")
    assert result.repairs == [] and kept[0].end_time is not None


# ---------------------------------------------------------------------------
# Page-level guards
# ---------------------------------------------------------------------------


def test_upcoming_dates_are_found_in_the_spellings_pages_use() -> None:
    # Proves: "Oct 12", "October 20th" and "Nov. 3" are dates; "Oct 2026" and "Oct 45" are not. Dates
    # before the fetch date (2026-10-12) are ignored, since pages keep past listings and posted-on dates.
    text = "Oct 12 October 20th Nov. 3 Oct 2026 Oct 45 Oct 5"
    assert validation.upcoming_dates(text, FETCHED) == {(10, 12), (10, 20), (11, 3)}


def test_only_the_past_31_days_are_ignored_so_an_older_archive_still_counts() -> None:
    # Proves (A3-PR2-2): "ignored if before the fetch date" is applied after `infer_year` places each
    # pair, which drops only the past 31 days. Aug 1 is more than 31 days before 2026-10-12, so it is
    # placed in 2027 and counts as an upcoming date — accepted, and stated in the module docstring.
    assert validation.upcoming_dates("Sep 20", FETCHED) == set()
    assert validation.upcoming_dates("Aug 1", FETCHED) == {(8, 1)}


def test_json_ld_that_lists_fewer_events_than_the_page_names_is_under_reported() -> None:
    # Proves (A2.1-E16): three or more upcoming dates in the text with no extracted show on them means the
    # structured data is partial. Six dates named, two with shows, four unmatched -> error.
    text = "Oct 20 Oct 21 Oct 22 Oct 23 Oct 24 Oct 25"
    extraction = page(show(datetime.date(2026, 10, 20)), show(datetime.date(2026, 10, 21)))
    on_jsonld, _ = validate(extraction, source="jsonld", text=text)
    on_model, _ = validate(extraction, source="model", text=text)
    assert CheckCode.JSONLD_UNDER_REPORTED in codes(on_jsonld, Severity.ERROR)
    assert CheckCode.JSONLD_UNDER_REPORTED not in codes(on_model)  # a JSON-LD guard, on JSON-LD only


def test_a_json_ld_page_whose_dates_all_have_shows_is_not_under_reported() -> None:
    # Proves: the case both real White Squirrel captures were checked against before this plan was
    # written (5 and 6 dates in the text, each matched by an event): no finding. Excluded shows count
    # as covered — the JSON-LD did list them.
    text = "Oct 20 Oct 21 Oct 22 Oct 23"
    shows = [show(datetime.date(2026, 10, d)) for d in (20, 21, 22)]
    shows.append(ShowExtraction.model_validate({
        "venue": "V", "date": datetime.date(2026, 10, 23), "acts": [], "is_ambiguous": False, "confidence": 1.0,
    }))
    result, _ = validate(page(*shows), source="jsonld", text=text)
    assert CheckCode.JSONLD_UNDER_REPORTED not in codes(result)


def test_an_archive_of_recent_past_dates_is_not_counted_as_under_reporting() -> None:
    # Proves (A3-PR1-20, A3-PR2-2): 7th St Entry's text lists Oct 1-9 against an Oct 10 capture.
    # Dates in the 31 days before the fetch aren't upcoming events, so they can't make a page look
    # under-reported.
    text = "Oct 1 Oct 2 Oct 3 Oct 4 Oct 5"
    result, _ = validate(page(show(datetime.date(2026, 10, 20))), source="jsonld", text=text)
    assert CheckCode.JSONLD_UNDER_REPORTED not in codes(result)


def test_an_empty_list_on_a_page_that_names_dates_is_an_error() -> None:
    # Proves (A3-D10): `page_readable: true, shows: []` is the most dangerous output (A5 would soft-delete
    # every stored show), so it isn't a confirmed-empty pass when the visible text names dates.
    result, _ = validate(page(), text="Oct 20 Oct 21 Oct 22 Oct 23 Oct 24")
    assert CheckCode.EMPTY_BUT_DATED in codes(result, Severity.ERROR)


def test_dates_that_extracted_shows_already_sit_on_do_not_make_a_page_empty_but_dated() -> None:
    # Proves (A3-CR1-1): the empty-page guard compares against every extracted show's
    # date, excluded ones included — exactly as the under-report guard does. A JSON-LD page whose
    # events are all out of window has all of them excluded; their dates are in the text, but the page
    # isn't "empty with dates it ignored", and the guard must not fire on them (it sent such a page to
    # the model route, whose year rule re-dated the shows into a plausible, wrong year).
    text = "Aug 1 Aug 2 Aug 3 Oct 20 Oct 21 Oct 22"
    shown = {(8, 1), (8, 2), (8, 3)}
    assert validation.check_empty_but_dated(text, datetime.date(2026, 10, 12), shown) != []  # Oct 20-22 unmatched
    assert validation.check_empty_but_dated("Aug 1 Aug 2 Aug 3", datetime.date(2026, 10, 12), shown) == []


def test_a_json_ld_page_whose_every_event_is_out_of_window_passes_with_each_exclusion_reported() -> None:
    # Proves (A3-CR1-1; A3-D13): all events stale -> all excluded with a warning each, no
    # `empty_but_dated` error, so no route fallback is triggered. Aug 1-3 2026 against a 2026-10-12 fetch
    # are more than 31 days back, so `upcoming_dates` places them in 2027 and they COUNT as dated text:
    # the guard has to subtract the shows' own dates, not rely on "past dates are ignored".
    # (A3-Gap-C: the window.)
    stale = [show(datetime.date(2026, 8, d), f"Band {d}") for d in (1, 2, 3)]
    result, kept = validate(page(*stale), source="jsonld", text="Band 1 Aug 1 8 pm Band 2 Aug 2 8 pm Band 3 Aug 3 8 pm")
    assert kept == [] and result.excluded == [0, 1, 2]
    assert result.errors == []
    assert [f.code for f in result.warnings] == [CheckCode.DATE_OUT_OF_WINDOW] * 3


def test_an_empty_list_on_a_page_with_no_dates_is_left_alone() -> None:
    # Proves: a genuinely empty calendar ("No events scheduled") raises no finding, so the verdict can
    # be CONFIRMED_EMPTY.
    result, _ = validate(page(), text="No events scheduled. Check back soon.")
    assert result.findings == [] and result.outcome is PageOutcome.CONFIRMED_EMPTY


def test_an_unreadable_page_is_not_also_reported_as_empty_but_dated() -> None:
    # Proves: one reason per fact. An unreadable page fails as unreadable; the empty-page guard is for
    # a page the model claims to have read.
    result, _ = validate(page(readable=False), text="Oct 20 Oct 21 Oct 22 Oct 23")
    assert result.outcome is PageOutcome.UNREADABLE
    assert CheckCode.EMPTY_BUT_DATED not in codes(result)


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def test_confidence_is_the_minimum_over_the_kept_shows_a_model_judged() -> None:
    # Proves (A3-D9): the minimum, not the mean — one doubtful show is the thing to look at. An excluded
    # show's confidence is ignored (it isn't in the record being judged).
    extraction = page(
        show(datetime.date(2026, 10, 20), confidence=0.95), show(datetime.date(2026, 10, 21), confidence=0.7),
        ShowExtraction.model_validate({
            "venue": "V", "date": datetime.date(2026, 10, 22), "acts": [], "is_ambiguous": False, "confidence": 0.1,
        }),
    )
    result, _ = validate(extraction)
    assert result.confidence == pytest.approx(0.7)


def test_json_ld_confidence_is_none_because_its_one_point_zero_is_a_placeholder() -> None:
    # Proves (A3-D9, A2.1-PR1-15): the JSON-LD route stamps `confidence=1.0` on every show,
    # claiming a certainty about acts the splitter doesn't have. It must not read as evidence.
    result, _ = validate(page(show(confidence=1.0)), source="jsonld")
    assert result.confidence is None


def test_shows_the_status_merge_added_are_left_out_of_the_confidence() -> None:
    # Proves (A3-PR2-11): the merge adds shows with a placeholder confidence of 1.0 that no model
    # judged; they are listed in notes["added_indices"] and must not raise the minimum.
    extraction = page(show(datetime.date(2026, 10, 20), confidence=0.6), show(datetime.date(2026, 10, 21), confidence=1.0))
    result, _ = validate(extraction, notes={"added_indices": [1]})
    assert result.confidence == pytest.approx(0.6)
    only_added, _ = validate(page(show(confidence=1.0)), notes={"added_indices": [0]})
    assert only_added.confidence is None


# ---------------------------------------------------------------------------
# Warnings never change the outcome
# ---------------------------------------------------------------------------


def test_ambiguous_and_possible_merge_are_warnings_only() -> None:
    # Proves (A3-D3): `is_ambiguous` means "a human may want to look" and never fails a page; acts with
    # different start times are flagged as a possible merge (A5 reads it) but are legitimately one
    # show when it has one ticket link.
    merged = ShowExtraction.model_validate({
        "venue": "V", "date": datetime.date(2026, 10, 20), "is_ambiguous": True, "confidence": 0.9,
        "acts": [{"name": "A", "start_time": "19:00"}, {"name": "B", "start_time": "21:00"}],
    })
    result, kept = validate(page(merged))
    assert set(codes(result, Severity.WARNING)) == {CheckCode.AMBIGUOUS, CheckCode.POSSIBLE_MERGE}
    assert result.errors == [] and len(kept) == 1


def test_the_kept_shows_keep_their_position_in_findings_after_an_exclusion() -> None:
    # Proves: a finding's `show_index` is the position in the *extracted* list, even after an earlier
    # show was excluded — so a human (and A4) can find the show it names.
    excluded = ShowExtraction.model_validate({
        "venue": "V", "date": datetime.date(2026, 10, 19), "acts": [], "is_ambiguous": False, "confidence": 0.9,
    })
    result, kept = validate(page(excluded, show(free_admission=True, admission_day=5.0)))
    [finding] = [f for f in result.errors if f.code is CheckCode.FREE_WITH_PRICE]
    assert finding.show_index == 1 and len(kept) == 1
