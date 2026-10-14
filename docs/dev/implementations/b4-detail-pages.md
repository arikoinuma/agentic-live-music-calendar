# B4 — detail pages

**Status:** Plan review
**Date:** October 14, 2026
**Author model:** Claude Opus 5.5 (plan)
**Reviewer model:** — (plan review round 1 pending)
**Spec:** `docs/dev/alpha-build-plan.md` §6 B4; `docs/arch/requirements-initial.md` ("Main Views & URL Scheme",
"Calendar" → "/Day view", "Venue", "Venues", "Artist", "Artists", "Show" — including "Times after midnight", "Metro");
`docs/arch/arch-initial.md` §4 (content model and JSON-LD, filter and view state in the URL, Google Maps links);
`docs/dev/api-contract.md` §2–6; `docs/references/nextjs-style-guide.md`; Next's own
`node_modules/next/dist/docs/01-app/02-guides/json-ld.md`; `docs/dev/implementations/b2-routes-and-data-loading.md`
(D1, D3, D4) and `b3-the-calendar.md` (D1–D8 and its "Follow-ups for other milestones"), both of which B4 inherits

## Context

B2 made the six routes exist and load their data; B3 built the real calendar on `/` and gave `/day/[date]` show
blocks. The detail routes are still B2's deliberately plain versions: `/venue/[id]` and `/artist/[id]` print metadata
only, `/day/[date]` lists one day's blocks in night order with no way to change it, and `/show/[id]` does not exist.
B4 finishes them, which is also point 4 of the phase's definition of done (`alpha-build-plan.md` §2: "with venue and
artist detail pages behind working links").

What the requirements ask for, and what exists today:

| Route | Requirement | Today | B4 |
|---|---|---|---|
| `/venue/[id]` | "lists the meta data of a venue … Has the default calendar lower in the page filtered to the venue … go back and forth to past or future with that exact calendar" | Metadata, raw enum values (`twenty_one_plus`) | Readable metadata, a Google Maps link, the B3 grid filtered to the venue with earlier/later paging, Event JSON-LD |
| `/artist/[id]` | "lists the meta data of an artist … Artist page contains the list view of their upcoming shows" | Metadata only | Readable metadata, a dated list of the artist's shows with the same paging |
| `/venues`, `/artists` | "a simple list sorted alphabetically" | Done in B2 (alphabetical from the API, each a link) | Nothing beyond a check (D5) |
| `/day/[date]` | Three orderings — by venue by alpha (default), by venue by time, by artist by alpha; venue modes as blocks, artist mode as "a list of Artist with the associated venue and time" | One ordering (night order, B3 departure 5) | All three, chosen by a URL search param |
| `/show/[id]` | "show = constitutes a single live music event" (a main view); `arch-initial.md` §4: every event gets its own server-rendered page carrying `schema.org` Event JSON-LD | Missing (B2 D3 deferred it until something links to it) | The page, `getShow()`, a link to it from every show block, Event JSON-LD |

What B4 is *not*: component tests (B5); edit forms ("Any user can edit the fields" is the later write phase);
socials, genres, members, instrumentation (absent from the contract on purpose, `api-contract.md` §6); an event page
(`requirements-initial.md`: "perhaps v2"); slugs in URLs (§6); a site URL / `metadataBase` (hosted phase); caching
(`arch-initial.md` §11).

### Decisions already made (earlier in this project)

- **Every route is dynamic and nothing is cached** (B2 D1). Unchanged.
- **The server owns "now"** (`api-contract.md` §3). B4 keeps the client from computing any window: the embedded
  calendars ask for the server's default window, page by sending only a `start`, and take every date they display from
  the `start`/`end` the API echoes (the paging section below).
- **Detail routes do not stream** (B3 D4). A `<Suspense>` boundary above a `notFound()` turns a 404 into a soft 200,
  so the venue, artist, show and day pages keep awaiting their data at the top level, as in B2. Consequence, unchanged
  from B2: with the API down they answer a bare 500.
- **Show dates and times are wall-clock values with no zone**; the metro's zone answers only questions about the real
  instant (B3, "What 'dates in the metro's timezone' actually means here"). B3 had one such question, "today". B4 adds
  the second: the JSON-LD `startDate` (below).
- **Times after midnight** (Ari, October 11; `requirements-initial.md` "Show"): a time before 5:00 AM belongs to the
  end of the night the show is listed under. `isAfterMidnight` and `nightSortKey` in `lib/dates.ts` own the rule; B4
  calls them and adds no second copy.
- **Null admission is "not stated", never free** (`api-contract.md` §4). This now also governs the JSON-LD `offers`.
- **B3's follow-ups for B4:** reuse `CalendarGrid` for the venue page, `ShowBlock` for the artist page, `nightSortKey`
  for the day view's "by venue by time" mode. All three are taken up.

### Paging an embedded calendar without a client clock (checked)

The venue page's requirement ("go back and forth to past or future with that exact calendar") needs a displayed range
that can move, and `arch-initial.md` §4 puts "the displayed date range" in the URL. The plan uses one search param,
`from=YYYY-MM-DD`, and leaves every other number to the server:

- **No `from`:** call `getShows({ venueIds: [id] })` with no dates; the API picks its default window (today plus 27
  days, `routers/shows.py` `DEFAULT_WINDOW`) and echoes it.
- **With `from`:** send `start=from` **and no `end`**. The API already handles that case (`if end is None: end = start
  + DEFAULT_WINDOW`), so the window length stays the server's decision, not a constant copied into TypeScript.
- **The links** come from the echoed range alone: *later* starts the day after `end`; *earlier* starts one window
  length before `start`, the length being `start.until(end).days + 1`. For the sample window 2026-09-28..2026-10-25 that
  is 28 days, so earlier = `2026-08-31`, later = `2026-10-26` (checked in Node with the polyfill). This is Gap B.
- **One edge, handled in the parser:** `from=9999-12-20` passes `parseDateParam`, but the API's `start + 27 days`
  overflows Python's `date` (max 9999-12-31) and answers 500. A search param must never 500 (`lib/params.ts`
  docstring), so `parseFromParam` also rejects a year above 9998.

### JSON-LD dates carry the metro's offset (checked)

`schema.org` `startDate` is an ISO 8601 date or date-time. Google's Event guidance asks for the venue's UTC offset on a
date-time, and only the metro's IANA zone can supply it. Checked with the polyfill:

| Listed as | `startDate` | Why |
|---|---|---|
| 2026-10-07, 20:00 | `2026-10-07T20:00:00-05:00` | CDT |
| 2026-10-07, 01:00 | `2026-10-08T01:00:00-05:00` | After midnight: the show is Wednesday night's, the instant is Thursday morning |
| 2026-12-05, 20:00 | `2026-12-05T20:00:00-06:00` | CST — the offset comes from the date, not a constant |
| 2026-10-31, 01:30 | `2026-11-01T01:30:00-05:00` | 01:30 on Nov 1 happens twice (fall back); Temporal's default `compatible` picks the earlier, CDT |
| 2026-10-07, no time | `2026-10-07` | A bare date is valid; never an invented midnight |
| metro unavailable or zone invalid | `2026-10-07T20:00:00` | Local time without an offset rather than a guessed zone or a failed page |

Built as `PlainDate.from(date).add({ days: isAfterMidnight(t) ? 1 : 0 }).toZonedDateTime({ timeZone, plainTime: t })
.toString({ timeZoneName: "never" })`. `endDate` follows the requirements' rule: the next calendar day when the end
time is after midnight **or** earlier than the start ("An end time earlier than its start is the next morning").

### Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **`/show/[id]` is built here.** The build plan's JSON-LD item says "show and venue pages", but no show page exists:
   B2 D3 deferred it until show blocks link to it, and B3 didn't make them links. B4 adds the page, `getShow()`, and the
   link (D3).
2. **Two [fill-in] items are proposed as [written]** (D5): the artist page (its only logic is reuse of B3 pieces and
   B4's Gap B) and `/venues` + `/artists` (B2 already built them to the requirement). Per `AGENTS.md`, no gap is
   invented for them.
3. **Added, not in the build plan's B4 list:** paging for the embedded calendars (`?from=`, D1); readable labels for
   the enum fields; the venue's Google Maps link (`arch-initial.md` §4 — it was never assigned to a milestone); real
   page titles through `generateMetadata` (D7).

## Decisions for Ari

Each has a recommendation, and the plan is written assuming it. **Ari: please confirm or change D1–D8 before
approving.** D1, D3 and D4 change the most.

- **D1 — The venue page's calendar pages earlier/later through `?from=YYYY-MM-DD`. Recommended.** The requirement asks
  for "back and forth to past or future with that exact calendar"; the mechanism is the "Paging" section above. The
  page also gets an "Open in the calendar" link to `/?venue=N` — the requirement's "anything other than [paging] … they
  have to go to a calendar view page". No filter header on the venue page. *Alternative:* no paging in B4 (the default
  four weeks only) and the requirement's back-and-forth deferred.
- **D2 — The artist page lists the server's default four weeks, with the same earlier/later paging. Recommended.** "Upcoming
  shows" really means *every* future show, and an artist with one show six weeks out would read "No shows listed" for
  the default window. But a longer window means either the client computing dates (against "the server owns now") or a
  new API parameter — a contract change that `AGENTS.md` ("Parallel tracks") wants in its own early PR. Paging covers
  the gap without either. *Alternative:* an API change, e.g. `GET /shows?artist_id=7&upcoming=true` returning every
  future show; worth doing in A1b when the query is real, not against sample data now.
- **D3 — `/show/[id]` exists, and each show block's time line becomes its link. Recommended.** The block already holds
  venue and artist links, which can't nest inside a block-wide link (B3 step 4). The time line ("8:00 PM – 11:30 PM") is
  the one line that is about the show itself, so it becomes `<Link href="/show/N">` with a visually hidden
  ", show details" so its accessible name says where it goes. *Alternative:* a separate small "Details" link at the
  bottom of each block (one more line in every block, 25 on `/`).
- **D4 — Posters and photos are links, not embedded images. Recommended.** `image_url` and `photo_url` point at
  arbitrary venue and artist hosts. Embedding means either `next/image` with an open-ended `images.remotePatterns`, or a
  bare `<img>` with `@next/next/no-img-element` disabled under `--max-warnings 0`; either way every reader's browser
  requests images from third-party hosts, and a dead link shows a broken image. A "Poster" / "Photo" link costs none of
  that. JSON-LD still carries `image` (search engines fetch it themselves). *Alternative:* a plain `<img>`,
  `loading="lazy"`, `referrerPolicy="no-referrer"`, with a one-line `eslint-disable-next-line` and a comment saying why;
  serving copies from R2 is the hosted phase's.
- **D5 — Re-mark two [fill-in] items [written].** Per `AGENTS.md` ("If no line in a [fill-in] task meets that bar, say
  so … propose re-marking it [written] — don't invent a gap"). *Artist page:* the fetch → 404 flow was B2's Gap E, the
  list is B3's `ShowBlock` sorted by the existing `nightSortKey`, the paging is Gap B; nothing new is left to type.
  *`/venues` and `/artists`:* B2 already built "a simple list sorted alphabetically" (the API sorts; each name links);
  B4 changes no code there unless the browser check finds a reason.
- **D6 — Day view mode is `?sort=` with values `time` and `artist`; the default (`venue`) is the bare URL.
  Recommended.** One canonical URL per view, like the calendar's filters (`/day/2026-10-07` is venue order;
  `?sort=venue` is accepted and treated as the default, but never written). The switch is three plain `<Link>`s with
  `aria-current="page"` on the active one — no Client Component, no JavaScript: changing the view is a navigation and
  the server renders it (`arch-initial.md` §4, "the current view"). An unknown value is ignored, never a 404 (a
  search param is not part of the resource's identity). *Alternative:* `?view=`; or a select (would need a Client
  Component for no gain).
- **D7 — Real page titles via `generateMetadata`. Recommended.** The detail pages exist for search and sharing
  (`arch-initial.md` §4), and every tab currently reads "Venue · …" or "Artist · …". `generateMetadata` and the page both
  need the record, so `getVenue`, `getArtist` and `getShow` are wrapped in React `cache()` (their argument is a number,
  so `cache()` keys correctly — B2 left them unwrapped only because nothing called them twice). *Alternative:* keep the
  static titles.
- **D8 — JSON-LD stays [written], as the build plan marks it, but its date line is lesson-shaped.** The `startDate`
  rule (after-midnight → next calendar date; the offset from the metro's zone) is the most interesting Temporal line
  in B4. The plan respects the marking. *Alternative, Ari's call:* make `eventDateTime` a fifth gap (Gap E: Lesson —
  the second and last place the metro's zone matters; Code — the expression in "JSON-LD dates" above; Check —
  `json-ld.test.ts`'s offset cases).

## Test approach (written first, watched fail, then made green)

Same shape as B2 and B3: logic lives in pure functions in `lib/` and is unit tested under Vitest's node environment;
async Server Components are **not** unit tested (style guide, Testing); pages are checked by build output, HTTP
responses, a JSON-LD parse and Ari's browser check (Verification). Expected values are worked out by hand from the
requirements, `lib/fixtures/shows.json` or a calendar, never read back from the code under test. Each test says where
its numbers come from.

**The fixture day.** Most expectations use `shows.json`'s 2026-10-07 (a Wednesday), which B3's D5 built to be hard:

| id | Venue | Start | Lineup (per-act time) |
|---|---|---|---|
| 8 | The Terminal Bar | 21:00 | Jaedyn James, Tarnation, Beasthead |
| 22 | The White Squirrel Bar | 18:00 | Lanue |
| 23 | The White Squirrel Bar | 22:00 (ends 00:30) | Nooky Jones (22:00), Pert Near Sandstone (23:15) |
| 24 | Zhora Darling | 20:00 | Charlie Parr |
| 25 | The Midway Saloon | 01:00 | Dead Man Winter |

### 1. `lib/show-order.test.ts` (new) — the day view's three orderings

`venueOrder` and `timeOrder` (comparators over `ShowSummary`) — **Gap D**:
- By venue (default) on the fixture day → ids `[25, 8, 22, 23, 24]`: The Midway Saloon, The Terminal Bar, The White
  Squirrel Bar (18:00 before 22:00), Zhora Darling. Alphabetical by the full name, as the API sorts venues (no
  "The"-stripping; see Not doing).
- By time → `[22, 24, 8, 23, 25]`: 18:00, 20:00, 21:00, 22:00, then the 1:00 AM show **last**, not first (clock order
  would put it first — the night rule).
- Ties (hand-built): two shows at one venue at the same time keep their input order (stable sort); two 20:00 shows at
  different venues sort by venue name in time mode; an untimed show is last within its venue in venue mode and last of
  all in time mode.

`artistRows(shows)` — **Gap C**:
- The fixture day → 8 rows, one per act, in this order (alphabetical, worked out by hand): Beasthead (Terminal Bar,
  21:00 — the show's time, no per-act time), Charlie Parr (Zhora Darling, 20:00), Dead Man Winter (The Midway Saloon,
  01:00), Jaedyn James (Terminal, 21:00), Lanue (White Squirrel, 18:00), Nooky Jones (White Squirrel, 22:00 — his own
  time), Pert Near Sandstone (White Squirrel, 23:15 — his own time, not the show's 22:00), Tarnation (Terminal, 21:00).
- Each row carries the artist, the venue, the show id and the date, so the page can link all three.
- One artist on two bills the same night (hand-built: 22:00 and 01:00) → two rows, the 22:00 one first (night order,
  not clock order).
- A show with an empty lineup contributes no rows (the requirements say a show has one or more artists, but the
  contract's `lineup` is a list and nothing enforces it).

`parseDaySort(value)` (written): `undefined` → `"venue"`; `"time"`, `"artist"` → themselves; `"venue"` → `"venue"`;
`"bogus"`, `""`, `"TIME"` → `"venue"`; a repeated key (`["artist", "time"]`) → the first valid value, matching
`parseMonthParam`'s rule.
`dayHref(date, sort)` (written): `("2026-10-07", "venue")` → `/day/2026-10-07`; `"time"` → `/day/2026-10-07?sort=time`.
**Round trip:** `parseDaySort` of each written href's `sort` gives back the mode.
`inNightOrder(shows)` (written; the artist page's order): by date, then `nightSortKey` — Charlie Parr's four fixture
shows come out 2026-09-28, 2026-10-07, 2026-10-08, 2026-10-20 whatever the input order.

### 2. `lib/calendar-window.test.ts` (new) — paging the embedded calendars

`windowLinks(start, end)` — **Gap B**:
- `("2026-09-28", "2026-10-25")` (the sample API's default window) → `{ earlier: "2026-08-31", later: "2026-10-26" }`.
  Hand-worked: 28 days inclusive; 28 days before Sep 28 is Aug 31 (Sep has 30 days: Sep 28 − 27 = Sep 1, − 1 more = Aug
  31).
- Leap year: `("2028-02-01", "2028-02-28")` → `later: "2028-02-29"`, `earlier: "2028-01-04"`.
- Year end: `("2026-12-20", "2027-01-16")` → `later: "2027-01-17"`, `earlier: "2026-11-22"`.
- One-day range `("2026-10-07", "2026-10-07")` → `earlier: "2026-10-06"`, `later: "2026-10-08"` (the length comes from
  the range, not a constant 28).

`windowHref(path, from)` (written): `("/venue/3", "2026-10-26")` → `/venue/3?from=2026-10-26`; `("/venue/3", null)` →
`/venue/3` (the server's default window).

### 3. `lib/params.test.ts` (cases added; existing cases unmodified)

`parseFromParam(value)` (written): `"2026-10-26"` → that string; `undefined`, `""`, `"garbage"`, `"20261026"`,
`"2026-02-30"` → `null` (same strictness as `parseDateParam`, which it calls); `["2026-10-26", "x"]` → the first
valid; `"9999-12-20"` → `null` and `"9998-12-31"` → valid — the API overflow above.

### 4. `lib/json-ld.test.ts` (new)

`eventDateTime(date, time, timeZone)`: every row of the "JSON-LD dates" table above, offsets worked out from US DST
rules (2026: CDT until 2:00 AM Sunday November 1, then CST −06:00; 2027 spring-forward is March 14), not from the code.
`eventEndDateTime(date, start, end, timeZone)`: `22:00`–`00:30` on 2026-10-07 → `2026-10-08T00:30:00-05:00`;
`18:00`–`23:00` → same day; `21:00`–`06:00` (end before start, not after midnight) → next day; `01:00`–`03:00` →
both next day (`2026-10-08T03:00:00-05:00`); end null → `null` (the key is omitted).
`showJsonLd(show, { venue, timeZone })`:
- `@context` `https://schema.org`, `@type` `MusicEvent`, `eventStatus` `https://schema.org/EventScheduled`,
  `eventAttendanceMode` `https://schema.org/OfflineEventAttendanceMode`.
- `name`: the lineup names in performance order, joined with ", " (`show-detail.json`: "Nooky Jones, Beasthead"); an
  empty lineup → "Live music at <venue name>".
- `performer`: one `{ "@type": "MusicGroup", name }` per act. `location`: `{ "@type": "MusicVenue", name }`, plus
  `address` only when the venue detail has one (`VenueDetail` id 3's address).
- **`offers`, the contract's rule:** `free_admission: true` → one offer with `price: "0"`, `priceCurrency: "USD"`;
  `"18.00"` / `"22.00"` → two offers carrying those **strings** (no `parseFloat`), named "Advance" and "Door"; a lone
  day price → one offer with no name; **all three null → no `offers` key at all** (asserted with `not.toHaveProperty`),
  never a price of 0.
- `image` present only when `image_url` is.
`jsonLdScriptContent(data)`: a name containing `</script><script>alert(1)</script>` serialises with **no `<`
character** in the output, and `JSON.parse` of the output gives the original name back (the escape is lossless).
**Why this matters here:** show and artist names are scraped from venue websites by a model — exactly the untrusted
text Next's JSON-LD guide warns about.

### 5. `lib/detail-format.test.ts` (new)

`mapsUrl(address)`: `"1010 Washington Ave N, Minneapolis, MN 55401"` →
`https://www.google.com/maps/search/?api=1&query=1010%20Washington%20Ave%20N%2C%20Minneapolis%2C%20MN%2055401`
(`arch-initial.md` §4's format; `&` and `#` in an address are encoded, so they can't end the parameter).
Label maps (`AGE_LABELS`, `SETTING_LABELS`, …): one spot-check each (`twenty_one_plus` → "21+", `all_ages` → "All
ages", `both_other` → "Original and covers"). Their completeness is a compile-time guarantee: each is a
`Record<Enum, string>`, so a new enum value from `make types` is a type error, not a test failure.

### 6. `lib/api.test.ts` (tests added)

- `getShow(2)` calls `/shows/2` and returns `show-detail.json` unchanged; a 404 → `null`.
- `getShows({ start: "2026-10-26", venueIds: [3] })` sends `start` and `venue_id` and **no `end`** (the paging contract
  above; `apiUrl` omits undefined values, pinned here so a later "both or neither" refactor can't silently break it).

### What is *not* covered, stated plainly

- Rendered output of the four detail pages (async Server Components): build, HTTP checks, a JSON-LD parse of the served
  HTML, and Ari's browser check.
- That Google accepts the JSON-LD: the Rich Results Test and validator.schema.org need a public URL or a pasted
  snippet, and the cloud sandbox has no route to them. Verification 5 pastes the served JSON into the validator from
  Ari's machine.
- `cache()` de-duplication of `getVenue`/`getArtist`/`getShow` between `generateMetadata` and the page: one request
  per page load in the API log (Verification 4), not a unit test (`cache()` only works inside a server render).

### Tests-first caveat

As in B2 and B3: stubs that export the functions and throw come first, so the red state is assertion failures, not
import errors. The gap tests (B, C, D) stay red at handoff.

## Implementation steps

Order: pure functions first (they unblock everything), then the API client, then the pages, then cleanup.

### Working protocol for [fill-in] steps

As in B2, B3 and `AGENTS.md` "[fill-in] tasks": everything around each lesson is written (imports, types, signatures,
wiring, markup, tests — which stay red); the lines that carry the lesson become `TODO(Ari)` blocks with
**Lesson / Code / Check**; each placeholder throws through `lib/todo.ts` (B3's helper, recreated for B4 and deleted
when the last gap is filled); then stop and hand off with a file:line list. "Implement B4" does not fill the blocks.
Before handoff the four `Code:` snippets are applied in a scratch copy, everything is run, and the scaffold is restored
byte for byte (checksums), so the snippets are known to fit. **Handoff happens on an uncommitted tree** — or, in a cloud
session, pushed to the branch as `AGENTS.md` "Branches and PRs" item 5 allows, with the red tests named in the PR.

### TODO(Ari) gaps

Four blocks across two [fill-in] items — two each, inside `AGENTS.md`'s "1–3 spots": the venue page → A and B; the day
view → C and D. **Fill order: B, C, D first** (pure, unit tested, independent); **then A** (its check is the running
page, which needs B for the paging links).

- **Gap A — loading the venue page in parallel, `app/venue/[id]/page.tsx`** (step 5; the venue page item).
  *Lesson:* two `await`s in a row are a **waterfall**: the shows request can't start until the venue request has
  finished, though neither needs the other. The venue, its shows and the metro (for "Today") are independent, so start
  them together with `Promise.all`; the 404 check comes **after**, because a missing venue still costs only one wasted
  (and harmless, empty) shows request. This is the server-side form of the style guide's first anti-pattern — data
  loading that waits on something it doesn't need. The detail page still awaits at the top level, with no `<Suspense>`,
  so `notFound()` keeps its real 404 (B3 D4).
  *Code:*
  ```
  const [venue, { start, end, shows }, metro] = await Promise.all([
    getVenue(id),
    getShows({ venueIds: [id], start: from ?? undefined }),
    getMetroOrNull(),
  ]);
  if (venue === null) notFound();
  ```
  *Check:* `pnpm check-types`; then `curl -s -o /dev/null -w "%{http_code}"` → `/venue/1` 200, `/venue/9999` 404,
  `/venue/abc` 404; and in the Next terminal the `[api] GET /venues/1` and `[api] GET /shows?venue_id=1` lines both
  print, each with its own "in Nms", for one page load. Likeliest mistakes: `await getVenue(id)` then
  `await getShows(...)` (works — just slower, the waterfall; nothing fails, which is why it's worth typing once), or
  wrapping the `Promise.all` in a `try`/`catch` "for the 404" (`getVenue` already returns `null` on a 404, and a
  catch would also swallow `notFound()`'s throw if it were moved inside).
- **Gap B — `windowLinks`, `lib/calendar-window.ts`** (step 2; the venue page item, reused by the artist page).
  *Lesson:* the paging links are computed from the range the **server echoed**, never from a clock or a constant 28
  (`api-contract.md` §3). The window's length is `start.until(end).days + 1` — inclusive, hence the `+ 1`. Temporal does
  the month, year and leap-day arithmetic.
  *Code:*
  ```
  const s = Temporal.PlainDate.from(start);
  const e = Temporal.PlainDate.from(end);
  const length = s.until(e).days + 1;
  return { earlier: s.subtract({ days: length }).toString(), later: e.add({ days: 1 }).toString() };
  ```
  *Check:* `pnpm --filter calendar test calendar-window` — the default-window and one-day cases. Likeliest mistakes:
  forgetting the `+ 1` (earlier overlaps the current window by a day: `2026-09-01`), or `s.until(e).days` read from a
  `Duration` built with `largestUnit: "month"` (then `days` is the remainder, not the total — the default unit is days,
  so don't pass one).
- **Gap C — `artistRows`, `lib/show-order.ts`** (step 3; the day view item).
  *Lesson:* artist mode isn't a different sort of the same list — it's a different **shape**: one row per act, not one
  per show, so a three-act bill becomes three rows and an artist on two bills gets two. That's why the API returns flat
  shows and leaves grouping to the frontend (`routers/shows.py` docstring: "the day view needs three different
  groupings of identical data"). `flatMap` makes the shape, then the sort. Each row's time is the act's own when the
  listing gave one, else the show's.
  *Code:*
  ```
  const rows = shows.flatMap((show) =>
    show.lineup.map((entry) => ({
      artist: entry.artist, venue: show.venue, showId: show.id, date: show.date,
      time: entry.start_time ?? show.start_time ?? null,
    })),
  );
  return rows.sort((a, b) =>
    a.artist.name.localeCompare(b.artist.name, "en-US") || nightSortKey(a.time) - nightSortKey(b.time));
  ```
  *Check:* `pnpm --filter calendar test show-order` — the 8-row fixture case and the same-artist-twice case.
  Likeliest mistakes: `map` instead of `flatMap` (an array of arrays; the type error says so), or the show's time for
  every act (Pert Near Sandstone at 22:00 instead of 23:15).
- **Gap D — the two venue-mode comparators, `lib/show-order.ts`** (step 3; the day view item).
  *Lesson:* "by venue by alpha" and "by venue by time" are the **same two keys in opposite priority**. A comparator
  chain is `primary || secondary`: `0` (a tie) is falsy, so `||` falls through to the next key. Time is
  `nightSortKey`, not the clock (the 1:00 AM show is last). Names compare with `localeCompare` and a fixed locale, as
  `groupCalendar` does.
  *Code:*
  ```
  export const venueOrder = (a: ShowSummary, b: ShowSummary) =>
    byVenueName(a, b) || nightSortKey(a.start_time) - nightSortKey(b.start_time);
  export const timeOrder = (a: ShowSummary, b: ShowSummary) =>
    nightSortKey(a.start_time) - nightSortKey(b.start_time) || byVenueName(a, b);
  ```
  (`byVenueName` is written above the gap.)
  *Check:* `pnpm --filter calendar test show-order` — `[25, 8, 22, 23, 24]` and `[22, 24, 8, 23, 25]`. Likeliest
  mistakes: comparing `a.start_time < b.start_time` as strings (puts 01:00 first), or `&&` instead of `||` (every
  non-tie returns the secondary key).

### 1. Pure helpers (written) — `lib/params.ts`, `lib/detail-format.ts`, `lib/json-ld.ts`

- Tests first (§3, §4, §5).
- `parseFromParam` in `lib/params.ts`, next to `parseMonthParam` (same "first valid of a repeated key" rule, calls
  `parseDateParam`, adds the year ≤ 9998 check with a comment naming the API overflow).
- `lib/detail-format.ts`: `mapsUrl`; `Record<Enum, string>` label maps for age restriction, setting, seating, venue
  type, artist format and repertoire (from `app/enums.py`); `alcoholLabel(bool)`. Module docstring: why the maps are
  `Record`s (exhaustive by type).
- `lib/json-ld.ts`: `eventDateTime`, `eventEndDateTime`, `showJsonLd`, `jsonLdScriptContent`. Imports
  `isAfterMidnight` from `lib/dates.ts` (the rule's one home) and `orderedLineup` from `lib/show-format.ts`. Catches
  only `RangeError` from an unknown zone, as `metroTodayOrNull` does, and falls back to the no-offset form. Typed with a
  small local `JsonLdEvent` type, not the `schema-dts` package (one type, no new dependency). Docstring: why `<` is
  escaped (scraped text inside a `<script>`), why the offset, why no `offers` when nothing is stated, and that `url` is
  omitted until a site URL exists (hosted phase).

### 2. Window paging (fill-in: Gap B) — `lib/calendar-window.ts`, `app/_components/window-nav.tsx`

- Tests first (§2). `windowLinks` (Gap B) and `windowHref` (written).
- `WindowNav({ path, start, end, isDefault })` — a Server Component: "← Earlier" and "Later →" links built by
  `windowLinks` + `windowHref`, the range they sit between ("Mon, Sep 28 – Sun, Oct 25", via `formatDayHeading`), and,
  when the page isn't on the default window, "Back to the next four weeks" (`windowHref(path, null)`). Plain links, no
  JavaScript. `rel="nofollow"` on earlier/later, so crawlers don't walk an unbounded chain of empty windows.

### 3. The day view's orderings (fill-in: Gaps C, D) — `lib/show-order.ts`

- Tests first (§1). `byVenueName`, `parseDaySort`, `dayHref`, `inNightOrder` written; `venueOrder` and `timeOrder`
  (Gap D) and `artistRows` (Gap C) scaffolded.
- `DaySort = "venue" | "time" | "artist"`. The module is pure and Temporal-free itself, but imports `nightSortKey` from
  `lib/dates.ts`, so it is server-side in practice (stated in its docstring, like `lib/calendar.ts`).

### 4. The API client (written) — `lib/api.ts`

- Tests first (§6). Add `getShow(id)` (`getOrNull`, `/shows/{id}`) to `ApiClient`, `createApiClient` and the exports.
- Wrap `getVenue`, `getArtist` and `getShow` in `cache()` (D7) and rewrite the comment above `getMetro` that says only
  it is wrapped: they take a number, which `cache()` compares by value, and `generateMetadata` plus the page now call
  them twice per render. `getShows` stays unwrapped (object argument).
- Correct the `ShowsQuery` comment in `lib/params.ts` ("either both present or both absent"): a `start` alone is now
  sent on purpose, and the server fills `end`.

### 5. `/venue/[id]` (fill-in: Gap A)

- `VenuePage(props)` awaits `params` **and** `searchParams`; `parseIdParam` → `notFound()`; `parseFromParam`; then
  **Gap A** (`Promise.all` over `getVenue`, `getShows`, `getMetroOrNull`, then the 404 check).
- Above the calendar: name; a **Photo** link (D4); metadata as today's `<dl>`, now through the label maps, with the
  address as a link to `mapsUrl(address)`; phones as `tel:` links and emails as `mailto:` links; website and calendar
  URL as plain external `<a>`s, as B2 wrote them (no `target="_blank"`, so no `rel` is needed).
- The calendar: a "Shows" heading; `WindowNav`; then `CalendarGrid` with
  `groupCalendar({ start, end, shows, today })` — reused unchanged (B3 follow-up), so it is literally "the default
  calendar filtered to the venue"; when `shows` is empty, "No shows listed for these dates" instead of 28 empty rows;
  an "Open in the calendar" link to `buildCalendarHref({ venueIds: [id], artistIds: [], month: null })` (D1).
- `<JsonLd data={shows.map((s) => showJsonLd(s, { venue, timeZone }))} />` — the events in the displayed window, with
  the venue's address as their location. Nothing when there are no shows.
- `generateMetadata`: title = venue name; description "Live music at <name>, <address>" when there is an address.
  Calls the cached `getVenue`; a bad id returns the generic title (the page itself calls `notFound()`).
- Known cost, accepted: each venue column in the grid repeats the venue's name as a link to the page it's on. A
  `withVenueHeader` prop would remove it, but B3's grid has one shape and the requirement asks for that calendar.

### 6. `/artist/[id]` (written — D5)

- Same flow as the venue page (complete, not a gap): `params` + `searchParams`, `Promise.all` over `getArtist` and
  `getShows({ artistIds: [id], start: from ?? undefined })`, then `notFound()`.
- Metadata through the label maps; Photo link (D4); website.
- "Shows" heading, `WindowNav`, then an `<ol>` in `inNightOrder`: each item a date heading (`formatDayHeading` + year)
  over a `ShowBlock` with `withVenue` — B3's block, so time, venue, full lineup and price read the same as on `/`.
  Empty: "No shows listed between <start> and <end>" (both formatted, both the server's).
- No JSON-LD (the build plan scopes it to show and venue pages; see Not doing). `generateMetadata`: title = name.

### 7. `/day/[date]` (fill-in: Gaps C, D)

- Awaits `params` and `searchParams`; `parseDateParam` → `notFound()` (unchanged); `parseDaySort(searchParams.sort)`.
- A mode switch under the heading: "By venue · By time · By artist", three `<Link>`s to `dayHref(day, mode)`, the
  active one with `aria-current="page"` and no underline. Server-rendered; no Client Component (D6).
- `venue` and `time`: today's block grid, sorted with `venueOrder` / `timeOrder` (replaces B3's night-only sort and
  its comment).
- `artist`: a `<ul>` of `artistRows(shows)` — "**Artist** · Venue · 8:00 PM", the artist and venue as links and the
  time via `formatShowTime(date, time)` (so Dead Man Winter reads "1:00 AM Thu"), "Time not listed" when null. The
  requirement's "list of Artist with the associated venue and time".
- Empty day: unchanged ("No shows listed for this day."), whatever the mode.
- `generateMetadata`: title = the formatted date ("Wed, Oct 7, 2026"); no API call needed.

### 8. `/show/[id]` (written — the JSON-LD item, D3)

- New `app/show/[id]/page.tsx`; run `pnpm check-types` after adding it (`next typegen` makes `PageProps<"/show/[id]">`).
- `parseIdParam` → `notFound()`; `Promise.all([getShow(id), getMetroOrNull()])` → `notFound()` on `null`; then
  `getVenue(show.venue.id)` for the address. That second request **is** a dependent one (the venue id comes from the
  show) — a comment says so, so it isn't mistaken for Gap A's waterfall. A `null` venue (deleted between the two
  calls) renders the page without an address rather than a 404.
- Content: the date with year (`formatDayHeading`) and time line (`formatShowTime` + `formatClockTime` end, as the
  block); venue link and, when known, address as a Maps link; the lineup in `orderedLineup` with per-act times; the
  admission line (`formatAdmission`, nothing when `null`); the four resolved fields through the label maps (age,
  alcohol, setting, seating — `api-contract.md` §5: the page doesn't say whether they came from the venue); the event
  name as plain text when present (no event page, v2); **Poster** link (D4); **"Source: <venue's page>"** linking
  `original_url` — "part of making the agent's work visible to the reader" (`schemas.py`).
- `<JsonLd data={showJsonLd(show, { venue, timeZone: metro?.timezone ?? null })} />`.
- `generateMetadata`: title "<lineup> at <venue>, <date>".

### 9. JSON-LD component and the show block link (written)

- `app/_components/json-ld.tsx`: `JsonLd({ data })` renders
  `<script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScriptContent(data) }} />` — Next's
  recommended form (a native `<script>`, not `next/script`; its JSON-LD guide). The only `dangerouslySetInnerHTML` in
  the app; the comment says why it's safe here and points at the test.
- `app/_components/show-block.tsx`: the time line becomes `<Link href={`/show/${show.id}`}>` with
  `<span className="sr-only">, show details</span>` (D3). Update its docstring's "Deliberately NOT here" list (the
  `/show/[id]` bullet goes; the poster bullet now points at D4).

### 10. Docs and bookkeeping (written)

- `alpha-build-plan.md` B4: point at this file, tick the boxes, apply departures 1–3 and D5's re-markings.
- `apps/calendar/AGENTS.md`: the `?from=` paging and `?sort=` conventions under "Where data and URL state live"; the
  new `lib/` modules; `/show/[id]` and the cached getters; "the venue, artist and list pages are still deliberately
  plain until B4" becomes past tense; JSON-LD's escaping rule.
- `docs/dev/api-contract.md` §2: the `/shows` row already names the embedded calendars; add one line under Filtering
  that `start` without `end` means "the default window from `start`", which B4 now relies on.
- `docs/dev/notes.md`: only real surprises.

## Critical files

- New: `apps/calendar/lib/{show-order,calendar-window,json-ld,detail-format}.ts` + `.test.ts` for each;
  `apps/calendar/lib/todo.ts` (temporary, deleted with the last gap); `apps/calendar/app/show/[id]/page.tsx`;
  `apps/calendar/app/_components/{window-nav,json-ld}.tsx`
- Modified: `apps/calendar/app/{venue/[id],artist/[id],day/[date]}/page.tsx`,
  `apps/calendar/app/_components/show-block.tsx`, `apps/calendar/lib/{api,params}.ts` and
  `apps/calendar/lib/{api,params}.test.ts`, docs in step 10
- Reused as-is: `lib/{dates,calendar,show-format,calendar-href,metro,types}.ts`,
  `app/_components/calendar-grid.tsx`, `app/{venues,artists}/page.tsx` (D5), `app/{layout,error,not-found}.tsx`
- Not touched: `apps/api/` (no contract change — D2 keeps it that way), `lib/api-types.ts`, `lib/fixtures/`

## Verification

1. **Tests first.** New test files and stubs written, run, and confirmed red for the right reason (assertions, not
   imports) before implementing.
2. **`make check`** green with the snippets applied (ruff, mypy, eslint, `next typegen` + tsc, pytest, Vitest,
   contract-check). At handoff it is red only on the gap tests (B, C, D) — the log lists exactly which. Snippets applied
   in a scratch copy and restored byte for byte (checksums), as in B3.
3. **Build with the API unreachable** (`API_BASE_URL=http://127.0.0.1:9 pnpm build`): succeeds; every data route,
   `/show/[id]` and `/_not-found` are `ƒ`. Bundle check unchanged from B3 (`grep -rl "Do not use built-in arithmetic
   operators with" .next/static` finds nothing): B4 adds no Client Component.
4. **HTTP matrix** against `next start` with the API up (snippets applied), expected values from the fixture:
   - `/venue/1` [200; 8 show blocks; "Earlier" → `?from=2026-08-31`, "Later" → `?from=2026-10-26`; one JSON-LD
     script holding 8 events]; `/venue/3` [200; 6 blocks; events carry Zhora Darling's address];
     `/venue/1?from=2026-10-26` [200; "No shows listed"; a "Back to the next four weeks" link; no JSON-LD];
     `/venue/1?from=garbage` and `/venue/1?from=9999-12-20` [200; the default window]; `/venue/9999`, `/venue/abc`
     [404].
   - `/artist/1` [200; Charlie Parr's 4 shows in date order]; `/artist/9999` [404].
   - `/day/2026-10-07` [200; block order ids 25, 8, 22, 23, 24]; `?sort=time` [22, 24, 8, 23, 25]; `?sort=artist`
     [8 rows, Beasthead first, "1:00 AM Thu" on Dead Man Winter]; `?sort=bogus` [200; venue order];
     `/day/2026-02-30` [404].
   - `/show/2` [200; JSON-LD parses; `startDate` `2026-09-30T21:00:00-05:00`; two offers "18.00"/"22.00"];
     `/show/25` [`startDate` `2026-10-08T01:00:00-05:00`; one offer, price "0"]; `/show/22` [no `offers` key — Lanue's
     show has no admission data]; `/show/9999`, `/show/abc` [404].
   - `/venues`, `/artists` [200; alphabetical, unchanged]; `/` [200; each block's time line links to `/show/N`].
   - The JSON-LD checks extract the `<script type="application/ld+json">` body from `curl` output and `JSON.parse` it in
     Node; recorded as measured.
   - **De-duplication (D7):** one `[api] GET /venues/1` line per load of `/venue/1` (not two), and likewise for
     `/artist/1` and `/show/2` — except the 404 pages, which render twice (B2 code review #5).
5. **JSON-LD validity** — Ari, locally: paste `/show/2`'s and `/venue/3`'s JSON-LD into validator.schema.org (or the
   Rich Results Test's code tab). The cloud sandbox can't reach either.
6. **API down at runtime:** `/venue/1`, `/artist/1`, `/show/2`, `/day/2026-10-07` give B2's bare 500, with no error
   text, URL or stack in the body; `/` keeps B3's 200 with the skeleton; `/health` 200. Recorded as measured.
7. **Layout** (headless Chromium, `/opt/pw-browsers`, snippets applied): page `scrollWidth === clientWidth` at 375 and
   1280px on `/venue/1`, `/day/2026-10-07?sort=artist` and `/show/2` (the venue page embeds B3's grid, whose
   scroll-container rule must still hold inside a new parent).
8. **Browser check by Ari:** each page; the day view's mode switch and Back; earlier/later on the venue page; a show
   block's time line → the show page; screen-reader name of that link; the tab titles.

## Not doing in B4

Edit forms and the write API; socials, genres, members, instrumentation (`api-contract.md` §6); an event page; poster
and photo embedding (D4); "every upcoming show" for an artist (D2 — an A1b-era API parameter); JSON-LD on the artist
page (`arch-initial.md` §4 says "detail pages", the build plan scopes it to show and venue pages; adding the artist's
events is a few lines later if Ari wants it); `url` in JSON-LD and `metadataBase` (no site URL until the hosted phase);
"The"-insensitive alphabetising of venues (the API's order stands; "The Midway Saloon" sorts under T); previous/next
day links on `/day/[date]`; a filter header on the venue page (the requirement sends that to the calendar); component
tests (B5); Playwright; caching.

## Follow-ups for other milestones

- **A1b:** the `/shows` query must keep "`start` without `end` = the default window from `start`" (the venue and
  artist pages page that way), and should order a day by night (B3's follow-up, still open). D2's "every upcoming
  show" parameter fits there.
- **B5:** the day view's mode switch and `WindowNav` are links in Server Components, so they need no component test;
  `show-order.ts` and `calendar-window.ts` are already unit tested.
- **Hosted phase:** a site URL, then `url` in JSON-LD and `metadataBase`; poster copies in R2 would reopen D4.

## Plan review
