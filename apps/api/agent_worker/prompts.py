"""The extraction instruction sent to the model — one copy, shared.

`extract_node` (the pipeline) and `eval/run_eval.py` (the measurement harness) both
need the same instruction text. They used to each carry their own copy, and the copies
drifted (the eval's lacked the `page_readable` paragraph), which made eval results
unrepresentative of the pipeline. Both now call `extraction_instruction()`, so a change
to the prompt is one edit and the eval always measures what the pipeline sends.

How to read this file: the instruction is assembled from named pieces (the base
paragraph, the `page_readable` paragraph) so each rule has one home. Per-field meaning
(what a "time" is, how to say "not stated") lives in the schema's field descriptions
(`schemas.py`), which `instructor` sends to the model as well; this module holds only
the cross-cutting rules about what counts as a show.
"""

# The base instruction: what the model is looking at and what to pull out of it.
# (A2's one edit to the pre-A2 text: "any ticket info" became the typed admission /
# image fields, because `ticket_info` no longer exists in the schema. Per-field detail
# — which time counts, how to say "not stated" — lives in the schema's descriptions.)
_BASE = """\
If given a calendar page html, extract every show listed.
If given an image, extract a show that the image is depicting based
on the text you can find on the image.
For each show, identify the venue, date, time, performing act(s),
whether the listing was ambiguous, admission prices (advance and
day-of), whether it is explicitly free, a poster image link, and
your confidence.
"""

# page_readable guidance: lets "this page is genuinely empty" be told apart from "this
# page is broken" — both otherwise look like `shows: []` (see VenuePageExtraction).
_PAGE_READABLE = """\
Also set page_readable: true if you could understand this page well
enough to reliably tell whether it lists any shows, even if your
answer is that it lists zero shows right now — a page that's
genuinely empty is still readable. Set page_readable: false only if
the content itself was broken, garbled, an error page, or otherwise
not something you could meaningfully interpret as a venue's show
listings — regardless of how many shows you end up returning.
"""


def _non_music_rule() -> str:
    """The exclusion rule: what is NOT a show, stated for the model."""
    # Venues list entries that aren't live music with a performing artist, and the requirements say to
    # skip them ("Karaoke night", "Party", "Open mic" without an identifiable artist; "Hosted by" is not
    # a performance: requirements-initial.md, "Agent Handling of Entries … that don't have performing
    # artists"). Stating the rule is a correctness fix AND a reliability fix: Phase 5's one documented
    # failure was a non-music entry mixed into a musical listing, exhausting the model's token budget
    # (env-setup.md Phase 5). Decided scope (Ari, Oct 9 2026): a *named* DJ is an identifiable
    # performing artist, so a DJ night with a named DJ is a show; comedy is not music and is excluded
    # like karaoke and open mic; a party or "night" naming no artist is excluded. "Hosted by" alone
    # doesn't make a non-music night a show, but since October 11, 2026 a named host of a *music* show
    # is one of its acts (Ari, A2.1-D5; A2.1-CR2-12).
    # It belongs in the prompt, not the schema: it is about what counts as a show at all (a
    # cross-cutting rule), not about one field's meaning.
    # Reworded October 11, 2026 (A2.1) to Ari's "when in doubt, include it": a missed show
    # costs the calendar more than a stray non-music listing. The earlier wording ("Only extract
    # entries that name an identifiable performing artist… Skip karaoke nights, open mics, comedy
    # nights, and parties or themed nights that name no performing artist…") read as "when in
    # doubt, skip" and dropped two real shows in the eval.
    return (
        "When in doubt, include the listing: missing a real show is worse than listing a "
        "non-music event. A listing that names any performing artist or band is a show, even "
        "if it also mentions karaoke, a party, a series name or a themed night. Skip only "
        "entries that name no performer at all, such as a karaoke night, an open mic or a "
        "comedy night with no performing artist named. A named DJ is a performing artist. "
        "A named host of a music show is one of its acts, but being \"hosted by\" someone does "
        "not make a karaoke night, open mic or comedy night a show.\n"
    )


def _one_show_rule(per_act_times: bool = True) -> str:
    """The one-show-vs-several rule: how to split a listing into shows, for the model.

    `per_act_times=False` drops the last sentence for the title-split route, whose listing
    schema has no acts to put a start time on (A2.1-CR2-9: a rule the model has
    no field to follow). That route loses per-act start times — a known limit, recorded with
    A2.1-CR2-9's resolution in the A2.1 plan and left to Ari against A2-D8.
    """
    # One listing can be one show with several artists, or several distinct shows back to back, and
    # the answer decides insert-vs-update downstream: reconcile's composite key is (venue, date, time),
    # so a model that splits or merges differently between runs reads as shows appearing and
    # disappearing. The requirements' rule (requirements-initial.md, "One Show or Several?"): listings
    # under one time / ticket link are a single multi-artist show; separately timed or separately
    # ticketed listings are distinct shows; and several start times with ONE ticket link is still one
    # multi-artist show (each act carrying its own start time).
    rule = (
        "A listing under a single time or ticket link is a single show with several "
        "artists, not several shows. Listings with separate start times or separate "
        "ticket links are distinct shows."
    )
    if per_act_times:
        rule += (
            " If a listing shows several start times but only one ticket link, it is still a "
            "single show: put each artist's own start time on that artist."
        )
    return rule + "\n"


def _cancelled_rule() -> str:
    """A2.1-D12 of the A2.1 plan (decided by Ari, October 10, 2026): cancelled and postponed
    listings are still extracted, with their status.

    They aren't shows to display, but the show was most likely extracted on an earlier scan
    before it was cancelled, so reconcile has to find it and update the stored record — which
    needs the listing's date, time and acts. Sent only with the schema variant that has a
    `status` field (`ExtractionConfig.status_field`, rung `a21-cancelled`).
    """
    return (
        "A listing marked cancelled or postponed is still extracted, with its date, time "
        "and acts as listed, and its status set to cancelled or postponed.\n"
    )


def _act_conventions() -> str:
    """A2.1-D5's conventions for which performing acts a listing names — one text for both routes.

    The labels the eval scores against apply these conventions (A2.1-D5, approved by
    Ari October 10). Both routes must be told them, or the labels and the model disagree by
    construction (A2.1-PR2-2): the JSON-LD route's act splitter includes this
    text in its instruction (`act_split.py`), and the full-page model route includes it when
    `ExtractionConfig.act_conventions` is on (rung `a21-act-conventions`). The display of a
    listing's artist text is a separate, deferred question (requirements-initial.md, Show:
    "artists: display text and associations").
    """
    return (
        # Every example below is INVENTED (A2.1-CR2-2): the first version quoted
        # the eval's own labelled titles with their answers, which made the score partly
        # in-sample. A test (test_no_prompt_quotes_a_labelled_answer) keeps it that way.
        "How to name the performing acts in a listing:\n"
        "- Split a list of acts at 'w.', 'w/', 'with', 'featuring', 'ft.', '/', ',', '+', "
        "'•' and a final '&' or 'and' ('A, B & C' is three acts).\n"
        "- Keep an '&' that is part of one act's name: 'Jenny Lake & Friends' and "
        "'Ray Ortiz & the Night Shift' are one act each.\n"
        "- A series, tour or night's name, or an album's title, is not an act; name only the "
        "performers it lists ('Ana Reyes The Long Way Home Tour with The Halvorsens' is Ana "
        "Reyes and The Halvorsens; 'GROOVE CLUB W/ MILO PRATT' is MILO PRATT). Remove such a "
        "name before splitting, so markers inside it don't split anything.\n"
        "- In 'X Album Release Show' (or 'X Album Release'), X is the artist releasing the "
        "album and is an act ('The Velvet Pines Album Release Show w/ Harbor Lights' is The "
        "Velvet Pines and Harbor Lights); a quoted album title is not an act.\n"
        "- 'X Presents:' names a promoter, not an act ('Northside Presents: The Gravel Kings' "
        "is The Gravel Kings).\n"
        "- A named DJ is an act; keep 'DJ' as part of the name ('DJ Nightjar').\n"
        "- Drop anything in parentheses after a name ('Dana Fields (of The Moths)' is Dana "
        "Fields; 'Leo Park (solo)' is Leo Park).\n"
        "- Tags such as '✦ All Ages ✦' and credits such as 'visuals by' or 'sound by' are not "
        "acts. A named host of a music show or series is an act ('Sam & Lou's Folk Thursdays: "
        "Ft. Ivy Moreno' is Sam & Lou and Ivy Moreno).\n"
        "- Copy each act's name as written in the listing; never add an act the listing "
        "doesn't name.\n"
    )


def _date_heading_rule() -> str:
    """Page layout, for the full-page model route only: a date heading owns the lines under it.

    Added October 11, 2026 after `a21-conventions-newlines` (a2.1-extraction-reliability.md):
    Terminal Bar lists a date line followed by one line per act ("Saturday October 17th" /
    "Customers Band" / "Lone Sum / Nancy Gross"). With line breaks kept, the model took only the
    first line as the show's act and turned later lines into extra shows. The JSON-LD act splitter
    never sees page layout, so this is not part of `_act_conventions()`.
    """
    return (
        "When the page lists a date followed by several lines, every line under that date, up "
        "to the next date, belongs to that one show: each such line names one or more of its "
        "acts. Do not make a separate show from a line that has no date of its own.\n"
    )


def _title_rule() -> str:
    """The title-split route's one instruction about acts: copy, don't split (A2-S6)."""
    return (
        "For each listing, copy its performer text into title exactly as the page writes it, "
        "including every line of it under its date. Do not split it into acts, shorten it or "
        "reword it; another step does that.\n"
    )


def extraction_instruction(
    include_new_rules: bool = True, *, cancelled_rule: bool = False, act_conventions: bool = False,
    date_heading: bool | None = None, title_split: bool = False,
) -> str:
    """Assemble the instruction text. The page content is appended by the caller.

    `include_new_rules` exists so the eval can run a middle configuration (new schema,
    old rules) and attribute a change in results to the schema or to the rules, rather
    than to both at once (a2-extraction-schema.md, Step 5). The keyword switches are A2.1's
    additions, each switched on by its own experiment rung (a2.1-extraction-reliability.md,
    "Experiment protocol"): `cancelled_rule`, `act_conventions`, `date_heading` (follows
    `act_conventions` unless given) and `title_split` (adds the copy-the-title rule and drops
    the per-act start-time sentence). All default off, which is the instruction as A2 left it;
    the adopted combination is `extraction.PIPELINE_CONFIG`. It is a function and not a module-level constant so the rule
    functions above only run when a prompt is actually built — an import never raises.
    """
    parts = [_BASE]
    if include_new_rules:
        parts += [_non_music_rule(), _one_show_rule(per_act_times=not title_split)]
    if cancelled_rule:
        parts.append(_cancelled_rule())
    if act_conventions:
        parts.append(_act_conventions())
    # The date-heading rule goes with the conventions unless asked for separately (the title-split
    # route wants the layout rule without the splitting conventions).
    if act_conventions if date_heading is None else date_heading:
        parts.append(_date_heading_rule())
    if title_split:
        parts.append(_title_rule())
    parts.append(_PAGE_READABLE)
    return "\n".join(parts) + "\n"
