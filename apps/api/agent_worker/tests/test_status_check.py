"""Tests for merging the status question's answer into an extraction (`status_check.apply`).

A2.1-D12 (decided by Ari, October 11, 2026): cancelled and postponed listings are found by a separate
narrow question, and code merges the answer — a matching show gets its status, a skipped listing
is added. The merge is in the adopted pipeline, and A2.1-CR2-1 showed three ways a
loose merge corrupts a calendar: marking the wrong show cancelled, adding a duplicate, and adding
an invented show from a date slip. These tests pin the stricter rules. Expected values are worked
out by hand from each case.

How to read it: helpers build an extraction and an answer -> matching -> adding.
"""

import datetime
from typing import Any

from agent_worker import status_check
from agent_worker.schemas import VenuePageExtraction

D = datetime.date


def extraction(*shows: tuple[int, list[str]]) -> VenuePageExtraction:
    """An extraction holding shows on the given October 2026 days with the given acts."""
    return VenuePageExtraction.model_validate({"page_readable": True, "shows": [
        {"venue": "V", "date": D(2026, 10, day).isoformat(), "acts": [{"name": a} for a in acts],
         "is_ambiguous": False, "confidence": 0.9}
        for day, acts in shows
    ]})


def answer(*items: tuple[int, list[str], str]) -> status_check.StatusAnswer:
    """A status answer listing the given (day, acts, status) items."""
    return status_check.StatusAnswer(items=[
        status_check.StatusItem(date=D(2026, 10, day), acts=acts, status=status)  # type: ignore[arg-type]
        for day, acts, status in items
    ])


def merge(ex: VenuePageExtraction, ans: status_check.StatusAnswer, page_text: str, **kwargs: Any) -> list[tuple[Any, ...]]:
    """Run the merge and return (date, acts, status) per show, for easy comparison."""
    merged, _notes = status_check.apply(ex, ans, page_text=page_text, fetch_date=None, venue_name="V", **kwargs)
    return [(s.date.day, [a.name for a in s.acts], s.status) for s in merged.shows]  # type: ignore[attr-defined]


def test_a_shared_filler_word_is_not_a_match() -> None:
    # Proves: "The Back Alley" (cancelled, skipped by the main extraction) is not matched to
    # "The Bright Light Social Hour" on the same night just because both contain "The"; the
    # real show stays scheduled and the cancelled one is added.
    shows = merge(
        extraction((17, ["The Bright Light Social Hour", "Miradores del Sol"])),
        answer((17, ["The Back Alley"], "cancelled")),
        page_text="Oct 17 The Bright Light Social Hour with Miradores del Sol. Cancelled: The Back Alley",
    )
    assert shows == [
        (17, ["The Bright Light Social Hour", "Miradores del Sol"], "scheduled"),
        (17, ["The Back Alley"], "cancelled"),
    ]


def test_short_names_match_by_exact_name() -> None:
    # Proves: acts with no word of three letters ("MO", "U2") still match the show they name,
    # so the show is marked rather than duplicated.
    shows = merge(extraction((10, ["MO", "U2"])), answer((10, ["MO", "U2"], "cancelled")), page_text="Cancelled MO U2")
    assert shows == [(10, ["MO", "U2"], "cancelled")]


def test_an_answer_with_only_short_names_is_added_only_if_the_page_contains_them() -> None:
    # Proves (A7): a status answer whose acts have no identifying word ("MO" is under three letters) is checked against
    # the page by the fallback in `_on_page`: its folded name must appear in the folded page text. Present -> added,
    # absent -> recorded in `not_on_page` and not added ("no invented shows").
    # This fallback is a SUBSTRING test, not a word test: "mo" is inside "armory", so a page that never lists the act
    # still passes. That looseness is pinned here as it is today (the third case), not endorsed; it is cheap, and
    # the main guard against an invented show is the identifying-word check every longer name goes through.
    # The page texts are written to contain, or not contain, the letters "mo" by hand.
    cancelled_mo = answer((18, ["MO"], "cancelled"))

    on_page = merge(extraction(), cancelled_mo, page_text="Oct 18: MO cancelled")
    assert on_page == [(18, ["MO"], "cancelled")]

    merged, notes = status_check.apply(
        extraction(), cancelled_mo, page_text="Oct 18: Lizzo cancelled", fetch_date=None, venue_name="V",
    )
    assert merged.shows == []
    assert notes["not_on_page"] == [["MO"]]

    inside_a_word = merge(extraction(), cancelled_mo, page_text="Oct 18: Lizzo at the Armory")
    assert inside_a_word == [(18, ["MO"], "cancelled")]


def test_a_one_day_date_slip_still_matches() -> None:
    # Proves: this model sometimes puts a listing on the neighbouring date ("MARIS" Oct 30 for
    # 31). The answer is matched to the show it names a day away instead of adding an invented
    # show beside the real one.
    shows = merge(extraction((31, ["MARIS"])), answer((30, ["MARIS"], "postponed")), page_text="postponed MARIS")
    assert shows == [(31, ["MARIS"], "postponed")]


def test_an_answer_the_page_doesnt_contain_is_not_added() -> None:
    # Proves: a listing is only added when its acts appear in the page text — an answer the page
    # doesn't support is recorded in the notes, never turned into a show ("no invented shows").
    ex = extraction((10, ["Robert Ellis"]))
    merged, notes = status_check.apply(
        ex, answer((12, ["Nobody Listed"], "cancelled")), page_text="Cancelled Robert Ellis",
        fetch_date=None, venue_name="V",
    )
    assert [(s.date.day, s.status) for s in merged.shows] == [(10, "scheduled")]  # type: ignore[attr-defined]
    assert notes["not_on_page"] == [["Nobody Listed"]]


def test_an_added_listing_is_split_when_a_splitter_is_given() -> None:
    # Proves: A2.1-CR2-4 — on the title-split route, an added cancelled listing goes through
    # the same act splitter as every other title, so it isn't stored as one long "artist".
    shows = merge(
        extraction(), answer((17, ["Sophie Truax with Sasha Cee"], "cancelled")),
        page_text="Cancelled Sophie Truax with Sasha Cee",
        split_titles=lambda titles: [["Sophie Truax", "Sasha Cee"] for _ in titles],
    )
    assert shows == [(17, ["Sophie Truax", "Sasha Cee"], "cancelled")]
