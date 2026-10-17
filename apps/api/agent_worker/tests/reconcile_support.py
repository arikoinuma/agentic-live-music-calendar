"""Builders for the reconcile tests: stored shows, listings, known artists, and a stand-in for the write.

What this is: reconcile (reconcile.py) is pure, so its tests hand it hand-built data. These helpers keep each test to
the one fact it is about. Dates are October 2026 and `FETCHED` (October 12) is the fetch date, matching
`fakes.FETCHED`, so a listing on the 20th is a week ahead.

`apply_plan` is the one non-obvious piece: **a test-only mirror of what `commit_node` (A6) will do** with a plan,
turning (stored shows, plan) into the stored shows that would exist afterwards. It exists so the tests can check the
property that stops a show flipping every night: feeding a plan's own result back in must give all no-ops
(idempotency). A6 replaces it with a real database round trip. It is deliberately dumb: it applies each decision's
`changes` and lineup and nothing else, so a decision that omits something shows up as a failed idempotency check.
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

FETCHED = datetime.date(2026, 10, 12)
URL = "https://venue.example/events"
OPTIONS = RequestOptions(model="test-model", temperature=0.0)


def day(n: int) -> datetime.date:
    """October `n`, 2026."""
    return datetime.date(2026, 10, n)


def at(hour: int, minute: int = 0) -> datetime.time:
    return datetime.time(hour, minute)


def stored(
    show_id: int, date: datetime.date, start: datetime.time | None = None, acts: Sequence[tuple[int, str]] = (),
    status: ShowStatus = ShowStatus.ACTIVE, **fields: Any,
) -> StoredShow:
    """A stored show. `acts` is (artist id, name) in performance order; `original_url` defaults to the page's URL
    so a test about something else doesn't also see a changed URL."""
    fields.setdefault("original_url", URL)
    lineup = tuple(StoredLineupEntry(artist_id, name, None, i) for i, (artist_id, name) in enumerate(acts, start=1))
    return StoredShow(id=show_id, date=date, start_time=start, status=status, lineup=lineup, **fields)


def listed(
    index: int, date: datetime.date, time: datetime.time | None = None, acts: Iterable[str | ListedAct] = ("Nona",),
    status: str = "scheduled", **fields: Any,
) -> Listing:
    """A listing; an act can be a plain name or a `ListedAct` (to give it a set time or a stated order)."""
    return Listing(
        index=index, date=date, time=time, status=status, **fields,
        acts=tuple(a if isinstance(a, ListedAct) else ListedAct(a) for a in acts),
    )


# Artists that exist in the tests' database, with ids a test can refer to.
NONA = KnownArtist(7, "Nona")
ZHORA = KnownArtist(8, "Zhora")
PRINCE = KnownArtist(9, "Prince")
KNOWN = [NONA, ZHORA, PRINCE]


def inputs_for(
    listings: Sequence[Listing], *, fetched: datetime.date = FETCHED, excluded: Iterable[datetime.date] = ()
) -> ReconcileInputs:
    """The reconcile inputs for a page with these listings; the window is derived as the pipeline derives it (D1)."""
    excluded = frozenset(excluded)
    return ReconcileInputs(tuple(listings), excluded, covered_window(listings, excluded, fetched), fetched)


def plan_for(
    listings: Sequence[Listing], stored_shows: Sequence[StoredShow] = (), known: Sequence[KnownArtist] = KNOWN, *,
    excluded: Iterable[datetime.date] = (), client: Any = None,
) -> ReconcilePlan:
    """The plan for a page. With no `client` the model is unscripted: a test that reaches the model by accident
    fails with an AssertionError instead of passing quietly."""
    return build_plan(
        inputs_for(listings, excluded=excluded), stored_shows, known, original_url=URL,
        client=client or scripted_client({}), options=OPTIONS,
    )


def actions(plan: ReconcilePlan) -> list[str]:
    """The plan's actions in order, as strings."""
    return [d.action.value for d in plan.shows]


def only(plan: ReconcilePlan, action: Action) -> list[Any]:
    """The decisions with this action."""
    return [d for d in plan.shows if d.action is action]


def apply_plan(
    plan: ReconcilePlan, before: Sequence[StoredShow], known: Sequence[KnownArtist] = KNOWN
) -> tuple[list[StoredShow], list[KnownArtist]]:
    """Test-only mirror of commit (see the module docstring): the stored shows and artists after `plan`."""
    shows = {s.id: s for s in before}
    artists = {a.id: a for a in known}
    new_ids: dict[str, int] = {}
    next_show = max(shows, default=0) + 1
    next_artist = max(artists, default=0) + 1

    def artist_id(entry: Any) -> int:
        nonlocal next_artist
        if entry.artist_id is not None:
            return int(entry.artist_id)
        if entry.key not in new_ids:  # one new artist per distinct name, however many shows name it
            new_ids[entry.key] = next_artist
            artists[next_artist] = KnownArtist(next_artist, entry.name)
            next_artist += 1
        return new_ids[entry.key]

    def lineup(decision: Any) -> tuple[StoredLineupEntry, ...]:
        return tuple(
            StoredLineupEntry(artist_id(e), e.name, e.start_time, e.sequence_number) for e in decision.lineup
        )

    for d in plan.shows:
        if d.action is Action.INSERT:
            listing = d.listing
            shows[next_show] = StoredShow(
                id=next_show, date=d.date, start_time=listing.time, end_time=listing.end_time,
                admission_advance=to_price(listing.admission_advance), admission_day=to_price(listing.admission_day),
                free_admission=listing.free_admission, image_url=listing.image_url, original_url=URL, lineup=lineup(d),
            )
            next_show += 1
        elif d.action is Action.UPDATE:
            current = shows[d.stored_id]
            values = {k: v[1] for k, v in d.changes.items() if k not in ("lineup", "status")}
            new_status = d.changes["status"][1] if "status" in d.changes else current.status
            shows[d.stored_id] = dataclasses.replace(current, status=new_status, lineup=lineup(d), **values)
        elif d.action is Action.REMOVE:
            shows[d.stored_id] = dataclasses.replace(shows[d.stored_id], status=ShowStatus.REMOVED)
    return list(shows.values()), list(artists.values())


def violates_free_check(
    show: StoredShow, changes: dict[str, tuple[Any, Any]]
) -> bool:
    """True if applying `changes` to `show` would break the table's CHECK (data-model-initial.md, `show`): free
    admission and a price at once. Mirrors the constraint so a test can assert it without a database."""
    advance = changes["admission_advance"][1] if "admission_advance" in changes else show.admission_advance
    day_price = changes["admission_day"][1] if "admission_day" in changes else show.admission_day
    free = changes["free_admission"][1] if "free_admission" in changes else show.free_admission
    return bool(free) and (advance is not None or day_price is not None)


def money(value: str) -> decimal.Decimal:
    return decimal.Decimal(value)


def extracted(
    date: datetime.date, acts: Sequence[str] = ("Nona",), time: datetime.time | None = datetime.time(20, 0), **fields: Any
) -> ShowExtraction:
    """One show as the extraction model returns it (the raw record, before validation)."""
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
