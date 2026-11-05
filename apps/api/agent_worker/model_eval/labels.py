"""Hand-written ground truth for the eval pages, scored by Ari's accuracy standard.

Each `PageLabel` says, for one fixture, which shows the page really lists — date, acts, and
the fields the page states — and which entries on it are NOT shows (karaoke, comedy, a
recurring header), so the scorer can tell a tolerated leak from an invented show
(docs/dev/implementations/a2.1-extraction-reliability.md, A2.1-D1, A2.1-D2, A2.1-D5, A2.1-D11; the standard itself
is in requirements-initial.md, "Agent Extraction: Accuracy Standards").

How labels were written (so they can be checked):
- **From the page text, never from JSON-LD or a model's output.** Each show carries the
  `source_line` it was read from, so a reviewer can check a row without opening the fixture.
- **A field left as None means the page doesn't state it** — then any returned value there is
  wrong (an invented value). A start time is labelled only where the page's text states one.
- **Acts follow A2.1-D5's conventions** (`prompts._act_conventions()`); a row where a convention was
  a judgement call names it in `convention`, and a genuinely ambiguous title lists its other
  acceptable readings in `alternatives`. Ari confirms those rows before the first gated run.
- **Labels describe the captured page**, not the venue's whole season.

How to read it: the dataclasses; `VENUE_FACTS` (what the pipeline will read from each venue's
database row, plus where to fetch it); then `PAGE_LABELS`, one entry per fixture file, grouped
by venue.
"""

import datetime
from dataclasses import dataclass

D = datetime.date
T = datetime.time


@dataclass(frozen=True)
class NonShow:
    """An entry the page lists that is not a show (A2.1-D5 and A2.1-D12, and the exclusion rule). A returned
    show on its `date`, or on its `weekday` (0 = Monday) for a recurring header such as
    "OPEN MIC Every Monday", is scored as a tolerated leak, not a fabrication."""

    title: str
    date: datetime.date | None
    weekday: int | None
    reason: str


@dataclass(frozen=True)
class LabelledShow:
    """One real show on a page. Every optional field is None when the page doesn't state it."""

    date: datetime.date
    acts: tuple[str, ...]
    source_line: str
    time: datetime.time | None = None
    end_time: datetime.time | None = None
    admission_advance: float | None = None
    admission_day: float | None = None
    free_admission: bool | None = None
    status: str = "scheduled"  # A2.1-D12: cancelled / postponed listings are labelled with status
    convention: str | None = None  # the A2.1-D5 judgement call applied, if any
    alternatives: tuple[tuple[str, ...], ...] = ()  # other acceptable act sets (A2.1-D5)


@dataclass(frozen=True)
class PageLabel:
    """Everything the scorer needs to know about one fixture."""

    venue: str  # a VENUE_FACTS key
    gated: bool  # A2.1-D2: True only for pages production can actually fetch
    captured_on: datetime.date  # the fetch date the year rule (A2.1-D13) uses for this fixture
    shows: tuple[LabelledShow, ...]
    non_shows: tuple[NonShow, ...] = ()
    note: str = ""
    # C5-D3: set aside for C6's held-out test. A held-out page is labelled now (label once) but is in no default set, so the
    # baseline and every tuning run never score it; `--set held_out` is how C6 scores it, and the results file says it did.
    held_out: bool = False


@dataclass(frozen=True)
class VenueFacts:
    """What the pipeline will read from a venue's database row (name, metro zone), plus the
    calendar URL capture fetches. The first four venues are `app/db/seed.py`'s; 7th St Entry,
    Mortimer's and the Uptown Art House were offered by Ari on October 10, 2026 and are not in
    the seed. Every zone is the seeded metro's (`America/Chicago`)."""

    name: str
    url: str
    metro_timezone: str = "America/Chicago"
    feed_url: str | None = None  # a public calendar feed, captured for later (no reader yet)
    # Why a plain fetch can't get this venue's listings; capture skips it unless named (A2.1-D3).
    blocked: str | None = None


VENUE_FACTS: dict[str, VenueFacts] = {
    "white_squirrel": VenueFacts("The White Squirrel Bar", "https://whitesquirrelbar.com/calendar/"),
    "terminal": VenueFacts("The Terminal Bar", "https://terminalbarmn.com/live-music/",
                           blocked="show details are in poster images; image route deferred (arch-initial.md §11)"),
    "zhora": VenueFacts("Zhora Darling", "https://www.zhoradarling.com/events",
                        blocked="listings drawn client-side by the DICE widget; needs a browser"),
    "midway": VenueFacts("The Midway Saloon", "https://www.themidwaysaloon.com/events",
                         blocked="HTTP 403 Cloudflare bot challenge; not to be worked around (D3)"),
    "seventh_st_entry": VenueFacts("7th St Entry", "https://first-avenue.com/shows/?venues=59161"),
    "mortimers": VenueFacts("Mortimer's", "https://www.mortimerscalendar.com/"),
    "uptown_arthouse": VenueFacts(
        "Uptown Art House Theater & Gallery",
        "https://uptownarthousetheater.org/shows-events.html",
        feed_url="https://calendar.google.com/calendar/ical/arthousetheatermpls%40gmail.com/public/basic.ics",
    ),
    "ginkgo_coffee": VenueFacts(
        "Ginkgo Coffeehouse",
        "https://ginkgocoffee.com/events/list/",
    ),
    "finnish_bistro": VenueFacts(
      "The Finnish Bistro",
      "https://finnishbistro.com/events/",
      blocked="HTTP 403; not to be worked around (A2.1-D3)"
    ),
    "cloudland": VenueFacts(
      "Cloudland",
      "https://www.cloudlandtheater.com/",
      blocked="show details are in poster images; image route deferred (arch-initial.md §11)",
    ),
    "331": VenueFacts(
      "331 Club",
      "https://331club.com/",
      blocked="show details load via JavaScript on the home page, will be tricky to read the calendar",
    ),
    "hook_ladder": VenueFacts(
        "The Hook & Ladder",
        "https://thehookmpls.com/events/",
    ),
    "turf_club": VenueFacts(
        "Turf Club",
        "https://first-avenue.com/shows/?venues=26147"
    )

}

# The August fixtures were saved from a browser on this date (their files' dates; the White
# Squirrel page lists August 17-22).
AUGUST_CAPTURE = D(2026, 8, 17)

OCTOBER_CAPTURE = D(2026, 10, 10)  # model_eval/capture.py, the pipeline's own fetch

NOVEMBER_CAPTURE = D(2026, 11, 4) # Ari's manual effort as part of the milestone C5

S = LabelledShow  # short alias: the rows below are long enough already

# Recurring headers on both Terminal Bar pages: "OPEN MIC Every Monday", "DJ Night Every
# Wednesday" (no DJ named), "OPEN COMEDY Every Thursday" — not shows (exclusion rule).
_TERMINAL_HEADERS = (
    NonShow("OPEN MIC Every Monday", None, 0, "open mic"),
    NonShow("DJ Night Every Wednesday", None, 2, "DJ night with no DJ named"),
    NonShow("OPEN COMEDY Every Thursday", None, 3, "comedy"),
)

PAGE_LABELS: dict[str, PageLabel] = {
    # -------------------------------------------------------------------------------------
    # White Squirrel — gated. Every listing states start and end ("6:00 pm - 8:00 pm"); no
    # prices. Its JSON-LD (the route A2.1-D4 adds) carries the same listings, but these rows were
    # read from the visible text.
    # -------------------------------------------------------------------------------------
    "Archives_ Events - The White Squirrel Bar.html": PageLabel(
        venue="white_squirrel", gated=True, captured_on=AUGUST_CAPTURE, shows=(
            S(D(2026, 8, 17), ("The Cottonwood Shivers", "Nat Harriet"), "The Cottonwood Shivers w. Nat Harriet / Monday August 17 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0)),
            S(D(2026, 8, 17), ("Nona",), "Nona / Monday August 17 @ 9:00 pm - 12:00 am", T(21, 0), T(0, 0)),
            S(D(2026, 8, 18), ("The New Havoline Supremes",), "The New Havoline Supremes / Tuesday August 18 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0)),
            S(D(2026, 8, 18), ("Alex & Toke", "Joan Of Profile", "Meghan Kreidler"),
              "Alex & Toke’s (Pullstring) Acoustic Tuesdays: Ft. Joan Of Profile, Meghan Kreidler (Kiss The Tiger) / Tuesday August 18 @ 9:00 pm - 12:00 am",
              T(21, 0), T(0, 0), convention="series name is not an act; parenthetical dropped. Ari decided (Oct 10): a live music show; (Oct 11): a music series' named hosts are acts — Alex & Toke (of Pullstring). The possessive form and the band name are accepted too",
              alternatives=(("Alex & Toke’s", "Joan Of Profile", "Meghan Kreidler"), ("Pullstring", "Joan Of Profile", "Meghan Kreidler"))),
            S(D(2026, 8, 19), ("Ye-Ye Pow", "Les Souvenirs"), "Ye-Ye Pow w. Les Souvenirs / Wednesday August 19 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0)),
            S(D(2026, 8, 19), ("Lord Jeremy", "Enemies", "The Limns", "Woodzen"),
              "Lord Jeremy w/ Enemies w. The Limns, Woodzen / Wednesday August 19 @ 9:00 pm - 12:00 am", T(21, 0), T(0, 0),
              convention="Ari decided (Oct 10, revising his first answer): 'w/' more likely introduces opening acts than a band name, so split, as the conventions say. 'Lord Jeremy w/ Enemies' as one act is also accepted",
              alternatives=(("Lord Jeremy w/ Enemies", "The Limns", "Woodzen"),)),
            S(D(2026, 8, 20), ("Martin Devaney & Friends", "Wesley Church & the Fabulous Vanguards"),
              "Martin Devaney & Friends w. Wesley Church & the Fabulous Vanguards / Thursday August 20 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0),
              convention="'&' inside a name stays"),
            S(D(2026, 8, 20), ("Lent", "Gills", "Boomdagger"), "Lent w. Gills, Boomdagger / Thursday August 20 @ 9:00 pm - 12:00 am", T(21, 0), T(0, 0)),
            S(D(2026, 8, 21), ("Aaron James", "Bury ‘Em Deep"), "Aaron James w. Bury ‘Em Deep / Friday August 21 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0)),
            S(D(2026, 8, 21), ("Dusk Rat", "Tiny Traces", "Fauna Sauna"), "Dusk Rat w. Tiny Traces, Fauna Sauna / Friday August 21 @ 9:00 pm - 12:00 am", T(21, 0), T(0, 0)),
            S(D(2026, 8, 22), ("Francis Emil Johnson", "Cody James", "The Weeping Covenant"), "Francis Emil Johnson w. Cody James, The Weeping Covenant / Saturday August 22 @ 1:00 pm - 4:00 pm", T(13, 0), T(16, 0)),
            S(D(2026, 8, 22), ("Caitlin Robertson",), "Caitlin Robertson / Saturday August 22 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0)),
        ),
    ),
    "white_squirrel-2026-10-10.html": PageLabel(
        venue="white_squirrel", gated=True, captured_on=OCTOBER_CAPTURE, shows=(
            S(D(2026, 10, 10), ("Catfish Troy & Friends", "Sammie Jean Cohen"), "Catfish Troy & Friends w. Sammie Jean Cohen / Saturday October 10 @ 1:00 pm - 4:00 pm", T(13, 0), T(16, 0),
              convention="'&' inside a name stays"),
            S(D(2026, 10, 10), ("120 Minutes", "Big Trouble", "Catfish Blue"),
              "Steve McPherson’s 50th Birthday ft. 120 Minutes, Big Trouble, Catfish Blue / Saturday October 10 @ 5:00 pm - 8:00 pm", T(17, 0), T(20, 0),
              convention="event name is not an act"),
            S(D(2026, 10, 10), ("Joan of Profile", "Cassandra Johnson", "Eldest Daughter"), "Joan of Profile w. Cassandra Johnson, Eldest Daughter / Saturday October 10 @ 9:00 pm - 12:00 am", T(21, 0), T(0, 0)),
            S(D(2026, 10, 11), ("Nici Peper", "Sarah VanVolkenberg", "Doyle Turner", "AJ Schieber"),
              "Songwriter Showcase: Nici Peper, Sarah VanVolkenberg, Doyle Turner, AJ Schieber / Sunday October 11 @ 1:00 pm - 4:00 pm", T(13, 0), T(16, 0),
              convention="series name is not an act"),
            S(D(2026, 10, 11), ("Potential New Boyfriend", "Clawhammer Mike & The Old-Time Barnstormers"),
              "Potential New Boyfriend w. Clawhammer Mike & The Old-Time Barnstormers / Sunday October 11 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0),
              convention="Ari decided (Oct 10): probably two acts — Potential New Boyfriend, and Clawhammer Mike with his band as one billing (an artist and a backing band are one act, as in 'Slash and the Conspirators'). 'Probably', so the three-act reading is also accepted",
              alternatives=(("Potential New Boyfriend", "Clawhammer Mike", "The Old-Time Barnstormers"),)),
            S(D(2026, 10, 12), ("Mumblin’ Drew’s Oldfangled Orchestrators",), "Mumblin’ Drew’s Oldfangled Orchestrators / Monday October 12 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0)),
            S(D(2026, 10, 12), ("Basement Heroes", "Calavrosa", "Buzzbox"), "Basement Heroes w. Calavrosa, Buzzbox / Monday October 12 @ 9:00 pm - 12:00 am", T(21, 0), T(0, 0)),
            S(D(2026, 10, 13), ("The Dan’s",), "The Dan’s / Tuesday October 13 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0),
              convention="title only: the description's guests (Pat Donohue, Erik Lillestol) are not added"),
            S(D(2026, 10, 13), ("DJ Dedicated Enemy",), "DJ Dedicated Enemy / Tuesday October 13 @ 9:00 pm - 12:00 am", T(21, 0), T(0, 0),
              convention="a named DJ is an act"),
            S(D(2026, 10, 14), ("Molly Maher",), "Molly Maher / Wednesday October 14 @ 6:00 pm - 8:00 pm", T(18, 0), T(20, 0)),
            S(D(2026, 10, 14), ("Cole Diamond",), "Cole Diamond’s Whiskey Wednesdays / Wednesday October 14 @ 9:00 pm - 11:00 pm", T(21, 0), T(23, 0),
              convention="Ari decided (Oct 10): Cole Diamond is the artist; 'Whiskey Wednesdays' is the series name"),
        ),
        non_shows=(NonShow("Open Jam", D(2026, 10, 11), None, "open jam: no performing artist named"),),
    ),
    # -------------------------------------------------------------------------------------
    # Terminal Bar — informational since October 11, 2026 (Ari: an outlier; A2.1-D2 revised). Its layout —
    # a date line, then one line per act — defeated every rung that helped the other pages (the model
    # takes the first line as the act and turns later lines into extra shows). The text states dates
    # and acts, never a time (the times are in
    # the poster images, which the image path would read — deferred); no prices. Each act
    # line is its own <br> line on the page (A2.1-PR1-1).
    # -------------------------------------------------------------------------------------
    "Terminal Bar – The Terminal Bar.html": PageLabel(
        venue="terminal", gated=False, captured_on=AUGUST_CAPTURE, non_shows=_TERMINAL_HEADERS, shows=(
            S(D(2026, 8, 7), ("Envies",), "Friday August 7th / Envies",
              convention="title only: the poster names two more acts; the page text names one"),
            S(D(2026, 8, 8), ("Cowboy Thoughts",), "Saturday August 8th / Cowboy Thoughts",
              convention="title only: the poster names two more acts; the page text names one"),
            S(D(2026, 8, 14), ("Sigtones", "Muffleur", "Dirty 930"), "Friday August 14th / Sigtones / Muffleur / Dirty 930"),
            S(D(2026, 8, 15), ("Xmas on Neptune",), "Saturday August 15th / Xmas on Neptune"),
            S(D(2026, 8, 21), ("Garrett Jones",), "Friday August 21st / Garrett Jones"),
            S(D(2026, 8, 22), ("NONA",), "Saturday Augusut 22nd / NONA"),
            S(D(2026, 8, 28), ("Man Down", "Justin Payne", "Larrkins"), "Friday Augusut 28th / Man Down / Justin Payne / Larrkins"),
            S(D(2026, 8, 29), ("Fighting the Urge", "Scarlett Tangerines"), "Saturday August 29th / Fighting the Urge / Scarlett Tangerines"),
        ),
    ),
    "terminal-2026-10-10.html": PageLabel(
        venue="terminal", gated=False, captured_on=OCTOBER_CAPTURE, shows=(
            S(D(2026, 10, 2), ("Griffin", "Alec C"), "Friday October 2nd / Griffin / Alec C"),
            S(D(2026, 10, 3), ("Vaguely Yours", "True Stories", "Mukwa"), "Saturday October 3rd / Vaguely Yours / True Stories / Mukwa"),
            S(D(2026, 10, 9), ("MLLT",), "Friday October 9th / MLLT"),
            S(D(2026, 10, 10), ("Jung Min-Noh", "Cowboy Thoughts", "Loan Sum"), "Saturday October 10th / Jung Min-Noh / Cowboy Thoughts / Loan Sum"),
            S(D(2026, 10, 16), ("Torrentia", "The F* All", "Massive Shadow", "Sweet Land"), "Friday October 16th / Torrentia / The F* All / Massive Shadow / Sweet Land"),
            S(D(2026, 10, 17), ("Customers Band", "Lone Sum", "Nancy Gross"), "Saturday October 17th / Customers Band / Lone Sum / Nancy Gross"),
            S(D(2026, 10, 23), ("Andrew Himmer",), "Friday October 23rd / Terminal Fest 2 / hosted by Andrew Himmer",
              convention="Ari decided (Oct 11): a music event's named host is an act; 'Terminal Fest 2' is the event's name"),
            S(D(2026, 10, 24), ("Hot Fruit", "houseluna"), "Saturday October 24th / Hot Fruit / houseluna"),
            S(D(2026, 10, 30), ("Pretty Pretty Please",), "Friday October 30th / Pretty Pretty Please"),
            S(D(2026, 10, 31), ("Cole Diamond", "Clayton Ryan Trio", "Cowboy Thoughts"), "Saturday October 31st / Cole Diamond / Clayton Ryan Trio / Cowboy Thoughts"),
        ),
        non_shows=(
            *_TERMINAL_HEADERS,
        ),
    ),
    # -------------------------------------------------------------------------------------
    # 7th St Entry — gated. October listing: headliner | tour or tag | with | support. No
    # times in the listing (they are on each show's detail page — a deeper fetch, deferred);
    # no prices. Cancelled / postponed listings are labelled with their status (A2.1-D12).
    # -------------------------------------------------------------------------------------
    "seventh_st_entry-2026-10-10.html": PageLabel(
        venue="seventh_st_entry", gated=True, captured_on=OCTOBER_CAPTURE, shows=(
            S(D(2026, 10, 1), ("Owen Riegling", "Payton Smith"), "Owen Riegling | In The Feeling Tour | with | Payton Smith", convention="tour name is not an act"),
            S(D(2026, 10, 2), ("Cardinal Bloom", "Holdfast."), "Cardinal Bloom | Burn the House Tour | with | Holdfast.", convention="tour name is not an act; the name is written with a period",
              alternatives=(("Cardinal Bloom", "Holdfast"),)),
            S(D(2026, 10, 3), ("Love Spells", "Orca"), "Love Spells | Love Is The Law World Tour | with | Orca", convention="tour name is not an act"),
            S(D(2026, 10, 4), ("Kennedy Ryon",), "Kennedy Ryon | The Can We Evolve? Tour", convention="tour name is not an act"),
            S(D(2026, 10, 6), ("Elizabeth Nichols", "Soren Anderson"), "Elizabeth Nichols | I Don't Kiss & Tell, I Kiss & Tour | with | Soren Anderson",
              convention="tour name removed before splitting"),
            S(D(2026, 10, 7), ("The Bright Light Social Hour", "Miradores del Sol"), "The Bright Light Social Hour | with | Miradores del Sol"),
            S(D(2026, 10, 8), ("Dana and Alden", "Alex Amen"), "Dana and Alden | with | Alex Amen",
              convention="Ari decided (Oct 10): probably one act (a duo), but there is no systematic way to tell from the title, so the split reading is also accepted",
              alternatives=(("Dana", "Alden", "Alex Amen"),)),
            S(D(2026, 10, 9), ("Bebe Stockwell", "Khatumu"), "Bebe Stockwell | with | Khatumu"),
            S(D(2026, 10, 10), ("Robert Ellis", "Philip Bowen"), "Cancelled | Robert Ellis | with | Philip Bowen (solo)", status="cancelled",
              convention="parenthetical dropped"),
            S(D(2026, 10, 11), ("Karina Rykman", "Tarias and the Sound"), "Karina Rykman | with | Tarias and the Sound",
              convention="Ari decided (Oct 10): probably two acts — Karina Rykman, and Tarias and the Sound as one billing. 'Probably', so the split reading is also accepted",
              alternatives=(("Karina Rykman", "Tarias", "the Sound"),)),
            S(D(2026, 10, 13), ("Silly Goose", "Cheem", "MUTTLEE"), "Silly Goose | The “Set It Off” Tour | with | Cheem | and | MUTTLEE", convention="tour name is not an act"),
            S(D(2026, 10, 14), ("First to Eleven", "Keepsake"), "First to Eleven | with | Keepsake"),
            S(D(2026, 10, 15), ("Emily Bjorke", "clovers daughter", "anni xo"), "Emily Bjorke | ‘Are You Going to Heaven or Hell’ Album Release | with | clovers daughter | and | anni xo",
              convention="album-release name is not an act"),
            S(D(2026, 10, 16), ("Telescreens", "Runner and Bobby", "Nautics"), "Telescreens | Why The Lights Flicker North American Tour | with | Runner and Bobby | and | Nautics",
              convention="tour name is not an act; 'Runner and Bobby' read as one act by analogy with Ari's answers on 'Tarias and the Sound' and 'Dana and Alden' — not confirmed by Ari; both readings accepted",
              alternatives=(("Telescreens", "Runner", "Bobby", "Nautics"),)),
            S(D(2026, 10, 17), ("Sophie Truax", "Sasha Cee"), "Cancelled | Sophie Truax | with | Sasha Cee", status="cancelled"),
            S(D(2026, 10, 17), ("Interlay", "12th House Sun", "abalone"), "Interlay | with | 12th House Sun | and | abalone"),
            S(D(2026, 10, 18), ("WILL DEMPSEY", "Gavin Hughes"), "WILL DEMPSEY | Carry The Weight Tour | with | Gavin Hughes", convention="tour name is not an act"),
            S(D(2026, 10, 19), ("RAV", "Teller Bank$", "Fatboi Sharif"), "RAV | with | Teller Bank$ | and | Fatboi Sharif"),
            S(D(2026, 10, 20), ("Hillhaven", "MVRROW", "onlytime"), "Hillhaven | with | MVRROW | and | onlytime"),
            S(D(2026, 10, 21), ("Baby Bugs", "Elliot Lee"), "postponed | Baby Bugs | with | Elliot Lee", status="postponed"),
            S(D(2026, 10, 22), ("Mati", "Moise", "Morgan McCarthy"), "Mati | ★ Local Show ★ | with | Moise | and | Morgan McCarthy", convention="tag is not an act"),
            S(D(2026, 10, 23), ("IAN SWEET", "meg elsier"), "IAN SWEET | with | meg elsier"),
            S(D(2026, 10, 24), ("DICE", "The Back Alley"), "DICE | with | The Back Alley"),
            S(D(2026, 10, 25), ("Wishy", "Dead Sullivan"), "Wishy | Nature’s Pill Tour | with | Dead Sullivan", convention="tour name is not an act"),
            S(D(2026, 10, 26), ("Delicate Steve", "Yellow Ostrich"), "Delicate Steve | with | Yellow Ostrich"),
            S(D(2026, 10, 27), ("Yana", "Emma Andersen"), "Yana | The Feelings are Forever Tour | with | Emma Andersen", convention="tour name is not an act"),
            S(D(2026, 10, 28), ("gavn!",), "gavn!"),
            S(D(2026, 10, 30), ("Count Spookula", "Hastings 3000", "King Sized Coffin", "Lusurfer", "DJ Eve"),
              "Count Spookula | A Halloween Eve Spooktacular with | Hastings 3000 | • | King Sized Coffin | • | Lusurfer | • | DJ Eve | ★ Local Show ★",
              convention="event name and tag are not acts; '•' separates acts"),
            S(D(2026, 10, 31), ("MARIS",), "MARIS"),
            S(D(2026, 10, 31), ("Daisy Hex", "bubucore69", "be3e", "Evilsoundguy"),
              "INTERNET KIDS Hyperpop Dance Party | Halloween: Night of the Living Core | featuring | Daisy Hex | • | bubucore69 | • | be3e | • | Evilsoundguy | • live visuals by | Visa_Card | • | Wizard.Imma | ★ Local Show ★",
              convention="night's name is not an act; 'live visuals by' credits are not acts. Ari decided (Oct 10): Wizard.Imma is a visual artist too"),
        ),
    ),
    # -------------------------------------------------------------------------------------
    # Mortimer's — gated. The labelling fill-in (A2.1-D11): rows by Ari and Claude, October 10.
    # -------------------------------------------------------------------------------------
    # Ground truth is a set of decisions, and writing it is where you find out how many there are.
    # The scorer can only be as right as these rows: each one decides what "correct" means for one
    # listing (A2.1-D1, A2.1-D5). Mortimer's has the most calls of any page: weekly comedy and karaoke between
    # real shows, a night's name in front of its performers, a B2B DJ set, a parenthetical hometown,
    # and an album-release show that ends in "+ Karaoke".
    #
    # No times are labelled, on purpose. The site shows start and end times (Ari checked:
    # e.g. Flange August Back to Back 10 pm), but they live in the page's embedded Wix event
    # data, not in its visible text — and the visible text is all the model route sends. A
    # time the pipeline can't see can only ever be "missing", and seven guaranteed misses
    # would sink the pooled 10% tier on every run for a reason no rung can fix. The page
    # states no year either (the year rule, A2.1-D13) and no prices. When a Wix reader exists
    # (deferred: build plan §8), the times become labellable.
    "mortimers-2026-10-10.html": PageLabel(
        venue="mortimers", gated=True, captured_on=OCTOBER_CAPTURE, shows=(
            S(D(2026, 10, 10), ("Flange August Back to Back",), "Flange August Back to Back / Sat, Oct 10",
              convention="Ari decided (Oct 10): one act. 'Flange August' without 'Back to Back' is accepted too",
              alternatives=(("Flange August",),)),
            S(D(2026, 10, 11), ("KENNY D", "MINI BLANCO"), "KENNY D + MINI BLANCO / Sun, Oct 11",
              convention="'+' separates acts"),
            S(D(2026, 10, 13), ("SAM WOODMAN",), "POPUP! W/ SAM WOODMAN / Tue, Oct 13",
              convention="a night's name is not an act", alternatives=(("POPUP!", "SAM WOODMAN"),)),
            S(D(2026, 10, 14), ("Boss's Daughter",), "Boss's Daughter (Reno) / Wed, Oct 14",
              convention="parenthetical (hometown) dropped, per the conventions the model is sent; Ari wrote it with '(Reno)', kept as an alternative",
              alternatives=(("Boss's Daughter (Reno)",),)),
            S(D(2026, 10, 15), ("DJ Gwiingwans", "Coagula", "PRSPHNE"), "SPELLBOUND w/ DJ Gwiingwans, Coagula, and PRSPHNE / Thu, Oct 15",
              convention="a night's name is not an act; a named DJ is an act",
              alternatives=(("SPELLBOUND", "DJ Gwiingwans", "Coagula", "PRSPHNE"),)),
            S(D(2026, 10, 16), ("Absolutely Yours", "Embahn", "The Vanity Project"),
              "Absolutely Yours Album Release Show w/ Embahn + The Vanity Project + Karaoke / Fri, Oct 16",
              convention="'+ Karaoke' is not an act. Ari decided (Oct 10): Absolutely Yours is the band — album releases focus on the artist name, not the album's"),
            S(D(2026, 10, 17), ("SUPPORTIVE PARENTS", "VIRGIN WHORES", "DAISYCUTTER", "BEHIND THE WIRE", "CA$UAL"),
              "SUPPORTIVE PARENTS + VIRGIN WHORES + DAISYCUTTER + BEHIND THE WIRE + CA$UAL / Sat, Oct 17",
              convention="'+' separates acts"),
        ), non_shows=(
            # Weekly, so one entry per weekday (6 = Sunday, 0 = Monday) rather than one per date:
            # Comedy Open Mic on Oct 11, 18, 25, Nov 1, 8, 15; Autotune Karaoke Oct 12, 19, 26,
            # Nov 2, 9. (Ari's rows, with the date/time arguments moved into the weekday field.)
            NonShow("Comedy Open Mic (Early)", None, 6, "comedy open mic, Sundays"),
            NonShow("Autotune Karaoke", None, 0, "karaoke, Mondays"),
        ),
    ),
    # -------------------------------------------------------------------------------------
    # Informational (not gated, A2.1-D2).
    # -------------------------------------------------------------------------------------
    # Zhora Darling, the August browser capture: a dense multi-act stress test, but production
    # can't fetch these listings (the DICE widget draws them with JavaScript). Times stated;
    # "Buy now $X" is an online ticket price, so admission_advance (A2.1-D7); no year (rule).
    "Events — Zhora Darling.html": PageLabel(
        venue="zhora", gated=False, captured_on=AUGUST_CAPTURE, shows=(
            S(D(2026, 8, 17), ("Torrentia", "Social Pariah", "Sweetland", "Divinum Insanus"), "Torrentia, Social Pariah, Sweetland, & Divinum Insanus / Mon 17 Aug ― 6:00pm / Buy now $15.24", T(18, 0), admission_advance=15.24),
            S(D(2026, 8, 18), ("Woolly Mack", "Anslem", "Cohen Bros", "Mike Midwestern"), "Woolly Mack, Anslem, Cohen Bros, & Mike Midwestern / Tue 18 Aug ― 6:30pm / Buy now $12.70", T(18, 30), admission_advance=12.7),
            S(D(2026, 8, 19), ("J-Mo On The Beat & The J-Lighters", "Mike Horvath", "D.Santos"), "J-Mo On The Beat & The J-Lighters, Mike Horvath, & D.Santos / Wed 19 Aug ― 6:30pm / Buy now $12.70", T(18, 30), admission_advance=12.7, convention="'&' inside a name stays"),
            S(D(2026, 8, 20), ("Grave Society", "Uxia", "Hill of Crosses", "Ambivalent Chaos"), "Grave Society, Uxia, Hill of Crosses, & Ambivalent Chaos / Thu 20 Aug ― 6:30pm / Buy now $12.70", T(18, 30), admission_advance=12.7),
            S(D(2026, 8, 21), ("Silva", "Grand Demise of Civilization", "Unsouling", "Cavernous Maw"), "Silva, Grand Demise of Civilization, Unsouling, & Cavernous Maw / Fri 21 Aug ― 6:30pm / Buy now $12.70", T(18, 30), admission_advance=12.7),
            S(D(2026, 8, 22), ("Shrive", "TFBUNDY", "Laugh Track", "Glurge"), "Shrive, TFBUNDY, Laugh Track, & Glurge / Sat 22 Aug ― 7:30pm / Buy now $12.70", T(19, 30), admission_advance=12.7),
            S(D(2026, 8, 25), ("Seer", "Crypt.id", "Semi Infamous", "X1ztyr"), "Seer, Crypt.id, Semi Infamous, & X1ztyr / Tue 25 Aug ― 7:00pm / Buy now $12.70", T(19, 0), admission_advance=12.7),
            S(D(2026, 8, 26), ("The Violet Ghost", "Osenya", "Mach Fox", "Color in Reverse"), "The Violet Ghost, Osenya, Mach Fox, & Color in Reverse / Wed 26 Aug ― 6:30pm / Buy now $19.06", T(18, 30), admission_advance=19.06),
            S(D(2026, 8, 29), ("MC Pirate Pants",), "Crazy Clyde Presents: The Return of MC Pirate Pants / Sat 29 Aug ― 7:00pm / Buy now $12.70", T(19, 0), admission_advance=12.7,
              convention="presenter and event name are not acts"),
            S(D(2026, 8, 30), ("Naked Eye", "The Lamellas", "The Dirty Pretty", "Bev"), "Naked Eye, The Lamellas, The Dirty Pretty, & Bev / Sun 30 Aug ― 6:30pm / Buy now $12.70", T(18, 30), admission_advance=12.7),
            S(D(2026, 9, 4), ("ECID", "OKnice", "DJ Adatrack"), "ECID w/ OKnice & DJ Adatrack / Fri 4 Sep ― 8:00pm / Buy now $15.24", T(20, 0), admission_advance=15.24),
            S(D(2026, 9, 8), ("Dillinger Four", "Dark Thoughts", "Cheap Glue"), "Dillinger Four, Dark Thoughts (PA), & Cheap Glue / Tue 8 Sep ― 6:30pm / Join The Waiting List $34.91", T(18, 30), admission_advance=34.91,
              convention="parenthetical dropped; a waiting-list price is still the online price"),
            S(D(2026, 9, 10), ("Parlour Magic", "Observant", "Drey DK"), "Windlass Presents: Parlour Magic (NYC), Observant, & Drey DK / Thu 10 Sep ― 7:00pm / Buy now $15.24", T(19, 0), admission_advance=15.24,
              convention="presenter is not an act; parenthetical dropped"),
            S(D(2026, 9, 11), ("The Motion Mosaic", "Wanderer", "The Central", "Andthecanaryfell", "RIME"), "The Motion Mosaic, Wanderer, The Central (WI), Andthecanaryfell, & RIME / Fri 11 Sep ― 7:00pm / Buy now $19.06", T(19, 0), admission_advance=19.06),
            S(D(2026, 9, 12), ("Lovely Dark", "Physics", "Wish Wash", "Night Audit"), "Lovely Dark, Physics, Wish Wash, & Night Audit / Sat 12 Sep ― 6:30pm / Buy now $19.06", T(18, 30), admission_advance=19.06),
            S(D(2026, 9, 16), ("THESAURUS REX", "Marie's Island", "Secret Menu"), "Out of Office Tour: THESAURUS REX w/ Marie's Island & Secret Menu / Wed 16 Sep ― 6:30pm / Buy now $19.06", T(18, 30), admission_advance=19.06,
              convention="tour name is not an act"),
            S(D(2026, 9, 18), ("VOID", "PHANTOM"), "VOID (LA) & PHANTOM (MX) / Fri 18 Sep ― 7:30pm / Buy now $25.38", T(19, 30), admission_advance=25.38),
            S(D(2026, 9, 19), ("Syncline", "Scorched Waves", "Toadstool"), "Syncline & Scorched Waves (WI) w/ Toadstool / Sat 19 Sep ― 7:00pm / Buy now $12.70", T(19, 0), admission_advance=12.7,
              convention="'&' between two bands"),
            S(D(2026, 9, 22), ("Something Meets Boy", "Larrikins", "Moneybones", "Midso"), "Something Meets Boy, Larrikins, Moneybones, & Midso / Tue 22 Sep ― 6:30pm / Buy now $15.24", T(18, 30), admission_advance=15.24),
            S(D(2026, 9, 24), ("YHWH NAILGUN",), "YHWH NAILGUN / Thu 24 Sep ― 7:00pm / Buy now $31.73", T(19, 0), admission_advance=31.73),
            S(D(2026, 9, 25), ("Blood Cookie", "NATL PARK SRVC", "Falcon Arrow"), "Blood Cookie, NATL PARK SRVC, & Falcon Arrow / Fri 25 Sep ― 7:00pm / Buy now $12.70", T(19, 0), admission_advance=12.7),
            S(D(2026, 9, 26), ("Friendly Fred",), "Friendly Fred: Never Too Late To Become Who You Are Album Release Party / Sat 26 Sep ― 7:30pm / Buy now $19.06", T(19, 30), admission_advance=19.06,
              convention="album-release name is not an act"),
            S(D(2026, 9, 30), ("Rachel Bochner",), "Rachel Bochner | The “Sorry If It’s Selfish” Tour / Wed 30 Sep ― 7:00pm / From $21.59", T(19, 0), admission_advance=21.59,
              convention="tour name is not an act; 'From $21.59' is the lowest online price"),
        ),
        non_shows=(NonShow("4th Annual SummerSlam of Tribute Bands", D(2026, 8, 28), None, "an event naming no performing acts"),),
        note="unreachable by the pipeline's plain fetch (Context); informational only",
    ),
    # The two Terminal Bar posters (the image path; deferred for live pages). Each states one
    # unlabelled price, so admission_day (A2.1-D7); no year (the rule supplies it).
    "terminal_bar_show_1.png": PageLabel(
        venue="terminal", gated=False, captured_on=AUGUST_CAPTURE, shows=(
            S(D(2026, 8, 7), ("THE ENVIES", "MÜLLET", "KURT RUSSELL'S MUSCLES"), "THE ENVIES / MÜLLET / KURT RUSSELL'S MUSCLES / TERMINAL BAR FRIDAY, AUGUST 7 8:30PM $10", T(20, 30), admission_day=10.0),
        ),
    ),
    "terminal_bar_show_2.webp": PageLabel(
        venue="terminal", gated=False, captured_on=AUGUST_CAPTURE, shows=(
            S(D(2026, 8, 8), ("COWBOY THOUGHTS", "BURIED ANIMALS", "RUPERT ANGELEYES"), "COWBOY THOUGHTS / BURIED ANIMALS / RUPERT ANGELEYES / TERMINAL BAR AUG 8 - 9PM - $10", T(21, 0), admission_day=10.0,
              convention="'OXYGEN' on the tanks in the drawing is not an act"),
        ),
    ),
    # -------------------------------------------------------------------------------------
    # Ginkgo's — gated. held out. The labelling fill-in (A2.1-D11): rows by Ari and Claude, November 4.
    # -------------------------------------------------------------------------------------
    "ginkgo_coffee-2026-11-04.html": PageLabel(
        venue="ginkgo_coffee",
        gated=True,
        captured_on=NOVEMBER_CAPTURE,
        held_out=True,
        note="Open mics are 1st and 3rd Wednesdays and trivia is Thursdays, each listed as its own dated entry. "
          "The 'Featured Concerts' block at the top shows Chuck Suchy dated 'November 14, 2025' (a stale year); "
          "the real listing is November 14, 2026.",
        shows = (
            S(D(2026, 11, 6), ("David Singley",), "David Singley / November 6 @ 6:00 pm", T(18, 0)),
            S(D(2026, 11, 13), ("JOAN",), "JOAN / November 13 @ 6:00 pm", T(18, 0)),
            S(D(2026, 11, 14), ("Chuck Suchy",), "Chuck Suchy / November 14 @ 7:30 pm", T(19, 30), admission_advance=20.0, admission_day=20.0, free_admission=False,
              convention="Tickets: $20 with an ORDER TICKETS link, when the ticket price doesn't specify advance or door, assume it applies to both"),
            S(D(2026, 11, 20), ("Mac Hoffman",), "Mac Hoffman / November 20 @ 6:00 pm", T(18, 0)),
            S(D(2026, 11, 27), ("Nicholas Soden",), "Nicholas Soden / November 27 @ 6:00 pm", T(18, 0)),
            S(D(2026, 12, 4), ("Cathie English",), "Cathie English / December 4 @ 6:00 pm", T(18, 0)),
        ),
        non_shows=(
            NonShow("Open Mic with host Neal Dimick", D(2026, 11, 4), None, "open mic"),
            NonShow("Open Mic with host Neal Dimick", D(2026, 11, 18), None, "open mic"),
            NonShow("Trivia Mafia", D(2026, 11, 5), None, "trivia night"),
            NonShow("Trivia Mafia", D(2026, 11, 12), None, "trivia night"),
            NonShow("Trivia Mafia", D(2026, 11, 19), None, "trivia night"),
            NonShow("Trivia Mafia", D(2026, 12, 3), None, "trivia night"),
        )
    ),
    # -------------------------------------------------------------------------------------
    # Hook & Ladder — gated, held out. The labelling fill-in (A2.1-D11): rows by Ari and Claude, November 4.
    # -------------------------------------------------------------------------------------
    "hook_ladder-2026-11-04.html": PageLabel(
        venue="hook_ladder", gated=True, captured_on=NOVEMBER_CAPTURE,
        held_out=True,
        note="Event names ('Sleepy Weekend', 'AMERIGRASS '26') are not acts. The page runs into January 2027. Each event "
            "carries a room (Theater / Zen Arcade), which the schema does not model. The two Trailer Trash titles say "
            "Friday and Saturday but are dated Saturday and Sunday.",
        shows=(
            S(D(2026, 11, 6), ("Paul Cebar & Tomorrow Sound",), "Paul Cebar & Tomorrow Sound / Theater / 6:30 pm", T(18, 30),
              alternatives=(("Paul Cebar", "Tomorrow Sound"),), convention="'&' may join two names or be one band name; both accepted"),
            S(D(2026, 11, 6), ("Heather Mae", "Mother Banjo"), "Heather Mae with Mother Banjo / Zen Arcade / 7 pm", T(19, 0)),
            S(D(2026, 11, 7), ("Sleeping Jesus", "Harlow", "anni xo", "Hiahli", "Simon Cropp & his All-Star Band", "Molly Brandt",
              "Kiernan", "Sugar Lads", "DJ Sumthyn Sumthyn"), "Sleepy Weekend with Sleeping Jesus, Harlow, ... / 6 pm", T(18, 0),
              convention="'Sleepy Weekend' is the event's name, not an act"),
            S(D(2026, 11, 8), ("Davy Knowles",), "Davy Knowles / Theater / 6 pm", T(18, 0)),
            S(D(2026, 11, 11), ("Sqwerv",), "Sqwerv 'Fall Tour 2026' / Theater / 7:30 pm", T(19, 30), convention="tour name is not an act"),
            S(D(2026, 11, 12), ("ODD1OUT", "EMPTHY", "Obsidian James"), "RISING VOICES feat. ODD1OUT, EMPTHY, Obsidian James / 7 pm", T(19, 0),
              convention="'RISING VOICES' is the event's name"),
            S(D(2026, 11, 13), ("Rue Nouveau",), "Rue Nouveau / Theater / 7 pm", T(19, 0)),
            S(D(2026, 11, 13), ("Andra Suchy", "The Long Honeymoon", "Mary K and the Realistix"),
              "Andra Suchy with The Long Honeymoon and Mary K and the Realistix / 7 pm", T(19, 0)),
            S(D(2026, 11, 14), ("Maygen & The Birdwatcher", "Rich Mattson and the Northstars", "Emmy Woods", "Ross Thorn"),
              "AMERIGRASS '26 with Maygen & The Birdwatcher, Rich Mattson and the Northstars, Emmy Woods, Ross Thorn / 6:30 pm", T(18, 30),
              convention="'AMERIGRASS '26' is the event's name; the acts are on the 'with' line"),
            S(D(2026, 11, 14), ("Golden Satellite", "Killed By Kiwis", "JuiceNeck"), "Golden Satellite / Killed By Kiwis / JuiceNeck / 7:30 pm", T(19, 30)),
            S(D(2026, 11, 20), ("Atypical Daydream",), "Deadsgiving Feat. Atypical Daydream / 7:30 pm", T(19, 30)),
            S(D(2026, 11, 20), ("Becca Murray & The Wildflowers", "Auronova"), "Clean Plate Club with Becca Murray & The Wildflowers and Auronova / 7:30 pm",
              T(19, 30), convention="'Clean Plate Club' is the night's name"),
            S(D(2026, 11, 21), ("Corpse Reviver", "Adam Kiesling", "Jillian Rae", "Pop Wagner", "Mikkel"),
              "SONGS OF LEAD BELLY ... feat. Corpse Reviver, Adam Kiesling, Jillian Rae, Pop Wagner, Mikkel / 6:30 pm", T(18, 30),
              convention="'Mikkel' exactly as the page writes it, in both the title and the 'with' line"),
            S(D(2026, 11, 21), ("Follow the Firefly", "Matt Wilson"), "Follow the Firefly Album Release w/ Guest Matt Wilson / 7 pm", T(19, 0),
              alternatives=(("Matt Wilson",),), convention="unclear whether 'Follow the Firefly' is the artist or the album"),
            S(D(2026, 11, 25), ("ELnO", "DJ TimeMachine"), "Drinksgiving with ELnO + DJ TimeMachine / 7 pm", T(19, 0),
              convention="'Drinksgiving' is the night's name; a named DJ is an act"),
            S(D(2026, 11, 27), ("Bluedog", "Jada Brown", "Laura Hugo", "Corey Medina & Brothers", "Imnížaska Drum Group"),
              "Truthsgiving: A Decolonized Thanksgiving Show with Bluedog, Jada Brown, ... / 5 pm", T(17, 0),
              convention="acts come from the 'with' line, as on the other listings"),
            S(D(2026, 11, 28), ("The Brothers Allmanac", "Shoeless Revolution", "Shane Cox & the Funky Spuds"),
              "GETDOWN & GIVE - The Brothers Allmanac • Shoeless Revolution • Shane Cox & the Funky Spuds / 7 pm", T(19, 0),
              convention="'GETDOWN & GIVE' is the night's name"),
            S(D(2026, 12, 3), ("Benjamin Cartel & Friends",), "Hanukkah Rocks Feat. Benjamin Cartel & Friends / 6:30 pm", T(18, 30),
              alternatives=(("Benjamin Cartel",),)),
            S(D(2026, 12, 4), ("Debbie Briggs",), "Debbie Briggs - Very Vintage Holiday Swing Dance / 7 pm", T(19, 0)),
            S(D(2026, 12, 4), ("The Silverteens", "Mary Strand & The Garage", "The Hell And The Quiet"),
              "RAWK The Halls! with The Silverteens, Mary Strand & The Garage, and The Hell And The Quiet / 7 pm", T(19, 0)),
            S(D(2026, 12, 9), ("David Cook",), "David Cook / Theater / 7 pm", T(19, 0)),
            S(D(2026, 12, 10), ("The Steepwater Band", "Mark Joseph", "Nicholas David"), "The Steepwater Band with Mark Joseph, Nicholas David / 7:30 pm",
              T(19, 30), convention="the 'with' line names the supporting acts"),
            S(D(2026, 12, 11), ("Trailer Trash",), "Trailer Trash's Trashy Little X-Mas (Friday) / SAT 12 / 7 pm", T(19, 0),
              convention="the title says (Friday) but the page dates it Saturday Dec 12; labelled by the page's date"),
            S(D(2026, 12, 12), ("Trailer Trash",), "Trailer Trash's Trashy Little X-Mas (Saturday) / SUN 13 / 7 pm", T(19, 0),
              convention="the title says (Saturday) but the page dates it Sunday Dec 13; labelled by the page's date"),
            S(D(2026, 12, 17), ("Cornbread & Friends",), "Cornbread & Friends - Holiday Blues Show / 6:30 pm", T(18, 30)),
            S(D(2026, 12, 18), ("Hipshaker MPLS",), "Hipshaker MPLS | Heavy Funk & Rare Soul Dance Party / 8 pm", T(20, 0),
              convention="a dance-party collective; Ari to decide whether it is an act or a night's name"),
            S(D(2026, 12, 19), ("The Belfast Cowboys",), "The Belfast Cowboys \"Santa Watch at The Hook\" / 7 pm", T(19, 0)),
            S(D(2026, 12, 27), ("Mark Joseph & The American Soul", "Dean Magraw", "Ryan David Young", "The Tillerman Choir"),
              "Mark Joseph & The American Soul - Annual 'Tea For The Tillerman' Concert with Dean Magraw, Ryan David Young, The Tillerman Choir / 6 pm", T(18, 0)),
            S(D(2027, 1, 23), ("Ryan Picone Quartet",), "Ryan Picone Quartet Album Release / JAN 24 / 6 pm", T(18, 0),
              convention="the page rolls into 2027 here; the year rule must give 2027, not 2026"),
        ),
        non_shows=(
            NonShow("ABOLISH ICE: A Benefit Concert for the MN15!", D(2026, 11, 7), None, "benefit concert, no performer named"),
            NonShow("Space Between Monthly Music Industry MEETUP", D(2026, 11, 10), None, "industry meetup"),
            NonShow("IRA FORD Comedy Special 'Live Recording'", D(2026, 11, 12), None, "comedy"),
            NonShow("Light 'em Up The Bong Show", D(2026, 11, 15), None, "variety night, no performer named"),
            NonShow("Music For Everyone - Give To The Max Celebration", D(2026, 11, 19), None, "fundraiser, no performer named"),
            NonShow("Dirty P’s Thirsty 3rd Thursdays Club", D(2026, 11, 19), None, "club night, no performer named"),
            NonShow("Space Between JAM", D(2026, 11, 24), None, "open jam"),
            NonShow("Private Event", D(2026, 11, 28), None, "private event"),
            NonShow("Record Sale", D(2026, 12, 5), None, "record sale, not a show"),
            NonShow("Space Between Monthly Music Industry MEETUP", D(2026, 12, 9), None, "industry meetup"),
            NonShow("Dirty P’s Thirsty 3rd Thursdays Club", D(2026, 12, 17), None, "club night, no performer named"),
            NonShow("Space Between JAM", D(2026, 12, 23), None, "open jam"),
        ),
    ),
    # -------------------------------------------------------------------------------------
    # Turf Club — gated. The labelling fill-in (A2.1-D11): rows by Ari and Claude, November 4.
    # -------------------------------------------------------------------------------------
    "turf_club-2026-11-04.html": PageLabel(
      venue="turf_club", gated=True, captured_on=NOVEMBER_CAPTURE,
      held_out=False,
      note="First Avenue's site, same layout as 7th St Entry: no times or prices in the listing. Each event appears twice "
          "in the markup (two blocks). Covers November 2026 only. Nov 28's last two acts are in the Clown Lounge.",
      shows=(
        S(D(2026, 11, 3), ("BLITZKID", "They Live"), "BLITZKID | Modern Hel Tour 2026 | with | They Live",
          convention="tour name is not an act"),
        S(D(2026, 11, 6), ("Levi Bloom",), "Levi Bloom"),
        S(D(2026, 11, 7), ("Michael Grey",), "Last Nite ⏤ An Indie Sleaze Dance Party | ★ Local Show ★ | with | Michael Grey",
          convention="'Last Nite' is the night's name; the named performer is the act. Ari to confirm"),
        S(D(2026, 11, 11), ("Fruition", "Gardener"), "Fruition | Something More: The Final Tour | with | Gardener",
          convention="tour name is not an act"),
        S(D(2026, 11, 12), ("Tired Eyes",), "Tired Eyes — Neil Young and Crazy Horse Tribute Band | ★ Local Show ★",
          alternatives=(("Tired Eyes — Neil Young and Crazy Horse Tribute Band",),),
          convention="the band is 'Tired Eyes'; the rest describes the tribute"),
        S(D(2026, 11, 13), ("The Suburbs", "The Rodents"), "The Suburbs | ★ Local Show ★ | with | The Rodents"),
        S(D(2026, 11, 14), ("The Suburbs", "The Rodents"), "The Suburbs | ★ Local Show ★ | with | The Rodents"),
        S(D(2026, 11, 17), ("Nicole Atkins", "John Gallagher Jr.", "Emily Bjorke"), "Nicole Atkins | with | John Gallagher Jr. | and | Emily Bjorke"),
        S(D(2026, 11, 18), ("GHOSTWOMAN", "Croaker"), "GHOSTWOMAN | with | Croaker"),
        S(D(2026, 11, 19), ("Jennifer Eckes", "Annie Enneking", "Matthew French", "Ted Hajnasiewicz", "Zachary Scot Johnson", "Leslie Rich",
          "Colleen Somerville", "Lydia Sophia", "The Twins of Franklin", "Katy Vernon", "Nicole Wilder & Emmy Woods"),
          "Zachary Scot Johnson presents A Twin Cities All-Star ‘90s Tribute featuring Jennifer Eckes • Annie Enneking • ...",
          alternatives=(("Jennifer Eckes", "Annie Enneking", "Matthew French", "Ted Hajnasiewicz", "Zachary Scot Johnson", "Leslie Rich",
          "Colleen Somerville", "Lydia Sophia", "The Twins of Franklin", "Katy Vernon", "Nicole Wilder", "Emmy Woods"),),
          convention="the title is the night's name; each bullet is a performer; the last bullet is two names joined by '&', so the split reading is also accepted"),
        S(D(2026, 11, 20), ("Them Coulee Boys", "Good Morning Bedlam"), "Them Coulee Boys | with | Good Morning Bedlam"),
        S(D(2026, 11, 21), ("Erik Koskinen Band", "Nieves del Norte"), "Erik Koskinen Band | ★ Local Show ★ | with | Nieves del Norte"),
        S(D(2026, 11, 22), ("The Mainliners", "The Nu-Viles"), "The Mainliners | with | The Nu-Viles"),
        S(D(2026, 11, 23), ("Devil Master", "BAAZLVAAT", "Jail", "Glorious Descent"), "Devil Master | with | BAAZLVAAT, Jail | and | Glorious Descent"),
        S(D(2026, 11, 25), ("Tropical Depression", "Thomas Sticha", "Cowboy Thoughts", "Molly Maher"),
          "Cole Diamond’s Twangsgiving ft. Tropical Depression ( Alan Jackson Tribute ) | ★ Local Show ★ | with | Thomas Sticha, Cowboy Thoughts | and | Molly Maher",
          alternatives=(("Cole Diamond", "Tropical Depression", "Thomas Sticha", "Cowboy Thoughts", "Molly Maher"),),
          convention="'Cole Diamond’s Twangsgiving' is the night's name; parenthetical dropped; this is a music event, assumes the headliner Cole Diamond is a performer and not just a host"),
        S(D(2026, 11, 27), ("World’s Forgotten Boys", "GOO GOO MUCKS", "Cretin Avenue Hop"),
          "World’s Forgotten Boys (Stooges Tribute ft. members of Impaler, Dumpster Juice, Extermination Day) | ★ Local Show ★ | with | GOO GOO MUCKS | and | Cretin Avenue Hop (Ramones Tribute)",
          convention="parentheticals dropped; the 'members of' bands are not billed acts"),
        S(D(2026, 11, 28), ("The Melismatics", "Al Church", "Alex Fuller", "Annie Thoma", "Arzu Gokcen", "Ashley Ackerson", "Brian Vanderwerf",
          "Brynn Arens", "Cindy Lawson", "Claire Luger", "Curtiss A", "Erik Paulson", "Faith Boblett", "Gini Dodds", "Hilary James",
          "Laura Larson", "Meghan Kriedler", "Nikii Post", "Scott Macdonald", "Sophie Hiroko", "Tommy Ratz", "The Penny Peaches", "Embahn"),
          "A Tribute to the Replacements ft. The Melismatics with special guest vocalists Al Church • Alex Fuller (Pullstring) • ... + The Penny Peaches • Embahn performing in the Clown Lounge",
          convention="the title is the night's name; each vocalist is an act; their band names in parentheses are dropped; the last two perform in the Clown Lounge"),
      ),
      non_shows=(),
    ),
}


def gated_fixtures() -> list[str]:
    """Fixture file names in the gated set (A2.1-D2). Held-out pages (C5-D3) are never in it."""
    return [name for name, page in PAGE_LABELS.items() if page.gated and not page.held_out]


def informational_fixtures() -> list[str]:
    """Fixture file names reported but not gated (A2.1-D2). Held-out pages (C5-D3) are never in it."""
    return [name for name, page in PAGE_LABELS.items() if not page.gated and not page.held_out]


def held_out_fixtures() -> list[str]:
    """Fixture file names set aside for C6's held-out test (C5-D3): labelled, and in no other set."""
    return [name for name, page in PAGE_LABELS.items() if page.held_out]
