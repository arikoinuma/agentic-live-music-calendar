"""Reconcile's decision logic: what should happen to the calendar, given the page and what is stored.

HOW TO READ THIS
  Reconcile compares two things for one venue: the **listings** on the venue's calendar page as this run
  extracted them, and the **stored shows** already in our `show` table. It decides, for each, one of:

      insert    a listing with no stored twin
      update    a listing whose twin differs (details, lineup), or a removed show that came back
      no_op     a listing whose twin is unchanged
      remove    a stored show the page no longer lists (inside the range the page reached), or one the
                page marks cancelled or postponed
      skip      a cancelled/postponed listing with nothing stored to cancel

  and writes nothing. `commit_node` (A6) executes the plan; keeping "decide" and "do" apart is what lets the
  audit trail tell a bad decision from a failed write (arch-initial.md §7).

  Everything in this module is a pure function of its arguments: no database, no model client of its own
  (the one model question, about an ambiguous artist name, is `artist_match.py`), no clock, and **no import of
  `state.py`** (the state imports these types for its new fields, so the dependency runs the other way:
  validation, schemas, artist_match <- reconcile <- state <- nodes). Read in this order:

  1. The data types: `StoredShow` (a row, from `calendar_reader.py`), `Listing` (a kept extracted show),
     `Coverage` (how far the page reached), `ShowDecision` and `ReconcilePlan` (the answer).
  2. `night_sort_key`, `prepare_inputs`, `covered_window`, `load_request`: turn the validated extraction into
     the inputs, and say which stored shows to read.
  3. `match_shows` (**A5-K1**): pair each listing with its stored twin. `plan_for_listing` (**A5-K3**): what a pair,
     or a lone listing, means. `show_changes`: has anything changed.
  4. `removed_by_absence` (**A5-K2**) and `withhold_if_mass_removal`: the soft delete and its guard.
  5. `build_plan`: runs the steps in order.

WHY IT'S SHAPED THIS WAY
  Every rule that decides what the calendar looks like is a decision Ari made in a5-reconcile.md, cited where
  it applies (A5-D1 to A5-D12 and "Settled details"). The ones that are easy to get wrong silently are covered by tests
  that state their expected values from the requirements, not from this code: the window (a show past the page's
  last date is out of sight, not gone), the null time (blank is not equal to blank, in SQL or in a sensible
  match), and the idempotency property (feeding a plan's own result back in must give all no-ops, or a show
  flips every night).

docs/dev/implementations/a5-reconcile.md.
"""

import datetime
import decimal
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from agent_worker.artist_match import (
    DEFAULT_ARTIST_POLICY,
    ArtistMatchPolicy,
    ArtistResolution,
    KnownArtist,
    artist_key,
    resolve_artists,
)
from agent_worker.llm import RequestOptions
from agent_worker.schemas import VenuePageExtraction
from agent_worker.sources.jsonld import NIGHT_CUTOFF
from agent_worker.validation import CheckCode, ValidationResult, check_plausibility
from app.enums import AuditOutcome, ShowStatus

# ---------------------------------------------------------------------------
# What is stored, what is listed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredLineupEntry:
    """One artist on a stored show, as `show_artist` holds it."""

    artist_id: int
    artist_name: str
    start_time: datetime.time | None = None
    sequence_number: int | None = None


@dataclass(frozen=True)
class StoredShow:
    """A `show` row and its lineup, as the calendar reader returns it (every status, `removed` included)."""

    id: int
    date: datetime.date
    start_time: datetime.time | None = None
    end_time: datetime.time | None = None
    status: ShowStatus = ShowStatus.ACTIVE
    admission_advance: decimal.Decimal | None = None
    admission_day: decimal.Decimal | None = None
    free_admission: bool | None = None
    image_url: str | None = None
    original_url: str | None = None
    lineup: tuple[StoredLineupEntry, ...] = ()

    @property
    def lineup_keys(self) -> frozenset[str]:
        return frozenset(artist_key(entry.artist_name) for entry in self.lineup)

    def ordered_lineup(self) -> list[StoredLineupEntry]:
        """The lineup in performance order (stated sequence first, unnumbered last)."""
        return sorted(self.lineup, key=lambda e: (e.sequence_number is None, e.sequence_number or 0, e.artist_id))


@dataclass(frozen=True)
class ListedAct:
    name: str
    start_time: datetime.time | None = None
    sequence_number: int | None = None


@dataclass(frozen=True)
class Listing:
    """One kept extracted show, reduced to what reconcile reads. `index` is its position among the kept shows.

    A plain dataclass, not the extraction's pydantic model: the extraction schema has variants (with and
    without `status`), and reconcile should depend on neither.
    """

    index: int
    date: datetime.date
    time: datetime.time | None = None
    end_time: datetime.time | None = None
    acts: tuple[ListedAct, ...] = ()
    status: str = "scheduled"  # "scheduled" | "cancelled" | "postponed" (A2.1-D12)
    admission_advance: float | None = None
    admission_day: float | None = None
    free_admission: bool | None = None
    image_url: str | None = None

    @property
    def is_scheduled(self) -> bool:
        return self.status == "scheduled"

    @property
    def act_keys(self) -> frozenset[str]:
        return frozenset(artist_key(act.name) for act in self.acts)


@dataclass(frozen=True)
class Coverage:
    """The dates a fetch reached, both ends inclusive (A5-D1): the only dates where "not on the page" can mean "gone"."""

    start: datetime.date
    end: datetime.date

    def contains(self, day: datetime.date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class ReconcilePolicy:
    """The removal guard's numbers (A5-D10), named in one place the way `RetryPolicy` names the retry settings."""

    min_removals_to_guard: int = 3
    max_removal_share: float = 0.5


DEFAULT_RECONCILE_POLICY = ReconcilePolicy()

# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------


class Action(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    NO_OP = "no_op"
    REMOVE = "remove"
    SKIP = "skip"  # a cancelled/postponed listing with nothing stored: no insert, no row

    @property
    def outcome(self) -> AuditOutcome | None:
        """What A6's per-show audit row will call this (`SKIP` writes none)."""
        return {
            Action.INSERT: AuditOutcome.INSERTED, Action.UPDATE: AuditOutcome.UPDATED,
            Action.NO_OP: AuditOutcome.NO_OP, Action.REMOVE: AuditOutcome.REMOVED, Action.SKIP: None,
        }[self]


@dataclass(frozen=True)
class LineupEntry:
    """One act of a show's resulting lineup. `artist_id` is None for an artist commit is to create (named `name`);
    equal `key`s mean the same new artist."""

    key: str
    artist_id: int | None
    name: str
    start_time: datetime.time | None = None
    sequence_number: int | None = None


@dataclass(frozen=True)
class ShowDecision:
    """What to do with one show. `changes` is `{field: (old, new)}` for an update; `lineup` is the resulting lineup
    for an insert, update or no-op."""

    action: Action
    date: datetime.date
    start_time: datetime.time | None
    reason: str
    listing: Listing | None = None
    stored_id: int | None = None
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    lineup: tuple[LineupEntry, ...] = ()
    needs_review: bool = False


@dataclass(frozen=True)
class ReconcilePlan:
    """Everything reconcile decided for one venue run. `withheld` are removals the guard held back (A5-D10)."""

    coverage: Coverage | None
    shows: tuple[ShowDecision, ...]
    artists: tuple[ArtistResolution, ...] = ()
    withheld: tuple[ShowDecision, ...] = ()

    def counts(self) -> dict[str, int]:
        """Decisions per action, every action present (so an audit row's shape doesn't depend on the run)."""
        counts = {action.value: 0 for action in Action}
        for decision in self.shows:
            counts[decision.action.value] += 1
        return counts


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def night_sort_key(day: datetime.date, time: datetime.time | None) -> tuple[datetime.date, int, datetime.time]:
    """Order within a venue's calendar: by the night a show is listed under, with a time before the 5:00 AM
    cutoff after that night's evening shows, and an untimed show last (requirements-initial.md, "Times after
    midnight"; the frontend's `nightSortKey` and the API order the same way). The stored `date` is already the
    listed night, so matching needs no date arithmetic; this is only for ordering."""
    if time is None:
        return (day, 2, datetime.time.min)
    return (day, 1 if time < NIGHT_CUTOFF else 0, time)


@dataclass(frozen=True)
class ReconcileInputs:
    """The page, in the terms reconcile needs: listings, dates the splitter left out, and how far it reached."""

    listings: tuple[Listing, ...]
    excluded_dates: frozenset[datetime.date]
    coverage: Coverage | None
    fetched_on: datetime.date


def listings_from(extraction: VenuePageExtraction | None) -> list[Listing]:
    """The kept shows as `Listing`s. `status` is read with a default: `ShowExtraction` doesn't declare it, only the
    pipeline's schema variant does (`schemas.show_model`), and the image route has none."""
    if extraction is None:
        return []
    return [
        Listing(
            index=i, date=show.date, time=show.time, end_time=show.end_time,
            acts=tuple(ListedAct(a.name, a.start_time, a.sequence_number) for a in show.acts),
            status=getattr(show, "status", "scheduled"),
            admission_advance=show.admission_advance, admission_day=show.admission_day,
            free_admission=show.free_admission, image_url=show.image_url,
        )
        for i, show in enumerate(extraction.shows)
    ]


def excluded_listing_dates(
    extraction: VenuePageExtraction | None, validation: ValidationResult | None, fetched_on: datetime.date
) -> frozenset[datetime.date]:
    """Dates of listings validation left out because they named no act, on a plausible date. They are still on the page
    (A5-D1), and may be a real show the splitter missed, so they protect a stored show on their date from the soft delete,
    and they count as evidence the page reached that date.

    Two traps. `Finding.show_index` is a position in `extraction.shows`, the RAW list, not in the validated list (which
    has the excluded shows removed): reading the wrong list protects the wrong dates. And validation leaves a show out
    for naming no act BEFORE it checks the date, so a placeholder entry ("Private event") with a date years away arrives
    here too; its date is not evidence the page reached that far, and would stretch the window over every stored show in
    between. So a date outside the plausible window is dropped (A5-CR1-1).
    """
    if extraction is None or validation is None:
        return frozenset()
    return frozenset(
        extraction.shows[f.show_index].date
        for f in validation.findings
        if f.code is CheckCode.EXCLUDED_NO_ACTS and f.show_index is not None and f.show_index < len(extraction.shows)
        and not check_plausibility(extraction.shows[f.show_index], fetched_on).date_out_of_window
    )


def covered_window(
    listings: Sequence[Listing], excluded_dates: Iterable[datetime.date], fetched_on: datetime.date
) -> Coverage | None:
    """A5-D1: from `fetched_on` to the latest date the page evidences (a kept listing, cancelled ones included, or a
    listing we left out). None when there is no evidence of reach: a confirmed-empty page (A5-D2), or a page whose
    listings are all before `fetched_on`, which would give `end < start`."""
    dates = [listing.date for listing in listings] + list(excluded_dates)
    if not dates:
        return None
    end = max(dates)
    return Coverage(fetched_on, end) if end >= fetched_on else None


def prepare_inputs(
    extraction: VenuePageExtraction | None, validated: VenuePageExtraction | None,
    validation: ValidationResult | None, fetched_on: datetime.date,
) -> ReconcileInputs:
    """Everything reconcile reads from the validated page, as plain data (the trace wrapper calls this too, to know
    which stored shows to load)."""
    listings = listings_from(validated)
    excluded = excluded_listing_dates(extraction, validation, fetched_on)
    return ReconcileInputs(tuple(listings), excluded, covered_window(listings, excluded, fetched_on), fetched_on)


def load_request(inputs: ReconcileInputs) -> tuple[datetime.date, datetime.date] | None:
    """The date range of stored shows to read, or None to read nothing.

    Matching needs stored shows on every LISTING date, and listings reach back up to 31 days (pages keep last week's
    shows); removal needs only the window. So the range is wider than the window on the left. Reading just the window
    would find no stored twin for a past-dated listing and insert it again every night, and those duplicates sit
    outside the removal window forever.
    """
    dates = [listing.date for listing in inputs.listings]
    if inputs.coverage is not None:
        dates += [inputs.coverage.start, inputs.coverage.end]
    return (min(dates), max(dates)) if dates else None


# ---------------------------------------------------------------------------
# A5-K1: pairing listings with stored shows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchResult:
    pairs: tuple[tuple[Listing, StoredShow], ...]
    unpaired_listings: tuple[Listing, ...]
    unpaired_stored: tuple[StoredShow, ...]
    review_listings: frozenset[int]  # listing indexes a person should look at (a guess was involved)
    review_stored: frozenset[int]  # stored show ids, likewise


def _order_listing(listing: Listing) -> tuple[Any, ...]:
    return (night_sort_key(listing.date, listing.time), listing.index)


def _order_stored(stored: StoredShow) -> tuple[Any, ...]:
    return (night_sort_key(stored.date, stored.start_time), stored.id)


def _overlap(listing: Listing, stored: StoredShow) -> int:
    """How many act names the two share (tidied with `artist_key`)."""
    return len(listing.act_keys & stored.lineup_keys)


def _assign_by_acts(
    candidates: list[tuple[Listing, StoredShow]], *, need_overlap: bool
) -> list[tuple[Listing, StoredShow, bool]]:
    """Pair candidates globally: highest shared-act overlap first, ties broken by status (a scheduled listing before a
    cancelled or postponed one), then listing order, then the stored show's order, so the same input always pairs
    the same way. Each side is used once. With `need_overlap` a pair
    must share at least one act. The third item of each result says the pair was settled by the order tie-break
    (another unused candidate scored the same), which is flagged for review.

    A global assignment, not "each listing takes its first candidate": with two shows at one time, the listing
    that shares acts with the second stored show must get it even though the first has the lower id.
    """
    ranked = sorted(
        candidates,
        key=lambda p: (-_overlap(*p), not p[0].is_scheduled, _order_listing(p[0]), _order_stored(p[1])),
    )
    taken_listings: set[int] = set()
    taken_stored: set[int] = set()
    out: list[tuple[Listing, StoredShow, bool]] = []
    for listing, stored in ranked:
        if listing.index in taken_listings or stored.id in taken_stored:
            continue
        overlap = _overlap(listing, stored)
        if need_overlap and overlap < 1:
            continue
        tied = any(
            _overlap(other_l, other_s) == overlap
            for other_l, other_s in candidates
            if (other_l.index == listing.index) != (other_s.id == stored.id)
            and other_l.index not in taken_listings and other_s.id not in taken_stored
        )
        taken_listings.add(listing.index)
        taken_stored.add(stored.id)
        out.append((listing, stored, tied))
    return out


def _null_time_pairs(
    listings: list[Listing], stored: list[StoredShow]
) -> list[tuple[Listing, StoredShow, bool]]:
    """A5-K1: pair what the timed pass left over on one date, where a missing time is involved (A5-D3).

    Two different times never pair (that is a time change: a cancelled show plus a new one). A missing time on
    EITHER side is the only thing that can pair across times. With exactly one listing and one stored show left it is
    unambiguous and they pair; with several, shared act names settle it, and a cancelled or postponed listing pairs
    only that way, never by date alone (its status is evidence about a specific show).
    """
    # The key is (venue, date, time), exact, with no fuzzy matching on shows (arch-initial.md §7), and the subtlety is
    # what a NULL does. In SQL `NULL = NULL` is not true, so a naive key never finds an untimed show: every night would
    # insert a duplicate and remove yesterday's (A5-D3). Python's `None == None` is True, which is the opposite trap:
    # comparing the two times directly would pair two different untimed shows but not an untimed one with a timed one,
    # so the test is "either side is missing", not "the times are equal". A tie among several candidates is broken the
    # same way every run (`_assign_by_acts`), so nothing churns.
    pairable = [(l, s) for l in listings for s in stored if l.time is None or s.start_time is None]
    if len(listings) == 1 and len(stored) == 1 and pairable and listings[0].is_scheduled:
        return [(*pairable[0], False)]
    return _assign_by_acts(pairable, need_overlap=True)


def match_shows(listings: Sequence[Listing], stored: Sequence[StoredShow]) -> MatchResult:
    """Pair each listing with its stored twin (A5-D3): per date, **active stored shows first**, then removed ones for
    the listings still unpaired (so a returning show is found, but a removed twin never outranks an active one).
    Each round runs a timed pass (same time) then a null-time pass (`_null_time_pairs`).

    Flags `needs_review` only where a guess was involved: a pair settled by the order tie-break, or a null time
    left unpaired while the other side has an unpaired show that date. An ordinary new timed show or an ordinary
    removal is not flagged, or the flag would list every show and mean nothing.
    """
    pairs: list[tuple[Listing, StoredShow]] = []
    taken_listings: set[int] = set()
    taken_stored: set[int] = set()
    review_listings: set[int] = set()
    pools = [
        [s for s in stored if s.status is ShowStatus.ACTIVE],
        [s for s in stored if s.status is ShowStatus.REMOVED],
    ]
    for pool in pools:
        for day in sorted({listing.date for listing in listings}):
            left_l = sorted((l for l in listings if l.date == day and l.index not in taken_listings), key=_order_listing)
            left_s = sorted((s for s in pool if s.date == day and s.id not in taken_stored), key=_order_stored)
            if not left_l or not left_s:
                continue
            timed = [(l, s) for l in left_l for s in left_s if l.time is not None and l.time == s.start_time]
            found = _assign_by_acts(timed, need_overlap=False)
            for listing, show, _ in found:
                pairs.append((listing, show))
                taken_listings.add(listing.index)
                taken_stored.add(show.id)
            if any(tied for _, _, tied in found):  # a guessed pairing is flagged whole, not just its first half
                review_listings |= {listing.index for listing, _, _ in found}
            left_l = [l for l in left_l if l.index not in taken_listings]
            left_s = [s for s in left_s if s.id not in taken_stored]
            if left_l and left_s:
                found = _null_time_pairs(left_l, left_s)
                for listing, show, _ in found:
                    pairs.append((listing, show))
                    taken_listings.add(listing.index)
                    taken_stored.add(show.id)
                if any(tied for _, _, tied in found):
                    review_listings |= {listing.index for listing, _, _ in found}

    unpaired_l = [l for l in listings if l.index not in taken_listings]
    unpaired_s = [s for s in stored if s.id not in taken_stored]
    review_stored: set[int] = set()
    for day in {l.date for l in unpaired_l if l.is_scheduled} & {s.date for s in unpaired_s if s.status is ShowStatus.ACTIVE}:
        day_l = [l for l in unpaired_l if l.date == day and l.is_scheduled]
        day_s = [s for s in unpaired_s if s.date == day and s.status is ShowStatus.ACTIVE]
        if any(l.time is None for l in day_l) or any(s.start_time is None for s in day_s):
            review_listings |= {l.index for l in day_l}
            review_stored |= {s.id for s in day_s}
    return MatchResult(
        tuple(pairs), tuple(unpaired_l), tuple(unpaired_s), frozenset(review_listings), frozenset(review_stored)
    )


# ---------------------------------------------------------------------------
# Lineups and changes
# ---------------------------------------------------------------------------


def to_price(value: float | None) -> decimal.Decimal | None:
    """An extracted price as the `Numeric(10, 2)` column holds it: through `str` (a float's binary tail is not the
    price the page said), then two places. A6 uses this for the write, so comparison and storage agree."""
    return None if value is None else decimal.Decimal(str(value)).quantize(decimal.Decimal("0.01"))


def lineup_for(listing: Listing, resolutions: dict[str, ArtistResolution]) -> tuple[LineupEntry, ...]:
    """The listing's acts as a resolved lineup.

    * An artist named twice in one show appears once (`show_artist` is keyed by (show, artist)); the first mention wins.
    * Stated sequence numbers are kept only when every act has one AND they are all different; otherwise all are
      numbered by list position (requirements: "make an assumption ... based on the order in which the artists are
      listed"), because a mix of stated and derived numbers can collide, and so can a number stated twice.
    * The lineup is returned in performance order (by sequence number), because that is the order a stored lineup is read
      back in; a page that lists "Zhora" first but states Zhora is second would otherwise look changed against itself on
      every run (A5-CR1-2).
    """
    entries: list[LineupEntry] = []
    seen: set[tuple[str, Any]] = set()
    for act in listing.acts:
        key = artist_key(act.name)
        resolution = resolutions[key]
        identity = ("id", resolution.artist_id) if resolution.artist_id is not None else ("new", key)
        if identity in seen:
            continue
        seen.add(identity)
        entries.append(LineupEntry(key, resolution.artist_id, act.name, act.start_time, act.sequence_number))
    stated = [entry.sequence_number for entry in entries]
    if not all(n is not None for n in stated) or len(set(stated)) != len(stated):
        entries = [replace(entry, sequence_number=i) for i, entry in enumerate(entries, start=1)]
    return tuple(sorted(entries, key=lambda entry: entry.sequence_number or 0))


def merge_lineup(lineup: tuple[LineupEntry, ...], stored: StoredShow) -> tuple[LineupEntry, ...]:
    """A5-D4 for a lineup: an act whose own set time is unstated now keeps the time stored for the same artist."""
    stored_times = {e.artist_id: e.start_time for e in stored.lineup}
    return tuple(
        replace(entry, start_time=stored_times.get(entry.artist_id))
        if entry.start_time is None and entry.artist_id is not None else entry
        for entry in lineup
    )


def show_changes(
    stored: StoredShow, listing: Listing, lineup: tuple[LineupEntry, ...], original_url: str
) -> dict[str, tuple[Any, Any]]:
    """What differs between the stored show and the listing: `{field: (old, new)}`, empty meaning no-op.

    A5-D4: a field the listing leaves blank never erases a stored value; only a different non-blank value is a change.
    A5-D5: `admission_advance`, `admission_day` and `free_admission` are one unit. If the listing states any of them it
    replaces all three (an unstated one becomes blank, so the result can never be "free" and priced at once, which
    the table's CHECK forbids); if it states none, all three stay as stored.
    The extraction's `time` is the column `start_time`. `lineup` is the resolved lineup after `merge_lineup`.
    """
    changes: dict[str, tuple[Any, Any]] = {}
    plain: list[tuple[str, Any, Any]] = [
        ("start_time", listing.time, stored.start_time),
        ("end_time", listing.end_time, stored.end_time),
        ("image_url", listing.image_url, stored.image_url),
    ]
    for column, new, old in plain:
        if new is not None and new != old:
            changes[column] = (old, new)
    if any(v is not None for v in (listing.admission_advance, listing.admission_day, listing.free_admission)):
        admission: list[tuple[str, Any, Any]] = [
            ("admission_advance", to_price(listing.admission_advance), stored.admission_advance),
            ("admission_day", to_price(listing.admission_day), stored.admission_day),
            ("free_admission", listing.free_admission, stored.free_admission),
        ]
        for column, new, old in admission:
            if new != old:
                changes[column] = (old, new)
    if stored.original_url != original_url:
        changes["original_url"] = (stored.original_url, original_url)
    old_lineup = tuple((e.artist_id, e.start_time) for e in stored.ordered_lineup())
    new_lineup = tuple((e.artist_id, e.start_time) for e in lineup)
    if old_lineup != new_lineup:  # a new artist (id None) never equals a stored one
        changes["lineup"] = (old_lineup, new_lineup)
    return changes


# ---------------------------------------------------------------------------
# A5-K3: what a listing means
# ---------------------------------------------------------------------------


def plan_for_listing(
    listing: Listing, stored: StoredShow | None, lineup: tuple[LineupEntry, ...], original_url: str
) -> ShowDecision:
    """What one listing means, given its stored twin (or none) (A5-D6, A5-D7, A2.1-D12)."""

    def decide(action: Action, reason: str, *, start_time: datetime.time | None, **fields: Any) -> ShowDecision:
        return ShowDecision(action, listing.date, start_time, reason, listing=listing, **fields)

    if listing.status != "scheduled":  # cancelled / postponed
        # A cancelled or postponed listing is evidence about a stored show, not a show (requirements-initial.md: "the
        # agent has to match it to that stored record and update it"; A5-D6). It is never inserted: the status decides
        # what the match means, so the answer depends on both the listing and the stored show.
        if stored is None:
            return decide(Action.SKIP, f"{listing.status} listing, no stored show", start_time=listing.time)
        if stored.status is ShowStatus.ACTIVE:
            return decide(Action.REMOVE, listing.status, start_time=stored.start_time, stored_id=stored.id)
        return decide(
            Action.NO_OP, f"already removed ({listing.status})", start_time=stored.start_time, stored_id=stored.id
        )

    # Cancelled and postponed listings returned above, so a scheduled listing with no stored twin is a new show.
    if stored is None:
        return decide(Action.INSERT, "new show", start_time=listing.time, lineup=lineup)
    merged = merge_lineup(lineup, stored)
    changes = show_changes(stored, listing, merged, original_url)
    start = listing.time if listing.time is not None else stored.start_time
    if stored.status is ShowStatus.REMOVED:  # A5-D7: the same row comes back
        changes = {"status": (ShowStatus.REMOVED, ShowStatus.ACTIVE), **changes}
        return decide(Action.UPDATE, "reappeared", start_time=start, stored_id=stored.id, changes=changes, lineup=merged)
    if changes:
        return decide(Action.UPDATE, "details changed", start_time=start, stored_id=stored.id, changes=changes, lineup=merged)
    return decide(Action.NO_OP, "unchanged", start_time=start, stored_id=stored.id, lineup=merged)


# ---------------------------------------------------------------------------
# A5-K2: the soft delete, and its guard
# ---------------------------------------------------------------------------


def removed_by_absence(
    stored: Iterable[StoredShow], matched_ids: set[int], coverage: Coverage | None,
    excluded_dates: Iterable[datetime.date],
) -> list[StoredShow]:
    """The stored shows the page no longer lists, inside the dates it reached (A5-D1, A5-D2)."""
    # A show is removed because the page no longer lists it, and only if the fetch reached its date
    # (data-model-initial.md, `show.status`; requirements-initial.md: "falling within the date range that fetch
    # actually covered"). "Absent from the validated list" is not "absent from the page": a listing the splitter left
    # out is still on the page. And a show beyond the last listed date is not absent, it is out of sight.
    if coverage is None:  # a confirmed-empty page: no evidence of reach, so nothing is removed (A5-D2)
        return []
    skipped = set(excluded_dates)
    return [
        s for s in stored
        if s.status is ShowStatus.ACTIVE
        and coverage.contains(s.date)
        and s.id not in matched_ids
        and s.date not in skipped  # a listing we left out may be this show
    ]


def withhold_if_mass_removal(
    removals: list[StoredShow], in_window_active: list[StoredShow], policy: ReconcilePolicy
) -> tuple[list[StoredShow], list[StoredShow]]:
    """A5-D10: `(removals to do, removals withheld)`. A page that is merely truncated passes validation and would wipe
    most of the calendar silently, so a run that would remove at least `min_removals_to_guard` shows AND more than
    `max_removal_share` of the active shows in the window removes none of them, and the plan says so."""
    if len(removals) >= policy.min_removals_to_guard and len(removals) > policy.max_removal_share * len(in_window_active):
        return [], removals
    return removals, []


# ---------------------------------------------------------------------------
# The whole plan
# ---------------------------------------------------------------------------


def build_plan(
    inputs: ReconcileInputs, stored: Sequence[StoredShow], known_artists: Sequence[KnownArtist], *,
    original_url: str, client: Any, options: RequestOptions,
    policy: ReconcilePolicy = DEFAULT_RECONCILE_POLICY, artist_policy: ArtistMatchPolicy = DEFAULT_ARTIST_POLICY,
) -> ReconcilePlan:
    """Decide everything for one venue run, in the order each step needs the last:

    1. Pair listings with stored shows (A5-K1). This compares act NAMES, so it needs no artist resolution.
    2. Resolve artists, once per distinct name, **only for scheduled listings**: a cancelled listing never inserts or
       updates a lineup, so its acts cost no model call and create no artist.
    3. Decide each listing's action (A5-K3) and its changes.
    4. Remove stored shows absent from the page, inside the window (A5-K2), then apply the guard.
    5. Sort in calendar order. `plan.artists` holds only resolutions some decision uses.
    """
    matched = match_shows(inputs.listings, stored)
    twin = {listing.index: show for listing, show in matched.pairs}
    scheduled = [l for l in inputs.listings if l.is_scheduled]
    resolutions = resolve_artists(
        [act.name for l in scheduled for act in l.acts], known_artists,
        client=client, options=options, policy=artist_policy,
    )

    decisions: list[ShowDecision] = []
    for listing in inputs.listings:
        lineup = lineup_for(listing, resolutions) if listing.is_scheduled else ()
        decision = plan_for_listing(listing, twin.get(listing.index), lineup, original_url)
        if listing.index in matched.review_listings:
            decision = replace(decision, needs_review=True)
        decisions.append(decision)

    window = inputs.coverage
    absent = removed_by_absence(stored, {show.id for _, show in matched.pairs}, window, inputs.excluded_dates)
    in_window_active = [s for s in stored if window is not None and s.status is ShowStatus.ACTIVE and window.contains(s.date)]
    to_remove, held_back = withhold_if_mass_removal(absent, in_window_active, policy)

    def removal(show: StoredShow, reason: str) -> ShowDecision:
        return ShowDecision(
            Action.REMOVE, show.date, show.start_time, reason, stored_id=show.id,
            needs_review=show.id in matched.review_stored,
        )

    decisions += [removal(s, "absent from the page") for s in to_remove]
    withheld = [removal(s, "absent from the page (withheld by the removal guard)") for s in held_back]

    decisions.sort(key=lambda d: (night_sort_key(d.date, d.start_time), d.stored_id or 0))
    used: dict[str, ArtistResolution] = {}
    for decision in decisions:
        for entry in decision.lineup:
            used.setdefault(entry.key, resolutions[entry.key])
    return ReconcilePlan(window, tuple(decisions), tuple(used.values()), tuple(withheld))
