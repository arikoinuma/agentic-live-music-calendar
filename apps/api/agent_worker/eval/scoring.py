"""Score extractions against hand-written labels, by Ari's accuracy standard.

The standard (decided by Ari, October 10, 2026; requirements-initial.md, "Agent Extraction:
Accuracy Standards"; A2.1-D1 of docs/dev/implementations/a2.1-extraction-reliability.md) is
tiered, and this module counts exactly its tiers:

- **date and acts: 100%** — `missed` (a labelled show not found on its date) and `acts_wrong`
  (found, but the acts differ) must be 0;
- **no invented shows** — `fabricated` (an extra matching nothing on the page) must be 0;
- **other fields: missing tolerated, wrong never** — per field, `missing` at most 10% of the
  values the page states (pooled per run), `wrong` always 0;
- **non-music leaks: about one per month per venue** — `leaks` (an extra matching a labelled
  non-show entry) at most 1 per page.

How to read it: `ReturnedShow` normalises one returned show (including A2's legacy
string-acts form); `match_shows` pairs labelled and returned shows (A2.1-K2);
`score_page` counts one page; `gate` applies the standard to every run of a label. A returned
show with `acts: []` is dropped before anything is counted — both routes keep rejected
non-music entries that way for A3's completeness check to drop (A2.1-PR1-4).

C5 (docs/dev/implementations/c5-pipeline-eval-harness.md) added what the graph-level harness needs and changed none of the
counting: every returned show carries its position in the dump (`ReturnedShow.index`), every counted error also comes out
as a structured `ErrorItem` (so validation recall can join it to a finding, C5-K4), `scheduled_only` gives the label the
database can be held to, and `headline_rates` turns a page's counts into precision and recall (C5-K2).
"""

import datetime
from dataclasses import dataclass, field, replace
from typing import Any

from agent_worker.eval.labels import LabelledShow, NonShow, PageLabel
from agent_worker.normalize import fold_text, identifying_words

# The fields the standard scores as "missing tolerated, wrong never", besides the image link
# (checked against the page itself, since labels don't list images).
FIELDS = ("time", "end_time", "admission_advance", "admission_day", "free_admission", "status")
MISSING_TOLERANCE = 0.10  # "if the venue lists a time but the model misses it 1 times out of 10"
LEAKS_PER_PAGE = 1  # "1 per month per venue"; a captured page is about a month


# ---------------------------------------------------------------------------
# A returned show, normalised
# ---------------------------------------------------------------------------


def _parse_date(value: Any) -> datetime.date | None:
    """An extraction's ISO date string -> date (None if absent or unparseable)."""
    try:
        return datetime.date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _parse_time(value: Any) -> datetime.time | None:
    """An extraction's ISO time string -> naive time (None if absent or unparseable)."""
    try:
        return datetime.time.fromisoformat(str(value)).replace(tzinfo=None) if value else None
    except ValueError:
        return None


@dataclass(frozen=True)
class ReturnedShow:
    """One returned show as the scorer sees it."""

    date: datetime.date | None
    acts: tuple[str, ...]
    time: datetime.time | None = None
    end_time: datetime.time | None = None
    admission_advance: float | None = None
    admission_day: float | None = None
    free_admission: bool | None = None
    image_url: str | None = None
    status: str = "scheduled"
    # Position in the dump BEFORE empty-act shows are dropped: the same position validation's findings use
    # (`Finding.show_index` indexes `state.extraction.shows`), so an error here can be joined to a finding (C5-M1).
    index: int | None = None

    @classmethod
    def from_dump(cls, show: dict[str, Any], index: int | None = None) -> "ReturnedShow":
        """From an extraction dump (`model_dump(mode="json")`). A2's `baseline-32k` stored acts
        as plain strings and has no `status`; both are accepted (A2.1-PR1-13). `index` is the show's
        position in the dump's `shows` list."""
        acts = tuple(
            (a if isinstance(a, str) else str(a.get("name", ""))).strip()
            for a in show.get("acts") or []
        )
        return cls(
            date=_parse_date(show.get("date")),
            acts=tuple(a for a in acts if a),
            time=_parse_time(show.get("time")),
            end_time=_parse_time(show.get("end_time")),
            admission_advance=show.get("admission_advance"),
            admission_day=show.get("admission_day"),
            # A2-F1: `false` means "not stated" (the schema coerces it; old stored results don't).
            free_admission=show.get("free_admission") or None,
            image_url=show.get("image_url"),
            status=show.get("status") or "scheduled",
            index=index,
        )


def acts_correct(label: LabelledShow, acts: tuple[str, ...]) -> bool:
    """True when the returned acts, as a set, equal the label's or one of its alternatives,
    after folding spelling (case, entities, typographic punctuation, spacing). Order is not
    compared (A2.1-D1)."""
    returned = {fold_text(a) for a in acts}
    readings = (label.acts, *label.alternatives)
    return any(returned == {fold_text(a) for a in reading} for reading in readings)


# ---------------------------------------------------------------------------
# Matching (A2.1-K2)
# ---------------------------------------------------------------------------


@dataclass
class Matching:
    """The result of pairing a page's labelled shows with the shows returned for it."""

    matched: list[tuple[LabelledShow, ReturnedShow]]
    missed: list[LabelledShow]  # labelled shows nothing was paired with
    extras: list[ReturnedShow]  # returned shows nothing was paired with


def match_shows(labelled: list[LabelledShow], returned: list[ReturnedShow]) -> Matching:
    """Pair each labelled show with at most one returned show on the same date."""
    # What counts as correct is a design decision. Ari's standard (A2.1-D1) makes a show's IDENTITY its
    # date and acts, and makes time a field with its own tolerance, so match on date, then judge acts
    # and fields. Matching on (date, time), the key reconcile uses, would turn a found show with a
    # missed time into a missed show AND a fabricated one: the opposite of the tiers. When several
    # returned shows share a date (White Squirrel's 6 pm and 9 pm sets; 7th St Entry's two untimed
    # Oct 31 shows), pair the right ones first: acts that are correct, then a time that agrees, then
    # whatever is left. That runs in three passes over all labels, so a weak pairing for one label
    # can't take a strong one from another. Each returned show is used once.
    remaining = list(returned)
    pairs: dict[LabelledShow, ReturnedShow] = {}
    for prefer in (lambda lbl, r: acts_correct(lbl, r.acts), lambda lbl, r: r.time == lbl.time, lambda lbl, r: True):
        for lbl in labelled:
            hit = None if lbl in pairs else next((r for r in remaining if r.date == lbl.date and prefer(lbl, r)), None)
            if hit is not None:
                remaining.remove(hit)
                pairs[lbl] = hit
    return Matching(matched=list(pairs.items()), missed=[lbl for lbl in labelled if lbl not in pairs], extras=remaining)



# ---------------------------------------------------------------------------
# One page
# ---------------------------------------------------------------------------


@dataclass
class FieldTally:
    """One field's counts over a page's matched shows."""

    stated: int = 0  # labelled shows whose page states the value
    correct: int = 0
    missing: int = 0  # stated, returned null — tolerated up to MISSING_TOLERANCE
    wrong: int = 0  # returned a different value, or a value the page never states — never ok


@dataclass(frozen=True)
class ErrorItem:
    """One counted error, in a form a program can join to validation's findings (C5-D7).

    `kind` is one of missed, acts_wrong, fabricated, leak, field_wrong, field_missing, image_wrong. `index` is the returned
    show's position in the dump (None for a missed show nothing was returned for). `date` is an ISO string, not a
    `datetime.date`, so `dataclasses.asdict` of a page score stays JSON-serialisable in a results file.
    """

    kind: str
    date: str | None
    index: int | None = None
    field: str | None = None


@dataclass
class PageScore:
    """One page's counts against the standard. `route` is set by the harness from the
    extraction result, so the gate can be read per route (A2.1-PR1-15)."""

    fixture: str = ""
    route: str = "model"
    labelled: int = 0
    returned: int = 0
    dropped_empty: int = 0  # returned with acts: [] — not counted (A2.1-PR1-4)
    missed: int = 0
    acts_wrong: int = 0
    fabricated: int = 0
    leaks: int = 0
    unsplit: int = 0  # diagnostic: of acts_wrong, one returned act holding several labelled acts
    order_differs: int = 0  # diagnostic: correct acts in a different order (not gated)
    fields: dict[str, FieldTally] = field(default_factory=lambda: {f: FieldTally() for f in (*FIELDS, "image_url")})
    errors: list[str] = field(default_factory=list)  # human-readable, for reading a run
    items: list[ErrorItem] = field(default_factory=list)  # the same errors, structured (C5-D7)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PageScore":
        """Rebuild from `dataclasses.asdict` output, as stored in a results file. A file written before C5 has no `items`
        (they stay empty); a newer one has them as plain dicts, which are rebuilt into `ErrorItem`s (C5-PR1-12)."""
        fields = {name: FieldTally(**tally) for name, tally in data.get("fields", {}).items()}
        items = [ErrorItem(**item) for item in data.get("items", [])]
        return cls(**{**data, "fields": fields, "items": items})


@dataclass
class PageFailure:
    """A page whose extraction raised. It fails the gate: a crash can't be skipped. A page that
    never finished took no route, so by default it counts in every route's scope ("any") —
    `gate [jsonld]` can't pass a label in which a JSON-LD page crashed (A2.1-CR1-5)."""

    fixture: str
    error: str
    route: str = "any"


def _same(label_value: Any, returned_value: Any) -> bool:
    """Field equality, with a cent's tolerance for prices."""
    if isinstance(label_value, float) or isinstance(returned_value, float):
        return abs(float(label_value) - float(returned_value)) < 0.005
    return bool(label_value == returned_value)


def _tally(tally: FieldTally, label_value: Any, returned_value: Any) -> str | None:
    """Count one field of one matched show; return a description if it is an error."""
    if label_value is None:
        if returned_value is not None:
            tally.wrong += 1
            return f"invented {returned_value!r}"
        return None
    tally.stated += 1
    if returned_value is None:
        tally.missing += 1
        return f"missing (page states {label_value!r})"
    if _same(label_value, returned_value):
        tally.correct += 1
        return None
    tally.wrong += 1
    return f"wrong: {returned_value!r}, page states {label_value!r}"


# Identifying words (folded, filler dropped) come from normalize.identifying_words, shared with
# the status merge.
_title_words = identifying_words


def _is_leak(show: ReturnedShow, non_shows: tuple[NonShow, ...]) -> bool:
    """An extra is a tolerated leak only when it is recognisably a listed non-show: on that
    entry's date (or, for a recurring header such as "OPEN MIC Every Monday", its weekday)
    AND sharing an identifying word with its title. Date or weekday alone would let an
    invented band on a Monday, or a duplicate on a night that also lists "Open Jam", pass the
    "no invented shows, ever" tier (A2.1-CR1-1)."""
    if show.date is None:
        return False
    returned_words = _title_words(" ".join(show.acts))
    return any(
        (ns.date == show.date or (ns.weekday is not None and show.date.weekday() == ns.weekday))
        and bool(_title_words(ns.title) & returned_words)
        for ns in non_shows
    )


def _unsplit(label: LabelledShow, acts: tuple[str, ...]) -> bool:
    """Diagnostic for A2-F9: one returned act that contains two or more of the labelled acts."""
    wanted = [fold_text(a) for a in label.acts]
    return any(sum(w in fold_text(a) for w in wanted) >= 2 for a in acts)


def _dropped_index(dropped: list[ReturnedShow], day: datetime.date) -> int | None:
    """The position of a returned show with no acts on `day`, taken out of `dropped`; None when there is none.

    When the act splitter drops a show it stays in the dump with `acts: []` and validation puts `splitter_dropped` on its
    index. The scorer drops it before matching, so the label it belonged to is `missed`; this lets the missed item carry
    the dropped show's index, so the error and the finding can meet (C5-PR1-2).

    Known limit (C5-CR1-5): the match is on the date alone and the first show wins. A page that lists a non-music entry (also
    `acts: []`, with only an `excluded_no_acts` warning) on the same date as a show the splitter dropped can hand the missed label
    the non-music entry's index, so validation recall reads "flagged" where it should read "caught". A dump carries no title to
    match on; the count of such pages is small and is visible in the per-kind table."""
    for show in dropped:
        if show.date == day:
            dropped.remove(show)
            return show.index
    return None


def score_page(label: PageLabel, extraction: dict[str, Any], page_html: str = "", fixture: str = "") -> PageScore:
    """Count one extraction of one page against its label."""
    shows = [ReturnedShow.from_dump(s, i) for i, s in enumerate(extraction.get("shows") or [])]
    with_acts = [s for s in shows if s.acts]
    dropped = [s for s in shows if not s.acts]
    score = PageScore(
        fixture=fixture, labelled=len(label.shows), returned=len(with_acts),
        dropped_empty=len(dropped),
    )
    matching = match_shows(list(label.shows), with_acts)

    for missed in matching.missed:
        score.missed += 1
        score.errors.append(f"missed {missed.date} {missed.source_line!r}")
        score.items.append(ErrorItem("missed", missed.date.isoformat(), _dropped_index(dropped, missed.date)))
    for lbl, ret in matching.matched:
        if not acts_correct(lbl, ret.acts):
            score.acts_wrong += 1
            score.unsplit += _unsplit(lbl, ret.acts)
            score.errors.append(f"acts wrong {lbl.date}: {list(ret.acts)} vs {list(lbl.acts)}")
            score.items.append(ErrorItem("acts_wrong", lbl.date.isoformat(), ret.index))
        elif [fold_text(a) for a in ret.acts] != [fold_text(a) for a in lbl.acts]:
            score.order_differs += 1
        for name in FIELDS:
            tally = score.fields[name]
            missing_before = tally.missing
            problem = _tally(tally, getattr(lbl, name), getattr(ret, name))
            if problem:
                score.errors.append(f"{name} {lbl.date} {lbl.source_line!r}: {problem}")
                kind = "field_missing" if tally.missing > missing_before else "field_wrong"
                score.items.append(ErrorItem(kind, lbl.date.isoformat(), ret.index, name))
        image = score.fields["image_url"]
        if ret.image_url is not None:
            if ret.image_url in page_html:
                image.correct += 1
            else:
                image.wrong += 1
                score.errors.append(f"image_url {lbl.date}: {ret.image_url!r} is not on the page")
                score.items.append(ErrorItem("image_wrong", lbl.date.isoformat(), ret.index, "image_url"))
    for extra in matching.extras:
        day = extra.date.isoformat() if extra.date else None
        if _is_leak(extra, label.non_shows):
            score.leaks += 1
            score.errors.append(f"leak {extra.date} {list(extra.acts)}")
            score.items.append(ErrorItem("leak", day, extra.index))
        else:
            score.fabricated += 1
            score.errors.append(f"fabricated {extra.date} {list(extra.acts)}")
            score.items.append(ErrorItem("fabricated", day, extra.index))
    return score


def scheduled_only(label: PageLabel) -> PageLabel:
    """The label with its cancelled and postponed shows removed: what the DATABASE can be held to.

    A cancelled or postponed listing is labelled with its status (A2.1-D12), but `ShowStatus` has only active and removed,
    and reconcile skips such a listing with nothing stored (`reconcile.Action.SKIP`), so the rows left cannot hold it.
    Scored against the full label, every run of a page like 7th St Entry's would report those shows missed for correct
    behaviour (C5-PR1-5). Used for the committed column and by `C5-K3`."""
    return replace(label, shows=tuple(s for s in label.shows if s.status == "scheduled"))


# ---------------------------------------------------------------------------
# Precision and recall (C5-K2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rates:
    """A page's headline numbers. `found` is the shows that were matched with the right acts; `precision` counts every
    returned show that has acts against it, `precision_lenient` leaves out the tolerated leaks (A2.1-D1)."""

    found: int
    labelled: int
    returned: int
    recall: float
    precision: float
    precision_lenient: float


def headline_rates(score: PageScore) -> Rates:
    """Precision and recall for one page's counts."""
    # TODO(Ari) — Key point of interest (C5-K2): what counts as FOUND, and whether a tolerated leak is a false positive.
    #   Ari's standard (A2.1-D1) makes identity "date and acts", so a show is FOUND when it was matched AND its acts are
    #   correct: found = labelled - missed - acts_wrong. Recall is found / labelled. For precision the denominator is every
    #   show returned with acts: the standard tolerates about one leak per page, but a leak is still a row in the calendar
    #   that is not a show, so the STRICT precision counts it against; the LENIENT figure (precision_lenient) does not, and
    #   both are reported so the tolerated case stays visible. (docs/dev/alpha-deployment-plan.md C5; A2.1-D1.)
    # To align: copy the Code lines by hand, then run the Check.
    # Code:
    #   found = score.labelled - score.missed - score.acts_wrong
    #   return Rates(
    #       found=found, labelled=score.labelled, returned=score.returned,
    #       recall=found / score.labelled if score.labelled else 1.0,
    #       precision=found / score.returned if score.returned else 1.0,
    #       precision_lenient=found / (score.returned - score.leaks) if score.returned - score.leaks else 1.0,
    #   )
    # Check: uv run pytest agent_worker/tests/test_scoring.py -k headline_rates — the likeliest mistake is
    #   `found = labelled - missed` (counting a wrong-acts show as found, which the standard says is an error), or a
    #   ZeroDivisionError on an empty page.
    raise NotImplementedError("TODO(Ari)")


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    """Whether every run met every tier, and if not, each reason (run, page, tier). `pages` is
    how many page results were in scope: a gate over none never passes (it would be vacuous —
    a route no page took has proven nothing)."""

    passed: bool
    failures: list[str]
    pages: int = 0


def gate(
    runs: dict[int, list[PageScore | PageFailure]], route: str | None = None,
    missing_tolerance: float = MISSING_TOLERANCE, leaks_per_page: int = LEAKS_PER_PAGE,
) -> GateResult:
    """Apply the standard to every run (A2.1-D1: every run must pass; an average doesn't count).

    Counted per page: missed, acts wrong, fabricated, leaks, and wrong field values. Pooled
    per run across its pages: the missing rate per field, because a 12-show page can't
    express "1 in 10" on its own. `route` restricts the gate to pages that took that route.
    """
    failures: list[str] = []
    considered = 0
    for run_index, pages in sorted(runs.items()):
        stated: dict[str, int] = dict.fromkeys(FIELDS, 0)
        missing: dict[str, int] = dict.fromkeys(FIELDS, 0)
        for page in pages:
            if route is not None and page.route not in (route, "any"):
                continue
            considered += 1
            where = f"run {run_index}: {page.fixture or 'page'}"
            if isinstance(page, PageFailure):
                failures.append(f"{where}: raised {page.error}")
                continue
            for tier in ("missed", "acts_wrong", "fabricated"):
                if getattr(page, tier):
                    failures.append(f"{where}: {getattr(page, tier)} {tier}")
            if page.leaks > leaks_per_page:
                failures.append(f"{where}: {page.leaks} leaks (at most {leaks_per_page})")
            for name, tally in page.fields.items():
                if tally.wrong:
                    failures.append(f"{where}: {tally.wrong} wrong {name}")
                if name in stated:
                    stated[name] += tally.stated
                    missing[name] += tally.missing
        for name in FIELDS:
            if stated[name] and missing[name] / stated[name] > missing_tolerance:
                failures.append(
                    f"run {run_index}: {name} missing {missing[name]} of {stated[name]} "
                    f"(more than {missing_tolerance:.0%})"
                )
    if considered == 0:
        failures.append("no pages in scope")
    return GateResult(passed=not failures, failures=failures, pages=considered)
