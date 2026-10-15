"""Checks on an extraction — pure functions, no model, no database, no clock.

What this is: A3's answer to "is what the model (or the JSON-LD reader) returned fit to write to the
calendar?" `validate_extraction` runs the three checks `requirements-initial.md` ("Agent
Validation") names — completeness, plausibility, internal consistency — plus the guards A2.1 left for
A3, and returns a `ValidationResult`: what the page was, every finding, every repair, which shows were
excluded, and the model's confidence. It does **not** decide pass or fail: `policy.combine` does that,
so the evidence (here) and the decision (there) stay separate and a router never reads a bare float
(docs/dev/implementations/a3-validation-and-retry.md, Design §1).

How to read it, top to bottom:
1. The types. `Finding` (something noticed, error or warning), `Repair` (a value dropped because it
   failed verification), `ValidationResult`. All the types live here, so `policy.py` and `state.py`
   import from this module and never the other way round.
2. The per-show checks, one function each so a test can call one alone.
3. The page-level guards: JSON-LD under-reporting and "empty but dated".
4. `validate_extraction`, which runs it all and returns the result plus the shows to keep.

Three ideas the checks share:
* **The date is passed in.** Plausibility is relative to when the page was *fetched*, not to the wall
  clock, so a replayed capture (local_test.py's August page) validates the same way it did that day.
* **Excluded is not failed.** A show with no acts isn't a show (`requirements-initial.md`, Show:
  "Artists — one or more"), so it is left out of what is committed and reported with a warning.
  It is never silently dropped, and "excluded" does not mean "confirmed not music": the act splitter
  returns `acts: []` for real shows too.
* **Repairs drop, never rewrite** (D4). A value that fails verification is set to null and recorded.
  Ari's tiered standard tolerates a missing field about one time in ten and never a wrong one.
"""

import datetime
import html as html_lib
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Literal

from agent_worker.normalize import (
    YEAR_LOOKBACK,
    fold_text,
    infer_year,
)
from agent_worker.schemas import ShowExtraction, VenuePageExtraction
from agent_worker.sources.jsonld import end_time_is_stated

# Which route produced the extraction (PageExtractionResult.source).
Source = Literal["jsonld", "model", "image"]

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class Severity(StrEnum):
    # An error makes the page fail validation (and so retry or escalate); a warning is recorded
    # and never changes the verdict.
    ERROR = "error"
    WARNING = "warning"


class Target(StrEnum):
    """Which model call a finding is about, so a retry hint reaches the call that produced the
    field and no other (plan, §3: a date problem must not disturb the act splitter)."""

    PAGE = "page"
    SPLITTER = "splitter"


class CheckCode(StrEnum):
    """Every finding's name. The strings are what the audit trail (A4) will store."""

    # errors
    BLANK_ACT_NAME = "blank_act_name"
    SPLITTER_DROPPED = "splitter_dropped"
    DATE_IMPLAUSIBLE = "date_implausible"
    FREE_WITH_PRICE = "free_with_price"
    JSONLD_UNDER_REPORTED = "jsonld_under_reported"
    EMPTY_BUT_DATED = "empty_but_dated"
    # warnings
    EXCLUDED_NO_ACTS = "excluded_no_acts"
    DATE_OUT_OF_WINDOW = "date_out_of_window"
    ACT_NOT_IN_TITLE = "act_not_in_title"
    UNUSUAL_START_TIME = "unusual_start_time"
    POSSIBLE_MERGE = "possible_merge"
    AMBIGUOUS = "ambiguous"


# Only the act splitter produces these; every other check is about a field the page model (or
# code) produces.
_SPLITTER_CODES = {CheckCode.BLANK_ACT_NAME, CheckCode.SPLITTER_DROPPED, CheckCode.ACT_NOT_IN_TITLE}


@dataclass(frozen=True)
class Finding:
    """One thing a check noticed. `show_index` is the position in the *extracted* shows (before
    exclusion), or None for a page-level finding."""

    code: CheckCode
    severity: Severity
    message: str
    show_index: int | None = None

    @property
    def target(self) -> Target:
        return Target.SPLITTER if self.code in _SPLITTER_CODES else Target.PAGE


@dataclass(frozen=True)
class Repair:
    """A value dropped because it failed verification (D4: dropped, never moved or rewritten)."""

    show_index: int
    field: str
    old: str | None
    reason: str


class PageOutcome(StrEnum):
    """What the page turned out to be (G3: three outcomes, not two)."""

    HAS_SHOWS = "has_shows"
    CONFIRMED_EMPTY = "confirmed_empty"
    UNREADABLE = "unreadable"


class Verdict(StrEnum):
    PASSED = "passed"
    CONFIRMED_EMPTY = "confirmed_empty"  # a legitimate pass: the venue lists nothing
    FAILED = "failed"


class FailureReason(StrEnum):
    """Why a verdict is FAILED, strongest evidence first (the order of this enum)."""

    EXTRACT_FAILED = "extract_failed"
    UNREADABLE = "unreadable"
    CHECK_ERRORS = "check_errors"
    LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True)
class ValidationResult:
    """The evidence about one extraction. `verdict` and `reasons` are None/empty until
    `policy.combine` fills them in."""

    # None only when the model call itself failed (there was no extraction to classify).
    outcome: PageOutcome | None
    findings: list[Finding] = field(default_factory=list)
    repairs: list[Repair] = field(default_factory=list)
    # Positions (in the extracted shows) of shows left out because they name no act, or, on the
    # JSON-LD route, because their date is outside the plausible window.
    excluded: list[int] = field(default_factory=list)
    # None = no model judged the record (JSON-LD route), or nothing was kept to judge.
    confidence: float | None = None
    extraction_failed: bool = False
    verdict: Verdict | None = None
    reasons: list[FailureReason] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @classmethod
    def for_failed_extraction(cls) -> "ValidationResult":
        """The result when the model call raised: nothing to check, and that alone fails."""
        return cls(outcome=None, extraction_failed=True)

    def with_verdict(self, verdict: Verdict, reasons: list[FailureReason]) -> "ValidationResult":
        return replace(self, verdict=verdict, reasons=reasons)


@dataclass(frozen=True)
class PlausibilityFlags:
    """What `check_plausibility` found: two independent yes/no facts about one show."""

    date_out_of_window: bool
    end_equals_start: bool


# ---------------------------------------------------------------------------
# Page outcome (Gap B)
# ---------------------------------------------------------------------------


def classify_page(extraction: VenuePageExtraction) -> PageOutcome:
    """Which of the three things this page turned out to be, from `page_readable` and `shows`."""
    # `page_readable` tells apart two situations that both look like `shows: []`: a venue that
    # genuinely lists nothing (a legitimate pass), and a page the model couldn't read (a failure
    # worth a retry; see the comment on it in schemas.py). So readability is asked FIRST. An
    # unreadable page that also returned a stray show is still unreadable: a model that says "I
    # couldn't read this" shouldn't be trusted on what it then returned (arch-initial.md §7; build
    # plan G3).
    if not extraction.page_readable:
        return PageOutcome.UNREADABLE
    return PageOutcome.HAS_SHOWS if extraction.shows else PageOutcome.CONFIRMED_EMPTY


# ---------------------------------------------------------------------------
# Per-show checks
# ---------------------------------------------------------------------------


def is_excluded(show: ShowExtraction) -> bool:
    """A show naming no act isn't a show (requirements, Show: "Artists — one or more"). Both
    routes hand these over on purpose: JSON-LD lists the whole calendar, karaoke included, and the
    model route can leak one (A2 Design, "Consequences")."""
    return not show.acts


def check_blank_acts(show: ShowExtraction, index: int) -> list[Finding]:
    """Completeness: an act with no name can't become an Artist row."""
    if any(not act.name.strip() for act in show.acts):
        return [Finding(
            CheckCode.BLANK_ACT_NAME, Severity.ERROR, f"the show on {show.date} has an act with no name", index,
        )]
    return []


def check_consistency(show: ShowExtraction, index: int) -> list[Finding]:
    """Internal consistency: "Free Admission cannot be true at the same time as an Admission
    Advance or Admission Day price being set" (requirements, Validation). The converse isn't a
    rule: a missing price never implies free, and a price with `free_admission` null is fine."""
    if show.free_admission is True and (show.admission_advance is not None or show.admission_day is not None):
        return [Finding(
            CheckCode.FREE_WITH_PRICE, Severity.ERROR,
            f"the show on {show.date} is marked free but also has an admission price", index,
        )]
    return []


# Live music is "overwhelmingly afternoon and evening" (requirements, Fields): a start between these
# times is more likely a mis-converted PM than a brunch set, so it is worth a look. A warning,
# because brunch music exists — and a time before 05:00 is after midnight of the listed night
# (requirements, Show), which is normal.
_MORNING_FROM = datetime.time(5, 0)
_MORNING_UNTIL = datetime.time(11, 0)


def check_start_time(show: ShowExtraction, index: int) -> list[Finding]:
    if show.time is not None and _MORNING_FROM <= show.time < _MORNING_UNTIL:
        return [Finding(
            CheckCode.UNUSUAL_START_TIME, Severity.WARNING,
            f"show {index} starts at {show.time:%H:%M}, which is unusual for live music", index,
        )]
    return []


def check_plausibility(show: ShowExtraction, fetched_on: datetime.date) -> PlausibilityFlags:
    """Plausibility, relative to when the page was fetched (not to the wall clock)."""
    # Plausibility is relative to *when the page was fetched* and to the venue's *night*, not to the
    # data alone. The date window is `fetched_on - 31 days` to `fetched_on + 366 days` (D2; the
    # lookback is normalize.YEAR_LOOKBACK, shared with the year rule so the two can't drift). An
    # `end_time` EARLIER than `time` is NOT a finding: "9:00 pm - 12:00 am" ends the next morning
    # (requirements-initial.md, Show), so a naive `end <= start` check would flag a correct record.
    # Only an end EQUAL to the start is wrong: a zero-length show (the JSON-LD route can produce one;
    # it is repaired, not failed). Be honest about reach: with the year rule on, the window mostly
    # guards the JSON-LD route and the Feb 29 that infer_year leaves unchanged.
    earliest = fetched_on - YEAR_LOOKBACK
    latest = fetched_on + datetime.timedelta(days=366)
    return PlausibilityFlags(
        date_out_of_window=not earliest <= show.date <= latest,
        end_equals_start=show.time is not None and show.end_time == show.time,
    )


def check_ambiguous(show: ShowExtraction, index: int) -> list[Finding]:
    """`is_ambiguous` means "a human may want to look" and never routes (D3): the requirements
    say an unclear lineup order is expected (assume list order), and A2's eval had it fall to 0."""
    if show.is_ambiguous:
        return [Finding(CheckCode.AMBIGUOUS, Severity.WARNING, f"show {index} was marked ambiguous", index)]
    return []


def check_possible_merge(show: ShowExtraction, index: int) -> list[Finding]:
    """Acts with different start times may be separately-timed listings the model merged (A2's
    eval, White Squirrel seed 2). Legitimately also one show with one ticket link and several
    set times, so only a warning; A5's matching reads it."""
    starts = {act.start_time for act in show.acts if act.start_time is not None}
    if len(starts) > 1:
        return [Finding(
            CheckCode.POSSIBLE_MERGE, Severity.WARNING,
            f"show {index}'s acts have different start times; it may be several shows merged", index,
        )]
    return []


def check_act_in_title(show: ShowExtraction, index: int, title: str) -> list[Finding]:
    """A2.1's E3: every act name should appear in the verbatim title it was split from. Catches
    typos and invented names — the one deterministic guard on the 100% field. A warning, because
    the splitter legitimately drops parentheticals and "w." markers (those leave the name in the
    title; an invented name doesn't)."""
    folded_title = fold_text(title)
    missing = [a.name for a in show.acts if a.name.strip() and fold_text(a.name) not in folded_title]
    if missing:
        return [Finding(
            CheckCode.ACT_NOT_IN_TITLE, Severity.WARNING,
            f"show {index}: {', '.join(repr(m) for m in missing)} not found in its title {title!r}", index,
        )]
    return []


# ---------------------------------------------------------------------------
# Repairs: a value that fails verification is dropped, and the drop is recorded
# ---------------------------------------------------------------------------


def _show_with(show: ShowExtraction, **update: Any) -> ShowExtraction:
    """A copy of the show with fields replaced. `model_copy(update=)` skips validation, which is
    right here: the only values ever written are None."""
    return show.model_copy(update=update)


def verify_image_url(url: str, page_html: str, page_text: str) -> bool:
    """True when the URL appears verbatim in the page. Checked against the *unescaped* HTML as well
    as the text sent: an attribute `src="a?b=1&amp;c=2"` is read by the parser as `a?b=1&c=2`, so
    a naive `url in page_html` is false for a URL the model copied correctly."""
    return url in page_text or url in html_lib.unescape(page_html)


def repair_show(
    show: ShowExtraction, index: int, *, flags: PlausibilityFlags, source: Source, page_html: str,
    page_text: str, titles: list[str] | None,
) -> tuple[ShowExtraction, list[Repair]]:
    """Drop the values that fail verification; return the show and what was dropped.

    Which repair runs on which source (plan, §2): the two that read no page (a misplaced start,
    an end equal to the start) run everywhere; the image-URL and unstated-end-time checks read the
    page, so they run on the `model` source only — not `jsonld` (its values come from structured
    data, not a model) and not `image` (a poster run has no page HTML).
    """
    repairs: list[Repair] = []
    if show.time is None and show.end_time is not None:
        # A deliberate widening of the build-plan bullet ("end equal to a stated start"): the
        # code can't know what the page states, and an end with no start is rare enough that
        # dropping it costs little. A2's eval: the poster route put a start in end_time.
        repairs.append(Repair(index, "end_time", str(show.end_time), "an end time with no start time"))
        show = _show_with(show, end_time=None)
    elif flags.end_equals_start:
        repairs.append(Repair(index, "end_time", str(show.end_time), "end time equals the start time"))
        show = _show_with(show, end_time=None)
    if source == "model":
        if show.image_url is not None and not verify_image_url(show.image_url, page_html, page_text):
            repairs.append(Repair(index, "image_url", show.image_url, "not found verbatim in the page"))
            show = _show_with(show, image_url=None)
        if show.end_time is not None:
            # Title-scoped when the verbatim titles line up with the shows (A2.1's own docstring:
            # page-wide lets another listing's "11:00 pm" vouch for a default end), page-wide otherwise.
            if titles is not None:
                stated = end_time_is_stated(show.end_time, page_text, titles[index], titles)
            else:
                stated = end_time_is_stated(show.end_time, page_text)
            if not stated:
                repairs.append(Repair(index, "end_time", str(show.end_time), "the page doesn't state it"))
                show = _show_with(show, end_time=None)
    return show, repairs


# ---------------------------------------------------------------------------
# Page-level guards
# ---------------------------------------------------------------------------

_MONTHS = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
# "Oct 12", "October 12th", "Oct. 12". The day can't run into a following digit (so "Oct 2026"
# is not a date). Checked against the real fixtures before A3 was planned: both White Squirrel
# captures' text names exactly the dates their JSON-LD events fall on (5 and 6 dates, no extras).
_MONTH_DAY = re.compile(rf"\b({_MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!\d)", re.IGNORECASE)
_MONTH_NUMBER = {
    m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}

# How many dates the text may name that no extracted show falls on before the page is called
# under-reported (or empty-but-dated). A guess — measured against exactly two real pages — and
# stated as one.
MIN_UNMATCHED_DATES = 3


def upcoming_dates(page_text: str, fetched_on: datetime.date) -> set[tuple[int, int]]:
    """The (month, day) pairs the visible text names that are on or after the fetch date.

    Each pair is placed in a year with `infer_year` and ignored if that falls before `fetched_on`:
    pages keep past listings and posted-on dates (7th St Entry's text has Oct 1-9 against an Oct 10
    capture), and an under-report is about *upcoming* events. This drops only the past 31 days:
    an archive older than that is placed next year and still counts.
    """
    found: set[tuple[int, int]] = set()
    for match in _MONTH_DAY.finditer(page_text):
        month, day = _MONTH_NUMBER[match.group(1)[:3].lower()], int(match.group(2))
        try:
            listed = datetime.date(2000, month, day)  # a leap year, so Feb 29 is representable
        except ValueError:
            continue  # "Oct 45" isn't a date
        if infer_year(listed, fetched_on) >= fetched_on:
            found.add((month, day))
    return found


def check_under_reported(
    extraction: VenuePageExtraction, page_text: str, fetched_on: datetime.date
) -> list[Finding]:
    """JSON-LD route only. The structured data lists fewer events than the page does when the
    visible text names MIN_UNMATCHED_DATES or more upcoming dates on which no extracted show falls.
    Compared against *all* extracted shows' dates, excluded ones included: the JSON-LD did list them."""
    shown = {(s.date.month, s.date.day) for s in extraction.shows}
    extra = upcoming_dates(page_text, fetched_on) - shown
    if len(extra) >= MIN_UNMATCHED_DATES:
        return [Finding(
            CheckCode.JSONLD_UNDER_REPORTED, Severity.ERROR,
            f"the page names {len(extra)} upcoming dates with no event in its structured data "
            "(its JSON-LD may list only some of the shows)",
        )]
    return []


def check_empty_but_dated(
    page_text: str, fetched_on: datetime.date, shown: set[tuple[int, int]]
) -> list[Finding]:
    """D10: a page that yields no kept show but whose text names upcoming dates is not a confirmed
    empty calendar. An empty list is the most dangerous output (reconcile would soft-delete every
    stored show), so it needs more than the model's say-so. The price is a false alarm for a venue
    that is empty and also posts dated news; one human look.

    `shown` is the (month, day) of EVERY extracted show, excluded ones included, exactly as in
    `check_under_reported` (code review round 1, #1): a JSON-LD page whose events were all left out
    for an out-of-window date has its dates in the text, but they are accounted for. Without the
    subtraction the guard fired on them, sent the page to the model route, and that route's year
    rule re-dated the shows into a plausible, wrong year (D13 exists to stop exactly that)."""
    dates = upcoming_dates(page_text, fetched_on) - shown
    if len(dates) >= MIN_UNMATCHED_DATES:
        return [Finding(
            CheckCode.EMPTY_BUT_DATED, Severity.ERROR,
            f"no shows were found, but the page text names {len(dates)} upcoming dates",
        )]
    return []


def aggregate_confidence(
    shows: list[tuple[int, ShowExtraction]], source: Source, added: set[int]
) -> float | None:
    """The model's confidence in the record: the minimum over the shows it judged (D9).

    `shows` is (position in the extraction, show) for the kept shows. None when no model judged
    the record: the JSON-LD route stamps `confidence=1.0` on every show as a placeholder, the
    status merge's added shows carry the same placeholder (`added`), and a page with nothing kept
    has nothing to be confident about (`min([])` would raise).
    """
    if source == "jsonld":
        return None
    judged = [s.confidence for i, s in shows if i not in added]
    return min(judged) if judged else None


# ---------------------------------------------------------------------------
# The whole validation
# ---------------------------------------------------------------------------


def validate_extraction(
    extraction: VenuePageExtraction, *, source: Source, notes: dict[str, Any],
    fetched_on: datetime.date, page_html: str, page_text: str,
) -> tuple[ValidationResult, list[ShowExtraction]]:
    """Run every check; return the evidence and the shows to keep (repaired, exclusions removed).

    The per-show checks run on the shows that aren't excluded. The under-report comparison uses
    every extracted show's date. `notes` is `PageExtractionResult.notes`: the verbatim `titles`
    (JSON-LD and title-split routes), `no_acts`, `missing_ids` and the status merge's
    `added_indices`. `page_html` and `page_text` are empty for the image route.
    """
    outcome = classify_page(extraction)
    findings: list[Finding] = []
    repairs: list[Repair] = []
    excluded: list[int] = []
    kept: list[tuple[int, ShowExtraction]] = []

    # The verbatim titles line up with the shows only when counts match (the status merge can add
    # a show, which breaks the pairing); when they don't, the checks that need a title are skipped.
    raw_titles = notes.get("titles")
    titles = raw_titles if isinstance(raw_titles, list) and len(raw_titles) == len(extraction.shows) else None

    for index, show in enumerate(extraction.shows):
        if is_excluded(show):
            where = f" {titles[index]!r}" if titles is not None else ""
            findings.append(Finding(
                CheckCode.EXCLUDED_NO_ACTS, Severity.WARNING,
                f"show {index}{where} names no act and was left out; it may be a real show the act splitter missed",
                index,
            ))
            excluded.append(index)
            continue
        flags = check_plausibility(show, fetched_on)
        if flags.date_out_of_window:
            if source == "jsonld":
                # D13: the date is the source's own, a retry can't change it, and the model route's
                # year rule would re-date it into a plausible but wrong date. Excluded, visibly.
                findings.append(Finding(
                    CheckCode.DATE_OUT_OF_WINDOW, Severity.WARNING,
                    f"show {index} is dated {show.date}, outside the plausible window around {fetched_on}; left out",
                    index,
                ))
                excluded.append(index)
                continue
            findings.append(Finding(
                CheckCode.DATE_IMPLAUSIBLE, Severity.ERROR,
                f"show {index} is dated {show.date}, which is not plausible for a page fetched on {fetched_on}",
                index,
            ))
        findings += check_blank_acts(show, index)
        findings += check_consistency(show, index)
        findings += check_start_time(show, index)
        findings += check_ambiguous(show, index)
        findings += check_possible_merge(show, index)
        if titles is not None:
            findings += check_act_in_title(show, index, titles[index])
        show, show_repairs = repair_show(
            show, index, flags=flags, source=source, page_html=page_html, page_text=page_text, titles=titles,
        )
        repairs += show_repairs
        kept.append((index, show))

    # A title the splitter left out of its answer would otherwise look exactly like an exclusion.
    for missing in notes.get("missing_ids") or []:
        findings.append(Finding(
            CheckCode.SPLITTER_DROPPED, Severity.ERROR,
            f"the act splitter returned no answer for listing {missing}", missing,
        ))

    if source == "jsonld":
        findings += check_under_reported(extraction, page_text, fetched_on)
    # D10: no kept show (an empty list, or every show excluded) on a page whose text names dates.
    if not kept and outcome is not PageOutcome.UNREADABLE and source != "image":
        findings += check_empty_but_dated(page_text, fetched_on, {(s.date.month, s.date.day) for s in extraction.shows})

    confidence = aggregate_confidence(kept, source, set(notes.get("added_indices") or []))
    result = ValidationResult(
        outcome=outcome, findings=findings, repairs=repairs, excluded=excluded, confidence=confidence,
    )
    return result, [show for _, show in kept]
