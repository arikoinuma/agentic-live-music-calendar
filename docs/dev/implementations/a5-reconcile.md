# A5 — reconcile

**Status:** Done (Ari sign off) - Oct 19, 2026
**Date:** October 16, 2026 (plan); October 17, 2026 (decisions, implementation)
**Author model:** Claude Sonnet 5.5 (plan and plan-review resolution, October 16, 2026; implementation and code-review resolution, October 17, 2026)
**Reviewer model:** Claude Opus 5.5 (plan review round 1, October 16, 2026); Claude Opus 5.5 (code review round 1, October 17, 2026)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A5 (and A2.1's carried items: after-midnight times, cancelled and
postponed listings, two untimed shows on one date); `docs/arch/arch-initial.md` §7 ("Reconcile (insert / update /
delete / no-op)" and its outcome table); `docs/arch/requirements-initial.md` ("Agent Reconciliation", "Agent Artist
Creation & Matching", "Show", "Times after midnight", "Cancelled or postponed listings"); `docs/arch/data-model-initial.md`
§2 (`show`, `show_artist`, `artist`) and §3 (`audit_log`); `docs/references/fastapi-style-guide.md`; `apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D12` and the fill-in key points `K1`–`K5`; elsewhere they
are written `A5-D1`, `A5-K1` and so on (`docs/dev/conventions.md`). Review items are `A5-PR<round>-<n>` (plan
review) and `A5-CR<round>-<n>` (code review). Other plans' IDs carry their scope (`A4-D1`, `A3-D9`, `A2.1-D12`,
`v0.1-G6`).

**Branch.** `AGENTS.md` names the branch `a5-reconcile`. This session was assigned `claude/vigilant-keller-858dzn`,
so the plan, and later the code, land there. Rename on merge if you want the milestone name.

## Context

A4 made every run inspectable: an `agent_run` per venue, one `audit_log` row per node, the raw extraction in MongoDB.
`reconcile_node` is still the stub it was in Phase 6: it sets `reconcile_decision = "insert"` and returns. A5 makes it
the real thing, **deciding what should happen to the calendar** and writing nothing to it (A6's `commit_node` does
the writing; `arch-initial.md` §7 keeps them apart so a bad decision and a failed write are different failures in the
audit trail).

What reconcile decides, per venue run:

1. **For each show on the page:** is it already stored? If so, did anything change? Insert, update or no-op.
2. **For each stored show not on the page:** was it inside the date range this fetch actually covered? If so, remove
   it (soft: `status = 'removed'`). If not, leave it alone.
3. **For each act named:** is there already an `artist` row for it? Exact, none, or the ambiguous middle, where a
   language model decides (the one place in the pipeline where a model makes a database decision).
4. **Cancelled and postponed listings:** evidence about a stored show, not a show to display (`A2.1-D12`).

Two things make this milestone different from A4. First, it is the first place the worker **reads the calendar**, so
the context needs a reader, and an unreadable calendar has to stop the run rather than look empty (an empty read
turns every listing into an insert). Second, the dangerous failures here are *silent and destructive* ones: a soft
delete that removes shows because the page was short, not because they are gone; a duplicate artist; a show that
flips between insert and remove every night. Most of the design below exists to make those failures impossible
or visible.

A5 cannot observe its own effect on the calendar: nothing writes until A6. So its tests simulate the write, and its
real-world verification (Verification §4) shows decisions against an empty or hand-seeded database, not a
before-and-after calendar. That is stated again under "What is not covered".

### What A5 delivers

| Item (build plan A5) | Marking | Where it lands |
|---|---|---|
| Show matching on (venue, date, time) → insert / update / no-op | [fill-in] | `reconcile.match_shows` — **K1** |
| A show may have no `time`; what the composite key does with a null (the open decision) | [fill-in] | The same function, its null-time branch — **K1**; decision **D3** |
| A multi-listing day coming back as one show with per-act times (A2's eval) | [written] *(re-marked, see "Departures")* | Reconcile never assumes `time`; pinned by tests. A3's `possible_merge` finding already flags it |
| Set-diff soft delete within the covered date range | [fill-in] | `reconcile.removed_by_absence` — **K2**; the window is **D1** |
| Artist matching by name: exact, none, ambiguous | [fill-in] | `artist_match.classify_artist` — **K4** |
| The ambiguous-artist LLM branch inside `reconcile_node`, audited with `model_used` and `confidence` | [fill-in] | `artist_match.decide_ambiguous` — **K5**; rows written by `trace.audited` |
| Times after midnight: sort and match with the 5:00 AM cutoff in mind | [written] *(re-marked)* | `reconcile.night_sort_key`; the frontend already has `nightSortKey` (B3/B4) |
| Cancelled and postponed listings update the stored show; two untimed shows on one date tie-break on acts | [fill-in] + [written] | `reconcile.plan_for_listing` — **K3**; the act tie-break is inside **K1** |
| `sequence_number` derived from list position when the extraction leaves it null | [written] | `reconcile.lineup_for` |
| (A7 item, pulled forward) Unit tests for reconcile's decision logic against a seeded database | [written] | `tests/test_reconcile_db.py`, with `polyfactory` |

### Decisions already made (earlier in this project)

- **Match shows on (venue, date, time); never fuzzy.** A time change reads as a cancelled show plus a new one; a
  lineup change at the same key is an update (`arch-initial.md` §7; `requirements-initial.md`, "Agent
  Reconciliation": "If 8pm show disappears but then 9pm show appears, that's a time change, but then the above rule
  about marking the old show as cancelled and entering a new show applies").
- **Soft delete only within the date range the fetch actually covered** (`requirements-initial.md`;
  `data-model-initial.md` `show.status`). Pagination depth varies run to run (`arch-initial.md` §7).
- **Reconcile decides, commit writes** (`arch-initial.md` §7). `reconcile_node` touches no table.
- **The ambiguous-artist call is a branch inside `reconcile_node`, not a node** (`arch-initial.md` §7).
- **A show belongs to the night the venue lists it under; a time before 05:00 is after midnight of that night**
  (`requirements-initial.md`, "Times after midnight"; decided by Ari, October 11, 2026). The stored `date` is the
  listed night, so the key (date, time) needs no conversion.
- **Escalation is per page, all or nothing** (`arch-initial.md` §7, Validation and retry). A failed page never reaches
  reconcile, so reconcile can treat "the shows it was given" as the whole page *minus the excluded ones* (D1 uses this).
- **Artist matching is global, not metro-scoped** (`requirements-initial.md`, "Agent Artist Creation & Matching").
- **Graph nodes are sync bodies run in a thread; database work is awaited in the `trace.audited` wrapper**
  (`A4-D1`: "A5/A6 `await` their database work in the wrapper's context; they don't reopen this").

### What the code already gives reconcile

- `state.validated_extraction`: the shows to reconcile, repairs applied, excluded shows removed; the graph reaches
  reconcile only on a *passed* or *confirmed-empty* verdict (`graph.route_after_validate`, `policy.decide_route`).
- `state.validation.excluded` (positions in `state.extraction.shows`) and `validation.findings`, whose
  `Finding.code` says *why* a show was excluded (`EXCLUDED_NO_ACTS` or `DATE_OUT_OF_WINDOW`) — D1 depends on telling
  those apart.
- Each show may carry a `status` of `scheduled | cancelled | postponed` (the model route's status question and the
  JSON-LD route's `eventStatus`; `ShowExtraction` itself doesn't declare it, the pipeline's schema variant does, so
  reconcile reads it with a default, see "Known gotchas").
- `state.fetched_on` (the metro-local fetch date), `state.venue_id`, `state.calendar_url` (what `show.original_url`
  should hold).
- `fold_text` in `normalize.py` for comparing names; `NIGHT_CUTOFF` (05:00) in `sources/jsonld.py`.

## Decisions for Ari

**How to read this section.** Each decision is **one question** with two options. Each opens with a real-life
scenario, then names the fields and functions involved, then says what each option costs. The plan below is written
to the recommended option (A). **★ = it changes how the calendar behaves** and is yours to decide; **technical** =
it changes how the code is built, and I'd settle it myself, but a different answer changes what gets built.

**Words used here.** *The page* is the venue's calendar page (its `calendar_url`) as fetched in this run. A *listing*
is one entry on that page. A *stored show* is a row already in our `show` table from an earlier run. Reconcile
compares the two.

**Renumbered on October 17, 2026.** Ari asked that each decision hold exactly one decision, so the original D1–D9
were split and renumbered. **Plan review round 1 cites the old numbers**; this table maps them.

| Old (cited in review round 1) | Now |
|---|---|
| D1 (covered range) | D1 (window end) and D2 (empty page) |
| D2 (null-time matching) | D3; the rest are in "Settled details" |
| D3 (unstated field, admission) | D4 and D5 |
| D4 (cancelled and postponed) | D6 and D7 |
| D5 (artist matching) | D8, D9 and D12 |
| D6 (removal guard) | D10 |
| D7 (where the database read lives) | "Settled details" (Ari, October 17: not a decision) |
| D8 (audit rows) | D11 |
| D9 (`reconcile_decision` removed) | "Settled details" |

| # | Question | Kind | Recommendation | Status |
|---|---|---|---|---|
| D1 | How far does the page "reach" for deciding a show is gone? | ★ | A: the latest date it lists | **Decided A** (Ari, Oct 17) |
| D2 | What if the page is empty? | ★ | A: remove nothing | **Decided A** (Ari, Oct 17) |
| D3 | Is an untimed show the same show as a stored one? | ★ | A: yes when unambiguous | **Decided A** (Ari, Oct 17) |
| D4 | If the new listing leaves a field blank, do we erase what we stored? | ★ | A: keep the stored value | **Decided A** (Ari, Oct 17) |
| D5 | How do the three price fields update? | ★ | A: as one unit | **Decided A** (Ari, Oct 17) |
| D6 | How is a cancelled or postponed show stored? | ★ | A: reuse `removed` | **Decided A** (Ari, Oct 17) |
| D7 | If a removed show is listed again, what happens? | ★ | A: bring the same row back | **Decided A** (Ari, Oct 17) |
| D8 | When are two artist names "exactly the same"? | ★ | A: after tidying case, accents, "The", "&" | **Decided A** (Ari, Oct 17) |
| D9 | If the model is unsure about an artist, what do we do? | ★ | A: create a new artist | **Decided A** (Ari, Oct 17) |
| D10 | Do we guard against one run removing most of a venue's shows? | ★ | A: yes | **Decided A** (Ari, Oct 17) |
| D11 | What does reconcile write to the audit trail? | technical | A: a summary row plus one row per model decision | **Decided A** (Ari, Oct 17) |
| D12 | How do we measure "similar" artist names? | technical | A: Python `difflib`, no new dependency | **Decided A** (Ari, Oct 17) |

---

### D1 — How far does the page "reach" for deciding a show is gone? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario.** Today is Oct 17. The venue's page lists shows through Oct 31. We have a show stored for Nov 14 from
  an earlier run, when the page happened to list further. Is the Nov 14 show gone?
- **Option A — the window ends at the latest date the page lists.** The page says nothing about Nov 14, so the show
  is left alone. A stored Oct 20 show that is missing *is* removed, because the page reached Oct 20 and it isn't there.
  Technically: `reconcile.covered_window` returns `[fetched_on, latest date among the kept listings and the listings
  excluded for naming no act]`.
- **Option B — a fixed horizon, say 28 days.** Nov 14 would be removed even though the page never showed that far.
  A shallow fetch deletes good shows, and a deeper fetch the next day re-adds them as new rows.
- **Cost of A:** a show stored *beyond* the page's last listing, which the venue then drops, lingers until the page
  reaches that date again. A stale show up too long is the safe direction.
- *Later:* when fetch paginates, the window becomes the smaller of how deep fetch got and the last listing. That depth
  field doesn't exist yet and isn't added now.

### D2 — What if the page is empty? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario.** The venue's calendar plugin breaks and the page loads with no events, or says "no upcoming events".
  Validation lets it through as `confirmed_empty`. We have 12 future shows stored for this venue. Do they go?
- **Option A — remove nothing.** An empty page names no date, so there is no window to remove inside. The audit row
  records `coverage: null`.
- **Option B — treat it as "the venue has no shows" and remove every stored show from today on.**
- **Cost of A:** a venue that truly cancels everything keeps stale rows until a person looks.
- Why A is the safer side: your requirements call an empty list "the most dangerous output", because reconcile would
  remove every stored show.

### D3 — Is an untimed show the same show as a stored one? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario.** Terminal Bar's page lists shows with no times at all. Monday's run stores "Band X, Oct 24, no time".
  Tuesday's page lists "Band X, Oct 24, no time" again. Matching on (venue, date, time) with a blank time never
  finds the stored row (in SQL, blank is not equal to blank), so every night would add a fresh copy of Band X and
  remove yesterday's. A related case: on Wednesday the venue adds "8:00 PM" to that show. Same show, or a new one?
- **Option A — pair them when it is unambiguous.** Per date, if exactly one listing and one stored show are left
  unmatched and either has no time, they are the same show. If several are left, pair by shared act names, with a
  fixed tie-break order so the same input always pairs the same way. A time that appears later (blank → 8:00 PM) is
  an **update**, not remove + insert. Two *different* times (8 PM stored, 9 PM listed) never pair: the requirements
  already say that is a cancelled show plus a new one.
  Technically: `show.start_time` against the extraction's `time`, in `reconcile.match_shows` (**K1**).
- **Option B — never pair a blank time.** Always insert the new listing and remove the stored one. Simple, and it
  churns every untimed venue every night.
- **Cost of A:** one wrong pairing is possible. If a venue replaces an untimed show with a different band, untimed,
  and nothing else is left on that date, we call it the same show with a changed lineup (an update). The requirements
  already treat a lineup change at the same key as an update, so this is consistent.
- This was the build plan's open decision, which asked for your confirmation here.

### D4 — If the new listing leaves a field blank, do we erase what we stored? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario.** Monday's page said the show ends at 11 PM and had a poster. Tuesday's extraction has no end time and
  no poster, either because the model missed them or because the venue removed them. Does the stored show lose its end
  time and poster?
- **Option A — keep the stored value.** Only a *different, non-blank* value counts as a change. The same rule covers
  `start_time` (a blank time never clears a time) and a lineup's per-act set times. It follows the project's rule
  "missing is tolerated, wrong is not" (A3-D4).
  Technically: `reconcile.show_changes` over `end_time`, `image_url`, `start_time` and each act's `start_time`.
- **Option B — overwrite, so the database mirrors the latest page exactly.** A model hiccup on Tuesday erases
  Monday's good data, and the show flips between versions.
- **Cost of A:** when a venue really removes an end time, the pipeline can't clear it. A human edit can, once edits exist.
- Prices are handled by D5, not here.

### D5 — How do the three price fields update? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario 1.** A show is stored with a $20 door price. The venue now says "FREE". The listing has
  `free_admission = true` and no prices. If we kept each field separately (D4's rule), the row would be free *and* $20,
  which the table refuses (the `show_free_admission_check` constraint). The write in A6 would fail every night.
- **Scenario 2.** Stored: advance $20, door $25. Tuesday's page says only "$25 at the door". Is the advance price gone?
- **Option A — `admission_advance`, `admission_day` and `free_admission` update as one unit.** If the listing states
  *any* of them, it replaces all three (what it doesn't state becomes blank). If it states none, all three stay as
  stored. Scenario 1 becomes free with no prices. Scenario 2 clears the advance price.
- **Option B — fix only the conflict.** "Free" clears the prices, and a price clears "free", but a stored advance price
  stays when the listing mentions only the door price. Scenario 2 keeps the $20 advance price.
- **Cost of A:** a listing that mentions only the door price erases a real advance price. **Cost of B:** it can keep an
  advance price the venue stopped offering, and it is harder to explain.
- The reviewer found this as the plan's one blocker, which is why it is its own decision.

### D6 — How is a cancelled or postponed show stored? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario.** Last week we stored "Band Y, Oct 22". This week Mortimer's page shows "CANCELLED, Band Y, Oct 22".
  What does the database say?
- **Option A — reuse `removed`.** `show.status` today is `active` or `removed`, and the read API hides `removed`
  (your requirements: a cancelled listing is "not a show to display"). The reason, `cancelled` or `postponed`, is kept
  in the audit row. No migration. A cancelled listing that matches nothing stored is skipped, never inserted.
- **Option B — add a `cancelled` status.** A migration, an `api-contract.md` change and regenerated
  `api-types.ts`, so the app could later show a "Cancelled" badge.
- **Cost of A:** the app can't distinguish "cancelled" from "dropped" without reading the audit trail. Nothing planned
  needs it.

### D7 — If a removed show is listed again, what happens? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario.** Band Y's Oct 22 show was marked removed when Mortimer's cancelled it. A week later the venue un-cancels
  it and lists it as scheduled for the same date and time.
- **Option A — bring the same row back.** `status` goes from `removed` to `active`, the reason is `reappeared`, and the
  lineup updates if it changed. One row carries the show's whole history.
- **Option B — leave the removed row and insert a new one.** Two rows for one real show.
- **Cost of A:** a different show at the same date and time could reactivate an old row. Matching only considers a
  removed show after every active one has been paired, which limits that.

### D8 — When are two artist names "exactly the same"? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario.** The page says "The Hold Steady" and we have "Hold Steady". Or "Poliça" against "Polica". Or
  "Jenny Lake & Friends" against "Jenny Lake and Friends". Same artist, with no review?
- **Option A — yes, after tidying.** Names are compared after lower-casing, removing accents, reading `&` as `and`,
  dropping punctuation and dropping a leading "the". Equal tidied names are one artist, with no model call.
  Technically: `artist_match.artist_key`, used by `classify_artist` (**K4**).
- **Option B — only case and spacing.** Anything else goes to the model.
- **Cost of A:** two different acts that differ only by those details would merge (a hypothetical: a local band
  called "Wild" and another called "The Wild"). Cost of B: more model calls, and more rows in the audit trail, for names
  that are plainly the same.

### D9 — If the model is unsure about an artist match, what do we do? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario.** The page lists "Zhora Band". We have an artist "Zhora". They are similar but not equal, so reconcile
  asks the model: same act? The model answers "probably, 0.6", or declines to choose, or the call fails.
- **Option A — create a new artist.** The same applies when the model names an artist we didn't offer it. Below a
  confidence of 0.8 we don't link. Worst case is a duplicate artist, which is visible and revertable (merging is a
  deferred feature, `data-model-initial.md` §5). The fallback is written to the audit row.
  Technically: `artist_match.decide_ambiguous` (**K5**).
- **Option B — link to the best candidate anyway.** Fewer duplicates, but a wrong guess silently puts two acts on one
  artist page.
- **Cost of A:** more duplicate artists until merge exists.

### D10 — Do we guard against one run removing most of a venue's shows? ★ **Decided A (Ari, October 17, 2026)**

- **Scenario.** A venue's site glitches and returns half its calendar: of 8 shows in the window, 5 are missing. It
  passes validation, because half a calendar is still a calendar.
- **Option A — guard.** If absence would remove **3 or more** stored shows **and more than half** of the active stored
  shows in the window, those removals are withheld and the audit row says so. A cancellation the page states is
  evidence, not absence, and is never withheld. Both numbers live in `ReconcilePolicy`.
- **Option B — no guard.** Trust validation.
- **Cost of A:** a real mass removal (a venue closing for renovation) waits for a person.

### D11 — What does reconcile write to the audit trail? (technical) **Decided A (Ari, October 17, 2026)**

- **Scenario.** Months from now you ask: "why did the app think 'Zhora Band' was 'Zhora'?" Where is the answer?
- **Option A — one summary row per run, plus one row per model decision.** The summary row (entity = the venue) has the
  counts per action, the window, review flags and withheld removals. Each model decision gets its own row with
  `entity_type = artist`, `model_used`, `confidence` and the reason. A new saved query lists them. The per-show rows
  with before/after snapshots stay in A6's commit, because they record what was written.
- **Option B — also one row per show decision from reconcile.** More rows, and they overlap with commit's.

### D12 — How do we measure "similar" artist names? (technical) **Decided A (Ari, October 17, 2026)**

- **Scenario.** "Dessa" and "Desa" score 0.889 on Python's `difflib`; "Zhora" and "Zhora Band" score 0.667, which a
  ratio alone would miss.
- **Option A — `difflib` plus a word-containment rule, in Python, over all artists loaded per run.** No new dependency
  and no migration. Starting values, in a named `ArtistMatchPolicy`: ratio 0.85, up to three candidates shown to the
  model. A8 calibrates them against labelled data.
- **Option B — `rapidfuzz`** (a new dependency, same ratio). **Option C — Postgres `pg_trgm`** (a migration).
- **Cost of A:** loading every artist per run doesn't scale past a large table. Fine at alpha size.

---

### Settled details (veto only)

These follow from your requirements or from the decisions above. I'm listing them so nothing is hidden; object to any.

- **The window starts today.** Past shows are never removed (they fall off pages naturally). Shows up to 31 days back
  can still be *matched*.
- **A listing we left out still protects a stored show on its date.** The act splitter drops real shows, so "the
  validated list lacks it" is not "the page lacks it".
- **An implausible date can't stretch the window.** A year-2028 entry in a venue's structured data isn't evidence of
  reach.
- **Different non-blank times never pair** (8 PM stored, 9 PM listed). Your requirements: that is a cancelled show plus
  a new one.
- **A cancelled or postponed listing is never inserted,** and it pairs only on a timed key or shared acts, never on
  date alone.
- **Active stored shows are matched before removed ones.**
- **Ties between untimed shows break by listing order, then stored order,** and the pair is flagged for review so
  nothing churns.
- **`needs_review` is set only where a guess was involved,** and lives in the audit row only. No review queue yet.
- **Artists resolve once per distinct name per run,** and only for scheduled listings. The same artist twice in one
  show collapses to one lineup entry.
- **Artist model settings:** the question uses temperature 0 and the base model; confidence is bounded 0 to 1; an
  empty name key falls back to the plain folded name.
- **The resulting lineup is in performance order,** which is the order a stored lineup is read back in. Stated sequence numbers
  are kept only when every act has one and they are all different; otherwise the acts are numbered by list position.
- **On a tie, a scheduled listing takes the stored show before a cancelled or postponed one,** so a page carrying both for one
  show settles the same way every night. A guessed pairing is flagged as a whole (both halves), not just its first pair.
- **`reconcile_decision` leaves `VenueGraphState`, replaced by `reconcile_plan`.** The old field is a single value and
  can't describe a run that inserts three shows, updates two and removes one. It touches the audit stub,
  `commit_node`'s log line and the tests that read it.
- **The calendar read happens in the `trace.audited` wrapper, before the reconcile node runs,** through a
  `CalendarReader` on `WorkerContext`: the same pattern as the audit writer and the staging store, and the one A4-D1
  already chose (async database work is awaited in the wrapper; node bodies stay plain functions). The node is then
  tested with a hand-written list of stored shows, no database. **If the read fails, the run stops with an error**;
  reconcile never treats an unreadable calendar as an empty one, because that would insert a duplicate of every show.
  (Was D13; Ari removed it as a decision on October 17, 2026. The alternative, an async reconcile node that reads for
  itself, was already rejected in A4-D1.)

## Design

### The pure core: `agent_worker/reconcile.py`

No I/O, no model, no clock. Everything here is a function of its arguments, so every rule is tested with
hand-built data.

```
StoredShow       id, date, start_time, end_time, status, prices, free_admission, image_url, original_url,
                 lineup: tuple[StoredLineupEntry, ...]            # what the reader returns
StoredLineupEntry   artist_id, artist_name, start_time, sequence_number
KnownArtist      id, name                                         # all artists, for matching
Coverage         start, end                                       # the D1 window (end inclusive)
Listing          index, show (ShowExtraction), status             # a kept extracted show + its A2.1-D12 status
LineupEntry      artist: ArtistRef, start_time, sequence_number   # one act, resolved
Action           StrEnum: INSERT, UPDATE, NO_OP, REMOVE, SKIP     # .outcome → AuditOutcome (SKIP has none)
ShowDecision     action, listing | None, stored_id | None, changes: dict[str, tuple[old, new]],
                 lineup: tuple[LineupEntry, ...], reason, needs_review
ReconcilePlan    coverage | None, shows: tuple[ShowDecision, ...], artists: tuple[ArtistResolution, ...],
                 withheld: tuple[ShowDecision, ...]
ReconcilePolicy  max_removal_share = 0.5, min_removals_to_guard = 3     # D10; one named place, as RetryPolicy
```

The functions, in the order a reader should take them:

| Function | Job | Marking |
|---|---|---|
| `night_sort_key(date, time)` | Orders by listed night, with times before `NIGHT_CUTOFF` after the evening's, and **an untimed show last** (as the frontend's `nightSortKey` and the API do). Used wherever reconcile needs a deterministic order | [written] |
| `listings_from(extraction, validated)` | The kept shows as `Listing`s, with `status` read by `getattr(show, "status", "scheduled")` | [written] |
| `covered_window(kept, excluded_no_act_dates, fetched_on)` | D1, D2: `Coverage`, or `None` for a confirmed-empty page **or when every listed date is before `fetched_on`** (then `end < start`: no evidence of reach, so no window) | [written] |
| `load_request(kept, window, fetched_on)` | The range the reader loads (below) | [written] |
| `lineup_for(show, resolutions)` | Resolved lineup with sequence numbers: stated numbers are kept only if every act has one, otherwise all are renumbered by list position; the same artist twice collapses to the first | [written] |
| `match_shows(listings, stored)` | D3: active first, then removed for the leftovers; each round a timed pass and a null-time pass; returns pairs, the unpaired sides and which pairs/leftovers need review | **K1** |
| `plan_for_listing(listing, stored)` | What a listing means given its matched stored show (or none): insert, update, no-op, remove, skip, reactivate — the A2.1-D12 status rules | **K3** |
| `show_changes(stored, listing, lineup, original_url)` | D4, D5: comparison, `{field: (old, new)}`, empty = no-op. Prices compared as `Decimal(str(v)).quantize(0.01)`; admission as one unit | [written] |
| `removed_by_absence(stored, matched_ids, coverage, excluded_dates)` | D1: the soft delete | **K2** |
| `withhold_if_mass_removal(removals, in_window_active, policy)` | D10 | [written] |
| `build_plan(...)` | Orders the steps below and assembles the plan | [written] |

All of these take **plain arguments** (the extraction, the validation result, dates), not `VenueGraphState`:
`reconcile.py` must not import `state.py`, because `state.py` imports reconcile's types for its new fields.

**Import order** (`apps/api/AGENTS.md` asks for a DAG): `normalize`, `schemas`, `validation`, `llm`, `prompts` ←
`artist_match`, `reconcile` ← `state` ← `nodes`, `graph`, `trace`. `calendar_reader` imports `reconcile`'s dataclasses
and `app.db`; `context` imports `calendar_reader`'s protocol. `artist_match` needs `EXTRACTION_ERRORS` (K5), which
today lives in `nodes.py` (above `state`), so it **moves to `llm.py`** (where the client and its failure types
belong) and `nodes.py` imports it from there. A test imports `agent_worker.reconcile` and `agent_worker.artist_match`
in a fresh interpreter and asserts `agent_worker.state` is not in `sys.modules`.

`build_plan` order (each step's output feeds the next):

1. Match listings to stored shows (K1). It compares act *names* (`artist_key`), so it needs no artist resolution.
2. Resolve artists once per distinct `artist_key`, **only for scheduled listings** (cancelled and postponed listings
   never insert or update a lineup, so their acts cost no model call, create no artist and write no decision row):
   exact → none → ambiguous → model (`artist_match.py`).
3. Decide each listing's action (K3) and compute its changes (D4, D5).
4. Soft-delete stored shows absent from the page, inside the window (K2).
5. Apply the guard (D10).
6. Sort the decisions by `night_sort_key`, so the plan, and the audit row, read in calendar order.
   `plan.artists` contains only resolutions some decision references.

### The artist side: `agent_worker/artist_match.py`

Mirrors `status_check.py` and `act_split.py` (a narrow question, a schema, a pure function around the call).

- `artist_key(name)`, `classify_artist(name, known, policy)` → `Exact(artist_id)` | `Ambiguous(candidates)` | `New`
  (**K4**).
- `ArtistMatchAnswer` (schema the model fills: `matched_artist_id: int | None`, `confidence: float`, `reason: str`),
  `ask(incoming, candidates, client, options)`.
- `decide_ambiguous(...)` turns an answer (or a failed call) into an `ArtistResolution`: matched, or new with the
  fallback reason recorded (**K5**).
- `ArtistResolution`: `name`, `key`, `outcome` (`exact | new | matched_by_model | new_after_model`),
  `artist_id`, `decided_by` (`rule | model`), `model_used`, `confidence`, `candidates`, `reason`. The audit rows for
  model decisions are built from these.

### The reader: `agent_worker/calendar_reader.py`

`CalendarReader` protocol: `stored_shows(venue_id, start, end) -> list[StoredShow]` (shows in the range, **every
status**, with their lineups) and `artists() -> list[KnownArtist]`. `PostgresCalendarReader(session_factory)` uses a
short read-only session per call, as `PostgresAuditWriter` does. The query uses the `show (venue_id, date)` index
A1 added for exactly this (`app/db/models/calendar.py`).

**What the reader loads.** Matching needs stored shows on every *listing* date, and listings reach back up to 31 days
(pages keep last week's shows); removal needs only the window. So the range is
`[min(kept listing dates, fetched_on), max(kept listing dates, coverage.end)]` — wider than the window on the left. A
confirmed-empty page with no kept listings loads nothing. If it were just the window, every past listing would find no
stored twin and be inserted again every night, and those duplicates sit outside the removal window forever.

### The wiring

- `context.py`: `WorkerContext` gains `reader: CalendarReader`.
- `state.py`: `stored_shows`, `known_artists` (loaded by the wrapper), `reconcile_plan` (set by the node);
  `reconcile_decision` removed (see "Settled details").
- `trace.audited`: for `StepType.RECONCILE`, before the thread, compute `reconcile.load_request(...)` (from the state's validated extraction, validation result and fetch date, passed in as plain arguments), `await` the
  reader, put the results on the state; after the thread, write the summary row, then one row per model decision
  (`audit.model_decision_entries(state)`).
- `nodes.reconcile_node`: calls `build_plan` with the model client; sets `state.reconcile_plan`; logs a summary.
- `nodes.commit_node`: still a stub, now logging the plan's counts instead of the removed field.
- `audit.py`: `_detail` for `RECONCILE` (D11); `RECONCILE` joins `_VENUE_LEVEL`; `COMMIT` stays a stub row.
- `main.py` and `local_test.py`: build `PostgresCalendarReader(SessionFactory)`.

## Test approach (written first, watched fail, then made green)

Every test is written before its code and watched fail (build plan §3). Tests follow `AGENTS.md`: each opens with
`Proves:`, tests sit under labelled section comments, and the source of every expected value is stated. **Expected
values come from the requirements and the data model and from the literal inputs, never from the code under test.**
Four layers.

### 1. Pure show decisions (`agent_worker/tests/test_reconcile_shows.py`)

Hand-built `StoredShow`s and `Listing`s; no database, no model. Sources: `requirements-initial.md` "Agent
Reconciliation", `arch-initial.md` §7's outcome table, D3–D7.

- **Section: the composite key (K1)**
  - same date and time, same details → pair, `no_op`;
  - same date and time, different lineup → `update` (lineup change), not remove + insert;
  - 8 pm stored, 9 pm listed, same date → **no pair**: one `remove` and one `insert` (the requirements' own example);
  - null → 20:00 (stored untimed, listing timed) → `update` filling `start_time`, one pair;
  - 20:00 → null (stored timed, listing untimed), one of each on the date → pair, and `start_time` is **not**
    cleared (D4);
  - two untimed shows on one date, both stored: pair by shared acts (the 7th St Entry, October 31 case), even when
    the listings come in the opposite order;
  - two untimed, lineups changed completely: no pair, two inserts and two removal candidates, all `needs_review`;
  - two timed shows at the same time on one date: pair by shared acts, then lowest stored id;
  - a returning show: stored `removed`, listed `scheduled` → pair, `update` to `active`;
  - **a show with no `time` and per-act times** (A2's White Squirrel seed 2) reconciles without error and without
    inventing a show time.
- **Section: preferences and ties (D3)**
  - a stored `removed` twin and a stored `active` twin at the same key: the listing pairs with the **active** one;
  - a long-ago `removed` show on a date plus one active untimed show: an untimed listing with changed acts still pairs
    with the active one (an `update`, not remove + insert);
  - **two untimed shows by the same act on one date** (early and late): they pair by the order tie-break, flagged,
    and feeding the result back in gives all `no_op` (the idempotency test includes this input);
  - two shows at the same time on one date, two stored: assigned by overlap globally, so listing A (sharing acts with
    stored #2) gets #2 even though #1 is the lower id;
  - `needs_review` is **false** for an ordinary new timed show and an ordinary removal, **true** for the null-time and
    tie-break cases.
- **Section: cancelled and postponed (K3)**: the matrix from D6 and D7 — cancelled × {stored active → `remove`, stored
  removed → `no_op`, no stored → `skip`}, postponed the same, scheduled × {stored removed → reactivate}. The audit
  reason distinguishes `cancelled` from `postponed`. A `skip` creates no insert and no artist, and a cancelled listing naming an unknown artist makes **zero** model calls and no resolution. A cancelled listing with a null time and an unrelated stored show on its date does **not** pair (round 1, finding 3).
- **Section: what counts as a change (D4)**
  - a different price, end time or image → `update` with that field in `changes`; a null in any of them → unchanged;
  - prices compare as money: stored `Decimal("20.00")` equals extracted `20.0`; `19.99` differs;
  - `original_url` differing alone → `update` (the doc: "overwritten on each successful reconcile");
  - lineup order changed → `update`; the same names with the same order → `no_op`;
  - **idempotency:** feeding a plan's own result back in as the stored shows (a test-only simulator that mirrors what
    commit will do) gives all `no_op`s. This is the property that stops a show flipping nightly; A6 later replaces
    the simulator with a real round trip.
- **Section: admission is one unit (D5)**
  - stored `admission_day = 20`, listing `free_admission = True` with no prices → `update` to free with both prices
    null (never free-with-a-price);
  - stored `free_admission = True`, listing a day price with `free_admission` null → `update` to the price, free
    cleared;
  - a listing stating no admission value leaves all three as stored;
  - every merged result satisfies the table's CHECK (asserted by a helper that mirrors the constraint, named in the
    test as the data-model source).
  - a lineup whose per-act time went from stated to unstated → `no_op`, the time kept; a different non-null time →
    `update`.
- **Section: lineups**: `sequence_number` from list position when none is stated; stated numbers kept only when every
  act has one (a mix is renumbered, since mixing would collide); an artist named twice in one show appears once.
- **Section: after midnight**: `night_sort_key(Fri, 01:00)` sorts after `(Fri, 20:00)` and before `(Sat, 20:00)`; the
  cutoff itself (05:00) is evening, 04:59 is after midnight; an untimed show sorts last on its night; a 01:00 show listed under Friday and stored under
  Friday matches by the plain key, with no date arithmetic.

### 2. Pure soft delete and the guard (`agent_worker/tests/test_reconcile_removal.py`)

Sources: `requirements-initial.md` ("falling within the date range that fetch actually covered"), D1, D2, D10.

- **Section: the window (K2)**
  - a stored active show on a covered date and absent from the page → removed;
  - **a stored show dated after the page's last listed date is untouched** (the subtle half of the lesson);
  - a stored show dated before `fetched_on` is untouched (past shows fall off pages);
  - a show dated exactly on `fetched_on`, and one exactly on the last listed date, are inside (inclusive both ends);
  - an already-`removed` stored show is never removed again;
  - **an excluded listing on a stored show's date protects it** (the splitter may have dropped it); an excluded
    listing on another date doesn't;
  - an out-of-window excluded listing (a 2028 JSON-LD entry) does not stretch the window.
- **Section: what is loaded and how wide the window is**
  - `covered_window` is `None` when every listed date is before `fetched_on` (a page showing only last week);
  - `load_request` reaches back to the earliest kept listing date even when it is before `fetched_on`;
  - **a listing dated before `fetched_on` with a stored twin gives `no_op`, not `insert`** (the whole-plan version of
    this runs in `test_reconcile_db.py`).
- **Section: the empty page**: `covered_window` is `None` for a confirmed-empty page, so nothing is removed, the plan
  says `coverage: None`, and stored shows are untouched. A page with only cancelled listings still has a window.
- **Section: the guard (D10)**: 3 of 4 in-window active shows missing → all three withheld and none removed; 2 of 4
  missing → removed (below the minimum); 3 of 8 missing → removed (not more than half); a cancelled listing's removal
  is never withheld; the plan lists what was withheld.

### 3. Artists (`agent_worker/tests/test_artist_match.py`)

Sources: `requirements-initial.md` "Agent Artist Creation & Matching"; D8, D9, D12; the difflib ratios in D12 (measured, not
assumed).

- **Section: classification (K4)**: exact on case, accents, a leading "The", `&` vs `and`, spacing; ambiguous on
  `Dessa`/`Desa` and `Low`/`Lowe` (ratio), on `Zhora`/`Zhora Band` (containment); none on `Zhora`/`Prince`.
  Boundary: a policy with `ratio = 0.9` turns `Low`/`Lowe` into `New`, proving the threshold is read from the policy,
  not hard-coded. Two stored artists with equal keys → exact, lowest id, and the duplicate is reported.
- **Section: keys**: `!!!` does not match `???`, and a name that is only punctuation never reaches the containment
  rule (the empty-key fallback).
- **Section: the model branch (K5)**, with `fakes.ScriptedClient` (a new `ARTIST_MATCH` script key): "same, 0.93,
  id 7" → `matched_by_model`, id 7; "different" → `new_after_model`; "same" at 0.6 (below `min_confidence`) →
  `new_after_model`; a raised `InstructorError` → `new_after_model`, with the error text in the reason and no
  exception out; an out-of-range confidence (1.7) is a validation error, not a match; an answer naming an id that wasn't offered → `new_after_model` (a model can hallucinate an id; it
  must not reach the database).
- **Section: once per name**: the same incoming name on two shows triggers **one** model call and one resolution; a
  name that is exact makes **zero** calls.
- **Section: new artists**: three shows naming the same unknown artist produce one `New` resolution used three times.

### 4. The graph, the audit rows and the real database

- **`tests/test_graph_reconcile.py`** (in-memory fakes: `RecordingAudit`, `RecordingStager`, and a new
  `FakeReader` that returns scripted stored shows and artists): the real compiled graph on a clean JSON-LD page.
  - A first run (empty calendar): the plan is all `insert`; the reconcile audit row is venue-level with
    `detail.counts = {insert: n, ...}` and `detail.coverage`.
  - A second run with `FakeReader` returning that run's result: all `no_op`.
  - A cancelled listing for a stored show: one `remove`, reason `cancelled`.
  - One ambiguous artist with a scripted "same" answer: **two** reconcile rows, the summary and one artist-decision
    row carrying `entity_type = artist`, `model_used`, `confidence`; `RecordingAudit` shows them in that order.
  - **A reader that raises propagates out of `ainvoke` and no reconcile row is written** ("Settled details": an unreadable calendar
    must not look empty).
  - The existing context-injection test (`test_the_context_reaches_the_audited_nodes`) still passes with the new
    `reader` field.
- **`tests/test_audit_entries.py` (updated):** reconcile now names the venue as its entity; its `detail` is the D11
  shape (keys listed in the test); `model_decision_entries` builds the artist rows: `entity_type = artist`,
  `model_used` from the resolution, `confidence` through `audit_confidence` (a `None` stays `NULL`, A3-D9), and the
  JSON-serializable check from A4 extends to them.
- **`tests/test_calendar_reader.py`** (Postgres, `db_session`): `stored_shows` returns shows in the range with
  lineups ordered by sequence, **including `removed` ones**; excludes other venues and out-of-range dates; `artists()`
  returns every artist. Seeded with `polyfactory` factories **for the filler columns only** (fixed seed; build plan A7 names `polyfactory` as unused since Phase 3, and this is its first consumer). Artist names and show dates are set explicitly in each test: random names could land in the ambiguous band and trigger an unscripted model call (`ScriptedCompletions` raises on one), and random dates would make the expected outcomes depend on the code under test.
- **`tests/test_reconcile_db.py`** (Postgres): the whole decision logic against a database seeded the way a venue
  looks after weeks of runs (the A7 item, pulled forward): insert, update, no-op and soft delete in one plan; a
  returning removed show; an artist found by `Poliça` vs `Polica`.
- **`tests/test_audit_queries.py` (extended):** the new saved query `artist_match_decisions` runs against a scripted
  run that made one model decision, and returns exactly that row (and none from a run that made none).
- **Existing tests:** every `WorkerContext(...)` call site gains `reader=` (listed in "Critical files");
  `test_graph.py`'s `reconcile_ran` helper currently reads `state.reconcile_decision`, which the plan removes ("Settled details"), so it reads
  `state.reconcile_plan is not None`.

### What is not covered, stated plainly

- **The model on real data.** The cloud sandbox has no Ollama. The ambiguous-artist prompt is tested for what it
  sends and how its answer is handled, with a scripted client; whether the real model answers well is unmeasured. The
  thresholds in D12 are starting values, to be calibrated in A8. Ari runs the live check locally (Verification §5).
- **A real before-and-after calendar.** Nothing writes until A6. The idempotency test uses a simulator of the write; a
  real database round trip is A6's test.
- **Pagination.** Fetch is one page. The window is derived from the listings (D1); when fetch paginates, the
  window becomes the smaller of the reached depth and the last listing.
- **Concurrency.** Two workers reconciling one venue at once (H-phase) would race on stored shows; the alpha runs
  venues one after another.

### Known gotchas to handle up front

- **`ShowExtraction` doesn't declare `status`.** The pipeline's schema variant (`schemas.show_model(status=True, ...)`)
  does. Read it with `getattr(show, "status", "scheduled")`; a direct `.status` fails the type checker and the
  image route (no status). A test builds both kinds of show.
- **`validation.excluded` is a list of positions in `state.extraction.shows`, not in `validated_extraction.shows`.**
  They differ whenever a show is excluded. D1's protection and reach logic read the raw list; reading the wrong one
  silently protects the wrong dates. A test excludes a show in the middle of the list.
- **The state crosses a thread.** The wrapper puts `stored_shows` and `known_artists` on the state *before*
  `asyncio.to_thread`, and the node reads them; it never touches the database (A4-D1).
- **`StoredShow.start_time` vs the extraction's `time`.** The extraction field is `time`; the column is
  `start_time` (build plan A5, "reconcile maps it"). The mapping lives in one place (`show_changes`).
- **Prices.** Extraction carries `float | None`, the column `Numeric(10, 2)`. Comparison converts with
  `Decimal(str(v)).quantize(Decimal("0.01"))`, the conversion A6 will use for the write (A6's [written] price item);
  it is defined once, in `reconcile.py`, and A6 imports it.
- **`NIGHT_CUTOFF` lives in `sources/jsonld.py`.** Reconcile imports it from there rather than redefining a second
  05:00. Moving it to `constants.py` would be tidier and touches a route A2.1 owns; noted, not done.
- **`local_test.py` runs a fixture path as `calendar_url`**, so `original_url` in the plan will be a file path on
  that run. Harmless while nothing writes; A6 should know.

## Implementation steps

### Working protocol for [fill-in] steps

The scaffold is complete except for five `TODO(Ari)` blocks (K1–K5). Each fails loudly with
`raise NotImplementedError("TODO(Ari)")`, so its tests are red, not accidentally green. Everything else, including
the tests for the gaps, is written. "Go ahead" or `/build-milestone` produces the scaffold. A gap is filled only when
Ari asks for it by name; the cleanup pass (`AGENTS.md`, step 4) follows.

### TODO(Ari) gaps

**Fill order:** K4 → K1 → K3 → K2 → K5. K4 is a pure classifier (its tests need nothing else). K1 and K3 need only
hand-built data. K2 needs K1's `matched_ids`. K5 needs K4. **`build_plan` calls all five, so every test that runs the
whole plan (the graph tests, the DB test, the idempotency test) is red until all five are filled**; the pure tests
for each gap go green as that gap closes. The Implementation log will list the red tests by file.

- **K1 — the composite-key match, in `reconcile.py` (`match_shows`).** *(Build plan items 1 and 3; D3.)*
  - *Lesson:* the key is (venue, date, time), exact, with no fuzzy matching on shows (`arch-initial.md` §7), and the
    whole subtlety is what a **null** does. In SQL `NULL = NULL` is not true, so a naive key never finds an untimed
    show: every night would insert a duplicate and remove the old one. The rule is: two different times never pair
    (that is a time change); a null on either side pairs only when it is unambiguous (one listing, one stored show on
    the date) or when shared acts settle it, and a tie is broken the same way every run so nothing churns. Anything
    unpaired is flagged, not guessed.
  - *Code:* written around the gap — the grouping by date, the active-then-removed rounds, the timed pass, the
    consumed-set bookkeeping, and `_assign_by_acts` (global assignment by overlap, then order). The gap is the
    null-time pass:
    ```python
    # leftovers on this date: ls (listings), ss (stored shows), both sorted by night_sort_key / id
    pairable = [(l, s) for l in ls for s in ss if l.show.time is None or s.start_time is None]
    if len(ls) == 1 and len(ss) == 1 and pairable and l_is_scheduled(ls[0]):
        pairs.append(pairable[0])
    else:
        pairs += _assign_by_acts(pairable)    # written: needs >= 1 shared act; overlap desc, then order
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_reconcile_shows.py -k "composite or null or untimed or tie"`. The
    likeliest mistake is pairing *any* leftover listing with *any* leftover stored show on the date, which turns an
    8 pm → 9 pm change into an update (the requirements say it is remove + insert); the 8 pm / 9 pm test catches it.
    The second likeliest is `l.show.time == s.start_time` for the null case instead of "either side is null": it is
    `True` for two nulls (`None == None` in Python, unlike SQL) but `False` for null-against-timed, so the
    **null → 20:00 and 20:00 → null** tests are the ones that go red.

- **K2 — the soft delete, in `reconcile.py` (`removed_by_absence`).** *(Build plan item 4; D1, D2.)*
  - *Lesson:* a show is removed because the **page** no longer lists it, and only if the fetch **reached** its date
    (`data-model-initial.md`, `show.status`; `requirements-initial.md`, "falling within the date range that fetch
    actually covered"). "Absent from the validated list" is not "absent from the page": excluded listings are still on
    the page. And a show beyond the last listed date is not absent, it is out of sight.
  - *Code:*
    ```python
    if coverage is None:           # confirmed-empty page: no evidence of reach, so no removal
        return []
    return [
        s for s in stored
        if s.status is ShowStatus.ACTIVE
        and coverage.start <= s.date <= coverage.end
        and s.id not in matched_ids
        and s.date not in excluded_dates          # a listing we left out may be this show
    ]
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_reconcile_removal.py -k window`. The likeliest mistake is
    dropping the `coverage` bounds (the "beyond the last listed date is untouched" test fails: it would remove every
    show past the page's horizon); the second is forgetting `s.status`, which "removes" an already-removed show and
    writes a pointless audit row.

- **K3 — what a cancelled or postponed listing means, in `reconcile.py` (`plan_for_listing`).** *(Build plan item 8;
  D6, D7; `A2.1-D12`.)*
  - *Lesson:* a cancelled or postponed listing is **evidence about a stored show, not a show**
    (`requirements-initial.md`: "the agent has to match it to that stored record and update it"). It must never be
    inserted. The status decides *what the match means*, which is why the answer depends on both the listing and the
    stored show. **The gap is only the non-scheduled branch**; the scheduled path (insert, reactivate a removed show,
    compare the details) is written and runs while the gap is open, so the scheduled tests stay green.
  - *Code:*
    ```python
    if listing.status != "scheduled":              # cancelled / postponed
        if stored is None:
            return ShowDecision(Action.SKIP, ..., reason=f"{listing.status} listing, no stored show")
        if stored.status is ShowStatus.ACTIVE:
            return ShowDecision(Action.REMOVE, ..., reason=listing.status)
        return ShowDecision(Action.NO_OP, ..., reason=f"already removed ({listing.status})")
    ```
    (Written below the gap, for contrast: a scheduled listing with no stored show is an `INSERT`; one that matches a
    `removed` show is an `UPDATE` back to `active`, reason `reappeared`; otherwise `show_changes` decides update or
    no-op.)
  - *Check:* `uv run pytest agent_worker/tests/test_reconcile_shows.py -k "cancelled or postponed"`. The likeliest
    mistake is falling through to `INSERT` for a cancelled listing with no stored show; the `skip` test catches it.

- **K4 — classify an artist name, in `artist_match.py` (`classify_artist`).** *(Build plan item 5; D8, D12.)*
  - *Lesson:* "clear matches and clear non-matches resolve automatically; ambiguous matches go through a review step
    rather than a fixed rule" (`requirements-initial.md`). That is a **three-way** answer, not a similarity score with
    one cut-off, and the middle band is deliberately where the model is used. A two-way rule is wrong in one
    direction either way: too loose merges two acts, too strict duplicates one.
  - *Code:*
    ```python
    key = artist_key(name)
    exact = sorted(a.id for a in known if artist_key(a.name) == key)
    if exact:
        return Exact(artist_id=exact[0], duplicates=tuple(exact[1:]))
    close = [
        (a, _similarity(key, artist_key(a.name))) for a in known
        if _is_close(key, artist_key(a.name), policy)       # ratio >= policy.ratio or word containment
    ]
    close.sort(key=lambda pair: (-pair[1], pair[0].id))
    return Ambiguous(candidates=tuple(a for a, _ in close[: policy.max_candidates])) if close else New()
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_artist_match.py -k classification`. The likeliest mistake is
    returning `Exact` for the best *similar* name (merging `Dessa` into `Desa` with no review); the ambiguous-band
    tests catch it.

- **K5 — the model decides the ambiguous case, with the conservative fallback, in `artist_match.py`
  (`decide_ambiguous`).** *(Build plan item 6; D9, D11.)*
  - *Lesson:* this is the one place in the pipeline where a model makes a database decision, so the failure direction
    is a design decision, not an accident. A wrong merge is silent and spreads (two acts share one page); a
    duplicate is visible and revertable. So low confidence, a refusal, a hallucinated id and a failed call **all**
    resolve to "new artist", and the resolution records *why*, which `trace.audited` turns into the audit row.
  - *Code:*
    ```python
    try:
        answer = ask(name, candidates, client=client, options=options)
    except EXTRACTION_ERRORS as err:
        return _new(name, reason=f"model call failed: {type(err).__name__}: {err}")
    offered = {c.id for c in candidates}
    if answer.matched_artist_id in offered and answer.confidence >= policy.min_confidence:
        return _matched(name, answer, model=options.model)
    return _new(name, reason=answer.reason, answer=answer)      # different, unsure, or an id nobody offered
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_artist_match.py -k model_branch`. The likeliest mistake is
    trusting `matched_artist_id` without checking it was offered (the hallucinated-id test catches it); the second is
    catching bare `Exception`, which would hide a bug in our own code as a "failed call" (`apps/api/AGENTS.md`).

### 1. Schema (written): none

No migration. `show_status` keeps `active | removed` (D6), `audit_log.entity_type` already has `artist`, `show.original_url`
exists. `app/schemas.py` is untouched, so `make types` / `make fixtures` have nothing to regenerate and there is no
B-track impact. Stated because the build plan's gate for schema changes is "their own early PR".

### 2. `agent_worker/reconcile.py` (written, except K1–K3)

The dataclasses, `ReconcilePolicy`, `night_sort_key`, `listings_from`, `covered_window`, `lineup_for`,
`show_changes`, `withhold_if_mass_removal`, `build_plan`, `load_request`. A module docstring says what reconcile is and
the order to read it in (as `validation.py` does); each function says what it is for.

### 3. `agent_worker/artist_match.py` (written, except K4–K5)

`artist_key`, the schema and `ask` (prompt text in `prompts.py` beside the act splitter's, with a test that pins what
it contains: the incoming name, the candidates with ids, the instruction to answer null when unsure), the
resolution type, and `resolve_artists` (once per distinct key, caching the answer).

### 4. `agent_worker/calendar_reader.py` (written)

The protocol and `PostgresCalendarReader`. One query for the shows with their lineups (a join, ordered), one for the
artists.

### 5. Wiring (written)

`context.py`, `state.py`, `trace.py`, `nodes.py`, `audit.py`, `llm.py` (`EXTRACTION_ERRORS` moves here from `nodes.py`, see "Import order"), `main.py`, `local_test.py`, and the fakes
(`FakeReader`, the `ARTIST_MATCH` script key). `trace.audited` keeps its comment block style: the new reconcile branch
says why the read happens before the thread and why a reader error is not swallowed.

### 6. `docs/dev/audit-queries.sql` (written)

The header comment lists the `reconcile` row's `detail` keys (it is the source of truth for readers of the file). A fifth
query, `artist_match_decisions` ("which artists did the model decide, and what did it say"), selects the reconcile
rows with `entity_type = 'artist'`, joined to the run's venue. It uses `CAST(... AS ...)`, not `::`, like the others.

### 7. Docs and bookkeeping (written)

- `alpha-build-plan.md`: tick A5; record the departures below; mark the A7 reconcile-test item done.
- `arch-initial.md` §7: a short "Built in A5" paragraph after A4's: the window rule, the null-time rule, the
  cancelled mapping, the guard, and the departure that reconcile's database read is in the wrapper.
- `data-model-initial.md`: under `show.status`, one sentence: cancelled and postponed listings are stored as `removed`,
  with the distinction in the audit trail (D6).
- `conventions.md`: add `A4` and `A5` to the scope table (A4 was missing).
- `apps/api/AGENTS.md`: the worker paragraph gets reconcile's module map and the "an unreadable calendar stops the
  run" rule.
- `notes.md`: append anything non-obvious the build turns up (the `excluded` index trap is a candidate).

### Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **Three A5 bullets are re-marked [written]** (the bar in `AGENTS.md`: "choose lines where the concept lives"):
   - *"Reconcile must not assume a show has a `time`"* is satisfied by K1's design and pinned by tests; there is no
     separate line of code that carries a lesson.
   - *"Times after midnight: sort and match with that in mind"* is `night_sort_key`, two lines over a decided rule.
     The matching needs nothing (the stored date is the listed night). The frontend part ("have B3/B4 display it")
     is already done: `lib/dates.ts` `nightSortKey`, `formatShowTime`.
   - *`sequence_number` from list position* is a rule, not a concept.
   Ari may re-mark any of them [fill-in] at approval.
2. **The window is derived in reconcile, not carried from fetch** (D1). The build plan says the state should carry how
   far the run reached; with one-page fetch there is nothing to carry beyond the listings themselves.
3. **A7's "unit tests for reconcile's decision logic against a seeded database" is done in A5**, tests-first, as the
   cycle requires. A7 keeps the fake-model-client and mypy items.
4. **`reconcile_decision` is removed from the state** ("Settled details").
5. **The "deterministic or LLM" distinction in the audit trail** (`arch-initial.md` §7, "Audit trail extensions") is
   carried by one row per model decision plus `decided_by` in the summary, not by a column (D11).

## Critical files

| File | Change |
|---|---|
| `apps/api/agent_worker/reconcile.py` (new) | The pure core — K1, K2, K3 |
| `apps/api/agent_worker/artist_match.py` (new) | Names, classification, the model question — K4, K5 |
| `apps/api/agent_worker/calendar_reader.py` (new) | `CalendarReader`, `PostgresCalendarReader` |
| `apps/api/agent_worker/prompts.py` | The artist-match prompt |
| `apps/api/agent_worker/llm.py` | `EXTRACTION_ERRORS` moved here (import order) |
| `apps/api/agent_worker/state.py` | `stored_shows`, `known_artists`, `reconcile_plan`; `reconcile_decision` removed |
| `apps/api/agent_worker/context.py` | `reader` |
| `apps/api/agent_worker/trace.py` | The reconcile read before the thread; the model-decision rows after |
| `apps/api/agent_worker/audit.py` | Reconcile `detail`; `model_decision_entries`; `RECONCILE` venue-level |
| `apps/api/agent_worker/nodes.py` | `reconcile_node` real; `commit_node` log line |
| `apps/api/agent_worker/main.py`, `local_test.py` | Build the reader; `local_test` prints the plan's counts |
| `apps/api/agent_worker/tests/` | `test_reconcile_shows`, `test_reconcile_removal`, `test_artist_match`, `test_graph_reconcile`, `test_calendar_reader`, `test_reconcile_db` (new); `fakes.py`, `test_audit_entries`, `test_audit_queries`, `test_graph`, `test_graph_audit`, `test_run_venue` (updated: the new `WorkerContext` field, `reconcile_decision`) |
| `docs/dev/audit-queries.sql` | Reconcile keys in the header; `artist_match_decisions` |
| Docs listed in step 7 | Bookkeeping |

## Verification

**In the cloud session (this author's):**

1. `make check`. Baseline before A5, measured October 16, 2026: **669 passed, 15 skipped** for the API suite. Expect
   red, by design, wherever a test runs the whole plan (K1–K5 all feed `build_plan`): `test_graph_reconcile`,
   `test_reconcile_db`, the idempotency test, and every graph-running test that reaches reconcile (`test_graph.py`,
   `test_graph_audit.py`, `test_run_venue.py`, `test_audit_queries.py`) until the gaps are filled. The pure tests for
   each gap are red until that gap is filled and everything else must be green. The Implementation log lists the red
   tests by file with the reason. The JS suite is untouched.
2. Gaps verified filled on a scratch copy (a throwaway `git worktree`, removed afterwards): with all five filled the
   whole suite is green, and the result is recorded in the Implementation log (the A3/A4 pattern).
3. No migration, so no `alembic` round trip; `make contract-check` stays green (no schema change).

**Locally (Ari, after filling the gaps; needs Docker and Ollama):**

4. `make db-reset && make seed`, then `cd apps/api && uv run python -m agent_worker.local_test`. Expect the printed
   plan counts: against the empty calendar, every show is an `insert`, `coverage` runs from the fixture's fetch date
   to its last listing, and the audit trail has a `reconcile` row whose `detail` shows the counts. Run it twice: the
   second plan is **still all inserts**, because commit is a stub (A6); that is expected, and is why A5 cannot be
   verified end to end until A6.
5. The model branch: seed one artist by hand whose name is close to one on the fixture (`make db-shell`:
   `INSERT INTO artist (name) VALUES ('<a fixture act, slightly altered>')`), re-run, and check the new
   `artist_match_decisions` query returns the model's answer, confidence and reason. This is the only check of whether
   the real model answers this question sensibly (unmeasured; A8 calibrates).
6. Seed a stored show by hand on a date inside the fixture's range that the page doesn't list, re-run, and check the
   plan removes it, and one *after* the page's last date, and check it is left alone.

**Local results (October 19, 2026).** Run by Claude Haiku 5.5 at Ari's request, on Ari's machine: Postgres 18 and
MongoDB 7.0 from `docker compose`, Ollama serving `gemma4-e4b-32k` (`MODEL_NAME` in `apps/api/.env`), the saved White
Squirrel fixture with `fetched_on` August 17, 2026, the JSON-LD route. Each step ran `local_test` and read the printed
plan, the `reconcile` audit rows and the database.

- **Step 4, runs 1 and 2** (after `make db-reset`, then `make seed`; no artists, no shows). Both runs passed validation on
  the first attempt. Both plans: 12 `insert`, 0 `update`, 0 `no_op`, 0 `remove`, 0 `skip`; coverage August 17 to
  August 22, 2026; 0 withheld; 27 artists resolved `new` by rule, 0 `exact`, 0 model calls. Both runs are the same plan,
  so the second run is still all inserts, as expected while commit is a stub. Run 1 was started by mistake with its
  output discarded; it is counted here because it gave the same plan as the run the plan asks for.
- **Step 5, run 3** (`INSERT INTO artist (name) VALUES ('Nat Harriett')`, id 1). The plan is unchanged at 12 inserts.
  One model decision, for "Nat Harriet" (similarity 0.957, so ambiguous): `matched_by_model`, `artist_id` 1,
  `model_used` `gemma4-e4b-32k`, `confidence` 0.950, reason "The names are extremely similar, suggesting a minor
  spelling variation of the same artist.", candidates `[{"id": 1, "name": "Nat Harriett"}]`. The other 26 names
  resolved `new` by rule with no model call. The `artist_match_decisions` query returns exactly that row.
- **Step 6, run 4** (stored shows seeded by hand at venue 1: August 19, 2026 at 23:00, id 1; August 25, 2026 at 20:00,
  id 2; both `active`). The plan has 12 inserts and 1 `remove`: stored show 1, reason "absent from the page", inside
  the window. Stored show 2 is not in the plan at all: it is after the window's end (August 22), and the reader loads
  only August 17 to August 22, so it was never read. 0 withheld. Both rows are still `active` in the database, as
  expected while commit is a stub.
- **Deviation from step 6.** The fixture lists every date from August 17 to August 22, so there is no date inside the
  range that the page does not list at all. The stored show used a time the page does not list on a listed date.
  Under the "two different times never pair" rule (A5-D3), that is absent, and the result matches what the step checks.
- **Audit trail.** Four runs, each with a venue-level `reconcile` row; runs 3 and 4 also have the artist decision row.
- **Left in the local database after these runs:** artist 1 (Nat Harriett) and shows 1 and 2. `make db-reset` clears them.
- **Still open:** all of this checks the decisions, not the calendar. Nothing was written to `show` or `event`; that is A6.

## Not doing in A5

- **Writing to the calendar** — A6 (`commit_node`, the per-show `audit_log` rows with `previous_value` /
  `new_value`, the price conversion at the write, the `event` rows, `show.original_url`).
- **A decision memory for ambiguous artists** (an alias table, so the model isn't re-asked each night about
  the same pair). The cost is a model call per ambiguous name per run, deterministic at temperature 0, and
  rare. It is the same gap as artist merge/de-duplication (`data-model-initial.md` §5); the schema change belongs to
  that feature.
- **`pg_trgm` / `rapidfuzz`** for artist similarity (D12), until the artist table is large enough for the Python scan
  to matter.
- **Pagination-aware coverage** (D1), until fetch paginates.
- **Concurrency control** between workers on one venue.
- **A `needs_review` queue.** The flags are in the audit row only; a review UI or queue is a later feature
  (`requirements-initial.md`, "Manual & Flagged Re-processing").
- **Moving `NIGHT_CUTOFF` to `constants.py`** (see Known gotchas).
- **Changing the frontend or the read API.** B3/B4 already order and display after-midnight times; the read routes
  are still on `sample_data.py` (A1b), and ordering there is that milestone's.

## Approval

**Ari, October 17, 2026:** decided D1 (window end = the latest date the page lists) and D2 (an empty page removes nothing), both as recommended (option A). **Ari, October 17, 2026 (later):** decided D3 through D12, all as recommended (option A). D13 (where the database read lives) was removed as a decision at Ari's request and listed under "Settled details". **All twelve decisions are closed.**

**Ari, October 17, 2026: approved the plan** ("The plan is approved. /build-milestone docs/dev/implementations/a5-reconcile.md"). The status was set to `Approved` by `/build-milestone` at step 0 and recorded here after code review round 1 found the approval was missing from the file (A5-CR1-4). No [written] item was re-marked [fill-in] or the reverse at approval.

**Ari, October 19, 2026: signed off. A5 is Done.** Ari filled the five key points himself (A5-K1 to A5-K5, commit `efe95ca`) and ran
the local verification (Postgres 18, MongoDB 7.0, Ollama with `gemma4-e4b-32k`; recorded in the Implementation log, commit `7153119`),
which found everything in order. Plan review round 1 (16 findings) and code review round 1 (9 findings) are both fully resolved. Not
verified, and not claimed: reconcile's effect on the calendar itself, since nothing writes to `show`, `show_artist` or `artist`
until A6; and the artist-match thresholds, which A8 calibrates against labelled data.

## Plan review

### Round 1 — Claude Opus 5.5, October 16, 2026

**Scope.** The plan as committed in `9c0ead1` ("A5: draft the reconcile implementation plan"). This is a plan review, so no code exists yet.

**What was checked and how.**
- **Docs read:** `AGENTS.md` ([fill-in] and Implementation plans); `apps/api/AGENTS.md`; `docs/references/fastapi-style-guide.md` (Database section and Anti-patterns); build plan §3 and §5 A5–A7; `arch-initial.md` §7 (Reconcile, its outcome table, Audit trail extensions); `requirements-initial.md` (Show and "Times after midnight", Agent Artist Creation & Matching, Cancelled or postponed listings, Agent Validation, Agent Reconciliation); `data-model-initial.md` §2 `show`, §3 `audit_log`, §5; `conventions.md`.
- **Code read:** `state.py`, `context.py`, `trace.py`, `nodes.py`, `audit.py`, `graph.py`, `main.py`, `local_test.py`, `schemas.py`, `validation.py`, `status_check.py`, `extraction.py` (the JSON-LD route), `normalize.fold_text`, `app/db/models/calendar.py`, `app/db/types.py`, `app/enums.py`, `tests/fakes.py`, `tests/test_graph.py`, and `apps/calendar/lib/dates.ts` `nightSortKey`.
- **Run in a throwaway `git worktree` of HEAD, removed afterwards:**
  - The API suite with `REQUIRE_DB=1`: **669 passed, 15 skipped**. This matches the plan's baseline (CONFIRMED).
  - A probe test that rebuilt the graph with a spy in place of `reconcile_node`, on a JSON-LD page with one `EventCancelled` event. The spy saw each show in `validated_extraction` with its `status` (`['scheduled', 'cancelled']`), so the A2.1-D12 status does survive LangGraph's state passing into reconcile, and the plan's `getattr(show, "status", "scheduled")` works (CONFIRMED).
  - `difflib.SequenceMatcher` on the D5 examples gave 0.889, 0.857, 0.857, 0.667 and 0.632, as the plan says (CONFIRMED).
- **Checked against the source by grep or reading:** `EntityType.ARTIST` exists, `show.original_url` exists, `NIGHT_CUTOFF` is in `sources/jsonld.py`, `polyfactory` is a dependency nothing imports, and `A4` is missing from the `conventions.md` scope table. All CONFIRMED.

**What holds up.** The test approach is tests-first, and it states where each expected value comes from. The five gaps sit where the concepts live: the null in the composite key, the coverage window, status as evidence, the three-way classifier and the failure direction of the model fallback. Re-marking three bullets [written] is argued against `AGENTS.md`'s bar and left to Ari. Keeping the reader out of the node (D7) follows A4-D1. The red-test note under "TODO(Ari) gaps" follows the pattern A4 settled (A4-PR1-4).

**Counts:** 1 blocker, 6 should-fix, 9 nits.

**Verdict:** *proceed after fixes.* The blocker is in ★ D3, so the decision Ari is asked to confirm has to be corrected first. Most of the should-fix rows are matching rules that, as written, would churn or remove the wrong show, plus one gap in the reader's load range. None of them changes the shape of the milestone.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | blocker | ★ D3's rule "an unstated field never erases a stored one", applied field by field to `admission_advance`, `admission_day` and `free_admission`, can produce a row that breaks the table's CHECK constraint. Two cases. **(a)** Stored `admission_day = 20`; the venue goes free and the new listing has `free_admission = True` with both prices null. D3 keeps the price, so the merged row is free with a price. **(b)** Stored `free_admission = True`; the new listing has a price and `free_admission` null. The merged row is again free with a price. A3's FREE_WITH_PRICE check looks at the extraction alone, not at the extraction merged with the stored row, so nothing upstream catches this. The fix: treat the three admission fields as one unit (any non-null admission value in the listing replaces all three), or clear the conflicting side when the other is stated. Add both cases to the "what counts as a change" tests. | CONFIRMED by reading: `app/db/models/calendar.py`, `Show.__table_args__`, `CheckConstraint("NOT (free_admission AND (admission_advance IS NOT NULL OR admission_day IS NOT NULL))")`; the D3 text; `validation.check_consistency` reads only the show it is given. | Reconcile emits an `update` that A6 cannot write: the write fails with a CHECK violation on every run for that show, and the show is stuck with a stale price. Or A6 silently "fixes" it, which moves a decision out of reconcile. Either way the idempotency test, which uses a simulator rather than Postgres, passes. | **Fixed.** D3 rewritten: `admission_advance`, `admission_day` and `free_admission` are one unit. A listing stating any of them replaces all three; stating none leaves all three. The merged row can't violate the CHECK because the listing passed A3's own consistency check. The cost (a day-price-only listing clears a stored advance price) is stated in D3. Both cases, and a CHECK-mirroring assertion, are added to the "admission is one unit" tests. Ari should read the cost line before confirming ★ D3. |
| 2 | should-fix | The reader's load range is never specified. Design names `reconcile.load_request(state)` but not its range. Matching needs stored shows on every **listing** date, and those reach back to `fetched_on − 31 days` because pages keep last week's shows (D1 says so). Removal needs only the coverage window, `[fetched_on, end]`. If the range is the coverage window, every past listing finds no stored twin and is inserted again each night. State the range as `[min(listing dates, fetched_on), coverage.end]`, decide what a confirmed-empty page loads (nothing, presumably), and add a test: a listing dated before `fetched_on` with a stored twin gives `no_op`, not `insert`. | PLAUSIBLE (the function isn't written yet). Grounded in D1 ("Shows up to 31 days back can still be matched"), `validation.check_plausibility` (window `fetched_on − YEAR_LOOKBACK`), and the build-plan order of the Design section. | A duplicate of every past-week show the page still lists, on every run. Because a past show sits outside the removal window, the duplicates are never cleaned up. | **Fixed.** New "What the reader loads" paragraph in Design: `[min(kept listing dates, fetched_on), max(kept listing dates, coverage.end)]`; a confirmed-empty page with no kept listings loads nothing. `load_request` has its own row in the function table. Tests added: `load_request` reaches back before `fetched_on`, and a past-dated listing with a stored twin is a `no_op` (whole-plan version in `test_reconcile_db.py`). |
| 3 | should-fix | A cancelled or postponed listing can pair with an unrelated stored show by date alone. Listings that `status_check.apply` adds **always have a null time**, so they always reach the null-time pass, where "one listing and one stored show on the date" pairs with no act check. Then K3 turns the pair into a `remove` with reason `cancelled`, and that path skips both of D1's absence protections: the excluded-listing date guard and the D6 guard. Example: stored show S on date D; the splitter dropped S's listing (an EXCLUDED_NO_ACTS listing on D); the page also marks a different act cancelled on D. S is removed "as cancelled". The fix: a non-scheduled listing pairs only on shared acts (status is evidence about *a specific* show, A2.1-D12), never on date alone. Add a test. | CONFIRMED by reading `status_check.apply`: an added show is built with no `time` ("it has no time (the question doesn't ask for one)"). The K1 code pairs `pairable[0]` when there is one listing and one stored show. D6 says "Explicit cancellations are not withheld". | A real show is removed on the strength of another show's cancellation, with an audit reason that says it was cancelled, which is the explanation a person would trust most. | **Fixed.** D2 and D4: a cancelled or postponed listing pairs only on a timed key or on shared acts, never on date alone (one-and-one by date applies to scheduled listings only; K1's snippet carries the condition). Test added: a cancelled listing with a null time and an unrelated stored show on its date does not pair. Finding 3's example (excluded S plus a different act cancelled on the same date) is the test's input. |
| 4 | should-fix | Removed stored shows take part in matching with no preference for active ones. D2 matches against "every status" so that a returning show is found, but **(a)** the null-time pass's "exactly one stored show on the date" counts removed rows too. A cancelled show from weeks ago then turns an otherwise unique untimed pair into the "several" branch: if the acts changed, that is an insert plus a removal instead of an update. **(b)** The timed tie-break (shared acts, then lowest id) can pick a removed twin over the active one at the same key and reactivate it, while absence removes the active one. Rule: match against active shows first, and fall back to removed shows only for what is still unpaired (the reactivation case). Add a test for each case. | PLAUSIBLE (reasoned from D2 and the K1 code). `ShowStatus` is `active` or `removed`, and removed rows stay forever (`data-model-initial.md` §2 `show.status`). | The calendar churns: one update becomes remove plus insert, flagged, on any date that ever held a cancelled show. Or a record's history gets mixed with another show's. | **Fixed.** D2: matching runs in two rounds, active stored shows first, removed ones offered only to listings still unpaired. K1's description and the function table say so. Tests added for both cases in the finding (a removed twin never outranks the active one; a long-ago removed show doesn't turn a unique untimed pair into the several-case). |
| 5 | should-fix | "Ties → none" in the mutual-best pairing never settles when two untimed shows on one date share acts. An early and a late show by the same act, untimed (Terminal Bar lists no times; 7th St Entry lists untimed shows), tie for both stored shows, so neither pairs. That gives two inserts and two removals. The next night the newly stored pair ties again, and so on every night. The idempotency property the plan relies on fails for exactly this input. Use a deterministic tie-break that still converges (listing order against stored `night_sort_key` and then id, flagged `needs_review`), and add this input to the idempotency test. Use the same mutual-best assignment in the **timed** pass for two rooms at one time: greedy in listing order can give the first listing the lowest id even when it shares acts with the other stored show. | PLAUSIBLE (reasoned from the K1 code and the plan's own idempotency definition, Test approach §1). | Two shows deleted and recreated every night, each with a new id, so links to them break and the audit trail fills with churn. | **Fixed.** D2 and K1: the several-case is a global assignment (highest shared-act overlap, then listing order, then the stored show's `night_sort_key` and id), needing at least one shared act, flagged when the tie-break decided. The timed pass uses the same assignment, so two rooms can't swap lineups. The early-and-late-show input is added to the idempotency test, plus a two-rooms test. |
| 6 | should-fix | Artists are resolved before the action is known, so skipped listings still resolve artists. `build_plan` step 1 resolves every distinct act key first. That includes acts on cancelled or postponed listings that K3 will `skip` (no stored show) or `remove`, which need no lineup. Those names still cost a model call, write a D8 artist-decision row and add an `ArtistResolution(new)` to `plan.artists` that A6 would create. This contradicts the test "A `skip` creates no insert and no artist". Resolve artists only for listings whose action needs a lineup (scheduled listings: insert, update, no-op), or prune `plan.artists` and the decision rows to those a decision references. K1's tie-break compares names, not ids, so moving resolution after matching costs nothing. | CONFIRMED by reading the plan: the `build_plan` order (step 1, "which is why artist resolution is first") against Test approach §1, cancelled and postponed ("A `skip` creates no insert and no artist"), and §3 (once per name). | An orphan artist row for every act on a never-stored cancelled listing, a wasted model call, and an audit row recording a database decision that is never used. | **Fixed.** `build_plan` reordered: match first (it compares names, so it needs no resolution), then resolve artists only for scheduled listings, and `plan.artists` holds only referenced resolutions. Tests: a cancelled listing naming an unknown artist makes zero model calls and no resolution. |
| 7 | should-fix | Import cycle between `state` and `reconcile`. `state.py` gains fields typed with `reconcile` classes (`stored_shows`, `known_artists`, `reconcile_plan`), and Pydantic needs those types at runtime. Meanwhile `reconcile.py`'s `listings_from(state)`, `covered_window(state)` and `load_request(state)` take a `VenueGraphState`. `apps/api/AGENTS.md` requires the imports to stay a DAG (`validation` ← `policy` ← `state` ← `nodes`/`graph`). Give these functions plain arguments (the extraction, the validation result, `fetched_on`) and keep `reconcile.py` free of `state`. That also matches the plan's own "everything here is a function of its arguments". Same check for `calendar_reader` → `reconcile` and `context` → `calendar_reader`. | CONFIRMED by reading the plan (Design: the dataclass list, the function table, "The wiring") against `apps/api/AGENTS.md` ("keep it a DAG") and `state.py`'s imports. | A circular-import error at import time, or a `TYPE_CHECKING` workaround that hides the cycle and puts a pure module downstream of the state. | **Fixed.** All `reconcile.py` functions take plain arguments (`listings_from(extraction, validated)`, `covered_window(kept, excluded_no_act_dates, fetched_on)`, `load_request(kept, window, fetched_on)`); an explicit import order is added to Design. Checking it also found that `artist_match` needs `EXTRACTION_ERRORS`, which lives in `nodes.py` (above `state`): it moves to `llm.py` (Critical files, wiring step). A fresh-interpreter test asserts `reconcile` and `artist_match` don't import `state`. |
| 8 | nit | The lineup is "replaced wholesale", which goes against D3 for per-act `start_time`. A listing that has lost a per-act time would erase the stored one and be counted as a change. Today no adopted route produces per-act times, so the effect is latent, but H1 adds them, and the sticky JSON-LD-to-model fallback would make them flicker. Compare lineups on artist identity and order, and apply D3 to each act's `start_time`. | CONFIRMED by reading: the JSON-LD route builds `ActExtraction(name=name)` (`extraction.py`, the JSON-LD route), and A2.1-CR2-9 says the title-split route returns no per-act times. | A lineup update every time a route stops stating per-act times, once H1 lands. | **Fixed.** D3: the lineup compares artist identity and order, and each act's `start_time` follows the unstated-never-erases rule. Test added (a lineup that lost a per-act time is `no_op` and keeps the stored time). |
| 9 | nit | K1's *Check* names the wrong test for its second-likeliest mistake. Writing `l.show.time == s.start_time` instead of "either side is null" gives the same answer when both sides are null (`None == None`), so the two-untimed-shows test still passes. The mistake breaks only null-against-timed pairing, and the null → 20:00 and 20:00 → null tests are the ones that catch it. Fix the wording so Ari is pointed at the test that actually goes red. | CONFIRMED by working through the K1 filter for each combination: both null, null and timed, two different times. | Ari is sent to the wrong test when K1 misbehaves. | **Fixed.** K1's Check now says `l.show.time == s.start_time` is `True` for two nulls but `False` for null-against-timed, so the null → 20:00 and 20:00 → null tests are the ones that go red. |
| 10 | nit | D2 doesn't say when `needs_review` is set. "Anything still unpaired is ... flagged" reads as covering every ordinary insert (a new timed show) and every ordinary removal, which would make the flag mean nothing. Say it is set only on dates where a null time was involved in the leftovers (or list the cases), and pin that with a test. | CONFIRMED by reading D2 step 2. | `detail.needs_review` lists every new show, and people learn to ignore it. | **Fixed.** D2: `needs_review` is set only where a guess was involved (a null time left unpaired with the other side present, or an order tie-break). Test added: false for an ordinary new timed show and an ordinary removal. |
| 11 | nit | `artist_key` can come out empty. Dropping punctuation turns a name like "!!!" (a real touring band) into an empty key. Empty keys compare equal, so "!!!" exactly matches any other all-punctuation name, and an empty word set passes the containment rule against every artist. Fall back to `fold_text` when the key is empty, and add a test. | CONFIRMED by reasoning from D5's normalisation rules ("punctuation dropped"; the containment rule tests subset-of-words). | A wrong merge, the outcome D5 is built to avoid, or every known artist offered as a candidate. | **Fixed.** D5: an empty `artist_key` falls back to `fold_text(name)` and never reaches the containment rule. "Keys" test section added (`!!!` vs `???`). |
| 12 | nit | `night_sort_key` doesn't say where untimed shows sort. The frontend's `nightSortKey` and the API put untimed shows **last**. State the same rule and add it to the after-midnight tests, so the plan, the audit row and the calendar all order a night the same way. | CONFIRMED: `apps/calendar/lib/dates.ts` `nightSortKey` ("an untimed one comes last ... the API's own ordering puts untimed last"). | The audit row's order disagrees with the calendar's, or the comparison raises on `None` if the key compares times directly. | **Fixed.** `night_sort_key` puts an untimed show last, as `nightSortKey` and the API do (function table); added to the after-midnight tests. |
| 13 | nit | It's unclear where K3's gap ends. Its code block ends with a comment ("reactivate if it had been removed, else compare the details"), yet the Check runs the `returning` tests and the Lesson names reactivation. Say whether the reactivation branch is inside the `TODO(Ari)` block or written after it. Code written after a `raise` is unreachable while the gap is open. | CONFIRMED by reading the K3 bullet. | The scaffold either leaves the reactivation lesson out of the gap or contains dead written code. | **Fixed.** K3's gap is now only the non-scheduled branch, so the `raise` sits inside it and the scheduled path (insert, reactivate, compare) is written and runs while the gap is open. Lesson, Code and Check rewritten to match; the Check now runs `-k "cancelled or postponed"`. |
| 14 | nit | `covered_window` doesn't define the case where every kept and no-act listing is dated before `fetched_on`, as on a page showing only last week. Then `end < start`. Say that this gives `None` (no window) or an empty window, and test it. | CONFIRMED by reading D1 (start = `fetched_on`; end = the latest listed date; past listings are plausible back to 31 days). | It's harmless with the K2 comparison as written, but undefined, and the audit row's `coverage` would show a negative range. | **Fixed.** `covered_window` returns `None` when every listed date is before `fetched_on` (`end < start`), with a test; `load_request` still reaches back for matching. |
| 15 | nit | The polyfactory seeding in `test_calendar_reader` and `test_reconcile_db` should set artist names and show dates explicitly and use the factories only for filler columns. Random names can land in the ambiguous band against the test's own names, which triggers an unscripted `ARTIST_MATCH` call (`ScriptedCompletions` raises `AssertionError`). Random dates make the expected outcomes depend on the code under test, against `AGENTS.md`'s "say where the expected values come from". | PLAUSIBLE: `tests/fakes.py` `ScriptedCompletions.create` raises on an unscripted model. | Brittle tests whose failures depend on the seed, or expected values that can't be traced to the requirements. | **Fixed.** `test_calendar_reader` and `test_reconcile_db` use `polyfactory` for filler columns only; names and dates are set explicitly, with the reason (unscripted model call; expected values traceable to the test). |
| 16 | nit | `ArtistMatchAnswer.confidence` should carry `Field(ge=0, le=1)`, as the other schemas the model fills do, so an out-of-range value is a validation error and not a "match" at 1.7. Also say which request options the artist question uses (`PIPELINE_OPTIONS`, temperature 0, seed) and that `model_used` comes from them. | CONFIRMED by reading `schemas.ShowExtraction.confidence` (`ge=0, le=1`) and the D5/K5 text. | An unbounded confidence passes the `min_confidence` gate, and the audit row's `model_used` source is left to the implementer. | **Fixed.** D5: `ArtistMatchAnswer.confidence` is `Field(ge=0, le=1)` (test: 1.7 is a validation error), the question uses `PIPELINE_OPTIONS` (temperature 0, base model), and `model_used` comes from those options. |

**Rejected:** none. Round 1 resolved by the author (Claude Sonnet 5.5), October 16, 2026: 16 of 16 fixed in the plan. The blocker (row 1) changed a decision Ari is asked to confirm (★ D3), and rows 3 to 6 changed the matching rules (D2) and the `build_plan` order; no round 2 was run, but Ari may want one given that. Review rows 1, 3, 4 and 5 are the ones to read first.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 17, 2026

**Scope.** `git diff 886e04e` (the last plan commit) plus the new untracked files: the working tree, uncommitted at the
time the reviewer is spawned. Branch `claude/vigilant-keller-858dzn` (assigned by the session; `AGENTS.md` names
`a5-reconcile`).

*New:* `agent_worker/reconcile.py`, `artist_match.py`, `calendar_reader.py`; tests `reconcile_support.py` (helpers),
`test_reconcile_shows.py`, `test_reconcile_removal.py`, `test_artist_match.py`, `test_graph_reconcile.py`,
`test_reconcile_audit.py`, `test_calendar_reader.py`, `test_reconcile_db.py`.
*Changed:* `llm.py` (`EXTRACTION_ERRORS` moved here), `nodes.py` (`reconcile_node` real, `commit_node` stub logs counts),
`state.py` (`stored_shows`, `known_artists`, `reconcile_plan`; `reconcile_decision` removed), `context.py` (`reader`),
`trace.py` (`read_calendar`, the model-decision rows), `audit.py` (reconcile detail, `model_decision_entries`, reconcile
venue-level), `prompts.py` (`artist_match_instruction`), `main.py`, `local_test.py`; tests `fakes.py` (`FakeReader`,
`ARTIST_MATCH`), `test_audit_entries.py`, `test_audit_queries.py`, `test_graph.py`, `test_graph_audit.py`,
`test_run_venue.py`; docs `audit-queries.sql` (header keys, the fifth query), `alpha-build-plan.md`, `arch-initial.md`
§7, `data-model-initial.md`, `conventions.md`, `apps/api/AGENTS.md`, `notes.md`. No migration, no schema change.

**Departures from the plan, each with its reason.**

1. **The tests were not all written before the code.** I wrote the logic with the five gaps filled first, then the tests,
   to get a known-good version to derive the scaffold from; the "watched fail" step is the scaffold itself (118 red results: 108 failed plus 10 fixture errors, all
   `NotImplementedError: TODO(Ari)`). The tests' expected values were still written from the requirements and
   decisions, not read from the code; the reviewer should check that, since I can't show the red-before-green order.
2. **`Listing` is a plain dataclass of the fields reconcile reads** (`ListedAct`, `time`, `end_time`, prices, `status`),
   not a wrapper around the pydantic `ShowExtraction` the plan's type list showed. The extraction schema has variants
   (with and without `status`) and reconcile should depend on neither; it also keeps the plan free of pydantic subclass
   quirks when LangGraph passes the state.
3. **`prepare_inputs(extraction, validated, validation, fetched_on)` and `excluded_listing_dates` are new functions**
   (the plan named `listings_from`, `covered_window`, `load_request`). They gather the plain arguments in one place,
   used by both the node and the wrapper.
4. **K3's gap is only the non-scheduled branch,** as plan review finding 13 resolved; K1's gap is `_null_time_pairs`,
   the whole null-time pass, with `_assign_by_acts` written around it.
5. **The `commit` stub's audit `detail` is `{"stub": true}`;** the `decision` key went with `reconcile_decision`.
6. **`Action.outcome`** (maps to `AuditOutcome`) is an addition, for A6's per-show rows; tested.
7. **`trace.read_calendar` uses `nodes.metro_today`** when `fetched_on` is unset, so the wrapper and the node agree on
   "today" (both fall back the same way; `fetch_node` always sets it in a real run).
8. **`local_test.py` prints the plan** (counts, window, one line per decision), the plan's Verification step 4.

**`TODO(Ari)` gaps** (all open; review the code as it stands, they are not findings):

| Key | Where | Lesson |
|---|---|---|
| A5-K1 | `reconcile.py` `_null_time_pairs` | What a null time does in the composite key |
| A5-K2 | `reconcile.py` `removed_by_absence` | Absent from the page, inside the reached range |
| A5-K3 | `reconcile.py` `plan_for_listing` (non-scheduled branch) | A cancelled listing is evidence about a stored show |
| A5-K4 | `artist_match.py` `classify_artist` | Exact, ambiguous or new: a three-way answer |
| A5-K5 | `artist_match.py` `decide_ambiguous` | The model's failure direction is "new artist" |

Fill order K4, K1, K3, K2, K5. Every graph-running and plan-running test is red until all five are filled (K4 is on
every path that has a scheduled listing).

**Verification.**

- **Baseline** before A5, measured October 16: 669 passed, 15 skipped.
- **As delivered (gaps open):** `REQUIRE_DB=1 uv run pytest`: **666 passed, 108 failed, 10 errors, 15 skipped**. All 118
  red results are `NotImplementedError: TODO(Ari)` (checked by grepping every failure message; none is anything else;
  an earlier draft of this log said 226, which counted traceback lines twice: A5-CR1-7).
  Red by file: `test_reconcile_shows.py` 41, `test_artist_match.py` 24, `test_reconcile_removal.py` 15,
  `test_graph.py` 13, `test_graph_audit.py` 6, `test_audit_queries.py` 6, `test_graph_reconcile.py` 5,
  `test_reconcile_db.py` 4, `test_calendar_reader.py` 2, `test_run_venue.py` 2 (failures and fixture errors together).
- **Gaps filled on a scratch copy** (a temporary directory outside the repo, removed afterwards): **784 passed, 15
  skipped**, ruff clean. That is the 669 baseline plus 115 new tests.
- `uv run ruff check .` clean. `uv run mypy app/` clean (the CI scope); the three new modules also pass `mypy`
  (`reconcile.py`, `artist_match.py`, `calendar_reader.py`); widening mypy to `agent_worker/` is A7.
- `make lint`, `make typecheck` and `make contract-check` pass; `pnpm turbo run test` passes (the JS suite is untouched).
- `make check` as a whole stops at its Python test stage, red by design; nothing else in it is skipped.
- **Not run here:** `make worker` and `local_test` (no Ollama, no Docker, no Mongo in the cloud sandbox), and so the
  live model's answers to the artist question (unmeasured; plan, "What is not covered"). Ari runs Verification 4-6 locally.

**Where to look hardest.**

1. **`match_shows` and `_assign_by_acts`** (`reconcile.py`): the two-round (active then removed), two-pass structure; whether
   the tie flag (`tied`) and the `needs_review` rules mean what D3 says; and whether the global assignment can give a
   wrong pair that the tests don't pin.
2. **The window and the excluded dates** (`excluded_listing_dates`, `covered_window`): the index trap (raw list, not the
   validated one) is easy to get wrong silently, and one test excludes a show in the middle of the list.
3. **`show_changes` + `merge_lineup`** and the no-op/update boundary, because a false update every night is a silent
   churn: the admission unit, the lineup comparison with new artists (id `None`), and `original_url`.
4. **`trace.audited`'s reconcile branch** (`read_calendar`, the order of the rows) and that a failed read leaves no
   partial state.
5. **`build_plan`'s `plan.artists`** (only the artists some decision uses) and that cancelled listings cost no model call.
6. Anything in the tests whose expected value I may have taken from the code instead of the requirements.

### Round 2 — Claude Sonnet 5.5, October 17, 2026 (fixes for code review round 1)

**Scope.** The fixes for `A5-CR1-1` to `A5-CR1-9`, on top of `f0baae2`: `reconcile.py` (`excluded_listing_dates`,
`prepare_inputs`, `_assign_by_acts`, `match_shows`, `lineup_for`), `artist_match.py` (`_new`, `_matched`, a shorter K5 gap),
tests `reconcile_support.py` (`extracted`, `validated`), `test_reconcile_removal.py`, `test_reconcile_shows.py`, and docs
(`a5-reconcile.md`, `alpha-build-plan.md`, `notes.md`). Each testable finding got a failing test first (7 failed before the
fixes, which is the proof the tests catch what the findings describe); findings 3 and 4 and the nits 7 to 9 are tests or text.

**Departures.** None from the plan. Two behaviours were added to "Settled details" (the lineup is in performance order and
repeated stated numbers are renumbered; a scheduled listing outranks a cancelled one on a tie, and a guessed pairing is
flagged whole), because the review showed the plan hadn't said them.

**`TODO(Ari)` gaps.** All five still open (A5-K1 to A5-K5). K5's `Code:` block is now 7 lines.

**Verification.**
- **As delivered (gaps open):** `REQUIRE_DB=1 uv run pytest`: **668 passed, 112 failed, 10 errors, 15 skipped**. All 122
  red results are `NotImplementedError: TODO(Ari)`.
- **Gaps filled on a scratch copy** (outside the repo, removed afterwards): **790 passed, 15 skipped**, ruff clean, and the
  three new modules pass `mypy`. That is the 669 baseline plus 121 new tests.
- `uv run ruff check .`, `uv run mypy app/`, `make contract-check` and `pnpm turbo run test` pass; `make check` as a whole
  still stops at its Python test stage, red by design.

**Where to look hardest.** `excluded_listing_dates` (the plausibility test, because it now decides whether a page "reached"
a date); `lineup_for` (the sort and the distinct-numbers rule, because a wrong order is a nightly update); the batch
flagging in `match_shows`.

### Round 3 — Claude Sonnet 5.5, October 19, 2026 (scoped designations; a comment-only pass)

**Scope.** Ari noticed that comments cited plan items bare (`# D7: the same row comes back`), against
`docs/dev/conventions.md` rule 2 ("Code, tests and code comments always scope"). All 14 A5 source and test files that had
them were rewritten to the scoped form (`A5-D7`, `A5-K1`, `A5-PR1-4`, `A5-CR1-2`); one line in `alpha-build-plan.md` too.
Nothing else changed in the code.

**Verification (a comment-only pass, as `AGENTS.md` asks).** Syntax trees compared before and after with docstrings
stripped: **identical in all 14 files**. `ruff` clean. `REQUIRE_DB=1 uv run pytest`: 668 passed, 112 failed, 10 errors,
15 skipped, the same as before the pass (all 122 red results are `NotImplementedError: TODO(Ari)`; gaps still open). The
new `make designation-check BASE=886e04e` exits 0 on the branch, and fails on a planted bare `D9`.

**Ari's commit `efe95ca` (October 19, 2026) arrived while this pass was running:** he filled all five `TODO(Ari)` gaps
(A5-K1 to A5-K5) locally, in `reconcile.py` and `artist_match.py`. This pass was merged with it (a merge, not a rebase, since
it is his history); where we both edited a line his version won, then the scoping was re-applied around it. His code is
identical to his commit (syntax trees compared). One fix in his docstring text: `A8-D8`/`A8-D12` read `A5-D8`/`A5-D12` (A8 is
a different milestone). With his gaps filled the suite is **790 passed, 15 skipped** on the branch itself, ruff clean. The
gap scaffolding comments ("Lesson" blocks) are still in place: the cleanup pass of `AGENTS.md` step 4 follows once Ari asks
for it ("clean up the closed gaps in A5").

**Process change (so this does not recur).** `AGENTS.md` ("Cross-references carry a scope") now says code, tests and comments
write the scoped form even when implementing the one plan in view; `docs/dev/conventions.md` rule 2 and "Checking" say the
same and document `make designation-check` (`scripts/check_designations.py`, which reads only the lines a branch adds);
the `build-milestone` skill cites scoped IDs while implementing and runs the check before review and after resolving;
`plan-milestone` asks for a "Designations" paragraph; the `plan-reviewer` agent runs the check on a code review.

### Round 4 — Claude Sonnet 5.5, October 19, 2026 (cleanup of the closed gaps; the designation check in CI)

**Cleanup pass (`AGENTS.md` "[fill-in] tasks" step 4).** Ari had filled A5-K1 to A5-K5 (`efe95ca`) and removed the `TODO(Ari)` markers,
`Code:`/`Check:` blocks and the `noqa`. What remained was formatting from the scaffold, so this pass made each block a plain
why-comment in the style of its neighbours (`reconcile.py`: `_null_time_pairs`, `plan_for_listing`, `removed_by_absence`;
`artist_match.py`: `classify_artist`, `decide_ambiguous`), dropped a comment that repeated its docstring, and removed the
"(the scheduled path below is written)" aside. The reasoning and the plan-level references (`A5-D3`, `A5-D6`, the `A5-K1`..`A5-K5`
section headers and test headers) are kept. One stale note of the same kind in A4's `test_run_venue.py` ("stay red until Ari
fills …", closed in A4) was reworded. **Comment-only, verified as such:** syntax trees (docstrings stripped) identical before
and after in all three files. No placeholder helper existed to delete (`lib/todo.ts` is the frontend's).

**Designation check wired in.** `make designation-check` is now part of `make check` (default base: where the branch left
`origin/main`) and a CI job, `designations`, on pull requests (base: the PR's own merge-base), with `fetch-depth: 0`. It caught a
bare example in its own CI comment on the first run.

**Verification.** `make check` end to end: **exit 0**. Python 790 passed, 15 skipped; JS 283 passed; ruff, mypy (`app/`),
eslint, tsc and `make contract-check` clean; `make designation-check` exits 0. The five gaps are all filled (by Ari) and cleaned;
no `TODO(Ari)` remains in the A5 files.

## Code review

### Round 1 — Claude Opus 5.5, October 17, 2026

**Scope.** Implementation log round 1: `git diff 886e04e` on branch `claude/vigilant-keller-858dzn`. The log describes the
work as an uncommitted working tree, but it is now committed as `f0baae2` ("A5: implement reconcile (scaffold with five
TODO(Ari) gaps), tests, docs"). That is 34 files and the same file list the log gives. The five open `TODO(Ari)` gaps
(A5-K1 to A5-K5) are not findings.

**What was checked and how.**
- **Docs read:** `AGENTS.md` ([fill-in] tasks, Implementation plans); `apps/api/AGENTS.md`;
  `docs/references/fastapi-style-guide.md` (Anti-patterns table); this plan in full, including plan review round 1 and
  Implementation log round 1; the doc diffs to `arch-initial.md` §7, `data-model-initial.md`, `alpha-build-plan.md`,
  `conventions.md`, `notes.md` and `audit-queries.sql`.
- **Code read:** `reconcile.py`, `artist_match.py` and `calendar_reader.py` in full; the diffs to `trace.py`, `audit.py`,
  `nodes.py`, `state.py`, `context.py`, `llm.py`, `prompts.py`, `main.py` and `local_test.py`; `tests/reconcile_support.py`;
  `test_reconcile_removal.py` in full; most of `test_reconcile_shows.py`; the test lists of the other new test files;
  `validation.validate_extraction`; `status_check.apply`; `schemas.ActExtraction.sequence_number` and `free_admission`.
- **`make check` on HEAD:** ruff, eslint, mypy (`app/`), tsc and contract-check all pass. The API suite gives
  **666 passed, 108 failed, 10 errors, 15 skipped**, and every one of the 118 red results is
  `NotImplementedError: TODO(Ari)` (I counted the `E` lines). This is red by design, as the log says (CONFIRMED).
  `uv run mypy` on the three new modules is clean (CONFIRMED).
- **Gaps filled in a throwaway `git worktree` of HEAD (removed afterwards):** I pasted each gap's own `Code:` lines
  verbatim and removed the `noqa`. Result: **784 passed, 15 skipped**, ruff clean. This matches Verification step 2 and
  the log (CONFIRMED). I also wrote probe tests in the same worktree for findings 1, 2, 5 and 6. Their output is quoted in
  the Evidence column.
- **Checked and found sound:** the import DAG (`reconcile`/`artist_match` never import `state`; a test enforces it).
  Active-first matching. A cancelled listing never pairs by date alone. A failed read propagates and leaves no reconcile
  row. `plan.artists` holds only resolutions some decision references. Cancelled listings make no model call.
  `free_admission = False` cannot wipe prices under D5, because `false_to_none` turns it into null first. The real
  `PostgresCalendarReader` returns `ShowStatus` members, so the `is ShowStatus.ACTIVE` comparisons hold (exercised by
  `test_reconcile_db.py` with the gaps filled). No route, async or bare-`Exception` anti-patterns.

**Counts:** 1 blocker, 3 should-fix, 5 nits.

**Verdict:** *proceed after fixes.* The blocker is a silent wrong removal, which is the failure class this milestone
exists to prevent. It contradicts a "Settled detail", and the test that claims to cover it can't fail. The fix is two
lines in written code, not in a gap. The should-fix rows are a nightly-churn input that the test suite already builds,
two promised tests that don't exist, and an approval the file doesn't record.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | blocker | **A listing left out for naming no act can stretch the removal window to any date, implausible ones included.** `validate_extraction` handles the no-act exclusion *before* the plausibility check, so a show with no acts and a 2028 date gets only an `EXCLUDED_NO_ACTS` finding, never `DATE_OUT_OF_WINDOW`. `excluded_listing_dates` keeps every `EXCLUDED_NO_ACTS` date, and `covered_window` takes the max over them. That breaks "Settled details": "An implausible date can't stretch the window. A year-2028 entry in a venue's structured data isn't evidence of reach." The test that claims to cover this (`test_a_listing_left_out_for_an_impossible_date_does_not_stretch_the_window`) calls `covered_window(..., [], ...)` with no excluded dates at all, so it cannot fail. Fix: in `excluded_listing_dates`, keep a no-act date only when it is inside the plausibility window (`validation.check_plausibility(show, fetched_on).date_out_of_window` is False, which means passing `fetched_on` in), or at least drop dates past `fetched_on + 366 days`. Replace the test with one that goes through `validate_extraction` → `prepare_inputs` with a no-act 2028 show. | CONFIRMED (worktree probe, gaps filled). A JSON-LD page has Nona on Oct 20, a no-act show on 2028-03-01 at index 1, and Zhora on Oct 25; stored shows exist on Oct 20, Oct 25, Dec 5 and Feb 5 2027. Output: `FINDINGS [(EXCLUDED_NO_ACTS, 1)]`, `COVERAGE Coverage(start=2026-10-12, end=2028-03-01)`, `PLAN [no_op 1, no_op 2, remove 3 'absent from the page', remove 4 'absent from the page'] withheld 0`. Code: `validation.py:487-496` (the `continue` comes before `check_plausibility`); `reconcile.py:267-294`; `test_reconcile_removal.py:101-107`. | Every stored show between the page's real horizon and the bogus date is soft-deleted on every run that sees the placeholder entry (a "Private event" or "Gift cards" item, the kind of entry the plan itself calls out). The D10 guard does not catch it: matched shows count toward `in_window_active`, so a venue with 20 listed shows loses up to 10 out-of-sight shows unguarded. `notes.md`'s new entry says such a date "is not evidence", so the docs claim protection the code doesn't give. | **Fixed.** `excluded_listing_dates` now takes `fetched_on` and keeps a no-act date only when `validation.check_plausibility` says it is inside the plausible window (the finding's own suggestion); `prepare_inputs` passes it. Failing test first: `test_a_no_act_listing_with_an_impossible_date_does_not_stretch_the_window` goes through real `validate_extraction` and `prepare_inputs` with the 2028 entry from the probe, and asserts the window ends October 25 and nothing between there and 2028 is removed; it failed before the fix. The old test that could not fail is replaced. Added the other half (`..._plausible_date_still_counts_as_reach`). `notes.md` and the Settled details already stated the intended behaviour. |
| 2 | should-fix | **A stated performance order that differs from list order turns into an update every night.** `lineup_for` keeps the entries in list order and keeps the stated `sequence_number`s. `show_changes` compares that list-order tuple against `stored.ordered_lineup()`, which sorts by `sequence_number`. For acts listed `[Zhora (2), Nona (1)]`, the stored side reads `[Nona, Zhora]` and the new side reads `[Zhora, Nona]` on every run, forever. `test_stated_sequence_numbers_are_kept_when_every_act_has_one` builds exactly this input, but the idempotency test never feeds it back in. `ActExtraction.sequence_number` is filled whenever "the page explicitly states an order", so this is a real input. Fix: sort the resolved lineup by `sequence_number` before comparing (or compare `(artist_id, sequence_number, start_time)` as a set). Add this listing to `test_feeding_a_plans_result_back_in_gives_all_no_ops`. | CONFIRMED (worktree probe): `plan_for` → `apply_plan` → `plan_for`, twice, gives `SECOND [(update, {'lineup': (((7, None), (8, None)), ((8, None), (7, None)))})]` and the same `THIRD`. Code: `reconcile.py:98-100`, `480-500`, `544-547`; `test_reconcile_shows.py:399-402`; `schemas.py:67-79`. | Exactly the churn the idempotency property is meant to prevent: once A6 writes, every such show gets an UPDATE, a `show_artist` rewrite and an audit row per night, and the summary row's `update` count never settles. | **Fixed.** `lineup_for` returns the lineup sorted by sequence number, and treats stated numbers as stated only if every act has one and they are all different (otherwise renumbered by position). Failing tests first: `test_a_stated_order_that_differs_from_list_order_is_stable_run_to_run` (three runs through `apply_plan`), `test_stated_sequence_numbers_are_kept_and_the_lineup_is_in_that_order`, `test_repeated_stated_numbers_are_renumbered_by_position`; the stated-order input is also in `test_feeding_a_plans_result_back_in_gives_all_no_ops`. All failed before the fix. |
| 3 | should-fix | **Two tests the plan names under "Known gotchas" don't exist, and the log says one of them does.** The plan says "A test excludes a show in the middle of the list" (the raw-vs-validated index trap) and "A test builds both kinds of show" (`status` read with `getattr`). No test calls `excluded_listing_dates`, `prepare_inputs` or `listings_from`. Every removal test passes `excluded=` dates directly through `reconcile_support.inputs_for`, which skips the index mapping. Implementation log "Where to look hardest" 2 says "one test excludes a show in the middle of the list". The code is right today (the finding 1 probe's exclusion at index 1 gave the right date), but nothing pins it, and `notes.md` calls this the trap that is "easy to get wrong silently". Add a unit test that builds a raw extraction plus a `ValidationResult` with an `EXCLUDED_NO_ACTS` finding at a middle index, and asserts the date. Add a `listings_from` test with a status-carrying show (`show_model(status=True, ...)`) and a plain `ShowExtraction`. | CONFIRMED: `grep -rn "excluded_listing_dates\|prepare_inputs\|listings_from" agent_worker/tests/` finds only a comment (`test_reconcile_removal.py:103`). Plan, "Known gotchas", bullets 1 and 2; log, "Where to look hardest" 2. | A refactor that indexes `validated_extraction.shows` protects the wrong dates, and no test goes red. The image route's status-less show likewise has no test. | **Fixed.** Added `test_excluded_dates_come_from_the_raw_list_not_the_validated_one` (a no-act show in the MIDDLE of three, through real validation and `prepare_inputs`; the validated list is [Oct 20, Oct 25] and the excluded date must be Oct 22) and `test_a_listing_carries_its_status_when_the_schema_has_one_and_is_scheduled_when_it_does_not` (the status-carrying variant against a plain `ShowExtraction`). Both pass on the existing code and now pin it; the log's claim that such a test existed was wrong when written and is true now. New helpers `extracted` and `validated` in `reconcile_support.py`. |
| 4 | should-fix | **The file never records plan approval.** Per `AGENTS.md`, only Ari moves the status past step 4 (`Approved`). The header went from `Awaiting approval` (`886e04e`) straight to `Code review` (`f0baae2`). The "Approval" section still ends "*(Awaiting Ari's approval of the plan … `/build-milestone` records the approval.)*". The Implementation log doesn't mention approval either. `alpha-build-plan.md` meanwhile says "plan approved by Ari October 17, 2026". If Ari approved outside the file, `/build-milestone` should have recorded it. The header also has no author line for the implementation round, and its `Date` still reads October 16 (`AGENTS.md`: "The header records the status, the date, the author model, and the reviewer model for each round"). | CONFIRMED: `git show <c>:docs/dev/implementations/a5-reconcile.md` for `ff210cb`, `160405a` and `886e04e` all read `Status: Awaiting approval`; plan lines 852-857; the `alpha-build-plan.md` A5 paragraph. Whether Ari approved in chat is PLAUSIBLE but not visible. | The Ari gate isn't auditable from the file, which is the only channel between the models. A reader can't tell whether implementation began before approval. **Ari should confirm.** | **Fixed (recorded; Ari confirms).** The Approval section now records Ari's message approving the plan on October 17, 2026 ("The plan is approved. /build-milestone …") and that `/build-milestone` set `Approved` at step 0; the header gains an implementation author line and the dates. The status had gone from `Awaiting approval` to `Code review` without an `Approved` commit in between because the skill sets and advances it in one run; I did not record a separate commit for it. **Ari should check this reading of the approval.** |
| 5 | nit | **When a cancelled and a scheduled listing tie for one stored show, the tie-break can make them swap every night.** `_assign_by_acts` breaks equal overlap by listing order, ignoring status. With "CANCELLED Nona 20:00" listed before "Nona 20:00", and one stored Nona at 20:00, the cancelled listing takes the active row (remove) and the scheduled one inserts a new row. On the next run the cancelled listing takes the new active row and the scheduled one reactivates the old row, and so on. Rank a scheduled listing ahead of a non-scheduled one on equal overlap (or let a cancelled listing take only what a scheduled one didn't). | CONFIRMED behaviour (worktree probe, three runs through `apply_plan`): `RUN 0 [insert, remove 1 'cancelled']`, `RUN 1 [update 1 'reappeared', remove 2 'cancelled']`, `RUN 2 [remove 1 'cancelled', update 2 'reappeared']`. How realistic the input is: PLAUSIBLE. `status_check.apply` adds only untimed listings, so it would take a JSON-LD page carrying both an `EventCancelled` and a scheduled event at one key. Code: `reconcile.py:360`. | Two rows for one show, alternating between removed and active nightly, each flip flagged. Rare, but it is the churn class D3 and D7 are written against. | **Fixed.** `_assign_by_acts` ranks a scheduled listing ahead of a cancelled/postponed one on equal overlap. Failing test first: `test_a_scheduled_listing_outranks_a_cancelled_one_for_the_same_stored_show` runs the probe's input for three runs through `apply_plan` and asserts the same `no_op` + `skip` each time; it failed before the fix. |
| 6 | nit | **A tie-break flags only the first pair it settles.** With two untimed same-act shows on one date, `tied` is True for the first pair. The second pair is then settled by elimination and comes out False, because its alternatives are already taken. "Settled details" says "the pair is flagged for review", and the test asserts `any(d.needs_review …)`, so it doesn't pin which one. A person reviewing sees half of a swap. Flag every pair on a date where `_assign_by_acts` reported a tie, and assert `all(...)` over that date's decisions. | CONFIRMED (worktree probe): `TIE [(0, 1, True), (1, 2, False)]`. Code: `reconcile.py:370-375`; `test_reconcile_shows.py:138`. | The review list shows one listing of a guessed pairing and hides its partner. | **Fixed.** `match_shows` flags every pair of a batch in which `_assign_by_acts` reported a tie (both the timed and the null-time pass). `test_two_untimed_shows_by_the_same_act_pair_in_a_fixed_order_and_are_flagged` now asserts `all(...)` over the date's decisions instead of `any(...)`; it failed before the fix. |
| 7 | nit | **The red-test count in the Implementation log is wrong.** Departure 1 and Verification both say "226" red results (failures). The real count is 118: 108 failed plus 10 errors, which also matches the log's own per-file list (41+24+15+13+6+6+5+4+2+2 = 118) and 784 − 666. | CONFIRMED: `make check` output `108 failed, 666 passed, 15 skipped, 1 warning, 10 errors`; 118 `E … NotImplementedError: TODO(Ari)` lines. | A reader checking the log against a run sees a mismatch and can't tell whether 108 failures have gone missing. | **Fixed.** The log said 226 (it counted traceback lines twice); the real count is 118 red results at the time, 122 after this round's six new tests (112 failed + 10 errors). Corrected in Round 1 with a note, and Round 2 gives the new figures. |
| 8 | nit | **`alpha-build-plan.md`'s A7 tick says "done in A5, tests first … A5-D3 departure".** Both parts are wrong. Implementation log departure 1 says the tests were *not* written first. `A5-D3` is the null-time decision; pulling the A7 item forward is this plan's "Departures from the build plan" item 3, which has no scoped ID. Say "(done in A5: …; see a5-reconcile.md, Departures 3)" and drop "tests first". | CONFIRMED: the `docs/dev/alpha-build-plan.md` diff (the A7 bullet); `conventions.md` (a `D<n>` is a decision); Implementation log departure 1. | A wrong cross-reference, and a claim about test-first order that the plan's own log contradicts. | **Fixed.** The `alpha-build-plan.md` A7 tick now reads "done in A5 … see a5-reconcile.md, Departures 3" and no longer claims tests-first or cites the null-time decision. |
| 9 | nit | **The A5-K5 `Code:` block is about 13 lines, against `AGENTS.md`'s "each a few lines at most".** Most of the length is repeated `_resolution(...)` keyword arguments. The plan's version used `_new(...)` / `_matched(...)` helpers and came to 7 lines. Write those two helpers outside the gap, so the lines Ari types are only the lesson (the try/except over `EXTRACTION_ERRORS`, the offered-id check and the confidence bar). | CONFIRMED by reading `artist_match.py:220-235` against the plan's K5 `Code:`. | The gap costs more typing than reasoning, which goes against the Oct 8 "minutes, not research" rule. | **Fixed.** `artist_match._new` and `_matched` are written outside the gap; K5's `Code:` block is now 7 lines (the try/except over `EXTRACTION_ERRORS`, the offered-id and confidence check, the fallback), as the plan's version was. Rebuilt the scaffold and re-verified the gap on a scratch copy. |

**Rejected:** none. Round 1 resolved by the author (Claude Sonnet 5.5), October 17, 2026: 9 of 9 fixed. Test-suite result after the fixes: 668 passed, 112 failed, 10 errors, 15 skipped with the five gaps open (every red result is `NotImplementedError: TODO(Ari)`); 790 passed, 15 skipped with the gaps filled on a scratch copy. No round 2 review was run; the blocker was in written code and is covered by a test that goes through real validation, but Ari may want one given that `excluded_listing_dates` now decides what the page "reached".
