"""Builders and stand-ins for the reconcile tests: stored shows, listings, known artists, and a mirror of the write.

WHAT THIS IS
  Reconcile (reconcile.py) is pure: it takes the page's listings, the stored shows and the known artists as plain data
  and returns a plan. So its tests do not need a database or a model; they need small, readable pieces of data. This
  module builds those pieces, so that each test states only the one fact it is about ("a stored 8 PM show", "a listing
  with no time") and the rest is filled in sensibly.

HOW TO READ IT, top to bottom
  1. Constants: the fetch date, the page URL and the model settings every test shares.
  2. Date and time shorthands (`day`, `at`).
  3. Builders for the two sides reconcile compares: `stored` (what is already in the database) and `listed` (what the
     venue's page shows now), plus the artists that "exist" (`KNOWN`).
  4. Running reconcile: `inputs_for`, `plan_for`, and two readers of a plan (`actions`, `only`).
  5. `apply_plan`: a test-only mirror of the write that A6's `commit_node` will do. This is the one non-obvious piece.
  6. Mirrors of two data rules (`violates_free_check`, `money`).
  7. Builders for the extraction side (`extracted`, `validated`), for tests that go through real validation.

THE ONE NON-OBVIOUS PIECE: apply_plan
  Nothing writes to the calendar until A6, so a test cannot run reconcile twice against a real database and see the
  second run find nothing to do. `apply_plan` stands in for that write: it turns (the stored shows before, a plan) into
  the stored shows that WOULD exist afterwards. The tests then feed that result back into reconcile and check the
  property that stops a show flipping every night: after a plan is applied, the same page must give all no-ops
  (idempotency). It is deliberately dumb. It applies each decision's `changes` and lineup and nothing else, so a
  decision that leaves something out shows up as a second run that still wants to change the show. A6 replaces it with
  a real database round trip.

Dates are October 2026, and `FETCHED` (October 12) is the fetch date, matching `fakes.FETCHED`: a listing on the 20th is
a week ahead, one on the 8th is four days in the past. Plan references use the A5 scope (`A5-D1` and so on), as
`docs/dev/conventions.md` asks of code.
"""

import dataclasses
import datetime
import decimal
from collections.abc import Iterable, Sequence
from typing import Any

from agent_worker.artist_match import KnownArtist
from agent_worker.llm import RequestOptions
from agent_worker.reconcile import (
    Action,
    ListedAct,
    Listing,
    ReconcileInputs,
    ReconcilePlan,
    StoredLineupEntry,
    StoredShow,
    build_plan,
    covered_window,
    to_price,
)
from agent_worker.schemas import ShowExtraction, VenuePageExtraction
from agent_worker.tests.fakes import scripted_client
from agent_worker.validation import ValidationResult, validate_extraction
from app.enums import ShowStatus

# ---------------------------------------------------------------------------
# Constants every test shares
# ---------------------------------------------------------------------------

# The date the (imaginary) fetch ran. Reconcile's window starts here (A5-D1), so a stored show before this date is
# "past" and one after it is "upcoming". The same date as `fakes.FETCHED`, so a graph test and a pure test agree.
FETCHED = datetime.date(2026, 10, 12)

# The venue page's URL. Reconcile stores it as each show's `original_url` and compares it on every run, so the
# builders below default a stored show's URL to this one: a test about something else then doesn't also see a change.
URL = "https://venue.example/events"

# The model settings reconcile is given. Only `model` matters to a test (it is what an audit row records as `model_used`);
# temperature 0 matches the pipeline's own setting.
OPTIONS = RequestOptions(model="test-model", temperature=0.0)

# ---------------------------------------------------------------------------
# Date and time shorthands
# ---------------------------------------------------------------------------


def day(n: int) -> datetime.date:
    """October `n`, 2026. `day(20)` reads better in a test than `datetime.date(2026, 10, 20)` six times over."""
    return datetime.date(2026, 10, n)


def at(hour: int, minute: int = 0) -> datetime.time:
    """A clock time: `at(20)` is 8 PM, `at(1)` is 1 AM (after midnight, so it belongs to the night before), and
    `at(22, 30)` is 10:30 PM."""
    return datetime.time(hour, minute)


# ---------------------------------------------------------------------------
# The two sides reconcile compares
# ---------------------------------------------------------------------------


def stored(
    show_id: int, date: datetime.date, start: datetime.time | None = None, acts: Sequence[tuple[int, str]] = (),
    status: ShowStatus = ShowStatus.ACTIVE, **fields: Any,
) -> StoredShow:
    """A show that is ALREADY in the database, as the calendar reader would hand it to reconcile.

    `show_id` is its row id. `start` is `show.start_time` (None means the show has no time). `acts` is its lineup as
    (artist id, artist name) pairs in performance order; the builder numbers them 1, 2, 3 as `show_artist` would. Any
    other column (`end_time`, prices, `image_url`, `free_admission`) goes in as a keyword. `original_url` defaults to
    the page's URL so that a test about something else does not also see a changed URL.

    Example: `stored(1, day(20), at(20), acts=[(7, "Nona")])` is show 1, October 20 at 8 PM, with Nona on the bill.
    """
    fields.setdefault("original_url", URL)
    lineup = tuple(StoredLineupEntry(artist_id, name, None, i) for i, (artist_id, name) in enumerate(acts, start=1))
    return StoredShow(id=show_id, date=date, start_time=start, status=status, lineup=lineup, **fields)


def listed(
    index: int, date: datetime.date, time: datetime.time | None = None, acts: Iterable[str | ListedAct] = ("Nona",),
    status: str = "scheduled", **fields: Any,
) -> Listing:
    """One entry on the venue's page, after extraction and validation (a "kept" listing).

    `index` is its position among the page's kept listings (reconcile uses it to tell two listings apart). `time` is
    the time the page states (None means none stated). `acts` are the performers in the order the page lists them: a
    plain name, or a `ListedAct` when the test needs that act to carry its own set time or a stated order. `status`
    is "scheduled", "cancelled" or "postponed". Other fields (`end_time`, `admission_day`, `free_admission`,
    `image_url`) go in as keywords.

    Example: `listed(0, day(20), at(20), acts=["Nona", "Zhora"])` is a page entry for October 20 at 8 PM naming two acts.
    """
    return Listing(
        index=index, date=date, time=time, status=status, **fields,
        acts=tuple(a if isinstance(a, ListedAct) else ListedAct(a) for a in acts),
    )


# The artists that "exist" in the tests' imaginary database, with ids a test can write directly (`(7, "Nona")` in a
# stored lineup means this Nona). Three clearly different names, so a test never lands in the ambiguous middle by
# accident: that would trigger a model question, and the default client in `plan_for` fails on an unscripted call.
NONA = KnownArtist(7, "Nona")
ZHORA = KnownArtist(8, "Zhora")
PRINCE = KnownArtist(9, "Prince")
KNOWN = [NONA, ZHORA, PRINCE]

# ---------------------------------------------------------------------------
# Running reconcile
# ---------------------------------------------------------------------------


def inputs_for(
    listings: Sequence[Listing], *, fetched: datetime.date = FETCHED, excluded: Iterable[datetime.date] = ()
) -> ReconcileInputs:
    """The inputs reconcile reads from a validated page, built the way the pipeline builds them.

    `excluded` are the dates of listings validation left out for naming no act (they are still on the page, so they
    protect a stored show on their date from the soft delete). The window, from the fetch date to the latest date the
    page evidences, is derived by the same `covered_window` the pipeline uses (A5-D1), not typed in by the test, so a
    test cannot drift from the real rule.
    """
    excluded = frozenset(excluded)
    return ReconcileInputs(tuple(listings), excluded, covered_window(listings, excluded, fetched), fetched)


def plan_for(
    listings: Sequence[Listing], stored_shows: Sequence[StoredShow] = (), known: Sequence[KnownArtist] = KNOWN, *,
    excluded: Iterable[datetime.date] = (), client: Any = None,
) -> ReconcilePlan:
    """The plan reconcile makes for these page listings against these stored shows and known artists.

    This is the function most tests call. With no `client`, the model is an unscripted fake: a test that reaches the
    model by accident (a name close to a known artist) fails with an AssertionError instead of quietly passing. A test
    that WANTS the model passes a scripted client (`fakes.scripted_client`).
    """
    return build_plan(
        inputs_for(listings, excluded=excluded), stored_shows, known, original_url=URL,
        client=client or scripted_client({}), options=OPTIONS,
    )


def actions(plan: ReconcilePlan) -> list[str]:
    """The plan's actions in plan order, as plain strings (`["insert", "no_op"]`), for compact assertions."""
    return [d.action.value for d in plan.shows]


def only(plan: ReconcilePlan, action: Action) -> list[Any]:
    """The plan's decisions that have this action (for example every `Action.REMOVE`), in plan order."""
    return [d for d in plan.shows if d.action is action]


# ---------------------------------------------------------------------------
# The mirror of the write
# ---------------------------------------------------------------------------


def apply_plan(
    plan: ReconcilePlan, before: Sequence[StoredShow], known: Sequence[KnownArtist] = KNOWN
) -> tuple[list[StoredShow], list[KnownArtist]]:
    """Test-only mirror of commit (see the module docstring): the stored shows and artists after `plan` is applied.

    Takes the stored shows `before` and the artists that exist (`known`), applies every decision in the plan the way
    A6's `commit_node` will, and returns the new (stored shows, artists). Insert adds a show, update changes the fields
    named in `changes` and replaces the lineup, remove marks a show removed, and no-op and skip change nothing. New
    artists get fresh ids, once per distinct name however many shows name them.
    """
    # Working copies, keyed by id so a decision can find the row it changes.
    shows = {s.id: s for s in before}
    artists = {a.id: a for a in known}
    # The ids handed out to artists the plan says to create, by the name's comparison key. Reconcile plans a new artist
    # as a lineup entry with no id; commit must create it ONCE even if three shows name it, and this is that rule.
    new_ids: dict[str, int] = {}
    next_show = max(shows, default=0) + 1
    next_artist = max(artists, default=0) + 1

    def artist_id(entry: Any) -> int:
        """The id for a lineup entry: the existing artist's, or a freshly created one (the same one every time)."""
        nonlocal next_artist
        if entry.artist_id is not None:
            return int(entry.artist_id)
        if entry.key not in new_ids:  # one new artist per distinct name, however many shows name it
            new_ids[entry.key] = next_artist
            artists[next_artist] = KnownArtist(next_artist, entry.name)
            next_artist += 1
        return new_ids[entry.key]

    def lineup(decision: Any) -> tuple[StoredLineupEntry, ...]:
        """A decision's resulting lineup as stored `show_artist` rows (artist ids resolved, order and set times kept)."""
        return tuple(
            StoredLineupEntry(artist_id(e), e.name, e.start_time, e.sequence_number) for e in decision.lineup
        )

    for d in plan.shows:
        if d.action is Action.INSERT:
            # A new row built from the listing itself: reconcile's insert carries the listing and the lineup.
            listing = d.listing
            assert listing is not None  # an insert always carries the listing it was built from
            shows[next_show] = StoredShow(
                id=next_show, date=d.date, start_time=listing.time, end_time=listing.end_time,
                admission_advance=to_price(listing.admission_advance), admission_day=to_price(listing.admission_day),
                free_admission=listing.free_admission, image_url=listing.image_url, original_url=URL, lineup=lineup(d),
            )
            next_show += 1
        elif d.action is Action.UPDATE:
            # Apply exactly the fields the decision names (new value of each `(old, new)` pair). The lineup and the
            # status are handled separately: the lineup is replaced wholesale, the status may flip back to active.
            assert d.stored_id is not None  # an update always names the stored show it changes
            current = shows[d.stored_id]
            values = {k: v[1] for k, v in d.changes.items() if k not in ("lineup", "status")}
            new_status = d.changes["status"][1] if "status" in d.changes else current.status
            shows[d.stored_id] = dataclasses.replace(current, status=new_status, lineup=lineup(d), **values)
        elif d.action is Action.REMOVE:
            # A soft delete: the row stays, its status says removed.
            assert d.stored_id is not None  # a removal always names the stored show it retires
            shows[d.stored_id] = dataclasses.replace(shows[d.stored_id], status=ShowStatus.REMOVED)
        # NO_OP and SKIP change nothing.
    return list(shows.values()), list(artists.values())


# ---------------------------------------------------------------------------
# Mirrors of two data rules
# ---------------------------------------------------------------------------


def violates_free_check(
    show: StoredShow, changes: dict[str, tuple[Any, Any]]
) -> bool:
    """True if applying `changes` to `show` would break the table's CHECK constraint on free admission.

    The `show` table forbids `free_admission` together with a price (`show_free_admission_check`,
    data-model-initial.md). A6's write would fail with a database error on such a row. This mirrors the constraint so a
    test can assert, without a database, that reconcile never produces an update that breaks it (A5-D5). For each of
    the three admission fields it takes the value after the change if the change names it, else the stored value.
    """
    advance = changes["admission_advance"][1] if "admission_advance" in changes else show.admission_advance
    day_price = changes["admission_day"][1] if "admission_day" in changes else show.admission_day
    free = changes["free_admission"][1] if "free_admission" in changes else show.free_admission
    return bool(free) and (advance is not None or day_price is not None)


def money(value: str) -> decimal.Decimal:
    """A price as the `Numeric(10, 2)` column holds it: `money("20.00")`. A string, never a float, so the test's
    expected value is exact (a float's binary tail is not the price the page said)."""
    return decimal.Decimal(value)


# ---------------------------------------------------------------------------
# The extraction side (for tests that go through real validation)
# ---------------------------------------------------------------------------


def extracted(
    date: datetime.date, acts: Sequence[str] = ("Nona",), time: datetime.time | None = datetime.time(20, 0), **fields: Any
) -> ShowExtraction:
    """One show as the extraction model returns it: the raw record, before validation has looked at it.

    The defaults make a well-formed show (8 PM, one act, confidence 0.9). Pass `acts=[]` for a show that names no act,
    which validation leaves out (the case several window tests need), or another `date` to put it outside the plausible
    window.
    """
    return ShowExtraction(
        venue="The Venue", date=date, time=time, is_ambiguous=False, confidence=0.9,
        acts=[{"name": a} for a in acts], **fields,  # type: ignore[arg-type]
    )


def validated(
    shows: Sequence[ShowExtraction], fetched: datetime.date = FETCHED
) -> tuple[VenuePageExtraction, VenuePageExtraction, ValidationResult]:
    """Run real validation over these raw shows. Returns (the raw extraction, the validated extraction with excluded
    shows taken out, the validation result): exactly the three things `prepare_inputs` reads, so a test goes through
    the same index mapping the pipeline does (the raw positions in the findings, the validated list without them)."""
    raw = VenuePageExtraction(page_readable=True, shows=list(shows))
    result, kept = validate_extraction(raw, source="model", notes={}, fetched_on=fetched, page_html="", page_text="")
    return raw, raw.model_copy(update={"shows": kept}), result
