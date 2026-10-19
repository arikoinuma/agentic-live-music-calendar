"""Tests for how reconcile decides what happens to each SHOW: pairing, cancellations, changes, lineups.

Milestone A5 (docs/dev/implementations/a5-reconcile.md, Test approach §1). Everything here is a pure function of
hand-built data (`reconcile_support.py`): no database, no model. Reading order follows the plan: the composite key
and its null-time rules (A5-K1, A5-D3), cancelled and postponed listings (A5-K3, A5-D6, A5-D7), what counts as a change (A5-D4, A5-D5),
lineups, and the idempotency property.

Expected values come from `requirements-initial.md` ("Agent Reconciliation", "Times after midnight", "Cancelled or
postponed listings", "Show"), `arch-initial.md` §7's outcome table, `data-model-initial.md` (`show`, including its
CHECK) and the decisions A5-D1 to A5-D12 in the plan, and from the literal inputs of each test. None is read from the code
under test. The scenarios are the plan's: 8 PM against 9 PM, 7th St Entry's two untimed shows on October 31,
Terminal Bar's page with no times.
"""

import dataclasses
import datetime
import subprocess
import sys

import pytest

from agent_worker.reconcile import (
    Action,
    ListedAct,
    StoredLineupEntry,
    night_sort_key,
)
from agent_worker.tests.reconcile_support import (
    KNOWN,
    URL,
    actions,
    apply_plan,
    at,
    day,
    listed,
    money,
    only,
    plan_for,
    stored,
    violates_free_check,
)
from app.enums import ShowStatus

# ---------------------------------------------------------------------------
# The composite key (A5-K1, A5-D3)
# ---------------------------------------------------------------------------


def test_the_same_date_and_time_with_nothing_changed_is_a_no_op() -> None:
    # Proves: a show that matches a stored record and hasn't changed is left alone (requirements, "Agent
    # Reconciliation"; arch-initial.md §7's "No-op" row). A reconcile that updated unchanged shows would write an
    # audit row per show per night.
    plan = plan_for([listed(0, day(20), at(20))], [stored(1, day(20), at(20), acts=[(7, "Nona")])])
    [decision] = plan.shows
    assert decision.action is Action.NO_OP and decision.stored_id == 1


def test_a_new_opener_at_the_same_date_and_time_is_an_update_not_a_remove_and_an_insert() -> None:
    # Proves: "If a 8pm show on a given date features a different set of performing artists in the latest scan,
    # then update the Show" (requirements, "Agent Reconciliation"). If matching depended on the lineup, an opener
    # being added would read as one show disappearing and another appearing.
    plan = plan_for(
        [listed(0, day(20), at(20), acts=["Nona", "Zhora"])], [stored(1, day(20), at(20), acts=[(7, "Nona")])]
    )
    [decision] = plan.shows
    assert decision.action is Action.UPDATE and decision.stored_id == 1 and "lineup" in decision.changes
    assert [e.artist_id for e in decision.lineup] == [7, 8]


def test_a_time_change_is_a_cancelled_show_plus_a_new_one() -> None:
    # Proves: "If 8pm show disappears but then 9pm show appears, that's a time change ... the old show [is marked]
    # as cancelled and [a] new show [entered]" (requirements, "Agent Reconciliation"). Two different times never
    # pair. It also proves needs_review stays False for ordinary changes: a flag on every insert and removal would
    # mean nothing (plan A5-D3).
    plan = plan_for([listed(0, day(20), at(21))], [stored(1, day(20), at(20), acts=[(7, "Nona")])])
    assert sorted(actions(plan)) == ["insert", "remove"]
    assert not any(d.needs_review for d in plan.shows)
    [removed] = only(plan, Action.REMOVE)
    assert removed.stored_id == 1


def test_a_time_that_appears_later_is_an_update() -> None:
    # Proves (A5-D3): a stored show with no time that now lists 8 PM is the same show getting its time, one update
    # (not a remove plus an insert). Terminal Bar's page has no times at all, so this is the shape of its first
    # change.
    plan = plan_for([listed(0, day(20), at(20))], [stored(1, day(20), None, acts=[(7, "Nona")])])
    [decision] = plan.shows
    assert decision.action is Action.UPDATE and decision.changes["start_time"] == (None, at(20))


def test_a_time_that_disappears_does_not_clear_the_stored_time() -> None:
    # Proves (A5-D4): an extraction that fails to read a time must not erase the stored one ("missing is tolerated,
    # wrong is not", A3-D4). The untimed listing still pairs with the stored 8 PM show (one of each, a blank time
    # on one side) and nothing changes.
    plan = plan_for([listed(0, day(20))], [stored(1, day(20), at(20), acts=[(7, "Nona")])])
    [decision] = plan.shows
    assert decision.action is Action.NO_OP and "start_time" not in decision.changes


def test_an_untimed_show_is_found_again_instead_of_duplicated_every_night() -> None:
    # Proves (A5-D3): in SQL a blank time never equals a blank time, so a naive (date, time) key would insert a fresh
    # copy of an untimed show and remove yesterday's, every night. The untimed listing finds its untimed twin.
    plan = plan_for([listed(0, day(20))], [stored(1, day(20), None, acts=[(7, "Nona")])])
    assert actions(plan) == ["no_op"]


def test_two_untimed_shows_on_one_date_pair_by_their_acts() -> None:
    # Proves (A5-D3; the 7th St Entry case, October 31): with two untimed shows on a date the lineups settle which
    # listing is which, even when the page lists them in the opposite order to how they were stored.
    plan = plan_for(
        [listed(0, day(31), acts=["Zhora"]), listed(1, day(31), acts=["Nona"])],
        [stored(1, day(31), None, acts=[(7, "Nona")]), stored(2, day(31), None, acts=[(8, "Zhora")])],
    )
    assert {d.listing.index: d.stored_id for d in plan.shows if d.listing} == {0: 2, 1: 1}
    assert set(actions(plan)) == {"no_op"}


def test_two_untimed_shows_whose_lineups_all_changed_are_inserted_and_removed_and_flagged() -> None:
    # Proves (A5-D3): when nothing ties a listing to a stored show, the pipeline doesn't guess. It inserts the
    # listings, removes the stored shows, and flags all four for a person (a guess was involved). Visible and
    # revertable, not silently wrong.
    plan = plan_for(
        [listed(0, day(31), acts=["Prince"]), listed(1, day(31), acts=["Sunny Day"])],
        [stored(1, day(31), None, acts=[(7, "Nona")]), stored(2, day(31), None, acts=[(8, "Zhora")])],
    )
    assert sorted(actions(plan)) == ["insert", "insert", "remove", "remove"]
    assert all(d.needs_review for d in plan.shows)


def test_two_untimed_shows_by_the_same_act_pair_in_a_fixed_order_and_are_flagged() -> None:
    # Proves (A5-D3, A5-PR1-5): an early and a late show by the same act, both untimed, tie on acts.
    # A tie that pairs nothing would insert and remove both shows every night, forever. A fixed order (listing
    # order against the stored shows' order) pairs them the same way each run, and the pair is flagged.
    plan = plan_for(
        [listed(0, day(22), acts=["Nona"]), listed(1, day(22), acts=["Nona"])],
        [stored(1, day(22), None, acts=[(7, "Nona")]), stored(2, day(22), None, acts=[(7, "Nona")])],
    )
    assert {d.listing.index: d.stored_id for d in plan.shows if d.listing} == {0: 1, 1: 2}
    assert all(d.needs_review for d in plan.shows)  # both halves of the guessed pairing, not just the first (A5-CR1-6)


def test_two_shows_at_one_time_pair_by_acts_not_by_the_lower_id() -> None:
    # Proves (A5-D3, A5-PR1-5): with two shows at 8 PM (two rooms), the listing that shares acts with the SECOND stored
    # show must get it, even though the first has the lower id. A greedy "first candidate wins" would swap the
    # lineups.
    plan = plan_for(
        [listed(0, day(20), at(20), acts=["Zhora"]), listed(1, day(20), at(20), acts=["Nona"])],
        [stored(1, day(20), at(20), acts=[(7, "Nona")]), stored(2, day(20), at(20), acts=[(8, "Zhora")])],
    )
    assert {d.listing.index: d.stored_id for d in plan.shows if d.listing} == {0: 2, 1: 1}
    assert not any(d.needs_review for d in plan.shows)


def test_a_scheduled_listing_outranks_a_cancelled_one_for_the_same_stored_show() -> None:
    # Proves (A5-CR1-5): a page carrying both "CANCELLED Nona 8 PM" and "Nona 8 PM" for one stored show must
    # settle the same way every night. The scheduled listing takes the stored show (a no-op) and the cancelled one,
    # with nothing left to cancel, is skipped. Ranked the other way (listing order), the pair swaps every run: two rows
    # alternating between removed and active.
    page = [listed(0, day(20), at(20), status="cancelled"), listed(1, day(20), at(20))]
    shows, artists = [stored(1, day(20), at(20), acts=[(7, "Nona")])], list(KNOWN)
    for _ in range(3):
        plan = plan_for(page, shows, artists)
        assert sorted(actions(plan)) == ["no_op", "skip"]
        shows, artists = apply_plan(plan, shows, artists)


def test_an_active_twin_outranks_a_removed_one_at_the_same_key() -> None:
    # Proves (A5-D3, A5-PR1-4): when a removed show and an active show share a key, the listing belongs to the active
    # one. Without active-first matching the tie-break could pick the removed twin, reactivate it, and then remove
    # the active one by absence.
    plan = plan_for(
        [listed(0, day(20), at(20), acts=["Nona"])],
        [
            stored(1, day(20), at(20), acts=[(7, "Nona")], status=ShowStatus.REMOVED),
            stored(2, day(20), at(20), acts=[(7, "Nona")]),
        ],
    )
    [decision] = plan.shows
    assert decision.stored_id == 2 and decision.action is Action.NO_OP


def test_an_old_removed_show_does_not_make_an_untimed_pair_ambiguous() -> None:
    # Proves (A5-D3, A5-PR1-4): a cancelled show from weeks ago on the same date must not turn "the only untimed
    # show on the date" into the several-candidates case. The untimed listing with changed acts is still an update
    # of the active untimed show, not an insert plus a removal.
    plan = plan_for(
        [listed(0, day(20), acts=["Zhora"])],
        [
            stored(1, day(20), at(20), acts=[(9, "Prince")], status=ShowStatus.REMOVED),
            stored(2, day(20), None, acts=[(7, "Nona")]),
        ],
    )
    [decision] = plan.shows
    assert decision.action is Action.UPDATE and decision.stored_id == 2


def test_a_returning_show_brings_the_same_row_back() -> None:
    # Proves (A5-D7): a show removed (say it was cancelled) and then listed again as scheduled is the same show: the
    # same row goes from removed to active, reason `reappeared`. Without this it would be inserted again, leaving
    # two rows for one real show.
    plan = plan_for(
        [listed(0, day(20), at(20))], [stored(1, day(20), at(20), acts=[(7, "Nona")], status=ShowStatus.REMOVED)]
    )
    [decision] = plan.shows
    assert decision.action is Action.UPDATE and decision.reason == "reappeared" and decision.stored_id == 1
    assert decision.changes["status"] == (ShowStatus.REMOVED, ShowStatus.ACTIVE)


def test_a_show_with_no_time_but_per_act_times_reconciles_without_inventing_a_show_time() -> None:
    # Proves: A2's eval found a multi-listing day coming back as one show with a blank time and per-act start
    # times (White Squirrel, seed 2), so reconcile "must not assume a show has a `time`" (build plan A5). It is
    # inserted with no start time, and the acts keep their own times.
    plan = plan_for([listed(0, day(20), None, acts=[ListedAct("Nona", at(19)), ListedAct("Zhora", at(21))])])
    [decision] = plan.shows
    assert decision.action is Action.INSERT and decision.start_time is None
    assert [e.start_time for e in decision.lineup] == [at(19), at(21)]


# ---------------------------------------------------------------------------
# Cancelled and postponed listings (A5-K3, A5-D6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["cancelled", "postponed"])
def test_a_cancelled_listing_removes_the_stored_show_and_says_why(status: str) -> None:
    # Proves (A5-D6; requirements, "Cancelled or postponed listings"): the show "was most likely extracted on an
    # earlier scan before it was cancelled, and the agent has to match it to that stored record and update it".
    # The status is `removed` (the read API hides it), and the audit reason keeps the distinction.
    plan = plan_for(
        [listed(0, day(20), at(20), status=status)], [stored(1, day(20), at(20), acts=[(7, "Nona")])]
    )
    [decision] = plan.shows
    assert decision.action is Action.REMOVE and decision.reason == status and decision.stored_id == 1


@pytest.mark.parametrize("status", ["cancelled", "postponed"])
def test_a_cancelled_listing_for_an_already_removed_show_changes_nothing(status: str) -> None:
    # Proves (A5-D6): a show already removed, listed as cancelled again, is a no-op. Without it every run would
    # write a removal for the same cancelled show.
    plan = plan_for(
        [listed(0, day(20), at(20), status=status)],
        [stored(1, day(20), at(20), acts=[(7, "Nona")], status=ShowStatus.REMOVED)],
    )
    [decision] = plan.shows
    assert decision.action is Action.NO_OP and decision.reason.startswith("already removed")


@pytest.mark.parametrize("status", ["cancelled", "postponed"])
def test_a_cancelled_listing_with_nothing_stored_is_skipped_not_inserted(status: str) -> None:
    # Proves (A5-D6): "Only on a venue's very first scan can a cancelled listing simply be ignored" and it is never
    # a show to display, so it must not become a row. A decision of `skip` (it has no audit outcome) records
    # that it was seen.
    plan = plan_for([listed(0, day(20), at(20), status=status)])
    [decision] = plan.shows
    assert decision.action is Action.SKIP and decision.action.outcome is None


def test_a_skipped_listing_creates_no_artist_and_makes_no_model_call() -> None:
    # Proves (A5-PR1-6): artists are resolved only for scheduled listings. A cancelled listing naming
    # an artist nobody has heard of must not cost a model call, create an artist, or leave a resolution for commit
    # to write. The default client is unscripted, so a model call here would fail the test.
    plan = plan_for([listed(0, day(20), at(20), acts=["Totally New Band"], status="cancelled")])
    assert actions(plan) == ["skip"] and plan.artists == ()


def test_a_cancelled_untimed_listing_does_not_pair_with_an_unrelated_show_by_date_alone() -> None:
    # Proves (A5-PR1-3): cancelled listings that the status merge ADDS have no time, so they always
    # reach the null-time pairing. By date alone, one cancelled listing and one stored show would pair, and an
    # unrelated show would be removed "as cancelled" on another show's cancellation. Here the stored show's own
    # listing was left out by validation (its date is in `excluded`), and a different act's cancellation on the same
    # date must neither remove it nor pair with it.
    plan = plan_for(
        [listed(0, day(20), None, acts=["Prince"], status="cancelled")],
        [stored(1, day(20), None, acts=[(8, "Zhora")])],
        excluded=[day(20)],
    )
    assert actions(plan) == ["skip"]


def test_a_cancelled_untimed_listing_pairs_with_the_show_whose_acts_it_names() -> None:
    # Proves (A5-D3, A5-D6): the cancellation pairs on shared acts, so the right show is removed.
    plan = plan_for(
        [listed(0, day(20), None, acts=["Zhora"], status="cancelled")],
        [stored(1, day(20), None, acts=[(8, "Zhora")])],
    )
    [decision] = plan.shows
    assert decision.action is Action.REMOVE and decision.reason == "cancelled" and decision.stored_id == 1


# ---------------------------------------------------------------------------
# What counts as a change (A5-D4, A5-D5)
# ---------------------------------------------------------------------------


def test_a_different_price_is_an_update_naming_the_field() -> None:
    # Proves: a show that matches but has different details updates the record (requirements, "Agent
    # Reconciliation"), and the decision says which field, old and new. Prices compare as money.
    plan = plan_for(
        [listed(0, day(20), at(20), admission_day=25.0)],
        [stored(1, day(20), at(20), acts=[(7, "Nona")], admission_day=money("20.00"))],
    )
    [decision] = plan.shows
    assert decision.action is Action.UPDATE and decision.changes == {"admission_day": (money("20.00"), money("25.00"))}


def test_a_price_equal_to_the_stored_one_is_no_change() -> None:
    # Proves: extraction carries a float and the column a Numeric(10, 2); 20.0 and Decimal("20.00") are the same
    # price. Compared as floats against Decimals they would differ or compare unreliably, and every priced show
    # would update every night. 19.99 is a real difference.
    same = plan_for(
        [listed(0, day(20), at(20), admission_day=20.0)],
        [stored(1, day(20), at(20), acts=[(7, "Nona")], admission_day=money("20.00"))],
    )
    different = plan_for(
        [listed(0, day(20), at(20), admission_day=19.99)],
        [stored(1, day(20), at(20), acts=[(7, "Nona")], admission_day=money("20.00"))],
    )
    assert actions(same) == ["no_op"] and actions(different) == ["update"]


def test_a_blank_field_does_not_erase_a_stored_value() -> None:
    # Proves (A5-D4): Monday's page had an end time and a poster; Tuesday's extraction has neither. The stored show
    # keeps both ("missing is tolerated, wrong is not"). A different non-blank value is a change.
    stored_show = stored(1, day(20), at(20), acts=[(7, "Nona")], end_time=at(23), image_url="https://x.example/p.png")
    blank = plan_for([listed(0, day(20), at(20))], [stored_show])
    changed = plan_for([listed(0, day(20), at(20), end_time=at(22, 30))], [stored_show])
    assert actions(blank) == ["no_op"]
    assert changed.shows[0].changes == {"end_time": (at(23), at(22, 30))}


def test_free_stated_over_a_stored_price_clears_the_price() -> None:
    # Proves (A5-D5, A5-PR1-1): the table forbids free admission together with a price (the
    # `show_free_admission_check` constraint). A stored $20 door price and a listing now saying FREE must become
    # free with NO price. Updating field by field (A5-D4's rule) would keep the $20 and produce a row A6 cannot
    # write.
    show = stored(1, day(20), at(20), acts=[(7, "Nona")], admission_day=money("20.00"))
    plan = plan_for([listed(0, day(20), at(20), free_admission=True)], [show])
    [decision] = plan.shows
    assert decision.changes == {"admission_day": (money("20.00"), None), "free_admission": (None, True)}
    assert not violates_free_check(show, decision.changes)


def test_a_price_stated_over_stored_free_clears_free() -> None:
    # Proves (A5-D5, A5-PR1-1): the other direction. Stored FREE and a listing now showing a $15 door price becomes
    # priced and no longer free.
    show = stored(1, day(20), at(20), acts=[(7, "Nona")], free_admission=True)
    plan = plan_for([listed(0, day(20), at(20), admission_day=15.0)], [show])
    [decision] = plan.shows
    assert decision.changes == {"admission_day": (None, money("15.00")), "free_admission": (True, None)}
    assert not violates_free_check(show, decision.changes)


def test_stating_only_the_door_price_clears_a_stored_advance_price() -> None:
    # Proves (A5-D5): the accepted cost. Admission is one unit, so a listing that states only the door price replaces
    # all three values, and the stored advance price goes. Pinned so that changing the rule is a decision, not an
    # accident.
    show = stored(
        1, day(20), at(20), acts=[(7, "Nona")], admission_advance=money("20.00"), admission_day=money("25.00")
    )
    plan = plan_for([listed(0, day(20), at(20), admission_day=25.0)], [show])
    assert plan.shows[0].changes == {"admission_advance": (money("20.00"), None)}


def test_a_listing_stating_no_admission_leaves_all_three_as_stored() -> None:
    # Proves (A5-D5): a listing that says nothing about admission changes nothing about it. Stored FREE stays FREE.
    show = stored(1, day(20), at(20), acts=[(7, "Nona")], free_admission=True)
    assert actions(plan_for([listed(0, day(20), at(20))], [show])) == ["no_op"]


def test_a_changed_page_url_alone_is_an_update() -> None:
    # Proves: `show.original_url` is "the web page where this information was extracted. The most recent instance"
    # (requirements, "Show"). When the venue's calendar URL changes, every show is updated once; a no-op there
    # would leave a link to a page that no longer lists it.
    plan = plan_for(
        [listed(0, day(20), at(20))],
        [stored(1, day(20), at(20), acts=[(7, "Nona")], original_url="https://old.example/events")],
    )
    assert plan.shows[0].changes == {"original_url": ("https://old.example/events", URL)}


def test_a_reordered_lineup_is_an_update_and_the_same_order_is_not() -> None:
    # Proves: performance order is part of the lineup (`show_artist.sequence_number`). The same acts in the same
    # order are a no-op; swapped, an update.
    show = stored(1, day(20), at(20), acts=[(7, "Nona"), (8, "Zhora")])
    same = plan_for([listed(0, day(20), at(20), acts=["Nona", "Zhora"])], [show])
    swapped = plan_for([listed(0, day(20), at(20), acts=["Zhora", "Nona"])], [show])
    assert actions(same) == ["no_op"] and actions(swapped) == ["update"]


def test_an_act_time_that_is_no_longer_stated_is_kept_and_a_different_one_is_a_change() -> None:
    # Proves (A5-D4): a route that stops stating per-act set times (the title-split route returns none) must not
    # erase the stored ones; the lineup is a no-op and the resulting lineup keeps the stored time. A different
    # stated time is an update.
    show = dataclasses.replace(stored(1, day(20), at(20)), lineup=(StoredLineupEntry(7, "Nona", at(21), 1),))
    kept = plan_for([listed(0, day(20), at(20), acts=["Nona"])], [show])
    moved = plan_for([listed(0, day(20), at(20), acts=[ListedAct("Nona", at(22))])], [show])
    assert actions(kept) == ["no_op"] and kept.shows[0].lineup[0].start_time == at(21)
    assert actions(moved) == ["update"]


# ---------------------------------------------------------------------------
# Lineups
# ---------------------------------------------------------------------------


def test_sequence_numbers_come_from_list_position_when_the_page_states_none() -> None:
    # Proves (requirements, "Agent Extraction: Fields": "make an assumption ... based on the order in which the
    # artists are listed"): acts in list order are numbered 1, 2, 3.
    plan = plan_for([listed(0, day(20), at(20), acts=["Nona", "Zhora", "Prince"])])
    assert [e.sequence_number for e in plan.shows[0].lineup] == [1, 2, 3]


def test_stated_sequence_numbers_are_kept_and_the_lineup_is_in_that_order() -> None:
    # Proves: a page that states the order is believed, and the lineup is in performance order (by sequence number),
    # whatever order the page lists the acts in. Stored lineups are read back in sequence order, so a lineup left in
    # list order would look changed against itself.
    plan = plan_for([listed(0, day(20), at(20), acts=[ListedAct("Zhora", None, 2), ListedAct("Nona", None, 1)])])
    assert [(e.artist_id, e.sequence_number) for e in plan.shows[0].lineup] == [(7, 1), (8, 2)]


def test_a_stated_order_that_differs_from_list_order_is_stable_run_to_run() -> None:
    # Proves (A5-CR1-2): a page that lists "Zhora" first but states Zhora is 2nd and Nona 1st must not be an
    # update every night. Written, read back and reconciled again, it is a no-op, three runs in a row.
    page = [listed(0, day(20), at(20), acts=[ListedAct("Zhora", None, 2), ListedAct("Nona", None, 1)])]
    shows, artists = [], list(KNOWN)
    for _ in range(3):
        plan = plan_for(page, shows, artists)
        shows, artists = apply_plan(plan, shows, artists)
    assert actions(plan) == ["no_op"]


def test_repeated_stated_numbers_are_renumbered_by_position() -> None:
    # Proves: two acts both stated as "1" would collide and could not be read back in a fixed order, so repeated numbers
    # are treated as not stated and the acts are numbered by list position.
    plan = plan_for([listed(0, day(20), at(20), acts=[ListedAct("Zhora", None, 1), ListedAct("Nona", None, 1)])])
    assert [(e.artist_id, e.sequence_number) for e in plan.shows[0].lineup] == [(8, 1), (7, 2)]


def test_a_mix_of_stated_and_derived_numbers_is_renumbered_by_position() -> None:
    # Proves: one stated number among unstated ones would collide with the derived ones (a stated 2 beside a
    # derived 2), so any gap renumbers everything by position.
    plan = plan_for([listed(0, day(20), at(20), acts=[ListedAct("Zhora", None, 2), ListedAct("Nona")])])
    assert [e.sequence_number for e in plan.shows[0].lineup] == [1, 2]


def test_an_artist_named_twice_in_one_show_appears_once() -> None:
    # Proves: `show_artist` is keyed by (show, artist), so a lineup naming the same artist twice ("Nona" and
    # "nona") would break the write. The first mention wins.
    plan = plan_for([listed(0, day(20), at(20), acts=["Nona", "nona", "Zhora"])])
    assert [e.artist_id for e in plan.shows[0].lineup] == [7, 8]


# ---------------------------------------------------------------------------
# After midnight
# ---------------------------------------------------------------------------


def test_a_show_after_midnight_sorts_after_that_nights_evening_shows() -> None:
    # Proves (requirements, "Times after midnight", decided by Ari October 11): a listing under Friday at 1:00 AM
    # is Friday night's show, sorted after Friday's evening shows and before Saturday's. The cutoff is 5:00 AM:
    # 5:00 is evening, 4:59 is after midnight. An untimed show comes last (as the frontend's nightSortKey does).
    friday, saturday = datetime.date(2026, 10, 16), datetime.date(2026, 10, 17)
    assert night_sort_key(friday, at(20)) < night_sort_key(friday, at(1)) < night_sort_key(saturday, at(20))
    assert night_sort_key(friday, at(4, 59)) > night_sort_key(friday, at(23))
    assert night_sort_key(friday, at(5)) < night_sort_key(friday, at(23))
    assert night_sort_key(friday, at(1)) < night_sort_key(friday, None) < night_sort_key(saturday, at(20))


def test_an_after_midnight_show_matches_by_its_plain_key() -> None:
    # Proves: the stored date is the listed night, so a 1:00 AM show listed under Friday matches a stored Friday
    # 1:00 AM show with no date arithmetic.
    plan = plan_for([listed(0, day(16), at(1))], [stored(1, day(16), at(1), acts=[(7, "Nona")])])
    assert actions(plan) == ["no_op"]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_feeding_a_plans_result_back_in_gives_all_no_ops() -> None:
    # Proves: reconcile is stable. Whatever it decides, once that is written the next run over the same page
    # finds nothing to do. If not, a show flips every night (a new row and an audit row per show, per night).
    # The page covers: a priced timed show, a show naming a brand-new artist, two untimed shows by the same act
    # (the tie case), and a show with no time and per-act times. `apply_plan` mirrors what commit will write.
    page = [
        listed(0, day(20), at(20), acts=["Nona"], admission_day=15.0),
        listed(1, day(21), None, acts=["Zhora", "Brand New Band"]),
        listed(2, day(22), None, acts=["Nona"]),
        listed(3, day(22), None, acts=["Nona"]),
        listed(4, day(23), None, acts=[ListedAct("Prince", at(19)), ListedAct("Zhora", at(21))]),
        listed(5, day(24), at(20), acts=[ListedAct("Zhora", None, 2), ListedAct("Nona", None, 1)]),
    ]
    first = plan_for(page)
    assert set(actions(first)) == {"insert"}
    shows, artists = apply_plan(first, [])
    second = plan_for(page, shows, artists)
    assert set(actions(second)) == {"no_op"}, [(d.listing.index, d.action, d.changes) for d in second.shows if d.listing]


def test_an_update_is_stable_after_it_is_applied() -> None:
    # Proves: after an update is written, the same page gives no-ops. Covers the changes reconcile reports being
    # sufficient to reproduce the listing (a price, a new opener, a time that appeared).
    before = [stored(1, day(20), None, acts=[(7, "Nona")], admission_day=money("10.00"))]
    page = [listed(0, day(20), at(20), acts=["Nona", "Zhora"], admission_day=12.0)]
    first = plan_for(page, before)
    assert actions(first) == ["update"]
    shows, artists = apply_plan(first, before)
    assert actions(plan_for(page, shows, artists)) == ["no_op"]


def test_a_removal_is_stable_after_it_is_applied() -> None:
    # Proves: a show removed because the page dropped it is not removed again on the next run.
    before = [stored(1, day(20), at(20), acts=[(7, "Nona")]), stored(2, day(21), at(20), acts=[(8, "Zhora")])]
    page = [listed(0, day(21), at(20), acts=["Zhora"]), listed(1, day(25), at(20), acts=["Prince"])]
    first = plan_for(page, before)
    assert sorted(actions(first)) == ["insert", "no_op", "remove"]
    shows, artists = apply_plan(first, before)
    assert sorted(actions(plan_for(page, shows, artists))) == ["no_op", "no_op"]


# ---------------------------------------------------------------------------
# Layering
# ---------------------------------------------------------------------------


def test_reconcile_and_artist_match_do_not_import_the_state() -> None:
    # Proves (A5-PR1-7): `state.py` imports reconcile's and artist_match's types for its new fields, so
    # they must not import `state.py` back (apps/api/AGENTS.md: keep the imports a DAG). Run in a fresh interpreter,
    # because this one has already imported everything.
    code = (
        "import sys, agent_worker.reconcile, agent_worker.artist_match; "
        "sys.exit(1 if 'agent_worker.state' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
