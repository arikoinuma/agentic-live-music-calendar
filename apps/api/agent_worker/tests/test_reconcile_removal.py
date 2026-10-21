"""Tests for the soft delete: which stored shows a run may remove because the page no longer lists them.

Milestone A5 (docs/dev/implementations/a5-reconcile.md, Test approach §2). The risk in this half of reconcile is
silent and destructive: a show removed because the page was short, not because the show is gone. Each test pins one
way that could happen. Sources of the expected values: `requirements-initial.md` ("A previously stored show no
longer on the page, and falling within the date range that fetch actually covered, is marked removed"; "an empty
list is the most dangerous output"), `data-model-initial.md` (`show.status`), and decisions A5-D1, A5-D2 and A5-D10 (Ari,
October 17, 2026), plus the literal inputs.

"The page" is the venue's calendar page as fetched in the run; a "listing" is one entry on it; a "stored show" is a
row already in our table.
"""

import datetime

from agent_worker.reconcile import (
    Action,
    ReconcilePolicy,
    build_plan,
    covered_window,
    excluded_listing_dates,
    listings_from,
    load_request,
    prepare_inputs,
    removed_by_absence,
    withhold_if_mass_removal,
)
from agent_worker.schemas import VenuePageExtraction, show_model
from agent_worker.tests.fakes import scripted_client
from agent_worker.tests.reconcile_support import (
    FETCHED,
    KNOWN,
    OPTIONS,
    URL,
    actions,
    at,
    day,
    extracted,
    inputs_for,
    listed,
    only,
    plan_for,
    stored,
    validated,
)
from app.enums import ShowStatus

# ---------------------------------------------------------------------------
# The window (A5-K2, A5-D1)
# ---------------------------------------------------------------------------


def test_a_stored_show_the_page_dropped_inside_the_reached_dates_is_removed() -> None:
    # Proves (A5-D1): the page lists through October 31 and the stored October 20 show is not on it, so the venue
    # dropped it. This is the soft delete: status `removed`, never deleted.
    plan = plan_for(
        [listed(0, day(31), at(20), acts=["Prince"])], [stored(1, day(20), at(20), acts=[(8, "Zhora")])]
    )
    [removed] = only(plan, Action.REMOVE)
    assert removed.stored_id == 1 and removed.reason == "absent from the page"


def test_a_stored_show_beyond_the_last_listed_date_is_left_alone() -> None:
    # Proves (A5-D1; the subtle half of the lesson): the page lists through October 31 and says nothing about
    # November 14, so a show stored for November 14 is out of sight, not gone. Without the window bound, a venue
    # that lists two weeks would have every show booked further out removed on every run.
    plan = plan_for(
        [listed(0, day(31), at(20), acts=["Prince"])], [stored(1, datetime.date(2026, 11, 14), at(20), acts=[(8, "Zhora")])]
    )
    assert only(plan, Action.REMOVE) == []


def test_a_stored_show_before_today_is_left_alone() -> None:
    # Proves (A5-D1): past shows fall off venue pages naturally; a show from October 3 missing from today's page is
    # not a removal.
    plan = plan_for(
        [listed(0, day(31), at(20), acts=["Prince"])], [stored(1, day(3), at(20), acts=[(8, "Zhora")])]
    )
    assert only(plan, Action.REMOVE) == []


def test_both_ends_of_the_window_are_inside_it() -> None:
    # Proves (A5-D1): a show dated today (the fetch date) and one dated the last listed date are both removable when
    # absent. Off-by-one at either end would leave a stale show for a day, or remove nothing at the edge.
    plan = plan_for(
        [listed(0, day(31), at(20), acts=["Prince"])],
        [stored(1, FETCHED, at(20), acts=[(8, "Zhora")]), stored(2, day(31), at(22), acts=[(7, "Nona")])],
    )
    assert sorted(d.stored_id for d in only(plan, Action.REMOVE)) == [1, 2]


def test_an_already_removed_show_is_not_removed_again() -> None:
    # Proves: removing a removed show would write a pointless audit row on every run for as long as the page
    # stays without it.
    plan = plan_for(
        [listed(0, day(31), at(20), acts=["Prince"])],
        [stored(1, day(20), at(20), acts=[(8, "Zhora")], status=ShowStatus.REMOVED)],
    )
    assert only(plan, Action.REMOVE) == []


def test_a_listing_the_splitter_left_out_protects_a_stored_show_on_its_date() -> None:
    # Proves (A5-D1): validation leaves a listing out when no act could be found, and that listing may be a real show
    # (Mortimer's, two on every run). "The validated list lacks it" is not "the page lacks it": the stored show on
    # the same date must not be removed. A listing left out on another date doesn't protect it.
    page = [listed(0, day(31), at(20), acts=["Prince"])]
    show = stored(1, day(20), at(20), acts=[(8, "Zhora")])
    assert only(plan_for(page, [show], excluded=[day(20)]), Action.REMOVE) == []
    assert len(only(plan_for(page, [show], excluded=[day(21)]), Action.REMOVE)) == 1


def test_a_no_act_listing_with_an_impossible_date_does_not_stretch_the_window() -> None:
    # Proves (A5-D1, "Settled details"; A5-CR1-1): a placeholder entry such as "Private event" can name no act
    # AND carry a date far outside the plausible window (here March 2028). Validation leaves it out for naming no act
    # before it ever checks the date, so it must not count as evidence the page reached 2028: that would remove every
    # stored show between the page's real last date and 2028, and the A5-D10 guard does not stop it (the matched shows
    # count toward its denominator). Goes through real validation and `prepare_inputs`, the path the pipeline takes.
    raw, kept, result = validated([
        extracted(day(20), ["Nona"]), extracted(datetime.date(2028, 3, 1), []), extracted(day(25), ["Zhora"]),
    ])
    inputs = prepare_inputs(raw, kept, result, FETCHED)
    assert inputs.coverage is not None and inputs.coverage.end == day(25)
    plan = build_plan(
        inputs,
        [
            stored(1, day(20), at(20), acts=[(7, "Nona")]), stored(2, day(25), at(20), acts=[(8, "Zhora")]),
            stored(3, datetime.date(2026, 12, 5), at(20), acts=[(9, "Prince")]),
            stored(4, datetime.date(2027, 2, 5), at(20), acts=[(9, "Prince")]),
        ],
        KNOWN, original_url=URL, client=scripted_client({}), options=OPTIONS,
    )
    assert only(plan, Action.REMOVE) == []


def test_a_no_act_listing_with_a_plausible_date_still_counts_as_reach() -> None:
    # Proves (A5-D1): the other half. A listing left out for naming no act, on a plausible date, IS evidence the page
    # reached that date (it is on the page), so the window runs to it.
    raw, kept, result = validated([extracted(day(20), ["Nona"]), extracted(day(28), [])])
    assert prepare_inputs(raw, kept, result, FETCHED).coverage == covered_window([listed(0, day(20))], [day(28)], FETCHED)


def test_excluded_dates_come_from_the_raw_list_not_the_validated_one() -> None:
    # Proves (notes.md, the index trap): `Finding.show_index` is a position in the RAW extraction. The show left out
    # sits in the MIDDLE (index 1), so the validated list is [Oct 20, Oct 25] and index 1 there is Oct 25. Reading
    # the wrong list would protect October 25 instead of October 22, silently.
    raw, kept, result = validated([
        extracted(day(20), ["Nona"]), extracted(day(22), []), extracted(day(25), ["Zhora"]),
    ])
    inputs = prepare_inputs(raw, kept, result, FETCHED)
    assert inputs.excluded_dates == frozenset({day(22)})
    assert [(l.index, l.date) for l in inputs.listings] == [(0, day(20)), (1, day(25))]


def test_a_listing_carries_its_status_when_the_schema_has_one_and_is_scheduled_when_it_does_not() -> None:
    # Proves (plan, "Known gotchas"): `ShowExtraction` doesn't declare `status`, only the pipeline's schema variant does,
    # and the image route has none. `listings_from` reads it with a default, so a plain show is "scheduled" and a
    # status-carrying one keeps "cancelled".
    with_status = show_model(status=True, split_acts=False)(
        venue="The Venue", date=day(20), time=at(20), acts=[{"name": "Nona"}], is_ambiguous=False, confidence=0.9,
        status="cancelled",
    )
    page = VenuePageExtraction(page_readable=True, shows=[extracted(day(21)), with_status])
    assert [listing.status for listing in listings_from(page)] == ["scheduled", "cancelled"]


def test_no_extraction_or_no_validation_means_no_listings_and_no_protected_dates() -> None:
    # Proves (A7): reconcile's two page-reading helpers answer "nothing" when there is nothing to read: no extraction
    # gives no listings, and no extraction or no validation result gives no protected dates, so a missing input can
    # never raise or protect a stored show from the soft delete by accident. The control uses the same page as the
    # test above (an excluded show on Oct 22), so the empty answers are not simply what the helper always returns.
    raw, _kept, result = validated([
        extracted(day(20), ["Nona"]), extracted(day(22), []), extracted(day(25), ["Zhora"]),
    ])
    assert excluded_listing_dates(raw, result, FETCHED) == frozenset({day(22)})

    assert listings_from(None) == []
    assert excluded_listing_dates(None, result, FETCHED) == frozenset()
    assert excluded_listing_dates(raw, None, FETCHED) == frozenset()


def test_the_window_is_none_when_every_listed_date_is_before_today() -> None:
    # Proves (A5-PR1-14): a page showing only last week's shows gives `end < start`. That is no
    # evidence of reach, so no window (and no removals) rather than a negative range in the audit row.
    assert covered_window([listed(0, day(5), at(20))], [], FETCHED) is None


def test_cancelled_listings_count_as_evidence_of_reach() -> None:
    # Proves (A5-D1): a page that lists a cancelled show on October 28 reached October 28, so a stored show on
    # October 25 that isn't listed is gone.
    plan = plan_for(
        [listed(0, day(28), at(20), acts=["Prince"], status="cancelled")],
        [stored(1, day(25), at(20), acts=[(8, "Zhora")])],
    )
    assert [d.stored_id for d in only(plan, Action.REMOVE)] == [1]


def test_removed_by_absence_unit() -> None:
    # Proves (A5-K2): the function itself, with its inputs spelled out. Inside the window, active, unmatched and not
    # on a protected date: removed. Each other row of this table is one way to be left alone.
    window = covered_window([listed(0, day(31), at(20))], [], FETCHED)
    shows = [
        stored(1, day(20)),  # removable
        stored(2, day(20), status=ShowStatus.REMOVED),  # already removed
        stored(3, day(21)),  # matched by a listing
        stored(4, day(22)),  # a listing was left out on this date
        stored(5, datetime.date(2026, 11, 3)),  # beyond the window
        stored(6, day(10)),  # before today
    ]
    kept = removed_by_absence(shows, {3}, window, [day(22)])
    assert [s.id for s in kept] == [1]


# ---------------------------------------------------------------------------
# What is read (the range the reader loads)
# ---------------------------------------------------------------------------


def test_the_reader_range_reaches_back_to_the_earliest_listing() -> None:
    # Proves (A5-PR1-2): pages keep last week's shows, so a listing can be dated before today. The
    # stored shows to read start at the earliest listing, not at today, or that listing finds no stored twin.
    inputs = inputs_for([listed(0, day(8), at(20)), listed(1, day(25), at(20))])
    assert load_request(inputs) == (day(8), day(25))


def test_a_listing_dated_before_today_finds_its_stored_twin() -> None:
    # Proves (A5-PR1-2, whole plan): a listing from October 8 (four days before the fetch) with a stored twin is a
    # no-op, not an insert. This is what goes wrong if the range were just the window: a duplicate of every
    # past-week show the page still lists, on every run, outside the removal window so never cleaned up.
    plan = plan_for(
        [listed(0, day(8), at(20), acts=["Nona"]), listed(1, day(25), at(20), acts=["Zhora"])],
        [stored(1, day(8), at(20), acts=[(7, "Nona")])],
    )
    assert sorted(actions(plan)) == ["insert", "no_op"]


def test_a_confirmed_empty_page_reads_nothing() -> None:
    # Proves (A5-D2): no listings and no excluded dates means no window and nothing to compare.
    assert load_request(inputs_for([])) is None


# ---------------------------------------------------------------------------
# The empty page (A5-D2)
# ---------------------------------------------------------------------------


def test_a_confirmed_empty_page_removes_nothing() -> None:
    # Proves (A5-D2, decided A by Ari October 17): the venue's calendar plugin breaks and the page loads with no events.
    # Validation passes it as confirmed-empty, and twelve stored future shows must NOT be removed: "an empty list
    # is the most dangerous output, since reconcile would remove every stored show". The plan records
    # `coverage: None`.
    twelve = [stored(i, day(13 + i), at(20), acts=[(7, "Nona")]) for i in range(1, 13)]
    plan = plan_for([], twelve)
    assert plan.shows == () and plan.coverage is None


def test_a_page_of_only_cancelled_listings_still_has_a_window() -> None:
    # Proves (A5-D2): "empty" means no dates at all. A page whose only entries are cancelled shows has dates, so it
    # has a window and stored shows inside it that it doesn't list are removed.
    plan = plan_for(
        [listed(0, day(20), at(20), acts=["Prince"], status="cancelled")],
        [stored(1, day(18), at(20), acts=[(8, "Zhora")])],
    )
    assert plan.coverage is not None and [d.stored_id for d in only(plan, Action.REMOVE)] == [1]


# ---------------------------------------------------------------------------
# The guard (A5-D10)
# ---------------------------------------------------------------------------


def _venue(count: int) -> list:
    """`count` active stored shows on consecutive days from October 13."""
    return [stored(i, day(12 + i), at(20), acts=[(8, "Zhora")]) for i in range(1, count + 1)]


def test_a_run_that_would_remove_most_of_the_calendar_removes_none_of_it() -> None:
    # Proves (A5-D10): a venue's site glitches and returns half its calendar. Of 4 shows in the window, 3 are missing:
    # at least 3, and more than half. The removals are withheld and listed in the plan, not performed.
    shows = _venue(4)
    plan = plan_for([listed(0, day(16), at(20), acts=["Zhora"])], shows)
    assert only(plan, Action.REMOVE) == [] and len(plan.withheld) == 3


def test_fewer_than_the_minimum_is_not_guarded() -> None:
    # Proves (A5-D10): 2 of 4 missing is below the minimum of 3 (and exactly half is not MORE than half), so a small
    # venue losing two shows is an ordinary change.
    shows = _venue(4)
    plan = plan_for([listed(0, day(15), at(20), acts=["Zhora"]), listed(1, day(16), at(20), acts=["Zhora"])], shows)
    assert len(only(plan, Action.REMOVE)) == 2 and plan.withheld == ()


def test_losing_a_minority_of_a_big_calendar_is_not_guarded() -> None:
    # Proves (A5-D10): 3 of 8 missing meets the minimum but is not MORE than half, so the removals proceed.
    kept = [listed(i, day(12 + i), at(20), acts=["Zhora"]) for i in range(4, 9)]
    plan = plan_for(kept, _venue(8))
    assert len(only(plan, Action.REMOVE)) == 3 and plan.withheld == ()


def test_the_guard_does_not_withhold_cancellations() -> None:
    # Proves (A5-D10): a cancellation the page states is evidence, not absence. Three cancelled listings remove their
    # three shows even though that is most of the window.
    shows = _venue(4)
    page = [listed(i - 1, day(12 + i), at(20), acts=["Zhora"], status="cancelled") for i in (1, 2, 3)]
    plan = plan_for(page + [listed(3, day(16), at(20), acts=["Zhora"])], shows)
    assert len([d for d in only(plan, Action.REMOVE) if d.reason == "cancelled"]) == 3


def test_the_guard_numbers_come_from_the_policy() -> None:
    # Proves: the minimum and the share are `ReconcilePolicy`'s, not literals (so A8 can vary them). With the
    # minimum raised to 5, three removals of four are no longer withheld.
    shows = _venue(4)
    absent = shows[:3]
    kept, held = withhold_if_mass_removal(absent, shows, ReconcilePolicy(min_removals_to_guard=5))
    assert (len(kept), held) == (3, [])
    kept, held = withhold_if_mass_removal(absent, shows, ReconcilePolicy())
    assert (kept, len(held)) == ([], 3)
