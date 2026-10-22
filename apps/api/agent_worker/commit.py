"""Commit's decision-to-writes logic: which writes reconcile's plan asks for, and what a snapshot of a show is.

HOW TO READ THIS
  Reconcile (reconcile.py) decides what should happen to the calendar and writes nothing. Commit executes that
  decision. This module is the **pure half** of commit: it turns a `ReconcilePlan` into the list of writes
  (`ShowOp`s) and says what a snapshot of a show is. The **impure half**, which runs the writes against Postgres,
  is `calendar_writer.py`. Keeping them apart is the same split as reconcile and commit themselves (arch-initial.md §7):
  "what should be written" is a rule tested without a database; "was it written" is a database concern.

  No I/O, no clock, no model, and **no import of `state.py` or `audit.py`**: the state imports these types for its
  new fields (`commit_ops`, `commit_result`) and `audit.py` imports the state, so the dependency runs the other way
  (reconcile, artist_match <- commit <- state <- audit <- calendar_writer). A test enforces it.

  Read in this order:

  1. The types: `ShowOp` (one write), `ShowFailure` and `CommitResult` (what happened).
  2. `build_ops`: the plan in, the writes out. Only insert, update and remove are writes (A6-D1); no-op and skip are not,
     and a removal the guard withheld (A5-D10) is never one. Inserts and updates come first, removals last.
  3. `insert_values`, `changed_values`: the columns a write sets. Prices are converted here, at the write.
  4. `snapshot_of`: a show as restorable JSON, for `audit_log.previous_value` / `new_value` (A6-D3).

WHY IT'S SHAPED THIS WAY
  Commit adds no judgement. Every rule about what the calendar should look like (a blank field never erases a stored
  one, the admission fields change as a unit, a cancelled listing is a soft delete) was decided in reconcile and is
  already in `ShowDecision.changes`; `changed_values` applies `changes` as given and does not re-derive them. The
  decisions that ARE commit's (A6-D1 to A6-D3) are cited where they apply.

docs/dev/implementations/a6-commit.md.
"""

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_core import to_jsonable_python

from agent_worker.reconcile import (
    Action,
    LineupEntry,
    Listing,
    ReconcilePlan,
    ShowDecision,
    to_price,
)
from app.db.models import Show
from app.enums import AuditOutcome, ShowStatus

# ---------------------------------------------------------------------------
# What a snapshot holds (A6-D3)
# ---------------------------------------------------------------------------

# A snapshot is the whole `show` row except its two timestamps, plus the lineup. The timestamps are left out because a
# revert restores what the agent (or a person) set, not when the row was last touched. The column list is DERIVED from
# the model, not typed out, so a column added by a later migration appears in snapshots without anyone remembering to;
# test_commit_ops.py pins the current list against a literal one, so that change is deliberate and visible.
SNAPSHOT_EXCLUDED = frozenset({"created_at", "updated_at"})
SNAPSHOT_COLUMNS: tuple[str, ...] = tuple(c.key for c in Show.__table__.columns if c.key not in SNAPSHOT_EXCLUDED)

# A run with at least this many operations, every one of which failed with a decision error, is flagged `all_failed`
# in the summary: several shows failing the same way looks like a bug in the writes, not like several bad listings
# (A6-PR2-2). Three mirrors `ReconcilePolicy.min_removals_to_guard`.
MIN_OPS_FOR_ALL_FAILED = 3

# ---------------------------------------------------------------------------
# The types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShowOp:
    """One write to the calendar: a show to insert, update or remove, and everything the writer needs to do it.

    `values` are the `show` columns to set: all of them for an insert, only the changed ones for an update, just
    `status` for a removal. `lineup` is the show's resulting lineup when the writer must replace its `show_artist` rows
    (an insert, or an update whose lineup changed), and None when it must leave them alone. `new_artist_names` maps the
    comparison key of each act that has no `artist` row yet to the spelling to create it with (the first one seen).
    """

    decision: ShowDecision
    values: dict[str, Any]
    lineup: tuple[LineupEntry, ...] | None
    new_artist_names: dict[str, str] = field(default_factory=dict)

    @property
    def action(self) -> Action:
        return self.decision.action

    @property
    def stored_id(self) -> int | None:
        return self.decision.stored_id

    @property
    def outcome(self) -> AuditOutcome:
        """What this write's audit row calls it. Only writes become operations, so an action always has one."""
        outcome = self.decision.action.outcome
        assert outcome is not None
        return outcome

    @property
    def reconcile_reason(self) -> str:
        return self.decision.reason

    @property
    def needs_review(self) -> bool:
        return self.decision.needs_review


@dataclass(frozen=True)
class ShowFailure:
    """One show whose write the database refused (A6-D2): enough to say WHICH show, and why."""

    action: str
    date: datetime.date
    time: datetime.time | None
    stored_id: int | None
    reconcile_reason: str
    sqlstate: str | None
    error: str


@dataclass(frozen=True)
class CommitResult:
    """What a commit run did. `written` counts the shows written by outcome (`inserted`, `updated`, `removed`);
    `total_ops` is how many writes were attempted, so `all_failed` can tell a few bad shows from a broken write."""

    written: dict[str, int] = field(default_factory=dict)
    artists_created: int = 0
    failures: tuple[ShowFailure, ...] = ()
    total_ops: int = 0

    @property
    def all_failed(self) -> bool:
        return self.total_ops >= MIN_OPS_FOR_ALL_FAILED and len(self.failures) == self.total_ops


# ---------------------------------------------------------------------------
# The plan, as writes
# ---------------------------------------------------------------------------


def insert_values(listing: Listing, venue_id: int, original_url: str) -> dict[str, Any]:
    """The columns of a new show: the listing's own facts, the venue it belongs to, the page it came from, and
    `status = active`. Prices go through `reconcile.to_price` (the decimal string, then two places), the conversion A5
    defined once so that comparing a listing with a stored show and storing it agree."""
    return {
        "venue_id": venue_id,
        "date": listing.date,
        "start_time": listing.time,
        "end_time": listing.end_time,
        "admission_advance": to_price(listing.admission_advance),
        "admission_day": to_price(listing.admission_day),
        "free_admission": listing.free_admission,
        "image_url": listing.image_url,
        "original_url": original_url,
        "status": ShowStatus.ACTIVE,
    }


def changed_values(changes: Mapping[str, tuple[Any, Any]]) -> dict[str, Any]:
    """The columns of an update: the new side of each `(old, new)` pair in the decision's `changes`, without `lineup`
    (the lineup is rows in another table, handled separately). Reconcile already applied the rules about what counts as
    a change, so this does not re-derive them."""
    return {column: new for column, (_, new) in changes.items() if column != "lineup"}


def build_ops(plan: ReconcilePlan, venue_id: int, original_url: str) -> tuple[ShowOp, ...]:
    """The writes a plan asks for, in the order to do them.

    Only insert, update and remove are writes (A6-D1): a no-op wrote nothing and a skip has nothing stored, so neither
    becomes an operation, and the audit trail grows with change. A removal the guard withheld (`plan.withheld`) is not in
    `plan.shows` and so is never written (A5-D10). Inserts and updates come first, in calendar order, and removals last:
    if a run stops half way, a time change (the 8 PM show removed, the 9 PM show inserted) is then left as a duplicate
    rather than a gap.
    """
    names = {resolution.key: resolution.name for resolution in plan.artists}
    writes: list[ShowOp] = []
    removals: list[ShowOp] = []
    for decision in plan.shows:
        if decision.action is Action.INSERT:
            assert decision.listing is not None  # an insert is always a listing with no stored twin
            values = insert_values(decision.listing, venue_id, original_url)
            lineup: tuple[LineupEntry, ...] | None = decision.lineup
        elif decision.action is Action.UPDATE:
            values = changed_values(decision.changes)
            lineup = decision.lineup if "lineup" in decision.changes else None
        elif decision.action is Action.REMOVE:
            values, lineup = {"status": ShowStatus.REMOVED}, None
        else:  # NO_OP and SKIP write nothing
            continue
        new_names = {e.key: names.get(e.key, e.name) for e in (lineup or ()) if e.artist_id is None}
        op = ShowOp(decision, values, lineup, new_names)
        (removals if decision.action is Action.REMOVE else writes).append(op)
    return tuple(writes + removals)


def summary_counts(plan: ReconcilePlan, result: CommitResult) -> dict[str, int]:
    """The summary row's `counts`: exactly five keys, so its shape doesn't depend on the run. `inserted`, `updated` and
    `removed` are what was WRITTEN (from the result); `no_op` and `skip` are what reconcile decided to leave alone
    (from the plan). Failures are not a key: they are the summary's `failed` list (A6-PR2-8)."""
    decided = plan.counts()
    return {
        "inserted": result.written.get("inserted", 0),
        "updated": result.written.get("updated", 0),
        "removed": result.written.get("removed", 0),
        "no_op": decided[Action.NO_OP.value],
        "skip": decided[Action.SKIP.value],
    }


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------


def snapshot_of(columns: Mapping[str, Any], lineup: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A show as JSON that a revert could restore it from (A6-D3).

    Takes exactly the keys in `SNAPSHOT_COLUMNS` from `columns` (a missing one is a `KeyError`: a snapshot that silently
    lacked a column would be a revert that silently lost it; an extra one, the timestamps, is dropped). `lineup` entries
    are `{artist_id, start_time, sequence_number}`, put in performance order. Conversion is `to_jsonable_python`: a
    `Decimal` becomes its decimal string (`"20.00"`, never a float, which cannot hold cents without a binary tail), times
    and dates become ISO strings, an enum its value.
    """
    snapshot: dict[str, Any] = {column: columns[column] for column in SNAPSHOT_COLUMNS}
    snapshot["lineup"] = [
        {"artist_id": e["artist_id"], "start_time": e["start_time"], "sequence_number": e["sequence_number"]}
        for e in sorted(lineup, key=lambda e: (e["sequence_number"] is None, e["sequence_number"] or 0, e["artist_id"]))
    ]
    converted: dict[str, Any] = to_jsonable_python(snapshot)
    return converted
