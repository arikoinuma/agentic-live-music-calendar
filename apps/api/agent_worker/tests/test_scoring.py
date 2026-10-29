"""Tests for the scorer behind Ari's accuracy standard (`agent_worker/eval/scoring.py`).

The standard (A2.1-D1 of docs/dev/implementations/a2.1-extraction-reliability.md; `requirements-initial.md`,
"Agent Extraction: Accuracy Standards") is tiered: date and acts exact, no invented shows,
other fields may be *missing* now and then but never *wrong*, and a non-music entry may leak
about once a month per venue. These tests pin how each tier is counted, because a scorer that
counts wrongly would pass or fail the gate for the wrong reason.

How to read it: helpers build labels and returned shows by hand -> matching (A2.1-K2)
-> acts -> fields -> extras (leak vs fabricated) -> the gate. Every expected value is worked
out by hand from the case and the standard, never read from the scorer.
"""

import datetime
from typing import Any

from agent_worker.eval import scoring
from agent_worker.eval.labels import LabelledShow, NonShow, PageLabel

D = datetime.date
T = datetime.time

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def label(day: int, *acts: str, **fields: Any) -> LabelledShow:
    """A labelled show on October `day`, 2026. Fields the page states are passed by keyword;
    anything not passed is "the page doesn't state it" (None)."""
    return LabelledShow(
        date=D(2026, 10, day), acts=tuple(acts), source_line=" / ".join(acts), **fields
    )


def page_label(*shows: LabelledShow, non_shows: tuple[NonShow, ...] = ()) -> PageLabel:
    """A gated page holding the given labelled shows and non-show entries."""
    return PageLabel(
        venue="test_venue", gated=True, captured_on=D(2026, 10, 10),
        shows=tuple(shows), non_shows=non_shows,
    )


def returned(day: int, *acts: str, **fields: Any) -> dict[str, Any]:
    """One show as an extraction dump carries it (`model_dump(mode="json")`), with only the
    fields a test cares about; the rest are null, as a model's "not stated" would be."""
    show: dict[str, Any] = {
        "venue": "Test", "date": D(2026, 10, day).isoformat(), "time": None, "end_time": None,
        "acts": [{"name": a, "start_time": None, "sequence_number": None} for a in acts],
        "is_ambiguous": False, "admission_advance": None, "admission_day": None,
        "free_admission": None, "image_url": None, "confidence": 0.9,
    }
    for key, value in fields.items():
        show[key] = value.isoformat() if isinstance(value, T) else value
    return show


def score(lbl: PageLabel, *shows: dict[str, Any], page_html: str = "") -> scoring.PageScore:
    """Score one extraction (the given returned shows) against a page label."""
    return scoring.score_page(lbl, {"page_readable": True, "shows": list(shows)}, page_html)


# ---------------------------------------------------------------------------
# Matching (A2.1-K2): date is identity, time is a field
# ---------------------------------------------------------------------------


def test_a_perfect_extraction_passes_every_tier() -> None:
    # Proves: the baseline case counts nothing against the standard.
    s = score(page_label(label(9, "Lent", "Gills")), returned(9, "Lent", "Gills"))
    assert (s.missed, s.acts_wrong, s.fabricated, s.leaks) == (0, 0, 0, 0)


def test_a_missed_time_is_a_missing_field_not_a_missed_show() -> None:
    # Proves: A2.1-D1 made time a field with its own tolerance. A found show whose stated time
    # came back null is *missing* a time (tolerated up to 1 in 10), not a missed show — the
    # reason A2.1-K2 matches on date rather than (date, time).
    s = score(page_label(label(9, "Lent", time=T(21, 0))), returned(9, "Lent"))
    assert s.missed == 0 and s.fabricated == 0
    assert (s.fields["time"].missing, s.fields["time"].wrong) == (1, 0)


def test_a_different_time_is_a_wrong_field() -> None:
    # Proves: a wrong time is never tolerated, but it is a field error on a found show.
    s = score(page_label(label(9, "Lent", time=T(21, 0))), returned(9, "Lent", time=T(20, 0)))
    assert s.missed == 0
    assert s.fields["time"].wrong == 1


def test_a_time_the_page_never_states_is_wrong() -> None:
    # Proves: an invented value is a wrong value (A2.1-D1). Terminal Bar, 7th St Entry and
    # Mortimer's state no times in their text, so any returned time there is invented.
    s = score(page_label(label(9, "Lent")), returned(9, "Lent", time=T(21, 30)))
    assert s.fields["time"].wrong == 1
    clean = score(page_label(label(9, "Lent")), returned(9, "Lent"))
    assert clean.fields["time"].wrong == 0


def test_two_sets_on_one_night_pair_by_acts_not_by_order() -> None:
    # Proves: White Squirrel lists a 6 pm and a 9 pm show each night. Returned in the other
    # order, each still pairs with its own label (A2.1-K2 prefers correct acts), so both times
    # score correct. Taking the first same-date candidate would score two wrong times.
    lbl = page_label(label(9, "Early Band", time=T(18, 0)), label(9, "Late Band", time=T(21, 0)))
    s = score(lbl, returned(9, "Late Band", time=T(21, 0)), returned(9, "Early Band", time=T(18, 0)))
    assert (s.missed, s.acts_wrong, s.fabricated) == (0, 0, 0)
    assert (s.fields["time"].correct, s.fields["time"].wrong) == (2, 0)


def test_two_untimed_shows_on_one_date_and_a_same_date_leak() -> None:
    # Proves: 7th St Entry's Oct 31 case (two untimed shows on one date) plus a returned
    # non-show on the same date: both shows correct, the extra is a tolerated leak, not a
    # fabrication (A2.1-PR2-3).
    lbl = page_label(
        label(31, "MARIS"), label(31, "Internet Kids"),
        non_shows=(NonShow(title="Halloween Karaoke", date=D(2026, 10, 31), weekday=None, reason="karaoke"),),
    )
    s = score(lbl, returned(31, "Halloween Karaoke"), returned(31, "Internet Kids"), returned(31, "MARIS"))
    assert (s.missed, s.acts_wrong, s.fabricated, s.leaks) == (0, 0, 0, 1)


def test_a_duplicate_is_fabricated_not_counted_twice() -> None:
    # Proves: each returned show is used once (A2.1-K2's likeliest mistake is not removing a
    # hit). The second copy is a show that isn't on the page.
    s = score(page_label(label(9, "Lent")), returned(9, "Lent"), returned(9, "Lent"))
    assert (s.missed, s.fabricated) == (0, 1)


def test_a_wrong_date_is_a_missed_show_and_a_fabricated_one() -> None:
    # Proves: date is identity (A2.1-D1). Dates shifted by one listing — seen on Terminal Bar in
    # A2's runs — fail the 100% tier twice over.
    s = score(page_label(label(9, "Lent")), returned(10, "Lent"))
    assert (s.missed, s.fabricated) == (1, 1)


# ---------------------------------------------------------------------------
# Acts
# ---------------------------------------------------------------------------


def test_spelling_variants_of_an_act_are_correct() -> None:
    # Proves: case, HTML entities, typographic apostrophes, dashes and spacing don't make a
    # correct act wrong (A2.1-PR1-5).
    lbl = page_label(label(9, "The Dan's", "Martin Devaney & Friends", "Back-to-Back"))
    s = score(lbl, returned(9, "the dan’s", "Martin Devaney &#038; Friends", "Back–to–Back"))
    assert s.acts_wrong == 0


def test_an_unsplit_title_is_acts_wrong_and_diagnosed() -> None:
    # Proves: A2-F9 — "Lent w. Gills" returned as one act is wrong, and the scorer says why.
    s = score(page_label(label(9, "Lent", "Gills")), returned(9, "Lent w. Gills"))
    assert (s.missed, s.acts_wrong) == (0, 1)
    assert s.unsplit == 1


def test_act_order_is_not_gated() -> None:
    # Proves: A2.1-D1 — order is reported, not scored (A5 derives order from list position).
    s = score(page_label(label(9, "Lent", "Gills")), returned(9, "Gills", "Lent"))
    assert s.acts_wrong == 0
    assert s.order_differs == 1


def test_an_alternative_reading_is_accepted() -> None:
    # Proves: a genuinely ambiguous title (A2.1-D5: "Slashfire w. Dread Spell & Couch Potato
    # Massacre") is correct under any reading the label lists, and wrong under any other.
    slashfire = label(
        9, "Slashfire", "Dread Spell", "Couch Potato Massacre",
        alternatives=(("Slashfire", "Dread Spell & Couch Potato Massacre"),),
    )
    ok = score(page_label(slashfire), returned(9, "Slashfire", "Dread Spell & Couch Potato Massacre"))
    bad = score(page_label(slashfire), returned(9, "Slashfire w. Dread Spell & Couch Potato Massacre"))
    assert (ok.acts_wrong, bad.acts_wrong) == (0, 1)


def test_a_show_with_no_acts_is_dropped_before_counting() -> None:
    # Proves: a rejected non-music entry kept with `acts: []` (both routes do this, for A3's
    # completeness check) is neither a leak nor a fabrication (A2.1-PR1-4).
    s = score(page_label(label(9, "Lent")), returned(9, "Lent"), returned(12))
    assert (s.fabricated, s.leaks, s.dropped_empty) == (0, 0, 1)


def test_legacy_string_acts_and_a_missing_status_still_score() -> None:
    # Proves: A2's stored `baseline-32k` results (acts as plain strings, no `status`) can be
    # rescored (A2.1-PR1-13).
    legacy = returned(9)
    legacy["acts"] = ["Lent", "Gills"]
    s = score(page_label(label(9, "Lent", "Gills")), legacy)
    assert s.acts_wrong == 0
    assert s.fields["status"].wrong == 0


# ---------------------------------------------------------------------------
# Other fields: missing is tolerated, wrong never
# ---------------------------------------------------------------------------


def test_price_in_the_wrong_field_is_missing_plus_wrong() -> None:
    # Proves: a day price returned as an advance price is the day price *missing* and an
    # advance price the page never states *wrong* (A2.1-D7 decides which field is right).
    s = score(page_label(label(9, "Lent", admission_day=10.0)), returned(9, "Lent", admission_advance=10.0))
    assert s.fields["admission_day"].missing == 1
    assert s.fields["admission_advance"].wrong == 1


def test_free_admission_the_page_never_states_is_wrong() -> None:
    # Proves: `free_admission: true` with nothing on the page is an invented value. (`false`
    # is coerced to null by the schema, A2-F1, so it never reaches the scorer as a value.)
    s = score(page_label(label(9, "Lent")), returned(9, "Lent", free_admission=True))
    assert s.fields["free_admission"].wrong == 1


def test_a_cancelled_show_returned_as_scheduled_is_wrong() -> None:
    # Proves: A2.1-D12 — status is a field, and a cancelled show shown as on is never acceptable.
    lbl = page_label(label(10, "Robert Ellis", "Philip Bowen", status="cancelled"))
    s = score(lbl, returned(10, "Robert Ellis", "Philip Bowen"))
    assert s.missed == 0
    assert s.fields["status"].wrong == 1
    ok = score(lbl, returned(10, "Robert Ellis", "Philip Bowen", status="cancelled"))
    assert ok.fields["status"].correct == 1


def test_an_image_url_not_in_the_page_is_wrong() -> None:
    # Proves: an image link is checked against the page itself (labels don't list images);
    # A2 saw a model invent "N/A (Source Image Poster)".
    html = '<img src="https://venue.example/poster.png">'
    ok = score(page_label(label(9, "Lent")), returned(9, "Lent", image_url="https://venue.example/poster.png"), page_html=html)
    bad = score(page_label(label(9, "Lent")), returned(9, "Lent", image_url="N/A (Source Image Poster)"), page_html=html)
    assert (ok.fields["image_url"].wrong, bad.fields["image_url"].wrong) == (0, 1)


# ---------------------------------------------------------------------------
# Extras: a tolerated leak vs an intolerable fabrication
# ---------------------------------------------------------------------------


def test_an_extra_on_a_non_show_date_or_weekday_is_a_leak() -> None:
    # Proves: the two kinds of extra the standard treats differently. Mortimer's lists
    # "Autotune Karaoke" on Oct 12; Terminal Bar's header says "OPEN MIC Every Monday".
    lbl = page_label(
        label(9, "Lent"),
        non_shows=(
            NonShow(title="Autotune Karaoke", date=D(2026, 10, 12), weekday=None, reason="karaoke"),
            NonShow(title="OPEN MIC", date=None, weekday=0, reason="open mic, every Monday"),
        ),
    )
    s = score(lbl, returned(9, "Lent"), returned(12, "Autotune Karaoke"), returned(19, "Open Mic Host"), returned(14, "Nobody Listed This"))
    assert s.leaks == 2  # Oct 12 (dated entry) and Oct 19 (a Monday)
    assert s.fabricated == 1  # Oct 14, a Wednesday, matches nothing on the page


# ---------------------------------------------------------------------------
# The gate: every run must meet every tier
# ---------------------------------------------------------------------------


def run_of(*scores: scoring.PageScore | scoring.PageFailure) -> list[scoring.PageScore | scoring.PageFailure]:
    """One run's per-page outcomes, as the gate takes them."""
    return list(scores)


def test_the_gate_fails_on_a_single_fabrication_in_one_run() -> None:
    # Proves: every run must pass, and "never" means never: four clean runs don't excuse
    # one invented show.
    lbl = page_label(label(9, "Lent"))
    clean = score(lbl, returned(9, "Lent"))
    dirty = score(lbl, returned(9, "Lent"), returned(14, "Invented"))
    result = scoring.gate({0: run_of(clean), 1: run_of(clean), 2: run_of(dirty)})
    assert not result.passed
    assert any("run 2" in f and "fabricated" in f for f in result.failures)


def test_the_missing_rate_is_pooled_per_run_at_ten_percent() -> None:
    # Proves: "missing 1 in 10 is ok" — 2 of 20 stated times missing passes, 3 of 20 fails.
    # Pooled over the run's pages, because one 12-show page can't express 10% on its own.
    def page_with(missing: int, total: int) -> scoring.PageScore:
        lbl = page_label(*[label(d, f"Band {d}", time=T(20, 0)) for d in range(1, total + 1)])
        shows = [returned(d, f"Band {d}", time=None if d <= missing else T(20, 0)) for d in range(1, total + 1)]
        return score(lbl, *shows)

    assert scoring.gate({0: run_of(page_with(1, 10), page_with(1, 10))}).passed
    assert not scoring.gate({0: run_of(page_with(2, 10), page_with(1, 10))}).passed


def test_more_than_one_leak_on_a_venue_page_fails() -> None:
    # Proves: "about once a month per venue" — a page is about a month, so one leak per page
    # passes and two fail.
    lbl = page_label(
        label(9, "Lent"),
        non_shows=(NonShow(title="Karaoke", date=None, weekday=0, reason="karaoke, Mondays"),),
    )
    one = score(lbl, returned(9, "Lent"), returned(12, "Karaoke"))
    two = score(lbl, returned(9, "Lent"), returned(12, "Karaoke"), returned(19, "Karaoke"))
    assert scoring.gate({0: run_of(one)}).passed
    assert not scoring.gate({0: run_of(two)}).passed


def test_a_run_that_raised_fails_the_gate() -> None:
    # Proves: a crash can't be skipped; it counts as a failed page.
    result = scoring.gate({0: run_of(scoring.PageFailure(fixture="page.html", error="IncompleteOutputException"))})
    assert not result.passed


def test_the_gate_can_be_read_per_route() -> None:
    # Proves: a pass can't be read as "the model extracts this well" when some pages got
    # their dates from JSON-LD (A2.1-PR1-15): the gate filters by route.
    lbl = page_label(label(9, "Lent"))
    good = score(lbl, returned(9, "Lent"))
    good.route = "jsonld"
    bad = score(lbl, returned(10, "Lent"))
    bad.route = "model"
    runs = {0: run_of(good, bad)}
    assert scoring.gate(runs, route="jsonld").passed
    assert not scoring.gate(runs, route="model").passed


def test_a_gate_with_no_pages_does_not_pass() -> None:
    # Proves: "every run met every tier" is never true vacuously. A route no page took (the
    # JSON-LD route in a model-only label) has nothing to pass; reporting PASS there would
    # read as evidence it works. Found smoke-testing the rescore of A2's results.
    lbl = page_label(label(9, "Lent"))
    page = score(lbl, returned(9, "Lent"))
    result = scoring.gate({0: run_of(page)}, route="jsonld")
    assert not result.passed
    assert result.pages == 0


def test_an_invented_show_on_a_non_show_weekday_is_still_fabricated() -> None:
    # Proves: A2.1-CR1-1 (blocker). A leak must RESEMBLE the non-show it is attributed
    # to — sharing a word of its title — not merely fall on its date or weekday. Otherwise a
    # made-up band on a Monday hides behind "OPEN MIC Every Monday" and the "no invented
    # shows, ever" tier passes. Reproduced by the reviewer on Terminal Bar's October page.
    lbl = page_label(
        label(9, "Lent"),
        non_shows=(NonShow(title="OPEN MIC Every Monday", date=None, weekday=0, reason="open mic"),),
    )
    s = score(lbl, returned(9, "Lent"), returned(5, "Totally Invented Band"))
    assert (s.fabricated, s.leaks) == (1, 0)
    assert not scoring.gate({0: run_of(s)}).passed


def test_a_duplicate_on_a_non_show_date_is_fabricated() -> None:
    # Proves: A2.1-CR1-1. White Squirrel's Oct 11 lists "Open Jam" (a non-show) and a real
    # show; a second copy of the real show that day is an invented show, not a leaked jam.
    lbl = page_label(
        label(11, "Nici Peper", "Doyle Turner"),
        non_shows=(NonShow(title="Open Jam", date=D(2026, 10, 11), weekday=None, reason="open jam"),),
    )
    s = score(lbl, returned(11, "Nici Peper", "Doyle Turner"), returned(11, "Nici Peper", "Doyle Turner"))
    assert (s.fabricated, s.leaks) == (1, 0)


def test_a_failed_page_counts_in_every_route_scope() -> None:
    # Proves: A2.1-CR1-5. A page that raised can't be attributed to a route it never
    # finished, so it fails every scope — `gate [jsonld]` can't print PASS for a label in
    # which a JSON-LD page crashed.
    lbl = page_label(label(9, "Lent"))
    good = score(lbl, returned(9, "Lent"))
    good.route = "jsonld"
    crashed = scoring.PageFailure(fixture="ws.html", error="InstructorRetryException")
    runs = {0: run_of(good, crashed)}
    assert not scoring.gate(runs, route="jsonld").passed
    assert not scoring.gate(runs, route="model").passed


# ---------------------------------------------------------------------------
# C5: structured errors, the dump index, and the committed-column label
# ---------------------------------------------------------------------------
#
# C5-D1 / C5-D7 (docs/dev/implementations/c5-pipeline-eval-harness.md, Test approach §1). The graph-level harness joins
# each counted error to validation's findings by position (C5-K4), so the scorer must say which returned show an error
# is about, in the positions validation uses: the index in `state.extraction.shows`, the raw list.


def with_index_gap() -> tuple[PageLabel, list[dict[str, Any]]]:
    """A page whose dump holds [show with acts, show with NO acts, show with acts]: the empty one is dropped by the scorer
    before matching, so a position taken after that filter would be 1 for the last show where validation says 2."""
    lbl = page_label(label(9, "Lent"), label(11, "Nici Peper"))
    return lbl, [returned(9, "Lent"), returned(10), returned(11, "Somebody Else")]


def test_returned_shows_carry_their_position_in_the_dump_not_in_the_filtered_list() -> None:
    # Proves: C5-M1. `ReturnedShow.index` is the position in the dump BEFORE empty-act shows are dropped, because
    # `validation.Finding.show_index` is a position in `state.extraction.shows` (apps/api/AGENTS.md). Taken after the
    # filter, the third show would be index 1 and every later join in validation recall would point at the wrong show.
    # The expectation is the dump's own order, written out by hand.
    _, dump = with_index_gap()
    shows = [scoring.ReturnedShow.from_dump(s, i) for i, s in enumerate(dump)]
    assert [s.index for s in shows] == [0, 1, 2]
    lbl, _ = with_index_gap()
    result = score(lbl, *dump)
    acts_wrong = [i for i in result.items if i.kind == "acts_wrong"]
    assert [(i.date, i.index) for i in acts_wrong] == [("2026-10-11", 2)]


def test_every_counted_error_has_a_structured_item() -> None:
    # Proves: C5-D7. Each error `score_page` counts also comes out as an `ErrorItem` with its kind, so validation recall
    # (C5-K4) can classify errors without parsing the human-readable strings. Constructed page: one missed show, one
    # wrong-acts show, one fabricated show, one leak, one wrong time and one missing time. Expected kinds are the tiers of
    # A2.1-D1, counted by hand from the case.
    lbl = page_label(
        label(1, "Missed Band"), label(2, "Right Band"), label(3, "Timed Band", time=T(20, 0)),
        label(4, "Stated Time Band", time=T(21, 0)),
        non_shows=(NonShow(title="Karaoke Night", date=D(2026, 10, 8), weekday=None, reason="karaoke"),),
    )
    result = score(
        lbl, returned(2, "Wrong Band"), returned(3, "Timed Band", time=T(19, 0)), returned(4, "Stated Time Band"),
        returned(6, "Invented Band"), returned(8, "Karaoke Night"),
    )
    assert sorted(i.kind for i in result.items) == sorted(
        ["missed", "acts_wrong", "field_wrong", "field_missing", "fabricated", "leak"]
    )
    wrong = next(i for i in result.items if i.kind == "field_wrong")
    assert (wrong.field, wrong.date) == ("time", "2026-10-03")


def test_the_error_strings_are_unchanged_by_the_structured_items() -> None:
    # Proves: C5-D7 leaves `PageScore.errors` alone. `run_eval.py` and every stored results file read the strings.
    # Expected text is what the A2.1 scorer already wrote.
    result = score(page_label(label(1, "Missed Band")))
    assert result.errors == ["missed 2026-10-01 'Missed Band'"]


def test_a_missed_show_takes_the_index_of_the_dropped_show_on_its_date() -> None:
    # Proves: C5-PR1-2. When the act splitter drops a show, it stays in the dump with `acts: []`; `score_page` drops it
    # before matching, so the label is `missed`. Validation puts `splitter_dropped` on that show's real index, so the
    # missed item must carry it, or the commonest real error would join to nothing and be called "silent".
    lbl = page_label(label(9, "Lent"), label(11, "Nici Peper"))
    result = score(lbl, returned(9, "Lent"), returned(10), returned(11))
    missed = [i for i in result.items if i.kind == "missed"]
    assert [(i.date, i.index) for i in missed] == [("2026-10-11", 2)]


def test_a_missed_show_with_nothing_returned_has_no_index() -> None:
    # Proves: C5-PR1-2, the other half. A show the extraction never mentioned has no dump position, so its item has none
    # and only a page-level finding can cover it.
    result = score(page_label(label(9, "Lent")))
    assert [(i.kind, i.index) for i in result.items] == [("missed", None)]


def test_page_scores_with_items_round_trip_through_json_and_old_files_still_load() -> None:
    # Proves: C5-PR1-12 (a). `from_dict` must rebuild `ErrorItem`s (a plain `cls(**data)` leaves dicts), the dict must be
    # JSON-serialisable (so the date is a string, not a `datetime.date`), and a results file written before C5, with no
    # `items` key, still loads so `--rescore` of an A2.1 file keeps working.
    import dataclasses
    import json

    result = score(page_label(label(1, "Missed Band")))
    stored = json.loads(json.dumps(dataclasses.asdict(result)))
    again = scoring.PageScore.from_dict(stored)
    assert again.items == result.items
    assert isinstance(again.items[0], scoring.ErrorItem)
    del stored["items"]
    assert scoring.PageScore.from_dict(stored).items == []


def test_scheduled_only_drops_cancelled_and_postponed_shows_from_a_label() -> None:
    # Proves: C5-PR1-5. A cancelled or postponed listing is labelled with its status (A2.1-D12) but reconcile skips it and
    # `ShowStatus` has no such value, so the rows left cannot hold it. Scored against the full label, every run of a page
    # like 7th St Entry's would report those shows missed for correct behaviour.
    lbl = page_label(label(1, "Live Band"), label(2, "Gone Band", status="cancelled"), label(3, "Later Band", status="postponed"))
    assert [s.acts for s in scoring.scheduled_only(lbl).shows] == [("Live Band",)]
    assert len(lbl.shows) == 3  # the original is untouched


# ---------------------------------------------------------------------------
# C5-K2: precision and recall (red until Ari fills the TODO in `headline_rates`)
# ---------------------------------------------------------------------------


def k2_page_score() -> scoring.PageScore:
    """A constructed page, not hand-set fields, so an impossible combination can't arise: 10 labelled shows; the extraction
    misses one, gives one the wrong acts, adds one invented show and one listed non-show (a leak)."""
    shows = tuple(label(day, f"Band {day}") for day in range(1, 11))
    lbl = page_label(
        *shows, non_shows=(NonShow(title="Karaoke Night", date=D(2026, 10, 20), weekday=None, reason="karaoke"),),
    )
    returned_shows = [returned(day, f"Band {day}") for day in range(3, 11)]  # shows 1 and 2 not returned yet
    returned_shows[0] = returned(3, "Wrong Band")  # show 3: wrong acts
    returned_shows.append(returned(2, "Band 2"))  # show 2 found; show 1 stays missed
    returned_shows.append(returned(15, "Invented Band"))
    returned_shows.append(returned(20, "Karaoke Night"))
    return score(lbl, *returned_shows)


def test_headline_rates_count_found_as_labelled_minus_missed_minus_wrong_acts() -> None:
    # Proves: C5-K2. Ari's standard makes a show's identity its date and acts (A2.1-D1), so a show is FOUND only when it
    # was matched AND its acts are right. Expected numbers worked by hand from the page above: 10 labelled; show 1 missed;
    # show 3 has wrong acts; shows 2 and 4 to 10 are right, so 8 found. Returned with acts: 8 right + 1 wrong + 1 invented
    # + 1 leak = 11. Recall 8/10. Strict precision 8/11 counts the leak against; lenient 8/10 does not. The likeliest mistake
    # is `found = labelled - missed` (counting the wrong-acts show as found).
    base = k2_page_score()
    assert (base.labelled, base.returned, base.missed, base.acts_wrong, base.fabricated, base.leaks) == (10, 11, 1, 1, 1, 1)
    rates = scoring.headline_rates(base)
    assert rates.found == 8
    assert rates.recall == 8 / 10
    assert rates.precision == 8 / 11
    assert rates.precision_lenient == 8 / 10


def test_headline_rates_on_an_empty_page_are_perfect_not_a_division_error() -> None:
    # Proves: C5-M8. An empty labelled page returned empty is a perfect score, not a ZeroDivisionError. A page of only
    # leaks has no returned show that is a real one, so the lenient figure must not divide by zero either.
    empty = scoring.headline_rates(score(page_label()))
    assert (empty.recall, empty.precision, empty.precision_lenient) == (1.0, 1.0, 1.0)
    only_leak = score(
        page_label(non_shows=(NonShow(title="Karaoke Night", date=D(2026, 10, 8), weekday=None, reason="karaoke"),)),
        returned(8, "Karaoke Night"),
    )
    assert scoring.headline_rates(only_leak).precision_lenient == 1.0
