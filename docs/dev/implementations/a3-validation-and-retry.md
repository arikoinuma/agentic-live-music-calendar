# A3 — validation and retry: making the loop real

**Status:** Done (Ari sign off) - Oct 14, 2026
**Date:** October 12, 2026
**Author model:** Claude Sonnet 5.5
**Reviewer model:** Claude Opus 5.5 (plan review round 1, October 12, 2026; plan review round 2, October 12, 2026; code review round 1, October 12, 2026)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A3 (gaps G2–G6, G25; the A2/A2.1 items it absorbed), `docs/arch/arch-initial.md` §7 ("Validation and retry", the reliability-risk paragraph), `docs/arch/requirements-initial.md` ("Agent Validation", "Agent Extraction: Accuracy Standards", Show › "Times after midnight"), `docs/dev/implementations/a2.1-extraction-reliability.md` (E3, E16, D10, D12, D13; "Deferred explorations"), `docs/references/fastapi-style-guide.md`

## Decisions for Ari (read first)

Thirteen small decisions. Each has a recommendation, and the plan is written *as if every recommendation
is accepted*; if you choose differently, only the named section changes. The two that most change what
gets built are **D1** and **D5**.

| # | Decision | Recommendation | Why, in one line |
|---|---|---|---|
| **D1** | **What escalation covers: the whole page, or just the failing shows.** | **Whole page, all-or-nothing.** | A partial commit corrupts A5's soft delete: shows that failed validation would be missing from the committed set and so be marked `removed`. |
| D2 | A show dated up to 31 days *before* the fetch date is plausible; one more than 31 days past or more than 366 days ahead is an error. | Accept. | Matches A2.1's year rule (`infer_year` keeps dates within 31 days back) and the build plan's "a month past, a year out". Pages do keep last week's shows. |
| D3 | What `is_ambiguous` means now that validation reads it. | **A warning only: "a human may want to look". It never routes.** | A2's eval had it fall to 0, so it can't carry a gate; and the requirements say an unclear lineup order is *expected* (assume list order). |
| D4 | What a **repair** does with a value that fails a verification: drop it (set null), never move or rewrite it. | Drop. | Ari's tiered standard: a missing field is tolerated about 1 in 10, a wrong one never. A misplaced start time is dropped, not moved into `time`. |
| **D5** | **The "larger model" escalation tier.** | Build the mechanism and the setting (`escalation_model_name`, default unset). Until H1 gives a hosted model, tier 3 on the laptop is the *same* model with the full hint, and the audit record says so. | The arch doc's second escalation step needs a model that doesn't fit this laptop (16 GB RAM, 12 GB disk; A2.1 E1). Faking it would make A8 misreport. |
| D6 | Fetch failures (network error, 4xx/5xx) are in A3: transient errors retried with `tenacity` backoff, then a recorded `fetch_error` routes to escalate. | In scope. | G2's crash applies to fetch too, and `arch-initial.md` §7 names it as the other failure mode. Small. |
| D7 | Lower `RequestOptions.max_retries` from 3 to 1. | Lower it. | Measured: 0 parse failures and mean 1.0 attempts in 45 of 45 `a21-confirm` runs. As it stands, one venue can cost 3 × (4 + 4 + 4) = 36 calls, not the "12" the build plan counted. |
| D8 | **Re-mark three [fill-in] bullets as [written]:** the JSON-LD guards, the repairs from A2's eval (image URL, unstated end time, misplaced start), and the non-empty-`acts` check. | Re-mark (see "Why five gaps, not nine"). | No single line in them teaches a concept; they are heuristics and thresholds measured against fixtures. `AGENTS.md` asks for exactly this call. |
| D9 | The confidence signal: the minimum over shows the *model* judged (the JSON-LD route's `1.0` is a placeholder and is ignored), threshold stays 0.8. | Accept; A8 revisits the number. | Build plan A3 "replace the placeholder". |
| D10 | A page that says `page_readable: true, shows: []` but whose visible text mentions three or more calendar dates is **not** a confirmed-empty pass; it fails and retries. | Accept, knowing it will be noisy for a venue that is empty and has dated blog posts. | An empty list is the most dangerous output (A5 would soft-delete everything). The cost of a false alarm is one human look. |
| D11 | Retry-policy settings live on the graph state (`state.policy`), not in a graph factory. | Accept. | The compiled graph stays a singleton; A8 and tests vary a run by passing a different policy. |
| D12 | `image_url` link preservation (G25) ships behind an `ExtractionConfig` switch, off by default, and is adopted only if one gated eval run holds 56/60 with no wrong field. | Accept. | A2.1's protocol: one change per label. Adding text to every page the model reads is exactly the kind of change that moved act splitting before. |
| D13 | **A JSON-LD event dated outside the plausibility window is excluded with a warning, not retried or sent to the model route** (round 2 #1). | Accept. | The date is the source's own and a retry can't change it; the model route's year rule would re-date it into a plausible but wrong date (a date 400 days out becomes next month) and it would pass clean. A visible exclusion beats a silent wrong date. On the model route the same finding stays an error and retries. |

## Context

A2 and A2.1 made *extraction* good enough: the pipeline reads a page and returns shows with typed
fields. What the graph still does around that is a skeleton. `extract_node` has no error handling (G2), so
the failure Phase 5 documented kills the graph before `attempt_count` ever increments. `validate_node` checks
only the model's own confidence and treats an empty page as a failure (G3), never reading `page_readable`.
The three checks `requirements-initial.md` names (completeness, plausibility, internal consistency) don't
exist (G4). A retry repeats the identical call (G5), and at the adopted temperature 0 an identical call is
deterministic: A2.1's `a21-confirm` ran five times with identical output. So the retry loop, as built, can
never help. The router compares `float | None` and returns a different enum than its path map is keyed on
(G6). This milestone is where the "validation approach for agentic outputs" requirement gets answered.

### What A3 delivers

| Piece | Where | Closes |
|---|---|---|
| Errors in the model call become recorded failed attempts; fetch errors become a routed escalation | `nodes.py` | G2, D6 |
| Pure check functions: completeness, plausibility, consistency, repairs, JSON-LD guards; `validate_extraction(...)` returns a `ValidationResult` (outcome, findings, repairs, excluded shows, verdict) | new `validation.py` | G3, G4, E16 |
| One routing signal: the **verdict**, with confidence and findings kept beside it, not folded into a float | `validation.py`, `state.py` | the "collapsing into one float" worry |
| Escalating attempts: tier 1 as adopted; tier 2 narrows with a hint built from what failed (and falls back from JSON-LD to the model route when JSON-LD under-reports); tier 3 is a larger model if one is configured | new `policy.py`, `extraction.py`, `act_split.py` | G5 |
| Named, injectable `RetryPolicy`; a router that cannot hit the `None` or two-enums collisions | `policy.py`, `graph.py`, `constants.py` | G6 |
| Image links survive cleaning behind a switch | `extraction.py` | G25 |
| `max_retries` revisited | `llm.py` | D7 |
| Per-attempt history on the state (what A4 will persist and A8 will measure) | `state.py` | feeds A4, A8 |

### What A3 deliberately does not do

- **No audit writes, no `structlog`, no `agent_run` row, no MongoDB** (A4). The state carries everything A4
  will log (`extraction_source`, `extraction_notes`, `validation`, `attempt_history`, `escalation_reason`), and
  the nodes still `print()` where they did.
- **No reconcile, commit or real escalate writes** (A5, A6). `escalate_node` gains one pure step, composing
  `state.escalation_reason`, and keeps its `print()`.
- **No evaluation of the retry design** (A8). A3 builds the mechanism and records which tier ran and what it
  produced; whether the hint-and-escalate retry *recovers failures or just costs tokens* is A8's question
  and is not assumed answered here.
- **No larger hosted model, no hosted endpoint** (H1). The setting and the tier exist; the model doesn't.
- **No chunking the page into smaller model calls** as a tier-2 narrowing (arch §7 mentions "fewer entries per
  call"). Layouts like Terminal Bar's date-then-lines make a safe split a real design problem (A2.1 E6);
  tier 2 narrows by *instruction* instead. Recorded for A8 if the hint doesn't recover failures.
- **No validation of per-act start times, venue-name mismatch or duplicate shows.** Duplicates are A5's
  tie-break problem (A2.1: 7th St Entry, Oct 31).

### Decisions already made (earlier in this project)

- Validation checks completeness, plausibility, internal consistency; "a show that fails validation is never
  silently dropped — it's always visible somewhere as needing attention" (`requirements-initial.md`).
- Retries capped at 3 attempts; exhausting the cap escalates to human review; each attempt escalates in
  approach, narrowing the task first and a larger model second (`arch-initial.md` §7).
- A retry runs Extract only, against the saved snapshot (`state.page_html`), not a fresh fetch (§7). The
  graph's existing `retry → extract` edge already does this.
- `end_time` earlier than `time` means the next morning (requirements, Show).
- A time before 5:00 AM belongs to the previous night (requirements, Show; `jsonld.NIGHT_CUTOFF`).
- "Wrong is never acceptable; missing is tolerated ~1 in 10" (Accuracy Standards): this is what shapes D4.
- Tests first, always (`alpha-build-plan.md` §3).

## Design

### 1. One verdict, not one float

The build plan asks how a deterministic check failure combines with the model's self-reported confidence
into the routing signal, and warns that "collapsing both into one float may be losing information". The
design answers by not collapsing:

- `validate_node` computes a **`ValidationResult`**: the page's `PageOutcome`, every `Finding` (code,
  severity, show index, message), every `Repair`, the indices of `excluded` shows, and a `verdict`
  (`PASSED`, `CONFIRMED_EMPTY`, `FAILED`) with the ordered **reasons** for a failure.
- `state.confidence` stays a `float | None` and stays in the state, unchanged in meaning from today
  except that it is now `None` where no model judged the record (below). It is an input to the verdict,
  and an input to A8's calibration question. It is not the router's input.
- The router reads the verdict and `attempt_count` only. It never compares a float, so G6's `None`
  comparison cannot happen, and it returns `NodeOutcomes` members only.

**Evidence kinds don't mix.** A deterministic error ("free admission *and* a $15 price") is a fact about the
record, true however sure the model was; confidence 0.99 does not outvote it. Low confidence is a statement
about the model's state of mind, and it only matters when nothing deterministic has failed. So the
precedence is: extraction failed → unreadable page → check errors → low confidence → (empty page: dated-text
contradiction) → pass. The reasons list keeps *all* that apply, strongest first, so the retry hint (§3) and
the audit trail can say why.

### 2. The checks

`validation.py` is pure: no model, no database, no clock (the date comes in as `today`, which the node
takes from `state.fetched_on`, not from the wall clock; `local_test.py` replays an August capture and would
otherwise flag every show as past). Check functions take a show (or the page) and return `Finding`s.

**Page outcome** (G3, Gap B), from `page_readable` and `shows`:

| `page_readable` | `shows` | Outcome | Meaning |
|---|---|---|---|
| true | non-empty | `HAS_SHOWS` | normal |
| true | empty | `CONFIRMED_EMPTY` | the venue lists nothing: a legitimate pass (D10's dated-text contradiction aside) |
| false | any | `UNREADABLE` | a failure worth a retry, even if the model also returned some shows (a model that says "I couldn't read this" shouldn't be trusted on what it then returned) |

**Per-show checks.** Each is a function, so a test can call it alone.

| Check | Rule | Severity | Source of the rule |
|---|---|---|---|
| Completeness | `acts` empty → the show is **excluded** (not a show: "Artists — one or more"; non-music entries arrive this way from both routes by A2's design), recorded in the result, never an error. **Excluded is not "confirmed non-music"** (round 1 #7): in `a21-confirm` the splitter returns `acts: []` for two *real* Mortimer's shows every run (they are the gate's `missed: 2`). So each excluded show also gets a **warning** `excluded_no_acts` carrying its title (from `extraction_notes["no_acts"]`, or its index when notes are absent), so it reaches A4's record and a future review list instead of vanishing | excluded + warning | `requirements-initial.md` Show and Agent Validation ("never silently dropped"); A2 Design "Consequences" |
| Completeness | a title the splitter **left out of its answer** (`extraction_notes["missing_ids"]` non-empty) → error `splitter_dropped`. `split_titles` gives such a title `acts: []`, which would otherwise look exactly like an exclusion (round 1 #8). Retries, with a splitter-only hint ("return every id") | error | `act_split.py` (`missing_ids`) |
| Completeness | an act whose name is blank → error | error | requirements |
| Acts appear in the title (A2.1 E3) | when the verbatim titles are known (`extraction_notes["titles"]` and `len(titles) == len(shows)`; the status merge can add a show and break the alignment, in which case the check is skipped), an act name not contained in its title after `fold_text` → warning `act_not_in_title`. Catches typos and invented names, the one deterministic guard on the 100% field; a warning, not an error, because the splitter legitimately drops parentheticals and "w." markers (round 1 #16) | warning | A2.1 plan, Deferred explorations E3 |
| Plausibility, date | more than 31 days before `fetched_on`, or more than 366 days after → **on the `model` and `image` sources an error (D2); on the `jsonld` source the show is excluded with a warning `date_out_of_window`** carrying its title and date (D13, round 2 #1). The lookback is `normalize.YEAR_LOOKBACK` (renamed from the private `_YEAR_LOOKBACK` in step 5), so the year rule and the check share one number. **What it actually guards:** with the year rule on, `infer_year` already puts every model-route and image-route date in `[fetched_on − 31, fetched_on + 334]`, so the window can only fire there for a Feb 29 in a non-leap year (`infer_year` returns it unchanged and names this check as the backstop). Its main job is the JSON-LD route, whose dates come straight from the source (round 1 #13) | error | build plan A3 (E16); A2.1 D13 |
| Plausibility, start | a start in 05:00–10:59 → warning (live music is "overwhelmingly afternoon and evening"; venues do host brunch music, so not an error) | warning | requirements, Fields |
| Plausibility, end | `end_time` earlier than `time` is **valid** (the next morning); `end_time == time` → a **repair on all sources** (drop `end_time`, record a `Repair`), never an error and never a reason to change route: `jsonld._end_time` accepts a zero-length show and `end_time_is_stated` is satisfied by the stated *start*, so a plugin that writes `endDate == startDate` would otherwise fail every run (round 2 #4; the same family as the misplaced-start repair) | none / repair | requirements, Show; A3 build-plan bullet (White Squirrel "9:00 pm – 12:00 am") |
| Consistency | `free_admission is True` together with `admission_advance` or `admission_day` set → error. Absent prices never imply free (so `None` with no price is fine, and `free_admission is None` with a price is fine) | error | requirements, Show and Validation |
| Image, **repair** | `image_url` not found verbatim in the page → set to `None` and record a `Repair`. "Verbatim" is checked against the unescaped HTML (`html.unescape`) *and* the text sent: an attribute value `a?b=1&amp;c=2` parses to `a?b=1&c=2`, and a naive `in page_html` is false. **Runs on the `model` source only.** Not `jsonld`: the URL came from structured data, not a model, and the eval's `invented_image_urls` aggregate of 225 in `a21-confirm` is all JSON-LD shows checked against cleaned text, a false alarm (CONFIRMED against `a21-confirm.json`: every non-null URL is on a `jsonld` run; none on a model run). Not `image`: an image run has no `page_html` (`state.page_html` is `None`, `page_content` is base64) | repair | build plan A3 (F6) |
| End time, **repair** | on the **`model` source only**, an `end_time` that the page doesn't state (`jsonld.end_time_is_stated`) → `None` + `Repair`. Title-scoped when `extraction_notes["titles"]` aligns with the shows (same rule as `act_not_in_title`), page-wide otherwise: A2.1's own docstring says page-wide lets another listing's "11:00 pm" vouch for a default end (round 1 #14). **Evidence, corrected** (round 1 #6): the model route had **0** invented end times in `a21-confirm`; all 5 were the poster image route (`terminal_bar_show_2.webp`, one per seed), which is the misplaced-start rule below, not this one. This repair is kept as the cheap guard A2.1 D10 gave the JSON-LD route, not because the model route has been seen to need it. A2.1 already does the title-scoped version on the JSON-LD route | repair | A2.1 D10; Accuracy Standards |
| Misplaced start, **repair** | **all sources** (it reads no page): `time is None` and `end_time` set → drop `end_time` + `Repair` (D4: dropped, not moved). A **deliberate widening** of the build-plan bullet, which says "`end_time` equal to a stated start time"; the code can't know what the page states, and an end with no start is rare enough that dropping it costs little | repair | A2 eval, "one case" (the poster image route) |
| Acts with differing start times | a show whose acts carry different `start_time`s → warning `possible_merge` (a lineup with one ticket link and several times is legitimately one show, so never an error). Feeds A5's merge worry | warning | build plan A5 bullet |
| `is_ambiguous` | true → warning (D3) | warning | build plan A3 ("decide what it means") |

**Page-level guards** (E16):

- **JSON-LD under-reporting.** Only when the source is `jsonld`. If the visible text mentions three or more
  distinct (month, day) pairs on which *no extracted show falls*, the structured data lists fewer events than
  the page does → error `jsonld_under_reported`, and the retry falls back to the model route (§3). The pair finder
  is a regex over month names and abbreviations with an optional ordinal. **Only upcoming pairs count**
  (round 1 #20, corrected in round 2 #2): each pair is placed in a year with `normalize.infer_year(…,
  fetched_on)` and **ignored if the result falls before `fetched_on`**, since pages keep past listings and
  posted-on dates (7th St Entry's text has Oct 1–9 against an Oct 10 capture; measured: this rule keeps 20 of
  its 28 pairs). It drops only the *past 31 days*: an archive older than that is placed next year and still
  counts, which is accepted. "No extracted show falls" compares against **all extracted shows' dates**,
  excluded ones included (the JSON-LD did list them). **Checked against the real
  fixtures before writing this plan:** both White Squirrel captures give an empty difference (Oct 10–14 and
  Aug 17–22; 5 and 6 pairs, all matched by a show). The threshold of 3 is a guess measured against exactly
  two real pages, so it is stated as such.
- **Empty but dated** (D10). A page that is `page_readable` but has **no kept shows** (the raw list is empty, *or
  every show was excluded*; round 1 #4) with three or more upcoming dated pairs in the text → error
  `empty_but_dated`. Keyed on kept shows rather than on `CONFIRMED_EMPTY`, so an all-excluded dated page can't
  slip past the guard D10 exists to apply. An all-excluded page with no dates passes: nothing to commit, and
  each excluded show already carries its warning.
- **JSON-LD route: what a failed attempt does next** (round 1 #2, reworked in round 2 #1, #3, #4). On the
  JSON-LD route dates, times and prices come from code, and the page hint has no consumer there (only the act
  splitter calls a model), so a retry whose reasons are not about acts would repeat attempt 1 byte for byte.
  Rule: **an attempt whose route was JSON-LD and that `FAILED` with any reason that isn't `SPLITTER`-targeted
  makes the next attempt fall back to the model route.** That covers `jsonld_under_reported`, `empty_but_dated`
  and `extract_failed` (a deterministic `ValueError` from a malformed `startDate`) and every consistency
  error. It deliberately does **not** cover an out-of-window date (D13: excluded with a warning, because the
  model route's year rule would re-date it into a wrong date that passes) or `end_time == time` (a repair).
  `SPLITTER`-targeted failures (`blank_act_name`, `splitter_dropped`) retry on the JSON-LD route with the
  splitter hint. The route an attempt *used* is recorded on its `AttemptRecord.route` even when the attempt
  fails, so the sticky fallback can see it (§5). If the model route is also bad, the page escalates and the
  escalation reason names both routes. A truly bad source still escalates daily until a person acts: the
  intended "visible somewhere as needing attention", not a loop to engineer away.

**Confidence** (D9): the minimum over the *kept* shows (excluded ones don't count) when the source is `model`
or `image`; `None` for `jsonld` (the `confidence=1.0` the JSON-LD route stamps on each show is a
placeholder, `extraction.py` says so, and is now ignored here), shows the **status merge added** are also
excluded from the minimum (they carry the same placeholder `1.0`; `status_check.apply` records their
positions in its notes as `added_indices`; round 2 #11), and `None` for any page with **no kept shows**
(`min([])` raises, and would do it in `validate_node`, outside Gap A's catch: G2 again one node later;
round 1, finding 4). Threshold in `RetryPolicy`, 0.8 as today. Low confidence adds the `low_confidence` reason only if
`confidence is not None`.

**What the node passes on.** `state.extraction` stays the model's raw output (the audit record). A new
`state.validated_extraction` holds the shows after repairs, with excluded shows removed. Reconcile (A5)
reads *that*. The graph only reaches reconcile on a pass, so it never sees a failing record.

### 3. Escalation: each attempt changes the request

`policy.plan_for_attempt(attempt, policy, history)` (`history` = `state.attempt_history`; each `AttemptRecord` keeps its error findings, §5) returns an `AttemptPlan` (tier name, the
`ExtractionConfig`, the `RequestOptions`, whether a larger model was actually used). `extract_node` calls
it with `attempt = state.attempt_count + 1` and `state.attempt_history`.

| Attempt | Tier | What changes | Basis |
|---|---|---|---|
| 1 | `initial` | nothing: `PIPELINE_CONFIG`, `PIPELINE_OPTIONS`, no hint. The request is byte-identical to today's (a test pins it), so A2.1's 56/60 stays valid | A2.1 |
| 2 | `narrowed` | the hints are set from the *previous attempt's* reasons and findings (e.g. "A show was dated 2026-03-01, more than a month before today (2026-10-12)…", "Check which lines under a date belong to which show"). The hints come from the **error findings of attempt 1**. If any earlier attempt used the JSON-LD route and failed with a non-`SPLITTER` reason (§2), also `route="model"` | arch §7: "narrow the task or address the specific ambiguity in the prompt first" |
| 3 | `larger_model` | hints built from the **union of the error findings of every earlier attempt** (deduplicated by code and message, so attempt 1's reason isn't lost when attempt 2 fails for another), plus `options.model = policy.escalation_model` **if set** (D5). **Every last attempt also adds a sentence of its own** (a conservative "leave a field null rather than guess" to the page model, "never add a name the title doesn't contain" to the splitter), found necessary during the build: when attempt 2 fails the same check as attempt 1 the union of findings is identical text, so with no larger model attempt 3 would otherwise be byte-identical to attempt 2 (see Implementation log, Departures). If unset, the tier still runs with the full hints and the plan records `larger_model_used=False`. **The route fallback is sticky** (round 1 #1): decided from the *whole* history (`any(...)`), not from attempt 2's reasons alone, so an attempt-2 failure for another reason doesn't send attempt 3 back to the JSON-LD route that already under-reported | arch §7: "larger model second" |

**Two hints, aimed at the call that produces the field** (round 1 #5). Each check code carries a target:
`PAGE` (dates, times, prices, `page_readable`, `empty_but_dated`, `low_confidence`, extraction errors) or
`SPLITTER` (`blank_act_name`, `splitter_dropped`, `act_not_in_title` if it ever routes). `retry_hint(history)`
returns `(page_hint, splitter_hint)`, either possibly empty. `ExtractionConfig` gains `retry_hint` (appended
after the page instruction by `instruction_for`) and `splitter_hint` (passed to `split_titles(..., hint="")`).
A date problem therefore can't disturb the act splitter, which A2.1 found to be the most sensitive call
and the source of every remaining gate failure; a test pins that a date-only hint leaves the splitter's
request byte-identical. The plumbing threads `config` into `_from_jsonld` and `_shows_from_listings`, which
don't take it today, **and into the status merge's own splitter call** (the lambda passed to
`status_check.apply`, a third `split_titles` call site; round 2 #11). With both hints empty nothing is appended: the byte-identical test. The hints are built
from the failed findings' own messages and from fixed generic sentences per check code, never from
labelled answers (A2.1's `test_no_prompt_quotes_a_labelled_answer` pattern is extended to the hint builder).

**Why this isn't wishful.** At temperature 0 a retry whose request is unchanged returns the same answer;
the hint is the one thing that changes the input. Whether it also changes the *output* for the better is
what A8's "does the escalating retry recover failures or just cost tokens" measures. The attempt history
(§5) records tier, model, reasons and outcome per attempt so A8 can answer from data.

**Tier 3 caveats stated up front.** `instructor_client` is bound to Ollama's endpoint, so a configured
`escalation_model` must be an Ollama model name until H1 makes endpoints per-call. `Settings` gains
`escalation_model_name: str | None = None`; `.env.example` documents it, commented.

### 4. The graph

```
START → fetch ──ok──────────────► extract → validate ──pass──────► reconcile → commit → END
          │                          ▲          │
          └─fetch_error─► escalate   └──retry───┤
                              ▲                  └─escalate─► escalate → END
```

- `route_after_fetch(state) -> NodeOutcomes`: `ESCALATE` when `state.fetch_error`, else `PASS` (D6).
- `route_after_validate(state) -> NodeOutcomes` is a thin reader of `policy.decide_route(verdict,
  attempt_count, state.policy)`: `PASSED` and `CONFIRMED_EMPTY` → `PASS`; `FAILED` and
  `attempt_count < policy.max_attempts` → `RETRY`; otherwise `ESCALATE`. A `None` verdict (validate never ran)
  raises `ValueError`: a wiring bug should be loud, not routed.
- G6, both halves: the router returns **only** `NodeOutcomes`, annotated `-> NodeOutcomes` (the string
  annotation hid the collision from mypy), and the path map is keyed on the same type. The old
  `return NodeNames.ESCALATE` worked only because `"escalate" == "escalate"` across two `StrEnum`s. A test
  asserts `type(result) is NodeOutcomes` for every branch (a `==` assertion cannot catch it) and a graph-level
  test drives each branch through the real compiled graph.
- Policy lives on the state (D11): `state.policy: RetryPolicy = DEFAULT_POLICY`. LangGraph's own idiom for
  per-run settings is `config["configurable"]`; the state field was chosen because the pipeline's nodes are
  plain functions of `VenueGraphState` and the routers get it for free. If the reviewer prefers
  `configurable`, only `policy.py` and the two routers change.
- Fetch-time retry (D6): `fetch_html` gets a `tenacity` retry (3 attempts, exponential backoff, only for
  `httpx.TransportError` and 5xx `HTTPStatusError`; a 4xx is not transient and isn't retried). A failure
  that survives is caught in `fetch_node` and stored as `state.fetch_error`. `fetch_html` is shared with
  `eval/capture.py`, which gains the retry too (harmless; stated so nobody is surprised).
- **An empty response is a fetch failure** (round 1 #3, refined in round 2 #8; `arch-initial.md` §7 lists
  "empty response" beside network errors). After cleaning, a **text page** (a URL, or a local text file, but
  not an image) whose visible text is empty or whitespace-only becomes `fetch_error = "empty response"` and
  routes to escalate, instead of reaching a model that could answer `page_readable: true, shows: []` on a
  page with no dates, which no later guard would catch. Two refinements: (a) a URL page's empty body is
  **retried by the same `tenacity` policy** (3 attempts, backoff), as §7 says a fetch failure should be; a local
  file isn't retried; (b) a page with **usable JSON-LD events and no visible text** (a script shell) is *not*
  an empty response: `extraction.usable_events(html)` is checked first and the JSON-LD route serves it. A
  local fixture path that doesn't exist is also a `fetch_error` (`OSError`), so a bad path reads the same as
  a bad URL.

### 5. State additions (`state.py`)

All defaulted so `VenueGraphState(**result)` re-wrapping still works.

| Field | Set by | Used for |
|---|---|---|
| `policy: RetryPolicy` | caller (default) | routers, nodes (D11) |
| `extraction_source`, `extraction_notes` | `extract_node` | the JSON-LD guards; A4's audit record (A2.1 E17) |
| `extract_error: str \| None`, `fetch_error: str \| None` | the node that failed | validate's `extract_failed` reason; the escalation reason |
| `last_plan: AttemptPlan \| None` | `extract_node` | the hint, the history |
| `validation: ValidationResult \| None`, `validated_extraction` | `validate_node` | router; A5 |
| `attempt_history: list[AttemptRecord]` | `validate_node` (one per attempt) | A4 persists; A8 measures retry recovery |
| `escalation_reason: str \| None` | `escalate_node` | A6 writes it |

`AttemptRecord`: attempt number, tier, model, **`route`** (the route the attempt *used*: `jsonld`, `model` or
`image`, recorded even when the attempt fails, because `extraction_source` is reset to `None` on a failed
attempt and Gap E's sticky fallback must still see a failed JSON-LD attempt; set from
`extraction.usable_events(html)` and the config *before* the call; round 2 #3), error (if any), verdict,
reasons, the **error findings themselves** (code, target, message, show index: the retry hints are built
from the messages, round 2 #6), confidence, error and warning counts.

**Module layout** (round 2 #5; the import graph is a DAG, so the stubs import cleanly in step 1):
`validation.py` ← `policy.py` ← `state.py` ← `nodes.py` / `graph.py`. `validation.py` owns **all the types**
(`Severity`, `CheckCode`, `Target`, `Finding`, `Repair`, `PageOutcome`, `Verdict`, `FailureReason`,
`ValidationResult`) and the checks; `validate_extraction(...)` returns a `ValidationResult` with the outcome,
findings, repairs, excluded shows and confidence, and **no verdict yet**. `policy.py` imports those types and
owns `RetryPolicy`, `AttemptPlan`, `AttemptRecord`, `combine(result, policy)` (Gap D; returns the result with
`verdict` and `reasons` set, via `dataclasses.replace`), `decide_route` and `plan_for_attempt` (Gap E).
`validate_node` calls both. Gap D therefore lives in `policy.py`, as its section already says. Retries add rows; nothing is overwritten (the same append-only idea as `audit_log`).

**Per-attempt fields are reset at the start of every attempt** (round 1 #15). LangGraph's Pydantic-state update
writes a field only when the node sets it, so a field the node leaves alone keeps its previous value:
without a reset, an attempt-2 success would still carry attempt 1's `extract_error`, and `escalate_node` could
cite an error from two attempts ago. `extract_node` therefore assigns `extract_error`, `extraction_source`,
`extraction_notes`, `last_plan`, `extraction` (to `None` where not produced) on every attempt, and a test asserts
`extract_error is None` after a recovery.

### 6. Failure handling in `extract_node` (G2, Gap A)

The model call is wrapped so that **any** of a defined tuple of expected failures becomes data:
`instructor`'s `InstructorError` (its `InstructorRetryException` is the "re-asked and still invalid" case),
`openai.OpenAIError` (connection, timeout, status), and `ValueError` (which includes pydantic's
`ValidationError`, and covers `jsonld.local_wall_clock`'s `fromisoformat` on a malformed `startDate`).
Verified in the venv: all of these exist, and `InstructorRetryException` derives from `InstructorError`.
Never a bare `Exception` (`apps/api/AGENTS.md`): a `KeyError` or `AttributeError` in our own code is a bug and
should crash. `ValueError` is the broad member: a `ValueError` from our own code (e.g. `zip(strict=True)` in
`_shows_from_listings`) also becomes a "failed attempt". That is accepted deliberately, because it ends in an
escalation with the error text recorded rather than a crash, and the comment beside `EXTRACTION_ERRORS` says
so, the way this paragraph does (round 1 #19). Order matters, and is the lesson: **increment `attempt_count` before the call**, so a failure can't
skip it; record `extract_error`; leave `extraction = None`; return normally. Validate then sees
`extraction is None` and fails with reason `extract_failed`, so the *existing* `retry` edge handles it. No
new edge, no special path.

## Why five gaps, not nine (the [fill-in] marking)

The build plan marks nine A3 bullets [fill-in]. `AGENTS.md` says a [fill-in] task gets 1–3 gaps where the
concept lives, and that if a task has no such line the plan should say so and propose re-marking. Reading
each:

| Build-plan bullet | Verdict |
|---|---|
| Wrap the model call (G2) | **Gap A.** The lesson is real: failure as data, count first. |
| Three outcomes from `page_readable` (G3) | **Gap B.** The truth table above. |
| The three checks, as functions | **Gap C**, on the one check whose rule is subtle: the plausibility date window and the next-morning end time. The completeness and consistency checks are one-line comparisons: written. |
| Combine checks with confidence | **Gap D.** The precedence is the design decision. Includes the router (G6). |
| Escalate each attempt (G5) | **Gap E.** The tier mapping. |
| The router's `None` and enum collision (G6) | Part of Gap D: the router is three lines once the verdict exists. |
| Allow `end_time < time` | Inside Gap C. |
| Image URL, misplaced start, `is_ambiguous` | **Proposed [written] (D8).** A lookup against the page with one escaping gotcha; no concept line. |
| `acts` non-empty | **Proposed [written] (D8).** One condition. |
| JSON-LD guards (E16) | **Proposed [written] (D8).** Heuristics and a threshold measured against fixtures; reading them teaches little that typing them would. |

## Test approach (written first, watched fail, then made green)

Tests state what they prove (`AGENTS.md`): each opens with a `Proves:` comment, sits under a labelled
section, and says where its expected values come from. No test reads its expectation from the code under
test: thresholds in tests are literals with the source named (D2's 31/366 days from the plan; the
verdict table from §1).

**What CI can and can't see (found while resolving round 1).** `agent_worker/eval/fixtures/` and
`agent_worker/eval/results/` are gitignored (`apps/api/.gitignore`), so CI and a fresh clone have neither,
and the existing tests never read them (`test_extraction.py` says so in its docstring). Two layers follow:

- **Committed tests (run in CI) use small synthetic pages written in the fixtures' shapes** — a JSON-LD list
  block with `-05:00` offsets and HTML entities, a date-then-lines text page, an `<img>` with `&amp;` in its
  `src` — and **pinned literals** where a real artefact is the source of truth (below). They are the
  test-first, red-then-green layer.
- **A local real-data check (skipped when the data is absent, and the skip is visible via `-rs`)** in
  `agent_worker/tests/test_validation_on_real_pages.py`: it replays real extractions and fixtures through
  `validate_extraction`. It runs on Ari's machine and in the implementer's `make check`, not in CI. It is
  the answer to round 1 #10 (nothing otherwise checks the new rules against real pages), stated honestly as
  local-only.

The build plan files "unit tests for the validation checks" and "for the routing function" under A7. A3
pulls them forward (tests first), and A7's boxes are ticked from here, the way A2.1 pulled forward A8's
labelling.

### Shared helper: `agent_worker/tests/fakes.py` (new)

`ScriptedClient`: like `test_extraction.FakeCompletions`, but answers from an ordered **script** (each step
is a response, or an exception to raise) and records every call, including `model`. This is the fake client
A7 plans, in the one shape A3 needs. `test_extraction.py` is left untouched.

### 1. `test_validation.py` — the pure checks

Sections: page outcome · completeness · plausibility · consistency · repairs · JSON-LD guards · confidence ·
`validate_extraction` as a whole.

- **Page outcome:** all three rows of the table, plus `page_readable=False` with shows (still `UNREADABLE`).
- **Completeness:** no acts → excluded and *not* an error, the result lists it **and carries an
  `excluded_no_acts` warning with its title** (the "never silently dropped" requirement; round 1 #7); a blank
  act name → error; `missing_ids` in the notes → `splitter_dropped` error, distinct from an exclusion (#8).
  `act_not_in_title` fires on an invented act and not on a parenthetical the splitter removed; it is skipped
  when titles and shows differ in length (E3, #16).
- **All shows excluded** (#4): a dated page whose every show is excluded → `empty_but_dated`; the same page
  with no dates → a pass; confidence is `None` and nothing raises.
- **Plausibility, date:** `fetched_on` 2026-10-12: 2026-09-11 (31 days) passes, 2026-09-10 (32) errors on a
  `model` source and is **excluded with `date_out_of_window`** on a `jsonld` source (D13); 2027-10-13 (366
  days) passes, 2027-10-14 likewise. A leap-day case: the date `infer_year` leaves
  unchanged for a Feb 29 in a non-leap year is exactly what the window catches (the backstop `infer_year`
  names; #13).
- **Plausibility, times:** start 01:00 fine (after midnight); start 07:00 warns; start 21:00 / end 00:00
  (White Squirrel's "Nona") produces **no finding**; end 21:00 / start 21:00 → a repair (end dropped) and no finding, on every source; start None / end 22:00
  → repair (end dropped).
- **Consistency:** free + advance, free + day → error; free with no price fine; price with `free=None` fine.
- **Image:** present in HTML → kept; absent → dropped + a `Repair`; `&amp;` in the page's attribute and `&`
  in the extracted URL → kept (the escaping case); `jsonld` and `image` sources → never checked (the `image`
  case: `page_html` is `None`, and the repair must not crash or drop a poster's URL; #6).
- **Model-route end time:** stated ("8pm – 11pm" in text) → kept; unstated → dropped + `Repair`; a page where
  *another* listing states "11:00 pm" and the show's own title is followed by no time → dropped when titles
  align (title-scoped, #14), kept-by-page-wide otherwise. **Poster (`image`) source:** an end time with a
  start time is **not** touched; a null start with an end → the misplaced-start repair (#6).
- **JSON-LD under-report:** a synthetic JSON-LD page whose text names six upcoming dates and whose events
  cover two → error; one whose extra dates fall in the **31 days** before `fetched_on` (an archive) → no
  finding (#20, #2); one whose extra dates are older than that is placed next year and **does** count;
  one whose dates all match → no finding. The real White Squirrel captures are checked in the local layer
  (their dates are the evidence the threshold was chosen from: Oct 10–14 and Aug 17–22, no extras).
- **Route fallback** (#2, #3): a JSON-LD-route attempt that fails with `empty_but_dated`,
  `jsonld_under_reported`, a consistency error or `extract_failed` is one that falls back; one that fails
  only with `splitter_dropped` / `blank_act_name` isn't; the same findings on a `model` route never trigger it.
- **Empty but dated:** a synthetic text with five dates and `shows=[]` → error; a one-sentence "No events
  scheduled" page → `CONFIRMED_EMPTY` and a pass.
- **Confidence:** min over kept shows; excluded show's low confidence ignored; `jsonld` → `None`; no kept shows → `None`
  (never `min([])`).
- **Warnings** (ambiguous, differing act start times): reported, never change the verdict.

### 2. `test_policy.py` — the verdict, the router, the tiers

- **Verdict precedence** (Gap D): extraction failed beats everything; check errors fail at confidence 0.99;
  low confidence fails only with no errors; `confidence=None` and a clean record → pass; reasons list carries
  all that apply, in order.
- **`decide_route`:** a table of verdict × `attempt_count` 1..3 with cap 3 and also cap 5 (the cap is read from
  the policy, not a literal): pass → `PASS`; failed at 1, 2 → `RETRY`; failed at 3 → `ESCALATE`.
  `type(result) is NodeOutcomes` for every row (G6). Unrun validation (`None`) raises.
- **`plan_for_attempt`:** attempt 1 equals the pipeline config exactly; attempt 2 has a non-empty hint
  built from attempt 1's finding *messages* and the same model; a failed JSON-LD attempt (non-`SPLITTER`
  reason) flips `route` to `"model"`, even though its `source` is `None`; attempt 3's hint carries both attempt
  1's and attempt 2's reasons when they differ; **the fallback is sticky** (round 1 #1): attempt 1 under-reported, attempt 2 failed
  low-confidence → attempt 3 is still `route="model"`; attempt 3 uses `escalation_model` when set, and
  `larger_model_used` is `False` when not.
- **`retry_hint` targets** (#5): a date-only failure yields a page hint and an **empty** splitter hint; a
  `splitter_dropped` failure the reverse. `DEFAULT_POLICY.escalation_model` equals
  `settings.escalation_model_name` (#22).

### 3. `test_extraction.py` additions — the plumbing

- With both hints empty, every route's sent request is byte-identical to today's (model route, JSON-LD
  route's splitter, status question, image route). **Where the expected strings come from** (round 1 #18,
  adjusted for CI; all four requests, round 2 #10): the *first* implementation step, before any code change,
  computes the SHA-256 of today's model-route `instruction_for(PIPELINE_CONFIG)`, `_act_split_instruction()`,
  the image route's `instruction_for(replace(PIPELINE_CONFIG, title_split=False))` and
  `status_check._instruction()`, and pastes them into the test as **literals**, so the expectation can't
  follow a refactor of `prompts.py`. The same step confirms, locally, that they equal the hashes of
  `request.instruction`, `splitter_instruction`, `image_instruction` and `status_instruction` stored in
  `eval/results/a21-review2.json` (the request that scored 56/60), and writes the result in the Implementation
  log. The failing state before the change is the missing `hint` parameter.
- A non-empty page hint reaches the page instruction and nothing else; a non-empty splitter hint reaches the
  splitter's instruction and nothing else; a date-only hint leaves the splitter request byte-identical (#5).
- `clean_text(..., keep_image_urls=True)` (G25): an `<img src>` becomes a `[image: URL]` line at its position;
  `data-src` is used when `src` is a placeholder or absent; a `data:` URI and an `<img>` with no usable source
  produce nothing; HTML entities in the attribute are unescaped; the default (`False`) output is unchanged.
- **The eval's image check** (round 1 #11): `run_eval`'s `invented_image_urls` skips `jsonld`-source runs and
  checks the rest against the unescaped HTML, the same rule as the pipeline's repair; a test builds a result
  set with a JSON-LD URL and a model-route URL, one present and one absent, and counts only the absent one.
- **Status merge** (round 2 #11): `added_indices` lists the shows the merge added; they are excluded from the
  confidence minimum; the splitter hint reaches the merge's splitter call.
- **Fetch** (round 1 #9), `httpx.get` patched (patching `nodes.fetch_html` would bypass `tenacity`) with
  `tenacity`'s wait patched to zero: three 503s → exactly 3 calls, then `fetch_error`; a `ConnectError` is
  retried; a 404 → exactly 1 call, then `fetch_error`; a 503 then a 200 → the page; an empty or
  whitespace-only URL body → retried 3 times, then `fetch_error = "empty response"` (#3); an empty local text
  file → 1 attempt, `fetch_error`; an empty body whose HTML carries usable JSON-LD events → **not** an error
  (#8); a local path that doesn't exist → `fetch_error`.

### 4. `test_graph.py` — the loop through the real compiled graph

Monkeypatch `nodes.instructor_client` with a `ScriptedClient`, read the page from a `tmp_path` file (the
local-fixture branch, no network), pass `fetched_on`. Each test asserts attempts and history as well as the
final node reached.

1. **Happy path** (JSON-LD page, splitter answers): one attempt, reaches reconcile, history has one row.
2. **Model call raises once, then answers** (G2): `attempt_count == 2`, a recorded `extract_failed` row, then pass,
   and `extract_error is None` afterwards (the per-attempt reset; #15). *Red today:* the exception escapes `invoke`.
3. **Model call always raises:** exactly `max_attempts` calls; ends at escalate; `escalation_reason` names the error.
4. **Confirmed empty** (G3): `page_readable=True, shows=[]` on a page with no dates → one attempt, reconcile.
5. **Unreadable twice, then readable:** two retries, recovers; the history shows two `FAILED` rows.
6. **A check error at confidence 0.99 retries** (the precedence, end to end).
7. **A retry sends a different request** (G5): attempt 2's message is not equal to attempt 1's and contains the
   hint; with a policy whose `escalation_model` is set, attempt 3's `model` differs. *This is the test that
   fails if someone reverts to identical re-calls.*
8. **Fetch failure → escalate** (D6): a missing local path and an empty page each end at escalate;
   `extract_node` is never called (the script is empty and asserts no call). The HTTP-level cases are in §3.
9. **JSON-LD under-report falls back to the model route** on attempt 2, and **stays there on attempt 3**
   when attempt 2 fails for another reason (the sticky fallback; #1).
10. **`None` confidence** (a JSON-LD page) doesn't crash the router and can pass.
11. **A stale or far-future JSON-LD event** (a date 400 days out; D13, round 2 #1): one attempt; the show is
    excluded with a `date_out_of_window` warning, the rest pass, and **no retry runs** (the model route would
    have re-dated it).
12. **Every show excluded, page undated** (#4): passes, with `confidence is None`, no exception, and the
    excluded shows listed in `validation`.
13. **A malformed `startDate` in the JSON-LD** (round 2 #3): attempt 1 records `extract_failed` with
    `route="jsonld"`; attempt 2 runs on the model route (a different request, not a byte-identical one).
14. **`endDate == startDate`** (round 2 #4): repaired on attempt 1, the page passes, the JSON-LD route is kept.

### What is *not* covered, stated plainly

- Whether the hint improves a real model's output. That is an A8 measurement; the tests prove the request
  *changes*, not that the answer improves.
- Real HTTP behaviour of `tenacity`'s backoff timing (the tests patch the wait to zero and check call counts).
- The 56/60 score itself: A3 changes no default request (§3's byte-identical test), but the confirmation is
  Verification 5.
- **CI does not run the real-page layer** (the fixtures and results are gitignored). A regression in a check
  that only a real page exposes is caught on a machine that has them, not by CI (see "What CI can and can't see").

### 5. `test_validation_on_real_pages.py` — local only, skipped when the data is absent

Round 1 #10. For each page in "gated plus Terminal" (White Squirrel ×2 captures, 7th St Entry, Mortimer's, which
are gated, and the Terminal Bar captures, which `labels.py` marks `gated=False`; the poster images separately), `validate_extraction` is run over the seed-0 extraction stored in
`eval/results/a21-confirm.json` with that fixture's capture date (`fetched_on`) and the source recorded on the
run. **Expected, from the stored data and the round-1 scratch replay:** verdict `PASSED`; no `error` finding;
the only repair anywhere is the misplaced-start on `terminal_bar_show_2.webp` (time null, end 21:00);
Mortimer's two missed shows appear as `excluded_no_acts` warnings; minimum confidence on model-route pages
≥ 0.8. The expected values are **literals read from the stored results during planning**, not recomputed by the
code under test. Also: the two White Squirrel fixtures give no `jsonld_under_reported`. **What this layer does
**not** exercise on real data** (round 2 #9), so a green result isn't evidence for it: `act_not_in_title` and the
title-scoped end-time repair (7th St Entry's titles don't align with its shows, 29 against 30, and no
model-route show in run 0 has an `end_time`); those rules are covered by the synthetic tests only.

## Implementation steps

Order matters: stubs and tests first, then the pure modules, then the nodes and graph, then the doc edits.
Markings follow "Why five gaps": **[written]** complete; **[fill-in]** scaffold with `TODO(Ari)` blocks (per
`AGENTS.md`, "implement A3" does not fill them).

1. **Stubs and red tests [written].** Create `validation.py` and `policy.py` with the types and the function
   signatures; the bodies `raise NotImplementedError`. Write the four test files and `fakes.py`; run, and
   confirm they fail by assertion (or `NotImplementedError`), not by import error (the B2 lesson). Gap bodies
   stay as `TODO(Ari)` below; the [written] bodies are filled right after.
2. **`validation.py` [written, with Gaps B and C].** Types: `Severity`, `CheckCode` (`StrEnum`), `Finding`,
   `Repair`, `PageOutcome`, `Verdict`, `FailureReason`, `ValidationResult`. Check functions per §2.
   `validate_extraction(extraction, *, source, notes, fetched_on, page_html, page_text)` runs them on the **kept**
   (non-excluded) shows, except the under-report comparison, which uses all extracted shows' dates (round 2 #7),
   and returns the result with **no verdict**; `policy.combine` adds it (§5, module layout). The month-day regex gets a
   why-comment citing the fixtures it was checked against.
3. **`policy.py` [written, with Gaps D and E].** `RetryPolicy` (`confidence_threshold=0.8`, `max_attempts=3`,
   `escalation_model`), `DEFAULT_POLICY = RetryPolicy(escalation_model=settings.escalation_model_name)` (round 1
   #22: so setting the env var changes tier 3), `AttemptPlan`, `AttemptRecord`, `retry_hint(history)` (written complete: fixed sentences
   per code), `combine(...)` (Gap D), `decide_route(...)` (Gap D), `plan_for_attempt(...)` (Gap E).
4. **State [written].** The §5 fields, with a comment on each saying who sets it and who reads it. Update
   `confidence`'s comment: its decided meaning replaces the "open design question" it carries.
5. **Extraction plumbing [written]** (`extraction.py`, `act_split.py`, `llm.py`, `status_check.py`; `prompts.py` untouched):
   `extraction.usable_events(html)` is the routing condition extracted from `extract_page` (Gap C of A2.1,
   filled by Ari) into a public helper that `extract_page` and `extract_node` share, behaviour unchanged and pinned
   by the existing routing tests; `status_check.apply` records `added_indices`;
   `ExtractionConfig.retry_hint`, `splitter_hint` and `keep_image_urls`; `clean_text(..., keep_image_urls)`; `config`
   threaded to `_from_jsonld` / `_shows_from_listings`; `split_titles(..., hint="")`; `request_kwargs` unchanged;
   `RequestOptions.max_retries = 1` (D7) with its comment updated to the measured evidence; `normalize._YEAR_LOOKBACK`
   renamed `YEAR_LOOKBACK` (it is now shared with `validation.py`, and only `normalize.py` uses it today). Eval harness:
   the hints are not exposed (retries are pipeline-only); add `--image-urls` for the G25 rung, **and make
   `invented_image_urls` source-aware** (skip `jsonld` runs, check the rest against the unescaped HTML, the
   pipeline's rule) so D12's adopt-or-reject rule reads a meaningful number (round 1 #11). **Before touching any
   code in this step, pin today's request hashes** (test approach §3).
6. **`extract_node` [fill-in, Gap A]** around the call; resets the per-attempt fields, stores
   `extraction_source`/`extraction_notes`, `last_plan`. **`fetch_node` / `fetch_html` [written]**: the `tenacity`
   retry, `fetch_error`, and the empty-response rule.
7. **`validate_node` [written]:** `fetched_on` from state, calls `validate_extraction`, stores
   `validation`, `validated_extraction`, `confidence`, appends the `AttemptRecord`.
8. **`escalate_node` [written, minimal]:** composes `escalation_reason` from `fetch_error` / `extract_error` /
   the failed verdict's reasons and findings; keeps its `print()`.
9. **`graph.py` and `constants.py` [written]** (round 1 #17: no `TODO(Ari)` block here; Gap D's lesson is
   entirely in `policy.py`, and the routers are three-line readers of `decide_route`): the two routers, the
   second conditional edge, path maps keyed on `NodeOutcomes`; remove the stale shape-to-follow comment block
   that describes the old router. `NodeNames.ESCALATE` is no longer returned by any router.
10. **`Settings.escalation_model_name`** and `.env.example` [written].
11. **G25 measurement [written, run by the implementer or Ari]:** one gated eval run with `--image-urls` (label
    `a3-image-urls`), recorded under the plan's Implementation log. The switch stays off unless D12's rule holds.
12. **Docs [written]:** see "Docs and bookkeeping".

### TODO(Ari) gaps

**The `Code` pasted in each gap's scaffold comment is authoritative.** The sketches below are the approved plan's; where the scaffold differs (Gap C returns a `PlausibilityFlags`; Gap D is split across `combine` and `decide_route`; Gap E adds `final=attempt >= 3` and uses a `route_falls_back` helper; Gap A's scaffold keeps today's unguarded call so the happy path still runs) the Implementation log lists it under Departures.

Each has Lesson / Code / Check. All sit in pure functions with tests, except Gap A's graph-level check.

- **Gap A — the model call as a recorded attempt, `extract_node` in `nodes.py`** (step 6; G2).
  *Lesson:* a failed model call is an **outcome**, not a crash. The retry loop was built to handle exactly
  this failure and could never fire, because the exception skipped the increment and killed the graph
  (`alpha-build-plan.md` G2; `arch-initial.md` §7). Two things carry it: count the attempt *before* the
  call, and catch a *named tuple* of expected errors rather than `Exception`.
  *Code:* `state.attempt_count += 1` before the call; then
  `try: result = ... ; state.extraction = result.extraction; ...  except EXTRACTION_ERRORS as err: state.extraction = None; state.extract_error = f"{type(err).__name__}: {err}"`.
  `EXTRACTION_ERRORS = (InstructorError, OpenAIError, ValueError)` is defined above, with the reason for each member.
  *Check:* `test_graph.py::test_model_call_raises_once_then_answers` and `::test_model_call_always_raises`.
  Likeliest mistake: incrementing *after* the call and outside any `try`, which is today's code (an exception
  skips it), or catching `Exception` (hides a typo in our own code as a "failed attempt"). `ValueError` is the
  broad member of the tuple on purpose; say so in its comment.
- **Gap B — `classify_page` in `validation.py`** (step 2; G3).
  *Lesson:* the three outcomes the `page_readable` field exists for: a confirmed-empty page is a *pass*, an
  unreadable one a *failure*, and unreadable wins even when shows came back (`schemas.py`'s own comment:
  without this validate "would have no way to tell those two apart").
  *Code:* `if not extraction.page_readable: return PageOutcome.UNREADABLE`, then
  `return PageOutcome.HAS_SHOWS if extraction.shows else PageOutcome.CONFIRMED_EMPTY`.
  *Check:* `test_validation.py -k page_outcome`. Likeliest mistake: testing `shows` first, so an unreadable
  page that returned a stray show reads as normal.
- **Gap C — the date window and the next-morning end time, `check_plausibility` in `validation.py`** (step 2; G4).
  *Lesson:* plausibility is relative to *when the page was fetched* and to the *venue's night*, not to the
  data alone. The window is `fetched_on − 31 days … fetched_on + 366 days` (D2, sharing `YEAR_LOOKBACK`);
  and an `end_time` earlier than `time` is **not** a finding, because "9:00 pm – 12:00 am" ends the next
  morning (`requirements-initial.md`, Show). A naive `end <= start` check flags a correct record. (Be honest
  about reach: with the year rule on, the window mainly guards the JSON-LD route and a Feb 29 that
  `infer_year` leaves unchanged; §2.)
  *Code:* `earliest = fetched_on - YEAR_LOOKBACK; latest = fetched_on + datetime.timedelta(days=366)`;
  `if not earliest <= show.date <= latest: finding(DATE_IMPLAUSIBLE)`; and for the end,
  `if show.time is not None and show.end_time == show.time: repair(end_time)` (a `Repair`, not a finding; note: `<` is never tested). On the `jsonld` source an out-of-window show is excluded with `date_out_of_window` instead of a `date_implausible` error (D13).
  *Check:* `test_validation.py -k plausibility` — the 31/32 and 366/367 boundaries and the "Nona" case.
  Likeliest mistake: `show.end_time < show.time` as an error; or measuring against `datetime.date.today()`,
  which fails every test of a replayed capture.
- **Gap D — the verdict and the router, `combine` and `decide_route` in `policy.py`** (step 3; the combination
  bullet, G6).
  *Lesson:* a deterministic error and a model's self-reported confidence are different *kinds* of evidence, so
  the router gets a **verdict**, not a float: errors fail whatever the confidence; low confidence fails only
  when nothing else has; `None` confidence is "no evidence", not zero. And the router returns only
  `NodeOutcomes` (G6): `StrEnum`s of different types with the same string compare equal, which is how the old
  code worked by accident (§4).
  *Code:* `reasons = [r for r in ordered_reasons if applies(r)]`;
  `verdict = FAILED if reasons else (CONFIRMED_EMPTY if outcome is CONFIRMED_EMPTY else PASSED)`;
  and `decide_route`: `if verdict is not FAILED: return NodeOutcomes.PASS`;
  `return NodeOutcomes.RETRY if attempt_count < policy.max_attempts else NodeOutcomes.ESCALATE`.
  `low_confidence` applies only when `confidence is not None and confidence < policy.confidence_threshold`.
  *Check:* `test_policy.py -k "verdict or route"`; `test_graph.py::test_a_check_error_at_high_confidence_retries`.
  Likeliest mistakes: `confidence < threshold` with `confidence is None` (a `TypeError`, the original G6), a
  literal `3` instead of `policy.max_attempts`, returning `NodeNames.ESCALATE`.
- **Gap E — the tier mapping, `plan_for_attempt` in `policy.py`** (step 3; G5).
  *Lesson:* a retry must change the request or it is a loop, and at temperature 0 an identical call returns an
  identical answer (A2.1's `a21-confirm` ran five times with byte-identical output). `arch-initial.md` §7 gives
  the order: narrow the task or name the ambiguity first, a larger model second.
  *Code:* `if attempt <= 1: return AttemptPlan("initial", base_config, base_options)`; otherwise
  `page_hint, splitter_hint = retry_hint(history)` (attempt 1's error findings for tier 2; the union of every earlier
  attempt's for tier 3);
  `fell_back = any(r.route == "jsonld" and any(f.target is not Target.SPLITTER for f in r.findings) for r in history)` (the whole
  history, so the fallback is **sticky**, and `route` is recorded even when the attempt failed);
  `config = replace(base_config, retry_hint=page_hint, splitter_hint=splitter_hint, route="model" if fell_back else base_config.route)`;
  then `if attempt >= 3 and policy.escalation_model: options = replace(base_options, model=policy.escalation_model); tier = "larger_model"` else
  `tier = "narrowed"` (or `"larger_model"` with `larger_model_used=False` at attempt 3).
  *Check:* `test_policy.py -k plan`; `test_graph.py::test_a_retry_sends_a_different_request`. Likeliest mistake:
  setting the hint on `options` (a dataclass that never reaches the prompt), escalating the model at attempt 2, or
  deciding the route fallback from the *previous* attempt only, which un-falls-back at attempt 3 (round 1 #1), or
  keying it on `r.source`, which is `None` for a failed attempt (round 2 #3).

## Critical files

- **New:** `apps/api/agent_worker/validation.py`, `policy.py`;
  `agent_worker/tests/{fakes,test_validation,test_policy,test_graph,test_validation_on_real_pages}.py`
- **Modified:** `agent_worker/{nodes,graph,state,constants,extraction,act_split,llm,status_check,normalize}.py`, `agent_worker/tests/test_extraction.py`
  (additions only), `agent_worker/eval/run_eval.py` (`--image-urls`), `agent_worker/local_test.py` (print the
  verdict and history), `app/config.py` (`escalation_model_name`), `apps/api/.env.example`
- **Docs:** `docs/dev/alpha-build-plan.md` (tick A3; mark the A7 items pulled forward; G2–G6, G25; re-marks per D8),
  `docs/arch/arch-initial.md` §7 (verdict, tiers, fetch retry: where the reasoning lives),
  `docs/arch/requirements-initial.md` "Agent Validation" (excluded vs error; recent-past; `is_ambiguous`),
  `apps/api/AGENTS.md` (the G-list pointer), `docs/dev/notes.md` (if a real surprise turns up: candidates are the
  `&amp;` image check and the `InstructorRetryException` hierarchy)
- **Reused as-is:** `prompts.py`, `schemas.py`, `status_check.py`, `normalize.py` (`fold_text`; `YEAR_LOOKBACK` after its rename),
  `sources/jsonld.py` (`end_time_is_stated`, `find_events`, `to_structured_show`), the eval scorer

## Docs and bookkeeping

- Tick A3 in `alpha-build-plan.md`; note which bullets were re-marked [written] and why (D8); update G2–G6
  and G25 with "closed in A3"; in A7, tick "unit tests for the validation checks" and "for the routing
  function" with "(done in A3)" and note `fakes.py` as the first piece of the fake client.
- `arch-initial.md` §7: add a short paragraph after "Validation and retry" recording the verdict design, the
  three tiers and D5's honesty about tier 3 locally. "When a design decision gets made, record it where the
  surrounding reasoning lives."
- `requirements-initial.md` "Agent Validation": one note on what happens to a show with no acts (excluded and
  reported with a warning, not failed, and **excluded does not mean confirmed non-music**: the splitter
  returns `acts: []` for real shows too), to a recently-past date, and what `is_ambiguous` means.
- Hand-offs written into the plan's log for later milestones: **A4** persists `attempt_history`,
  `extraction_notes` and `validation`; **A5** reads `validated_extraction`, and must decide whether a
  confirmed-empty page may soft-delete every stored show of a venue (the blast-radius question this plan routes
  to `PASS` because the requirements call an empty calendar legitimate); **A5/A6** need a review surface for
  `excluded_no_acts` titles, since a real show the splitter left empty is soft-deleted on the next run
  without anyone being told (round 1 #7); **A6** resolves relative image URLs against the venue URL; **A8** answers the retry-recovery and 0.8/3 questions from `attempt_history`.

## Verification

1. **Tests first:** the new test files and the `test_extraction.py` additions written, run, and confirmed
   failing for the right reason before any implementation. The local real-page file is run too, and is
   expected to go green once the checks exist (it asserts what the round-1 replay found).
2. `make check` green (ruff, mypy `app/`, pytest with the DB tests required, vitest, contract-check). The files
   A3 writes or rewrites are additionally type-checked: `uv run mypy --follow-imports=silent
   agent_worker/validation.py agent_worker/policy.py agent_worker/graph.py agent_worker/nodes.py
   agent_worker/state.py agent_worker/constants.py` reports **no issues** (round 1 #12). Today `graph.py` and
   `nodes.py` report 4 errors, including `graph.py:90`, G6's `float <= None`; clearing them is part of this
   milestone. `make check` itself still scopes mypy to `app/` until A7.
3. **`local_test.py`** against the White Squirrel capture still runs end to end through the real Ollama model
   and prints a `PASSED` verdict, one attempt, `source: jsonld`.
4. **The loop on a real failure.** With Ollama stopped, `local_test` (it reads the fixed White Squirrel
   *fixture*, so there is no fetch error to see) makes the splitter's attempts and ends at escalate with an
   `APIConnectionError` or `InstructorRetryException` reason in `escalation_reason`, instead of a traceback. The
   fetch-failure path is covered by the §3 HTTP-level tests.
5. **No regression in extraction:** `eval/run_eval.py` under label `a3-confirm` on the gated pages returns the
   A2.1 result (56 of 60, no invented show, no wrong field). A first attempt's request messages are
   unchanged by construction (the pinned-hash test); D7 changes only the instructor re-ask budget
   (`max_retries`), which a run with no parse failures never reaches. This run is the check that the tests
   aren't wrong about that.
6. **G25:** one gated run with `--image-urls`, label `a3-image-urls`. D12's rule: adopt only if still 56/60
   with no wrong field and at least one model-route show gets a verbatim image URL; otherwise leave off and
   record the numbers. The result goes in the Implementation log either way.
7. **Visual check by Ari:** read one `local_test_output.json` including `validation` and `attempt_history`,
   and check the plain-English reasons are ones a person would act on.

## Not doing in A3

Audit writes, `structlog`, MongoDB, the `agent_run` row (A4); reconcile, commit, real escalation writes (A5,
A6); chunked-page retries; a hosted or larger model (H1); exposing the policy in the eval harness beyond what A8
needs; per-act start-time validation; duplicate-show detection; relative-URL resolution (A6).

## Plan review

### Round 1 — Claude Opus 5.5, October 12, 2026

**Scope:** the plan body above (Decisions D1–D12, Design §1–§6, the five gaps, test approach, steps,
verification), checked cold against the docs it cites and the code at `b445e6f`.

**What was checked and how.** Read `AGENTS.md`, `apps/api/AGENTS.md`, the FastAPI style guide's
Anti-patterns table, build plan §1.3 (G2–G6, G25) and §5 A3/A5/A7/A8, `arch-initial.md` §7 ("Validation
and retry", the reliability-risk paragraph), `requirements-initial.md` (Show, "Agent Extraction: Fields",
Accuracy Standards, Agent Validation), A2.1's "Deferred explorations" (E3, E16, E17), and the code the plan
changes: `nodes.py`, `graph.py`, `state.py`, `constants.py`, `extraction.py`, `act_split.py`, `llm.py`,
`normalize.py`, `sources/jsonld.py`, `eval/run_eval.py`, `app/config.py`. Experiments, all read-only (scratch
scripts in the session scratchpad, no worktree needed, nothing in the repo touched):

- Instructor 1.15.4: `InstructorRetryException.__mro__` is `(InstructorRetryException, InstructorError,
  Exception, …)`; `pydantic.ValidationError` subclasses `ValueError`; instructor v2's retry is
  `stop_after_attempt(max_retries + 1)`, so `max_retries=3` is 4 attempts and `1` is 2. The plan's claims
  hold (CONFIRMED).
- `a21-confirm.json` aggregate: 45 runs, `mean_attempts_used` 1.0, `parse_failures` 0,
  `is_ambiguous_true` 0, `invented_image_urls` 225 (D3, D7 evidence CONFIRMED). Per run,
  `invented_end_time` is nonzero only on `terminal_bar_show_2.webp`, the **image** route (see #6).
- Re-implemented the month/day pair finder in a scratch script over `clean_text(html, False)` of every
  fixture: White Squirrel Oct 10 (5 pairs) and Aug 17 (6 pairs) both give an empty difference against
  `to_structured_show` dates, as the plan says (CONFIRMED); Mortimer's text has 17 pairs (so D10's
  Mortimer's test will fire, CONFIRMED); the archived Zhora JSON-LD page has 0.
- Replayed the planned per-show checks (date window from the capture date, end == start, null start with
  an end, free + price, blank act name, 05:00–10:59 start, differing act times, model-route image URL) over
  the seed-0 extraction of every fixture in `a21-confirm.json`: **no error-level finding on any gated page**;
  the only hit is the misplaced-start rule on `terminal_bar_show_2.webp` (time null, end 21:00). Minimum
  kept-show confidence on model-route pages is 0.95, above 0.8.
- Mortimer's in `a21-confirm`: `missed: 2` per run, and `notes.no_acts` contains "Flange August Back to Back"
  and "Boss's Daughter (Reno)" — real shows the splitter returned with `acts: []` (see #7).
- `a21-review2.json` stores the exact `instruction` and `splitter_instruction`; both are `==` to today's
  `instruction_for(PIPELINE_CONFIG)` and `_act_split_instruction()` (see #18).
- LangGraph 1.2.11 `_internal/_fields.get_update_as_tuples`: a Pydantic node output writes every field
  whose value is non-`None`, whose default is non-`None`, or that is in `model_fields_set`; a field left
  untouched by a node keeps its previous channel value (see #19).
- `uv run mypy --follow-imports=silent agent_worker/normalize.py` passes (Verification 2's command works);
  the same on `graph.py nodes.py` reports 4 errors today, including `graph.py:90` "Unsupported operand
  types for <= (float and None)", i.e. G6 (see #12).
- `tenacity` 9.1.4 is already a dependency (`pyproject.toml`).

**Counts:** 0 blocker, 12 should-fix, 10 nit. **Verdict: proceed after fixes.** The design (verdict
instead of a float, failures as data, policy on the state, pure checks) is sound and well argued, and the
gaps sit where the concepts live. The should-fix items are mostly places where a real page, as the
fixtures show it, takes a path the plan doesn't describe: a route fallback that undoes itself on attempt 3,
retries that can't change a JSON-LD answer, empty pages that pass, and real shows that are dropped without
anyone being told.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **The JSON-LD → model fallback is not sticky.** Gap E sets `route="model" if UNDER_REPORTED in reasons else base_config.route`, where the reasons are the *previous* attempt's. Attempt 2 runs on the model route, so its result can't contain `jsonld_under_reported`. If attempt 2 fails for any other reason, attempt 3 is back on `route="auto"`, the JSON-LD route, and under-reports again. Fix: carry the route forward from `state.last_plan` (once a run has fallen back it stays fallen back), or decide from the whole `attempt_history` instead of only the previous attempt. Add a `test_policy` row: attempt 1 under-reported, attempt 2 failed low-confidence → attempt 3 is still `route="model"`. | Plan, Gap E *Code*; §3 table row 2 (CONFIRMED by reading) | The tier-3 attempt, the last before escalation, re-runs the extraction that was already known to under-report. The page escalates with an incomplete record, and the history makes it look as though the fallback was tried. | **Fixed.** §3 table row 3 and Gap E: the route fallback is decided from the whole `attempt_history` (`any(...)`), so it is sticky; `AttemptRecord` gains the finding codes it reads; `test_policy` row (under-report → low-confidence → attempt 3 still `model`) and `test_graph` #9 extended. |
| 2 | should-fix | **On the JSON-LD route, a retry can't change most failures.** There, dates, times, prices and end times come from code (`to_structured_show`), and the hint only reaches the act splitter. So a `date_implausible` or `end_equals_start` finding on a JSON-LD show will repeat identically on attempts 2 and 3. Because of D1 (whole page, all or nothing), one stale or far-future event in a venue's JSON-LD then escalates that venue on **every daily run**, forever, after three wasted attempts each time. The plan should decide this explicitly. Options: (a) a finding on a code-derived field on the JSON-LD route also falls back to `route="model"`; (b) it escalates at once, since no retry can help; (c) it excludes and records that one show instead of failing the page, which is safe for A5 when the date is outside any window A5 would soft-delete in. | §3 table; D1; `extraction._from_jsonld` (only `act_split.split_titles` sees a model) (PLAUSIBLE: no fixture has such an event; the mechanism is CONFIRMED by reading) | Each daily run costs three attempts and produces a permanent escalation that no retry could fix, and the venue's calendar never updates. That is the "costs tokens without recovering" outcome A8 is meant to measure, built in from the start. | **Fixed (option a).** New "JSON-LD route: findings on code-derived fields" guard in §2 and `ROUTE_FALLBACK_CODES`: a check error on a field code derives makes the next attempt fall back to the model route, which re-reads the page text independently. A truly bad source still escalates daily, stated as intended. Tests: `test_validation` route-fallback rows; `test_graph` #11. |
| 3 | should-fix | **An empty HTTP 200 becomes a confirmed-empty pass.** `arch-initial.md` §7 lists "empty response" next to network errors as a *fetch* failure. The plan's D6 covers only `TransportError` and 5xx. An empty or near-empty body reaches the model, which can answer `page_readable: true, shows: []`; there are no dates in the text, so D10's guard can't fire, and the verdict is `CONFIRMED_EMPTY` → `PASS`. Fix: in `fetch_node`, treat an empty (or whitespace-only) `clean_text` as a `fetch_error`, and add a `test_graph` case for it. | `arch-initial.md` §7 "A **fetch failure** (network error, empty response)…"; plan D6, §4 last bullet (CONFIRMED against the doc; outcome PLAUSIBLE) | This is the exact blast-radius case D1 and D10 were written to prevent. Once A5 lands, a blank response soft-deletes the venue's whole calendar. | **Fixed.** §4: an empty or whitespace-only cleaned page, and a missing local path, are `fetch_error`s and route to escalate. Tests in §3 (HTTP-level) and `test_graph` #8. |
| 4 | should-fix | **The plan doesn't say what happens when every returned show is excluded.** The outcome comes from the raw `shows` (`HAS_SHOWS`), but `validated_extraction` is empty. Two problems follow. (a) D10's `empty_but_dated` guard is keyed on `CONFIRMED_EMPTY`, so it doesn't run, and an all-excluded dated page passes with nothing to commit. That is the same danger D10 names. (b) "Confidence = minimum over kept shows" is `min([])`, which raises `ValueError` inside `validate_node`, outside Gap A's catch, and crashes the graph (G2 again, one node later). Fix: classify on the *kept* shows for the empty-page guard (zero kept counts as empty for D10), define confidence as `None` when none are kept, and add a test for each. | §2 page-outcome table; §2 "Confidence"; D10 (CONFIRMED by reading; Mortimer's already excludes 13 of 18 per run in `a21-confirm`, so a page that excludes everything is not far-fetched) | A page whose shows were all excluded passes without the guard D10 exists to apply, or the graph crashes in validate. | **Fixed.** The empty-page guard (`empty_but_dated`) is keyed on *no kept shows*, not on `CONFIRMED_EMPTY`; confidence is `None` when none are kept (never `min([])`). §2 guards and Confidence; tests in `test_validation` ("All shows excluded", Confidence) and `test_graph` #12. |
| 5 | should-fix | **The hint goes to both calls whatever it is about.** §3 appends one hint to the page instruction *and* the splitter instruction. A date or price sentence sent to the act splitter can't help (the splitter sees only titles), and it changes the splitter's input, which A2.1 found to be the most sensitive call (every remaining gate failure is an act error). The reverse also holds: an act-level finding sent to the page model on the title-split route is noise. Fix: route each check code's sentence to the call that produces that field (acts and blank names → splitter; dates, times, prices, `page_readable`, D10 → page model), and test that a date-only hint leaves the splitter's request byte-identical. | §3 "The hint is appended after the instruction… and to the act splitter's instruction"; A2.1 sign-off, "the gate fails on four act names" (PLAUSIBLE) | A retry for a date problem can disturb act splitting that was correct, turning a recoverable failure into a wrong act. Wrong acts are the field held to 100%. | **Fixed.** §3: two hints, each aimed at the call that produces the field (`retry_hint` for the page model, `splitter_hint` for `split_titles`); `ExtractionConfig` gains both; tests pin that a date-only hint leaves the splitter request byte-identical, and the reverse. |
| 6 | should-fix | **The end-time evidence is attributed to the wrong route, and the image route's repairs are unspecified.** The plan says the model route had "5 [invented end times] in `a21-confirm`". All 5 are on `terminal_bar_show_2.webp`, the **image** route, one per seed (time null, end 21:00). The model route had **0**. That case is the misplaced-start rule, not the page-text end-time repair. Separately, the image and end-time repairs read `page_html` / page text, and an image run has neither (`page_html` is `None`, `page_content` is base64). The plan should say per source which repairs run: misplaced start on all routes; image-URL and end-time-stated on `model` only, explicitly not `image`. Otherwise an implementer who writes `source != "jsonld"` drops every poster's end time. Also, the misplaced-start rule as written ("`time is None` and `end_time` set → drop") is broader than the build-plan bullet ("`end_time` equal to a stated start time"). That is fine under D4, but say it is a deliberate widening. | `a21-confirm.json` runs: `invented_end_time` nonzero only for `terminal_bar_show_2.webp` seeds 0–4; `run_eval.py:303` (CONFIRMED) | The plan justifies a repair with evidence it doesn't have, and leaves a source condition open whose likely misreading wrongly drops poster end times. | **Fixed.** §2 repair rows corrected: the 5 invented end times were the poster image route (the misplaced-start rule), the model route had 0; each repair states which sources it runs on (image-URL and end-time-stated: `model` only; misplaced start: all); the misplaced-start widening is called deliberate. Test rows added for the `image` source. |
| 7 | should-fix | **Real shows are excluded as "no acts" every run today, and the plan treats that as never needing attention.** On Mortimer's, the splitter returns `acts: []` for "Flange August Back to Back" and "Boss's Daughter (Reno)", the two shows the gate counts as `missed`. Under §2 they are excluded, recorded only in `validation.excluded`, and the page passes. The requirements say a failing show is "always visible somewhere as needing attention", and "when in doubt, include it" says a missed real show is the worse error. The plan's rationale ("non-music entries arrive this way by design") covers only half of what arrives this way. At minimum: add a warning finding per excluded show carrying its title (from `extraction_notes["no_acts"]`) so it reaches A4's record and a future review list, say in the requirements note that excluded ≠ confirmed non-music, and hand off to A6 that excluded titles need a human-review surface. | `a21-confirm.json` Mortimer's seed 0: `label_score.missed = 2`; `notes.no_acts` lists both titles (CONFIRMED); `requirements-initial.md` Agent Validation, Accuracy Standards | The pipeline drops real shows on every run with no signal. Once A5 lands, a show that was stored earlier (by a human, or by a run that got it right) is soft-deleted without anyone being told. | **Fixed.** Each excluded show also gets an `excluded_no_acts` warning with its title; §2 says excluded ≠ confirmed non-music; the requirements note and the A5/A6 review-surface hand-off are in "Docs and bookkeeping". The local real-page test expects Mortimer's two as warnings. Not made an error: that would escalate Mortimer's every day over a splitter limit already known and deferred to H1. |
| 8 | should-fix | **A dropped splitter answer looks the same as a non-music exclusion.** `split_titles` gives a title the model left out of its answer `acts: []` and records its index in `missing_ids`. Validation would then exclude it silently. This signal is deterministic and already in `extraction_notes`. Fix: `missing_ids` non-empty → an error finding (`splitter_dropped`), which retries and suits a hint ("return every id"). | `act_split.py:107-112`; `extraction.py:212-214,252-254` (CONFIRMED by reading; 0 occurrences in `a21-confirm`) | A model that skips one item drops a real show without any trace in the verdict. This is cheap to catch now. | **Fixed.** New error `splitter_dropped` from `extraction_notes["missing_ids"]`, distinct from an exclusion; splitter-targeted hint; test row. |
| 9 | should-fix | **The tests don't cover fetch retries or fetch-failure classification.** D6 adds `tenacity` to `fetch_html`: 3 attempts, `TransportError` and 5xx only, 4xx not retried. But no test file lists a test for it. The only mention is under "not covered", which says "the test patches the wait to zero and checks the attempt count", for a test that doesn't appear in §1–§4. `test_graph` #8 also doesn't say how the fetch is made to fail. Patching `nodes.fetch_html` bypasses tenacity entirely; patching `httpx.get` doesn't. Add to the test approach: 5xx ×3 → 3 calls then `fetch_error`; `ConnectError` → retried; 404 → 1 call then `fetch_error`; a local fixture path that doesn't exist → (decide: `fetch_error` or crash). Also note that `fetch_html` is shared with `eval/capture.py`, which gains the retry too. | Plan §4 last bullet, "What is not covered" bullet 2, `test_graph` #8; `nodes.py:34-46` (CONFIRMED by reading) | A [written] behavior with a real branch (which statuses retry) ships without the test-first coverage build plan §3 requires. A 4xx being retried, or tenacity being bypassed, would go unnoticed. | **Fixed.** §3 "Fetch" tests added (patching `httpx.get`, wait patched to zero): 3×503 → 3 calls; `ConnectError` retried; 404 → 1 call; 503-then-200; empty body; missing local path. `eval/capture.py` sharing `fetch_html` noted in §4. |
| 10 | should-fix | **Nothing checks the new validation against real extractions.** The eval harness calls `extract_page`, not the graph, so Verification 5 (`a3-confirm`) can't see A3's findings or repairs. A check that misfires on a real gated page (an error that escalates White Squirrel every day, or a repair that drops a correct value) would reach `make check` green. The stored extractions in `a21-confirm.json` plus the fixtures make this cheap with no model needed. Add a test, or a step in Verification, that runs `validate_extraction` over each gated page's saved extraction with its capture date and asserts `PASSED` with no repair other than those expected. My scratch replay of the per-show rules found none on gated pages, so this should go green and then stay that way. | `run_eval.py` never imports validation; `a21-confirm.json` `runs[].extraction` (CONFIRMED) | False positives on the pages A3 is meant to serve are found only when `local_test` or production escalates. That is the regression the 56/60 gate can't detect. | **Fixed, with a limit the review didn't see.** `agent_worker/eval/fixtures/` and `eval/results/` are gitignored, so CI has neither. Added `test_validation_on_real_pages.py` (§5), local-only and skipped when the data is absent, with expectations taken from the stored results. The committed tests use synthetic pages. The plan says plainly that CI does not run the real-page layer. |
| 11 | should-fix | **G25's eval half is missing, so D12's adoption rule can't be evaluated.** The build-plan bullet asks for the eval's verbatim-URL check to "score it". Today `run_eval.py:308` checks against cleaned text, so every JSON-LD URL is "invented" (225 in `a21-confirm`). D12 adopts `--image-urls` only with "no wrong field", and the plan neither fixes the scorer nor says whether `invented_image_urls` counts. Fix: in step 5 or 11, make the eval's check source-aware, skipping `jsonld` and checking against the unescaped HTML, as the pipeline's repair does. Then state that D12's rule reads that number. | `run_eval.py:305-308`; build plan A3 G25 bullet; plan D12, step 11 (CONFIRMED) | The `a3-image-urls` run will report hundreds of "invented" URLs whether the change works or not, and the adopt/reject call becomes a judgement made by eye. | **Fixed.** Step 5 makes `invented_image_urls` source-aware (skips `jsonld`, checks the unescaped HTML) and a §3 test pins it; D12's rule reads that number. |
| 12 | should-fix | **Verification type-checks only the new modules, not the ones that carry G6.** §4 says that annotating the router `-> NodeOutcomes` is what lets mypy see the enum collision. But `make check` runs `mypy app/` only, and Verification 2 adds just `validation.py` and `policy.py`. Today `mypy --follow-imports=silent agent_worker/graph.py agent_worker/nodes.py` reports 4 errors, one of them G6's `float <= None`. Extend Verification 2's command to `graph.py nodes.py state.py constants.py` (the files A3 rewrites) and require "no issues". | `uv run mypy --follow-imports=silent agent_worker/graph.py agent_worker/nodes.py` → 4 errors incl. `graph.py:90` (CONFIRMED) | Without it, the type-level guard against G6 that the plan relies on is never actually run on the file where G6 lives. | **Fixed.** Verification 2 now type-checks `validation.py policy.py graph.py nodes.py state.py constants.py` and requires no issues, including clearing the 4 existing errors (G6's `graph.py:90`). `make check` still scopes mypy to `app/` until A7. |
| 13 | nit | **Gap C's lesson overstates what the date check catches.** With `year_rule=True` (adopted), `infer_year` puts every model-route and image-route date in `[fetched_on − 31, fetched_on + 334]`. The window can't fire there except for a Feb 29 in a non-leap year, which `infer_year` returns unchanged ("A3's plausibility check is the backstop"). In practice it guards the JSON-LD route and that leap-day fallthrough. Say so in the Lesson, and make the "leap-day case" test exactly that (model-route `2025-02-29`-style input surviving `infer_year`). Also, Gap C's code, §2 and Critical files ("`normalize.py` … reused as-is") say `_YEAR_LOOKBACK`, but step 5 renames it `YEAR_LOOKBACK`. Pick one. | `normalize.py:148-176`; plan §2, Gap C, step 5, Critical files (CONFIRMED by reading) | Ari learns a rule whose main production path is a different route than the lesson implies, and the gap's pasted code won't match the renamed constant. | **Fixed.** Gap C's lesson and §2 say the window mainly guards the JSON-LD route and `infer_year`'s Feb 29 fallthrough; the leap-day test is that case; the constant is `YEAR_LOOKBACK` everywhere (rename in step 5). |
| 14 | nit | **The model-route end-time repair uses the page-wide check that A2.1 rejected as too weak.** `end_time_is_stated` without a title lets "another listing's '11:00 pm' … vouch for a default end of 23:00" (its own docstring, from A2.1 code review round 2 #7). On the adopted title-split route, `extraction_notes["titles"]` has each show's verbatim title, so the same title-scoped call is available. Use it when titles exist, and fall back to page-wide otherwise. | `jsonld.py:198-215`; `extraction.py:210-215` (CONFIRMED by reading) | A repair meant to catch invented end times mostly won't fire on dense pages. That's low stakes given 0 observed (#6). | **Fixed.** The model-route end-time repair is title-scoped when `extraction_notes["titles"]` aligns with the shows, page-wide otherwise (the status merge can add a show and break alignment); test row. |
| 15 | nit | **Per-attempt fields can go stale across retries.** LangGraph keeps a field's last value unless a node writes it. If `extract_node` doesn't reset `extract_error`, `extraction_source`, `extraction_notes` and `last_plan` at the start of every attempt, an attempt-2 success carries attempt 1's `extract_error`, and `escalate_node` can cite an error from two attempts ago. State in step 6 that these are assigned on every attempt (to `None` where not produced), and have `test_graph` #2 assert `extract_error is None` after the recovery. | LangGraph `_internal/_fields.get_update_as_tuples` (CONFIRMED by reading); plan §5, step 6 | Misleading audit and escalation text, the record A4 persists. | **Fixed.** §5: `extract_node` assigns the per-attempt fields on every attempt; `test_graph` #2 asserts `extract_error is None` after the recovery. |
| 16 | nit | **E3 (each act appears in its title) is neither adopted nor deferred.** A2.1 recorded it as "useful as an A3 validation check either way". It is the one deterministic guard on the 100% field. Add it as a warning (it shouldn't route, given D1), or list it under "deliberately does not do" with a reason. | A2.1 plan, Deferred explorations, E3 (CONFIRMED) | A recorded hand-off from A2.1 gets lost. | **Fixed (adopted as a warning).** `act_not_in_title`, skipped when titles and shows don't align; §2 and a test row. Not routed, per the review's own reasoning. |
| 17 | nit | **Is there a `TODO(Ari)` in `graph.py`?** Step 9 marks `graph.py` "[fill-in, Gap D's router half]", but Gap D's *Code* is entirely in `policy.py`, and §4 calls the router "a thin reader". Say whether `graph.py` gets a `TODO(Ari)` block (and its Lesson/Code/Check) or is [written] around `decide_route`. | Plan step 9 vs Gap D (CONFIRMED) | The implementer has to guess the scaffold, and the code reviewer can't check it against the plan. | **Fixed.** Step 9 is [written]: no `TODO(Ari)` in `graph.py`; Gap D's code is entirely in `policy.py`. |
| 18 | nit | **The byte-identical test should pin against the measured request, not re-derive it from code.** §3 of the test approach builds the expected strings by calling `prompts.extraction_instruction(...)` and `_act_split_instruction()`, so the code under test supplies its own expectation. `a21-review2.json` stores the exact `instruction` and `splitter_instruction` that scored 56/60, and both equal today's output. Read the expectation from that file, which also makes the test's source independent. | `a21-review2.json["request"]` `==` current `instruction_for(PIPELINE_CONFIG)` / `_act_split_instruction()` (CONFIRMED) | A refactor of `prompts.py` together with the hint plumbing could change the first-attempt request, and a test that builds its expectation from the same functions would not notice. | **Fixed, adapted.** The expectation is now a pinned SHA-256 literal computed before any code change and confirmed locally against `a21-review2.json`'s stored `instruction` / `splitter_instruction`. Not read from the results file in the test itself, because that file is gitignored and CI would fail. |
| 19 | nit | **Gap A's notes:** (a) the "likeliest mistake" example is wrong: an increment in a `finally` still runs on failure, so it isn't the bug. The real mistake is today's code, an increment after the call outside any `try`. (b) `ValueError` in the tuple is broad: a `ValueError` from our own code (e.g. `zip(strict=True)` in `_shows_from_listings`) becomes a "failed attempt" too. That is acceptable, but say so beside `EXTRACTION_ERRORS`, the way the `Exception` exclusion is explained. | `nodes.py:156-158`; `extraction.py:208` (CONFIRMED by reading) | A Check line that points Ari at a non-bug. | **Fixed.** Gap A's likeliest-mistake line corrected (today's code increments after the call, outside any `try`); the breadth of `ValueError` is stated in §6 and in the gap. |
| 20 | nit | **D10 and the under-report guard count past dates.** 7th St Entry's page text has Oct 1–9 against an Oct 10 capture, and pages keep past listings and posted-on dates. Counting only pairs that `infer_year` places on or after `fetched_on` would cut the noise D10 accepts without losing the signal, since an under-report is about upcoming events. | Scratch replay: `seventh_st_entry-2026-10-10.html` pairs include (10,1)…(10,9) (CONFIRMED) | False escalations for venues with archives or blog dates. | **Fixed.** The under-report and `empty_but_dated` counts use only upcoming pairs (next occurrence on or after `fetched_on`); a test with an archive of past dates; the 7th St Entry case is named. |
| 21 | nit | **Verification wording.** V4 says "`local_test` on a URL page", but `local_test.py` runs a fixed local fixture, and stopping Ollama can't produce a *fetch* error. Say: with Ollama stopped, `local_test` (White Squirrel fixture) makes 3 splitter attempts and ends at escalate with an `APIConnectionError`/`InstructorRetryException` reason. V5 says "with every default unchanged", but D7 changes `RequestOptions.max_retries`. Say the request messages are unchanged and only the instructor re-ask budget differs. | `local_test.py:11-21`; plan V4, V5, D7 (CONFIRMED) | Verification steps that can't be run as written. | **Fixed.** Verification 4 and 5 reworded as the review says (the fixture can't produce a fetch error; D7 changes the re-ask budget, not the messages). |
| 22 | nit | **How `DEFAULT_POLICY` gets `escalation_model` isn't stated.** Say `DEFAULT_POLICY = RetryPolicy(escalation_model=settings.escalation_model_name)` (or wherever it's read), so that setting the env var actually changes tier 3. | Plan §3 "Tier 3 caveats", step 3, step 10 (CONFIRMED by reading) | A setting that's documented in `.env.example` but never read. | **Fixed.** Step 3: `DEFAULT_POLICY = RetryPolicy(escalation_model=settings.escalation_model_name)`; test in §2. |

Rejected: none. All 22 findings were accepted; #10 and #18 were adapted because the eval fixtures and results are gitignored (see "What CI can and can't see").

### Round 2 — Claude Opus 5.5, October 12, 2026

**Scope:** the revised plan body, read cold, with particular attention to what round 1's resolutions
added: the new checks (`excluded_no_acts`, `splitter_dropped`, `act_not_in_title`, the code-derived-field
fallback), the two-hint split, the sticky route fallback, the empty-response rule, and the local-only
real-page layer. Checked against the code at `b445e6f` (the uncommitted B3 changes in the tree don't touch
`apps/api`).

**What was checked and how.** Re-read `AGENTS.md`, `apps/api/AGENTS.md`, the FastAPI style guide's
Anti-patterns table, build plan §5 A3, `arch-initial.md` §7 ("Validation and retry"),
`requirements-initial.md` Agent Validation, and the code the plan changes: `nodes.py`, `graph.py`,
`state.py`, `constants.py`, `extraction.py`, `act_split.py`, `llm.py`, `normalize.py`, `status_check.py`,
`sources/jsonld.py`, `eval/labels.py`, `local_test.py`. Every round-1 Resolution was traced to the body:
**all 22 landed where they say they did.** Three of them brought new problems (#2 → findings 1 and 3, #20 →
finding 2, #10 → finding 9). Experiments, all read-only, run as scratch scripts in the session scratchpad
with `PYTHONPATH=. uv run python …` from `apps/api` (no worktree needed, nothing in the repo touched):

- `normalize.infer_year` with `fetched_on` 2026-10-12: a date 400 days out becomes **2026-11-16**, and one
  40 days back becomes **2027-09-02** (finding 1).
- The plan's "upcoming pair" rule (next occurrence on or after `fetched_on`) over
  `clean_text(seventh_st_entry-2026-10-10.html)`: **28 of 28** pairs are kept, Oct 1–9 included. Placing each
  pair with `infer_year` and dropping those before `fetched_on` keeps 20 (finding 2).
- `jsonld.to_structured_show` on an event with `endDate == startDate` (20:00) and page text "The Band Oct 15
  8:00 pm": `time 20:00, end_time 20:00`. `_end_time` accepts a zero-length show (`timedelta(0) <=`), and
  `end_time_is_stated` is satisfied by the stated *start*. No fixture's JSON-LD does this (0 of 48 events)
  (finding 4).
- A toy LangGraph 1.2.11 graph with a Pydantic state holding frozen-dataclass fields (`RetryPolicy`, an
  `AttemptPlan` wrapping `ExtractionConfig` and `RequestOptions`), looping twice: the dataclasses survive
  `invoke` and `VenueGraphState(**result)`-style re-wrapping, and assigning `err = None` on attempt 2 does
  clear attempt 1's value. §5's state design and the per-attempt reset work as written (CONFIRMED).
- Replayed the run-0 extraction of every fixture in `a21-confirm.json` with `labels.PAGE_LABELS[…].captured_on`
  as `fetched_on`: no `act_not_in_title` hit on any page whose titles align. 7th St Entry's titles **don't**
  align (29 titles, 30 shows: the status merge added one), and **no model-route show has an `end_time`** in
  that run. The JSON-LD White Squirrel pages give no under-report either way (finding 9).

**Counts:** 0 blocker, 6 should-fix, 5 nit. **Verdict: proceed after fixes.** The design still holds, and
round 1's fixes are in the body. What remains is mostly in the new JSON-LD fallback. One code that triggers
it (`date_implausible`) trades a visible escalation for a silently wrong date. Some JSON-LD failures still
retry with a byte-identical request. The "upcoming dates" filter doesn't filter. There is also one module
cycle to settle before step 1.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **Falling back to the model route on `date_implausible` turns a flagged date into a wrong one that passes.** The model route runs the year rule, and `infer_year` puts *every* month/day in `[fetched_on − 31, fetched_on + 334]`. So the event the JSON-LD route correctly flagged can't keep its real date on the model route. A festival 400 days out is re-dated to next month; a stale event 40 days back becomes a show next September. Both then pass the window check, which they now sit inside. `test_graph` #11 asserts exactly this outcome ("attempt 2 … passes"). Suggested: drop `date_implausible` from `ROUTE_FALLBACK_CODES`. On the JSON-LD route an out-of-window show is **excluded with a warning** (`date_out_of_window`, title and date in the message): round 1 #2's option (c). The date is the source's own, a retry can't change it, and no model route can represent it. Rewrite `test_graph` #11 to match. If Ari prefers escalation, make it an immediate escalate, not a fallback. | `normalize.py:155-176`; scratch: `infer_year(2026-10-12 + 400d) = 2026-11-16`, `infer_year(2026-10-12 − 40d) = 2027-09-02` (CONFIRMED); plan §2 "JSON-LD route: findings on code-derived fields", `test_graph` #11 | A wrong date reaches A5 as a confirmed pass. The Accuracy Standards call a wrong field never acceptable, and this one arrives with a clean validation record, so nobody looks. | **Fixed (new D13).** On the JSON-LD source an out-of-window event is *excluded with a `date_out_of_window` warning*, not retried and not sent to the model route; on the model route it stays an error. `date_implausible` leaves the fallback set; `test_graph` #11 rewritten (one attempt, show excluded, no retry). Added to the Decisions table because it changes behaviour Ari may want the other way (immediate escalate is the alternative). |
| 2 | should-fix | **The "upcoming pairs only" rule (round 1 #20's fix) filters nothing as written.** §2 says a pair is "placed in a year as the next occurrence on or after `fetched_on`, and a pair that falls before it is ignored". The next occurrence on or after a date can never fall before it, so every pair counts. That includes 7th St Entry's Oct 1–9, the example the fix names. The synthetic archive test ("extra dates all fall *before* `fetched_on` → no finding") then contradicts the rule, and the implementer has to guess which one is right. Round 1 #20's wording was "pairs that `infer_year` places on or after `fetched_on`". Use that: place with `infer_year`, ignore if the result is before `fetched_on`. Say that this drops only the past 31 days; an archive older than that still counts. Make the synthetic archive's dates fall inside the 31 days. | Plan §2 under-report bullet; scratch over `seventh_st_entry-2026-10-10.html`: plan's rule keeps 28/28 pairs, the `infer_year` rule keeps 20 and drops (10,1)…(10,9) (CONFIRMED) | `empty_but_dated` and `jsonld_under_reported` count past listings and posted-on dates, which is the noise #20 meant to remove. The archive test can't go green against the rule as written. | **Fixed.** The rule is now `infer_year(pair, fetched_on)`, ignored if before `fetched_on` (measured on 7th St Entry: 20 of 28 kept). §2 says it drops only the past 31 days; the synthetic archive test uses dates inside that window plus one older case that does count. |
| 3 | should-fix | **Some JSON-LD-route failures still retry with a byte-identical request, and the sticky fallback can't see a failed JSON-LD attempt.** (a) The page hint has no consumer on the JSON-LD route: `_from_jsonld` calls only the splitter. A `PAGE`-target error outside `ROUTE_FALLBACK_CODES` therefore leaves attempts 2 and 3 identical to attempt 1. One example is `empty_but_dated` when the splitter excluded every event on a dated page. Another is `extract_failed` from a malformed `startDate`, a deterministic `ValueError` in `fromisoformat` that §6 itself names. At temperature 0 that is G5 again. (b) §5 resets `extraction_source` to `None` when the attempt fails, so the `AttemptRecord` of a failed JSON-LD attempt has `source=None`. Gap E's `r.source == "jsonld"` then can't trigger a fallback for it. Suggested: record the **route attempted** on each attempt (e.g. `AttemptRecord.route`: whether `extract_page` found usable events, or `last_plan` plus a cheap `find_events` pre-check), not only the source produced. On a JSON-LD-route attempt, any `FAILED` verdict with no `SPLITTER`-target reason falls back. Add a `test_graph` row: malformed `startDate` → attempt 2 on the model route. | `extraction.py:219-259` (no page-model call on the JSON-LD route), `jsonld.py:126` (`fromisoformat`), plan §5 reset paragraph, Gap E *Code* (CONFIRMED by reading; how often it happens is PLAUSIBLE) | Three identical calls and a daily escalation for a venue whose JSON-LD has one malformed event: the "costs tokens without recovering" outcome A3 exists to remove. `test_graph` #7 only checks the model route, so it wouldn't notice. | **Fixed.** Replaced the fixed code set with one rule: a failed JSON-LD-route attempt with any non-`SPLITTER`-targeted reason falls back to the model route (covers `extract_failed` from a malformed `startDate`, `empty_but_dated`, `jsonld_under_reported`, consistency errors). `AttemptRecord.route` records the route used even when the attempt fails (via a shared `extraction.usable_events(html)` helper); Gap E keys on it. `test_graph` #13 added. |
| 4 | should-fix | **`end_equals_start` as an *error* sends any venue whose plugin writes `endDate == startDate` to the fallback on every run.** `jsonld._end_time` accepts a zero-length show, and `end_time_is_stated` vouches for 20:00 because the page states the 20:00 *start* next to the title. Every such show fails `end_equals_start`, which is in `ROUTE_FALLBACK_CODES`. So the page always loses attempt 1 and is read by the less precise model route, and every run is recorded as a failure first. Under D4 this is a value that fails verification, which the plan elsewhere **drops** rather than routes (the misplaced-start repair is the same family). Suggested: make it a **repair on all sources** (drop `end_time`, record a `Repair`) and remove it from `ROUTE_FALLBACK_CODES`. Optionally also make `_end_time` require `end > start`, recorded under A2.1 D10 where that guard lives. Gap C's lesson keeps its point: `<` is never a finding. | `jsonld.py:193` (`timedelta(0) <= end_at - start_at`), `jsonld.py:198-238`; scratch `to_structured_show` → `time 20:00, end_time 20:00` (CONFIRMED). No fixture has the pattern (0/48 events), so its frequency in the wild is PLAUSIBLE | Wasted attempts and noisy failure history for a common plugin habit, and the JSON-LD route's exact dates and prices are swapped for a model's reading on every run. | **Fixed.** `end_time == time` is a repair on all sources, not an error, and not a route trigger (§2, Gap C code, tests, `test_graph` #14). Tightening `jsonld._end_time` itself is left alone (A2.1 D10's code, no fixture has the pattern). |
| 5 | should-fix | **`validation.py` and `policy.py` import each other.** Step 2 has `validate_extraction` assemble the verdict "via Gap D's function in `policy.py`" (`combine`). Step 3's `policy.py` needs `validation.py`'s types: `Verdict`, `PageOutcome`, `FailureReason` for `combine`, `CheckCode` for `ROUTE_FALLBACK_CODES` and the hint targets. A module-level `from … import` each way fails with "partially initialized module" in step 1, when the stubs are first imported. Pick the layout in the plan, because it decides which file Gap D's `TODO(Ari)` sits in. Options: (a) `validate_extraction` returns findings and outcome, and `validate_node` calls `policy.combine`; (b) `combine` moves into `validation.py`, with `policy.py` importing from `validation.py` only. Also say where `AttemptRecord` lives (`state.py` needs `RetryPolicy` at runtime for the Pydantic field, and `policy.py` reads `AttemptRecord`). | Plan steps 2–3, §5 (CONFIRMED by reading the planned layout; the import failure is PLAUSIBLE, since an implementer could dodge it with function-level imports) | Step 1's "fail by assertion, not by import error" check fails for a structural reason, and the fix moves a gap between files without Ari or the reviewer having agreed to it. | **Fixed.** §5 "Module layout": `validation.py` ← `policy.py` ← `state.py` ← nodes/graph. `validation.py` owns all types and the checks and returns a result with no verdict; `policy.py` owns `RetryPolicy`, `AttemptPlan`, `AttemptRecord`, `combine` (Gap D), `decide_route`, `plan_for_attempt` (Gap E). Gap D stays in `policy.py`. Steps 2 and 3 updated. |
| 6 | should-fix | **Gap E's pasteable code builds the hint from an `AttemptRecord`, which doesn't carry what the hint is built from.** §3 says the hints come from "the failed findings' own messages" ("A show was dated 2026-03-01, more than a month before today…"). §5's `AttemptRecord` holds reasons, finding **codes** and counts, but no messages. `retry_hint(history[-1])` can only produce the fixed per-code sentences. Also, §3's table says tier 3 uses "tier 2's hints", while the code rebuilds from `history[-1]` (attempt **2's** findings), which drops attempt 1's reason if attempt 2 failed for another one. Fix: have `AttemptRecord` keep the error findings (code, target, message, show index), or pass the last `ValidationResult` to `plan_for_attempt`. Then state which findings tier 3 hints from: the last attempt's, or the union of the history's. | Plan §3 "Two hints", §5 `AttemptRecord`, Gap E *Code* (CONFIRMED by reading) | Ari pastes Gap E's code and it doesn't type-check against the record it's given, or it silently sends only generic sentences, which weakens the one thing that changes a temperature-0 retry. | **Fixed.** `AttemptRecord` keeps the error findings (code, target, message, show index); `retry_hint(history)` builds tier 2's hints from attempt 1's findings and tier 3's from the deduplicated union across attempts; §3 table, §5 and Gap E code updated, with a test row. |
| 7 | nit | **`validate_extraction`'s signature and scope leave three things unsaid.** (a) Step 2's signature `(extraction, *, source, fetched_on, page_html, page_text, policy)` has no `notes`, but `excluded_no_acts`, `splitter_dropped`, `act_not_in_title` and the title-scoped end-time repair all read `extraction_notes`. (b) It doesn't say whether the per-show checks run on **excluded** shows. JSON-LD lists the whole calendar, so a karaoke night's odd data could fail the page. Confidence already uses kept shows only, and the checks should match. (c) The under-report's "no extracted show falls" should say **raw** shows: the JSON-LD did list an event the splitter later excluded. | Plan step 2, §2 (CONFIRMED by reading) | Small guesses during implementation, and two of them affect the verdict. | **Fixed.** Step 2's signature now includes `notes` and drops `policy`; checks run on kept shows only; the under-report comparison uses all extracted shows' dates. |
| 8 | nit | **The empty-response rule is narrower and less retried than the text around it suggests.** (a) §4 states it for "a URL page", but `test_graph` #8 drives it with an empty **local** file. Say it applies to both text branches. (b) `arch-initial.md` §7 says a fetch failure, empty response included, "retries Fetch directly, with backoff". The plan escalates an empty body at once. Either add it to the `tenacity` predicate or record the departure and its reason. (c) A page whose events exist only in JSON-LD, with near-empty visible text (a JS shell), becomes a `fetch_error` even though the JSON-LD route could serve it. Check `find_events` before calling it empty, or state that the rule rejects such pages. | Plan §4 last bullet, `test_graph` #8; `arch-initial.md:175` (CONFIRMED by reading) | A test that contradicts its rule, and an undocumented departure from the doc the plan cites. | **Fixed, in part by recording a departure.** The rule covers text pages (URL or local file, not images); a URL's empty body is retried by `tenacity` as arch §7 says; a page with usable JSON-LD events and no visible text is not an empty response. Tests adjusted in §3 and `test_graph` #8. |
| 9 | nit | **The real-page layer's description is slightly off.** (a) It lists "Terminal Bar HTML" among the **gated** pages, but `labels.py` marks both Terminal captures `gated=False`. Keep them, but call the set "gated plus Terminal". (b) The expectations quote "the round-1 scratch replay", which didn't exercise two of the new rules on real data. 7th St Entry's titles don't align (29 vs 30), so `act_not_in_title` and the title-scoped end-time repair are skipped there. No model-route show in run 0 has an `end_time`, so that repair can't fire anywhere. Say so, so the green result isn't read as evidence for those two rules. | `eval/labels.py:185,199`; replay of `a21-confirm.json` run 0 (CONFIRMED) | Overstated coverage in the one layer that touches real data. | **Fixed.** The real-page set is called "gated plus Terminal", and the section lists what it does not exercise (`act_not_in_title`, the title-scoped end-time repair) so a green run isn't read as evidence for them. |
| 10 | nit | **The pinned hashes cover two of the four requests the byte-identical test claims.** The test covers the model route, the JSON-LD splitter, the status question and the image route. Only `instruction_for(PIPELINE_CONFIG)` and `_act_split_instruction()` are pinned. The image route sends `instruction_for(replace(config, title_split=False))`, and the status question has its own text. Pin all four, and confirm whichever `a21-review2.json` stores, or narrow the claim. | Plan test approach §3; `extraction.py:315-316`, `status_check.py` (CONFIRMED by reading) | A hint-plumbing change that alters the image or status request on attempt 1 passes the test. | **Fixed.** All four requests are pinned (model route, splitter, image route, status question) and checked locally against the four instruction texts stored in `a21-review2.json`. |
| 11 | nit | **Two loose ends in the plumbing.** (a) The status merge's splitter call (`extraction.py:181-183`, the lambda passed to `status_check.apply`) is a third `split_titles` call site. The plan threads `config` into `_from_jsonld` and `_shows_from_listings` only, so say whether the splitter hint reaches it. (b) Status-merge-added shows carry a **placeholder** `confidence=1.0`, like the JSON-LD route's (`status_check.apply` docstring). On a model page whose only kept shows were added by the merge, confidence would read 1.0 without any model judging it. Exclude them from the minimum as the JSON-LD placeholder is excluded. | `extraction.py:181-188`, `status_check.py:117-118,148-151` (CONFIRMED by reading) | An inconsistent hint on one call path, and a confidence number that claims more than it measures in a rare case. | **Fixed.** The splitter hint reaches the status merge's splitter lambda; `status_check.apply` records `added_indices` and the confidence minimum excludes those shows; test rows added. |

Rejected: none. All 11 findings were accepted. Round 2's size (it reworked the JSON-LD fallback rule, added D13 and a module layout) is the kind of change that could use a round 3 if Ari wants one.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 12, 2026

**Scope.** Diff base `b445e6f` (HEAD) plus the **uncommitted working tree**; nothing was committed. The tree also holds changes that are **not A3's** and should be left out of the review: Ari's B3 work (`apps/calendar/**`, `packages/ui/**`, `docs/dev/implementations/b3-the-calendar.md`, the B3 edits in `docs/dev/notes.md`, `docs/dev/api-contract.md`, `apps/api/app/sample_data.py`, `pnpm-lock.yaml`), and three files that changed while A3 was being built and that I didn't touch: `.vscode/launch.json`, the root `AGENTS.md`, `docs/dev/debugging.md`. A3's files:

- **New:** `apps/api/agent_worker/validation.py`, `policy.py`; `agent_worker/tests/{fakes,test_validation,test_policy,test_graph,test_retry_plumbing,test_validation_on_real_pages}.py`
- **Modified (code):** `agent_worker/{nodes,graph,state,extraction,act_split,status_check,llm,normalize,local_test}.py`, `agent_worker/eval/run_eval.py`, `agent_worker/tests/test_prompts.py` (one assertion: `max_retries` 3 → 1), `app/config.py` (`escalation_model_name`), `apps/api/.env.example`. `constants.py` is unchanged.
- **Modified (docs):** `docs/dev/alpha-build-plan.md` (A3 and A7 only), `docs/arch/arch-initial.md` §7, `docs/arch/requirements-initial.md` "Agent Validation", `apps/api/AGENTS.md`, `docs/dev/notes.md` (the last three entries), this plan.

**Departures from the plan**, each with its reason:

1. **Tests were written after the module code, not before it** (the plan and `AGENTS.md` say tests first). The types and scaffolds came first because the tests need the signatures; I then wrote every test against them. To show the tests aren't tautological I ran **ten mutations** on a scratch copy (route fallback never happens, a 4xx retried, image check on JSON-LD, `data-src` ignored, the naive `end <= start` check, an unguarded `min([])`, one hint sent to both calls, a non-sticky fallback, a last attempt that adds nothing, `shows` tested before `page_readable`): **all ten are caught**. One real defect was found by a test, not by me: see 3.
2. **`test_retry_plumbing.py` instead of additions to `test_extraction.py`**: the hint, image-link, status-merge, fetch and eval tests live in their own file, so A2.1's closed test file stays untouched. Same content as plan §3.
3. **A last-attempt sentence.** `test_graph`'s different-request test showed that when attempt 2 fails the same check as attempt 1, the union of findings is the same text, so on a machine with no larger model attempt 3 was **byte-identical to attempt 2**: G5 again. `retry_hint(history, final=True)` now adds a conservative sentence of its own to both hints ("leave a field null rather than guess"; "never add a name the title doesn't contain"). Plan §3's table and Gap E's code are updated to say so; the finding is in `notes.md`.
4. **Gap scaffolds differ from the plan's sketches in shape, not in lesson:** Gap C returns a `PlausibilityFlags` (two booleans) instead of appending findings (so `end_equals_start` can be a repair, round 2 #4); Gap D is split across `combine` and `decide_route` (two `raise` sites, one lesson); Gap E uses a written `route_falls_back(record)` helper and passes `final=attempt >= 3`; **Gap A's scaffold keeps today's unguarded call** (with the increment after it) so the happy path and A2.1's existing node tests still run, and only the error-path tests are red. The pasted `Code` in each scaffold is authoritative (noted in the plan).
5. **`route_falls_back`** is the rule "a JSON-LD attempt that failed with any reason that is not solely splitter-targeted" (round 2 #3), checked on `AttemptRecord.route`, `.verdict`, `.reasons` and `.findings`. The plan's inline code (`r.route == "jsonld" and any(f.target is not SPLITTER ...)`) would have missed `extract_failed`, which has no finding.
6. **`validate_extraction` returns `(result, kept_shows)`**, not a result holding the shows, so `ValidationResult` stays small enough to live on the state.
7. **Status merge:** `added_indices` is hoisted to `notes["added_indices"]` (top level) from the merge's notes, where validation reads it. The first version left it nested and a test caught it.
8. **JSON-LD notes gained `"titles"`** (the verbatim titles, in show order), which the title-scoped checks need on that route. Stored a21 runs lack it; the real-page test rebuilds it from `sent_text`.
9. **`fetch_html(url, *, reject_empty=False)`** gains a keyword and a `tenacity` retry (also used by `eval/capture.py`, whose behaviour on a good page is unchanged, tested).
10. **`from instructor.core.exceptions import InstructorError`**, not `instructor.InstructorError`: verified in the venv that both exist and that `InstructorRetryException` is a subclass.

**`TODO(Ari)` gaps — all five open**, in the order to fill them (B and C first: everything else runs through them):

| Gap | Where | Lesson |
|---|---|---|
| B | `validation.py:191` (`classify_page`) | readability is asked first: unreadable beats empty and beats "returned a stray show" |
| C | `validation.py:256` (`check_plausibility`) | the date window is relative to the fetch date; an end *earlier* than the start is the next morning, only an *equal* end is wrong |
| D | `policy.py:115` (`combine`) and `policy.py:148` (`decide_route`) | a verdict, not a float: errors fail whatever the confidence; `None` confidence is no evidence; the router returns `NodeOutcomes` only (G6) |
| E | `policy.py:262` (`plan_for_attempt`, attempts 2 and 3) | a retry must change the request; the route fallback is sticky; tier 3 says whether it really escalated the model |
| A | `nodes.py:206` (`extract_node`) | count the attempt before the call; catch a named tuple, never `Exception` |

Command: `cd apps/api && uv run pytest agent_worker/tests/test_validation.py agent_worker/tests/test_policy.py agent_worker/tests/test_graph.py`. Open gaps aren't findings.

**Verification** (every result below was observed):

- **Open-gap state:** `make check`: ruff clean, mypy (`app/`) clean, eslint/tsc 3 of 3 tasks, vitest 153 passed, `make contract-check` current; **pytest: 109 failed, 460 passed**. All 109 failures are gap-driven: **106** raise `NotImplementedError("TODO(Ari)")` (64 in `validation.py` — Gaps B and C — and 42 in `policy.py` — Gaps D and E), and **3** are exceptions escaping `extract_node` (Gap A). Baseline before A3 was 411 passed, so all 411 still pass (one assertion updated, departure noted).
- **Gaps filled** (the plan's `Code` pasted verbatim, on a **scratch copy** of `apps/api`, the repo's gaps untouched): **569 passed**, none skipped (the scratch copy links the fixtures and results), including the real-page layer.
- `uv run mypy --follow-imports=silent agent_worker/validation.py policy.py graph.py nodes.py state.py constants.py`: **no issues**, including the four errors those files had before (G6's `graph.py:90` among them).
- **`local_test`** on the White Squirrel capture, real Ollama, gaps filled on the scratch copy: `verdict: passed after 1 attempt(s); source: jsonld`, 71 s.
- **The loop on a real failure.** I did not stop your Ollama; on the scratch copy I pointed the client at a closed port (`localhost:9`). Result: three attempts, all `extract_failed`; attempt 1 on `jsonld`, attempts 2 and 3 on `model` (the fallback, sticky); tiers `initial`, `narrowed`, `larger_model` with no larger model configured; escalated with `...the last model call failed with InstructorRetryException: Connection error.; it failed on the jsonld and model routes both`, no traceback.
- **No regression (Verification 5), `a3-confirm`**, gated set, one run each (temperature 0, deterministic), 15 minutes: **56 of 60, the same per page as `a21-review2`** (the post-review run): Mortimer's 7 returned / 1 act wrong, 7th St Entry 2 acts wrong, White Squirrel (Oct) 1 missed, White Squirrel (Aug) clean. No invented show, no wrong field, 0 invented image URLs. Mortimer's used 2 instructor attempts (one re-ask, recovered), which D7's `max_retries=1` still allows.
- **G25 (Verification 6), `a3-image-urls`**: model-route shows now carry image URLs (Mortimer's: **17**, **0 invented**), but act splitting got worse on the model route: Mortimer's 1 missed + 1 act wrong (was 1 wrong), 7th St Entry 3 wrong (was 2), and 7th St Entry returned 31 shows (was 30). Per D12's rule (adopt only if 56/60 holds) **not adopted: `keep_image_urls` stays off**. White Squirrel (Oct) differing between the two runs is not this change (the JSON-LD route never reads the switch): `a21-confirm` and `a21-review2` flip the same way, and `notes.md` already records that the Ollama app can change under an eval. Image links therefore remain null on text pages; an alternative (a separate image-extraction call, not text for the page model) is for H1 or later.

**Where to look hardest:**

1. **`route_falls_back` and `plan_for_attempt` together** (`policy.py`): the rule that decides when a JSON-LD attempt gives way to the model route is new, subtle and was reworked in round 2. The intended behaviour is in `test_graph` tests 9–12.
2. **Excluded versus failed** (`validate_extraction`): an out-of-window JSON-LD event is excluded with a warning (D13), a model-route one is an error. Check that no path silently drops a show without a finding.
3. **`fetch_html`'s `tenacity` predicate and `EmptyResponse`** (`nodes.py`): a body with usable JSON-LD but no visible text must not be an empty response; a 4xx must not be retried.
4. **`validation.upcoming_dates`** (the year placement through `infer_year`): the threshold of 3 is a guess measured on two pages.
5. **What I'm least sure of:** whether `ValueError` in `EXTRACTION_ERRORS` is too broad (it also catches our own `zip(strict=True)`); and the real-page test's literals, which I read from the stored `a21-confirm` run 0 and haven't cross-checked against a second run.

## Code review

### Round 1 — Claude Opus 5.5, October 12, 2026

**Scope:** Implementation log round 1: the uncommitted working tree on top of `b445e6f`, limited to the A3
files the log lists (new `validation.py`, `policy.py`, `tests/{fakes,test_validation,test_policy,test_graph,test_retry_plumbing,test_validation_on_real_pages}.py`;
modified `nodes.py`, `graph.py`, `state.py`, `extraction.py`, `act_split.py`, `status_check.py`, `llm.py`,
`normalize.py`, `local_test.py`, `eval/run_eval.py`, `tests/test_prompts.py`, `app/config.py`, `.env.example`, and the
A3 parts of `alpha-build-plan.md`, `arch-initial.md` §7, `requirements-initial.md`, `apps/api/AGENTS.md`, `notes.md`).
Ari's B3 work and the other unrelated changes in the tree were not reviewed. The five open `TODO(Ari)` gaps are
not findings; their pasted *Code* and *Check* lines were reviewed as part of the scaffold.

**What was checked and how.** Read `AGENTS.md`, `apps/api/AGENTS.md`, the FastAPI style guide's Anti-patterns
table (nothing in it applies to this diff: no routes, no async code, no settings split; the one bare-`Exception`
risk is handled by the named `EXTRACTION_ERRORS` / `FETCH_ERRORS` tuples), the plan body and both plan-review
rounds, and every A3 file in full or by diff. Commands, results observed:

- `make check` on the tree as it stands: ruff clean, `mypy app/` clean, **pytest 109 failed / 460 passed**, and make
  stops there. Re-run with `-rf`: all 109 are in `test_validation.py`, `test_policy.py`, `test_graph.py` and
  `test_validation_on_real_pages.py`, consistent with the log's gap accounting (CONFIRMED). `make contract-check`
  run separately: "Generated contract output is current" (CONFIRMED). vitest was not run (make stops at pytest, and
  the JS side is B3's).
- `uv run mypy --follow-imports=silent` on `validation.py policy.py graph.py nodes.py state.py constants.py`: no
  issues, in the repo and with the gaps filled (CONFIRMED; Verification 2).
- **A throwaway `git worktree`** at `b445e6f` with the A3 files rsynced in and the five gaps filled by pasting each
  scaffold's *Code* verbatim (scripted). Result: **569 passed**, 0 skipped, the real-page layer included (CONFIRMED,
  the log's number). ruff then reports only the three `RUF100` unused-`noqa`s the scaffolds tell Ari to delete.
  The worktree was removed afterwards (`git worktree list` shows only `main`). `git status --porcelain` matched a
  snapshot taken before the review, apart from this file.
- **Eight extra mutations** of *written* code in that worktree, none of them among the author's ten: under-report
  ignoring the shows' dates; D10 keyed on raw rather than kept shows; past dates counted as upcoming; a blank act
  name downgraded to a warning; `_route_for` ignoring `config.route`; no `extract_error` reset; the fallback rule
  keyed on reasons only; merge-added shows counted in the confidence. **All eight were caught** by at least one test
  (CONFIRMED). The departure "tests written after the module code" is a real breach of build plan §3, disclosed;
  this mutation evidence and the author's makes the suite credible anyway.
- Two graph-level experiments with a `ScriptedClient` in the worktree (finding 1), one check of the
  `ESCALATION_MODEL_NAME=` setting (finding 3), and `pytest --collect-only -k …` for every gap's *Check* selector
  (finding 2).
- Eval results: `a3-confirm.json` per page equals `a21-review2.json` (White Squirrel Aug 0/0, Mortimer's 0 missed / 1
  act wrong, 7th St Entry 0 / 2, White Squirrel Oct 1 / 0) with `max_retries: 1` recorded, and `invented_image_urls`
  0 (CONFIRMED, Verification 5). `a3-image-urls.json` shows Mortimer's 1 / 1 and 7th St Entry 0 / 3, so not adopting
  G25 is right (CONFIRMED, Verification 6).
- Replayed `a3-confirm`'s model-route runs through `check_act_in_title`: on 7th St Entry (30 titles, 30 shows, so
  aligned) it fires on `'Devilsoundguy' not found in its title` (the title says "Evilsoundguy"), a real wrong act
  (CONFIRMED; see nit 9).

**Counts:** 0 blocker, 4 should-fix, 5 nit. **Verdict: proceed after fixes.** The structure matches the plan:
evidence in `validation.py`, decisions in `policy.py`, nodes that only wire, and the router can't reach a float or
the wrong enum. With the gaps filled the whole suite is green, and the request a first attempt sends is pinned to
the one that scored 56/60. One should-fix is behavioural: a JSON-LD page whose every event is out of window reaches
the model route through the D10 guard, and D13 exists to stop exactly that. The other three are small and cheap: two
gap *Check* commands that select no tests, an audit flag that can claim a larger model ran when none did, and a
promised test that doesn't exist although a comment says it does.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **A stale or wholly out-of-window JSON-LD page gets past D13 through the D10 guard.** When *every* JSON-LD event is outside the window, D13 excludes them all, so nothing is kept. `validate_extraction` then runs `check_empty_but_dated` (`validation.py:539-540`), and the visible text names those same events' dates. `upcoming_dates` places any date more than 31 days back in *next* year, so it counts as upcoming, and the page gets `empty_but_dated`. That is a non-`SPLITTER` error on the JSON-LD route, so `route_falls_back` sends attempt 2 to the model route. There the year rule re-dates the events into a plausible wrong year, and the page passes. D13 says this must not happen. The final `state.validation` carries none of attempt 1's `date_out_of_window` warnings either, because `AttemptRecord` keeps only error findings. The under-report guard already handles this correctly: it compares against *all* extracted shows' dates, excluded ones included (round 2 #7). Suggested: apply the same rule to `empty_but_dated` (subtract the dates of every extracted show, excluded ones included) and add a `test_graph` case for an all-stale JSON-LD page. **Ari may want to decide** what such a page should then do. Once the guard stops firing, it passes with nothing kept, and after A5 that soft-deletes the venue's stored shows. The alternative is an immediate escalation ("the structured data lists nothing upcoming"). This is D13's own question, one step further. | Worktree, gaps filled: JSON-LD events dated Aug 1–3 2026, body text "A Aug 1 8 pm B Aug 2 8 pm C Aug 3 8 pm", `fetched_on` 2026-10-12, model answer with the page's dates. History: `1 jsonld failed ['check_errors'] ['empty_but_dated']`, then `2 model passed`. Committed dates **`2027-08-01`, `2027-08-02`, `2027-08-03`**, reconcile reached, final warnings `[]` (CONFIRMED) | A venue whose site stopped updating, or one listing only a festival more than a year out, gets wrong dates written to the calendar on a clean pass. The audit record shows no sign that the structured data disagreed. D13's "a visible exclusion beats a silent wrong date" is reversed for exactly the page where it matters most. | **Fixed, with one question for Ari.** `check_empty_but_dated` now subtracts the (month, day) of every extracted show, excluded ones included (`validation.py`), like the under-report guard. Tests first: a pure-function test, a `test_validation` case, and `test_graph::test_a_json_ld_page_of_only_stale_events_is_excluded_not_sent_to_the_model_route` (the script has no PAGE answer, so any model-route call fails it); all red before the fix, green with the gaps filled; reverting the subtraction fails them (mutation). **Ari decides** (D13 one step further): an all-stale page now passes with nothing kept, each exclusion reported as a warning, and `empty_but_dated` stays for pages whose dates no show accounts for. The alternative is an immediate escalation ("the structured data lists nothing upcoming"). Recommended: pass, because once A5 exists an empty list's blast radius is A5's to guard (already its hand-off), and a venue whose site stopped updating is not an error the pipeline can fix. Also noted, not changed: `AttemptRecord` keeps only error findings, so an earlier attempt's warnings are not on the final `state.validation` (`warning_count` is). |
| 2 | should-fix | **Two gap *Check* commands select no tests.** Gap C's says `pytest agent_worker/tests/test_validation.py -k plausibility`, but no test name contains "plausibility" (the section comment does, and `-k` doesn't read comments). Gap E's says `test_policy.py -k plan`, but its tests are named `test_the_second_attempt_…`, `test_the_third_attempt_…` and so on. Both commands exit with code 5, "no tests ran". The others work: `-k page_outcome` selects 4, `-k verdict` 11, `-k route` 17, `test_graph -k raises` 2, `-k different_request` 1. Fix: change the selectors (e.g. Gap C `-k "window or end_time or feb_29"`, Gap E `-k attempt`), or rename the tests so the selectors match. | `validation.py:272`, `policy.py:284`; `uv run pytest --collect-only -q … -k plausibility` → 0, `-k plan` → 0 (CONFIRMED) | `AGENTS.md`: the *Check* is "the test that goes green when it's right", and a gap should cost minutes. Ari fills Gap C or E, runs the command he was given, sees "no tests ran", and can't tell whether his lines work. | **Fixed.** Gap C's Check is now `-k "window or feb_29 or end_time"` (12 tests), Gap E's `-k "attempt or sticky or retry"` (23). Every gap's Check selector was collected and selects tests: B 4, C 12, D `verdict` 11 and `route` 17, E 23, A `raises` 2, plus `different_request` 1. |
| 3 | should-fix | **An empty `ESCALATION_MODEL_NAME` makes the audit record claim a larger model ran.** pydantic-settings reads `ESCALATION_MODEL_NAME=` as `""`, not `None`. Gap E's pasted code then keeps the base model (`if model`), but it records `larger_model_used=model is not None`, which is `True`. `.env.example` shows the line as `# ESCALATION_MODEL_NAME=`, so uncommenting it as written produces this. D5 exists to stop exactly this misreport ("Faking it would make A8 misreport"). Fix in written code: `DEFAULT_POLICY = RetryPolicy(escalation_model=settings.escalation_model_name or None)`. Also make Gap E's *Code* use one test for both (`larger_model_used=bool(model)`), and add a `test_policy` row with `escalation_model=""`. | `policy.py:66`, `policy.py:280-282` (Gap E *Code*), `.env.example`; worktree with `ESCALATION_MODEL_NAME=` set empty: `settings.escalation_model_name == ''`, and `plan_for_attempt(3, …)` → `larger_model gemma4-e4b-32k True` (CONFIRMED) | A8 counts attempts as larger-model escalations when the same 4B model ran, so the retry-recovery measurement credits a tier that never ran. | **Fixed.** `RetryPolicy.__post_init__` turns an empty `escalation_model` into `None`, so `ESCALATION_MODEL_NAME=` left empty means none configured; Gap E's pasted Code uses `larger_model_used=bool(model)`. Tests: `RetryPolicy(escalation_model="").escalation_model is None`, and a Gap E case with an empty name (reverting the normalisation is caught by mutation). |
| 4 | should-fix | **The labelled-answer scan was not extended to the hint text, and a comment says it was.** Plan §3: the hints use fixed sentences "never from labelled answers (A2.1's `test_no_prompt_quotes_a_labelled_answer` pattern is extended to the hint builder)". `policy.py:170` says "never quoting a labelled answer (a test scans for that)". No test scans `_ADVICE`, `_REASON_ADVICE`, `_FINAL_PAGE_ADVICE`, `_FINAL_SPLITTER_ADVICE` or the two `_HINT_INTRO`s. `test_no_prompt_quotes_a_labelled_answer` is unchanged, and no new test references `PAGE_LABELS`. This isn't listed under Departures. Fix: add those constants to the `sent` list in `test_prompts.py:190-194` (or add a sibling test), so the comment becomes true. | `grep -rn "labelled\|PAGE_LABELS" agent_worker/tests/test_{policy,validation,graph,retry_plumbing}.py` → nothing; `test_prompts.py:179-198` unchanged by the diff (CONFIRMED) | The fixed hint sentences are model-facing text sent on every retry. The first A2.1 conventions slipped labelled answers into the prompt in exactly this way. The comment tells a future editor a guard exists when it doesn't. | **Fixed.** `test_no_prompt_quotes_a_labelled_answer` now scans `_ADVICE`, `_REASON_ADVICE`, both last-attempt sentences and both `_HINT_INTRO`s. It immediately found a false positive: the labelled act "void" is a substring of "avoid" in the intros (the guard matches substrings), so the intros now say "fix them this time". Putting a labelled act name into a hint sentence fails the test (mutation). The scan was a promised guard, not a listed departure; it is now real. |
| 5 | nit | **Two details in how the hint reaches the model.** (a) Several finding messages, which are sent verbatim as hints, identify the show only by its internal index: "show 0 is marked free but also has an admission price", "show 3 has an act with no name". The model was never shown those numbers, and on the title-split route a status merge can shift them. `DATE_IMPLAUSIBLE` already names the date. Adding the date (or the title from `notes["titles"]`) to `FREE_WITH_PRICE` and `BLANK_ACT_NAME` would give the hint something the model can find. (b) The page hint ends with a single `"\n"` and the page text follows straight after it (`extraction.py:157`). An unhinted request keeps the instruction's blank line before the page, but the hinted one runs the last hint line into the first page line. An extra `"\n"` after the hint keeps the separation. | `validation.py:221,232`; worktree: `repr(instruction_for(replace(PIPELINE_CONFIG, retry_hint=…))[-120:])` ends `"…avoid them this time:\n- show 0 is marked free but also has an admission price\n"` (CONFIRMED) | A weaker tier-2 request than the design intends: A8 then measures a hint the model can't act on. No effect on attempt 1 (pinned). | **Fixed.** (a) The `FREE_WITH_PRICE` and `BLANK_ACT_NAME` messages name the show by its date, not by an index the model was never shown (`DATE_IMPLAUSIBLE` already did); test asserts it. (b) The hinted page instruction keeps the blank line before the page text (`"\n\n"` after the hint); test asserts the message ends `"\n\n" + page text`. |
| 6 | nit | **Test-file conventions (`AGENTS.md`, "Tests state what they prove").** `test_a_server_error_then_a_page_is_a_page` and `test_a_missing_local_file_is_a_fetch_error` (`test_retry_plumbing.py:302,334`) have no `Proves:` comment. Helpers with neither a docstring nor a comment: `sha`, `run`, `model_route`, `fetch`, `_extraction_dump` (`test_retry_plumbing.py`); `page`, `validate`, `codes` (`test_validation.py`); `error`, `evidence`, `record` (`test_policy.py`); `reached_reconcile`, `reached_escalate` (`test_graph.py`; the module docstring does explain these two); `run_zero_per_fixture`, `replay` (`test_validation_on_real_pages.py`); and `scripted_client`, `completions`, `message_text`, `listings_answer` in `fakes.py`. | AST scan of the five test files for a `Proves` line and for helper docstrings or comments (CONFIRMED) | Small. These are the "explain each helper and fixture in plain terms" the convention asks for. | **Fixed.** `Proves:` comments on the two named tests, and a plain-terms docstring on every helper the scan listed (`test_retry_plumbing`, `test_validation`, `test_policy`, `test_graph`, `test_validation_on_real_pages`, `fakes`: 19 in all). |
| 7 | nit | **D7's comment cites stale evidence.** `llm.py:43-46` justifies `max_retries=1` by "the 45 `a21-confirm` runs used 0 re-asks". The *current* pipeline (`a21-review2`, `a3-confirm`) uses one re-ask on Mortimer's on every run (`attempts_used: 2`, `parse_failures: 1`, deterministic at temperature 0). The decision still holds, since one re-ask is kept and the log says so. But the comment should state that Mortimer's spends that one re-ask every time, so `max_retries=1` leaves it no slack, and a change that adds a second schema failure there becomes a failed attempt. | `a3-confirm.json` and `a21-review2.json` runs: Mortimer's `attempts_used` 2; aggregate `parse_failures` 1 (CONFIRMED) | Someone who later lowers this to 0, trusting the comment, breaks Mortimer's on every run. | **Fixed.** `llm.py`'s comment now says Mortimer's spends the one re-ask on every run of the current pipeline (2 attempts, 1 parse failure, deterministic), so 1 is the minimum, not a margin. |
| 8 | nit | **The build plan says G25 closes when the gaps are filled.** `alpha-build-plan.md:194`: "Gaps G2–G6 and G25 are closed once the gaps are filled." G25 is built but **not adopted**, so `image_url` stays null on text pages whatever Ari fills, and the G25 bullet itself says so (line 207). Say "G2–G6 close once the gaps are filled; G25's mechanism is built and was measured not adoptable (D12)". | `alpha-build-plan.md:194,207` (CONFIRMED by reading) | A reader of the build plan expects image URLs after Ari's fill-in. | **Fixed.** `alpha-build-plan.md`: "Gaps G2–G6 are closed once the gaps are filled. G25's mechanism is built but was measured not adoptable (D12), so `image_url` stays null on text pages whatever is filled in." |
| 9 | nit | **`act_not_in_title` is now exercised on real data, and the real-page layer doesn't know.** `test_validation_on_real_pages.py:16-20` says the rule is not exercised on real data (7th St Entry's titles don't align in `a21-confirm`). In `a3-confirm`, the current pipeline, they align (30 and 30), and the warning catches a real wrong act: `'Devilsoundguy' not found in its title` against "Evilsoundguy". This is the first real-data evidence for A2.1's E3 guard. Consider replaying `a3-confirm` instead of, or as well as, `a21-confirm`, with a literal expecting that warning. At least correct the docstring, and record it in the log for A8. | Replay of `a3-confirm.json` model-route runs through `validation.check_act_in_title` (CONFIRMED) | The one deterministic guard on the 100%-accuracy field has real evidence that nothing pins, and the docstring understates the coverage. | **Fixed.** New local-only test `test_act_not_in_title_catches_a_real_wrong_act_in_the_current_pipelines_run` reads `a3-confirm.json` (30 titles, 30 shows on 7th St Entry) and expects exactly the `Devilsoundguy` / `Evilsoundguy` warning and no error; the module docstring now says which rule is not exercised on real data (only the title-scoped end-time repair). First real-data evidence for A2.1's E3, recorded here for A8. |

Rejected: none. All 9 findings were accepted.

**Test-suite result after the fixes** (observed): with the five gaps open, `make check` gives ruff clean, `mypy app/` clean, and pytest **113 failed, 463 passed (576 collected)**. All 113 are gap-driven: 110 raise `NotImplementedError("TODO(Ari)")` (67 in `validation.py`, Gaps B and C; 43 in `policy.py`, Gaps D and E) and 3 are exceptions escaping `extract_node` (Gap A). With each gap's pasted Code applied on a scratch copy: **576 passed, 0 failed**. `uv run mypy --follow-imports=silent` on `validation.py policy.py graph.py nodes.py state.py constants.py`: no issues. vitest (153) and `make contract-check` pass separately. Four more mutations of the fixes were caught.

Two things for Ari beyond the gaps: the all-stale-page question in finding 1, and two untracked paths, `.claude/settings.json` and `scripts/cloud-setup.sh`, which appeared at 18:08 during the review. Neither the reviewer nor I created them; they are not part of A3.

