# A5 — reconcile

**Status:** Plan review
**Date:** October 16, 2026
**Author model:** Claude Sonnet 5.5 (plan, October 16, 2026)
**Reviewer model:** (pending: plan review round 1, a model other than the author's)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A5 (and A2.1's carried items: after-midnight times, cancelled and
postponed listings, two untimed shows on one date); `docs/arch/arch-initial.md` §7 ("Reconcile (insert / update /
delete / no-op)" and its outcome table); `docs/arch/requirements-initial.md` ("Agent Reconciliation", "Agent Artist
Creation & Matching", "Show", "Times after midnight", "Cancelled or postponed listings"); `docs/arch/data-model-initial.md`
§2 (`show`, `show_artist`, `artist`) and §3 (`audit_log`); `docs/references/fastapi-style-guide.md`; `apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D9` and the fill-in key points `K1`–`K5`; elsewhere they
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
| A show may have no `time`; what the composite key does with a null (the open decision) | [fill-in] | The same function, its null-time branch — **K1**; decision **D2** |
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

Each decision has a recommendation, and the plan below is written to that recommendation. **Decisions marked ★
change the calendar's behaviour and are yours to confirm**; the rest are mechanics I'd settle myself but am listing
because a different choice changes what gets built.

- **★ D1 — The "covered range" is `[fetched_on, the latest date the page evidences]`, derived in reconcile.**
  The build plan says the graph state must carry how far the run reached, "which it currently doesn't". Today fetch
  is one plain GET with no pagination, so the honest answer to "how far did we get" is "as far as the page's own
  listings go". So:
  - **start** = `state.fetched_on` (the metro's today). A show dated before today is never removed: past shows fall
    off venue pages naturally, and that is not a removal. Shows up to 31 days back can still be *matched*, since
    pages keep last week's listings (`A3`'s plausibility window).
  - **end** = the latest date among the kept shows **and** the shows excluded for naming no act. A listing the page
    shows, even one we left out, proves the page reached that date. Shows excluded for an implausible date
    (`DATE_OUT_OF_WINDOW`) are *not* evidence of reach: a year-2028 JSON-LD entry would otherwise stretch the window
    over every stored show.
  - **Absence is judged against the page, not the validated list.** A stored show is not removed when an excluded
    listing (no act found by the splitter) sits on its date: the splitter drops real shows (Mortimer's, two on every
    run — `validation.py` says so), and "the validated list lacks it" would delete the very show the splitter missed.
  - **A confirmed-empty page has no end date, so no window, so nothing is removed.** It is recorded in the audit
    row (`coverage: null`). The cost: a venue that really cancels every show keeps stale rows until a human looks.
    Chosen because "an empty list is the most dangerous output" (`requirements-initial.md`, Agent Validation).
  - **The cost of "latest listed date" as the end:** a show stored for a date *beyond* the page's last listing is
    never removed by that run, even if the venue dropped it. That under-removes (a stale show lingers until the page
    reaches it) rather than over-removes. When fetch learns to paginate (Playwright, H-phase), it will record how
    deep it got and the window becomes the smaller of the two; that field doesn't exist yet and isn't added now
    ("don't build what has nothing to consume it").
  - *Alternative:* a fixed horizon (for example, fetched_on + 28 days) regardless of the page. It removes more, and
    wrongly, on any venue that lists fewer weeks.
- **★ D2 — Null-time matching (the build plan's open decision, "Ari confirms in A5's plan").**
  Per date, matching runs in two passes over the listings and the stored shows (every status, so a returning show
  is found):
  1. **Timed exact.** A listing with a time matches a stored show with the same `start_time`. Two stored shows at
     one time (rare: two rooms) tie-break on shared act names, then lowest id.
  2. **Null-time pairing, on what is left.** A listing and a stored show pair only if **at least one of the two
     times is null**; two different non-null times never pair (that is the requirements' "time change = cancelled +
     new"). Among the leftovers: if there is exactly one listing and one stored show on that date, they pair; if
     there are several, a pair needs a shared act name and must be the best overlap for both sides. Anything still
     unpaired is an insert (listing) or a removal candidate (stored), and is **flagged `needs_review`** in the audit
     row.
  - A time appearing later (null → 20:00) is an **update**, not remove + insert. This is the recommendation in the
    build plan.
  - The case that exists today: 7th St Entry lists two untimed shows on October 31. They pair with their stored
    twins by shared acts. If the lineups changed completely, the result is two inserts and two removals, both
    flagged. That is wrong-looking but visible, safe, and revertable.
  - *Alternative:* never pair a null time; always insert + remove. Simpler, and it churns every untimed venue every
    night (Terminal Bar has no times at all).
- **★ D3 — An unstated field never erases a stored one.** If the new extraction has `end_time`, a price,
  `free_admission` or `image_url` as null and the stored show has a value, that field is left as stored; only a
  *different non-null value* is a change. Reason: the project's rule is "missing is tolerated, wrong is not"
  (A3-D4); a model that fails to read a price on Tuesday must not erase Monday's price. The cost: a venue that
  genuinely removes a price can't clear it through the pipeline (a human edit can; edits are deferred). The lineup
  is the one thing replaced wholesale (a lineup change is an update, per the requirements). `start_time` follows the
  same rule (a null time never clears a time), and is the field D2's null → time update fills.
- **★ D4 — Cancelled and postponed reuse `removed`; no new enum value.**
  - The data model's `show_status` is `active | removed`; the read API hides `removed`; the requirements say a
    cancelled listing is "not a show to display". So a cancelled or postponed listing that matches a stored
    **active** show → `remove` (reason `cancelled` or `postponed` in the audit detail). It matches a stored
    **removed** show → no-op. It matches nothing → `skip` (never inserted; only a first scan can ignore it, but it is
    never worth an insert either).
  - A **scheduled** listing that matches a stored **removed** show → `update` back to `active` ("reactivate", reason
    `reappeared`). Without this, a show wrongly removed (or un-cancelled) is re-inserted as a duplicate.
  - *Alternative:* add `cancelled` to `show_status`: a migration, an `api-contract.md` change and a regenerated
    `api-types.ts`, for a state the UI would hide anyway. The audit detail keeps the distinction a person needs.
- **D5 — Ambiguous artist matching: stdlib `difflib`, all artists loaded per run, a model asked about at most three
  candidates, and a conservative fallback.**
  - **Normalised key** (`artist_key`): `fold_text`, accents stripped, `&` read as `and`, punctuation dropped, a
    leading "the " dropped. Two names with equal keys are an **exact** match (`Poliça` = `Polica`, `The Hold Steady`
    = `Hold Steady`, `Jenny Lake & Friends` = `Jenny Lake and Friends`).
  - **Ambiguous** = not exact, and either `difflib.SequenceMatcher` ratio of the keys ≥ 0.85, or the shorter key's
    words are all in the longer key's words (containment: `Zhora` ⊂ `Zhora Band`). **None** otherwise. Ratios
    measured on October 16, 2026 with `difflib` (so the examples in the tests are not guesses): `Dessa`/`Desa` 0.889,
    `Low`/`Lowe` 0.857, `Cats`/`Cat` 0.857 — ambiguous. `Zhora`/`Zhora Band` 0.667 and `Prince`/`Prince Rogers`
    0.632 — below any usable ratio threshold, which is why containment is a separate rule. The numbers are **a
    starting point** in a named `ArtistMatchPolicy`, to be calibrated against labelled data in A8, exactly as A3's
    confidence threshold was.
  - **All artists are loaded per run** as `(id, name)` pairs and compared in Python. Hundreds to low thousands of
    rows at alpha scale; no `pg_trgm` extension or migration. Revisit when the table is large (noted in "Not doing").
  - **The model answers one question per ambiguous name:** given the incoming name and up to three candidate
    artists, is it the same act as one of them (which)? A confidence is requested.
  - **Fallback is the conservative direction:** an answer below `min_confidence` (0.8), a refusal to choose, or a
    failed model call (`EXTRACTION_ERRORS`) means **create a new artist**. A duplicate artist is a known, revertable
    annoyance (merging is deferred: `data-model-initial.md` §5); a wrong merge corrupts two acts' pages silently.
    The fallback is written to the audit row so it is visible.
  - **Resolution is per run, per distinct key.** The same new name on three shows is one new artist, not three
    (reconcile runs before commit, so the database can't tell commit "already created"). Within one show, two acts
    that resolve to the same artist collapse to one lineup entry (`show_artist` is keyed by (show, artist)).
  - *Alternatives:* `rapidfuzz` (a new dependency, for the same ratio) or `pg_trgm` (a migration). Neither is needed
    for alpha.
- **★ D6 — A removal guard.** If absence would remove **three or more** stored shows **and more than half** of the
  active stored shows inside the window, those removals are **withheld**: nothing is removed by absence in that run,
  and the audit row says so (`removals_withheld`, with the shows). Explicit cancellations are not withheld (they are
  evidence, not absence). Reason: A3's checks catch the empty page and the under-reported JSON-LD page, but a page
  that is merely truncated (a venue's site returning half a calendar) passes them and would silently wipe half the
  calendar. The guard turns the silent case into a visible one. The cost: a legitimate mass removal waits for a
  person. Both numbers live in `ReconcilePolicy`. *Alternative:* no guard, trusting A3. I'd rather pay the small
  code (about ten lines, pure, tested) than find out on a real venue.
- **D7 — The database read lives in the `trace.audited` wrapper, before the thread, behind a `CalendarReader` on
  `WorkerContext`.** Same pattern as the `AuditWriter` and `Stager` (a protocol, a Postgres implementation, a
  recording fake for graph tests). For the reconcile step the wrapper computes the load request (a pure function of
  the state), `await`s `reader.stored_shows(...)` and `reader.artists()`, puts the results on the state, then runs
  the sync `reconcile_node` in the thread as before. The node body stays a pure state → state function, tested
  without a database; the model call inside it stays a synchronous client call like extract's. **A reader that raises
  stops the run** (the exception propagates, the run is closed by `run_venue`'s `finally`): guessing an empty
  calendar would insert duplicates of everything. *Alternative:* make `reconcile_node` `async` and read inside it;
  rejected for the reason A4-D1 rejected async node bodies.
- **D8 — What reconcile writes to the audit trail: one summary row, plus one row per model decision.** The
  `reconcile` row is venue-level (entity = the venue) with `detail` carrying the counts per action, the coverage,
  the `needs_review` list, withheld removals, artist counts and which decisions the model made. **Each ambiguous-artist
  model decision gets its own `reconcile` row** with `entity_type = artist`, `entity_id` = the matched artist (null
  when the answer was "new"), `model_used`, `confidence`, and in `detail` the incoming name, the candidates offered,
  the answer, the reason and whether the fallback applied: "the one place a model makes a database decision is the
  one that most needs auditing". **Per-show rows with `previous_value` / `new_value` stay A6's** (they record what was
  *written*). A new saved query (`audit-queries.sql`) lists the model's artist decisions.
- **D9 — `reconcile_decision` leaves `VenueGraphState`, replaced by `reconcile_plan`.** The old field is a single
  `Literal["no_op", "delete", "insert", "update", "ambiguous_match"]`, which can't describe a run that inserts three
  shows, updates two and removes one. `ReconcilePlan` carries the per-show decisions A6 executes. Touches the audit
  stub, `commit_node`'s log line and the tests that read the old field (listed in "Critical files").

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
ReconcilePolicy  max_removal_share = 0.5, min_removals_to_guard = 3     # D6; one named place, as RetryPolicy
```

The functions, in the order a reader should take them:

| Function | Job | Marking |
|---|---|---|
| `night_sort_key(date, time)` | Orders by listed night, with times before `NIGHT_CUTOFF` after the evening's. Used wherever reconcile needs a deterministic order | [written] |
| `listings_from(state)` | The kept shows as `Listing`s, with `status` read by `getattr(show, "status", "scheduled")` | [written] |
| `covered_window(state)` | D1: `Coverage` or `None` (confirmed-empty page) | [written] |
| `lineup_for(show, resolutions)` | Resolved lineup with sequence numbers: stated numbers are kept only if every act has one, otherwise all are renumbered by list position; the same artist twice collapses to the first | [written] |
| `match_shows(listings, stored)` | D2: the two-pass match; returns pairs and unmatched sides | **K1** |
| `plan_for_listing(listing, stored)` | What a listing means given its matched stored show (or none): insert, update, no-op, remove, skip, reactivate — the A2.1-D12 status rules | **K3** |
| `show_changes(stored, listing, lineup, original_url)` | D3: field-by-field comparison, `{field: (old, new)}`, empty = no-op. Prices compared as `Decimal(str(v)).quantize(0.01)` | [written] |
| `removed_by_absence(stored, matched_ids, coverage, excluded_dates)` | D1: the soft delete | **K2** |
| `withhold_if_mass_removal(removals, in_window_active, policy)` | D6 | [written] |
| `build_plan(...)` | Orders the steps below and assembles the plan | [written] |

`build_plan` order (each step's output feeds the next, which is why artist resolution is first):

1. Resolve artists once per distinct `artist_key` (exact → none → ambiguous → model, `artist_match.py`).
2. Match listings to stored shows (K1).
3. For each pair or unpaired listing, decide the action (K3) and compute the changes (D3).
4. Soft-delete stored shows absent from the page, inside the window (K2).
5. Apply the guard (D6).
6. Sort the decisions by `night_sort_key` so the plan, and the audit row, read in calendar order.

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

### The wiring

- `context.py`: `WorkerContext` gains `reader: CalendarReader`.
- `state.py`: `stored_shows`, `known_artists` (loaded by the wrapper), `reconcile_plan` (set by the node);
  `reconcile_decision` removed (D9).
- `trace.audited`: for `StepType.RECONCILE`, before the thread, compute `reconcile.load_request(state)`, `await` the
  reader, put the results on the state; after the thread, write the summary row, then one row per model decision
  (`audit.model_decision_entries(state)`).
- `nodes.reconcile_node`: calls `build_plan` with the model client; sets `state.reconcile_plan`; logs a summary.
- `nodes.commit_node`: still a stub, now logging the plan's counts instead of the removed field.
- `audit.py`: `_detail` for `RECONCILE` (D8); `RECONCILE` joins `_VENUE_LEVEL`; `COMMIT` stays a stub row.
- `main.py` and `local_test.py`: build `PostgresCalendarReader(SessionFactory)`.

## Test approach (written first, watched fail, then made green)

Every test is written before its code and watched fail (build plan §3). Tests follow `AGENTS.md`: each opens with
`Proves:`, tests sit under labelled section comments, and the source of every expected value is stated. **Expected
values come from the requirements and the data model and from the literal inputs, never from the code under test.**
Four layers.

### 1. Pure show decisions (`agent_worker/tests/test_reconcile_shows.py`)

Hand-built `StoredShow`s and `Listing`s; no database, no model. Sources: `requirements-initial.md` "Agent
Reconciliation", `arch-initial.md` §7's outcome table, D2–D4.

- **Section: the composite key (K1)**
  - same date and time, same details → pair, `no_op`;
  - same date and time, different lineup → `update` (lineup change), not remove + insert;
  - 8 pm stored, 9 pm listed, same date → **no pair**: one `remove` and one `insert` (the requirements' own example);
  - null → 20:00 (stored untimed, listing timed) → `update` filling `start_time`, one pair;
  - 20:00 → null (stored timed, listing untimed), one of each on the date → pair, and `start_time` is **not**
    cleared (D3);
  - two untimed shows on one date, both stored: pair by shared acts (the 7th St Entry, October 31 case), even when
    the listings come in the opposite order;
  - two untimed, lineups changed completely: no pair, two inserts and two removal candidates, all `needs_review`;
  - two timed shows at the same time on one date: pair by shared acts, then lowest stored id;
  - a returning show: stored `removed`, listed `scheduled` → pair, `update` to `active`;
  - **a show with no `time` and per-act times** (A2's White Squirrel seed 2) reconciles without error and without
    inventing a show time.
- **Section: cancelled and postponed (K3)**: the matrix from D4 — cancelled × {stored active → `remove`, stored
  removed → `no_op`, no stored → `skip`}, postponed the same, scheduled × {stored removed → reactivate}. The audit
  reason distinguishes `cancelled` from `postponed`. A `skip` creates no insert and no artist.
- **Section: what counts as a change (D3)**
  - a different price, end time or image → `update` with that field in `changes`; a null in any of them → unchanged;
  - prices compare as money: stored `Decimal("20.00")` equals extracted `20.0`; `19.99` differs;
  - `original_url` differing alone → `update` (the doc: "overwritten on each successful reconcile");
  - lineup order changed → `update`; the same names with the same order → `no_op`;
  - **idempotency:** feeding a plan's own result back in as the stored shows (a test-only simulator that mirrors what
    commit will do) gives all `no_op`s. This is the property that stops a show flipping nightly; A6 later replaces
    the simulator with a real round trip.
- **Section: lineups**: `sequence_number` from list position when none is stated; stated numbers kept only when every
  act has one (a mix is renumbered, since mixing would collide); an artist named twice in one show appears once.
- **Section: after midnight**: `night_sort_key(Fri, 01:00)` sorts after `(Fri, 20:00)` and before `(Sat, 20:00)`; the
  cutoff itself (05:00) is evening, 04:59 is after midnight; a 01:00 show listed under Friday and stored under
  Friday matches by the plain key, with no date arithmetic.

### 2. Pure soft delete and the guard (`agent_worker/tests/test_reconcile_removal.py`)

Sources: `requirements-initial.md` ("falling within the date range that fetch actually covered"), D1, D6.

- **Section: the window (K2)**
  - a stored active show on a covered date and absent from the page → removed;
  - **a stored show dated after the page's last listed date is untouched** (the subtle half of the lesson);
  - a stored show dated before `fetched_on` is untouched (past shows fall off pages);
  - a show dated exactly on `fetched_on`, and one exactly on the last listed date, are inside (inclusive both ends);
  - an already-`removed` stored show is never removed again;
  - **an excluded listing on a stored show's date protects it** (the splitter may have dropped it); an excluded
    listing on another date doesn't;
  - an out-of-window excluded listing (a 2028 JSON-LD entry) does not stretch the window.
- **Section: the empty page**: `covered_window` is `None` for a confirmed-empty page, so nothing is removed, the plan
  says `coverage: None`, and stored shows are untouched. A page with only cancelled listings still has a window.
- **Section: the guard (D6)**: 3 of 4 in-window active shows missing → all three withheld and none removed; 2 of 4
  missing → removed (below the minimum); 3 of 8 missing → removed (not more than half); a cancelled listing's removal
  is never withheld; the plan lists what was withheld.

### 3. Artists (`agent_worker/tests/test_artist_match.py`)

Sources: `requirements-initial.md` "Agent Artist Creation & Matching"; D5; the difflib ratios in D5 (measured, not
assumed).

- **Section: classification (K4)**: exact on case, accents, a leading "The", `&` vs `and`, spacing; ambiguous on
  `Dessa`/`Desa` and `Low`/`Lowe` (ratio), on `Zhora`/`Zhora Band` (containment); none on `Zhora`/`Prince`.
  Boundary: a policy with `ratio = 0.9` turns `Low`/`Lowe` into `New`, proving the threshold is read from the policy,
  not hard-coded. Two stored artists with equal keys → exact, lowest id, and the duplicate is reported.
- **Section: the model branch (K5)**, with `fakes.ScriptedClient` (a new `ARTIST_MATCH` script key): "same, 0.93,
  id 7" → `matched_by_model`, id 7; "different" → `new_after_model`; "same" at 0.6 (below `min_confidence`) →
  `new_after_model`; a raised `InstructorError` → `new_after_model`, with the error text in the reason and no
  exception out; an answer naming an id that wasn't offered → `new_after_model` (a model can hallucinate an id; it
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
  - **A reader that raises propagates out of `ainvoke` and no reconcile row is written** (D7: an unreadable calendar
    must not look empty).
  - The existing context-injection test (`test_the_context_reaches_the_audited_nodes`) still passes with the new
    `reader` field.
- **`tests/test_audit_entries.py` (updated):** reconcile now names the venue as its entity; its `detail` is the D8
  shape (keys listed in the test); `model_decision_entries` builds the artist rows: `entity_type = artist`,
  `model_used` from the resolution, `confidence` through `audit_confidence` (a `None` stays `NULL`, A3-D9), and the
  JSON-serializable check from A4 extends to them.
- **`tests/test_calendar_reader.py`** (Postgres, `db_session`): `stored_shows` returns shows in the range with
  lineups ordered by sequence, **including `removed` ones**; excludes other venues and out-of-range dates; `artists()`
  returns every artist. Seeded with `polyfactory` factories using a fixed seed (build plan A7 names `polyfactory` as
  unused since Phase 3; this is its first consumer).
- **`tests/test_reconcile_db.py`** (Postgres): the whole decision logic against a database seeded the way a venue
  looks after weeks of runs (the A7 item, pulled forward): insert, update, no-op and soft delete in one plan; a
  returning removed show; an artist found by `Poliça` vs `Polica`.
- **`tests/test_audit_queries.py` (extended):** the new saved query `artist_match_decisions` runs against a scripted
  run that made one model decision, and returns exactly that row (and none from a run that made none).
- **Existing tests:** every `WorkerContext(...)` call site gains `reader=` (listed in "Critical files");
  `test_graph.py`'s `reconcile_ran` helper currently reads `state.reconcile_decision`, which D9 removes, so it reads
  `state.reconcile_plan is not None`.

### What is not covered, stated plainly

- **The model on real data.** The cloud sandbox has no Ollama. The ambiguous-artist prompt is tested for what it
  sends and how its answer is handled, with a scripted client; whether the real model answers well is unmeasured. The
  thresholds in D5 are starting values, to be calibrated in A8. Ari runs the live check locally (Verification §5).
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

- **K1 — the composite-key match, in `reconcile.py` (`match_shows`).** *(Build plan items 1 and 3; D2.)*
  - *Lesson:* the key is (venue, date, time), exact, with no fuzzy matching on shows (`arch-initial.md` §7), and the
    whole subtlety is what a **null** does. In SQL `NULL = NULL` is not true, so a naive key never finds an untimed
    show: every night would insert a duplicate and remove the old one. The rule is: two different times never pair
    (that is a time change); a null on either side pairs only when it is unambiguous (one listing, one stored show on
    the date) or when shared acts settle it. Everything unpaired is flagged, not guessed.
  - *Code:* written around the gap — the grouping by date, the timed pass, the consumed-set bookkeeping. The gap is
    the null-time pass:
    ```python
    # leftovers on this date: ls (listings), ss (stored shows), both sorted by night_sort_key / id
    pairable = [(l, s) for l in ls for s in ss if l.show.time is None or s.start_time is None]
    if len(ls) == 1 and len(ss) == 1 and pairable:
        pairs.append(pairable[0])
    else:
        pairs += _mutual_best_by_acts(pairable)   # written: shared act keys, best for both sides, ties → none
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_reconcile_shows.py -k "composite or null or untimed"`. The
    likeliest mistake is pairing *any* leftover listing with *any* leftover stored show on the date, which turns an
    8 pm → 9 pm change into an update (the requirements say it is remove + insert); the 8 pm / 9 pm test catches it.
    The second likeliest is `l.show.time == s.start_time` for the null case (`None == None` is `True` in Python,
    unlike SQL), which pairs two *different* untimed shows; the two-untimed-shows test catches it.

- **K2 — the soft delete, in `reconcile.py` (`removed_by_absence`).** *(Build plan item 4; D1.)*
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

- **K3 — what a listing means given the stored show, in `reconcile.py` (`plan_for_listing`).** *(Build plan item 8;
  D4; `A2.1-D12`.)*
  - *Lesson:* a cancelled or postponed listing is **evidence about a stored show, not a show**
    (`requirements-initial.md`: "the agent has to match it to that stored record and update it"). It must never be
    inserted, and a scheduled listing that matches a removed show must bring it back instead of duplicating it.
    The status decides *what the match means*, which is why it is a function of both the listing and the stored show.
  - *Code:*
    ```python
    if listing.status != "scheduled":              # cancelled / postponed
        if stored is None:
            return ShowDecision(Action.SKIP, ..., reason=f"{listing.status} listing, no stored show")
        if stored.status is ShowStatus.ACTIVE:
            return ShowDecision(Action.REMOVE, ..., reason=listing.status)
        return ShowDecision(Action.NO_OP, ..., reason=f"already removed ({listing.status})")
    if stored is None:
        return ShowDecision(Action.INSERT, ...)
    # scheduled + stored: reactivate if it had been removed, else compare the details
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_reconcile_shows.py -k "cancelled or postponed or returning"`. The
    likeliest mistake is falling through to `INSERT` for a cancelled listing with no stored show; the `skip` test
    catches it.

- **K4 — classify an artist name, in `artist_match.py` (`classify_artist`).** *(Build plan item 5; D5.)*
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
  (`decide_ambiguous`).** *(Build plan item 6; D5, D8.)*
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

No migration. `show_status` keeps `active | removed` (D4), `audit_log.entity_type` already has `artist`, `show.original_url`
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

`context.py`, `state.py`, `trace.py`, `nodes.py`, `audit.py`, `main.py`, `local_test.py`, and the fakes
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
  with the distinction in the audit trail (D4).
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
4. **`reconcile_decision` is removed from the state** (D9).
5. **The "deterministic or LLM" distinction in the audit trail** (`arch-initial.md` §7, "Audit trail extensions") is
   carried by one row per model decision plus `decided_by` in the summary, not by a column (D8).

## Critical files

| File | Change |
|---|---|
| `apps/api/agent_worker/reconcile.py` (new) | The pure core — K1, K2, K3 |
| `apps/api/agent_worker/artist_match.py` (new) | Names, classification, the model question — K4, K5 |
| `apps/api/agent_worker/calendar_reader.py` (new) | `CalendarReader`, `PostgresCalendarReader` |
| `apps/api/agent_worker/prompts.py` | The artist-match prompt |
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

## Not doing in A5

- **Writing to the calendar** — A6 (`commit_node`, the per-show `audit_log` rows with `previous_value` /
  `new_value`, the price conversion at the write, the `event` rows, `show.original_url`).
- **A decision memory for ambiguous artists** (an alias table, so the model isn't re-asked each night about
  the same pair). The cost is a model call per ambiguous name per run, deterministic at temperature 0, and
  rare. It is the same gap as artist merge/de-duplication (`data-model-initial.md` §5); the schema change belongs to
  that feature.
- **`pg_trgm` / `rapidfuzz`** for artist similarity (D5), until the artist table is large enough for the Python scan
  to matter.
- **Pagination-aware coverage** (D1), until fetch paginates.
- **Concurrency control** between workers on one venue.
- **A `needs_review` queue.** The flags are in the audit row only; a review UI or queue is a later feature
  (`requirements-initial.md`, "Manual & Flagged Re-processing").
- **Moving `NIGHT_CUTOFF` to `constants.py`** (see Known gotchas).
- **Changing the frontend or the read API.** B3/B4 already order and display after-midnight times; the read routes
  are still on `sample_data.py` (A1b), and ordering there is that milestone's.

## Approval

*(Awaiting Ari. After the plan review round and its resolution, the status becomes `Awaiting approval`. Ari sets
`Approved` and may re-mark any [written] item [fill-in] or the reverse; `/build-milestone` records the approval.)*
