# A2 — the extraction schema, against the real requirements

**Status:** Done — signed off by Ari October 12, 2026, together with A2.1. Everything A2 set out to build was built, verified and closed on October 10, 2026: all Decisions for Ari resolved, `make check` green, `local_test` run, `TODO(Ari)` scaffolding tidied (Implementation log round 5). The extraction quality bar Ari judged unacceptable on October 10 (Eval results › Addendum) was taken up by A2.1 (`a2.1-extraction-reliability.md`). It reached 56 of 60 on the gated venues, and the rest is milestone H1 of `docs/dev/alpha-deployment-plan.md`. Approval was recorded when `/build-milestone` was invoked on October 9, 2026.
**Date:** October 8, 2026
**Author model:** Claude Sonnet 5.5 (plan, implementation rounds 1–4); Claude Opus 5.5 (Implementation log round 5, closing A2, October 10, 2026)
**Reviewer model:** Claude Opus 5.5 (plan review round 1, October 8, 2026); Claude Opus 5.5 (code review round 1, October 9, 2026)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A2 (gaps v0.1-G7, v0.1-G8, v0.1-G9), `docs/arch/requirements-initial.md`
("Agent Extraction: Fields", "One Show or Several?", "Agent Handling of Entries … that don't have
performing artists"), `docs/arch/data-model-initial.md` §2 (`show`, `show_artist`),
`docs/dev/env-setup.md` Phase 5 (the model decision and its failure mode)

## Context

The extraction schema (`agent_worker/schemas.py`) is what the model is asked to fill in, and it was
written in Phase 5 from a one-line field list in `arch-initial.md` §7. It has drifted from what
`requirements-initial.md` and the database now say. A2 closes that gap in four ways:

| Gap | What is wrong today | A2 change |
|---|---|---|
| v0.1-G7 | One untyped `ticket_info` string; no poster image; `acts` is a bare `list[str]`, so no per-artist start time or order | `admission_advance` / `admission_day` / `free_admission`, `image_url`, and `acts` becomes a list of structured `ActExtraction` objects |
| v0.1-G8 | `time` is required, so the model's only way to say "the page doesn't state one" is to invent one | `time` optional, and its `description` says so (the description is sent to the model) |
| v0.1-G9 | The prompt never states the "ignore karaoke / open mic / party with no artist" rule | State it. This is the same shape as Phase 5's documented failure (a non-music entry mixed into a musical listing), so it is a reliability fix as well as a correctness fix |
| — | The prompt never states the one-show-vs-several rule | State it |

Then measure: **a richer schema is more for the model to get right, so whether A2 made extraction
better or worse is an experiment, not an assumption** (build plan A2, last item).

### Decisions already made with the user

- **`image_url`: add the field, guard against invention.** Verified this session: `html_clean`
  (`agent_worker/nodes.py`) keeps only visible text, so `<img src>` URLs never reach the model
  (a test input with an `<img src="…poster.jpg">` cleaned to `'Show 8pm'`), even though the
  fixtures contain 11–29 `<img>` tags each. So on text pages `image_url` will be null in practice
  until cleaning preserves image links — a field that is mostly empty, which `AGENTS.md` warns
  against, accepted here because the schema should be stable before A6 writes `show.image_url`.
  The guard is a prompt/description rule ("copy a URL only if it appears verbatim in the page
  text, else null") plus an eval check that any returned URL really is in the page. Preserving
  image links in cleaning becomes a **new build-plan item (v0.1-G25)**, not A2 scope.
- **`end_time`: add it, optional.** `requirements-initial.md` lists "End Time: leave blank if
  unclear" and `show.end_time` exists, but v0.1-G7's inventory and A2's items missed it. The eval
  measures whether it tempts the model to invent end times.

### What A2 deliberately does not do

- No validation logic (completeness / plausibility / consistency) — that is A3. The schema carries
  only the cheap constraints the model can be retried on (`ge=0` on prices, `ge=1` on order).
- No rename of `time` → `start_time` to match `show.start_time`. Not requested; **A5's reconcile
  maps `time` → `show.start_time`** and should say so.
- No change to fetch or `html_clean` (v0.1-G25 above), and no change to `extract_node`'s model call,
  `max_tokens`, `num_ctx`, or its missing error handling (A3, v0.1-G2).
- No hand-labelled ground truth (A8). The A2 measurement is directional, not scored.

## Design

### Schema (`agent_worker/schemas.py`)

```python
class ActExtraction(BaseModel):                 # new
    name: str
    start_time: ModelTime = None                 # this act's own set time; null if not stated
    sequence_number: int | None = Field(default=None, ge=1)
                                                 # only if the page STATES a performance order;
                                                 # otherwise null. A5 derives the order from list
                                                 # position when null (requirements: "make an
                                                 # assumption … based on the order in which the
                                                 # artists are listed") — code can compute that
                                                 # exactly; the model can only get it wrong

class ShowExtraction(BaseModel):
    venue: str                                   # unchanged
    date: datetime.date                          # unchanged (the one field the spec requires)
    time: ModelTime = None                       # CHANGED: optional  ← TODO(Ari) #1
    end_time: ModelTime = None                   # NEW
    acts: list[ActExtraction]                    # CHANGED: was list[str]  ← TODO(Ari) #2
    is_ambiguous: bool                           # unchanged
    admission_advance: float | None = Field(default=None, ge=0)   # NEW (replaces ticket_info)
    admission_day: float | None = Field(default=None, ge=0)       # NEW
    free_admission: bool | None = None           # NEW — true only if explicitly stated, else null
    image_url: str | None = None                 # NEW — poster link, verbatim-from-page or null
    confidence: float = Field(ge=0, le=1)        # unchanged
```

Rules that shape the field descriptions (all from `requirements-initial.md` "Agent Extraction:
Fields"):

- A single price shown → `admission_day`, `admission_advance` null.
- `free_admission` is `true` only when the listing explicitly says free; otherwise **null, not
  false** ("it's ok for neither prices nor free admission to be empty"; the DB CHECK also treats
  absence as not-stated).
- Poster image, never an artist photo.
- **Every optional field's description ends by telling the model how to say "not stated"**, in one
  fixed phrase: "otherwise null". The description text is part of what `instructor` puts in the
  request — it is an instruction, not a comment. A test enforces the exact phrase (a looser check
  for the word `null` would also pass on "nullable" or "not null").
- **Every time field says "24-hour HH:MM" — and the code accepts the sloppy formats a model
  actually produces anyway.** Pydantic's `datetime.time` parsing is strict (verified October 9:
  `"7pm"`, `"7:30 PM"`, `"7:30"`, `"8:00pm"` and `"24:00"` are all rejected as `time_parsing`),
  while an integer like `68400` and `"19:30:00Z"` are *accepted* as timezone-**aware** times that
  won't compare equal to the database's naive `time`. A2 triples the time fields per show, and one
  rejected time fails the whole page and triggers a full re-ask. So the description *asks* for
  `HH:MM`, and a **normalizer converts what comes back** before Pydantic validates it — an
  instruction the model may ignore is not a format guarantee (Ari, October 9). Specified below.
- **`time` means when the music starts, not doors.** Listings like "Doors 7 / Show 8" are common;
  an undecided choice flips between runs and reads as a time change (remove + insert) to
  reconcile.

Where each rule lives: **per-field semantics go in that field's `description`; cross-cutting rules
(what counts as a show, one vs. several) go in the prompt.** Putting a rule in both invites them to
drift.

Prices are `float | None` with `ge=0` **in the extraction schema**, not `Decimal`. Nothing at this
layer needs exact money, and `Decimal | None` makes Pydantic emit
`anyOf: [{number, minimum: 0}, {string, pattern: <regex>}, {null}]` — twice per show, in a prompt a
4B-class model has to follow, and a confound for the eval (worse admission fill rates could come
from the schema's shape rather than the model). The exact type matters at the database write:
**A6 converts with `Decimal(str(value))` and quantizes to `Numeric(10, 2)`** (the API's
string-on-the-wire rule, `api-contract.md`, is about the read API and is unaffected). Recorded in
the build plan's A6 item.

Consequences to keep visible, not fix:

- **`acts` may be an empty list in the schema, deliberately.** The requirements say a show has "one
  or more" artists, and an artist-less entry isn't a show. That check belongs to **A3's completeness
  validation** (added to its build-plan item), not to `min_length=1` here: a schema rule would turn
  one leaked "Karaoke" entry into a full-page `instructor` re-ask.
- **A null show `time` is new for reconcile.** A5's composite key is (venue, date, time) and in SQL
  `NULL = NULL` is not true, so a naive match never finds an untimed show: every run would insert a
  duplicate and soft-delete the previous one, and two untimed shows on one date would collide. The
  rule is recorded as an open decision in the build plan's A5 item, with this recommendation: *an
  untimed show matches a stored show on (venue, date) when exactly one candidate exists on either
  side, otherwise insert and flag for review; a time that appears later (null → 20:00) counts as an
  update, not remove + insert.* Ari confirms it in A5's plan; A2 only makes the case reachable.
- `acts` changes shape (`list[str]` → nested objects), so the JSON schema sent to the model gains a
  `$defs` section. Verified by grep that **nothing reads `.acts` today** (only `schemas.py`
  declares it) — which is exactly why changing it now is cheap and changing it after A5 would not
  be.
- `is_ambiguous` keeps its current meaning ("listing order or timing unclear"). Because most
  multi-act listings don't state an order, the assume-listed-order rule may make it true very
  often. Not redefined here; the eval records how often it fires.

### Time normalizer (`agent_worker/normalize.py`, new; applied in `schemas.py`)

`ModelTime = Annotated[datetime.time | None, BeforeValidator(normalize_time)]`, used by `time`,
`end_time` and `ActExtraction.start_time`. A `BeforeValidator` runs on the raw value *before*
Pydantic's own parsing, so the model's output is converted rather than rejected.

**Why `Annotated[datetime.time | None, …]` and not `Annotated[datetime.time, …] | None`:** the
validator must see the string `"n/a"` before the `None` branch of the union decides. Verified:
the first form turns `"n/a"` into `None`; the second rejects it. **The JSON schema sent to the model
is unchanged** by the validator (field schema compared with a plain `time | None`: identical), so the
model is still told "24-hour HH:MM" and nothing about our leniency.

**Rule: normalize only what is unambiguous; never guess.** *(Changed October 10, 2026 by Ari — Decisions
for Ari #2: a 12-hour time with no AM/PM is now read as **PM**, not rejected. The two rows below marked
"changed" record the new behaviour; the rest of the table stands.)*

| Input | Result | Why |
|---|---|---|
| `"19:30"`, `"19:30:00"`, `"07:30"` | the time | already valid; zero-padded `07:30` is clearly 24-hour |
| `"7pm"`, `"7 PM"`, `"7:30pm"`, `"7:30 PM"`, `"7:30 p.m."`, `"8:00pm"`, surrounding whitespace | 19:00 / 19:30 / 20:00 | 12-hour with an explicit meridiem is unambiguous |
| `"12am"` → 00:00, `"12pm"` → 12:00, `"12:15am"` → 00:15 | | the usual 12-hour edge cases |
| `"19:30:00Z"`, `"19:30-05:00"`, an already-aware `time` | 19:30, **tzinfo dropped** (wall-clock kept, not converted) | the database column is a naive `time` and the venue's local clock is what a listing means; a zone suffix from a model is noise, not information |
| `""`, `"null"`, `"none"`, `"n/a"`, `"na"`, `"tbd"`, `"tba"`, `"unknown"` (any case) | `None` | a model told "otherwise null" often writes the *word*; that means "not stated" |
| **`"7:30"`, `"7"`, `"10"`** (no meridiem, not a two-digit `HH:MM`) | **changed: PM** — 19:30 / 19:00 / 22:00 (was: rejected) | Ari, October 10: live music is overwhelmingly afternoon/evening, and a listing that really is in the morning says AM. The original reasoning (a guess is silently wrong for a brunch show) was weighed and accepted as the rarer error |
| `"10:30"`, `"11:00"` (two-digit, no meridiem) | **changed: kept as 24-hour** (10:30 / 11:00) | it is exactly the `HH:MM` the schema asks for, so the normalizer can't tell a converted value from a copied one. The PM rule for this case lives in every time field's description ("if the page gives no AM/PM, assume PM"), since the model does the 12→24 conversion itself |
| `"24:00"`, `"25:00"`, `"13pm"`, `"0pm"`, `"0:30"`, `"13"`, free text | rejected | not a time, or not a 12-hour reading |
| integers, floats, booleans | rejected | Pydantic would accept `68400` as `19:00+00:00` (aware); a number is never a clock reading here |

Rejected values raise `ValueError`, which Pydantic reports as a validation error, so `instructor`
re-asks exactly as it does today — normalization only turns *recoverable* formats into successes.
Success/failure is still visible to the eval (parse failures by field), but a normalized value is
not itself counted: **`baseline` has no normalizer** (the old `time` field lacked one) while
`schema-only` and `after` do, so `schema-only` is slightly flattered on time failures. The
by-field classification shows how much; it is noted in the verdict, not corrected for.

Marked [written], not a `TODO(Ari)`: it is mechanical string handling. It is a good gap candidate
if Ari wants a fifth — see "Decisions for Ari" in the handoff.

### Prompt (`agent_worker/prompts.py`, new)

`extract_node` and `eval/run_eval.py` each carry their own copy of the instruction text, and the
copies have **already drifted** — the eval's lacks the `page_readable` paragraph the pipeline's has.
A2's measurement is meaningless if the harness isn't running the pipeline's prompt, so the
instruction moves to one module that both import:

```python
def extraction_instruction(include_new_rules: bool = True) -> str:
                                       # assembles: base + (non-music rule + one-show rule) + page_readable
def _non_music_rule() -> str:          # TODO(Ari) #3
def _one_show_rule() -> str:           # TODO(Ari) #4
```

A function, not a module-level constant, so the `NotImplementedError` placeholders only fire when
the prompt is actually built (tests, `extract_node`) and never at import time, which would break
unrelated tests. `include_new_rules=False` returns base + `page_readable` with no new rules (the base
sentence carries A2's one wording edit — Implementation log departure 8 — so it is *not* byte-identical to
the pre-A2 text the `baseline` label used) so the eval can run a middle label, **`schema-only`** — new
schema, no new rules — and
separate the effect of the schema from the effect of the rules (see Steps).

The exclusion rule's scope is **decided** (Ari, October 9): a *named DJ* is an identifiable
performing artist, so DJ nights are shows; *comedy* is not music and is excluded, like karaoke,
open mic and parties with no identifiable artist; "Hosted by" someone never counts as a
performance. (The fixtures contain DJ and comedy entries — Zhora, Terminal Bar — that the
requirements are silent about.) The base text is the current `nodes.py` text, with one edit: "any ticket info" is
stale once `ticket_info` is gone and becomes "admission prices (advance and day-of), whether it is
explicitly free, a poster image link".

## Test approach — written first, watched fail, then made green

Tests live in a new **`agent_worker/tests/`** (with `__init__.py`, like `app/tests/`). They cannot
go in `app/tests/`: `apps/api/AGENTS.md` says `app/` never imports from `agent_worker/`, and the
round-1 reviewer of A1 flagged exactly that. That requires one small pull-forward from A7 (v0.1-G14):
`pyproject.toml` `testpaths = ["app"]` becomes `["app", "agent_worker/tests"]`. It does not collect
`agent_worker/local_test.py` (the reason `testpaths` was narrow), because that file isn't under
`tests/`. A7 will widen mypy and add the rest; this is only so A2's tests run under `make check`.

None of these tests call a model, so they are fast and run in CI. Importing `agent_worker.nodes`
and `agent_worker.eval.run_eval` is safe there (re-checked in plan review: both only construct
clients, which makes no network call). The tests never read `agent_worker/eval/fixtures/`, which
`apps/api/.gitignore` ignores and so doesn't exist in CI.

**`test_extraction_schema.py`** — pure Pydantic:

| Test | Proves |
|---|---|
| `required` set in `ShowExtraction.model_json_schema()` is exactly `{venue, date, acts, is_ambiguous, confidence}` | what `instructor` tells the model is required — the strongest single guard for v0.1-G8; catches "Optional but no default" (a Pydantic v2 trap: `X \| None` with no default is **still required** — verified this session) |
| omitted `time`, `end_time`, prices, `free_admission`, `image_url`, and an act's `start_time` / `sequence_number` all validate to `None` | "not stated" is representable |
| all-`None` admission is valid and `free_admission` is `None`, not `False` | absence of a price never reads as free |
| negative price rejected; `"15.00"` and `15` both accepted (as `15.0`) | the `ge=0` constraint and tolerance for the two shapes a model emits |
| acts must be objects: `["Band A"]` rejected; `sequence_number` 0 rejected, 1 and `None` accepted | the shape change took, and a stated order is 1-based |
| `acts=[]` validates | **pins a decision:** the schema deliberately doesn't enforce "one or more artists"; A3's completeness check does |
| `ticket_info` absent from `properties` | the old field is really gone (Pydantic ignores unknown input fields by default, so a stale field would otherwise go unnoticed) |
| every optional field's `description` contains the exact phrase `otherwise null` (both models) | the "tell the model how to say not-stated" convention holds; stricter than looking for `null`, which "nullable" would satisfy |
| every time-typed field's `description` contains `HH:MM`, and `time`'s mentions doors | the format instruction and the doors-vs-music-start rule can't be silently dropped |
| **normalizer, accepted** (parametrized, run through `ShowExtraction(date=…, time=value, …)`): `"19:30"`, `"19:30:00"`, `"07:30"` → as given; `"7pm"`, `"7 PM"`, `"7:30pm"`, `"7:30 PM"`, `"7:30 p.m."`, `"8:00pm"`, `" 7pm "` → 19:00 / 19:30 / 20:00; `"12am"` → 00:00, `"12pm"` → 12:00, `"12:15am"` → 00:15 | the sloppy formats a model actually emits are converted, not rejected — the behaviour this table section exists to pin |
| **normalizer, null-ish → `None`**: `""`, `"null"`, `"None"`, `"N/A"`, `"na"`, `"TBD"`, `"tba"`, `"Unknown"` | the model writing the *word* for "not stated" means not stated |
| **normalizer, tzinfo dropped**: `"19:30:00Z"`, `"19:30-05:00"` → naive `19:30` (`tzinfo is None`) | a timezone-aware time would later fail to compare with the database's naive times (A5) |
| **normalizer, rejected** (`ValidationError`, `type == "value_error"`) — *October 10: `"7:30"` and `"7"` moved to accepted (→ PM, Decisions for Ari #2); `"0:30"` and `"13"` added here*: `"7:30"`, `"7"`, `"24:00"`, `"25:00"`, `"13pm"`, `"0pm"`, `"after dark"`, `68400`, `19.5`, `True` | ambiguity and non-times are refused, never guessed; integers specifically (Pydantic alone would accept `68400` as an aware time) |
| the normalizer applies to **all three** time fields: the accepted/rejected cases are run against `ShowExtraction.time`, `ShowExtraction.end_time` and `ActExtraction.start_time` | a lenient field next to a strict one is the bug this would otherwise hide |
| `ShowExtraction.model_json_schema()` properties for `time`, `end_time` and (via `$defs`) `start_time` are `anyOf [{format: time, type: string}, {type: null}]` | leniency is invisible to the model: the schema it receives is unchanged |
| a realistic multi-act payload (advance + day price, per-act times) round-trips through `model_validate_json`; so does a minimal one (date + one act, everything else null) | the schema accepts what a model would plausibly emit |
| `VenuePageExtraction` still requires `page_readable` | nothing regressed |

**`test_prompts.py`** — `extraction_instruction()` contains: the `page_readable` paragraph, the
exclusion rule's key terms (`karaoke`, `open mic`, `hosted by`), the one-show rule's key terms
(single show, one ticket link / time), and no longer says "ticket info"; `include_new_rules=False`
omits both rules. **Behavioural, not an import check:** a test monkeypatches `nodes.instructor_client`
with a fake that captures `messages`, calls `extract_node(VenueGraphState(venue_id=1,
calendar_url="x.html", page_content="…"))`, and asserts the text `extraction_instruction()` returns
is what was sent; the same for `run_eval.extract` against a temporary text file. (Asserting only
that both modules import the function could be satisfied by an unused import while a module still
sends its own string — the drift this file exists to remove.) **Honest limit:** string-contains tests pin that the
text is present, not that it works — whether the model obeys it is what the eval measures. They
guard against the rule being deleted or the two copies drifting apart again.

**Red at handoff.** Per `AGENTS.md`, `TODO(Ari)` placeholders keep tests red. Expected failing at
handoff: the `required`-set test, the optional-`time` test, the acts-shape test, the description
tests and the `ticket_info` test (schema TODOs #1–#2 left at the old declarations), and the prompt
tests (TODOs #3–#4 raise `NotImplementedError`). `make check` is therefore red until the TODOs are
filled — intended.

## The `[fill-in]` steps and their `TODO(Ari)` blocks

Applying `AGENTS.md`'s rule: gaps go where the concept lives, not where the typing is.

| # | Where | Lesson (one line) | Check |
|---|---|---|---|
| 1 | `schemas.py` — `ShowExtraction.time` (v0.1-G8) | `datetime.time \| None` **without** `= None` is still required in Pydantic v2; and the `description` is an instruction to the model — 24-hour `HH:MM`, the time the music starts (not doors), "otherwise null" — not documentation. The type is `ModelTime` (the normalizer alias, written by me), so the line to type is `time: ModelTime = Field(default=None, description=…)` | `test_required_set…`, `test_omitted_optionals…`, the normalizer cases |
| 2 | `schemas.py` — `ShowExtraction.acts` (v0.1-G7) | Changing `list[str]` to `list[ActExtraction]` is a **shape** change: the JSON schema `instructor` sends becomes nested, and every reader of `.acts` must change (none exist yet, which is why it's cheap now) | `test_acts_must_be_objects` |
| 3 | `prompts.py` — `_non_music_rule()` (v0.1-G9) | The Phase 5 failure mode was a non-music entry mixed into a musical listing; stating the exclusion rule is both the correctness fix and the reliability fix. Decided scope: karaoke, open mic, comedy and parties with no identifiable artist are not shows; a *named* DJ is an artist; "Hosted by" is not a performer | `test_prompts.py`, then the eval |
| 4 | `prompts.py` — `_one_show_rule()` | "Listings under one time / ticket link are a single multi-artist Show; separately timed or ticketed listings are distinct Shows; several start times with one ticket link is still one Show" — this is what decides insert-vs-update downstream (A5's composite key is venue + date + time) | `test_prompts.py`, then the eval |

Each block will carry Lesson / Code (near-exact lines to type or paste) / Check, per `AGENTS.md`.

**Plan-review finding 9 (and Ari's decision).** The reviewer pointed out that TODOs #1 and #2 are
each a one-token edit to a Pydantic field declaration, a kind of gap `AGENTS.md` lists as bad, and
that leaving the old declaration in place isn't a `NotImplementedError` placeholder. **Ari chose to
keep all four as planned.** Recorded so the code reviewer doesn't re-raise it: the schema gaps stay
because the lesson in each (Optional-needs-a-default; a shape change ripples to every reader) is
what Ari wants to type, and a `NotImplementedError` inside a Pydantic class body would break every
import, so the red tests are the placeholder.

**Re-marking proposals** (per the rule "if no line meets the bar, say so"). *Closed October 10, 2026 —
Decisions for Ari #5: moot once Ari filled the gaps; the build-plan item stays as it is.*

- Build-plan A2 item 1 is largely Pydantic field declarations — explicitly a *bad gap* by
  `AGENTS.md`. Only the `acts` shape change carries a lesson (TODO #2). The remaining new fields
  (`end_time`, admission, `image_url`, the `ActExtraction` class) will be written by me as
  [written] in practice. Proposal: split the item, re-marking the declarations [written].
- Items 3 and 4 are each one paragraph of prompt text. They are valid gaps (the wording *is* the
  lesson) but small; they stay [fill-in].

## Steps

Order matters: **the baseline must be captured before the schema changes.**

0. **Ground truth for "before" (written).** Create `prompts.py` with `extraction_instruction()`
   returning the *current* `nodes.py` text verbatim (no TODOs yet; the `include_new_rules` flag
   exists but both values return the same text for now); make `nodes.py` and `run_eval.py` use it.
   The only behaviour change is that the eval now runs the pipeline's prompt (it previously lacked
   `page_readable`) — the baseline is captured *after* this, so it is not contaminated by it. Also
   in this step, make both `create(...)` call sites pass **`max_retries=3` explicitly** with a
   why-comment: `instructor`'s default is 3 retries (up to **4** attempts per call), implicit today,
   and the graph's own 3-attempt cap multiplies it to as many as 12 model calls per venue. Behaviour
   is unchanged; A3 revisits the number.
1. **Eval harness (written).** Extend `eval/run_eval.py`, still a throwaway, to run each fixture
   `--runs N` times under a `--label` and write `eval/results/<label>.json` (git-ignored). Per
   (fixture, run) it records:
   - **outcome:** `ok`, or the exception class. `IncompleteOutputException` (the Phase 5 failure)
     is its own class, because it is re-raised immediately and **never** emits `parse:error`.
   - **parse failures** (retries), via one `parse:error` handler registered once per client
     (`client.on("parse:error", handler)`; hook names verified in installed `instructor` 1.15.4),
     counter reset per call. `parse:error` fires on every failed parse *including the last attempt*,
     so the derived number is defined: `attempts_used = parse_failures + (1 if outcome == "ok" else 0)`.
     Each failure is classified **by field** from the validation error's `loc` (so a `time_parsing`
     failure on `acts.0.start_time` is distinguishable from a content failure).
   - wall seconds, number of shows, `page_readable`, per-optional-field fill counts, per-show act
     count, and whether any returned `image_url` is a substring of the page text it was extracted
     from. (The cleaned text contains no URLs, so any non-null `image_url` is almost certainly
     invented; the check makes that countable.)
   - **reproducibility:** the model digest (`/api/show`), the Ollama version (`/api/version`), and
     the request options (`num_ctx`, `max_tokens`, `max_retries`), plus **`options.seed` set to the
     run index** so any single run can be repeated. Temperature stays at the pipeline default so the
     runs remain representative.
   Known noise, not fixed here: both the pipeline and the eval label every image `image/png`,
   including the `.webp` fixture (`nodes.py:151`, `run_eval.py:124`). It predates A2, affects every
   label equally, and the image path is deferred work (build plan §8); the results note it on the
   two image rows.
1b. **Eval reference (written, by hand, before the baseline).** A short per-fixture list in this
   file under "Eval reference": each non-music entry by name and date (by the decided scope —
   karaoke, open mic, comedy, artist-less parties out; named DJs in), each listing that states an
   end time, each listing with a price, and each multi-act listing. This is **not** A8's full
   hand-labelling; it is the few facts needed to make "non-music leaked" and "invented end time"
   countable, and it is written once so the baseline and the later runs are scored against the same
   thing.
2. **Baseline run — label `baseline`.** Old schema, verbatim prompt, the six fixture files (four
   venue pages, two Terminal Bar poster images) × 3 runs against `gemma4:e4b`. Ollama is up here
   (`gemma4:e4b` present). Record in this file under "Eval results". N=3 because outputs are
   nondeterministic; this is directional, not statistics.
3. **Tests first.** Write `agent_worker/tests/` and the `testpaths` change; run; confirm failures
   are for the right reasons (no `ActExtraction`, `time` still required, `ticket_info` still
   present, prompt functions missing), not import errors.
4. **Scaffold (written + fill-in).** Write `ActExtraction` and all new `ShowExtraction` fields with
   their descriptions; write `normalize.py` (`normalize_time`) and the `ModelTime` alias; write
   `prompts.py` fully except TODOs #3–#4; wire `extract_node` to call
   `extraction_instruction()`. Leave TODOs #1–#4 as described. **Stop and hand off** with the four
   `file:line` links and `uv run pytest agent_worker/tests`.
5. **After Ari fills the TODOs (only when asked to proceed):** run **two** more labels so a
   regression can be attributed, not just observed — **`schema-only`** (new schema,
   `extraction_instruction(include_new_rules=False)`) and **`after`** (new schema, new rules). Then
   fill in the results table and the verdict (better / worse / mixed, with the evidence). If
   `after` is worse than `baseline`, `schema-only` says whether the schema or the new rules did it (its base sentence differs from baseline's by A2's one wording edit, so "schema only" is the schema plus that sentence),
   so the response (below, Risks) removes the right thing. 6 files × 3 runs × 3 labels = 54 runs.
6. **Docs.** Tick A2 in the build plan; add **v0.1-G25** ("`html_clean` strips image URLs, so `image_url`
   can't be populated from text pages") as a new item under A3/fetch; note in `arch-initial.md` §7
   that its extraction field list is superseded by `requirements-initial.md`; update the
   `schemas.py` docstring that cites the old list; add anything non-obvious that bit during the work
   to `docs/dev/notes.md` (candidate: `X | None` without a default is still required). Also, from
   plan review: edit **A7's v0.1-G14 item** to say the `agent_worker/tests` path was added to `testpaths`
   in A2 (so A7 widens rather than redoes it); add to **A5** the null-`time` matching question above;
   add to **A3** a completeness check that `acts` is non-empty; add to **A6** that prices are
   floats in the extraction and become `Decimal(str(v))` quantized to `Numeric(10, 2)` at write.

## Critical files

- New: `apps/api/agent_worker/prompts.py`, `apps/api/agent_worker/normalize.py`,
  `apps/api/agent_worker/tests/{__init__,test_extraction_schema,test_prompts}.py`
- Modified: `apps/api/agent_worker/schemas.py`, `agent_worker/nodes.py` (call `extraction_instruction()`),
  `agent_worker/eval/run_eval.py`, `apps/api/pyproject.toml` (`testpaths`), `apps/api/.gitignore`
  or root (`agent_worker/eval/results/`), `docs/dev/alpha-build-plan.md`, `docs/arch/arch-initial.md` (note only)
- Reused as-is: `agent_worker/state.py` (`extraction: VenuePageExtraction | None` follows the new
  schema automatically), `validate_node` (reads only `show.confidence`, which is unchanged),
  `agent_worker/eval/fixtures/`

## Verification

1. `cd apps/api && uv run pytest agent_worker/tests` — red for the right reasons after step 3; at
   handoff only the TODO-gated tests fail; green after Ari fills TODOs #1–#4.
2. `uv run ruff check . && uv run mypy app/` clean; `make check` green once the TODOs are filled.
3. Eval: the "Eval reference" exists before the baseline; `baseline.json` exists before the schema
   is touched; `schema-only.json` and `after.json` exist after. The results table compares the
   three labels on: completion rate (and `IncompleteOutputException` count), `attempts_used`,
   parse failures by field, latency, shows found, optional-field fill rates, invented end times and
   image URLs (against the reference), non-music entries leaked into `shows` (against the
   reference), and an eyeballed correctness note per fixture.
4. `uv run python -m agent_worker.local_test` (full graph, one fixture) still produces a plausible
   record end to end with the new schema — run after the TODOs are filled.

## Risks

- **A richer schema may degrade a 4B-class local model.** That is the point of measuring. If
  `after` is clearly worse (more failures or retries), compare `schema-only`: if `schema-only` is
  already worse, simplify the schema (e.g. drop `end_time` or per-act times); if only `after` is
  worse, the new prompt rules are the cause and the schema stays. Recorded as a finding either way.
- **Time formats.** Handled in code by the normalizer rather than left to the model. Remaining
  risks: a format the normalizer doesn't recognize (still a re-ask — the by-field parse-failure
  count after the runs shows whether another format earns a rule); and the normalizer flatters
  `schema-only`/`after` against `baseline` on time failures (noted above). The normalizer
  deliberately refuses ambiguous `"7:30"`; if the runs show models emit that form often, whether to
  assume PM is a decision for Ari, not a default.
- **Local runs are slow.** 54 runs on `gemma4:e4b`; run in the background.
- **Nondeterminism** limits what N=3 can show; the verdict will say "directional".
- **Admission fields are measured on one page.** Only one fixture (Zhora: `$12`–`$34`) shows any
  price; White Squirrel, Midway and Terminal Bar show none. Fill rates and the single-price →
  `admission_day` rule rest on one page × 3 runs and must not be generalized.
- **`image_url` hallucination** is the specific thing the substring check exists to catch.
- **The image-fixture rows carry MIME-label noise** (see Step 1).

## Decisions for Ari

*Open items that need you before or during implementation. Each has a recommendation.* **All resolved
as of October 10, 2026** — #1–#5 by Ari on that date (each resolution is under its item), #6 on October 9.

1. **The time normalizer wasn't seen by the plan reviewer.** Added October 9 at your request, after
   round 1. It is specified (Design › Time normalizer) and tested, but no second model has checked
   it. **Recommendation:** approve without another round and let the code review examine it; its
   behaviour is pinned by a table of accepted/rejected inputs, and the one real judgment call
   (refusing ambiguous `"7:30"`) is isolated in the next item. Say so if you'd rather have a short
   round 2 first.
   — **RESOLVED (Ari, October 10, 2026): covered by code review.** Code review round 1 examined the
   normalizer directly (about 25 extra spellings probed against plain Pydantic) and found two real gaps,
   fractional seconds and the bare `"7p"`; both were fixed tests-first (findings #2 and #4). No separate
   plan-review round.
2. **Ambiguous `"7:30"` (no AM/PM): reject, or assume PM?** The plan rejects it (one re-ask) rather
   than guess, because a guessed PM is silently wrong for a morning or brunch show. Nightlife
   listings make PM likely, so assuming PM is defensible. **Recommendation:** reject now; revisit
   only if the eval's by-field parse failures show models emit that form often.
   — **RESOLVED (Ari, October 10, 2026): assume PM.** Ari's reasoning: live music is overwhelmingly
   afternoon/evening; all-day festivals and other morning listings state AM/PM, so a listing with no
   meridiem means PM. (For the record, the eval itself never produced the form: the 36 new-schema runs
   had zero time-parsing failures.) Implemented the same day, tests first (Implementation log round 5):
   `normalize.py` reads a non-zero-padded time with no meridiem as PM; a two-digit `HH:MM` is still
   trusted as 24-hour, so every time field's *description* now also says "if the page gives no AM/PM,
   assume PM" (the model does the 12→24 conversion itself). Recorded as a product rule in
   `requirements-initial.md` ("Agent Extraction: Fields", Start Time) and in `arch-initial.md` §7.
3. **Tzinfo is dropped, not converted, from `"19:30:00Z"`.** The database column is a naive `time`
   and a listing means the venue's local clock, so a zone suffix from a model is treated as noise.
   Alternative: reject zoned values. **Recommendation:** drop (as planned).
   — **RESOLVED (Ari, October 10, 2026): drop, as built — on the condition that there is a source of
   truth for which zone a metro's wall-clock times are in.** Checked: there is. `metro.timezone` (IANA
   name, seeded `America/Chicago`) already exists in the model, migration, seed, API
   (`MetroSummary.timezone`) and all three design docs; what was missing was its second role. Recorded
   October 10 in `data-model-initial.md` (`metro.timezone` row), `requirements-initial.md` (Metro) and
   `arch-initial.md` §7: every show date/time is the venue's local wall clock in the metro's zone.
   **Carried to A2.1:** "drop" is right for *model* output only. A structured source that states an
   offset (Zhora's JSON-LD gives `2026-08-17T23:00:00Z`, which is 18:00 in Minneapolis) must be
   **converted** into `metro.timezone`, never passed through `normalize_time`, which would keep 23:00.
4. **Should the normalizer be a fifth `TODO(Ari)` gap?** It is mechanical string handling, so the
   plan marks it [written]. It does teach something real (validate-before-parse; refuse rather
   than guess). **Recommendation:** keep it [written]; add it as a gap only if you want to type
   it.
   — **RESOLVED (Ari, October 10, 2026): moot — it stays [written]**, as built and reviewed.
5. **Re-marking build-plan A2 item 1 as [written]** (the field declarations are the "bad gap" kind
   `AGENTS.md` warns about). You kept all four TODOs, which doesn't settle this. **Recommendation:**
   re-mark the item, keep the four TODOs.
   — **RESOLVED (Ari, October 10, 2026): moot.** Ari kept and filled all four gaps and the item is ticked;
   relabelling a finished item changes nothing. The build plan is left as it is.

6. **Which Ollama context window should the A2 eval run under?** — **RESOLVED (Ari, October 9, 2026):
   option (b), via a derived model.** The pipeline's `num_ctx` override doesn't work on Ollama 0.35.0's
   `/v1` endpoint, so every call ran at 4096 and 9 of 9 runs on the three big pages failed. Confirmed the
   cause for White Squirrel (see Eval results and `notes.md`). Fix applied: `ollama create gemma4-e4b-32k`
   from `apps/api/ollama/gemma4-e4b-32k.Modelfile` (same weights as `gemma4:e4b`, default context 32768),
   `MODEL_NAME=gemma4-e4b-32k` in `apps/api/.env` and `.env.example`, and `run_eval.py` follows
   `MODEL_NAME`. A smoke run of White Squirrel with `--legacy` completed first attempt with 12 shows. **Still
   to do:** re-run the baseline under this window (`--label baseline-32k --legacy`), then `schema-only` and
   `after`. The 4096-window `baseline.json` stays as a record of the failure and is not comparable to them.

## Eval reference

*Written October 9, 2026 by reading each cleaned fixture (and viewing both posters), **before** the
baseline run, so every label is scored against the same facts. Machine-readable form:
`apps/api/agent_worker/eval/reference.py`. This is not A8's labelling — only what makes "leaked",
"invented end time" and "invented start time" countable. Scoring matches lower-case substrings
against returned act names.*

| Fixture | Real shows (≈) | Not a show (a returned act matching these is a **leak**) | States end time? | States start time? | States a price? | Multi-act listings |
|---|---|---|---|---|---|---|
| White Squirrel (html) | 12 | none | **yes, all 12** ("6:00 pm - 8:00 pm") | yes | no | 9 of 12 ("X w. Y, Z"); Nona, New Havoline Supremes, Caitlin Robertson are solo |
| Midway (html, month grid) | 11 clear music entries (+6 "Blues Jam with Moses Oakland") | Weekly Pool Tournament, MNUFC GAMEDAY, MEGASTELLAR OPEN MIC NIGHT (×2). *Borderline, reported not scored:* Blues Jam | no | yes ("7p") | no | none (Aug 6 and Aug 13 each list two separately timed entries) |
| Zhora Darling (html) | 24 | none in the listings — "Karaoke" is only a nav link, so any act containing it is a leak. ECID w/ OKnice & **DJ Adatrack** is a named DJ ⇒ a show | no | yes | **yes, one price each** ⇒ `admission_day`, advance null; one is "Join The Waiting List $34.91", one "From $21.59" | nearly all |
| Terminal Bar (html) | 8 dated | OPEN MIC (Mondays), DJ Night (Wednesdays, no named DJ), OPEN COMEDY (Thursdays) | no | **no — the page states no times** | no | Sigtones / Muffleur / Dirty 930; Man Down / Justin Payne / Larrkins; Fighting the Urge / Scarlett Tangerines |
| terminal_bar_show_1.png | 1 (Envies / Müllet / Kurt Russell's Muscles, Fri Aug 7, 8:30PM, $10) | none | no | yes | yes, $10 ⇒ `admission_day` | 1, three acts |
| terminal_bar_show_2.webp | 1 (Cowboy Thoughts / Buried Animals / Rupert Angeleyes, Aug 8, 9PM, $10) | none | no | yes | yes, $10 ⇒ `admission_day` | 1, three acts |

Derived scoring rules: an **invented end time** is any `end_time` on every fixture except White
Squirrel; an **invented start time** is any show `time` on the Terminal Bar html page (under the
baseline schema `time` is required, so this counts every show there — v0.1-G8's cost, measured); an
**invented price** is any admission/ticket field on White Squirrel, Midway or Terminal html; an
**invented image URL** is any non-null `image_url` not found verbatim in the page text (for posters
there is no page text, so any non-null `image_url` counts). Dates are not scored: Zhora and the posters omit
the year (the posters came back as 2024 in every baseline run), the other pages state "August 2026", and the
Midway grid is ambiguous about month. (Scoring the year on the Terminal Bar page is possible and not done.)

## Eval results

*Filled in as labels are run. Raw results: `apps/api/agent_worker/eval/results/<label>.json`
(git-ignored). Regenerate with `uv run python -m agent_worker.eval.run_eval --label <label> --runs 3`:
`baseline` needs `--legacy` (the frozen pre-A2 schema and prompt, `eval/legacy.py`), `schema-only` needs
`--old-rules`, `after` needs neither. Compare with `--compare baseline schema-only after`, which now prints
provenance (loaded context window, prompt and schema hashes) first. Each results file stores the
instruction and JSON schema it sent; `--rescore <label>` recomputes scores from stored extractions.*

### Label `baseline` — old schema, pre-A2 prompt (step 0), 6 fixtures × 3 runs, October 9, 2026

`gemma4:e4b` (digest `c6eb396dbd59…`), Ollama 0.35.0, `max_tokens` 16000, `max_retries` 3, temperature
at Ollama's default. Raw: `eval/results/baseline.json`. **Two conditions to read this under:**

1. **The context window was 4096, not the 32768 the code requests.** Ollama's `/v1` endpoint ignores
   `options.num_ctx`; `/api/ps` reports `context_length: 4096` while the harness's calls are in flight
   (found *after* this run; reproduced, written up in `docs/dev/notes.md`). This is what the pipeline
   really runs with today, so the baseline is a true "before" — but it is probably not the condition
   Phase 5 meant to test, and it dominates the numbers below.
2. **The runs are unseeded.** The harness first passed the seed as `options.seed`, which `/v1` also
   ignores; fixed afterwards (top-level `seed`), so later labels are individually repeatable and
   this one is not. Seeds don't change the distribution, so the comparison stays fair. The first
   smoke test showed the effect: the same seed gave different outcomes on the same fixture.

| Fixture | ok | shows found (≈ real) | parse failures | notes |
|---|---|---|---|---|
| White Squirrel | **0/3** | – (12) | 0 | 3× `IncompleteOutputException` (70–74 s) |
| Midway | **0/3** | – (11) | 0 | 3× `IncompleteOutputException` (80–84 s) |
| Zhora Darling | **0/3** | – (24) | 0 | 3× `IncompleteOutputException` (67–73 s) |
| Terminal Bar (html) | 2/3 | 7, 8 (8) | 2 (13 field errors) | the third run: 1 failed parse, then `IncompleteOutputException` |
| Terminal poster 1 | 3/3 | 1, 1, 1 (1) | 0 | time 20:30 and `$10` correct; **year 2024** every run (the poster has none) |
| Terminal poster 2 | 3/3 | 1, 1, 1 (1) | 0 | time 21:00 and `$10` correct; year 2024; **`acts: []` in 2 of 3 runs** |

| Metric | Value |
|---|---|
| Completion | **8/18** (10 × `IncompleteOutputException`) |
| Mean attempts used / mean wall time | 0.56 / 63.5 s (each failed large page runs ~70–80 s and is cut off when the 4096-token context fills — not at `max_tokens`; see `notes.md`) |
| Parse failures by field | 13 × `shows.*.time:time_type`, all on Terminal Bar html — the model returned `time: null` for a required field, was rejected, re-asked |
| **Invented start times (v0.1-G8, measured)** | **15** — every show on the Terminal Bar page (7 + 8), which states no time anywhere; the model wrote `00:00:00` for 14 of them and `09:30` for one (it read the act "Dirty 930" as a time and dropped the act) |
| Invented end times / prices / image URLs | 0 / 0 / 0 (the baseline schema has no end time or image field; no price invented) |
| Non-music leaks / empty-`acts` shows | 0 / **2** (both poster 2) — leaks are matched on act names and `venue`, so the two empty shows score as clean; only 2 usable runs on the one page with such entries (Terminal Bar's OPEN MIC / DJ Night / OPEN COMEDY headers), and no run extracted them even without the exclusion rule |
| `is_ambiguous` true | 14 of 21 shows (all but the six poster shows and one Terminal Bar show) |
| Fill counts | `time` 21/21 (required), `ticket_info` 6/21 (only the six poster runs) |

**Eyeballed correctness.** Terminal Bar run 0 is visibly worse than run 2: dates shifted by one
(the page lists "Friday August 7th Envies", date before name), Aug 7 missing, "Dirty 930" misread
as a time. Run 2 has all eight dates right. Poster runs: right times and price, wrong year, and
`acts: []` twice for poster 2 — a leaked/empty entry that **only A3's completeness check would
catch** (this is the case the plan's "`acts` may be empty" decision exists for, and it happens
without any A2 change).

**What this baseline can and cannot support.** It *does* show, directly, v0.1-G8's cost (15 invented
times, 13 rejected nulls) and that the baseline schema already fails or comes back empty-ish on a
third of runs. It *cannot* say much about the three largest pages, where it fails 9/9 for what is
a context-window reason (confirmed for White Squirrel by replaying `instructor`'s exact messages through native `/api/chat`: truncated at `num_ctx` 4096, complete with 12 shows at 32768): any label run under the same 4096-token window will
mostly fail there too, and the richer schema (a bigger JSON schema in the prompt) will have less
room still. **Decision for Ari before Step 5** — see "Decisions for Ari" #6 (resolved: derived 32768-context model; the labels below are to be re-run under it).


### Labels `baseline-32k`, `schema-only`, `after` — 32768-token window, 6 fixtures × 3 runs each (October 9–10, 2026)

Run after Decision #6 was resolved: model `gemma4-e4b-32k` (digest `08aefbf02b7c`, same weights as
`gemma4:e4b`), `loaded_context_length` 32768 in every file, Ollama 0.35.0, seed = run index (top-level, so each
run is repeatable; **the same three seeds are used in every label**, so the labels are not independent samples).
Raw: `eval/results/{baseline-32k,schema-only,after}.json`; reproduce with `--legacy`, `--old-rules`, and no flag.
`baseline-32k` is the pre-A2 schema and prompt (frozen in `eval/legacy.py`); `schema-only` is the new schema
(4057-char JSON schema vs 1771) with the new base sentence but neither new rule; `after` adds both rules.
`baseline.json` (4096 window) is **not** comparable to these and stays as the record of the failure.

| Metric | baseline-32k | schema-only | after |
|---|---|---|---|
| Completed runs | 16/18 (2 × `InstructorRetryException`, both Terminal Bar html, 4 attempts each) | **18/18** | **18/18** |
| Mean attempts used | 1.67 | 1.06 | 1.06 |
| Failed parses (field errors in them) | 14 (77: 68 × `time:time_type` — null for the required field, 7 × `time:time_parsing`, 2 × `date:date_parsing`) | 1 (1: `date:date_type`) | 1 (1: `date:date_parsing`) |
| Mean seconds / run | 149 | 118 | 123 |
| **Invented start times** (page states none) | 8 | 2 | 2 |
| **Non-music leaks** (reference terms) | 26 (all Midway) | 26 | **0** |
| `acts: []` shows | 0 | 0 | 0 |
| Invented end times | 0 | 0 | 1 |
| Invented image URLs | 0 | 0 | 1 (`"N/A (Source Image Poster)"`, poster 1) |
| "Invented price" (counts `free_admission`) | 0 | 56 | 18 |
| `is_ambiguous` true | 9 | 8 | 0 |
| Total shows (completed runs) | 214 | 222 | 196 |

Shows found per fixture, three runs each (reference ≈ in the first column):

| Fixture | ≈ | baseline-32k | schema-only | after |
|---|---|---|---|---|
| White Squirrel | 12 | 12, 12, 12 | 12, 12, **6** | 12, 12, **6** |
| Midway | 11 clear + 6 jams | 32, 32, 30 | 28, 36, 28 | **7**, 34, 25 |
| Zhora | 24 | 23, 23, 24 | 24, 23, 23 | 23, 24, 23 |
| Terminal Bar (html) | 8 | 8 (2 runs failed) | 8, 8, 8 | 8, 8, 8 |
| Poster 1 / Poster 2 | 1 / 1 | 1, 1, 1 / 1, 1, 1 | 1, 1, 1 / 1, 1, 1 | 1, 1, 1 / 1, 1, 1 |

**What each number means (read before the verdict).**

- **Reliability improved, and v0.1-G8 is why.** The old schema's required `time` produced 75 rejected time values on
  the Terminal Bar page (the model returning null, then — on two runs — exhausting all four attempts) and 8
  invented start times. With `time` optional the same page completed 6/6 in both new labels. This is the
  clearest result in the table. Mean attempts and wall time fell with it.
- **The exclusion rule worked on the page that tests it.** Midway's 26 leaks (Weekly Pool Tournament, MEGASTELLAR
  OPEN MIC NIGHT, MNUFC GAMEDAY) are untouched by the schema (`schema-only` = 26) and gone with the rule (0). Terminal
  Bar's open-mic / DJ-night / comedy header lines were never extracted in any label.
- **The 2 remaining "invented" start times are one misreading, not invention from nothing.** On the Terminal
  Bar page the model read the act "Dirty 930" as a time (21:30 or 09:30), the same misread seen in the 4096
  baseline.
- **"Invented price" is entirely `free_admission: false`, not a price.** On pages that state no price the
  model returned `false` instead of `null` (Midway 36, White Squirrel 12, Terminal 8 in `schema-only`; White
  Squirrel 18 in `after`). The field description says "otherwise null" and the plan's rule is null-not-false
  (absence of a price must never read as "not free"), so this is the model ignoring the instruction. It
  would read as "confirmed not free" downstream; A3's validation or a coercion should treat it.
- **Zhora's single prices are mostly mislabelled.** Every Zhora listing shows one price; the requirements say a
  single price goes in `admission_day`. The model put 46 of ~70 shows' price in `admission_advance` (the page
  says "Buy now") and 24 in `admission_day`, in both new labels. Fill-rate reading: the field is used, but
  the single-price rule isn't followed reliably. One page; do not generalise.
- **A new instability on White Squirrel.** Seed 2 returned 6 shows, not 12, in *both* new labels: it merged the
  6 pm and 9 pm listings of each day into one show with the show `time` null and a per-act start time, and
  left names unsplit ("The Cottonwood Shivers w. Nat Harriet"). The pre-A2 schema gave 12 on all three seeds.
  The page states no ticket link, so the "several times, one link" rule isn't what justifies it: the per-act
  start-time field appears to invite the merge. A merged show has no show-level `time`, which would break
  A5's (venue, date, time) match key. Because the same seed shows it in both labels it is one repeatable
  case, not two independent ones.
- **The two optional fields that tempted invention did so once each**, in `after` only: an end time that
  was really poster 2's 9 PM start (with the start time left null), and a made-up image URL on poster 1.
  One run in 18 each; below what N=3 can distinguish from noise, but the failure shapes are the ones the
  plan feared.
- **`is_ambiguous` fell from 9/8 to 0 in `after`.** The model never flags ambiguity once told to follow
  listed order. Could be healthy (the plan's "assume listed order") or a lost signal; not decided here.
- **Midway counts are not interpretable.** 7 to 36 shows across runs and labels against a page whose month
  grid is ambiguous: the "Blues Jam with Moses Oakland" entry is listed 3 to 25 times (the page has six).
  The model repeats a weekly entry across months differently each run. The leak count is still valid.
- **Posters.** The `$10` → `admission_day` placement is right in all 12 new runs; times (20:30, 21:00) are
  right in 11 (one `after` run lost the start time, see above); the year is invented (2023 or 2024) in every
  run because the posters have none; act counts vary (1, 3 or 4) where each poster lists 3.

**Verdict: better overall, with named regressions — "mixed, leaning better".** A2's schema change fixed the
reliability failure it was written for (v0.1-G8: 16 → 18 completions, failed parses 14 → 1, invented
start times 8 → 2), and the exclusion rule removes the non-music entries it targets (26 → 0). Against that:
the model ignores "otherwise null" for `free_admission` (writes `false`), mislabels single prices as advance
on Zhora, merges separately timed listings on one White Squirrel seed, and invented one end time and one image URL
in `after`. None is a completion failure — they are the **correctness** problems A3's validation and A5's
matching have to absorb. Caveats, all real: N=3 with shared seeds, one small model, one page for admission
rules, and a Midway page whose ground truth is unclear.

**Follow-ups this produces (recorded in the build plan):** treat `free_admission: false` with no price as
null (or reject) in A3; decide how reconcile handles a show with no `time` but timed acts (A5); watch
the per-act start-time merge on multi-listing days; the invented image URL means the verbatim guard
needs the eval's substring check as an actual filter, not only a metric; and `is_ambiguous`'s meaning needs
a decision before A3 reads it.

### Addendum (October 10, 2026) — an act-splitting regression the verdict above missed

*Found by Claude Opus 5.5 while closing A2. No new eval was run: the numbers below are recounted from the
stored results files (`eval/results/{baseline-32k,schema-only,after}.json`, whose extractions hold every
show's `acts`), then reproduced live by `local_test` (Implementation log round 5).*

The harness records each show's act count, but the write-up above never compared it across labels. Counting
**shows with more than one act / shows returned**, per run:

| Fixture (multi-act listings per the Eval reference) | baseline-32k (old `list[str]`) | schema-only | after |
|---|---|---|---|
| White Squirrel (9 of 12) | 9/12, 9/12, 9/12 | 0/12, 0/12, 6/6 (the merged seed) | 0/12, 1/12, 6/6 (the merged seed) |
| Zhora (nearly all) | 18/23, 16/23, 16/24 | **0**/24, **0**/23, **0**/23 | **0**/23, **0**/24, **0**/23 |
| Terminal Bar html (3 of 8) | 3/8 (its one completed run) | 0/8, 0/8, 0/8 | 2/8, 2/8, 2/8 |
| Posters (3 acts each) | split in all 6 runs | split in 4 of 6 (poster 1 collapsed twice) | split in all 6 runs |

With the pre-A2 schema the model split "Lent w. Gills, Boomdagger" into three acts. With `acts` as a list of
`ActExtraction` objects it almost always returns **one act whose `name` is the whole listing title**.
`local_test` on White Squirrel (October 10) reproduces it: 12 of 12 shows, each with exactly one act.
Because it appears in `schema-only`, the **schema** change caused it, not the new prompt rules. The posters
(the image path) mostly still split, but show the opposite error too: "KURT RUSSELL'S MUSCLES" came back as
two acts in 2 baseline runs and 2 `after` runs, and one `after` run added a fourth act, "OXYGEN".

*Hypothesis, untested:* two things changed at once. The field became an object with a single `name` (inviting
one object per listing), and its description lost the plural: pre-A2 `"The name(s) of the act(s) performing,
in listed order"`, now `"The act(s) performing, in the order the page lists them"`. A2.1 should test the
description alone before anything structural, since it is a one-line change.

**Amended verdict: mixed — better on reliability and exclusion, clearly worse on acts.** v0.1-G8 (completions,
failed parses, invented start times) and v0.1-G9 (non-music leaks) improved as stated above. But **acts**, one
of the three fields in the 95% bar (Decision 9), regressed from mostly split to almost never split on every
multi-act text page. This is recorded as failure **F9** below and is the first thing A2.1 should fix or
explain.

## Refinement strategies — after the A2 eval (October 10, 2026)

**Ari's judgement (October 10): the quality the eval shows is not acceptable, and A2 is not signed off.**
A2's *mechanics* hold (the schema, the rules, the normalizer, the harness; 170 tests), but the measured
extraction is not reliable enough to build A5/A6 on. This section records what the numbers say, the failure
modes, the candidate strategies and a proposed order, so the next piece of work starts from the evidence. **Nothing
below has been implemented or run**; items marked *unchecked* are hypotheses about the pages that nobody has
looked at yet. (Status above is therefore `Awaiting sign-off` only in the lifecycle sense — it is waiting on
this refinement, not on a rubber stamp.)

### The failure modes, with the evidence for each

| # | Failure | Evidence (label, fixture) | Kind of problem |
|---|---|---|---|
| F1 | `free_admission: false` written where the page states no admission at all, against "otherwise null" | `schema-only`: 56 shows (Midway 36, White Squirrel 12, Terminal 8); `after`: 18 (White Squirrel) | model ignores an instruction; **fixable in code** |
| F2 | A single listed price goes to `admission_advance`, not `admission_day` | Zhora, both new labels: 46 advance vs 24 day of ~70 shows; the page says "Buy now" | model misreads a label; **a deterministic rule** (requirements: single price ⇒ day). *October 10: possibly not a model error* — the text is "Buy now $15.24", the DICE online price with fees (the JSON-LD's `offers.price`), which is arguably an advance price; the requirements' rule fits an unlabelled price. A requirements question for Ari in A2.1, before any code rule (see "S1 look: results") |
| F3 | Year invented where the page states none | posters: 2023 or 2024 in every run (baseline and new labels) | missing context; **code can supply it** |
| F4 | Separately timed same-day listings merged into one show with a null show `time` and per-act times; act names left unsplit ("X w. Y") | White Squirrel seed 2: 6 shows, not 12, in `schema-only` and `after` (pre-A2 schema: 12 on all seeds). One repeatable case, not two | **schema invites it** (per-act start time) and flattened text hides listing boundaries |
| F5 | Layout lost, so entries attach to the wrong date or repeat | Midway: 7–36 shows across runs, "Blues Jam" listed 3–25× (page has 6); Terminal Bar run 0 in the 4096 baseline had dates shifted by one listing; "Dirty 930" read as a 21:30 / 09:30 start time in both new labels | **text preprocessing**: `get_text(separator=" ")` flattens the DOM into one line |
| F6 | Invented values in fields added to the schema | `after`: one image URL (`"N/A (Source Image Poster)"`), one poster-2 start time written into `end_time` with `time` left null | fields that tempt invention; **verifiable in code** |
| F7 | Slow | ~120 s per page, most of it the model's reasoning | thinking model; unmeasured lever |
| F8 | `is_ambiguous` fell to 0 under the new rules | `after`: 0 of 196 shows (9 and 8 in the other labels) | meaning undecided; A3 reads it |
| F9 | **Acts not split**: a multi-act listing comes back as one act named with the whole title ("Lent w. Gills, Boomdagger") | *Added October 10* (Eval results › Addendum): multi-act shows White Squirrel 9/12 → 0/12, Zhora ~17/23 → 0 in every run, Terminal Bar 3/8 → 0–2/8; same in `schema-only`, so the schema caused it. Reproduced by `local_test` (12 of 12 single-act) | **schema-induced regression**; first suspect is the `acts` description, which lost "name(s)" |

What *did* improve and should be kept: reliability (v0.1-G8: 16 → 18 completions, failed parses 14 → 1), and the exclusion
rule (26 → 0 leaks on Midway). The refinements below must not regress those.

### Strategies considered

| ID | Strategy | Addresses | Expected value | Cost / risk | Status |
|---|---|---|---|---|---|
| S1 | **Use structured data where the page already has it** (schema.org JSON-LD, an `.ics` feed, the calendar plugin's JSON/REST endpoint); the model is only the fallback. *Unchecked:* White Squirrel's cleaned text mentions "Export .ics file"; Zhora and Midway look like hosted site builders; Terminal Bar is WordPress. Nobody has searched the saved pages or the live sites for this | F1–F6 wherever it applies (exact data, no model) | Potentially the largest: exact dates, times, prices, images with no inference | Fetch changes (A5/fetch scope); some sites won't have it. *October 10:* one generic JSON-LD reader, not per-venue work | **Look done October 10 (on the saved pages; live sites not yet fetched)** — see "S1 look: results" below: 2 of 4 venues have complete JSON-LD |
| S2 | **Preserve structure in the cleaned text** instead of stripping it: one line per element/list item/table cell, day cells kept with their numbers, links and `<img src>` kept (this is also v0.1-G25) | F4, F5, F6 (gives the model boundaries and real image URLs) | High on Midway and Terminal Bar. Token savings are small — the cleaned pages are already 0.8–2.7 KB (~500–900 tokens); the schema in the system prompt (~1000 tokens) and the reasoning dominate | New cleaning code per page shape; must not regress White Squirrel/Zhora | Not started |
| S3 | **Move code-fixable rules out of the model** (validation/coercion between extraction and write): F1 false→null when no price; F2 one price ⇒ `admission_day`; F3 supply the year from the run date or the page's stated month; F6 drop an `image_url` not found verbatim in the page, and treat `end_time` equal to a stated start with `time` null as a misplaced start | F1, F2, F3, F6 | Reliable by construction, cheap, testable without a model; this *is* A3's "validation of agentic output" | Rules can be wrong at the edges; they hide model unreliability rather than reduce it, so keep counting how often they fire | Not started; partly already in the build plan (A3 bullets added Oct 9) |
| S4 | **Shrink what the model must produce**: drop per-act `start_time` / `sequence_number` from the extraction schema (A5 derives order from list position anyway), keep date, time, act names, price, free flag; possibly drop `confidence` | F4 (removes the merge incentive), F7 (shorter output) | Medium; the per-act times are what made merging look correct to the model. Costs the per-act-time requirement, which would then need another route | Departs from requirements-initial.md's per-artist start time; needs Ari's call | Not started |
| S5 | **Chunk the page** (e.g. one day or section per call) | F4, F5, F7, and the original context pressure | Medium–high on Midway/Zhora; short answers are easier to get right | More calls; chunk boundaries need S2's structure to find; merges across chunks | Not started |
| S6 | **Two passes**: first list the entries (date + raw text), then parse each entry with a narrow prompt; code normalizes dates and times between | F4, F5 | Medium; more robust but the most machinery | Most code and the most calls | Not started |
| S7 | **Test the model's thinking off** (native API `think: false`, or a model that doesn't reason) | F7, possibly runaway outputs | Unknown — could cut latency a lot and could cost accuracy | A one-line experiment on the harness; needs the native API path or a model variant | Not started; cheap to try |
| S8 | **Bigger / different model on the hard pages** — `arch-initial.md` §7 already plans "larger model second" on retry | accuracy broadly | Unknown; depends on what fits this machine | Hardware; slower | Not started |
| S9 | **Vision (screenshot of the page).** Possible (Playwright is a dependency; `gemma4:e4b` supports images; posters already go through it). Not recommended as the main path: a tall page needs tiling, images cost more tokens and time (posters took 30–60 s), and a small local model reads text from pixels worse than it reads text we hand it. The poster runs show no reliability edge (invented years; 1, 3 or 4 acts for a 3-act poster). Where it earns a place: pages whose text isn't in the HTML (flyers, canvas/JS-drawn calendars), and perhaps a layout-heavy grid as a check. S2 should capture most of the layout benefit without vision | F5 (partly) | Low as a main path; real as a fallback | Browser dependency; token/time cost | Considered, not planned |
| S10 | **Repeat and vote** (2–3 extractions, keep what agrees) | noise | Low–medium | Multiplies a ~2-minute run | Last resort |
| S11 | *Added October 10.* **Set the sampling temperature.** Neither the pipeline nor the eval sets it, so every A2 label ran at the model's defaults: `ollama show gemma4-e4b-32k` gives `temperature 1`, `top_k 64`, `top_p 0.95` (and thinking on by default). 1.0 is unusual for extraction | run-to-run noise behind F4 (one seed), F5 (Midway 7–36), possibly F9 | Unknown; plausibly large for consistency, which the 95% bar needs across runs | One line (top-level `temperature`, like `seed`); near-deterministic runs make extra seeds less informative, so vary pages instead | Not started; cheap — run before S4–S10 |
| S12 | *Added October 10.* **Constrain the output to the JSON schema.** `instructor`'s `Mode.JSON` only asks for JSON (an OpenAI-style `json_object` response); it does not constrain decoding to the schema. Ollama can (native `format` with a JSON schema; whether its `/v1` honours `response_format: json_schema` in 0.40.2 is unchecked) | parse failures and their re-asks (already rare: 1 in 18 runs) | Low–medium: removes a failure class by construction | Interaction with thinking; Phase 5 found `Mode.TOOLS` unreliable on this model, so test the mode switch rather than assume | Not started |

### S1 look: results (October 10, 2026)

*Done by Claude Opus 5.5 on the saved fixtures (`eval/fixtures/*.html`): searched the raw HTML for
`application/ld+json`, iCal/webcal links, plugin and platform markers, and parsed every JSON-LD block. The live
sites were not fetched.*

| Venue | Platform | Structured data in the saved page | What it gives | What still needs a model |
|---|---|---|---|---|
| White Squirrel | WordPress + The Events Calendar plugin | **12 schema.org `Event` JSON-LD objects** (= the reference's 12); the plugin's REST API (`wp-json/tribe/events/v1/`); an iCal/webcal export | name, `startDate`/`endDate` with offset (`-05:00`), image for some, event URL; no `offers` (the page states no price either) | splitting "X w. Y, Z" titles into acts (`performer` is only `"Organization"`); HTML entities in names (`&#038;`) |
| Zhora Darling | Squarespace, tickets on DICE | **24 `MusicEvent` JSON-LD objects** (= the reference's 24) | start/end in **UTC** (`23:00:00Z` = 18:00 local), `offers.price` (e.g. 15.24), image, ticket URL, the year | splitting "A, B, C, & D"; titles that are not act lists ("4th Annual SummerSlam of Tribute Bands", "Crazy Clyde Presents: …") |
| Midway | Popmenu | **none for events**: one `Restaurant` JSON-LD block; the embedded page state carries only the calendar section's settings, no event records | — | everything |
| Terminal Bar | WordPress (block editor), a hand-written page | none | — | everything — the true model-path page |

What this means for A2.1 (recommendations; the A2.1 plan decides):

- **On White Squirrel and Zhora most failures disappear without a model**: F3 (year), F6 (invented image URL), the
  time half of F4, and prices. What remains for the model is a narrow task — split one title into acts — which is
  exactly where F9 lives, and can be scored directly.
- **The JSON-LD is ready-made ground truth** for those two pages: it and the visible text come from the same
  site record, so dates, times and prices can be scored automatically. Hand-labelling shrinks to act splits,
  Terminal Bar, Midway and the posters.
- **Fixture vs. production input (unchecked, important).** The fixtures were saved from a browser (the `_files`
  folders), i.e. the page *after* JavaScript ran. The pipeline fetches with `httpx.get`, which runs none. Midway's
  events are absent from its server-rendered state, which suggests they load client-side — production may see an
  empty calendar where the eval saw a full grid. Whether the JSON-LD survives a plain fetch on the other two is
  plausible (both platforms render it server-side) but unverified. One `httpx` fetch per live venue settles it.
- **Time zones.** JSON-LD times carry offsets and must be converted into `metro.timezone` (Decisions for Ari #3),
  never passed through `normalize_time`. Zhora's `endDate` is always 3–4 hours after the start, which looks like a
  platform default rather than a stated end time (the page text states none) — whether to store it is a decision.
- **The reader.** A small JSON-LD reader on BeautifulSoup (already a dependency) plus `json` is about 30–50 lines;
  the `icalendar` package if a feed is used; `extruct` (Zyte) held in reserve in case a venue uses microdata. The
  mapping from schema.org `Event` to a show (zone conversion, which price, acts) is ours whatever reads the JSON.
- **Architecture.** Making structured data the first source and the model a fallback changes the pipeline shape in
  `arch-initial.md` §7, and shifts some of the "agentic" learning toward routing (which source to trust). Ari's
  call, in A2.1's plan.

### Measurement has to come first

Right now "better" and "worse" in this file are judged from counts, leaks, invented fields and reading outputs by
eye. There is **no ground truth**, so a refinement could look better and not be. Before comparing strategies:

1. **Hand-label a few pages** — White Squirrel, Zhora and the Terminal Bar page are the cleanest; Midway needs a
   decision about its month grid first. This is A8's labelling, pulled forward in a small form. It turns "shows
   found" into precision/recall and lets field accuracy (date, time, acts, price) be scored per run.
2. **More seeds** (5+, not 3) and **independent seeds across labels**; the current labels share seeds 0–2, so
   they are not independent samples, and one White Squirrel seed has driven a lot of the story.
3. Report **per-fixture**, not totals: the totals mix a page where 12 shows is right with one (Midway) where nobody
   knows the answer.

### Proposed order (a recommendation — Ari decides)

1. **S1 look** (read-only; ~30 min): search the four saved pages (`eval/fixtures/*.html`, searching the raw HTML
   for JSON-LD, `application/ld+json`, `.ics`/`webcal` links, API endpoints) and then the live venue sites for a
   feed or JSON endpoint. Outcome: for each venue, "structured source exists / does not".
2. **Label** White Squirrel, Zhora, Terminal Bar html (and the two posters) by hand.
3. **S3** (rules in code) — cheap, testable, fixes F1/F2/F3/F6 regardless of anything else; each rule gets a
   test and a "how often did it fire" counter.
4. **S2** (structure-preserving cleaning) and re-run the labelled pages; this is the main test of the "less to
   sift through" idea — measured by F4/F5 on the labelled pages, not by token count.
5. **S4/S5/S7** as needed, one at a time, each against the labels.
6. S6, S8, S9, S10 only if 1–5 aren't enough.

*Updated suggestion, October 10 (after the S1 look, F9 and the environment change; the A2.1 plan decides):*

0. **Re-baseline on the current environment.** Ollama updated itself to 0.40.2 and the derived model was
   re-created (Start here, below); re-run at least the `after` label before comparing anything new against the
   stored results, and recheck whether `/v1` still ignores `num_ctx`.
1. **One live `httpx` fetch per venue** — what production actually sees (JSON-LD present? Midway's grid present?).
2. **F9 first**: restore act splitting, starting with the one-line `acts` description; measure act counts
   against the Eval reference.
3. **S11** (temperature) as its own label.
4. **S1**: the JSON-LD reader with the model only splitting titles; JSON-LD as ground truth for White Squirrel and
   Zhora; hand-label Terminal Bar, Midway (after its month-grid decision) and the posters.
5. **S3** for F1 (a schema-level `False` → `None` coercion is simplest, if `false` carries no meaning downstream),
   F3 and F6; F2 only after the requirements question above.
6. **S2** for the pages still going to the model; S12 and S7 as measured experiments.

### Scope: where this work lives

This is more than a fix-up. It touches fetch/cleaning (S1, S2), validation (S3, which is A3's territory), and
possibly the extraction schema (S4), and it needs its own plan, review and approval under `AGENTS.md`'s cycle.
**Decided (Ari, October 10): a new milestone, A2.1.** This file stays as the record of A2 as built and measured; the
refinement gets its own plan (`a2.1-extraction-reliability.md`, via `/plan-milestone`), with S1 and the labelling as its
first items. A3 keeps the validation half (see Decision 7).

### Decisions for Ari (October 10) — resolved

7. **New milestone or fold into A3? — DECIDED: a new milestone, named A2.1** (Ari, October 10). It gets its own plan file
   (`docs/dev/implementations/a2.1-<slug>.md`, e.g. `a2.1-extraction-reliability.md`) and runs the plan → review →
   approval cycle in `AGENTS.md`. A3 keeps the validation half; where S3 overlaps A3's bullets, A2.1's plan decides
   which milestone owns which rule. (This file's earlier text calls it "A2b"; it is A2.1.)
8. **Keep per-act start time in the extraction schema (S4)? — DECIDED: keep it for now** (Ari). It is in
   `requirements-initial.md`. Revisit only if the merge problem (F4) proves catastrophic and too costly to solve another
   way (S2 structure-preserving text, S5 chunking); in that case bring the trade-off to Ari before dropping it.
9. **What is "reliable enough"? — DECIDED: 95%** (Ari). Wording to carry into A2.1's plan: *at least 95% of shows on the
   labelled pages are extracted with the correct date, time and acts.* Ari's reasoning: the information is simple, so
   the extraction has to be reliable; a calendar that is often wrong is of no use. **Left for A2.1's plan to define
   precisely and for Ari to confirm** (not yet decided): whether the 95% is measured as recall (real shows found and
   correct), precision (returned shows that are real and correct), or both; whether a null time on a page that states
   none counts as correct; how admission prices, end time and image link are scored; and how many seeds/runs the 95% must
   hold across (a single lucky run should not pass the gate).

### New product requirement from this discussion (not yet in the requirements doc)

**Each listing must say that an AI agent visited the venue's site and interpreted it, and that users should verify with
the venue.** (Ari, October 10.) This is a user-facing requirement, not an extraction detail: it belongs in
`requirements-initial.md` (a standing notice on show blocks / the day and venue views, wording and placement to be
designed) and is a B3/B4 UI item. **I have not added it to either document**; Ari asked for it to be recorded here only.
It also bears on the 95% bar: the notice is a mitigation for the remaining errors, not a substitute for the bar.

### Start here — for whoever picks up A2.1

(Written for a model that has not seen this conversation. Read `AGENTS.md`, then this file's "Eval results" and
"Refinement strategies", then `docs/dev/notes.md`'s last three sections.)

- **State of the code** (updated October 10): A2 is built: `agent_worker/{schemas,prompts,normalize,nodes}.py`, the harness
  in `agent_worker/eval/` (`run_eval.py`, `reference.py`, `legacy.py`), 197 passing tests in `agent_worker/tests/`. The four
  `TODO(Ari)` gaps were filled by Ari and their scaffolding removed. Since the measurement, one behaviour change: a time with
  no AM/PM is read as PM (normalizer and all three time descriptions — Decisions for Ari #2), so the schema the code now
  sends differs from the stored labels' by that phrase. `make check` green on October 10.
- **Environment you must know about:** run the eval against the derived model `gemma4-e4b-32k`
  (`apps/api/ollama/gemma4-e4b-32k.Modelfile`, `MODEL_NAME` in `apps/api/.env`). Ollama 0.35.0's `/v1` endpoint ignores a
  request's `options.num_ctx` and `options.seed`; a model's own default context is honoured and `seed` must be a top-level
  argument (`notes.md`). The harness records `loaded_context_length` per label; a value of 4096 means a wrong run.
  **Changed since the measurement (found October 10):** the Ollama app updated itself to **0.40.2** (the stored labels say
  0.35.0), and `gemma4-e4b-32k` was re-created on October 10 at 07:27 — its digest is now `654af1bf75f4`, not the
  `08aefbf02b7c` in the results files (the base `gemma4:e4b` is unchanged, `c6eb396dbd59`). Whether 0.40.2's `/v1` still
  ignores `num_ctx` is unchecked. The model's sampling defaults are `temperature 1`, `top_k 64` and thinking on (S11).
- **The measurements to beat:** `eval/results/{baseline-32k,schema-only,after}.json` (git-ignored; reproduce with `--legacy`,
  `--old-rules`, no flag; `--compare` prints them side by side). `baseline.json` is the 4096-window run and is not comparable.
  Read the act-splitting Addendum before trusting `after`'s totals: it is better than `baseline-32k` on reliability and
  leaks and much worse on acts. Re-baseline on the current Ollama before comparing new runs (Proposed order, step 0).
- **Rules of this repo that matter here:** every non-trivial milestone gets a plan file reviewed by a different model;
  `[fill-in]` tasks are scaffolds with `TODO(Ari)` gaps, never filled by the agent unless Ari asks; tests state what they prove;
  comments explain why; `make check` before claiming done.
- **First items for A2.1's plan:** see "Proposed order" › *Updated suggestion, October 10* (the S1 look on the saved pages
  is done; its results are in "S1 look: results"). Decisions the plan should put to Ari: the structured-data-first
  architecture, the F2 single-price wording, whether to store JSON-LD's default-looking end times, Midway's month grid, and
  the open parts of the 95% bar (Decision 9).

## Reviewer brief — Plan review, round 1

*Written by the author for the reviewer. Ari's prompt to you can be one line ("review
`a2-extraction-schema.md`"); everything else you need is here and in `AGENTS.md`. Replace this
brief's relevance with your own judgment — it lists where I most want scrutiny, not the only
places to look.*

**Your job:** find what is wrong, missing or risky in this plan **before any code exists**. You are
a different model from the author (Claude Sonnet 5.5). Do not take any claim in this file on
trust: the ones marked "verified" below were checked by the author on one machine and are exactly
what you should re-check.

**What you may write:** only a new `### Round 1 — <your model>, <date>` at the end of
`## Plan review`, plus this file's header `Status` (set it to `Plan review: findings open`) and
`Reviewer model` line. Do not edit the plan body, any code, docs or tests, even for a one-character
fix — put it in a finding. Scratch experiments belong in a throwaway `git worktree`, removed
afterwards, and you say so in your round's preamble. Leave every **Resolution** cell empty. Then
stop; the author resolves, and Ari approves.

**Round format** (from `AGENTS.md`): a preamble (scope; what you read; commands you ran and their
results; counts by severity; verdict — *proceed*, *proceed after fixes*, or *rework*), then:

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|

Severity is `blocker` / `should-fix` / `nit`. Evidence is a file:line, a doc section or command
output, marked **CONFIRMED** (you reproduced it) or **PLAUSIBLE** (reasoned only).

**Read first:** this file; `AGENTS.md` (especially "[fill-in] tasks" and "Implementation plans");
`docs/dev/alpha-build-plan.md` §3 and §5 A2–A3, A7 and the v0.1-G7/G8/G9 rows of §1.3;
`docs/arch/requirements-initial.md` "Agent Extraction: Fields", "One Show or Several?", "Agent
Handling of Entries … without performing artists", "Agent Validation";
`docs/arch/data-model-initial.md` §2 `show` / `show_artist`; `docs/dev/env-setup.md` Phase 5 (the
model decision and its failure mode); `docs/dev/notes.md`; `docs/references/fastapi-style-guide.md`.
Code: `apps/api/agent_worker/{schemas,nodes,state,graph,constants}.py`,
`agent_worker/eval/run_eval.py`, `agent_worker/local_test.py`, `apps/api/pyproject.toml`,
`apps/api/conftest.py`, `apps/api/app/testing/db.py`, `.github/workflows/ci.yml`, `Makefile`.
You may run read-only commands: `uv run ruff check .`, `uv run mypy app/`, `uv run pytest`, and
short Python snippets against the installed packages (`apps/api/.venv`). Ollama with `gemma4:e4b`
is running on this machine; a **single small** model call to test a claim is fine, but do not run
the eval harness end to end (that is step 2 of the plan and takes a long time).

### Where I most want scrutiny

1. **The claims I marked verified.** Re-check each. (a) `html_clean` drops `<img src>` URLs so
   `image_url` cannot be grounded on text pages. (b) In Pydantic 2.13, `X | None` with no default is
   still *required*. (c) Nothing reads `.acts` or `ticket_info` outside `schemas.py`. (d)
   `eval/run_eval.py`'s instruction has drifted from `nodes.py`'s (it lacks the `page_readable`
   paragraph). (e) `instructor` 1.15.4 exposes a `parse:error` hook usable to count retries —
   check the real call signature (`client.on(...)`), and whether the count reflects retries of the
   structured-output call as the plan assumes. (f) `agent_worker/tests` would be collected by
   `testpaths = ["app", "agent_worker/tests"]` without collecting `local_test.py`, and the root
   `conftest.py` plugin loads harmlessly there.
2. **Import side effects in the new tests.** `agent_worker.nodes` builds an `OpenAI` client and an
   `instructor` client at import time, and imports `app.config.settings`. Does importing it in a
   test (for the "nodes uses the shared prompt" check) break in CI, where `MODEL_NAME` is a
   placeholder and there is no Ollama? Would importing `run_eval` do the same?
3. **Schema design.** Is the required set `{venue, date, acts, is_ambiguous, confidence}` right
   against the requirements ("Date (required)")? Is `sequence_number` better required or optional?
   Is `Decimal` plus `ge=0` (and deliberately no `decimal_places`) a sound choice for a model that
   emits JSON? `free_admission` null-not-false: consistent with the data model's CHECK and
   `api-contract.md`? `image_url` as plain `str` rather than a URL type? Does a nested
   `list[ActExtraction]` plus several `datetime.time` fields plausibly raise the failure rate of a
   small local model — in particular, how does Pydantic parse the time strings a model tends to
   emit ("7pm", "7:00 PM", "19:00")? Is this a pre-existing risk or one A2 enlarges?
4. **The test approach.** Does each test fail for the stated reason before the code exists? Which
   could pass while the code is wrong? The description-contains-"null" test and the prompt
   string-contains tests pin wording, not behaviour: acceptable, or a trap? Is the "both modules
   use `prompts.extraction_instruction`" check meaningful or satisfied by an unused import? Is
   pulling a slice of A7 (v0.1-G14) forward into `testpaths` the right call, and is anything in CI
   affected (the python job now has a Postgres service; `make test` sets `REQUIRE_DB=1`)?
5. **The `TODO(Ari)` gaps** (table in "The `[fill-in]` steps"). Are these the right lines — where
   the concept lives, not where the typing is — per `AGENTS.md`? Is leaving the *old* declarations
   in place for the two schema gaps a legitimate "fails loudly" placeholder, given that a
   `raise NotImplementedError` inside a Pydantic class body would break every import? Is the
   re-marking proposal (split build-plan A2 item 1) sound? Should anything else be a gap, or any
   of the four be dropped?
6. **The measurement design.** Is baseline-before-change ordering enforced by the plan's step
   order? Are N=3 runs, six fixture files and the listed metrics enough to say anything about
   "more or less reliable"? Are the metrics well-defined and obtainable (retry counting, the
   verbatim `image_url` check, "non-music leakage")? Does running with the same default sampling
   settings as the pipeline make the comparison fair, or should temperature be pinned for the eval?
   Is anything in step 0 (moving the prompt, switching the eval to the pipeline's prompt) going to
   contaminate the baseline?
7. **Gaps versus the docs.** Compare the schema and prompt rules, field by field, with
   `requirements-initial.md` "Agent Extraction: Fields": End Time, admission rules (single price →
   day; free only if explicit), "Do not populate Artist image link", the sequence-number
   assumption, and the fields **agents must not populate** (age restriction, alcohol, setting,
   seating). Does anything in the requirements, or in `arch-initial.md` §7's validation/retry
   description, conflict with what A2 does? Does the plan cover every A2 item in the build plan, and
   does it say plainly where it departs (adds `end_time`, a shared prompt module, `testpaths`)?
8. **Downstream effects.** Anything A2 makes harder for A3 (validation checks, the `is_ambiguous`
   interaction), A5 (the `time` → `show.start_time` mapping, composite-key matching with a now-
   nullable time, per-act `show_artist` rows) or A6 (`Decimal` fit to `Numeric(10, 2)`)?
   A null show time in particular: what does reconcile's (venue, date, time) key do with it?

## Plan review

_No rounds yet. Round 1 is the reviewer's, written to follow the brief above; the author fills in
the Resolution column afterwards, then Ari approves._

### Round 1 — Claude Opus 5.5, October 8, 2026

**Scope:** the plan as written (no code exists yet). **Read:** this file; `AGENTS.md` ("[fill-in]
tasks", "Implementation plans"); `alpha-build-plan.md` §3, §5 A2/A3/A5/A7, v0.1-G7–v0.1-G9/G14;
`requirements-initial.md` "Show", "Agent Extraction: Fields", "One Show or Several?", "…don't have
performing artists", "Agent Validation", "Agent Reconciliation"; `env-setup.md` Phase 5;
`agent_worker/{schemas,nodes,state}.py`, `eval/run_eval.py`, `local_test.py`, `pyproject.toml`, root
`conftest.py`; installed `instructor` (v2 `core/{client,retry,hooks}.py`) and Pydantic 2.13.4 source/behaviour.
**Ran:** `uv run ruff check .` → clean; `uv run mypy app/` → clean (28 files); `uv run pytest -q` →
64 passed. Short Pydantic snippets (time/Decimal parsing, JSON schema, required-ness); an import of
`agent_worker.nodes` and `agent_worker.eval.run_eval` with CI's placeholder env; `html_clean` on a
sample with `<img>`/`<a>`; a regex scan of the cleaned fixtures; **one** small `gemma4:e4b` call
(two optional time fields, `max_retries=0`). No worktree, no files written besides this round and
the header.
**Re-checked "verified" claims:** (a) CONFIRMED — `html_clean('…<img src=…poster.jpg>…<a href=…>Tickets</a>')`
→ `'Show 8pm Tickets'`: link *text* survives, no URL does. (b) CONFIRMED — `t: datetime.time | None`
with no default → `missing` error, and it lands in `required`. (c) CONFIRMED — `.acts`/`ticket_info`
appear only in `schemas.py` (other grep hits are unrelated prose). (d) CONFIRMED — `run_eval.py:97-105`
lacks the `page_readable` paragraph in `nodes.py:137-143`. (e) CONFIRMED with caveats — see #5.
(f) PLAUSIBLE — `local_test.py` is outside both proposed testpaths; the root-conftest plugin only
imports `app.testing.db` and defines fixtures nothing in `agent_worker/tests` requests. Importing
`nodes`/`run_eval` with `DATABASE_URL`/`MODEL_NAME` placeholders and no network: CONFIRMED safe
(client construction makes no call).
**Counts:** 0 blocker, 9 should-fix, 8 nit. **Verdict: proceed after fixes.**

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | `ActExtraction.sequence_number` is required with `ge=1`, but it is fully derivable from list position — which is exactly the requirement's fallback ("make an assumption … based on the order in which the artists are listed"). | Plan §Design schema; `requirements-initial.md` "Agent Extraction: Fields". PLAUSIBLE | A model that numbers from 0, repeats a number, or skips one raises a `ValidationError`, and instructor re-asks for the **whole page** — a new, avoidable retry source on every multi-act page, for a value code can compute. | **Fixed.** `sequence_number` is now `int | None = Field(default=None, ge=1)`, "only if the page states a performance order, otherwise null"; A5 derives order from list position when null (Design › Schema; test table: omitted → `None`, `0` rejected, `1` accepted). |
| 2 | should-fix | A nullable `time` meets reconcile's (venue, date, time) key with no rule for NULL. The plan says only "A5 maps `time` → `show.start_time`". | `requirements-initial.md` "Agent Reconciliation" (date and time are the primary match fields); `reconcile_node` docstring (`nodes.py:243-245`). PLAUSIBLE | In SQL, `NULL = NULL` is not true, so a naive composite match never matches an untimed show: each run inserts a duplicate and soft-deletes the previous one. Two untimed shows on one date collide. A time that appears later (null → 20:00) reads as remove + insert. | **Fixed (recorded; decision at A5).** Design › Consequences states the NULL-matching failure and recommends a rule (match on (venue, date) when exactly one candidate exists, else insert and flag; null → time is an update). Step 6 adds it to build-plan A5. Ari confirms it in A5's plan; A2 only makes the case reachable. |
| 3 | should-fix | The non-music rule (TODO #3) has no decided scope for entries the fixtures actually contain: DJ nights (is a named DJ an "identifiable artist"?) and comedy (not music; the requirements are silent). | Cleaned-fixture scan: Zhora `karaoke`, `party`, `dj`; Terminal `open mic`, `comedy`, `dj`; Midway `open mic`. `requirements-initial.md` names only karaoke / party / open mic / "hosted by". CONFIRMED | TODO #3's Code block can't be near-exact, and "non-music leakage" can't be scored, until someone decides these. Each judgment the prompt leaves open is the kind Phase 5 found exhausting the token budget. | **Fixed.** Asked Ari, decided October 9: a *named DJ* is an artist (DJ nights are shows); *comedy* is excluded with karaoke, open mic and artist-less parties; "Hosted by" never counts. Recorded in Design › Prompt and in the TODO #3 row, so its Code block can be written near-exactly. |
| 4 | should-fix | Two of the eval's metrics are undefined without a small hand-written reference: "non-music entries leaked" and "invented end times" both need to know which entries are non-music and which listings state an end time. | Plan Verification 3; Step 1 metric list. PLAUSIBLE | Without a per-fixture list written **before** the baseline (a few lines per fixture — not A8's full labels), both numbers become after-the-fact judgment, and the two runs may be scored differently. | **Fixed.** New Step 1b: a hand-written per-fixture "Eval reference" (non-music entries by name/date, listings stating an end time, priced listings, multi-act listings), written before the baseline and used to score all labels. Verification 3 now names it. Not A8's labels. |
| 5 | should-fix | Retry counting via `parse:error` is right in mechanism but undefined in meaning. `create()` defaults to `max_retries=3`, i.e. up to **4** attempts per call (`stop_after_attempt(max_retries + 1)`). `parse:error` fires on every failed parse, **including the last** (`is_last_attempt` kwarg). `IncompleteOutputException` (the Phase 5 failure) is re-raised immediately and **never** emits `parse:error`. | `instructor/v2/core/client.py:72-96` (`max_retries … = 3`); `retry.py:155`, `:184-185`, `:236-248`; `hooks.py:136-158` (a handler taking only `error` works). CONFIRMED by inspection | "Parse errors" means *retries* on success but *attempts* on failure, so the Phase 5 mode shows up only as an outcome. The default of 3 is implicit in both call sites: the graph's own 3-attempt cap multiplies to up to 12 model calls per venue, and each re-ask grows the context. | **Fixed.** Step 0 passes `max_retries=3` explicitly at both call sites with a why-comment (behaviour unchanged; A3 revisits). Step 1 defines the metric: `attempts_used = parse_failures + (1 if ok)`, `IncompleteOutputException` recorded as its own outcome class, one handler per client with the counter reset per call, failures classified by field. |
| 6 | should-fix | The "after" run changes four things at once: schema shape, base-prompt wording, the non-music rule and the one-show rule. The Risks section's response ("drop `end_time` or per-act times") assumes a regression can be traced to schema fields. | Plan Steps 4–5, Risks. PLAUSIBLE | If "after" is worse, nothing says whether the schema or the new rules caused it, so the planned simplification could remove the wrong thing. | **Fixed.** Step 5 now runs two labels, `schema-only` (new schema, `extraction_instruction(include_new_rules=False)`) and `after`; Risks says which to remove depending on where a regression first appears. 6 × 3 × 3 = 54 runs. |
| 7 | should-fix | The "`nodes` and `run_eval` both reference `prompts.extraction_instruction`" test can be satisfied by an unused import. | Plan Test approach, `test_prompts.py`. PLAUSIBLE | The drift the plan exists to fix (two prompt copies) can come back unnoticed: a module imports the function and still sends its own string. | **Fixed.** `test_prompts.py` is now behavioural: monkeypatch `nodes.instructor_client` with a capturing fake, call `extract_node`, assert the sent content contains `extraction_instruction()`; same for `run_eval.extract` with a temp file. Import-identity check removed. |
| 8 | should-fix | `Decimal \| None` with `ge=0` doesn't produce the simple JSON schema the plan implies: Pydantic emits `anyOf: [{type: number, minimum: 0}, {type: string, pattern: <regex>}, {type: null}]`, sent twice per show. Nothing at the extraction layer needs Decimal; `Numeric(10, 2)` matters at A6's write. | Snippet: `model_json_schema()` output; `"$15"` and `"15 USD"` → `decimal_parsing`. CONFIRMED | A noisier schema for a 4B model, for no benefit before A6. It also confounds the eval: worse admission fill rates could come from the schema shape rather than the model. | **Fixed.** Prices are `float | None, ge=0` in the extraction schema; A6 converts with `Decimal(str(v))` and quantizes to `Numeric(10, 2)` (Design › Schema; Step 6 adds it to A6). Tests: `"15.00"` and `15` both accepted. |
| 9 | should-fix | TODO #1 (`time … = None`) and TODO #2 (`acts: list[ActExtraction]`) are each a one-token edit to a Pydantic field declaration, a kind of gap `AGENTS.md` explicitly lists as bad. Leaving the old declarations in place isn't the "fail loudly" placeholder the rule asks for either; it relies on the tests being red. | `AGENTS.md` "Picking the gaps" ("Bad gaps: … Pydantic field declarations"); plan "The `[fill-in]` steps". CONFIRMED (doc text) | Ari types nothing that carries the lesson. The lessons ("`X \| None` without a default is still required"; "a shape change ripples to every reader") already live in the Lesson comments, the tests and `notes.md`. | **Rejected, by Ari.** Asked October 9; Ari chose to keep all four TODOs as planned. The reasoning is recorded in the TODO section so the code reviewer doesn't re-raise it. The build-plan re-marking proposal stays open. |
| 10 | nit | Pydantic's time parsing is strict: `"7:30"`, `"7pm"`, `"7:00 PM"`, `"8:00pm"` and `"24:00"` are all rejected (`time_parsing`), while an integer `68400` is accepted as a **timezone-aware** `19:00:00+00:00`. A2 triples the time fields per show (`time`, `end_time`, each act's `start_time`). Mitigation: in my one sample the model emitted ISO times (`"19:30:00"`, `"23:00:00"`), so the risk is real but may be small. | Snippets; one `gemma4:e4b` call. CONFIRMED (parsing) / PLAUSIBLE (frequency) | Any one bad time fails the whole page and triggers a re-ask, so a richer schema could look worse for a format reason, not a content one. An aware time would later fail to compare with naive ones in A5. | **Fixed (partly deferred by design).** Every time field's description says 24-hour `HH:MM` (test-enforced); the eval classifies parse failures by field. **Superseded October 9 by Ari:** the lenient conversion is now in A2, not deferred — a `BeforeValidator` normalizer (new Design › Time normalizer: 12-hour with meridiem, null-ish words → `None`, tzinfo dropped, ambiguous `"7:30"` and integers rejected), with its own tests. Not seen by the plan reviewer; Ari decides whether it needs a round. |
| 11 | nit | The `time` description doesn't say which time counts when a listing gives both doors and music. | Plan §Design; common "Doors 7 / Show 8" listings. PLAUSIBLE | Inconsistent choices across runs change reconcile's key and read as time changes, i.e. remove + insert (requirements, Agent Reconciliation). | **Fixed.** The `time` description defines it as when the music starts, not doors; test asserts it mentions doors (TODO #1 lesson updated). |
| 12 | nit | `acts` is required but can be `[]`. The requirements say a show has "one or more" artists, and the non-music rule says artist-less entries are not shows. The plan doesn't say whether that is a schema rule (`min_length=1`) or A3's completeness check. | `requirements-initial.md` "Show" ("Artists … One or more"). PLAUSIBLE | Left implicit, A3 may assume the schema enforces it while the schema assumes A3 does. A leaked "Karaoke" with `acts: []` passes both. | **Fixed.** `acts` stays a plain list; `acts=[]` validates, pinned by a test that says A3 owns the check; Step 6 adds the non-empty-`acts` completeness check to A3. Reason in Design › Consequences: a schema rule would turn one leaked entry into a full-page re-ask. |
| 13 | nit | The "every optional description contains `null`" test is satisfied by words like "nullable" or "not null". | Plan test table. PLAUSIBLE | The convention it guards ("say how to express not-stated") can quietly drop out while the test stays green. | **Fixed.** Descriptions must contain the exact phrase `otherwise null` (test table). |
| 14 | nit | Both the pipeline and the eval label every image as `image/png`, including `terminal_bar_show_2.webp`. This predates A2 and affects both labels equally, but it adds noise to the two image rows. | `nodes.py:151`; `run_eval.py:124`. CONFIRMED | The poster results for the webp fixture may reflect a mislabelled image rather than the model. | **Rejected.** The `image/png` label is a pre-existing bug on a path the build plan defers (§8, image-embedded shows) and affects every label equally. Not fixed in A2; Step 1 and Risks record it as known noise on the two image rows. |
| 15 | nit | Adding `agent_worker/tests` to `testpaths` pulls part of A7 (v0.1-G14) forward, but Step 6 doesn't update A7's item. | `alpha-build-plan.md` A7 item 1; plan Step 6. CONFIRMED | A7 later redoes or contradicts the change ("a `tests/` directory and a narrower `python_files`"). | **Fixed.** Step 6 edits A7's v0.1-G14 item to say the `agent_worker/tests` path was added to `testpaths` in A2. |
| 16 | nit | Reproducibility: the results files don't record the model digest, Ollama version or options. | Plan Step 1. PLAUSIBLE | A later "after" or re-run can't be checked against the same model build, and `ollama pull` silently changes `gemma4:e4b`. | **Fixed.** Results files record the model digest (`/api/show`), Ollama version (`/api/version`) and request options, with `options.seed` = run index; temperature left at the pipeline default (Step 1). |
| 17 | nit | Only one fixture shows any price (Zhora: `$12`–`$34`); White Squirrel, Midway and Terminal have none. | Cleaned-fixture scan. CONFIRMED | Admission fill rates and the single-price → `admission_day` rule are measured on one page × 3 runs. The verdict should say so rather than generalize. | **Fixed.** Added to Risks: admission fill rates and the single-price rule rest on one page × 3 runs. |

**Suggested changes, by number** (the table holds the evidence; these are what I'd change in the plan):

1. Make `sequence_number: int | None = Field(default=None, ge=1)` with a description like "only if the page states a performance order, otherwise null". A5 then derives order from list position when it is null. This drops a field the model can only get wrong, and it is exactly the requirement's fallback.
2. In this plan, record an explicit null-time rule for A5 and repeat it under the build plan's A5 item, e.g. "an untimed show matches a stored show on (venue, date) when exactly one candidate exists on either side; otherwise insert and flag". Ask Ari whether null → time counts as an update.
3. Ask Ari to decide named DJ sets (artist or not?) and comedy (excluded as not music?), then record the decision in the plan. TODO #3's Code block should then spell the rule out.
4. Before Step 2, add a per-fixture reference list to this file: the non-music entries (by name and date) and any listings that state an end time. Score both runs against it.
5. Pass `max_retries` explicitly in both `nodes.py` and the eval, with a why-comment. Define the eval metric as "attempts used", taken from the `attempt_number` / `is_last_attempt` kwargs. Record `IncompleteOutputException` separately, and register the hook once per client with the counter reset per call.
6. Add a middle run. `extraction_instruction(include_new_rules: bool = True)` lets the eval run `schema-only` (new schema, step-0 wording) before `after`, which separates the effect of the schema from the effect of the rules.
7. Replace the check with a behavioural one: monkeypatch `nodes.instructor_client` with a fake that captures `messages`, call `extract_node(VenueGraphState(venue_id=1, calendar_url="x.html", page_content="…"))`, and assert `extraction_instruction()` appears in the content sent. Do the same for `run_eval.extract` with a tmp text file.
8. Use `float | None = Field(default=None, ge=0)` in the extraction schema, with A6 converting via `Decimal(str(v))` and quantizing to 2 places. If Decimal is kept on purpose, say that the schema shape is part of what the eval measures.
9. Re-mark build-plan A2 item 1 fully [written], following the plan's own re-marking logic, and keep only TODOs #3 and #4. Alternatively keep #2 but make its placeholder fail loudly. A field-level `NotImplementedError` can't work, but a `model_validator` that raises works.
10. Add "24-hour `HH:MM`" to every time description. Have the eval classify parse errors by field, which the error's `loc` makes possible. After the baseline, decide whether a lenient `BeforeValidator` that accepts "7pm" / "7:30 PM" earns its place. Reject integers.
11. Define the time as "when the music starts — not doors" in the `time` description.
12. Leave `acts` as a plain list in the schema, and name this as an explicit A3 completeness check, since a schema rule would turn one leaked entry into a full-page retry.
13. Assert a fixed phrase (e.g. "otherwise null"), or `description.rstrip(".").endswith("null")`.
14. Derive the MIME type from the file suffix in both places, or note the known noise in the results.
15. Add to Step 6: edit A7's v0.1-G14 item to say the `agent_worker/tests` path was added in A2.
16. Write `ollama show gemma4:e4b` (digest), the Ollama version and the request options into each results file. Optionally set `options.seed` per run index so any single run can be reproduced; leave temperature at the pipeline default so the runs stay representative.
17. Add the single-fixture limit to the Risks section.

**Things checked and found sound:** keeping `free_admission` null rather than false matches the data model's CHECK and `api-contract.md`. The schema includes none of the four venue-inherited fields, matching "Not populated by agents in v1". "Never an artist photo" matches "Do not populate Artist image link". The one-show rule wording matches the requirements word for word. Capturing the baseline before changing the schema is enforced by the step order, and step 0 doesn't contaminate it: the only difference is the `page_readable` paragraph, which the pipeline already sends. `state.py` and `validate_node` (reading `show.confidence`) follow the new schema without changes. None of the proposed tests read the eval fixtures, which matters because `apps/api/.gitignore:18` ignores `agent_worker/eval/fixtures/`, so they don't exist in CI. A plain `str` for `image_url` is fine: a URL type would turn a model typo into a full-page retry.

**Resolved October 9, 2026 (author, Claude Sonnet 5.5).** All 17 Resolution cells filled: 15 fixed,
2 rejected (#9 by Ari, #14 with a reason). `Rejected:` #9 (keep all four TODOs — Ari's decision),
#14 (MIME label is pre-existing and on a deferred path). Two decisions came from Ari: the
DJ/comedy scope (#3) and keeping all four gaps (#9). Plan edits are in Design, Test approach, the
`[fill-in]` section, Steps (new 1b; Step 0 `max_retries`; Step 5 now two labels), Verification and
Risks. Awaiting Ari's approval before any code.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 9, 2026

**Scope.** Working tree on top of `283564e` (A1). The tree also holds uncommitted B1/B2 work, so diff
the paths below rather than the whole tree. A2's files:

- *New:* `apps/api/agent_worker/{prompts,normalize}.py`, `agent_worker/eval/reference.py`,
  `agent_worker/tests/{__init__,test_extraction_schema,test_prompts}.py`.
- *Modified:* `agent_worker/{schemas,nodes}.py`, `agent_worker/eval/run_eval.py`,
  `apps/api/pyproject.toml` (`testpaths`), `apps/api/.gitignore` (`eval/results/`).
- *Docs:* this file (Eval reference, Eval results, Decisions #6); `docs/dev/alpha-build-plan.md` — only
  the v0.1-G25 row, the A2 status line, and the new A3 / A5 / A6 / A7 bullets (other hunks in that file are
  B2's); `docs/arch/arch-initial.md` — only the italic note at the end of the "Fetch and extract"
  paragraph; `docs/dev/notes.md` — the last two sections (Pydantic `X | None`; Ollama `/v1`).
- *Not committed; not touched:* `agent_worker/state.py`, `graph.py`, `local_test.py`, `app/`.

**What was built, in plan order.** Step 0: `prompts.py` with the pre-A2 text, `nodes.py` and the eval
use it, `max_retries=3` explicit at both call sites. Step 1: the harness (`--label --runs --only
--old-rules --compare`; outcome classes; `parse:error` counted per call and classified by field;
provenance; scoring against `reference.py`). Step 1b: the Eval reference (table in this file,
machine-readable twin in `reference.py`). Step 2: baseline, 18 runs. Step 3: tests written and run
against the old schema plus a bare `ActExtraction` (127 failed / 17 passed — the failures were the
missing fields, the old required `time`, the absent normalizer behaviour, the old prompt: no import
errors). Step 4: scaffold. Step 5 (`schema-only`, `after`) **not run** — it waits for Ari's TODOs and
Decision #6. Step 6: docs, except ticking A2.

**Departures from the plan, each with its reason.**

1. **The `seed` is a top-level argument, not `options.seed`.** Found when a same-seed smoke run gave
   different outcomes; verified that Ollama's `/v1` ignores `options` (three identical prompts: top-level
   `seed` repeatable, `options.seed` not). The baseline ran *before* this was found and is unseeded
   (annotated in `baseline.json` and in Eval results). A test pins the top-level form.
2. **Bigger find, not fixed: `options.num_ctx` is ignored by `/v1` too** — the pipeline runs at 4096.
   Out of A2's scope (it changes the pipeline's call path or the Ollama setup) and not mine to decide, so:
   recorded in `notes.md`, measured into every results file (`loaded_context_length`), and raised as
   Decision #6. The baseline stands as "the pipeline as it really runs".
3. **Model digest from `/api/tags`**, not `/api/show` (which carries no digest in this Ollama version).
4. **`ticket_info` is already gone in the scaffold**, so `test_the_old_ticket_info_field_is_gone` is
   *green* at handoff. The plan's "red at handoff" list named it, but nothing about removing it is a
   gap; leaving it would only have kept a dead field.
5. **The normalizer tests validate one field in isolation** (`validate_field`: the field's own type
   rebuilt from `model_fields`) rather than `ShowExtraction(date=…, time=value, …)`. Reason: a whole-model
   build needs a valid `acts`, so while TODO #2 is open every `end_time` case would fail for the wrong
   reason. The cost is a small helper to trust (see "where to look hardest").
6. **Prompt text dedented.** The pre-A2 string in `nodes.py` was indented inside the function; step 0
   moved it dedented. Whitespace only, and the baseline was captured after the move.
7. **Extra scoring file** `eval/reference.py` (the table in this file, machine-readable) and the harness's
   `--old-rules` / `--compare` / `--only` flags: needed to make the reference scoring and the
   `schema-only` label runnable; not in the plan's file list.
8. **`prompts.py`'s `include_new_rules=False` returns the new base wording** (admission/image fields), not
   the literal pre-A2 base — it must, because the schema it pairs with has no `ticket_info`. The baseline
   label used the literal pre-A2 text.
9. **Tests added beyond the plan's table:** `max_retries` explicit at both call sites; the seed
   top-level-argument test; the page_readable assertion split into with/without-new-rules.
10. **`make check` is red, and not only for A2's gaps** — see Verification.

**`TODO(Ari)` gaps — all four open (none filled by anyone).**

| # | Where | One-line lesson |
|---|---|---|
| 1 | [schemas.py:91](../../../apps/api/agent_worker/schemas.py#L91) (`time`, line 115) | `X \| None` needs `= None` to be optional in Pydantic v2; the description is an instruction to the model |
| 2 | [schemas.py:129](../../../apps/api/agent_worker/schemas.py#L129) (`acts`, line 143) | `list[str]` → `list[ActExtraction]` is a shape change that ripples to every reader |
| 3 | [prompts.py:45](../../../apps/api/agent_worker/prompts.py#L45) | state the non-music exclusion (named DJ in, comedy out, "Hosted by" never) — correctness *and* reliability |
| 4 | [prompts.py:75](../../../apps/api/agent_worker/prompts.py#L75) | one time / ticket link ⇒ one multi-artist show; several times, one link, still one |

Their tests: `cd apps/api && uv run pytest agent_worker/tests`. #1/#2 leave the old declarations in
place (a `raise` in a Pydantic class body would break every import), so the red tests are the
placeholder, per the plan; #3/#4 `raise NotImplementedError("TODO(Ari)")`. Code review the scaffold as it
stands: the 45 failing tests below are expected, not findings. I verified the four Code blocks work: applied
to a scratch state they take the suite to 145 passed, then restored.

**Verification.**

- `cd apps/api && uv run pytest agent_worker/tests` → **45 failed, 100 passed**. The 45 are all gap-gated:
  30 normalizer cases on `show.time` (#1), plus the required-set, optional-default, `otherwise null`,
  `HH:MM`, doors, JSON-schema, minimal/realistic round-trip, `acts=[]`, `acts`-objects tests (#1/#2), and
  4 prompt tests (#3/#4).
- `uv run ruff check .` clean. `uv run mypy app/` clean (29 files; the worker isn't in mypy's scope until A7).
- Full `uv run pytest` → 45 failed (the same), 148 passed, **18 skipped** — the DB suite, because Postgres
  isn't running here (Docker's daemon is down, so `make db-up` can't run). Under `make check`
  (`REQUIRE_DB=1`) those 18 are *errors*, so `make check` stops at pytest. Not caused by A2, but it means
  **the DB suite was not run against this change** (nothing in A2 touches `app/`).
- `make check` → ruff ✓, `turbo lint` ✓, mypy ✓, `check-types` ✓, `contract-check` ✓ ("Generated contract
  output is current"), pytest ✗ (above). `pnpm run test` in `apps/calendar` also fails: 13 tests, all
  `Error: TODO(Ari)` from **B2's** open gaps (`lib/params.ts`), unrelated to A2.
- Baseline: 18 runs, `eval/results/baseline.json` (see Eval results). One short post-fix smoke run of the
  harness against a poster (`--old-rules`) succeeded and recorded `loaded_context_length: 4096`.
- Not run: the `schema-only` and `after` labels; `uv run python -m agent_worker.local_test` (plan
  Verification 4 — needs the TODOs filled).

**Where to look hardest.**

1. **`normalize.py`** — it was added after plan review round 1, so no second model has seen it (Decisions #1).
   The two regexes, the `bool | int | float` check (bool is an `int`), `"12am"`/`"12pm"`, and that
   `"19:30-0500"` and `"19:30-05"` are handled.
2. **`validate_field` in `test_extraction_schema.py`** — it rebuilds `Annotated[annotation, *metadata]`
   from `model_fields`. If Pydantic stops keeping the `BeforeValidator` in `FieldInfo.metadata` for an
   aliased `Annotated` type, the normalizer tests would test the wrong thing (I confirmed they go green
   with the Code blocks applied, which shows the validator is found).
3. **The harness's numbers** — `attempts_used`, the `invented_*` definitions (an `invented_price` also
   counts `ticket_info`), and `leaks` matching on act names only. They are as good as `reference.py`,
   which I wrote by reading the fixtures and may have misread (the Midway grid's months in particular).
4. **Whether to treat the num_ctx finding as A2's problem at all** — I stopped at recording and asking;
   a reviewer who thinks the harness should force a working window (the derived-model route) should say.
5. **`ShowExtraction`'s field descriptions** — they are the model's instructions and I wrote them without
   having seen a model respond to them; the eval is where they get judged.

## Code review

### Round 1 — Claude Opus 5.5, October 9, 2026

**Scope:** the A2 paths listed in Implementation log round 1, as uncommitted working-tree changes on top of `283564e`: `apps/api/agent_worker/{normalize,prompts,schemas,nodes}.py`, `agent_worker/eval/{run_eval,reference}.py`, `agent_worker/tests/{__init__,test_extraction_schema,test_prompts}.py`, `apps/api/pyproject.toml`, `apps/api/.gitignore`, and the A2 hunks of `docs/dev/alpha-build-plan.md`, `docs/arch/arch-initial.md` and `docs/dev/notes.md`. B1/B2 changes in the same tree were not reviewed. Per the log, the four `TODO(Ari)` gaps are open and are not findings. Plan-review finding 9 (keeping the schema gaps) is Ari's decision and is not raised again.
**Read:** this file in full; `AGENTS.md`; `apps/api/AGENTS.md`; `docs/references/fastapi-style-guide.md` Anti-patterns; the diffs above; `eval/results/baseline.json`.
**Ran:**
- `make check`. ruff, turbo lint, mypy (`app/`), check-types and contract-check all pass. pytest fails with **45 failed, 148 passed, 18 errors**: the 45 are the gap-gated tests, and the 18 errors are the DB suite under `REQUIRE_DB=1` with Postgres down. This matches the log. CONFIRMED.
- `uv run pytest agent_worker/tests` gives 45 failed / 100 passed. I grouped the failures by test name, and every one traces to TODOs #1–#4. CONFIRMED.
- In a **throwaway `git worktree`** of `HEAD`, with the A2 files copied in and the main `.venv` interpreter, I made two passes:
  - TODO #2's Code block **alone** leaves `test_acts_must_be_objects` and `test_an_empty_acts_list_is_deliberately_valid` red (see #5).
  - All four Code blocks pasted verbatim give **145 passed**, and the assembled prompt reads cleanly.
  - I then probed `normalize_time` with about 25 extra spellings, and compared Pydantic's native `datetime.time` parsing on the same inputs.
  - The worktree was removed and pruned afterwards, and a scratch copy of `HEAD:schemas.py` was deleted.
- I scanned the cleaned fixtures (`run_eval.load_text_fixture`) to spot-check `reference.py`, and read `baseline.json` (outcomes, empty-`acts` shows, provenance).
- Old vs new `VenuePageExtraction.model_json_schema()` size: 2,418 vs 4,057 characters (+68%).
- `uv run mypy` on the new worker files: the only non-gap error is outside CI's scope (`run_eval.py:171`, `messages` typing). It belongs to A7 and is not a finding.

**Counts:** 0 blocker, 4 should-fix, 6 nit. **Verdict: proceed after fixes.** The scaffold matches the plan, and the four TODO blocks are well formed: Lesson, Code and Check are each present, the Code pastes cleanly, and the file:line links are correct. The normalizer, the harness's retry accounting and the test wiring hold up. The should-fixes are concentrated in the measurement, because A2's verdict will rest on it.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **The baseline can't be regenerated from the tree, but Decision #6 recommends option (b), "re-run the baseline".** The baseline's schema (`ticket_info`, required `time`, `list[str]` acts) and its verbatim pre-A2 prompt exist nowhere now: `schemas.py` already has the new fields, `prompts._BASE` has the new wording, and the step-0 state was never committed (`prompts.py` is untracked). Results files also don't record the prompt text or the JSON schema each label sent. The Eval results heading says "regenerable with `… --label <label>`", which is not true for `baseline`. | `schemas.py:119-194` (no `ticket_info`); `prompts.py:20-28`; `git status` (`prompts.py` untracked); `baseline.json` keys are `label, started_at, include_new_rules, options, provenance, aggregate, runs`, with no prompt or schema. CONFIRMED | If Ari picks (b), the "re-run baseline" will quietly run something else, either the new schema or a hand reconstruction, and `baseline` vs `schema-only` vs `after` stop being the conditions the plan compares. The 4096-window problem makes this worse: the new schema is 68% larger (2,418 → 4,057 chars), so any label run at 4096 is confounded by size as well. | **Fixed.** New `eval/legacy.py` freezes the pre-A2 schema (verbatim from 283564e) and the step-0 instruction; `--legacy` runs it, so `baseline` is re-runnable independent of git or the live files. Every results file now stores the instruction text, the JSON schema, their hashes and the schema's size (`request`), plus `loaded_context_length`; `baseline.json` got a reconstructed `request` (marked as reconstructed, not captured). A test pins that `legacy=True` sends "any ticket info" and the old schema. The Eval results note now says which flag regenerates each label. The 68% schema growth is a real confound at 4096 and is now visible per label in `--compare`. |
| 2 | should-fix | **The normalizer rejects valid ISO times that Pydantic accepted before it existed.** It never passes a string through to Pydantic. Any string its two regexes don't match is refused, including fractional seconds. | `normalize.py:39-42,93`. Probe: `"19:30:00.000"`, `"19:30:00.123456"` → `ValueError`. Plain `TypeAdapter(datetime.time \| None)` accepts both (and `"19:30:00,5"`). CONFIRMED | This contradicts the plan's contract that normalization "only turns *recoverable* formats into successes" (Design › Time normalizer). A model emitting ISO-with-milliseconds, a common serializer output, now costs a full-page re-ask where the pre-A2 schema succeeded. That flatters `baseline` against `schema-only` / `after` on the time-failure row, the opposite of the bias the plan notes. Fix: accept an optional `(?:[.,]\d+)?` after seconds in `_TWENTY_FOUR_HOUR` and keep the microseconds, or truncate them. Add `"19:30:00.000"` to the accepted table. | **Fixed.** `_TWENTY_FOUR_HOUR` accepts `[.,]\d+` after the seconds and keeps up to six digits as microseconds. Added `"19:30:00.000"` and `"19:30:00.500"` (→ `time(19,30,0,500000)`) to the accepted table, run against all three fields. Test written first, saw it fail. |
| 3 | should-fix | **The leak metric can't see a leak that comes back with `acts: []`.** `score_extraction` matches non-music terms against act names only. A show with no acts contributes no names, so it is never counted, yet the plan's own Consequences section predicts that shape ("one leaked 'Karaoke' entry … with `acts: []`"). The baseline already produced two empty-`acts` shows (poster 2, runs 0 and 1), and the harness recorded them nowhere. The numbers in the results text were counted by hand. | `run_eval.py:221-231`; `baseline.json` `terminal_poster_2` runs 0–1: `'acts': []`; `aggregate` has no empty-acts field. CONFIRMED | "Non-music leaks: 0" can be a false zero, precisely for the v0.1-G9 rule (TODO #3) that A2 is measuring. Fix: count `empty_acts` per run and in `aggregate` / `compare`. Consider also matching the terms against the `venue` string, since a model sometimes puts the entry's title there. | **Fixed.** `score_extraction` now counts `empty_acts` per run, aggregate and `--compare` carry it, and leak matching also checks the `venue` string. Tests first: empty acts counted, venue-titled leak counted, aggregate sums over ok runs only. `--rescore` recomputed `baseline.json`: **empty_acts = 2**, leaks still 0 (recorded in Eval results — the false-zero caveat is now stated). |
| 4 | should-fix | **`"7p"` / `"8:30p"`, the exact format on the Midway fixture, are rejected even though they carry an explicit meridiem.** The plan's rule is that "12-hour with an explicit meridiem is unambiguous". `_TWELVE_HOUR` requires the `m`. | `normalize.py:32-34`. Probe: `"7p"`, `"8:30p"`, `"7P"` → `ValueError`. The cleaned Midway text contains `7p`, `6p`, `8p` (8+ occurrences). CONFIRMED | A model that copies the page's own spelling triggers a re-ask on one of the three fixtures that matter most. The by-field parse-failure row would then report a normalizer gap as model unreliability. Fix: `(?P<meridiem>[ap])\.?(?:m\.?)?`, plus `"7p"` / `"8:30p"` rows in the accepted test table. | **Fixed.** `_TWELVE_HOUR` meridiem is `[ap]\.?(?:m\.?)?`, so `"7p"`, `"8:30p"`, `"7P"`, `"11a"` convert; a bare `"7"` still doesn't (no meridiem). Rows added to the accepted table, test first. |
| 5 | nit | **TODO #2's Check doesn't go green until #1 is filled too.** `test_acts_must_be_objects` builds a whole `ShowExtraction` from `minimal_show()`, which omits `time`. With only #2 filled it stays red on `time: missing`. Separately, its `pytest.raises(ValidationError)` half passes for *any* error, not specifically the `acts` one. | Worktree: #2's Code block alone → `test_acts_must_be_objects`, `test_an_empty_acts_list_is_deliberately_valid` still fail (missing `time`). `test_extraction_schema.py:167-173`. CONFIRMED | Ari fills #2, runs the named Check, sees red, and goes looking for a mistake that isn't there. A gap should cost minutes. Fix: either say "after #1" in TODO #2's Check, or validate `acts` in isolation (`validate_field(ShowExtraction, "acts", ["Band A"])`) and assert the error `loc` starts with `("acts", 0)`. | **Fixed.** `test_acts_must_be_objects` and `test_an_empty_acts_list_is_deliberately_valid` now validate the `acts` field in isolation (`validate_field`), so TODO #2 alone turns the first green (verified: both pass with only #2 applied; the `ValidationError` is now specifically on the `acts` field). TODO #2's Check comment says the round-trip tests also need #1. |
| 6 | nit | **Cross-midnight end times are real in the fixtures, and nothing downstream is warned.** White Squirrel lists "Nona … 9:00 pm - 12:00 am", which normalizes correctly to `end_time` 00:00, earlier than its start of 21:00. | Cleaned White Squirrel text. The A3 bullets added to `alpha-build-plan.md` mention non-empty `acts` but not this. CONFIRMED (fixture) / PLAUSIBLE (impact) | A3's consistency check, or A6's write, may flag or reject a correct record as "ends before it starts". Fix: one line under A3: an `end_time` earlier than `time` means the next day. | **Fixed.** New A3 bullet in `alpha-build-plan.md`: consistency/plausibility must allow `end_time` earlier than `time` (next day), citing White Squirrel's "9:00 pm - 12:00 am". |
| 7 | nit | **The harness's provenance is captured but not surfaced, and two fields mislead.** `compare()` prints no provenance, so a `baseline` at 4096 next to a label at 32768 (Decision #6) would print side by side with nothing to show they differ. `started_at` is stamped when the file is written, after all runs. Each baseline run record carries `"seed": 0/1/2` even though seeds weren't applied (only the top-level `options.seed` note says so). | `run_eval.py:368-390`, `:303`, `:438`; `baseline.json` runs. CONFIRMED | Like-for-like violations are invisible at exactly the moment the labels get compared. Fix: print `loaded_context_length`, `model_digest` and `include_new_rules` per label in `compare()`; take `started_at` before the loop; drop or annotate the per-run `seed` in `baseline.json`. | **Fixed.** `compare()` prints loaded context window, model digest, legacy flag, instruction hash, schema size and `started_at` above the metrics; `started_at` is taken before the loop; baseline's per-run `seed` fields are null and its `options.seed` note says why. |
| 8 | nit | **Stale "step-0 wording" claims.** Departure 8 records that `include_new_rules=False` returns the *new* base wording, but the test comment and the plan body still call it the step-0 wording. | `test_prompts.py:82-83`; plan Design › Prompt ("returns the step-0 wording (base + `page_readable`, no new rules)"). CONFIRMED | Whoever reads the `schema-only` verdict will assume its prompt equals baseline's minus nothing. It actually differs from baseline in the base sentence as well as the schema, so the attribution `schema-only` exists to provide is slightly muddied. The verdict should say so. | **Fixed.** Plan Design › Prompt, the `test_prompts.py` comment, and the Step 5 text now say `include_new_rules=False` is base + `page_readable` with A2's one base-sentence edit, not the literal pre-A2 text; Step 5's `schema-only` note says its verdict is "schema plus that sentence". |
| 9 | nit | `fake_client()` has no explanation. `AGENTS.md` asks that each test helper say in plain terms what it is. | `test_prompts.py:50-51`. CONFIRMED | Minor convention gap. Its neighbours (`FakeCompletions`, `sent_text`) both have one. | **Fixed.** `fake_client()` has a docstring. |
| 10 | nit | The Eval reference says "the pages omit the year", but the Terminal Bar html states **"AUGUST 2026"**. | Cleaned Terminal text: "Music Calendar AUGUST 2026 OPEN MIC …". The plan's Eval reference, last paragraph. CONFIRMED | A free correctness check is left on the table. The posters' "2024" error is real, but on the html page the year *can* be scored. Optional: score the year there, or correct the sentence. | **Fixed.** The Eval reference sentence now says Zhora and the posters omit the year, the other pages state August 2026. Scoring the year on the Terminal Bar page is possible; not added (the baseline's wrong-year finding is on the posters, which have no page text to score against). |

**Checked and found sound:**
- **Normalizer, intended cases.** `normalize_time` behaves as its table says: `bool` is caught before `int`, `"12am"`/`"12pm"`/`"12:00:00 AM"` are correct, `"19:30-0500"`/`"+0530"` are dropped naive, `"19:30 PM"`/`"0pm"`/`"13pm"`/`"24:00"`/`"7:60pm"` are refused, and refusals are `value_error`, the error type `instructor` re-asks on.
- **Strict JSON validation.** `model_validate_json(..., strict=True)` still runs the `BeforeValidator`, so `"7pm"` becomes 19:00 and `"N/A"` becomes `None`.
- **`validate_field`.** The helper really does pick up the `BeforeValidator` and the `ge` constraints from `FieldInfo.metadata`; that is why the suite is green with the Code blocks applied.
- **Optional fields with constraints.** `Field(default=None, ge=…)` on `float | None` / `int | None` is not the style guide's "constraint contradicts the default" anti-pattern: the type is optional, and `ge` applies to the non-null branch (`test_negative_prices_are_rejected` passes).
- **Retry accounting.** `attempts_used` and the `parse:error` accounting match the baseline's own data: a run with 1 failed parse followed by `IncompleteOutputException` is recorded as attempts_used 1.
- **Wiring tests.** They are behavioural (sentinel through a fake client) and would catch a module sending its own string.
- **Test collection.** `testpaths` doesn't collect `local_test.py`, and the results directory is ignored at the right path.
- **Docs.** The A3/A5/A6/A7/v0.1-G25 build-plan bullets and the two `notes.md` entries are accurate against what I reproduced.
- **Decision #6.** Escalating it rather than changing the Ollama setup was right. Option (b) is the sound recommendation, but see #1: it needs a reproducible baseline first.

**Resolved October 9, 2026 (author, Claude Sonnet 5.5).** All 10 Resolution cells filled: 10 fixed, 0 rejected.
`Rejected:` none. Fixes were tests-first where testable (#2, #3, #4, #5, #1's legacy configuration); the
new and changed tests were seen red before the fix. One thing in the round I want Ari's eye on: #1 is the
reviewer pointing at the same problem Decision #6 raises, and the fix (frozen legacy config + stored request)
is what makes Decision #6 option (b) executable. **Test-suite result after the fixes:** `uv run pytest` in
`apps/api` → 48 failed (all gated on the four open `TODO(Ari)` gaps), 170 passed, 18 skipped (DB suite,
Postgres down); with the four Code blocks applied to a scratch state, `agent_worker/tests` → 170 passed, then
restored. `ruff` clean, `mypy app/` clean, `contract-check` current. `make check` still ends red at pytest
(the 48 gap-gated tests, plus the 18 DB tests erroring under `REQUIRE_DB=1` with no Postgres). A round 2 is not
warranted: nothing was rejected and no fix was a rework. A reviewer's header edit replaced the earlier
Status line, including its note that approval was recorded at `/build-milestone` invocation on October 9.

## Implementation log — round 2 (fixes after code review round 1)

### Round 2 — Claude Sonnet 5.5, October 9, 2026

**Scope.** Fixes to code review round 1 only. Files: `agent_worker/normalize.py` (fractions, bare `p`/`a`),
`agent_worker/eval/run_eval.py` (empty-acts metric, venue leak match, `--legacy`, `request` record,
`--rescore`, richer `--compare`, `started_at`), **new** `agent_worker/eval/legacy.py`,
`agent_worker/tests/{test_extraction_schema,test_prompts}.py` (edited) and **new**
`agent_worker/tests/test_eval_harness.py`, `agent_worker/schemas.py` (a Check comment only), plan and
build-plan text, `eval/results/baseline.json` (reconstructed `request`, nulled seeds, rescored). The four
`TODO(Ari)` gaps are all still open and untouched (same file:line targets as round 1, shifted by a few lines in
`schemas.py` only: #1 at 91, #2 at 129).

**Departures from round 1:** none. **Verification:** as in the Resolved note above.

**Where to look hardest:** `eval/legacy.py` — a hand copy of the old schema; it should match
`git show 283564e:apps/api/agent_worker/schemas.py` field for field (I diffed the saved original against git's
and it was identical, but the copy in the repo has the comments dropped). And that `--legacy` has been exercised
live only once, on one poster (it ran, 1 show); the full baseline re-run waits on Decision #6. Its stored
baseline `request` is reconstructed from the same module, so matching hashes prove consistency, not a
record of what was sent at run time.

### Round 3 — Claude Sonnet 5.5, October 9, 2026 (environment fix, after Ari filled the TODOs)

**Scope.** Not a code-review fix; this resolves Decision #6. Files: **new**
`apps/api/ollama/gemma4-e4b-32k.Modelfile`; `apps/api/.env` (gitignored; `MODEL_NAME=gemma4-e4b-32k`),
`apps/api/.env.example`; `agent_worker/eval/run_eval.py` (`MODELS = [settings.model_name]`; tag-tolerant
model-name matching for `/api/ps` and `/api/tags`, since Ollama lists an untagged model as `name:latest`);
`docs/dev/notes.md`; this file. Local Ollama gained one model entry, `gemma4-e4b-32k` (shares `gemma4:e4b`'s
weights); `gemma4:e4b` is untouched.

**State of the TODOs.** Ari has filled all four `TODO(Ari)` gaps; `agent_worker/tests` is 170 passed and
`ruff` is clean. (Not code-reviewed: the review ran against the scaffold.)

**Verification.** `/v1` call to `gemma4-e4b-32k` → `/api/ps` `context_length: 32768`, ~3.4 GB resident.
`--legacy` smoke run on White Squirrel: `ok`, 12 shows, 1 attempt, 137.8 s (first load included),
`provenance.loaded_context_length: 32768`. Not run: the full labels (next).

**Where to look hardest.** Other code that reads `MODEL_NAME` now gets the derived name (`nodes.py` via
`settings.model_name`); the first baseline's `baseline.json` still says `gemma4:e4b`. CI uses a placeholder
`MODEL_NAME`, so it is unaffected.

### Round 4 — Claude Sonnet 5.5, October 9–10, 2026 (the measurement, Step 5)

**Scope.** No code changed. Ran `baseline-32k` (`--legacy`), `schema-only` (`--old-rules`) and `after` (no flag),
3 runs × 6 fixtures each, back to back in the background on `gemma4-e4b-32k`; results files are git-ignored
(`eval/results/`). Wrote the Eval results tables and verdict into this file; updated the A2 block and added
follow-ups to A3 and A5 in `alpha-build-plan.md`.

**`TODO(Ari)` gaps:** all four filled by Ari (so none remain open). `agent_worker/tests`: 170 passed.

**Verification.** All 54 runs completed (16 + 18 + 18 ok; the 2 failures were `InstructorRetryException` on the
old schema). `--compare baseline-32k schema-only after` shows `loaded_context_length: 32768` for all three.
Not run: `make check` end to end (Postgres is down in this environment, as before); `local_test` (plan
Verification 4) — not exercised after the TODOs were filled.

**Where to look hardest.** The scoring definitions behind the headline numbers (`invented_price` counts
`free_admission`, which is why 56 reads as an error rate it isn't); the shared seeds (the White Squirrel seed-2
merge appears in two labels but is one case); Midway's counts (7–36, ground truth unclear); and that the
verdict rests on one small model at N=3.

### Round 5 — Claude Opus 5.5, October 10, 2026 (closing A2)

**Scope.** Closing A2's loose ends so the only thing it waits on is A2.1. Files: `agent_worker/normalize.py` and
`agent_worker/schemas.py` (the PM rule — code); `agent_worker/prompts.py`, `agent_worker/tests/{test_prompts,
test_extraction_schema}.py`, `apps/calendar/lib/{metro,params}.test.ts` (comment tidy, plus the new PM tests);
`docs/arch/{requirements-initial,data-model-initial,arch-initial}.md`; `docs/dev/alpha-build-plan.md`; `docs/dev/notes.md`;
this file (Status, Design › Time normalizer, Decisions for Ari #1–#5, Eval results › Addendum, Refinement strategies:
F2/F9, S1/S11/S12, "S1 look: results", updated order, Start here).

**What changed, and why.**

1. **Decisions for Ari #1–#5 resolved** (Ari, October 10). #1, #4 and #5 accepted as recommended. #2 reversed:
   assume PM. #3 accepted, conditional on a source of truth for the metro's zone, which already exists
   (`metro.timezone`); its second role is now written into the three design docs.
2. **The PM rule, tests first.** Added the accepted cases (`"7:30"` → 19:30, `"7"` → 19:00, `"9:45"`, `"1:00"`,
   `"10"` → 22:00; `"12:30"`, `"10:30"` and `"11:00"` stay as written because a two-digit `HH:MM` is the format the
   schema asks for), moved `"0:30"` and `"13"` into the refused set, and added a test that every time field's
   description says "assume PM". Watched 18 fail, then: `_TWELVE_HOUR`'s meridiem is optional and defaults to PM, the
   24-hour pattern is tried first (so a two-digit `HH:MM` never reaches the 12-hour branch), and the three time
   descriptions gained "(if the page gives no AM/PM, assume PM)". Recorded in `requirements-initial.md` ("Agent
   Extraction: Fields") and `arch-initial.md` §7.
3. **`TODO(Ari)` scaffolding removed** (Ari asked: resolved gaps must not show up when searching for `TODO`). Kept
   each Lesson as an ordinary comment in Ari's own "(Ari) — Lesson:" style; removed the "Code (replace …)" headers,
   the `Check:` blocks, the commented-out `OLD CODE`, the remaining `TODO(Ari)` marker on `_one_show_rule`, the tests'
   "RED until TODO(Ari) #n" notes, and the "TODO(Ari)" in three B2 test section labels (B2's gaps are already filled
   in its sources). Comment-only, checked the repo's way: files snapshotted first; Python syntax trees (docstrings
   stripped) identical before and after for all four `.py` files; the two `.ts` diffs touch only `// ---` comment
   lines. `grep -rn "TODO(Ari)" apps packages` now finds nothing.
4. **The act-splitting regression (F9)** found and written up (Eval results › Addendum): counted from the stored
   results, reproduced by `local_test`. The verdict is amended.
5. **The S1 look** done on the saved pages and recorded ("S1 look: results"), with two strategies added (S11
   temperature, S12 schema-constrained decoding) and an updated suggested order for A2.1.

**Departures.** The PM rule is a behaviour change *after* the measurement: the code now sends a slightly different
schema (one phrase in three time descriptions) than the stored labels did. A2.1 re-baselines anyway (environment
changed, below).

**`TODO(Ari)` gaps:** none open; all four filled by Ari; scaffolding removed as above.

**Verification.**

- `make check` (before the PM change, Postgres up): exit 0 — ruff, turbo lint, mypy, check-types, pytest **236 passed**
  (DB suite included), calendar vitest 94 passed, contract-check current.
- After the PM change, the tidy and every doc edit: `uv run pytest agent_worker/tests` → **197 passed**; `make check` →
  exit 0 (pytest **263 passed** with the DB suite, calendar vitest 94 passed, contract-check current).
- **`local_test` (plan Verification 4), first run since the TODOs were filled:** full graph on White Squirrel completed
  in 165 s, 1 attempt, `confidence` 0.98, `page_readable` true, `/api/ps` context 32768. **12 of 12 shows** with correct
  dates, start times and end times (including Nona's 21:00–00:00 across midnight), `free_admission` null throughout. But
  every show had exactly one act named with the whole listing title — F9. (`reconcile`/`commit` are still
  placeholders, so "end to end" means extraction and validation.)
- **Environment drift, found here:** Ollama is now 0.40.2 (app bundle updated October 10, 06:04); `gemma4-e4b-32k`
  re-created at 07:27 the same day with a new digest (`654af1bf75f4` vs `08aefbf02b7c` in the results files). Not
  caused by this round; recorded in Start here and `notes.md`.

**Where to look hardest.**

1. **The PM change has had no second-model review.** It is small and pinned by tests, but it reverses a reviewed design
   choice; Ari may want a one-round code review before sign-off, or fold it into A2.1's first review.
2. **The `"10:30"` limit.** A two-digit time with no meridiem is trusted as 24-hour; only the description tells the
   model to assume PM before converting. If the model copies a page's "10:30" verbatim, the show lands at 10:30 AM.
   A2.1's labelled pages should include a late listing to measure it.
3. **The F9 hypothesis** (the description lost "name(s)") is untested.
