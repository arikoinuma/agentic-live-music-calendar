"""Hand-written facts about each eval fixture, used to score extraction runs.

Not A8's full hand-labelling (build plan A8): this is only the handful of facts that
make three of A2's questions countable — "did a non-music entry leak into `shows`?",
"did the model invent an end time?", "did it invent a start time the page never
states?". It is written once, by reading each fixture, *before* the baseline run, so the
baseline and every later run are scored against the same thing. The same facts are
tabled in docs/dev/implementations/a2-extraction-schema.md under "Eval reference".

How to read it: one `FixtureReference` per fixture, keyed by `fixture_key()` (a short
name derived from the file name, since the saved-page names contain spaces and dashes).
Match terms are lower-case substrings tested against each returned act name.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FixtureReference:
    # Substrings (lower-case) that identify an entry the requirements say is NOT a show:
    # karaoke, open mic, comedy, a party with no identifiable artist, and "DJ Night"
    # without a named DJ (requirements-initial.md "…don't have performing artists";
    # DJ/comedy scope decided by Ari, Oct 9 2026). A returned act matching one of these
    # is a leak.
    non_music_terms: tuple[str, ...] = ()
    # Entries that read as music but are judgement calls; reported, never scored as leaks.
    borderline_terms: tuple[str, ...] = ()
    # True if the page itself states an end time for its listings. Where False, any
    # returned `end_time` is invented.
    states_end_time: bool = False
    # True if the page states a start time for its listings. Where False, any returned
    # show `time` is invented (the case v0.1-G8 exists for).
    states_start_time: bool = True
    # True if listings carry a price. Where False, any admission price is invented.
    states_price: bool = False
    # Rough count of real shows on the page, for reading the "shows found" column; not
    # an exact label (the Midway grid in particular is ambiguous about dates).
    approx_shows: int | None = None
    note: str = field(default="", compare=False)


REFERENCE: dict[str, FixtureReference] = {
    # 12 listings, each "6:00 pm - 8:00 pm" style, so every one states an end time.
    # No prices, no non-music entries. Nine are multi-act ("X w. Y, Z"); three are solo.
    "white_squirrel": FixtureReference(
        states_end_time=True, approx_shows=12,
        note="every listing has a start AND end time; nine multi-act, three single-act",
    ),
    # Month grid with start times like "7p". Non-music: weekly Pool Tournament, MNUFC
    # GAMEDAY, MEGASTELLAR OPEN MIC NIGHT (twice). "Blues Jam with Moses Oakland" is a
    # jam hosted by a named person — borderline. No end times, no prices.
    "midway": FixtureReference(
        non_music_terms=("pool tournament", "gameday", "open mic"),
        borderline_terms=("blues jam",),
        approx_shows=11,
        note="11 clear music entries plus six Blues Jams; the grid's month/year is ambiguous",
    ),
    # 24 listings, every one with a start time and a single price (so admission_day,
    # advance null). Multi-act almost throughout. "Karaoke" appears only as a nav link,
    # not as a listing, so any act containing it is a leak. DJ Adatrack / ECID is a
    # named DJ => a show.
    "zhora": FixtureReference(
        non_music_terms=("karaoke",), states_price=True, approx_shows=24,
        note="single price per listing; the page gives no end times",
    ),
    # Recurring header entries (OPEN MIC Mondays, DJ Night Wednesdays — no named DJ,
    # OPEN COMEDY Thursdays) are NOT shows; eight dated shows follow. The page states
    # NO times and NO prices, so any `time` is invented — the case that exposes v0.1-G8.
    "terminal_html": FixtureReference(
        non_music_terms=("open mic", "comedy", "dj night"),
        states_start_time=False, approx_shows=8,
        note="no times anywhere on the page; dates only",
    ),
    # Posters: one show each. Poster 1: The Envies / Müllet / Kurt Russell's Muscles,
    # Fri Aug 7, 8:30PM, $10. Poster 2: Cowboy Thoughts / Buried Animals / Rupert
    # Angeleyes, Aug 8, 9PM, $10. Neither states an end time; both state one price.
    # A2.1's new gated pages (October 10 captures). 7th St Entry: music only, no times or
    # prices in the listing. Mortimer's: weekly comedy open mics and karaoke between ~7 shows;
    # no times or prices in its text.
    "seventh_st_entry": FixtureReference(
        states_start_time=False, approx_shows=30,
        note="headliner | tour | with | support; two cancelled and one postponed listing",
    ),
    "mortimers": FixtureReference(
        non_music_terms=("comedy", "karaoke", "open mic"), states_start_time=False, approx_shows=7,
        note="18 entries, 11 of them weekly comedy or karaoke",
    ),
    "terminal_poster_1": FixtureReference(states_price=True, approx_shows=1),
    "terminal_poster_2": FixtureReference(states_price=True, approx_shows=1),
}


# A2.1's captures are named `<venue>-<YYYY-MM-DD>.html` (eval/capture.py); each venue maps to
# the REFERENCE entry for its page type (A2.1-PR1-12).
_CAPTURE_KEYS = {
    "white_squirrel": "white_squirrel", "terminal": "terminal_html", "zhora": "zhora",
    "midway": "midway", "seventh_st_entry": "seventh_st_entry", "mortimers": "mortimers",
}


def fixture_key(path: Path) -> str:
    """Map a fixture's file name to its REFERENCE key. Unknown files get their stem."""
    name = path.name.lower()
    capture = re.fullmatch(r"(?P<venue>[a-z_]+)-\d{4}-\d{2}-\d{2}", path.stem)
    if capture and capture["venue"] in _CAPTURE_KEYS:
        return _CAPTURE_KEYS[capture["venue"]]
    if name.startswith("archives"):
        return "white_squirrel"
    if name.startswith("calendar - the midway"):
        return "midway"
    if "zhora" in name:
        return "zhora"
    if name.startswith("terminal bar"):
        return "terminal_html"
    if name.startswith("terminal_bar_show_1"):
        return "terminal_poster_1"
    if name.startswith("terminal_bar_show_2"):
        return "terminal_poster_2"
    return path.stem
