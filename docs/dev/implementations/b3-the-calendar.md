# B3 — the calendar

**Status:** Awaiting sign-off — code review round 1 resolved (5 fixed, 1 rejected for now). **Ari: fill Gaps A–E, then do the browser/keyboard check (Verification 7) and decide finding #4.**
**Date:** October 12, 2026
**Author model:** Claude Opus 5.5 (plan, plan-review resolution); Claude Sonnet 5.5 (implementation, from October 12, 2026)
**Reviewer model:** Claude Sonnet 5.5 (plan review round 1) — findings under [Plan review](#plan-review); Claude Opus 5.5 (code review round 1) — findings under [Code review](#code-review)
**Spec:** `docs/dev/alpha-build-plan.md` §6 B3; `docs/arch/requirements-initial.md` ("Global Requirements", "Calendar
(Including Home Page)", "Show" — including "Times after midnight", "Metro"); `docs/arch/arch-initial.md` §4 (calendar
UI, dates, filter state) and §11 (caching, deferred); `docs/dev/api-contract.md` §2–4; `docs/references/nextjs-style-guide.md`;
`docs/dev/implementations/b2-routes-and-data-loading.md` (D1–D4, which B3 inherits)

## Context

B2 left `/` as a plain list: filters parsed from the URL, the matching shows from the API, rendered by a throwaway
`PlainShowList` with one demo `<Link>` per venue standing in for a filter UI. B3 replaces that with the real calendar
`requirements-initial.md` describes: "a vertically scrollable list of dates with horizontally scrollable group of
venues. Each venue is a mini column of its own and can contain 1-2 shows. Each show is represented as a block", with a
filter header above it (venue and artist multi-selects with type-to-filter, a future-only month dropdown) and a "No
matches found" state with a reset link.

`arch-initial.md` §4 is explicit that this is "fully custom, not a calendar-grid library … closer to a feed". It is
the first milestone with real client-side interactivity (the filter header) and the first that has to get layout
right across phone, tablet and desktop.

What B3 is *not*: the day view's three sort modes, the venue page's embedded calendar, `/venues` and `/artists`
polish, `/show/[id]` and JSON-LD (all B4); component tests with Testing Library (B5); the past-dates toggle, genre
and text search (requirements: "later"); caching (`arch-initial.md` §11).

### What B3 delivers

| Piece | Where | Notes |
|---|---|---|
| Calendar grid: date rows → venue columns → show blocks | `app/_components/calendar-grid.tsx` (Server Component) | Built on a pure `groupCalendar()` in `lib/calendar.ts` |
| Show block | `app/_components/show-block.tsx` (Server Component) | Used by the grid and by `/day/[date]`; B4 reuses it on the venue page. Location is D3 |
| Filter header | `app/_components/filter-header.tsx` (`"use client"`) | Venue and artist comboboxes, month select, clear link. Writes the URL; holds no results |
| Dates and times via Temporal | `lib/dates.ts` | Day headings, show times (including after midnight), month labels, the metro's "today" |
| Empty state | in `app/page.tsx` | "No matches found" + reset link when filters match nothing |
| Streaming on `/` | `app/page.tsx` | `<Suspense>` with a skeleton around the data-dependent body (D4) |
| `getCalendarMonths()` | `lib/api.ts` | B2 deliberately left it out: its only consumer is this dropdown |
| `/day/[date]` uses show blocks | `app/day/[date]/page.tsx` | So `PlainShowList` can be deleted; the sort modes stay B4 |

Deleted: `app/_components/plain-show-list.tsx` and the demo venue links on `/` (B2 marked both as B3's to delete).

### Decisions already made (earlier in this project)

- **Filters are URL search params** (`arch-initial.md` §4), parsed by `lib/params.ts` and written by
  `buildCalendarHref` (B2). Keys `venue`, `artist` (repeatable ids) and `month=YYYY-MM` (whole calendar month, B2 D2).
  B3 adds no keys.
- **The server owns "now"** (`api-contract.md` §3): the default window is whatever `start`/`end` the API echoes; the
  month dropdown's options come from `GET /calendar/months`, which decides "future-facing" and "has shows".
- **Every route is dynamic, nothing cached** (B2 D1). Unchanged.
- **Server Components fetch; `"use client"` only on the smallest interactive leaf** (style guide). Here that is the
  filter header and nothing else.
- **Times after midnight** (Ari, October 11, `requirements-initial.md` "Show"): a show belongs to the night the venue
  lists it under; a time before 5:00 AM is after midnight of that night, sorts after the evening's shows, and is
  displayed with the next day ("1:00 AM Sat"). The build plan's A5 item assigns the display to B3/B4.
- **Null admission means "not stated", never free** (`api-contract.md` §4). Money is a string; never `parseFloat`.

### What "dates in the metro's timezone" actually means here (checked)

The build plan's Temporal item says the calendar must render "in the metro's timezone rather than the browser's".
That is true but easy to misread, so the plan states it precisely:

- **Show dates and times need no conversion.** The API sends wall-clock values in the metro's zone
  (`requirements-initial.md`, "Metro": "what a listing says ('8 pm') is stored as written"), as `"2026-10-12"` and
  `"20:00:00"`. They become `Temporal.PlainDate` / `PlainTime`, which have no zone at all, so formatting them can't
  shift a day. Checked: `PlainDate.from("2026-10-12").toLocaleString("en-US", {weekday, month, day})` gives
  "Mon, Oct 12" under `TZ=Pacific/Kiritimati` (UTC+14) and `TZ=Pacific/Pago_Pago` (UTC−11) alike.
- **The zone matters for exactly one thing: "today".** Marking the row that is today requires asking what date it is
  *in Minneapolis*. This code runs on the Next server, not in the browser — and on Vercel the server's zone is UTC, so
  `new Date()` or a zone-less `Temporal.Now.plainDateISO()` says "tomorrow" from 7 PM Central onward (6 PM in winter).
  Checked: `Instant.from("2026-10-13T02:30:00Z").toZonedDateTimeISO("America/Chicago").toPlainDate()` is
  `2026-10-12`. This is Gap A.
- **The trap that remains is `new Date("2026-10-12")`** (UTC midnight, the 11th west of Greenwich). B3 adds no
  `Date` anywhere; the review checklist should grep for it.

### Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **The show block lives in `apps/calendar`, not `packages/ui`** — if Ari approves D3. The build plan's reason for
   `packages/ui` ("since the day view and venue page reuse it") is satisfied inside one app: both consumers are
   `apps/calendar` routes. The shadcn primitives the filter header needs *do* go in `packages/ui`, per
   `apps/calendar/AGENTS.md`.
2. **Two [fill-in] items have no line that carries a lesson** and are proposed as [written] (D6): the show block
   (markup; its one real rule — after-midnight display — is Gap B in `lib/dates.ts`) and the empty state (one
   condition and a link).
3. **The Temporal item's wording** is sharpened to the section above: wall-clock values need no zone; "today" does.
4. **Added, not in the build plan's B3 list:** `<Suspense>` streaming on `/` (B2 D4 said "add it with B3"; D4 here);
   `getCalendarMonths()`; four rows of sample data (D5); a Temporal-free module for `buildCalendarHref` so the client
   bundle doesn't ship the polyfill (step 5); switching `/day/[date]` to show blocks so `PlainShowList` can go.

## Decisions for Ari

**Settled by Ari, October 12, 2026: all eight recommendations accepted.** D1 — sparse date rows with per-row sideways
scrolling; Ari's reason: browsing one venue is a lower-priority use case (a reader after one venue should go to the
venue's own site or our venue page), so column alignment across dates isn't worth an emptier grid. (Ari's wording was
"go with my original design"; I read that as the plan's recommended design, the one matching `requirements-initial.md`'s
"vertically scrollable list of dates with horizontally scrollable group of venues".) D2 — a thin row for empty dates;
in a sizable metro they will be rare. D3 — app-local show block; if the Admin app ever needs it, re-architect then.
D4, D5, D6, D8 — as recommended. D7 — no cap on shows per venue per date (Ari: the many-shows case is mostly an
all-day festival, but the cap shouldn't be 2). The original text follows, unchanged.

Each has a recommendation; the plan is written assuming the recommendation. **Ari: please confirm or change D1–D8
before approving** — D1 and D4 change the most code.

- **D1 — Row model: one row per date holding only the venues that have shows that day, each row scrolling on its own.
  Recommended.** A date row lists the venues with a show that date, alphabetically, as columns in a horizontal
  scroller; a date with no shows is a slim row (D2). Reasons: the data is sparse (the sample has at most two venues on
  any date; a real metro has tens of venues and most are dark on most nights), so a full grid would be mostly empty
  cells; it matches "closer to a feed"; and independent horizontal rows inside a vertical page is the familiar
  carousel pattern that touch browsers handle well (axis locking). Cost: a venue isn't in the same horizontal position
  on every date, so "what's on at the Entry this week" is a scan, not a column read — that question is answered by
  the venue filter (and B4's venue page).
  *Alternative:* an aligned grid — every venue a column on every date, one two-dimensional scroll container with a
  sticky venue-name header row and a sticky date column. Better for comparing one venue across dates; much emptier,
  and a 2D scroll region is the hardest case on touch. Choosing it rewrites steps 3 and 7 and Gap E (the grid becomes
  one `overflow-auto` container with `position: sticky` on two axes). Note that B1's comment in `globals.css` mentions
  "B3's sticky date and venue headers", which suggests B1's author pictured this alternative; it was never decided.
- **D2 — Every date in the range is a row, including dates with no shows. Recommended.** It is what makes it a
  calendar rather than a list, and `sample_data.py` keeps an empty day on purpose ("the calendar has to render a date
  with no shows"). Empty rows are one line ("Nothing listed"). With a venue or artist filter most rows go empty;
  that is honest (the venue has nothing those nights) and the "No matches found" state covers zero results.
  *Alternative:* only dates with shows (a pure feed), or all dates unfiltered and only matching dates when filtered.
- **D3 — The show block is app-local (`app/_components/show-block.tsx`), not in `packages/ui`. Recommended.** Both
  consumers are in `apps/calendar`. Putting it in `packages/ui` would make the design-system package import
  `next/link` and the calendar's API types (`ShowSummary`), coupling it to one app, or would need a props layer with
  no second consumer. The project's component-library requirement (`project-overview.md`) is met by `packages/ui`'s
  shadcn primitives, which B3 starts using in the app for the first time (combobox, select). *Alternative:* the build
  plan's wording — `packages/ui/src/components/show-block.tsx` with plain props (strings and hrefs), the app mapping
  `ShowSummary` to them.
- **D4 — Streaming on `/` only: a `<Suspense>` boundary with a skeleton inside the home page; no root `loading.tsx`.
  Recommended.** B2 D4 deferred `loading.tsx` to B3 with two consequences recorded: it lets the shell render during
  an API outage (fixing B2's bare-500 document), but once a response streams, `notFound()` returns HTTP 200 (a soft
  404). A root `loading.tsx` wraps *every* page, so every detail page's 404 would turn into a 200. `/` never calls
  `notFound()`, so a boundary inside `/` gets the benefits there and costs nothing elsewhere. Consequence, to accept:
  with the API down, `/` now answers **HTTP 200** with the header, footer and skeleton, and `error.tsx` replaces the
  skeleton after hydration (B2 Verification 6 changes for `/` only; detail pages keep the bare 500). *Alternatives:*
  no streaming (B2's behaviour), or root `loading.tsx` (soft 404s everywhere).
- **D5 — Add four rows to `apps/api/app/sample_data.py`. Recommended.** The sample data never puts two shows at one
  venue on one date (the "1-2 shows" case that defines a venue column), has no show after midnight, and never has more
  than two venues on a date, so nothing overflows a desktop row. Building the layout "with static data first" against
  data that lacks its hardest cases defeats the point. Append (so existing ids 1–21 don't change) four shows on
  2026-10-07 (offset 9), which already has The Terminal Bar at 21:00 with Jaedyn James, Tarnation and Beasthead — so
  none of those three is reused that night (review #7: no double-booking):

  | Venue | Start–end | Lineup (existing artists) | Advance / day / free | Exercises |
  |---|---|---|---|---|
  | The White Squirrel Bar | 18:00 | Lanue | — / — / — | two shows at one venue (early); all-null admission renders nothing, not "Free" |
  | The White Squirrel Bar | 22:00–00:30 | Nooky Jones (22:00), Pert Near Sandstone (23:15) | — / 10.00 / — | two shows (late); end after midnight; per-act times; unlabelled price |
  | Zhora Darling | 20:00 | Charlie Parr | 20.00 / 25.00 / — | Charlie Parr appears at another venue on another date (artist filter check) |
  | The Midway Saloon | 01:00 | Dead Man Winter | — / — / true | after midnight → "1:00 AM Thu"; sorts last; free |

  That date then has all four venues. This is a Python change in Track A's file, regenerates the fixtures
  (`make fixtures`; `shows.json` and `calendar-months.json`, October 18 → 22) and updates the "21 shows" in
  `api-contract.md` §8 and `alpha-build-plan.md` Track 0 (review #8). *Alternative:* leave sample data alone and cover
  these cases only in unit tests with hand-built shows.
- **D6 — Re-mark the show block and the empty state [written].** Per `AGENTS.md` ("If no line in a [fill-in] task
  meets that bar, say so … propose re-marking it [written] — don't invent a gap"). The show block's lesson-bearing rule
  (after-midnight display) sits in `lib/dates.ts` as Gap B; what remains is markup. The empty state is
  `isFiltered && shows.length === 0` and a `<Link href="/">`.
- **D7 — A venue with three or more shows on one date shows all of them. Recommended.** The requirement says a column
  "can contain 1-2 shows", which describes the usual case rather than a cap; a cap hides real shows behind a link. The
  column just grows taller. *Alternative:* show two and a "+N more" link to `/day/[date]`.
- **D8 — Filter changes use `router.push` (a history entry per change). Recommended.** Back then undoes a filter
  change, which is what "the URL is the state" promises. Cost: several quick selections add several entries.
  *Alternative:* `router.replace` (Back leaves the calendar).

## Test approach (written first, watched fail, then made green)

Same shape as B2: the logic is pulled into pure functions in `lib/` and unit tested under Vitest's node environment;
the async Server Components and the client filter header are **not** unit tested (style guide: no unit tests for
`async function Page()`; Testing Library and jsdom are B5's). Pages are checked by build output, HTTP responses and
Ari's browser check (Verification). Expected values below are worked out by hand from the requirements or the fixture
data, never read back from the code under test; each test says where its numbers come from.

### 1. `lib/dates.test.ts` (new)
`metroToday(timeZone, now)` — **Gap A**:
- `2026-10-13T02:30:00Z`, `America/Chicago` → `2026-10-12` (21:30 CDT on the 12th; UTC already says the 13th — the
  Vercel bug). `2026-10-12T17:00:00Z` → `2026-10-12`. `2026-11-02T05:30:00Z` → `2026-11-01` (23:30 **CST** on the 1st,
  the first evening after the fall-back change at 07:00Z on the 1st; UTC says the 2nd — so the offset used must be
  −6, not −5; review #4). `Pacific/Auckland` at `2026-10-12T12:00:00Z` → `2026-10-13` (a zone ahead of UTC).
`metroTodayOrNull(timeZone, now)` (written, around Gap A): a valid zone → the same date as `metroToday`; an unknown
IANA id (`"Not/A_Zone"`) → `null` instead of a `RangeError` (review #9: the zone is free text in the `metro` row, and a
cosmetic "Today" label must not take the calendar down).
`isAfterMidnight(time)` — **Gap B**:
- `00:00`, `01:00`, `04:59` → true; `05:00`, `12:00`, `20:00`, `23:59` → false. Cut-off from
  `requirements-initial.md` ("before 5:00 AM"); 5:00 itself is not after midnight.
`formatDayHeading(date)`:
- `2026-10-12` → "Mon, Oct 12"; `2028-02-29` → "Tue, Feb 29" (a real leap day; review #6). **Zone independence:** the
  same output with `process.env.TZ` set to `Pacific/Pago_Pago` (UTC−11) and to `Pacific/Kiritimati` (UTC+14). The
  western zone is the one that catches the trap named above — `new Date("2026-10-12")` is UTC midnight, which is the
  11th in Pago Pago; the eastern zone catches the mirror bug (building a local-time `Date` and reading it back in UTC)
  (review #5). Vitest's default `forks` pool makes a runtime `TZ` change take effect. Restore in `afterEach`: put the
  original value back, or `delete process.env.TZ` when there was none — assigning `undefined` sets the string
  `"undefined"`.
`formatShowTime(date, time)`:
- `20:00:00` → "8:00 PM"; `19:30:00` → "7:30 PM"; `01:00:00` on `2026-10-09` (a Friday) → "1:00 AM Sat"; `00:00:00` on
  a Friday → "12:00 AM Sat"; `05:00:00` → "5:00 AM" (no suffix); `null`/`undefined` → `null` (the block says "Time
  not listed"). Weekdays worked out from a calendar.
`formatClockTime(time)` (end times, per-act times): `00:30:00` → "12:30 AM", no suffix.
`nightSortKey(time)`: sorting `[20:00, 01:00, null, 18:00]` gives `18:00, 20:00, 01:00, null` — evening first,
after-midnight after it, untimed last (the API's own `_ordering` puts untimed last for the same reason).
`formatMonthLabel(year, month)`: `(2026, 10)` → "October 2026". Comment why it goes through `toPlainDate({ day: 1 })`:
`PlainYearMonth.toLocaleString("en-US", …)` **throws** ("cannot format PlainYearMonth with calendar iso8601 in locale
with calendar gregory") — checked.

### 2. `lib/calendar.test.ts` (new) — `groupCalendar({ start, end, shows, today })`
- **Every date, inclusive, in order** — **Gap C**: `lib/fixtures/shows.json` (start `2026-09-28`, end `2026-10-25`)
  gives 28 rows: 28 because the API's default window is today plus 27 days (`routers/shows.py`, `DEFAULT_WINDOW`).
  The first row is `2026-09-28`, the last `2026-10-25`, and `2026-10-04` (sample day 6, "deliberately empty") is
  present with no venues.
- Single-day range → one row. `2028-02-28`..`2028-03-01` → three rows including the 29th (leap year).
- **Venue columns** within a row are alphabetical by venue name (D1) and carry the venue's id.
- **Two shows at one venue on one date** form one column holding both, in night order: 22:00 before 01:00, untimed
  last (hand-built shows; and, after D5, the fixture's `2026-10-07` row has four venue columns with White Squirrel
  holding 18:00 then 22:00).
- A show whose date is outside `start`..`end` is ignored (the API never sends one; a comment says so rather than
  inventing a row).
- `today` inside the range marks exactly that row; `today` outside it, or `null`, marks none.
- No shows → every row present and empty (the page decides the empty state, not this function).

### 3. `lib/show-format.test.ts` (new)
`formatPrice`: `"18.00"` → "$18", `"8.50"` → "$8.50". String handling only — no `parseFloat` (`api-contract.md` §4).
`formatAdmission(show)`:
- `free_admission: true` → "Free". Advance and day → "$18 adv / $22 door". Day only → "$10" (an unlabelled price is
  stored as the day price, `requirements-initial.md` "Agent Extraction: Fields", so the block doesn't claim "door").
  Advance only → "$15 adv". **All three null → `null`, not "Free"** (`api-contract.md` §4: the case the contract
  calls out). `free_admission: false` with no prices → `null`.
`orderedLineup(lineup)`: by `sequence_number`; entries with a null number keep the API's order, after the numbered
ones (a stable sort).

### 4. `lib/calendar-href.test.ts` (new) and `params.test.ts` (unchanged)
- `withIds(filters, "venueIds", [3, 1, 3])` → `venueIds: [1, 3]`, other keys untouched (the combobox reports
  selection order, and `buildCalendarHref` expects canonical input).
- `monthOptions(months, current)` (in `lib/calendar.ts`, since it formats with Temporal): the fixture's months →
  `[{ value: "2026-09", label: "September 2026" }, { value: "2026-10", label: "October 2026" }]`; a `current` month
  that isn't offered (a hand-edited past month — B2 D2 allows it) is added so the select can show the truth; `null`
  adds nothing.
- `params.test.ts` stays green **unmodified** after `buildCalendarHref` and `CalendarFilters` move to
  `lib/calendar-href.ts` and are re-exported from `params.ts`. That is the check that the move broke nothing.

### 5. `lib/api.test.ts` (one test added)
`getCalendarMonths()` calls `/calendar/months` and returns `calendar-months.json` unchanged (same pattern as the
other getters).

### 6. Python (`apps/api/app/tests/`)
D5 appends sample rows. No new Python test: `test_routers.py` checks filtering relationally (venue 1 + venue 3 =
both), not by absolute counts, so it should pass unchanged — confirmed by running it, and any test that does pin a
count is updated with the new number worked out by hand. `make fixtures` then `make contract-check`.

### What is *not* covered, stated plainly
- Rendered output of `/`, the grid, the show block and `/day/[date]` (async Server Components): build, HTTP checks and
  Ari's browser check.
- The filter header (a Client Component; Gap D): `pnpm check-types`, the build, and Ari's browser check. Its component
  test is B5's ("the filter header" is the first item there).
- Responsive layout (Gap E): measured by me in headless Chrome at 1280/768/500px (Verification 6); 375px, touch
  scrolling and keyboard are Ari's browser check (Verification 7).

### Tests-first caveat
As in B2: the new test files import modules that don't exist, so stubs that export the functions and throw come
first, making the red state assertion failures rather than import errors.

## Implementation steps

Order: data and pure functions first (they unblock everything), then the components, then the page, then cleanup.

### Working protocol for [fill-in] steps
As in B2 and `AGENTS.md` "[fill-in] tasks": I write everything around each lesson (imports, types, signatures,
wiring, markup, tests — which stay red); the lines that carry the lesson become `TODO(Ari)` blocks with
**Lesson / Code / Check**; each placeholder throws `new Error("TODO(Ari)")`; then I stop and hand off with a
file:line list and the commands. "Implement B3" doesn't fill the blocks. **Handoff happens on an uncommitted tree**:
red tests keep `make check` red until the gaps are filled, so nothing is committed in that state.

### TODO(Ari) gaps

Five blocks across four [fill-in] items — at most two per item, inside `AGENTS.md`'s "1–3 spots" per task
(review #3): the Temporal item → A and B (with the show block re-marked [written], D6, its after-midnight rule is the
Temporal item's); the layout item → C; the filter-header item → D; the responsive item → E. A–C are one line each on
purpose: each is the line where a requirement (the metro's today, the 5 AM cut-off, the served range) turns into
Temporal code. If Ari wants fewer, A and B are the two to merge into one block.

**Fill order: A, B, C first** (pure, unit tested, independent of each other); then **E**, then **D**.
While A–C are open, `/` renders the error boundary (the grid calls them), so E's and D's browser checks need A–C
filled. D's and E's own checks are `pnpm check-types` plus the browser.

- **Gap A — `metroToday` in `lib/dates.ts`** (step 2; the build plan's Temporal item).
  *Lesson:* "today" is a question about a place. This code runs on the Next server, whose zone is UTC on Vercel, so
  any zone-less "now" is tomorrow from early evening Central time on. Ask for the date in the metro's IANA zone
  (`MetroSummary.timezone`, `requirements-initial.md` "Metro"). Show dates themselves need no zone (they are wall-clock
  `PlainDate`s); this is the one place the metro's zone is needed.
  *Code:* `return now.toZonedDateTimeISO(timeZone).toPlainDate();` — the signature is
  `metroToday(timeZone: string, now: Temporal.Instant = Temporal.Now.instant())`, injectable so tests can fix the
  clock.
  *Check:* `pnpm --filter calendar test dates` — the `2026-10-13T02:30:00Z` case. Likeliest mistakes:
  `Temporal.Now.plainDateISO()` with no zone argument (the server's zone; also ignores `now`, so every case fails), or
  `new Date().toISOString().slice(0, 10)` (UTC).
- **Gap B — `isAfterMidnight` in `lib/dates.ts`** (step 2; the show block's rule).
  *Lesson:* Ari's after-midnight rule (`requirements-initial.md`, "Show", October 11) as one comparison — and Temporal
  refuses `<`: its objects throw on `valueOf()` precisely so `a < b` can't silently compare strings or `NaN`. Ordering
  goes through `compare`. Both `formatShowTime` (the "Sat" suffix) and `nightSortKey` (after the evening's shows) call
  this, so the rule lives in one line.
  *Code:* `return Temporal.PlainTime.compare(time, NIGHT_CUTOFF) < 0;` with `NIGHT_CUTOFF = Temporal.PlainTime.from("05:00")`
  declared above it.
  *Check:* `pnpm --filter calendar test dates` — `04:59` true, `05:00` false; the `formatShowTime` and `nightSortKey`
  cases go green with it. Likeliest mistakes: `time < NIGHT_CUTOFF` (throws a TypeError naming `compare` — the test
  shows it), or `<= 0` (makes 5:00 AM "after midnight").
- **Gap C — the date loop in `groupCalendar`, `lib/calendar.ts`** (step 3; the layout item).
  *Lesson:* the calendar's rows come from the **range the server served**, not from the shows — that is how an empty
  day gets a row (D2), and why the page renders `start`/`end` from the response (`api-contract.md` §3). Walk it with
  Temporal: `add({ days: 1 })` handles month ends and leap days, `compare` handles the inclusive end.
  *Code:*
  `for (let d = start; Temporal.PlainDate.compare(d, end) <= 0; d = d.add({ days: 1 })) rows.push(emptyRow(d, today));`
  *Check:* `pnpm --filter calendar test calendar` — the 28-row fixture case and the leap-year range. Likeliest
  mistakes: `< 0` (drops the last day; the API's `end` is inclusive), `d <= end` (throws), or building rows from
  `shows.map(s => s.date)` (passes the venue tests, fails the empty-day one).
- **Gap D — navigating from the filter header, `app/_components/filter-header.tsx`** (step 6; the filter item).
  *Lesson:* the Client Component never holds the calendar's results. A selection changes the **URL**; the server page
  re-renders from `searchParams` and streams new props down. `router.push` runs inside a transition, so
  `useTransition`'s `isPending` says a navigation is in flight; `useOptimistic` shows the new selection immediately and
  falls back to the server's value when the navigation lands. `scroll: false` keeps the reader's place.
  *Code:*
  ```
  startTransition(() => {
    setOptimisticFilters(next);
    router.push(buildCalendarHref(next), { scroll: false });
  });
  ```
  *Check:* `pnpm check-types`, then in the browser: picking a venue sets the URL to `/?venue=N` (canonical: a second
  venue gives `/?venue=1&venue=3` whichever order they were picked), the grid updates, Back restores the previous
  filters. Likeliest mistakes: keeping the selection in `useState` and filtering client-side (works, until the URL is
  shared — the recipient sees an unfiltered calendar), or `router.push` without `scroll: false` (the page jumps to the
  top on every change).
- **Gap E — the date row's scroller, `app/_components/calendar-grid.tsx`** (step 7; the responsive item). *Rewritten
  after review #1, which measured the original lesson as wrong for this markup.*
  *Lesson:* the one thing nested scrolling gets wrong is **which element is the grid item**. A grid item's automatic
  minimum width is its content's min-content width — *unless the item is itself a scroll container*, whose automatic
  minimum is 0. So the element with `overflow-x-auto` must be the row's grid item (or flex item) directly. Wrap it in a
  plain `<div>` — to add a caption, say — and that wrapper's minimum becomes the full width of every venue column, the
  `1fr` track grows to fit it, and the whole page scrolls sideways instead of the row (the reviewer measured
  scrollWidth 2884 against clientWidth 1280). This applies from `md` up, where the row is a grid; below it the row is block flow and a wrapper is harmless
  (code review #3). The fixes for a wrapper are `min-w-0` on it or `minmax(0,1fr)` on the
  track. Then, for touch: `overscroll-x-contain` stops a swipe that reaches the row's end from chaining into the
  browser's back gesture, and scroll-snap keeps columns aligned after a flick.
  *Code:* the scroller, written as the `<li>`'s **direct** child after the date heading (the `<li>` is
  `grid gap-2 py-3 md:grid-cols-[9rem_1fr]`, written — plain `1fr` on purpose, so the experiment below shows the
  failure):
  `<div role="region" aria-label={…} tabIndex={0} className="flex snap-x snap-mandatory gap-3 overflow-x-auto overscroll-x-contain pb-2">`
  *Check:* in the browser at 1280px and at phone width,
  `document.documentElement.scrollWidth === document.documentElement.clientWidth` in the console is `true` **while**
  the 2026-10-07 row (four venues after D5; 9rem + 4 × 16rem is wider than `max-w-6xl`'s content box) scrolls
  sideways on its own. Then the experiment that makes the lesson observable: wrap the scroller in a bare `<div>`, see
  the check turn `false` and the page scroll sideways (run it at 768–1024px, where the page grows by ~460px; at
  1280px it is only 16px); add `min-w-0` to the wrapper and see it turn `true`; remove the
  wrapper. Likeliest mistake: the wrapper itself — or `overflow-x-auto` placed on a venue column's parent that isn't
  the grid item.

### 1. Sample data (written, Python) — D5
- Append the four 2026-10-07 rows to `_SHOW_ROWS` in `apps/api/app/sample_data.py` (at the end, so ids 1–21 are
  stable), with a comment saying which layout case each exercises.
- `REQUIRE_DB=1 uv run pytest` (or without the DB suite if Docker is down, saying so); `make fixtures`; `make types`
  (should be a no-op); `make contract-check`. Update the "21 shows" in `api-contract.md` §8 and `alpha-build-plan.md`
  Track 0 to 25 (review #8; the build plan's line is a ticked historical item, so it gets "(25 since B3)" appended
  rather than rewritten).
- Note for A1b (not fixed here): `routers/shows.py` `_ordering` sorts a 01:00 show *first* in its day. B3 doesn't rely
  on the API's order within a day (it groups and re-sorts), but A1b's query, and A5, should order by night. Recorded in
  "Follow-ups" below.

### 2. Temporal helpers (fill-in: Gaps A, B) — `lib/dates.ts`
- Tests first (§1). Explicit `import { Temporal } from "@js-temporal/polyfill"` (Node has no global Temporal).
- `metroToday` (Gap A), `isAfterMidnight` (Gap B); written around them: `metroTodayOrNull` (catches only
  `RangeError`), `formatDayHeading`, `formatShowTime`,
  `formatClockTime`, `nightSortKey`, `formatMonthLabel`. All take the API's strings or Temporal values; none touch
  `Date`.
- Module docstring: the "wall-clock needs no zone; today does" explanation from Context, and that this module is
  **server-only in practice** — it pulls in the ~129 KB (36 KB gzipped) polyfill, so Client Components must not import
  it (step 5). Not marked `import "server-only"`: nothing secret is in it, and the tests import it directly; the
  bundle check in Verification 3 is the guard instead.

### 3. Grouping (fill-in: Gap C) — `lib/calendar.ts`
- Tests first (§2). Types: `CalendarRow = { date: string; isToday: boolean; venues: VenueColumn[] }`,
  `VenueColumn = { venue: VenueSummary; shows: ShowSummary[] }`. Dates stay ISO strings in the output (what the page
  renders and links with); Temporal is used inside.
- `groupCalendar` — the date loop is Gap C; written around it: bucket shows by date (ignoring out-of-range), group by
  venue id, sort columns by venue name (`localeCompare`), sort each column's shows by `nightSortKey`.
- `monthOptions(months, current)` (§4).

### 4. Show formatting and the show block (written — D6) — `lib/show-format.ts`, `app/_components/show-block.tsx`
- Tests first (§3) for `formatPrice`, `formatAdmission`, `orderedLineup`.
- `ShowBlock({ show, withVenue })` — a Server Component. Contents, focus on venue and artist names
  (`requirements-initial.md`): start time via `formatShowTime` ("Time not listed" when null), end time via
  `formatClockTime` when present ("8:00 PM – 12:30 AM"); the venue name as a `<Link>` to `/venue/[id]` **only when
  `withVenue`** (in the grid, the column header already names the venue; on `/day/[date]` the block stands alone);
  the lineup from `orderedLineup`, each artist a `<Link>` to `/artist/[id]`, with a per-act time when the API has one;
  admission from `formatAdmission`, rendering nothing when it returns `null`.
- **No poster image.** `image_url` hosts are arbitrary venue sites: `next/image` would need an open-ended
  `images.remotePatterns`, and a plain `<img>` trips `@next/next/no-img-element` under `--max-warnings 0`. The block's
  focus is names; the poster belongs on B4's show page.
- **Not a link to `/show/[id]`**: that page is B4 (its JSON-LD item), and the block already contains venue and artist
  links, which can't nest inside another link.

### 5. Filter state for a Client Component (written) — `lib/calendar-href.ts`, `lib/api.ts`
- Move `CalendarFilters` and `buildCalendarHref` out of `lib/params.ts` into a new **Temporal-free**
  `lib/calendar-href.ts`, and re-export them from `params.ts` so existing imports and `params.test.ts` are untouched.
  Why: `params.ts` imports the polyfill at module scope (for `parseDateParam` and the month range), and the filter
  header — a Client Component — needs `buildCalendarHref`. Importing it from `params.ts` would ship ~36 KB gzipped of
  Temporal to every visitor for a function that only joins strings. (B2's `params.ts` docstring anticipated the client
  caller: "B3's filter header will build hrefs from a Client Component".)
- Add `withIds` (§4) to `lib/calendar-href.ts`.
- `lib/api.ts`: add `getCalendarMonths()` to `ApiClient`, `createApiClient` and the exports (no `cache()` — one call
  per page). Test first (§5). Update the docstring's "six getters".

### 6. The filter header (fill-in: Gap D) — `packages/ui` primitives, `app/_components/filter-header.tsx`
- **Primitives from the shadcn CLI**, into `packages/ui` (`apps/calendar/AGENTS.md`: "Shared primitives go in
  `packages/ui`"): `combobox` (multi-select with chips and type-to-filter — Base UI ships `Combobox`, present in
  `node_modules/@base-ui/react/combobox`) and `select` for the month. Run `pnpm dlx shadcn@latest add combobox select`
  from `apps/calendar` (its `components.json` maps `ui` to `@repo/ui/components`). **Verify at the start of this step**
  that the `base-nova` registry has a `combobox` with multiple selection; if it doesn't, stop and record the
  alternative in the Implementation log rather than hand-rolling one (style guide: don't hand-roll shadcn primitives).
  If the CLI writes `.ts` files into a new `packages/ui/src` folder (e.g. `hooks/`), add an `exports` entry for it
  (`notes.md`, "`@repo/ui` only resolved `.tsx` files").
- **What the CLI will actually add** (review #2, from `shadcn view` against the live registry): `combobox` depends on
  `button` and `input-group`, and `input-group` on `button`, `input` and `textarea` — so expect `input.tsx`,
  `textarea.tsx` and `input-group.tsx` in `packages/ui/src/components/` too. **Do not let it overwrite
  `button.tsx`**: B1 settled that file; if the CLI offers to, decline, then diff the registry version against ours and
  record any difference in the Implementation log rather than taking it by habit. The generated code imports
  `lucide-react`, which `apps/calendar` has and `packages/ui` doesn't (pnpm doesn't hoist across workspaces), so add
  `lucide-react` to `packages/ui/package.json` `dependencies` at the same version range as the app's, and confirm with
  `pnpm --filter @repo/ui check-types` before importing anything from the app.
- **Tailwind `@source`:** this is the first time the calendar imports `@repo/ui`, so `app/globals.css` needs an
  `@source` line or the primitives render unstyled (`notes.md`). **The path recorded in `notes.md` and
  `apps/calendar/AGENTS.md` (`"../../packages/ui/src"`) looks wrong:** `@source` resolves relative to the CSS file,
  and from `apps/calendar/app/` that points at `apps/packages/ui/src`. The right path should be
  `"../../../packages/ui/src"`. Verify by building and grepping the CSS for a class only a `packages/ui` component
  uses, then correct both docs.
- `FilterHeader` (`"use client"`): props are `filters: CalendarFilters`, `venues` and `artists` as `{ id, name }[]`,
  `months` as `{ value, label }[]` — narrow, serialisable, built on the server (labels formatted there, so the client
  needs no Temporal). No `useSearchParams` (it would need its own `<Suspense>`; the server already parsed the URL and
  passes it down). Venue combobox, artist combobox, month select (first option "Next four weeks" = no month), and a
  "Clear filters" `<Link href="/">` when anything is set. `useOptimistic(filters)` + `useTransition`; each change
  builds `next` with `withIds` (or the month) and calls Gap D. While pending, `aria-busy` on the header and a quiet
  "Updating…".
- Imports `buildCalendarHref`/`withIds`/`CalendarFilters` from `@/lib/calendar-href` — **never** `@/lib/params` or
  `@/lib/dates` (comment says why).

### 7. The calendar grid (fill-in: Gap E) — `app/_components/calendar-grid.tsx`
- `CalendarGrid({ rows })` — a Server Component rendering `groupCalendar`'s output as an `<ol>` of dates:
  - Date heading: `formatDayHeading`, a `<Link>` to `/day/[date]` (requirements: "Clicking on the day will switch to
    the day view"), a "Today" label when `isToday`. On phones it sits above the row and is `sticky top-0` with a
    background so it stays visible while its row is on screen; from `md` up it is the row's first grid column.
  - The row `<li>` is `grid gap-2 py-3 md:grid-cols-[9rem_1fr]` with exactly two children, the heading and the
    scroller. The scroller (Gap E) is the `<li>`'s **direct** grid item — that is what lets plain `1fr` work
    (review #1), and a comment above it says so, so nobody wraps it later. It has `role="region"`, an `aria-label` naming the
    date, and `tabIndex={0}` so keyboard users can scroll it (axe's "scrollable region must have keyboard access").
  - Venue column: `w-[min(80vw,16rem)] shrink-0 snap-start`; header is the venue name as a `<Link>` to `/venue/[id]`;
    then a `ShowBlock` per show (`withVenue={false}`), all of them (D7). At phone width the 80vw column lets the next
    one peek in, which is the visual cue that the row scrolls.
  - Empty date (D2): one muted line, "Nothing listed".
- Why a Server Component: nothing in it is interactive (horizontal scroll is the browser's), so it ships no JS, and the
  Temporal formatting stays on the server.

### 8. The home page (written) — `app/page.tsx`
- `Home` keeps `parseCalendarFilters(await searchParams)` and renders the heading and a `<Suspense
  fallback={<CalendarSkeleton />}>` around an async `CalendarBody` (D4). The comment says why the boundary is here and
  not in a root `loading.tsx` (soft 404s), and that it changes `/`'s outage behaviour to a 200.
- `CalendarBody`: one `Promise.all` over `getShows(toShowsQuery(filters))`, `getVenues()`, `getArtists()`,
  `getCalendarMonths()` and `getMetroOrNull()` (shared with the layout's metro call through `cache()`). Then:
  `today = metro ? metroTodayOrNull(metro.timezone)?.toString() ?? null : null` (no "Today" label if the metro is
  unavailable or its zone is not a valid IANA id, rather than guessing a zone or failing the page — review #9;
  `metroTodayOrNull` logs the bad zone with `console.error`); `<FilterHeader …>`; the served range ("Mon, Sep 28 – Sun, Oct 25", formatted, still the
  server's numbers); then either the empty state or `<CalendarGrid rows={groupCalendar(...)} />`.
- **Empty state** (D6, written): no shows **and** a filter set → "No matches found" + `<Link href="/">Reset
  filters</Link>`; no shows and no filter → "No shows listed for these dates" (nothing to reset).
- `CalendarSkeleton`: a handful of grey rows in the grid's shape (`animate-pulse`), no data.
- No `key` on the `<Suspense>`: on a filter change the transition keeps the current calendar on screen (with the
  header's pending state) instead of flashing the skeleton.
- Delete the demo venue links and the `PlainShowList` import.

### 9. `/day/[date]` (written)
Replace `PlainShowList` with a list of `ShowBlock`s (`withVenue`), each heading formatted with `formatDayHeading`.
Order: as the API returns them for now — the three sort modes are B4. Delete `app/_components/plain-show-list.tsx`.

### 10. Docs and bookkeeping (written)
- `alpha-build-plan.md` B3: tick the boxes, apply departures 1–4, and point at this file.
- `apps/calendar/AGENTS.md`: the `@source` path (once verified), the "Temporal stays out of Client Components" rule
  and `lib/calendar-href.ts`, the filter header's URL-only state, D4's streaming boundary.
- `docs/dev/notes.md`: `PlainYearMonth.toLocaleString` throws in `en-US`; the `@source` path correction (fold into the
  existing entry); anything else that surprises.
- `globals.css`: B1's comment mentions "B3's sticky date and venue headers" — update it to what B3 built (D1).
- `api-contract.md` §8 and `alpha-build-plan.md` Track 0: the show count (D5, step 1).

## Critical files

- New: `apps/calendar/lib/{dates,calendar,show-format,calendar-href}.ts` + `.test.ts` for each;
  `apps/calendar/app/_components/{calendar-grid,show-block,filter-header}.tsx`;
  `packages/ui/src/components/{combobox,select,input-group,input,textarea}.tsx` (generated by the shadcn CLI —
  review #2; `button.tsx` is **not** overwritten)
- Modified: `apps/calendar/app/page.tsx`, `apps/calendar/app/day/[date]/page.tsx`, `apps/calendar/app/globals.css`,
  `apps/calendar/lib/{params,api}.ts`, `apps/calendar/lib/api.test.ts`, `apps/api/app/sample_data.py`,
  `apps/calendar/lib/fixtures/*.json` (**generated** — `make fixtures`, never by hand), `packages/ui/package.json`
  (`lucide-react`, plus any new `exports` entry), `pnpm-lock.yaml`, docs listed in step 10
- Deleted: `apps/calendar/app/_components/plain-show-list.tsx`
- Reused as-is: `lib/metro.ts` (`getMetroOrNull`), `lib/types.ts`, `app/layout.tsx`, `app/error.tsx`,
  `app/not-found.tsx`

## Verification

1. **Tests first.** New test files and stubs written, run, and confirmed red for the right reason (assertions, not
   imports) before implementing.
2. **`make check`** green once the gaps are filled (ruff, mypy, eslint, `next typegen` + tsc, pytest, Vitest,
   contract-check). At handoff it is red only on the gap tests (A–C) — the log lists exactly which. As in B2, before
   handing off I apply the five `Code:` snippets in a scratch copy, run everything, and restore the scaffold
   byte-for-byte, so the snippets are known to fit. The layout measurements in 6 are taken in that same
   snippets-applied copy (with A–C open, `/` renders the error boundary).
3. **Build with the API unreachable** (`API_BASE_URL=http://127.0.0.1:9 pnpm build`): succeeds, every data route and
   `/_not-found` still `ƒ`. **Plus the bundle check:** `grep -rl "Do not use built-in arithmetic operators with
   Temporal" .next/static` finds nothing — the polyfill (whose error message that is) is not in any client chunk. And
   the built CSS contains a class only a `packages/ui` primitive uses (the `@source` check, step 6).
4. **HTTP matrix** against `next start` with the API up:
   `/` [200; 28 date rows; "Today" on the metro's current date if it falls in 2026-09-28..2026-10-25, which on
   2026-10-12 it does], `/?venue=1` [200; fewer shows; all 28 rows], `/?venue=9999` [200; "No matches found" and a
   reset link], `/?month=2026-10` [200; 31 rows], `/?month=2026-02` [200; "No matches found" — a month filter with no shows is a filtered empty result, so no grid],
   `/day/2026-10-07` [200; five show blocks after D5], and B2's 404 rows re-checked because `/` now streams
   (B2 review #11): `/venue/abc`, `/venue/9999`, `/day/garbage`, `/nope` [all still 404].
5. **API down at runtime** (D4): `/` answers 200 with header, footer and the skeleton in the HTML, and no `ApiError`
   text, URL or stack in the body; detail routes keep B2's bare 500; `/health` 200. Recorded as measured.
6. **Layout measured by me, before handoff** (review #10): headless Chrome (`/Applications/Google Chrome.app`,
   `--headless=new`) against `next start` with the snippets applied, recording for `/` at 1280px, 768px and 500px
   (headless Chrome's minimum window; 375px is left to Ari's devtools) the page's `scrollWidth`/`clientWidth` and the
   2026-10-07 scroller's `scrollWidth`/`clientWidth`. Expected: page equal at every width, scroller wider than its box
   at 768 and 500 (and at 1280, per the Gap E arithmetic). I also run Gap E's wrapper experiment once and record both
   numbers, so the lesson Ari is about to see is known to reproduce in the real page, not only in the reviewer's
   plain-CSS model. The numbers go in the Implementation log.
7. **Browser check by Ari** — what needs a person:
   - At 375px (devtools): the same `scrollWidth === clientWidth` check; the next column peeks in; the date heading
     stays visible while scrolling down through a row.
   - Touch (a phone, or devtools touch emulation): a sideways swipe in a row scrolls the row, a vertical swipe scrolls
     the page, and a swipe past a row's end doesn't trigger Back.
   - Keyboard: Tab reaches a row; arrow keys scroll it.
   - Filters (Gap D): type-to-filter narrows the venue and artist lists; picking venues gives the canonical URL;
     Back undoes a change; the month select switches to the whole month and back to "Next four weeks"; "Clear filters"
     and the empty state's reset link both return to `/`; a shared filtered URL opened in a new window shows the same
     calendar.
   - After midnight: on 2026-10-07, The Midway Saloon's block reads "1:00 AM Thu", and White Squirrel's column shows
     18:00 then 22:00.

## Not doing in B3

Day view sort modes, the venue page's embedded calendar, `/venues`/`/artists` polish, `/show/[id]`, posters, JSON-LD
(B4); component tests, Testing Library, jsdom (B5); Playwright; the past-dates toggle, genre filter, text search
(requirements: "later"); caching or loading the whole calendar client-side (`arch-initial.md` §11); a root
`loading.tsx` (D4); `useSearchParams`; dark-mode work; any change to the API's response shapes.

## Follow-ups for other milestones

- **A1b / A5:** the API orders a day's shows by clock time, so a 01:00 show sorts first (`routers/shows.py`
  `_ordering`). B3 re-sorts by night and doesn't depend on it, but the query should order by the 5:00 AM cut-off too
  (and B4's day view "by time" sort mode will need the same `nightSortKey`).
- **B4:** reuse `CalendarGrid` for the venue page's embedded calendar, `ShowBlock` for the artist page's list, and
  `nightSortKey` for the day view's "by venue by time" mode.
- **B5:** the filter header is the first component test target.

## Plan review

### Round 1 — Claude Sonnet 5.5, October 12, 2026

**Scope:** the whole plan, before any B3 code exists. **Read:** `AGENTS.md` ("[fill-in] tasks", "Implementation plans"),
`docs/references/nextjs-style-guide.md` (Anti-patterns table included), `apps/calendar/AGENTS.md`, `alpha-build-plan.md` §6 B3,
`requirements-initial.md` (Calendar, Global Requirements, "Times after midnight"), `notes.md` (the `@source` entry), and
the code the plan builds on: `app/page.tsx`, `app/layout.tsx`, `app/error.tsx`, `app/day/[date]/page.tsx`,
`lib/{params,api,metro,types}.ts`, `packages/ui` (`package.json`, `components.json`, `button.tsx`),
`apps/api/app/{sample_data.py,routers/shows.py,routers/calendar.py,tests/test_routers.py}`, the generated fixtures.

**How it was checked.** No `git worktree` was needed: every experiment ran outside the repo, in the session scratchpad
(throwaway HTML files and one Node script that imports the repo's installed `@js-temporal/polyfill`), and nothing in the
repo was touched. Experiments: (1) Temporal under `TZ=Pacific/Kiritimati` / `Pacific/Pago_Pago`, the Chicago DST edge, a
`Pacific/Auckland` "today", `PlainYearMonth.toLocaleString`, weekday arithmetic; (2) the Gap E layout reproduced as plain
CSS in headless Google Chrome (1280 and 500 px windows, `document.documentElement.scrollWidth` vs `clientWidth`) with
10 venue columns, comparing `1fr` against `minmax(0,1fr)` with the scroller as the grid item and with a wrapper `<div>`
around it; (3) `shadcn view combobox select input-group` against the live `base-nova` registry; (4) path arithmetic for
the `@source` claim; (5) a read of `sample_data.py` and `test_routers.py` for D5. I did not run `make check` (no code to
check) or a Next build.

**Confirmed correct, so the author need not re-verify:** the Temporal claims in the "metro's timezone" section (wall-clock
`PlainDate` formatting is zone-independent; `Instant.toZonedDateTimeISO("America/Chicago")` gives the 12th for
`2026-10-13T02:30:00Z`; Auckland gives the 13th; `PlainYearMonth.toLocaleString("en-US", …)` throws as stated); the
Temporal-throws-on-`<` message ("Do not use built-in arithmetic operators with Temporal objects. When comparing, use …")
is in the installed polyfill, so the bundle-check grep string is real; all weekdays and counts in the plan (Oct 12 Monday,
Oct 9 Friday, Oct 7 Wednesday so "1:00 AM Thu", 28 rows for Sep 28 to Oct 25, 31 for October, five blocks on Oct 7 after
D5); `combobox` and `select` exist in the `base-nova` registry (the combobox is Base UI with chips); the `@source` path
in `notes.md` and `apps/calendar/AGENTS.md` is wrong (`../../packages/ui/src` from `apps/calendar/app/` does not exist,
`../../../packages/ui/src` does); the sample-data facts in D5 (Terminal Bar at 21:00 on offset 9, day offset 6 empty, no
two shows at one venue on one date, `_ordering` sorts a 01:00 show first); `test_routers.py` asserts relationally, so
appended rows should not break it; the root layout already survives an API outage through `getMetroOrNull`, so D4's
"200 with the shell" claim is plausible.

**Counts:** 0 blocker, 2 should-fix, 8 nit. **Verdict: proceed after fixes.** The structure, the test approach (pure
functions first, no unit tests for async Server Components, expected values hand-derived) and the decision list are sound.
The two should-fix items are Gap E teaching something the experiment contradicts, and the shadcn step underestimating what
the CLI will add.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **Gap E's lesson and its "likeliest mistake" are wrong for the markup the plan itself describes.** The gap says a `1fr` track "has a minimum of its content's min-content width, so a day with many venues widens the whole page", and that `md:grid-cols-[9rem_1fr]` makes the console check return `false` at 1280px. That is only true when the scroller is *wrapped* in another element. In step 7 the scroller is the row `<li>`'s direct grid child, and a scroll container's automatic minimum size is 0, so `1fr` is fine. | CONFIRMED in headless Chrome, 10 venue columns of `min(80vw,16rem)`, `max-w-6xl` container. Scroller as the direct grid item: `grid-template-columns: 9rem 1fr` gives `1280/1280` (scrollWidth/clientWidth, no page overflow), `9rem minmax(0,1fr)` gives `1280/1280`. Scroller wrapped in a plain `<div>` that is the grid item: `9rem 1fr` gives `2884/1280` (page blows out), `9rem minmax(0,1fr)` gives `1280/1280`. Phone (500px, single implicit column): scroller direct `500/500`, wrapped `2684/500`. | Ari types `minmax(0,1fr)`, runs the check, gets `true`, and has learned a false cause. The named mistake (`1fr`) also *passes* the check, so the gap's Check cannot go red for it; and the gap lives in class strings, which `AGENTS.md` lists as a poor place for a gap unless the concept really is in them. The real, demonstrable lesson is: the element that scrolls must be the grid/flex item itself (or the wrapper needs `min-w-0` / `minmax(0,1fr)`), because a wrapper's min-content includes its scrolling child's full width. | **Fixed.** Accepted on the reviewer's measurement (I didn't re-measure; Verification 6 now reproduces it in the real page before handoff). Gap E rewritten: the lesson is that the scroller must be the grid item itself (a scroll container's automatic minimum is 0; a wrapper's is its content's min-content); *Code* is the scroller as the `<li>`'s direct child; the written `<li>` keeps plain `1fr` on purpose; *Check* adds the wrapper experiment (wrap → `false`, `min-w-0` → `true`, unwrap). Step 7 says the scroller is the direct grid item, with a comment so nobody wraps it |
| 2 | should-fix | **Step 6 underestimates what `shadcn add combobox select` writes.** The plan expects `combobox.tsx` and `select.tsx` "plus whatever it adds" and only flags a possible `hooks/` folder. The registry says `combobox` has `registryDependencies: ["button", "input-group"]` and `input-group` pulls `["button", "input", "textarea"]`. The generated code also uses `lucide-react` (`IconPlaceholder` is rewritten to lucide imports for `iconLibrary: "lucide"`), which is a dependency of `apps/calendar` but **not** of `packages/ui` (`packages/ui/package.json` has no `lucide-react`). | CONFIRMED: `shadcn view combobox select input-group` output (registryDependencies as above); `grep lucide` finds it only in `apps/calendar/package.json:20`. The overwrite of an existing `button.tsx` is PLAUSIBLE (the CLI normally prompts). | (a) The CLI may offer to overwrite the existing `packages/ui/src/components/button.tsx`, which B1 already settled; accepting by habit changes a file B1 reviewed. (b) Four primitives (`button`, `input`, `textarea`, `input-group`) land in the diff, which is more than the Critical files list and the Implementation log scope will say. (c) If the CLI installs `lucide-react` into the wrong workspace, or not at all, `@repo/ui/components/combobox` fails to resolve from `packages/ui/src` (pnpm does not hoist across workspaces) and the failure shows up only at `pnpm check-types` or `next build`. | **Fixed.** Step 6 now lists what the CLI adds (`input-group`, `input`, `textarea` besides `combobox`/`select`), says to decline any overwrite of B1's `button.tsx` and diff it instead, and adds `lucide-react` to `packages/ui` dependencies, checked with `pnpm --filter @repo/ui check-types`. Critical files updated (primitives, `packages/ui/package.json`, `pnpm-lock.yaml`) |
| 3 | nit | **Five `TODO(Ari)` blocks exceed `AGENTS.md`'s "1-3 spots", and three are one-liners.** A (`toZonedDateTimeISO`), B (`compare(...) < 0`) and C (a `for` loop) are each a single line; B's lesson ("Temporal refuses `<`") is real but small, and C's real lesson (rows come from the served range, not the shows) is a design point the test already pins. Combined with finding 1, the two items the build plan calls the hard part (the layout, responsiveness) have the thinnest gap. | `AGENTS.md` "[fill-in] tasks" step 2 and "Picking the gaps". | Nothing breaks, but the budget is spent on small Temporal one-liners while the layout's actual structural decision (scroller is the grid item; sticky heading as a sibling) is written by the author. Ari's call: either accept five, or merge A+B into one "Temporal for the two time rules" block and put the structural lesson of finding 1 into Gap E. | **Rejected** (merging), **documented** (the count). `AGENTS.md`'s 1–3 is per task, and the five gaps map to four [fill-in] items with at most two each; that mapping is now stated at the top of the gaps section. The one-liners are the lines where a requirement becomes Temporal code, which is the lesson. The structural lesson the reviewer asked for is now Gap E's (#1). Flagged to Ari: A and B are the pair to merge if Ari wants fewer |
| 4 | nit | **The DST test case does not test what the plan says.** "`2026-11-01T06:30:00Z` → `2026-11-01` (00:30 CST, just after the fall-back change)". The US fall-back is 07:00Z on 2026-11-01, so 06:30Z is still **01:30 CDT**. | CONFIRMED: `Instant.from("2026-11-01T06:30:00Z").toZonedDateTimeISO("America/Chicago")` is `2026-11-01T01:30:00-05:00`. | The test passes but exercises no DST edge, and its comment would be false. A case that does discriminate: `2026-11-02T05:30:00Z` is `2026-11-01T23:30:00-06:00`, so `metroToday` must give `2026-11-01` where UTC says the 2nd. | **Fixed.** The DST case is now `2026-11-02T05:30:00Z` → `2026-11-01` (23:30 CST, offset −6), with the reason. Arithmetic re-done by hand: fall-back is 07:00Z on Nov 1, so 05:30Z on Nov 2 is 23:30 at −6 |
| 5 | nit | **Zone-independence test: one of the two zones cannot catch the trap named, and the restore is easy to get wrong.** The plan says the Kiritimati and Pago_Pago runs pin the property "so a later switch to `new Date(...)` fails here". `new Date("2026-10-12")` is UTC midnight, which is still Oct 12 east of UTC; only the western zone fails. Separately, "restored after" invites `process.env.TZ = original` where `original` is `undefined`, and Node coerces that to the string `"undefined"`. | CONFIRMED: a `Date`-based formatter prints "Mon, Oct 12" under Kiritimati and "Sun, Oct 11" under Pago_Pago; the Temporal formatter prints "Mon, Oct 12" under both. Vitest 5's default pool is `forks` (child processes), so changing `TZ` at runtime takes effect there. | Kiritimati would catch a different bug (local-time construction then UTC output) and is worth keeping, but the plan's stated reason is only true of Pago_Pago, so the comment should say so. A bad restore leaks an invalid TZ into later tests in the file. Use `delete process.env.TZ` when there was no original. | **Fixed.** Test §1 now says Pago Pago (west) catches `new Date("YYYY-MM-DD")` and Kiritimati (east) the mirror bug, notes the `forks` pool, and requires restoring with the original value or `delete process.env.TZ` |
| 6 | nit | **`formatDayHeading` test input `2026-02-29` is not a date.** "`2026-02-29`-style leap date -> its weekday". 2026 is not a leap year and `Temporal.PlainDate.from("2026-02-29")` throws (the repo's own `parseDateParam` relies on that). The `groupCalendar` section correctly uses 2028. | `params.ts` `parseDateParam` docstring ("Temporal itself … throws on impossible dates"); calendar arithmetic. | A test written literally from the plan throws at construction instead of testing anything. Use `2028-02-29` (a Tuesday). | **Fixed.** `2028-02-29` → "Tue, Feb 29" (checked: 2028-02-29 is a Tuesday) |
| 7 | nit | **D5's rows are specified without lineups, prices or flags.** `_SHOW_ROWS` tuples need a lineup (`_lineup(...)` of existing artist names, which raises `KeyError` on an unknown name) and the price/free/image columns. Which artists are used matters: reusing an artist already at another venue that night would create an unrealistic double-booking, and the artist filter (Gap D check) benefits from at least one new row having an artist who appears elsewhere. | `sample_data.py` `_lineup`, `_SHOW_ROWS` tuple shape. | Not a defect, just an under-specified step that the author will fill ad hoc. Say which artists and which admission cases (e.g. one new row with null prices, since "not stated" rendering is only covered by that today) so the fixture choices are deliberate and the `formatAdmission` cases appear in real data. | **Fixed.** D5 now has a table giving each new row's venue, times, lineup, prices/free and the case it exercises; no artist on The Terminal Bar's bill that night is reused; one row has all-null admission, one is free, one has per-act times and an end after midnight, and Charlie Parr appears at a second venue |
| 8 | nit | **Doc bookkeeping list misses a second "21 shows".** Step 10 updates `api-contract.md` §8 only. `alpha-build-plan.md:117` (the A1/Track 0 fixture checkbox) also says "21 shows over four weeks", and `calendar-months.json` changes too (October 18 -> 22), which `docs/dev/b2-…` verification notes do not depend on but any doc quoting it will. | CONFIRMED by grep: `docs/dev/alpha-build-plan.md:117`, `docs/dev/api-contract.md:151`. | A stale count in the build plan, which is the doc `AGENTS.md` points agents at. It is a historical checkbox, so either leave it with a "(25 after B3)" note or edit it; decide rather than miss it. | **Fixed.** Steps 1 and 10 and D5 update both counts: `api-contract.md` §8, and `alpha-build-plan.md` Track 0 gets "(25 since B3)" appended to its ticked historical line rather than a rewrite. D5 also notes `calendar-months.json` (October 18 → 22) |
| 9 | nit | **`metroToday` can throw on a bad zone and take the whole calendar down.** Step 8 does `metro ? metroToday(metro.timezone)...`. `getMetroOrNull` only guards the fetch; `toZonedDateTimeISO` throws `RangeError` for an unknown IANA id (a typo in the `metro` row, or a polyfill/ICU gap). | PLAUSIBLE (not run against a bad zone; the API's `timezone` is free text in the schema). | The "Today" label is cosmetic, but a throw inside `CalendarBody` is a full error page (and, after D4, a 200 with the error boundary). Cheap fix: catch `RangeError` in the page's one call site and treat it like `metro === null` (no Today), with a `console.error`. | **Fixed.** New written `metroTodayOrNull` in `lib/dates.ts` (catches only `RangeError`, logs, returns `null`), tested with `"Not/A_Zone"`; step 8 uses it, so a bad zone costs the "Today" label, not the page. Gap A stays the pure `metroToday` |
| 10 | nit | **Verification relies on Ari for numbers the author can measure.** The plan says "I have no browser". A headless Chrome exists at `/Applications/Google Chrome.app` and ran the layout experiment above with `--headless=new --dump-dom` and an inline script that writes `scrollWidth/clientWidth` into the DOM. | CONFIRMED (that is how finding 1 was measured). | Gap E's check, and the 375/768/1280 `scrollWidth === clientWidth` assertions in Verification 6, could be produced as recorded numbers before handoff against `next start`, leaving Ari the touch and keyboard checks that really need a person. Chrome's minimum headless window is about 500 px, so 375 needs devtools emulation or a `meta viewport` page. | **Fixed.** New Verification 6: I measure page and 2026-10-07 scroller `scrollWidth`/`clientWidth` in headless Chrome against `next start` (snippets applied) at 1280/768/500px, and run Gap E's wrapper experiment once, recording the numbers in the Implementation log. Ari's check (now 7) keeps 375px, touch, keyboard and the filter flows |

**Resolutions** (Claude Opus 5.5, October 12, 2026): 9 fixed in the plan above, 1 rejected. I re-did the arithmetic
for #4 and #6 by hand and confirmed #8 with `grep`. #1 and #2 are accepted on the reviewer's measurements and
`shadcn view` output; Verification 6 and step 6 re-check both during implementation.

Rejected: #3 (merging gaps) — five gaps over four [fill-in] items is within `AGENTS.md`'s per-task 1–3; the mapping is
now written down, and merging A and B is offered to Ari as an option.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 12, 2026

**Scope.** The uncommitted working tree on top of `b445e6f` (A2, committed by Ari; it also renamed `v1-build-plan.md`
to `alpha-build-plan.md`, which the plan's references already reflect). Review with `git status` / `git diff` plus the
untracked files. Nothing is committed (no request, and the gap tests are red). `plain-show-list.tsx` is staged as
deleted (`git rm`); that is the only staged change.
- Python: `apps/api/app/sample_data.py` (four rows appended, D5).
- Generated (`make fixtures`; `make types` was a no-op): `apps/calendar/lib/fixtures/{shows,calendar-months}.json`.
- Frontend lib (new): `lib/{dates,calendar,show-format,calendar-href,todo}.ts` and `.test.ts` for the first four.
  Modified: `lib/params.ts` (`CalendarFilters` and `buildCalendarHref` moved out, re-exported), `lib/api.ts` +
  `lib/api.test.ts` (`getCalendarMonths`).
- Frontend app (new): `app/_components/{calendar-grid,calendar-skeleton,filter-header,show-block}.tsx`.
  Modified: `app/page.tsx`, `app/day/[date]/page.tsx`, `app/globals.css`. Deleted: `app/_components/plain-show-list.tsx`.
- `packages/ui` (generated by the shadcn CLI, then fixed): `src/components/{combobox,select,input-group,input,textarea}.tsx`;
  `package.json` (+`lucide-react`), `pnpm-lock.yaml`.
- Docs: `docs/dev/{alpha-build-plan,api-contract,notes}.md`, `apps/calendar/AGENTS.md`, and this file.
- Not mine, present in the tree: `docs/dev/implementations/a3-validation-and-retry.md` (untracked, another plan).

**Departures from the plan.**
1. **The row `<li>` is block flow below `md` and a grid from `md` up** (`md:grid md:grid-cols-[9rem_1fr]`), not a grid at
   every width. A `sticky` heading only sticks within its own grid area, which in a one-column grid is its own row, so
   the plan's "heading stays visible on phones" could not work with a grid there (`notes.md`). Gap E's lesson is unchanged
   and the wrapper experiment is run at 1280px, where the grid applies.
2. **Gap E's scaffold** is the finished element with only the scroll classes missing (`className="flex gap-3"`), and its
   `Code:` is that one `className`. The plan said the `<li>` classes were "written, plain `1fr`"; they are.
3. **`lib/todo.ts` (new)**: a `todo(...inputs): never` helper every scaffolded gap calls, in place of B2's per-file
   `todo<T>()` copies. The helper's file is to be deleted when the last gap is filled (its docstring says so).
4. **Gap C's loop sits in `groupCalendar` itself** (as planned), with an `emptyRow` closure written around it.
5. **`/day/[date]` re-sorts by `nightSortKey`** and formats its heading with the year ("Mon, Oct 12, 2026"). The plan said
   "as the API returns them"; but that puts a 1:00 AM show first in its day, which is exactly the wrong answer for the new
   sample row. Sort is stable, so ties keep the API's order. B4's sort modes replace it.
6. **`formatClockTime` is hand-built, not `Intl`.** I first wrote that ICU versions differ on U+202F; I then checked: on this
   runtime (Node 24.19, ICU 78) `Intl` prints a plain space. The comment now says it is a guard, not a measured fix.
7. **shadcn step** (plan step 6): the CLI cannot run from `apps/calendar` (alias `ui` unresolved) and was run from
   `packages/ui`. It wrote `import { cn } from "cn"` into all five files and added an unrelated npm package `cn`; I rewrote
   the imports to `@repo/ui/lib/utils`, removed the dependency, restored `button.tsx` with `git checkout` (registry copy
   differed only in that import), and added `lucide-react`. `pnpm --filter @repo/ui check-types` and `lint` pass. All in `notes.md`.
8. **Unplanned extras:** `useId`-linked `aria-controls` on the combobox input; an `eslint-disable turbo/no-undeclared-env-vars`
   region in `dates.test.ts` (the zone test sets `TZ` on purpose); `lib/calendar-href.ts` got `withIds` only, no `withMonth`
   (a spread suffices); the page's range line reads "Showing Mon, Sep 28 – Sun, Oct 25".
9. **Plan review #2's "may offer to overwrite `button.tsx`"** was right; **#10's** headless-Chrome measurement is Verification 6.

**`TODO(Ari)` gaps (all five open; none filled by anyone).** Review the code as it stands; open gaps aren't findings.
- Gap A — `metroToday`, [lib/dates.ts:47](apps/calendar/lib/dates.ts#L47): "today" is the metro's date, not the server's.
- Gap B — `isAfterMidnight`, [lib/dates.ts:98](apps/calendar/lib/dates.ts#L98): the 5:00 AM rule as one `PlainTime.compare`.
- Gap C — the date loop in `groupCalendar`, [lib/calendar.ts:61](apps/calendar/lib/calendar.ts#L61): rows come from the served range.
- Gap D — `navigate` in the filter header, [app/_components/filter-header.tsx:76](apps/calendar/app/_components/filter-header.tsx#L76): the URL is the state.
- Gap E — the scroller's classes, [app/_components/calendar-grid.tsx:63](apps/calendar/app/_components/calendar-grid.tsx#L63): the scroller must be the grid item.
Fill order: A, B, C (unit tested), then E, then D. Tests: `pnpm --filter calendar test dates calendar`. While A–C are open `/`
renders the error boundary; with D–E open nothing fails to build, E's page overflows sideways and D's handler throws on use.

**Verification.**
- **Tests first.** Stubs that throw, run: 42 failures, all "not implemented" / a missing method (assertions, not import errors). Then implemented.
- **Baseline before any change:** `make check` green (411 Python, 94 Vitest, contract current).
- **`make check` at handoff:** ruff, mypy (29 files), eslint, `next typegen` + tsc all clean; **pytest 411 passed**; Vitest **121 passed, 32 failed** — exactly the open-gap tests: `dates.test.ts` 18 (A: `metroToday` ×4, `metroTodayOrNull` ×2; B: `isAfterMidnight` ×7, `nightSortKey` ×1, `formatShowTime` ×4 — `formatShowTime` calls B for every time) and `calendar.test.ts` 14 (C). `make contract-check`: current. (`make check` stops at Vitest, so contract-check was run on its own.)
- **Snippets validated.** With the five `Code:` snippets applied exactly as written (scratch application in the tree, restored byte-for-byte; SHA-256 of all four files checked before and after): **Vitest 153/153**, `check-types` and `lint` clean.
- **V3 (build, API unreachable):** `API_BASE_URL=http://127.0.0.1:9 pnpm build` succeeds; `/`, `/_not-found`, `/artist/[id]`, `/artists`, `/day/[date]`, `/health`, `/venue/[id]`, `/venues` all `ƒ`; only `_global-error.html` is prerendered. **Bundle check:** the polyfill's error text is in server chunks only, **none in `.next/static`**. **`@source`:** built three ways and grepped the CSS for `combobox-chip` — old two-`..` path absent, no `@source` absent, the three-`..` path present.
- **V4 (HTTP matrix, `next start`, snippets applied):** `/` 200 (28 rows, 25 blocks, one "Today"); `/?venue=1` 8 blocks; `/?venue=1&venue=3` 14; `/?venue=9999` and `/?month=2026-02` "No matches found" and no grid; `/?venue=abc` ignored (25); `/?month=2026-10` 31 rows, 22 blocks; `/day/2026-10-07` 5 blocks; `/day/2026-02-30`, `/day/garbage`, `/venue/9999`, `/venue/abc`, `/nope` all **404** (re-checked because `/` now streams); `/venue/1`, `/artist/1`, `/health` 200.
- **V5 (API stopped):** `/` **200** with header, footer and skeleton and no error text or URL; `/venues`, `/venue/1` still B2's bare 500; `/venue/abc` and `/nope` 404; `/health` 200; recovers on restart with no Next restart.
- **V6 (headless Chrome, CDP, snippets applied):** page `scrollWidth`/`clientWidth` equal at 375, 500, 768 and 1280px; the 2026-10-07 scroller is 1060 wide in a 343 / 468 / 580 / 964px box. **Wrapper experiment at 1280px:** direct 1280/1280, wrapped in a bare `<div>` **1296**/1280, wrapper with `min-width: 0` 1280/1280. **With only Gap E open:** page 1076 (375, 500), 1232 (768), 1296 (1280) against the viewport — the failure its Check names. 500px is headless Chrome's floor; 375 was set with device-metrics emulation.
- **Filter header in a browser (CDP, snippets applied, no console errors or exceptions):** typing "Zhor" leaves one option; picking it gives `/?venue=3` and 6 blocks; adding White Squirrel gives `/?venue=1&venue=3` (canonical though 3 was picked first) and 14 blocks; Back returns to `/?venue=3`; "Clear filters" to `/`; `/?month=2026-10&venue=9999` shows "October 2026" in the select and the empty state.
- **Not verified:** touch scrolling and back-gesture chaining (no touch device), keyboard scrolling of a row, picking a month through the select's popup (the month round-trips via URL only), dark mode, the sticky heading on a real phone, and Vercel's build as opposed to a local one.

**Where to look hardest.**
1. `app/_components/calendar-grid.tsx`: the `md:grid` / block-flow split and whether the sticky heading really sticks on a phone (I could not run one). Whether `role="region"` + `tabIndex={0}` on every row is right for 28 rows (28 tab stops).
2. `app/_components/filter-header.tsx`: the controlled `value={selected}` against object items, `useOptimistic` with a `filters` prop that the server replaces, and the `NEXT_FOUR_WEEKS` sentinel for the select.
3. `lib/dates.ts` `nightSortKey` / `formatShowTime` (after-midnight and the day suffix) and `metroTodayOrNull`'s `RangeError`-only catch.
4. The `packages/ui` files the CLI wrote: I fixed imports and dependencies but did not otherwise review them (generated code).
5. Whether the five gaps are still the right lines now that the scaffold exists, and whether A and B should merge (plan review #3).

## Code review

### Round 1 — Claude Opus 5.5, October 12, 2026

**Scope:** the uncommitted working tree on top of `b445e6f`, as listed in Implementation log round 1: the tracked diff
(`git diff HEAD`, 15 files plus the staged deletion of `plain-show-list.tsx`) and the untracked files it names (`lib/{dates,
calendar,show-format,calendar-href,todo}.ts` and their tests, `app/_components/{calendar-grid,calendar-skeleton,filter-header,
show-block}.tsx`, `packages/ui/src/components/{combobox,select,input-group,input,textarea}.tsx`). The five `TODO(Ari)`
gaps are open and are not findings. `a3-validation-and-retry.md` is outside the scope.

**Read:** `AGENTS.md`, `apps/calendar/AGENTS.md`, `docs/references/nextjs-style-guide.md` (including the Anti-patterns
table), `requirements-initial.md` ("Calendar", "/Day view"), the plan body, plan review round 1, and the code it builds on
(`app/layout.tsx`, `app/error.tsx`, `lib/{params,api,types}.ts`, `routers/shows.py` `_ordering`, `packages/ui/components.json`,
Base UI's `AriaCombobox.mjs`), plus `a2-extraction-schema.md` for how gap markers were handled last time.

**How it was checked.**
- **`make check` in the real tree:** ruff, mypy (29 files), eslint and `next typegen` + tsc are clean; pytest **411 passed**;
  Vitest **121 passed, 32 failed**. The failures are `dates.test.ts` 18 and `calendar.test.ts` 14, and every one throws
  `Error: TODO(Ari)` from `lib/todo.ts:17`. This matches the log. CONFIRMED.
- **Throwaway `git worktree`** at `b445e6f` (in the session scratchpad) with the working tree copied in, `pnpm install
  --offline`, and `apps/api/.env` copied so `make types` could run. **Removed afterwards** with `git worktree remove` and
  `prune`, and `git status` was checked against its state at the start. In it:
  - **Snippets:** I applied all five `Code:` snippets exactly as written and removed the `todo` imports. Vitest
    **153/153**, `check-types` and `lint` clean, `make contract-check` "current".
  - **Mutation test of the zone test:** I swapped `formatDayHeading` to `new Date(date).toLocaleDateString(…)`. The
    Pago_Pago case fails and Kiritimati passes, as plan review #5 predicted, so the test does catch the trap.
  - **V3:** `API_BASE_URL=http://127.0.0.1:9 pnpm build` succeeds with every route `ƒ`. The polyfill's error text appears
    only in a server chunk and nowhere in `.next/static`. The built CSS contains `combobox-chip`.
  - **V4:** `next start` on :3765 against uvicorn on :8765, started from the real `apps/api`, which only reads it.
    - `/`: 200, 28 rows, 25 blocks, one "Today" on Mon, Oct 12.
    - `/?venue=1`: 8 blocks. `/?artist=1`: 4 blocks. `/?month=2026-10`: 31 rows and 22 blocks.
    - `/?venue=9999` and `/?month=2026-02`: "No matches found" and no grid.
    - `/day/2026-10-07`: 5 blocks ordered 6:00 PM, 8:00 PM, 9:00 PM, 10:00 PM – 12:30 AM, 1:00 AM Thu, with the heading
      "Wed, Oct 7, 2026".
    - `/venue/abc`, `/venue/9999`, `/day/garbage` and `/nope` all return 404.
  - **V5 (API stopped):** `/` returns 200 with the skeleton and no `ApiError` or API URL in the body. `/venues` and
    `/venue/1` return 500, `/venue/abc` and `/nope` return 404, and `/health` returns 200.
  - **V6 and the filter header in headless Chrome over CDP** (throwaway Node scripts in the scratchpad):
    - Page `scrollWidth`/`clientWidth` is equal at 375, 500, 768 and 1280. The 2026-10-07 scroller is 1060 wide in a
      343, 468, 580 or 964 px box.
    - **Sticky heading:** with that row scrolled 40 px above the viewport, its `<h2>` sits at `top: 0` at all four
      widths. That answers "Where to look hardest" #1 for emulated phones.
    - **Filters:** typing "Mid" leaves one option; picking it gives `/?venue=2` and 6 blocks.
    - **Month select through its popup** (the log listed this as not verified): the options are Next four weeks,
      September 2026 and October 2026. Picking October gives `/?venue=2&month=2026-10` with 31 rows.
    - **Server render:** `/?venue=1&venue=3&month=2026-10` renders both chips and "October 2026".
    - Across every page load, no console errors, warnings or exceptions.
- **Anti-patterns table, line by line, against the diff:** no hits.
  - `"use client"` is only on `filter-header.tsx` and the generated primitives.
  - No `useEffect` fetching, and `searchParams` is awaited.
  - No `useSearchParams`.
  - The primitives came from the CLI.
  - The Client Component props are `{id, name}` and `{value, label}`.
  - `grep` finds `new Date` and `parseFloat` only in comments.

**Counts:** 0 blocker, 1 should-fix, 5 nit. **Verdict: proceed after fixes.**
- The implementation matches the plan and holds up under its own verification steps, all of which I reproduced except
  touch input and keyboard scrolling.
- The departures are sound, and departure 1 is a real fix: the block-flow row is what makes the phone heading stick.
- The should-fix touches comments only: the open gaps are written in the form this repo uses for *filled* gaps.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **The five open gaps carry no `TODO(Ari)` marker.** Each block opens `(Ari) — Gap X. Lesson:`. That is the form a gap is rewritten to *after* it is filled. | CONFIRMED. Searching `TODO(Ari)` in `apps/calendar/{lib,app}` finds only `lib/todo.ts:2,17`. The open blocks (`lib/dates.ts:47`, `:98`, `lib/calendar.ts:61`, `app/_components/filter-header.tsx:76`, `calendar-grid.tsx:63`) read exactly like B2's filled ones (`lib/params.ts:121`, `:166`, `lib/metro.ts:38`, `app/venue/[id]/page.tsx:18`, `:34`), and both milestones use the letters A–E. `AGENTS.md` "[fill-in] tasks" step 2 and its example (`TODO(Ari) — Lesson:`). `a2-extraction-schema.md` (Implementation log, item 3) records Ari's rule that *resolved* gaps must not appear in a TODO search; the open ones are meant to. | A search for open work finds nothing. "Gap A" in `dates.ts` (open) and "Gap A" in `params.ts` (filled) look identical. Filling a gap leaves no textual change in its comment, so nobody can tell from the code which lessons have been typed. Fix: prefix each open block with `TODO(Ari) —` (`// TODO(Ari) — Gap E. Lesson:` …). This is a comment-only change, so use the repo's snapshot-and-compare check. The filled form then drops `TODO`, as A2 did. | **Fixed.** All five open blocks now open `TODO(Ari) — Gap X. Lesson:` (`lib/dates.ts` ×2, `lib/calendar.ts`, `filter-header.tsx`, `calendar-grid.tsx`), so a search for `TODO(Ari)` finds open work and a filled gap, once its `TODO` is dropped, no longer matches (the A2 convention). Comment-only: snapshotted the four files and compared them with comments stripped (TypeScript `transpileModule`, `removeComments`): identical for all four; the comparator was shown to report a difference when code does change |
| 2 | nit | **Filling a gap as its `Code:` says leaves an unused `todo` import, so `make check` fails at lint.** Gaps A, B, C and D say "replace the `todo` line". Only D mentions an import change, and that one is adding `buildCalendarHref`. | CONFIRMED in the worktree: with the snippets applied and `import { todo } from "./todo"` left in `lib/dates.ts`, `pnpm lint` reports `'todo' is defined but never used  @typescript-eslint/no-unused-vars` and exits 1 under `--max-warnings 0`. `lib/todo.ts`'s docstring says to delete the file after the last gap, but no gap says so. | Ari's own Check (`pnpm --filter calendar test dates`) goes green, then `make check` goes red on a line Ari didn't write. It costs a minute, but it is avoidable. Fix: add "and delete the `todo` import once no gap in this file uses it" to the `Code:` of B, C and D (the last gap in each file). In the handoff, say that `lib/todo.ts` goes once all four are filled. | **Fixed.** The `Code:` of Gaps A/B (`dates.ts`: the second one filled removes the import), C (`calendar.ts`) and D (`filter-header.tsx`) now says to delete the `todo` import. Verified by applying the snippets that way with `lib/todo.ts` removed: Vitest 153/153, `check-types` and `lint` clean. The handoff says `lib/todo.ts` goes when the last of A–D is filled |
| 3 | nit | **Gap E's lesson holds only from `md` up, and its experiment barely shows at the width the Check names.** The comment at `calendar-grid.tsx:50-57` says the scroller is "the `<li>`'s direct grid item" without a width condition. Since departure 1, the `<li>` is block flow below `md`, and there a wrapper is harmless. At 1280 px the overflow is 16 px. Separately, departure 2 cut the typed part to one `className`, so the structural lesson is carried by the experiment rather than by what Ari types. | CONFIRMED by wrapping the 2026-10-07 scroller in a bare `<div>` in the live page (DOM edit over CDP) and reading page `scrollWidth`/`clientWidth` direct, wrapped, then wrapped with `min-width: 0`: at 375 px **375 / 375 / 375**; at 768 px **768 / 1232 / 768**; at 1024 px **1024 / 1232 / 1024**; at 1280 px **1280 / 1296 / 1280**. | At phone width Ari can't reproduce the stated failure. At 1280 the check does turn `false`, but "the page scrolls sideways" is a 16 px nudge that is easy to miss. Fix: say "from `md` up (below it the row is block flow, where a wrapper's width is its container's)" in the comment and in Gap E's Lesson. Run the wrapper experiment at 768–1024 px, where the page grows by roughly 460 px. Whether a class-string gap is still worth keeping is Ari's call, as plan review #3 left it. | **Fixed.** The comment in `calendar-grid.tsx` and Gap E's lesson/check in this plan say the lesson holds from `md` up and that below it a wrapper is harmless; the experiment is now to be run at 768–1024px (page 768 → 1232) rather than 1280px (only +16px). I re-measured nothing — the numbers are the reviewer's; they agree with my own 1280px figure (1296). `notes.md` carries all four widths. Whether a class-string gap is worth keeping is left to Ari, as in plan review #3: the structural lesson is carried by the experiment, not by the typed classes |
| 4 | nit | **`tabIndex={0}` and `role="region"` on every row with shows: 20 extra tab stops and 20 landmarks on `/`.** | CONFIRMED count: `document.querySelectorAll('[role=region][tabindex="0"]').length` is 20. PLAUSIBLE, not run through axe: every venue column already holds a focusable link (its heading), so Tab reaches each row and scrolls it into view, and arrow keys scroll the focused link's scroll container. axe's `scrollable-region-focusable` passes when a region contains focusable content. | Keyboard users tab through an extra stop per date before reaching that date's links, and a screen reader's landmarks list has 20 near-identical "Shows on …" entries. This is not a defect, and the implementer flagged it. Decide during Ari's keyboard check (Verification 7): either drop `tabIndex` (and possibly the region role), or record in the plan why the extra stops are wanted. | **Rejected (for now), flagged to Ari.** The row's `role="region"` + `tabIndex={0}` was specified by the approved plan, and axe's `scrollable-region-focusable` accepts either. Whether 20 extra tab stops and landmarks are worth it is a keyboard-use judgment, which Verification 7's keyboard check is for. If Ari prefers fewer, the change is deleting `tabIndex` and `role` on one element in `calendar-grid.tsx`; nothing else depends on them |
| 5 | nit | **`aria-controls={listId}` on `ComboboxChipsInput` overrides Base UI's own value, and nothing says why.** Base UI sets `aria-controls` only while the popup is open. The override makes it point, while collapsed, at a list that isn't in the DOM. | CONFIRMED: `@base-ui/react/combobox/root/AriaCombobox.mjs:873` (`reference['aria-controls'] = expanded ? listElement?.id : undefined`). The server-rendered `/` has `<input … role="combobox" aria-expanded="false" … aria-controls="_R_12pbtb_" id="filter-venues">`, and no element with that id exists while closed. Log departure 8 lists it as an "unplanned extra" without a reason. | Probably harmless: ARIA 1.2 lists `aria-controls` as required on a combobox, and that may be the intent. But it changes a generated primitive's behaviour without the comment this repo asks for, so the next person may remove it, or copy it, blind. Fix: add a one-line comment giving the reason, or drop it if there isn't one. | **Fixed.** Dropped the `aria-controls` override, the `useId` that fed it and the `id` on `ComboboxList` from `filter-header.tsx` — I had no reason for it beyond ARIA 1.2's wording, and Base UI sets `aria-controls` itself while the popup is open (`AriaCombobox.mjs:873`). Re-ran the browser interaction (type-to-filter, pick, canonical URL, Back, Clear) on the final code: same results, no console errors |
| 6 | nit | **`docs/dev/notes.md` gains a trailing blank line at EOF.** | CONFIRMED: `git diff HEAD --check` reports `docs/dev/notes.md:375: new blank line at EOF`. | Whitespace noise in the diff. Fix: delete the last empty line. | **Fixed.** Removed the trailing blank line; `git diff HEAD --check` is clean |

**Resolutions** (Claude Sonnet 5.5, October 12, 2026): 5 fixed, 1 rejected for now (#4, flagged to Ari). #1, #2, #5 and #6
were fixed by me and re-verified; #3 rests on the reviewer's measurements (they agree with mine at 1280px). No finding
was testable as a failing test first (#1, #3, #6 are comment/whitespace; #2 is a `Code:` instruction; #5 is the removal of
an attribute with no test surface), so none has a new test.

Rejected: #4 — keep `tabIndex={0}` and `role="region"` until Ari's keyboard check decides (reason above).

Test-suite result after the fixes: `make check` — ruff, mypy (29 files), eslint, `next typegen` + tsc clean; pytest **411
passed**; Vitest **121 passed, 32 failed**, the 32 being exactly the open-gap tests (`dates.test.ts` 18, `calendar.test.ts`
14). `make contract-check` current. With the five `Code:` snippets applied as now written (including deleting the `todo`
imports and `lib/todo.ts`): Vitest **153/153**, `check-types` and `lint` clean, and the filter flow works in headless Chrome.

