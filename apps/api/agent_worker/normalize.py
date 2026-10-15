"""Turn the sloppy time strings a model emits into real `datetime.time` values.

Why this exists (docs/dev/implementations/a2-extraction-schema.md, Design › "Time
normalizer"): Pydantic's own `datetime.time` parsing is strict. It rejects "7pm",
"7:30 PM", "8:00pm" and "24:00", and it *accepts* an integer like 68400 as a
timezone-aware 19:00 that would never compare equal to the database's naive `time`
column. A model asked for "HH:MM" mostly complies, but one rejected time fails the whole
page and triggers a full re-ask — and A2 triples the number of time fields per show. So
the schema *asks* for 24-hour HH:MM (the field description is an instruction to the model)
and this function *converts* what comes back before Pydantic validates it. An
instruction the model may ignore is not a format guarantee.

The rule is: **normalize what has one sensible reading; refuse the rest.** A 12-hour time
with no AM/PM ("7:30", "7") is read as PM. That is a decision, not a certainty (Ari,
October 10, 2026, reversing the plan's original "reject and re-ask"): live music is
overwhelmingly afternoon and evening, and a listing that really is in the morning says
AM. A two-digit "10:30" is left alone, because it is exactly the 24-hour HH:MM format the
schema asks for — telling the model to assume PM before converting is the field
description's job, not this function's.

How to read it: `normalize_time` is a Pydantic `BeforeValidator`; it receives the raw
value and returns either a `datetime.time`, `None`, or something Pydantic will then
validate itself. Anything it won't accept raises `ValueError`, which Pydantic reports as
a validation error, so `instructor` re-asks exactly as it did before.

A2.1 added three small helpers at the end of the file, each a rule that code applies to
what the model returns rather than trusting the model with it: `false_to_none` (A2-F1),
`infer_year` (A2.1-D13: the year comes from the fetch date) and `fold_text` (one comparison form
for names). docs/dev/implementations/a2.1-extraction-reliability.md says why each exists.
"""

import datetime
import html
import re
import unicodedata
from typing import Any

# Words a model writes when told "otherwise null" and it decides to spell it out.
# They mean "the page doesn't state a time".
_NULLISH = {"", "null", "none", "n/a", "na", "tbd", "tba", "unknown"}

# 12-hour clock: "7pm", "7 PM", "7:30pm", "7:30 p.m.", "12:15am", the bare "7p" / "8:30p"
# form some venue pages use themselves (the Midway calendar), and — meridiem omitted —
# "7:30" or "7", which are read as PM. It is tried *after* the 24-hour pattern, so a
# two-digit "10:30" never reaches it.
_TWELVE_HOUR = re.compile(
    r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?::(?P<second>\d{2}))?\s*(?:(?P<meridiem>[ap])\.?(?:m\.?)?)?$"
)

# 24-hour clock, optionally with seconds (and fractions of a second, which plain Pydantic
# also accepts, so refusing them would make the normalizer worse than none) and an optional
# zone suffix we throw away: "19:30", "07:30", "19:30:00", "19:30:00.000", "19:30:00Z",
# "19:30-05:00". Hour must be two digits — a bare "7:30" is NOT matched here; it is a
# 12-hour time with the meridiem left off (see module docstring).
_TWENTY_FOUR_HOUR = re.compile(
    r"^(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:[.,](?P<fraction>\d+))?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?$",
    re.IGNORECASE,
)


def normalize_time(value: Any) -> Any:
    """Convert an unambiguous time spelling to `datetime.time`; refuse anything else.

    Returns `None` for "not stated" spellings, and passes `None` through. An
    already-built `datetime.time` keeps its wall-clock value with the zone dropped
    (a listing means the venue's local clock; the database column is naive).
    """
    if value is None:
        return None

    # bool is a subclass of int, so it must be named explicitly; a number is never a
    # clock reading here (Pydantic alone would take 68400 as 19:00+00:00).
    # ValueError, not TypeError (ruff's TRY004), on purpose: Pydantic turns a ValueError
    # raised in a validator into a validation error that `instructor` re-asks on; a
    # TypeError would escape as a crash.
    if isinstance(value, bool | int | float):
        raise ValueError(f"a time must be written as HH:MM, not a number: {value!r}")  # noqa: TRY004

    if isinstance(value, datetime.time):
        return value.replace(tzinfo=None)

    if not isinstance(value, str):
        raise ValueError(f"a time must be a string like '19:30', got {type(value).__name__}")  # noqa: TRY004

    text = value.strip()
    if text.lower() in _NULLISH:
        return None

    twenty_four = _TWENTY_FOUR_HOUR.match(text)
    if twenty_four:
        # Fraction digits -> microseconds ("5" -> 500000), truncating past six places.
        fraction = (twenty_four["fraction"] or "").ljust(6, "0")[:6]
        return _build(
            int(twenty_four["hour"]),
            int(twenty_four["minute"]),
            int(twenty_four["second"] or 0),
            value,
            int(fraction or 0),
        )

    twelve = _TWELVE_HOUR.match(text.lower())
    if twelve:
        hour = int(twelve["hour"])
        minute = int(twelve["minute"] or 0)
        second = int(twelve["second"] or 0)
        if not 1 <= hour <= 12:  # "0pm", "13pm" are not 12-hour times
            raise ValueError(f"not a valid 12-hour time: {value!r}")
        # No meridiem means PM (module docstring). 12am is midnight (00), 12pm is noon
        # (12); everything else shifts by 12 for pm.
        meridiem = twelve["meridiem"] or "p"
        hour = hour % 12 + (12 if meridiem == "p" else 0)
        return _build(hour, minute, second, value)

    raise ValueError(f"unrecognised time {value!r}; use 24-hour HH:MM")


def _build(
    hour: int, minute: int, second: int, original: Any, microsecond: int = 0
) -> datetime.time:
    # datetime.time rejects 24:00, 25:00, minute 60, … with its own ValueError; re-raise
    # with the original text so the re-ask message the model sees names what it wrote.
    try:
        return datetime.time(hour, minute, second, microsecond)
    except ValueError as err:
        raise ValueError(f"not a valid time: {original!r}") from err


# ---------------------------------------------------------------------------
# A2.1 additions (docs/dev/implementations/a2.1-extraction-reliability.md)
# ---------------------------------------------------------------------------


def false_to_none(value: Any) -> Any:
    """`free_admission: false` -> None (A2-F1 of the A2 eval; A2.1-D6).

    The model wrote `false` on 56 shows whose pages state no admission at all, despite
    "otherwise null". Downstream, `false` would read as "confirmed not free", a claim the page
    never made, and nothing needs a stated "not free" (absence of a price never implies free:
    requirements-initial.md, Show). So `false` is folded into "not stated". Used as a
    BeforeValidator, so the JSON schema the model sees is unchanged, as with `normalize_time`.
    """
    return None if value is False else value


# How far before the fetch date a listed date may fall and still be read as this year: a page
# can keep a show up for a few weeks after it happens, but nothing further back than this is
# an upcoming listing (A2.1-D13). Public since A3: validation.py's date-plausibility window
# uses the same number, so the year rule and the check can't drift apart.
YEAR_LOOKBACK = datetime.timedelta(days=31)


def infer_year(listed: datetime.date, fetch_date: datetime.date) -> datetime.date:
    """Set a listed date's year from the fetch date (A2.1-D13 — decided by Ari: in code).

    The model is not trusted with a year: Mortimer's states none and the model guessed 2024.
    Rule: keep the month and day; the year is the one that puts the date no more than 31 days
    before the fetch date and otherwise as soon after it as possible — so a January listing
    scanned in December is next year, and a late-December listing scanned in early January is
    last year. It overrides the model's year even where a page states one; on a page of
    upcoming listings the rule gives the same answer.

    A Feb 29 in a year that has none returns the date unchanged (A3's plausibility check is the
    backstop) rather than raising.
    """
    earliest = fetch_date - YEAR_LOOKBACK
    # Compare (month, day) pairs rather than building dates, so Feb 29 can be placed before
    # knowing whether the chosen year has one.
    month_day = (listed.month, listed.day)
    if month_day >= (earliest.month, earliest.day):
        year = earliest.year
    else:
        year = earliest.year + 1
    try:
        return listed.replace(year=year)
    except ValueError:
        return listed


# Typographic characters that vary between a venue's page, its JSON-LD and a model's echo of
# either, mapped to one plain form. NFKC alone leaves curly quotes and dashes as they are
# (plan review #5: "Dan’s" != "Dan's" after NFKC).
_TYPOGRAPHIC = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "″": '"',
    "–": "-", "—": "-",
    " ": " ",
})


def fold_text(text: str) -> str:
    """One comparison form for names: entities unescaped, NFKC, typographic punctuation made
    plain, whitespace collapsed, lower-cased.

    Shared by the act splitter's title cross-check and the eval's scorer, so "The Dan’s",
    "The Dan's" and "the dan&#8217;s" are the same name everywhere. For comparing only — never
    for display or storage, which keep the venue's own spelling.
    """
    unescaped = html.unescape(text)
    normalised = unicodedata.normalize("NFKC", unescaped).translate(_TYPOGRAPHIC)
    return " ".join(normalised.split()).casefold()


# Words too common in listing titles to identify anything ("The", "with", "OPEN MIC Every Monday").
_FILLER = {
    "the", "and", "with", "every", "night", "nights", "early", "late", "show", "presents",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}


def identifying_words(text: str) -> set[str]:
    """The words of a title or act list that can identify it: folded, three letters or more,
    filler dropped. Shared by the eval's leak test and the status merge, which both decide
    whether two pieces of text name the same listing (code review round 2, #1: matching on any
    shared word, "the" included, marked the wrong show cancelled)."""
    words = "".join(c if c.isalnum() else " " for c in fold_text(text)).split()
    return {w for w in words if len(w) >= 3 and w not in _FILLER}

