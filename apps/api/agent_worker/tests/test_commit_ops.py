"""Tests for `commit.py`: what to write, as a pure function of reconcile's plan.

Milestone A6 (docs/dev/implementations/a6-commit.md, Test approach §1). `commit.build_ops` turns a `ReconcilePlan`
into the list of writes (`ShowOp`s) the calendar writer executes, and `snapshot_of` turns a row into the JSON a
revert would restore. Neither touches a database, so every rule is tested here with plans reconcile itself builds
from small, readable inputs (`reconcile_support.plan_for`).

How to read it: each section names one rule, builds the plan that rule is about, and asserts the operations.
Expected values are literals taken from `data-model-initial.md` (§2 columns, §3 snapshots), the A5 decisions
(A5-D4 to A5-D7) and the A6 decisions (A6-D1, A6-D3), never from the code under test: a price of `19.99` must
come out as the string `"19.99"` whatever `to_price` does.
"""

import datetime
import json
import subprocess
import sys
from decimal import Decimal
from typing import Any

import pytest

from agent_worker.commit import (
    MIN_OPS_FOR_ALL_FAILED,
    SNAPSHOT_COLUMNS,
    CommitResult,
    ShowFailure,
    build_ops,
    snapshot_of,
    summary_counts,
)
from agent_worker.reconcile import Action, ListedAct
from agent_worker.tests.reconcile_support import URL, at, day, listed, plan_for, stored
from app.enums import AuditOutcome, ShowStatus

VENUE = 4

# ---------------------------------------------------------------------------
# Which decisions become operations (A6-D1)
# ---------------------------------------------------------------------------


def a_mixed_plan():  # type: ignore[no-untyped-def]
    """One plan with every action: no-op (#1), update (#2, an opener added), remove (#3, absent), insert (a new show on
    the 25th) and skip (a cancelled listing on the 27th with nothing stored). Stored #1 to #3 are Nona, Zhora and Prince
    at 8 PM on the 20th, 22nd and 23rd; the window runs from the 12th to the 27th, so #3 is inside it."""
    return plan_for(
        [
            listed(0, day(20), at(20), acts=["Nona"]),
            listed(1, day(22), at(20), acts=["Zhora", "Nona"]),
            listed(2, day(25), at(20), acts=["Prince"]),
            listed(3, day(27), at(20), acts=["Zhora"], status="cancelled"),
        ],
        [
            stored(1, day(20), at(20), acts=[(7, "Nona")]),
            stored(2, day(22), at(20), acts=[(8, "Zhora")]),
            stored(3, day(23), at(20), acts=[(9, "Prince")]),
        ],
    )


def test_insert_update_and_remove_each_become_one_operation_and_no_op_and_skip_none() -> None:
    # Proves (A6-D1): only writes become operations. The plan has five decisions (no-op, update, remove, insert,
    # skip); the three that write are operations, and the unchanged show and the skipped cancelled listing are not,
    # so the audit trail grows with change, not with the number of shows times the number of nights.
    plan = a_mixed_plan()
    assert sorted(d.action.value for d in plan.shows) == ["insert", "no_op", "remove", "skip", "update"]
    ops = build_ops(plan, VENUE, URL)
    assert sorted(op.action.value for op in ops) == ["insert", "remove", "update"]
    assert {op.outcome for op in ops} == {AuditOutcome.INSERTED, AuditOutcome.UPDATED, AuditOutcome.REMOVED}


def test_inserts_and_updates_come_before_removals_each_in_calendar_order() -> None:
    # Proves (A6 "Settled details", removals last): if a run stops half way, a time change is left as a duplicate rather
    # than a gap. The plan is in calendar order (update on the 22nd, remove on the 23rd, insert on the 25th), so the
    # removal on the 23rd must still come last.
    ops = build_ops(a_mixed_plan(), VENUE, URL)
    assert [(op.action, op.decision.date.day) for op in ops] == [
        (Action.UPDATE, 22), (Action.INSERT, 25), (Action.REMOVE, 23),
    ]


def test_a_withheld_removal_is_never_an_operation() -> None:
    # Proves (A5-D10): the removal guard holds back a mass removal, and commit must not write what reconcile withheld.
    # The page lists one new show on the 25th; four stored shows (20th to 23rd) are inside the window and absent, which
    # is 4 of 4 (at least 3 and over half), so all four are withheld. The only operation is the new show's insert.
    plan = plan_for(
        [listed(0, day(25), at(20), acts=["Nona"])],
        [
            stored(1, day(20), at(20), acts=[(7, "Nona")]),
            stored(2, day(21), at(20), acts=[(8, "Zhora")]),
            stored(3, day(22), at(20), acts=[(9, "Prince")]),
            stored(4, day(23), at(20), acts=[(8, "Zhora")]),
        ],
    )
    assert len(plan.withheld) == 4
    assert [op.action for op in build_ops(plan, VENUE, URL)] == [Action.INSERT]


def test_a_cancelled_removal_and_an_absent_removal_are_both_status_removed_writes_with_their_reason() -> None:
    # Proves (A5-D6): a cancelled listing and a show that vanished are both soft deletes, `status = removed`, and the
    # audit row keeps the difference as the reconcile reason ("cancelled" against "absent from the page").
    plan = plan_for(
        [
            listed(0, day(20), at(20), acts=["Nona"], status="cancelled"),
            listed(1, day(24), at(20), acts=["Zhora"]),
        ],
        [stored(1, day(20), at(20), acts=[(7, "Nona")]), stored(2, day(22), at(20), acts=[(9, "Prince")])],
    )
    removals = [op for op in build_ops(plan, VENUE, URL) if op.action is Action.REMOVE]
    assert sorted((op.stored_id, op.reconcile_reason) for op in removals) == [
        (1, "cancelled"), (2, "absent from the page"),
    ]
    assert all(op.values == {"status": ShowStatus.REMOVED} and op.lineup is None for op in removals)


# ---------------------------------------------------------------------------
# The values of an insert
# ---------------------------------------------------------------------------


def only_insert(listing_fields: dict[str, Any]) -> Any:
    """The single insert operation for one new Nona show on the 20th at 8 PM with these extra fields."""
    plan = plan_for([listed(0, day(20), at(20), acts=["Nona"], **listing_fields)])
    [op] = build_ops(plan, VENUE, URL)
    return op


def test_prices_are_converted_at_the_write_not_carried_as_floats() -> None:
    # Proves (build plan A6): the extraction carries floats and the columns are Numeric(10, 2), so the write converts
    # through the decimal string. 19.99 must be exactly Decimal("19.99") (not 19.989999999999999...), 20.0 must be
    # Decimal("20.00"), and an unstated price stays None. The expected strings are literals.
    op = only_insert({"admission_advance": 19.99, "admission_day": 20.0})
    assert op.values["admission_advance"] == Decimal("19.99") and str(op.values["admission_advance"]) == "19.99"
    assert op.values["admission_day"] == Decimal("20.00") and str(op.values["admission_day"]) == "20.00"
    assert only_insert({}).values["admission_advance"] is None


def test_an_insert_carries_the_listing_the_venue_the_url_and_status_active() -> None:
    # Proves (data-model-initial.md §2): a new show is written with the listing's own date, time, end time, free flag
    # and poster, the venue it belongs to, the page it came from (`original_url`) and `status = active`.
    op = only_insert({"end_time": at(23), "free_admission": True, "image_url": "https://venue.example/poster.png"})
    assert op.values == {
        "venue_id": VENUE, "date": day(20), "start_time": at(20), "end_time": at(23),
        "admission_advance": None, "admission_day": None, "free_admission": True,
        "image_url": "https://venue.example/poster.png", "original_url": URL, "status": ShowStatus.ACTIVE,
    }


def test_a_listing_with_no_time_writes_no_start_time() -> None:
    # Proves (A5, "reconcile never assumes a time"): an untimed show is written untimed, not with an invented time.
    plan = plan_for([listed(0, day(20), None, acts=["Nona"])])
    [op] = build_ops(plan, VENUE, URL)
    assert op.values["start_time"] is None


# ---------------------------------------------------------------------------
# The values of an update
# ---------------------------------------------------------------------------


def only_update(listing: Any, stored_show: Any) -> Any:
    """The single operation for one listing against one stored show (an update)."""
    [op] = build_ops(plan_for([listing], [stored_show]), VENUE, URL)
    return op


def test_an_update_writes_only_the_changed_columns_and_leaves_the_lineup_alone() -> None:
    # Proves (A5-D4, A5-D5): `values` are the new side of each change and nothing else, and when the lineup did not
    # change `lineup` is None (the writer leaves show_artist untouched). A new end time and a day price change; the
    # advance price, the free flag, the poster and the time do not appear.
    op = only_update(
        listed(0, day(20), at(20), acts=["Nona"], end_time=at(23), admission_day=20.0),
        stored(1, day(20), at(20), acts=[(7, "Nona")]),
    )
    assert op.action is Action.UPDATE and op.stored_id == 1
    assert op.values == {"end_time": at(23), "admission_day": Decimal("20.00")}
    assert op.lineup is None


def test_a_blank_field_in_the_listing_is_not_written() -> None:
    # Proves (A5-D4): a field the new listing leaves blank never erases a stored value. The stored show has an end time
    # and a poster, the listing states neither (it adds only a day price), and neither blank appears in `values`.
    op = only_update(
        listed(0, day(20), at(20), acts=["Nona"], admission_day=15.0),
        stored(1, day(20), at(20), acts=[(7, "Nona")], end_time=at(23), image_url="https://venue.example/p.png"),
    )
    assert set(op.values) == {"admission_day"}


def test_a_changed_lineup_is_passed_whole_and_a_lineup_only_update_has_no_column_values() -> None:
    # Proves (A5-D4 and the A6 "lineup replaced wholesale" detail): an opener added to a stored show changes only the
    # lineup, so `values` is empty and `lineup` is the decision's resulting lineup (both acts, in performance order).
    op = only_update(
        listed(0, day(20), at(20), acts=["Zhora", "Nona"]),
        stored(1, day(20), at(20), acts=[(7, "Nona")]),
    )
    assert op.values == {}
    assert op.lineup is not None and [(e.artist_id, e.sequence_number) for e in op.lineup] == [(8, 1), (7, 2)]


def test_a_returning_removed_show_is_written_back_to_active() -> None:
    # Proves (A5-D7): a removed show that is listed again is the same row, `status` back to active.
    op = only_update(
        listed(0, day(20), at(20), acts=["Nona"]),
        stored(1, day(20), at(20), acts=[(7, "Nona")], status=ShowStatus.REMOVED),
    )
    assert op.reconcile_reason == "reappeared" and op.values["status"] is ShowStatus.ACTIVE


# ---------------------------------------------------------------------------
# Artists that do not exist yet
# ---------------------------------------------------------------------------


def test_new_artist_names_are_the_first_seen_spelling_of_each_unknown_act() -> None:
    # Proves (requirements, "Agent Artist Creation & Matching"; A5-D8): a new artist is created with the spelling first
    # seen on a page, once however many shows name it. "Sunny Day" and "SUNNY DAY" tidy to one key; the op for each
    # show names the key and the first-seen spelling. A known artist (Nona) needs no name.
    plan = plan_for([
        listed(0, day(20), at(20), acts=["Sunny Day", "Nona"]),
        listed(1, day(21), at(20), acts=[ListedAct("SUNNY DAY")]),
    ])
    first, second = build_ops(plan, VENUE, URL)
    assert first.new_artist_names == {"sunny day": "Sunny Day"}
    assert second.new_artist_names == {"sunny day": "Sunny Day"}
    [known] = build_ops(plan_for([listed(0, day(20), at(20), acts=["Nona"])]), VENUE, URL)
    assert known.new_artist_names == {}


# ---------------------------------------------------------------------------
# The snapshot (A6-D3)
# ---------------------------------------------------------------------------

# The columns of `show` a snapshot holds, typed out from data-model-initial.md §2 (everything except the two
# timestamps). `SNAPSHOT_COLUMNS` is DERIVED from the model; this literal list is what makes a new column a visible,
# deliberate change: a migration that adds one turns the pin below red (A6-PR1-10).
LITERAL_COLUMNS = (
    "id", "venue_id", "event_id", "date", "start_time", "end_time", "age_restriction", "serves_alcohol", "setting",
    "seating", "admission_advance", "admission_day", "free_admission", "image_url", "original_url", "status",
)


def a_row(**changes: Any) -> dict[str, Any]:
    """A `show` row as the writer reads it: every snapshot column, plus the two timestamps a snapshot must drop."""
    row: dict[str, Any] = {
        "id": 5, "venue_id": 4, "event_id": None, "date": datetime.date(2026, 10, 20), "start_time": datetime.time(20, 0),
        "end_time": None, "age_restriction": None, "serves_alcohol": None, "setting": None, "seating": None,
        "admission_advance": None, "admission_day": Decimal("20.00"), "free_admission": None, "image_url": None,
        "original_url": "https://venue.example/events", "status": ShowStatus.ACTIVE,
        "created_at": datetime.datetime(2026, 10, 1, 12, 0), "updated_at": datetime.datetime(2026, 10, 2, 12, 0),
    }
    row.update(changes)
    return row


def test_the_snapshot_columns_are_exactly_the_show_columns_minus_the_timestamps() -> None:
    # Proves (A6-D3, A6-PR1-10): the pinned list. `SNAPSHOT_COLUMNS` is derived from `Show.__table__`; this fails when a
    # migration adds a column, so adding one to snapshots (and to their documentation) is a decision, not an accident.
    assert set(SNAPSHOT_COLUMNS) == set(LITERAL_COLUMNS)


def test_a_snapshot_is_restorable_json_with_the_lineup_in_performance_order() -> None:
    # Proves (data-model-initial.md §3, "what a revert restores"): the exact JSON. A price is the string "20.00" (not
    # the float 20.0, which cannot carry cents without a binary tail), times and dates are ISO, the enum is its value,
    # the timestamps are absent, and the lineup is in sequence order whatever order it was read in.
    lineup = [
        {"artist_id": 8, "start_time": None, "sequence_number": 2},
        {"artist_id": 7, "start_time": datetime.time(20, 30), "sequence_number": 1},
    ]
    snap = snapshot_of(a_row(), lineup)
    assert snap == {
        "id": 5, "venue_id": 4, "event_id": None, "date": "2026-10-20", "start_time": "20:00:00", "end_time": None,
        "age_restriction": None, "serves_alcohol": None, "setting": None, "seating": None, "admission_advance": None,
        "admission_day": "20.00", "free_admission": None, "image_url": None,
        "original_url": "https://venue.example/events", "status": "active",
        "lineup": [
            {"artist_id": 7, "start_time": "20:30:00", "sequence_number": 1},
            {"artist_id": 8, "start_time": None, "sequence_number": 2},
        ],
    }
    json.dumps(snap)  # raises if anything non-JSON got through


def test_a_snapshot_with_a_column_missing_from_its_input_is_an_error() -> None:
    # Proves (A6-PR1-10): `snapshot_of` takes exactly the snapshot columns, so a row read without one of them is a bug
    # that fails loudly instead of a snapshot that silently lacks a column a revert needs.
    row = a_row()
    del row["image_url"]
    with pytest.raises(KeyError):
        snapshot_of(row, [])


# ---------------------------------------------------------------------------
# The result and the summary counts
# ---------------------------------------------------------------------------


def test_summary_counts_has_exactly_five_keys_written_from_the_result_and_the_rest_from_the_plan() -> None:
    # Proves (A6-PR2-8): `counts` is {inserted, updated, removed, no_op, skip}; the first three are what was WRITTEN
    # (from the result), the last two are what reconcile decided to leave alone (from the plan). Failures are never a
    # key here (they are the `failed` list).
    plan = a_mixed_plan()
    result = CommitResult(written={"inserted": 1, "updated": 1, "removed": 0}, artists_created=0, failures=(), total_ops=3)
    assert summary_counts(plan, result) == {"inserted": 1, "updated": 1, "removed": 0, "no_op": 1, "skip": 1}


def a_failure(n: int) -> ShowFailure:
    return ShowFailure("insert", day(20 + n), at(20), None, "new show", "22003", "DBAPIError: numeric field overflow")


def test_all_failed_needs_at_least_three_operations_that_all_failed() -> None:
    # Proves (A6 "an all-fail run is flagged"): three operations, every one failed, is flagged (it looks like a bug, not
    # three bad listings); two of two is not (too few to say), and three operations with two failures is not.
    assert MIN_OPS_FOR_ALL_FAILED == 3
    failed = tuple(a_failure(n) for n in range(3))
    assert CommitResult({}, 0, failed, total_ops=3).all_failed
    assert not CommitResult({}, 0, failed[:2], total_ops=2).all_failed
    assert not CommitResult({}, 0, failed[:2], total_ops=3).all_failed


# ---------------------------------------------------------------------------
# Layering
# ---------------------------------------------------------------------------


def test_commit_does_not_import_the_state_or_the_audit_module() -> None:
    # Proves (A6 Design, import order): `state.py` imports commit's types for its new fields and `audit.py` imports
    # the state, so commit must import neither (apps/api/AGENTS.md: keep the imports a DAG). Run in a fresh
    # interpreter, because this one has already imported everything.
    code = (
        "import sys, agent_worker.commit; "
        "sys.exit(1 if {'agent_worker.state', 'agent_worker.audit'} & set(sys.modules) else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
