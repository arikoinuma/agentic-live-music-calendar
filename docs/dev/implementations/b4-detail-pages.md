# B4 — detail pages

**Status:** Done (Ari sign off) - Oct 16, 2026
**Date:** October 14, 2026
**Author model:** Claude Opus 5.5 (plan, plan-review resolution); Claude Sonnet 5.5 (revisions after Ari's D2 and D4 decisions, October 14, 2026)
**Reviewer model:** Claude Sonnet 5.5 (plan review round 1); Claude Opus 5.5 (code review round 1)
**Spec:** `docs/dev/alpha-build-plan.md` §6 B4; `docs/arch/requirements-initial.md` ("Main Views & URL Scheme",
"Calendar" → "/Day view", "Venue", "Venues", "Artist", "Artists", "Show" — including "Times after midnight", "Metro");
`docs/arch/arch-initial.md` §4 (content model and JSON-LD, filter and view state in the URL, Google Maps links);
`docs/dev/api-contract.md` §2–6; `docs/references/nextjs-style-guide.md`; Next's own
`node_modules/next/dist/docs/01-app/02-guides/json-ld.md`; `docs/dev/implementations/b2-routes-and-data-loading.md`
(B2-D1, B2-D3, B2-D4) and `b3-the-calendar.md` (B3-D1–B3-D8 and its "Follow-ups for other milestones"), both of which B4 inherits

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
| `/artist/[id]` | "lists the meta data of an artist … Artist page contains the list view of their upcoming shows" | Metadata only | Readable metadata, the photo, and **every upcoming show** as a dated list, from a new `upcoming` API parameter (D2) |
| `/venues`, `/artists` | "a simple list sorted alphabetically" | Done in B2 (alphabetical from the API, each a link) | Nothing beyond a check (D5) |
| `/day/[date]` | Three orderings — by venue by alpha (default), by venue by time, by artist by alpha; venue modes as blocks, artist mode as "a list of Artist with the associated venue and time" | One ordering (night order, B3 departure 5) | All three, chosen by a URL search param |
| `/show/[id]` | "show = constitutes a single live music event" (a main view); `arch-initial.md` §4: every event gets its own server-rendered page carrying `schema.org` Event JSON-LD | Missing (B2-D3 deferred it until something links to it) | The page with its poster image, `getShow()`, a link to it from every show block, Event JSON-LD |

Unlike B2 and B3, B4 also touches the API: D2 adds one query parameter to `GET /shows` (step 0).

What B4 is *not*: component tests (B5); edit forms ("Any user can edit the fields" is the later write phase);
socials, genres, members, instrumentation (absent from the contract on purpose, `api-contract.md` §6); an event page
(`requirements-initial.md`: "perhaps v2"); slugs in URLs (§6); a site URL / `metadataBase` (hosted phase); caching
(`arch-initial.md` §11).

### Decisions already made (earlier in this project)

- **Every route is dynamic and nothing is cached** (B2-D1). Unchanged.
- **The server owns "now"** (`api-contract.md` §3). B4 keeps the client from computing any window: the venue
  calendar asks for the server's default window and pages by sending only a `start`; the artist page asks for
  `upcoming` and sends no date at all (D2); both take every date they display from the `start`/`end` the API echoes.
- **Detail routes do not stream** (B3-D4). A `<Suspense>` boundary above a `notFound()` turns a 404 into a soft 200,
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
- **Contract changes land first, on their own** (`AGENTS.md`, "Parallel tracks"): step 0's new query parameter
  regenerates `lib/api-types.ts`, which other B-track branches depend on, so it is its own early commit (or PR, if Ari
  wants the split) and everything after it builds on it.

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
  is 28 days, so earlier = `2026-08-31`, later = `2026-10-26` (checked in Node with the polyfill). This is K2.
- **One edge, handled in the parser:** `from=9999-12-20` passes `parseDateParam`, but the API's `start + 27 days`
  overflows Python's `date` (max 9999-12-31) and answers 500. A search param must never 500 (`lib/params.ts`
  docstring), so `parseFromParam` also rejects a year above 9998.

### `upcoming`: every future show for an artist, without a client clock (D2)

"Upcoming shows" means every show from today on, however far out. The default window (28 days) can't say that, and
neither can paging: an artist with one show in three months would show an empty page with an Earlier/Later pager. So
`GET /shows` gains one boolean query parameter, and the server — which owns "now" (`api-contract.md` §3) — does the
rest:

| Request | Meaning |
|---|---|
| `/shows?artist_id=1&upcoming=true` | Every show of artist 1 dated today or later, no upper limit |
| `upcoming=true` with `start` or `end` | **422.** "From today, open-ended" contradicts an explicit range, and silently preferring one would hide a client bug |
| `upcoming=true` with neither `venue_id` nor `artist_id` | **422.** Every show in the metro with no upper bound is exactly the unbounded scan `MAX_RANGE` exists to prevent; one artist or venue bounds it by what they can play |
| `upcoming=false` or absent | Today's behaviour, byte for byte |

The response is still a `ShowListResponse`, so the contract's shape doesn't change. `start` is the server's today
(`data.START` against sample data, the metro's local date in A1b); `end` is the date of the last show returned, or
`start` when there are none, so the echoed range is always valid (`end >= start`) and the page can print "from Mon,
Sep 28, 2026". Order is unchanged (date, time, venue).

**The sample data needs one more row to show the difference** (checked against `sample_data.py`): every sample show sits
inside the 28-day default window, so against it `upcoming=true` and the default are indistinguishable and no test or
browser check could tell them apart. Step 0 appends one show outside the window — Charlie Parr at The White Squirrel
Bar on 2026-10-29 (a Thursday, offset 31 from the pinned start), 20:00, day price 10.00, as show id 26 so ids 1–25 don't
change. Its effects, worked out by hand: Charlie Parr has 5 upcoming shows (09-28, 10-07, 10-08, 10-20, 10-29) against
4 in the default window; the venue page's "Later" link from the sample window now lands on a window with one show
instead of an empty one; `calendar-months.json`'s October count goes 22 → 23. **`shows.json` must not change**: the
fixture generator currently dumps every sample show under `start=START, end=END`, and a 2026-10-29 show would sit
outside the range the fixture claims (B3's `groupCalendar` ignores such a show, but the fixture would be lying). So the
generator keeps only shows inside the window, which is what the real default response contains anyway; the fixture
stays at 25 shows and B3's tests are untouched. Only the generator and `calendar-months.json` change.

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
   B2-D3 deferred it until show blocks link to it, and B3 didn't make them links. B4 adds the page, `getShow()`, and the
   link (D3).
2. **Two [fill-in] items are proposed as [written]** (D5): the artist page (its only logic is reuse of B3 pieces and
   B4's K2) and `/venues` + `/artists` (B2 already built them to the requirement). Per `AGENTS.md`, no gap is
   invented for them.
3. **Added, not in the build plan's B4 list:** paging for the venue calendar (`?from=`, D1); readable labels for
   the enum fields; the venue's Google Maps link (`arch-initial.md` §4 — it was never assigned to a milestone); real
   page titles through `generateMetadata` (D7).
4. **One line of the [written] JSON-LD item becomes a `TODO(Ari)` gap** (`eventDateTime`, K1) — D8, accepted.
5. **B4 is no longer frontend-only (D2).** `GET /shows?upcoming=true`, one later sample show and a fixture-generator
   filter are Python work in a frontend milestone (step 0). `api-types.ts` and `calendar-months.json` regenerate.
6. **The artist page is not paged (D2)**, so the build plan's "upcoming shows as a list" is met literally, and K2
   serves only the venue page.
7. **Images are rendered, not linked (D4)**, through one `RemoteImage` component holding the app's only
   `@next/next/no-img-element` exception. The B3 show block still has no poster.

## Decisions for Ari

**Settled by Ari, October 14, 2026 (D9, below, is new and still open).** D1, D3, D5, D6, D7 and D8 are accepted as recommended. **D2 and D4 take the
alternative** and are rewritten below as decided; their superseded recommendations are summarised in one line each so
the reasoning stays on record. The plan is adjusted throughout (Departures 5–7; the "`upcoming`" section; step 0; the
`RemoteImage` component; the artist page, tests and verification). Status stays *Awaiting approval*: settling the
decisions is not the approval gate.

- **D1 — The venue page's calendar pages earlier/later through `?from=YYYY-MM-DD`. Decided: approved.** The requirement asks
  for "back and forth to past or future with that exact calendar"; the mechanism is the "Paging" section above. The
  page also gets an "Open in the calendar" link to `/?venue=N` — the requirement's "anything other than [paging] … they
  have to go to a calendar view page". No filter header on the venue page. *Alternative:* no paging in B4 (the default
  four weeks only) and the requirement's back-and-forth deferred.
- **D2 — The artist page lists every upcoming show, from a new `upcoming` parameter on `GET /shows`. Decided: the
  alternative (Ari, October 14, 2026).** "Upcoming shows" means every future show, and the default four weeks (even
  with paging) would show an artist with one show three months out as having none. The API parameter keeps the client
  free of dates, because the server decides what "today" is. The design, its two 422 guards, and the extra sample row
  that makes it testable are in "`upcoming`" above; the work is step 0. *Superseded recommendation:* the default window
  with the same Earlier/Later paging as the venue page, no contract change, leaving "every upcoming show" to A1b.
  Consequence to know: B4 now has a Python half, and A1b must reproduce the parameter (and both guards) on the real
  query (Follow-ups).
- **D3 — `/show/[id]` exists, and each show block's time line becomes its link. Decided: approved.** The block already holds
  venue and artist links, which can't nest inside a block-wide link (B3 step 4). The time line ("8:00 PM – 11:30 PM") is
  the one line that is about the show itself, so it becomes `<Link href="/show/N">` with a visually hidden
  ", show details" so its accessible name says where it goes. *Alternative:* a separate small "Details" link at the
  bottom of each block (one more line in every block, 25 on `/`).
- **D4 — Posters and photos are rendered as plain `<img>` elements, through one component. Decided: the alternative
  (Ari, October 14, 2026).** `image_url` and `photo_url` point at arbitrary venue and artist hosts. `RemoteImage`
  (`app/_components/remote-image.tsx`) renders `<img loading="lazy" decoding="async" referrerPolicy="no-referrer">`,
  after `httpUrlOrNull` has accepted the URL (anything else renders nothing). It carries **the app's only**
  `eslint-disable-next-line @next/next/no-img-element`, with a comment saying why `next/image` isn't used: it needs
  an open-ended `images.remotePatterns` and a width and height the scraped data doesn't have. *Checked:* under the
  repo's `--max-warnings 0` a bare `<img>` fails lint (one warning), and the same element under that single
  disable comment passes. Used for the show page's poster, the venue's photo and the artist's photo. **The show block
  stays image-free** (B3: its focus is names, and 25 remote images on `/` would be 25 third-party requests).
  Accepted costs, stated so nobody rediscovers them: every reader's browser contacts the image's host (that host sees
  their IP; `no-referrer` at least hides which page they were on); a dead link shows the browser's broken-image
  marker with the `alt` text, because the cosmetic fix (`onError`) needs a Client Component that isn't worth adding;
  no dimensions are known, so the image reserves no space and the layout can shift as it loads (a `max-h-80 w-auto
  max-w-full object-contain` cap stops a huge image breaking the layout). The sample data's image URLs are
  `example.com` placeholders, so the browser check will show `alt` text, not pictures. Copies served from our own
  storage (R2, hosted phase) would replace the remote `src` in this one component. JSON-LD still carries `image`.
  *Superseded recommendation:* "Poster" and "Photo" as plain links.
- **D5 — Re-mark two [fill-in] items [written]. Decided: approved.** Per `AGENTS.md` ("If no line in a [fill-in] task meets that bar, say
  so … propose re-marking it [written] — don't invent a gap"). *Artist page:* the fetch → 404 flow was B2-K5, the
  list is B3's `ShowBlock` sorted by the existing `nightSortKey`, the paging is K2; nothing new is left to type.
  *`/venues` and `/artists`:* B2 already built "a simple list sorted alphabetically" (the API sorts; each name links);
  B4 changes no code there unless the browser check finds a reason.
- **D6 — Day view mode is `?sort=` with values `time` and `artist`; the default (`venue`) is the bare URL.
  Decided: approved.** One canonical URL per view, like the calendar's filters (`/day/2026-10-07` is venue order;
  `?sort=venue` is accepted and treated as the default, but never written). The switch is three plain `<Link>`s with
  `aria-current="page"` on the active one — no Client Component, no JavaScript: changing the view is a navigation and
  the server renders it (`arch-initial.md` §4, "the current view"). An unknown value is ignored, never a 404 (a
  search param is not part of the resource's identity). *Alternative:* `?view=`; or a select (would need a Client
  Component for no gain).
- **D7 — Real page titles via `generateMetadata`. Decided: approved.** The detail pages exist for search and sharing
  (`arch-initial.md` §4), and every tab currently reads "Venue · …" or "Artist · …". `generateMetadata` and the page both
  need the record, so `getVenue`, `getArtist` and `getShow` are wrapped in React `cache()` (their argument is a number,
  so `cache()` keys correctly — B2 left them unwrapped only because nothing called them twice). *Alternative:* keep the
  static titles.
- **D8 — One line of the [written] JSON-LD item becomes a gap: `eventDateTime` is K1. Decided: approved (changed
  after PR1-2).** The build plan marks JSON-LD [written], and the rest of it stays so. But its date line is the most
  lesson-shaped Temporal line in B4 — the second and last place the metro's zone matters, and the after-midnight rule
  meeting a real instant — while the plan's original K1 (`Promise.all` on the venue page) repeats what B3's
  `CalendarBody` already teaches and has a Check that passes whichever way it's written. So the venue page's loading is
  written complete and the gap moves here. Changing a marking is Ari's call, hence a decision. *Alternative:* keep the
  marking — JSON-LD fully [written], and B4 has three gaps (K2–K4).

- **D9 — Settled in effect (raised by CR1-2): how wide is K1? Recommended: keep it as built.** *Ari filled K1 as scaffolded (the narrow gap), so "keep" is what happened; see Implementation log round 3.*  D8 approved a gap with
  *two* ideas: the after-midnight date shift and the zone/offset. While building I made the shift a written helper
  (`instantDay`, `lib/json-ld.ts`) because the unknown-zone fallback needs it too, which left K1 (`withOffset`) as one
  line carrying one idea (attach the zone; the offset depends on the date). That narrowing was my call, not yours (Implementation
  log, departure 1). *Keep:* the shift is the same `isAfterMidnight` + `add({ days: 1 })` that B3-K2 and
  `formatShowTime` already taught, so the new lesson is the zone line. *Widen:* make `instantDay`'s one-line body part of K1
  (same TODO block, one more line; its Check and the tests are unchanged, since the fallback path would simply stay red
  with the rest of K1). Say which and I'll adjust the scaffold; nothing else depends on it.

## Test approach (written first, watched fail, then made green)

Same shape as B2 and B3: logic lives in pure functions in `lib/` and is unit tested under Vitest's node environment;
async Server Components are **not** unit tested (style guide, Testing); pages are checked by build output, HTTP
responses, a JSON-LD parse and Ari's browser check (Verification). Expected values are worked out by hand from the
requirements, `lib/fixtures/shows.json` or a calendar, never read back from the code under test. Each test says where
its numbers come from.

**The fixture day.** Most expectations use `shows.json`'s 2026-10-07 (a Wednesday), which B3-D5 built to be hard:

| id | Venue | Start | Lineup (per-act time) |
|---|---|---|---|
| 8 | The Terminal Bar | 21:00 | Jaedyn James, Tarnation, Beasthead |
| 22 | The White Squirrel Bar | 18:00 | Lanue |
| 23 | The White Squirrel Bar | 22:00 (ends 00:30) | Nooky Jones (22:00), Pert Near Sandstone (23:15) |
| 24 | Zhora Darling | 20:00 | Charlie Parr |
| 25 | The Midway Saloon | 01:00 | Dead Man Winter |

### 0. Python: `GET /shows?upcoming=true` (`apps/api/app/tests/test_routers.py`) — D2

Written first and watched fail (the parameter doesn't exist: FastAPI ignores an unknown query parameter, so the first
assertions fail on the *content* — no 2026-10-29 show — which is the right red). The sample data after the new row
(step 0) is the source of every expectation; Charlie Parr is artist 1 and his shows are listed in the "`upcoming`"
section.
- `/shows?artist_id=1&upcoming=true` → dates `["2026-09-28", "2026-10-07", "2026-10-08", "2026-10-20", "2026-10-29"]`,
  `start` `"2026-09-28"`, `end` `"2026-10-29"`. **Contrast in the same test:** `/shows?artist_id=1` (no `upcoming`)
  returns the first four and *not* 2026-10-29, `end` `"2026-10-25"` — the one-show difference is the whole feature.
- **From the server's today:** with `data.START` monkeypatched to `2026-10-08` (the router reads it at call time),
  `upcoming` for artist 1 → `["2026-10-08", "2026-10-20", "2026-10-29"]` and `start == "2026-10-08"`: shows before
  today are excluded.
- **No matches:** `artist_id=9999&upcoming=true` → 200, `shows == []`, `start == end == "2026-09-28"` (a valid range,
  not an error).
- **Combines like any filter:** `venue_id=3&artist_id=1&upcoming=true` → `["2026-10-07", "2026-10-20"]` (Zhora Darling
  is venue 3; the other three of Charlie Parr's shows are at venue 1). `venue_id=1&upcoming=true` includes 2026-10-29
  and nothing dated before 2026-09-28.
- **Rejected with 422** (parametrized): `upcoming=true` alone; `artist_id=1&upcoming=true&start=2026-10-01`;
  `artist_id=1&upcoming=true&end=2026-11-30`. The test names why: an explicit range contradicts "from today", and no
  filter means the unbounded scan `MAX_RANGE` guards against.
- `upcoming=false` with `artist_id=1` equals the request without it (4 shows), so a client sending an explicit false
  changes nothing.
- **OpenAPI:** the `GET /shows` operation lists `upcoming` among its parameters — the guard that the parameter reaches
  `api-types.ts` (the same reasoning as `test_openapi_exposes_the_response_schemas`).
- The existing router tests are expected to pass unchanged (they filter relationally or by explicit range; the new row
  is outside the default window), confirmed by running them. `make contract-check` after `make types` and `make
  fixtures`: `api-types.ts` gains the parameter, `calendar-months.json` October 22 → 23, `shows.json` unchanged.

### 1. `lib/show-order.test.ts` (new) — the day view's three orderings

`venueOrder` and `timeOrder` (comparators over `ShowSummary`) — **K4**:
- By venue (default) on the fixture day → ids `[25, 8, 22, 23, 24]`: The Midway Saloon, The Terminal Bar, The White
  Squirrel Bar (18:00 before 22:00), Zhora Darling. Alphabetical by the full name, as the API sorts venues (no
  "The"-stripping; see Not doing).
- By time → `[22, 24, 8, 23, 25]`: 18:00, 20:00, 21:00, 22:00, then the 1:00 AM show **last**, not first (clock order
  would put it first — the night rule).
- Ties (hand-built): two shows at one venue at the same time keep their input order (stable sort); two 20:00 shows at
  different venues sort by venue name in time mode; an untimed show is last within its venue in venue mode and last of
  all in time mode.

`artistRows(shows)` — **K3**:
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

### 2. `lib/calendar-window.test.ts` (new) — paging the venue page's calendar

`windowLinks(start, end)` — **K2**:
- `("2026-09-28", "2026-10-25")` (the sample API's default window) → `{ earlier: "2026-08-31", later: "2026-10-26" }`.
  Hand-worked: 28 days inclusive; 28 days before Sep 28 is Aug 31 (Sep has 30 days: Sep 28 − 27 = Sep 1, − 1 more = Aug
  31).
- Leap year: `("2028-02-01", "2028-02-28")` → `later: "2028-02-29"`, `earlier: "2028-01-04"`.
- Year end: `("2026-12-20", "2027-01-16")` → `later: "2027-01-17"`, `earlier: "2026-11-22"`.
- One-day range `("2026-10-07", "2026-10-07")` → `earlier: "2026-10-06"`, `later: "2026-10-08"` (the length comes from
  the range, not a constant 28).

`windowHref(path, from)` (written): `("/venue/3", "2026-10-26")` → `/venue/3?from=2026-10-26`; `("/venue/3", null)` →
`/venue/3` (the server's default window).
`windowNavLinks(path, start, end)` (written, around K2; PR1-5): the hrefs `WindowNav` renders, each direction
`null` when its date would not survive `parseFromParam` — so the URL parser is the single bound rule, and a link that
would silently reset to the default window is simply not shown. `("/venue/3", "9999-12-01", "9999-12-28")` →
`later: null`; `("/venue/3", "0001-01-01", "0001-01-28")` → `earlier: null`; the sample window → both hrefs.

### 3. `lib/params.test.ts` (cases added; existing cases unmodified)

`parseFromParam(value)` (written): `"2026-10-26"` → that string; `undefined`, `""`, `"garbage"`, `"20261026"`,
`"2026-02-30"` → `null` (same strictness as `parseDateParam`, which it calls); `["2026-10-26", "x"]` → the first
valid; `"9999-12-20"` → `null` and `"9998-12-31"` → valid — the API overflow above.

### 4. `lib/json-ld.test.ts` (new)

`eventDateTime(date, time, timeZone)` — **K1** (D8): every row of the "JSON-LD dates" table above, offsets worked
out from US DST rules (2026: CDT until 2:00 AM Sunday November 1, then CST −06:00; 2027 spring-forward is March 14),
not from the code. Plus the **spring-forward gap** (PR1-1d): listed 2027-03-13 at 02:30 → after midnight, so
2027-03-14 02:30, a wall time that doesn't exist in Chicago; Temporal's default `compatible` moves it forward an hour →
`2027-03-14T03:30:00-05:00` (checked with the polyfill). Accepted and pinned: a show listed at a nonexistent time starts
when the clocks allow, and nothing throws.
`eventEndDateTime(date, start, end, timeZone)`: `22:00`–`00:30` on 2026-10-07 → `2026-10-08T00:30:00-05:00`;
`18:00`–`23:00` → same day; `21:00`–`06:00` (end before start, not after midnight) → next day; `01:00`–`03:00` →
both next day (`2026-10-08T03:00:00-05:00`); end null → `null` (the key is omitted). **Start null, end present**
(PR1-1b): there is no start to compare against, so only the after-midnight rule applies — `00:30` → next day,
`23:00` → same day; never a throw or an `"undefined"` in the string.
`showJsonLd(show, { venue, timeZone })`:
- `@context` `https://schema.org`, `@type` `MusicEvent`, `eventStatus` `https://schema.org/EventScheduled`,
  `eventAttendanceMode` `https://schema.org/OfflineEventAttendanceMode`.
- `name`: the lineup names in performance order, joined with ", " (`show-detail.json`: "Nooky Jones, Beasthead"); an
  empty lineup → "Live music at <venue name>".
- `performer`: one `{ "@type": "MusicGroup", name }` per act. `location`: `{ "@type": "MusicVenue", name }`, plus
  `address` only when the venue detail has one (`VenueDetail` id 3's address). **`venue: null`** (PR1-1c — the show
  page allows it when the venue lookup misses): `location.name` falls back to `show.venue.name`, no `address` key.
- **`offers`, the contract's rule:** `free_admission: true` → one offer with `price: "0"`, `priceCurrency: "USD"`;
  `"18.00"` / `"22.00"` → two offers carrying those **strings** (no `parseFloat`), named "Advance" and "Door"; a lone
  day price → one offer with no name; **a lone advance price** (PR1-1a) → one offer named "Advance", matching
  `formatAdmission`'s "$15 adv" so the page and the JSON-LD say the same thing; **all three null → no `offers` key at all** (asserted with `not.toHaveProperty`),
  never a price of 0.
- `image` present only when `image_url` is an http(s) URL (`httpUrlOrNull`, §5 — PR1-3); `javascript:…` or
  `data:…` → no `image` key.
`jsonLdScriptContent(data)`: a name containing `</script><script>alert(1)</script>` serialises with **no `<`
character** in the output, and `JSON.parse` of the output gives the original name back (the escape is lossless).
**Why this matters here:** show and artist names are scraped from venue websites by a model — exactly the untrusted
text Next's JSON-LD guide warns about.

### 5. `lib/detail-format.test.ts` (new)

`mapsUrl(address)`: `"1010 Washington Ave N, Minneapolis, MN 55401"` →
`https://www.google.com/maps/search/?api=1&query=1010%20Washington%20Ave%20N%2C%20Minneapolis%2C%20MN%2055401`
(`arch-initial.md` §4's format; `&` and `#` in an address are encoded, so they can't end the parameter).
`httpUrlOrNull(url)` (PR1-3): `https://x.example/a` and `http://x.example` → unchanged; `javascript:alert(1)`,
`data:image/png;base64,AAAA`, `file:///etc/passwd`, `""`, `"garbage"`, `null`, `undefined` → `null`. Every external
link the detail pages render from data (website, calendar URL, Source), every image (`RemoteImage`: poster, venue and
artist photos) and the JSON-LD `image` go through it; a rejected URL renders no link or image. React 19 already blocks `javascript:` in `href`, but not `data:` or
`file:`, and nothing guards JSON-LD — one rule for all of them is simpler than reasoning per sink.
Label maps (`AGE_LABELS`, `SETTING_LABELS`, …): one spot-check each (`twenty_one_plus` → "21+", `all_ages` → "All
ages", `both_other` → "Original and covers"). Their completeness is a compile-time guarantee: each is a
`Record<Enum, string>`, so a new enum value from `make types` is a type error, not a test failure.

### 6. `lib/api.test.ts` (tests added)

- `getShow(2)` calls `/shows/2` and returns `show-detail.json` unchanged; a 404 → `null`.
- `getShows({ start: "2026-10-26", venueIds: [3] })` sends `start` and `venue_id` and **no `end`** (the paging contract
  above; `apiUrl` omits undefined values, pinned here so a later "both or neither" refactor can't silently break it).
- `getShows({ artistIds: [1], upcoming: true })` sends `artist_id=1&upcoming=true` and **no `start` or `end`** (D2);
  `upcoming: false` and `upcoming` absent both omit the key, so the default URL is unchanged.

### What is *not* covered, stated plainly

- Rendered output of the four detail pages (async Server Components): build, HTTP checks, a JSON-LD parse of the served
  HTML, and Ari's browser check.
- That Google accepts the JSON-LD: the Rich Results Test and validator.schema.org need a public URL or a pasted
  snippet, and the cloud sandbox has no route to them. Verification 5 pastes the served JSON into the validator from
  Ari's machine.
- `RemoteImage`'s markup (`loading`, `referrerPolicy`, the `alt` text) and the broken-image appearance: Verification 4
  greps the served HTML for the attributes; the rest is Ari's browser check. Its one decision (which URLs render) is
  `httpUrlOrNull`, which is unit tested.
- `cache()` de-duplication of `getVenue`/`getArtist`/`getShow` between `generateMetadata` and the page: one request
  per page load in the API log (Verification 4), not a unit test (`cache()` only works inside a server render).

### Tests-first caveat

As in B2 and B3: stubs that export the functions and throw come first, so the red state is assertion failures, not
import errors. The gap tests (K1–K4) stay red at handoff.

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

Four blocks (D8): the venue page → B; the day view → C and D; the JSON-LD item → A (one line of a [written] item,
D8). Each item stays inside `AGENTS.md`'s "1–3 spots". **All four are pure functions with unit tests**, so they can
be filled in any order; suggested **K1, K2, K3, K4**. The pages render errors while their gap is open (`/show/[id]` and
`/venue/[id]` need A for JSON-LD, `/venue/[id]` needs B for paging, `/day` needs C and D), so the
browser check comes after all four.

*Replaced after PR1-2:* the original K1 (`Promise.all` on the venue page) repeated B3's `CalendarBody`
lesson and had a Check that couldn't fail. The venue page's loading is now written complete (step 5).

- **K1 — `eventDateTime`, `lib/json-ld.ts`** (step 1; the JSON-LD item, D8).
  *Lesson:* the **second and last place the metro's zone matters** (B3's `metroToday` was the first). A show's date and
  time are wall-clock values with no zone, which is right for display and wrong for JSON-LD: `startDate` names a real
  instant, so it needs the venue's UTC offset — and the offset depends on the date (−05:00 in October, −06:00 in
  December), so it can't be a constant. Before attaching the zone, the after-midnight rule moves the *calendar* date:
  a 1:00 AM show listed under Wednesday happens on Thursday. `toZonedDateTime` attaches the zone; `toString({
  timeZoneName: "never" })` prints the offset without the `[America/Chicago]` suffix schema.org doesn't expect.
  *Code:*
  ```
  const t = Temporal.PlainTime.from(time);
  const day = Temporal.PlainDate.from(date).add({ days: isAfterMidnight(t) ? 1 : 0 });
  return day.toZonedDateTime({ timeZone, plainTime: t }).toString({ timeZoneName: "never" });
  ```
  (written around it: the untimed → bare date branch, the null-zone branch, and the `RangeError` fallback.)
  *Check:* `pnpm --filter calendar test json-ld` — the 01:00 row (`2026-10-08T01:00:00-05:00`) and the December row
  (`-06:00`). Likeliest mistakes: dropping the `add` (the 1:00 AM show dated the night before — a full day early), a
  hard-coded `-05:00`, or `.toString()` with no options (`…-05:00[America/Chicago]`).
- **K2 — `windowLinks`, `lib/calendar-window.ts`** (step 2; the venue page item).
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
- **K3 — `artistRows`, `lib/show-order.ts`** (step 3; the day view item).
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
- **K4 — the two venue-mode comparators, `lib/show-order.ts`** (step 3; the day view item).
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

### 0. The `upcoming` parameter and the later sample show (written, Python) — D2

Lands **first and on its own** (see "Contract changes land first"): green under `make check` before any frontend step.
- Tests first (§0): written, run, confirmed failing for the right reason.
- `apps/api/app/routers/shows.py`: `upcoming: bool = False` on `list_shows`. When true: 422 if `start` or `end` is given,
  422 if neither `venue_id` nor `artist_id` is, then `start = data.START` (the "TEMPORARY IMPLEMENTATION" comment's
  pinned today), keep shows dated `>= start`, apply the venue/artist filters as before, and set `end` to the last
  returned date or `start` when none. Everything else about the route — signature order, the return annotation, the
  default window, `MAX_RANGE` — is unchanged. Docstring and comments say what the 422s protect and cite
  `api-contract.md` §2. A scalar `bool` needs no `Query()` marker (unlike the list parameters beside it).
- `apps/api/app/sample_data.py`: append the one row described in "`upcoming`" to `_SHOW_ROWS` (id 26), with a comment
  naming D2 and saying why it exists (every other show is inside the default window).
- `apps/api/scripts/generate_fixtures.py`: `shows.json` is built from `[s for s in data.SHOWS if data.START <= s.date <=
  data.END]`, with a comment: the fixture is a default-window response, so it holds only default-window shows.
- `make types` (adds `upcoming` to `GET /shows` in `lib/api-types.ts`), `make fixtures` (`calendar-months.json` only),
  `make contract-check` clean. **Expected, not yet checked:** that openapi-typescript emits the parameter as
  `upcoming?: boolean` on the operation; step 0's author confirms it and records the actual type in the log.
- `docs/dev/api-contract.md` §2 (Filtering: the `upcoming` paragraph with its two 422s and the echoed `start`/`end`) and
  §8 (`shows.json` is the default window only; the sample has 26 shows, 25 in the fixture).
- This is [written], not [fill-in]: it is mechanical, and the only judgement in it (the two guards) is decided above.

### 1. Pure helpers (written) — `lib/params.ts`, `lib/detail-format.ts`, `lib/json-ld.ts`

- Tests first (§3, §4, §5).
- `parseFromParam` in `lib/params.ts`, next to `parseMonthParam` (same "first valid of a repeated key" rule, calls
  `parseDateParam`, adds the year ≤ 9998 check with a comment naming the API overflow).
- `lib/detail-format.ts`: `httpUrlOrNull` (PR1-3); `mapsUrl`; `Record<Enum, string>` label maps for age restriction, setting, seating, venue
  type, artist format and repertoire (from `app/enums.py`); `alcoholLabel(bool)`. Module docstring: why the maps are
  `Record`s (exhaustive by type).
- `lib/json-ld.ts`: `eventDateTime` (its core line is **K1**, D8), `eventEndDateTime`, `showJsonLd`,
  `jsonLdScriptContent`. Imports
  `isAfterMidnight` from `lib/dates.ts` (the rule's one home) and `orderedLineup` from `lib/show-format.ts`. Catches
  only `RangeError` from an unknown zone, as `metroTodayOrNull` does, and falls back to the no-offset form. Typed with a
  small local `JsonLdEvent` type, not the `schema-dts` package (one type, no new dependency). Docstring: why `<` is
  escaped (scraped text inside a `<script>`), why the offset, why no `offers` when nothing is stated, and that `url` is
  omitted until a site URL exists (hosted phase).

### 2. Window paging (fill-in: K2) — `lib/calendar-window.ts`, `app/_components/window-nav.tsx`

- Tests first (§2). `windowLinks` (K2) and `windowHref` (written).
- `WindowNav({ path, start, end, isDefault })` — a Server Component: "← Earlier" and "Later →" links from
  `windowNavLinks` (each omitted when `null`), the range they sit between **with years** ("Mon, Sep 28, 2026 – Sun,
  Oct 25, 2026", `formatDayHeading` plus the year, as `/day/[date]` already prints it — PR1-4: a December-to-January
  window must not be ambiguous), and, when the page isn't on the default window, "Back to upcoming dates"
  (`windowHref(path, null)`; the text names no length, since the length is the server's — PR1-4). Plain links, no
  JavaScript. `rel="nofollow"` on earlier/later, so crawlers don't walk an unbounded chain of empty windows.

### 3. The day view's orderings (fill-in: K3, K4) — `lib/show-order.ts`

- Tests first (§1). `byVenueName`, `parseDaySort`, `dayHref`, `inNightOrder` written; `venueOrder` and `timeOrder`
  (K4) and `artistRows` (K3) scaffolded.
- `DaySort = "venue" | "time" | "artist"`. The module is pure and Temporal-free itself, but imports `nightSortKey` from
  `lib/dates.ts`, so it is server-side in practice (stated in its docstring, like `lib/calendar.ts`).

### 4. The API client (written) — `lib/api.ts`

- Tests first (§6). Add `getShow(id)` (`getOrNull`, `/shows/{id}`) to `ApiClient`, `createApiClient` and the exports.
- Wrap `getVenue`, `getArtist` and `getShow` in `cache()` (D7) and rewrite the comment above `getMetro` that says only
  it is wrapped: they take a number, which `cache()` compares by value, and `generateMetadata` plus the page now call
  them twice per render. `getShows` stays unwrapped (object argument).
- `ShowsQuery` (`lib/params.ts`) gains `upcoming?: boolean`; `getShows` sends it as `upcoming: query.upcoming ?
  "true" : undefined` (`QueryValue` has no boolean, and `undefined` omits the key). Correct that type's comment
  ("either both present or both absent"): a `start` alone is now sent on purpose and the server fills `end`; and
  `upcoming` is exclusive with `start`/`end`, which the **server** enforces with a 422 — the type doesn't try to repeat
  the rule. `toShowsQuery` is unchanged: the home calendar never asks for `upcoming`.

### 5. `/venue/[id]` (fill-in: K2, in step 2)

- `VenuePage(props)` awaits `params` **and** `searchParams`; `parseIdParam` → `notFound()`; `parseFromParam`; then one
  `Promise.all` over `getVenue`, `getShows({ venueIds: [id], start: from ?? undefined })` and `getMetroOrNull`, and the
  404 check **after** it (a missing venue costs one harmless empty shows request). Written complete; the comment points
  at B3's `CalendarBody` for the no-waterfall reasoning rather than repeating it (PR1-2). No `<Suspense>`, so
  `notFound()` keeps its real 404 (B3-D4).
- Above the calendar: name; the photo as a `RemoteImage` (D4, step 9; nothing when there is no photo or the URL is rejected); metadata as today's `<dl>`, now through the label maps, with the
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

### 6. `/artist/[id]` (written — D5, D2)

- Same flow as the venue page (complete, not a gap), but simpler: `params` only — **no `searchParams`**, so a stray
  `?from=` on this page is ignored (a comment says so) — then `Promise.all` over `getArtist(id)` and
  `getShows({ artistIds: [id], upcoming: true })`, then `notFound()` for a `null` artist.
- Metadata through the label maps; the photo as a `RemoteImage` (D4); website.
- "Upcoming shows" heading and a muted line "Everything listed from Mon, Sep 28, 2026 on" — the **server's** `start`,
  formatted (`formatDayHeading` plus the year), so "the server owns now" is visible. Then an `<ol>` in `inNightOrder`:
  each item a date heading (`formatDayHeading` + year) over a `ShowBlock` with `withVenue` — B3's block, so time,
  venue, full lineup and price read the same as on `/`. No cap and no pager: the list is bounded by one artist's
  bookings, and the response envelope leaves room for a cursor if that ever stops being true (`api-contract.md` §2).
- Empty: "No upcoming shows listed." No `WindowNav` here (it serves the venue page only).
- With the sample data the list holds 5 shows, one of them untimed (2026-10-08), which exercises the show block's
  "Details" link.
- No JSON-LD (the build plan scopes it to show and venue pages; see Not doing). `generateMetadata`: title = name.

### 7. `/day/[date]` (fill-in: K3, K4)

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

### 8. `/show/[id]` (written — the JSON-LD item, D3; its date line is K1 in step 1)

- New `app/show/[id]/page.tsx`; run `pnpm check-types` after adding it (`next typegen` makes `PageProps<"/show/[id]">`).
- `parseIdParam` → `notFound()`; `Promise.all([getShow(id), getMetroOrNull()])` → `notFound()` on `null`; then
  `getVenue(show.venue.id)` for the address. That second request **is** a dependent one (the venue id comes from the
  show) — a comment says so, so it isn't mistaken for a needless waterfall. A `null` venue (deleted between the two
  calls) renders the page without an address rather than a 404.
- Content: the date with year (`formatDayHeading`) and time line (`formatShowTime` + `formatClockTime` end, as the
  block); venue link and, when known, address as a Maps link; the lineup in `orderedLineup` with per-act times; the
  admission line (`formatAdmission`, nothing when `null`); the four resolved fields through the label maps (age,
  alcohol, setting, seating — `api-contract.md` §5: the page doesn't say whether they came from the venue); the event
  name as plain text when present (no event page, v2); the poster as a `RemoteImage` (D4), alt text "Poster for <lineup>", above the details, nothing when there is none; **"Source: <venue's page>"** linking
  `original_url` — "part of making the agent's work visible to the reader" (`schemas.py`).
- `<JsonLd data={showJsonLd(show, { venue, timeZone: metro?.timezone ?? null })} />`.
- `generateMetadata`: title "<lineup> at <venue>, <date>".

### 9. JSON-LD component, `RemoteImage` and the show block link (written)

- `app/_components/json-ld.tsx`: `JsonLd({ data })` renders
  `<script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScriptContent(data) }} />` — Next's
  recommended form (a native `<script>`, not `next/script`; its JSON-LD guide). The only `dangerouslySetInnerHTML` in
  the app; the comment says why it's safe here and points at the test.
- `app/_components/remote-image.tsx` (D4): `RemoteImage({ src, alt, className })` — `src` is `string | null | undefined`;
  `httpUrlOrNull(src)` first, `null` → renders nothing; otherwise `<img src alt loading="lazy" decoding="async"
  referrerPolicy="no-referrer" className={...}>` with the default cap `max-h-80 w-auto max-w-full rounded-md border
  object-contain` merged with any `className`. The component's comment carries the whole D4 reasoning in a few lines
  and sits directly under the app's one `eslint-disable-next-line @next/next/no-img-element` (the rule's name and a
  `--` reason on the same line). Verification 2 greps that there is exactly one.
- `app/_components/show-block.tsx`: when the show has a time, the time line becomes `<Link href={`/show/${show.id}`}>`
  with `<span className="sr-only">, show details</span>` (D3). When it has none, "Time not listed" stays plain text and
  a separate "Details" link follows it (PR1-6: "Time not listed, show details" is a statement, not a destination).
  The link gets `inline-block py-1` (a taller tap target without moving the layout much — PR1-6). Update its docstring's "Deliberately NOT here" list: the
  `/show/[id]` bullet goes; the poster bullet stays true (the block shows no image) and now points at D4 ("the show page
  renders the poster").

### 10. Docs and bookkeeping (written)

- `alpha-build-plan.md` B4: point at this file, tick the boxes, apply departures 1–3 and D5's re-markings.
- `apps/calendar/AGENTS.md`: the `?from=` paging (venue page) and `?sort=` conventions under "Where data and URL state
  live"; the artist page's `upcoming` request; `RemoteImage` as the one place remote images are rendered (and why the
  lint exception lives only there); the new `lib/` modules; `/show/[id]` and the cached getters; "the venue, artist and list pages are still deliberately
  plain until B4" becomes past tense; JSON-LD's escaping rule.
- `docs/dev/api-contract.md` §2: the `/shows` row already names the embedded calendars; under Filtering add that
  `start` without `end` means "the default window from `start`" (B4 relies on it) and the `upcoming` paragraph (step 0).
- `alpha-build-plan.md`: also record Departures 5–7 (the API change, the unpaged artist page, rendered images).
- `docs/dev/notes.md`: only real surprises.

## Critical files

- New (Python side, step 0): none. Modified: `apps/api/app/routers/shows.py`, `apps/api/app/sample_data.py`,
  `apps/api/scripts/generate_fixtures.py`, `apps/api/app/tests/test_routers.py`; generated (never by hand):
  `apps/calendar/lib/api-types.ts`, `apps/calendar/lib/fixtures/calendar-months.json`
- New: `apps/calendar/lib/{show-order,calendar-window,json-ld,detail-format}.ts` + `.test.ts` for each;
  `apps/calendar/lib/todo.ts` (temporary, deleted with the last gap); `apps/calendar/app/show/[id]/page.tsx`;
  `apps/calendar/app/_components/{window-nav,json-ld,remote-image}.tsx`
- Modified: `apps/calendar/app/{venue/[id],artist/[id],day/[date]}/page.tsx`,
  `apps/calendar/app/_components/show-block.tsx`, `apps/calendar/lib/{api,params}.ts` and
  `apps/calendar/lib/{api,params}.test.ts`, docs in step 10
- Reused as-is: `lib/{dates,calendar,show-format,calendar-href,metro,types}.ts`,
  `app/_components/calendar-grid.tsx`, `app/{venues,artists}/page.tsx` (D5), `app/{layout,error,not-found}.tsx`
- Not touched: `apps/api/app/schemas.py` (no new or changed response shape — D2 adds a query parameter only), the other
  fixtures (`shows.json` stays byte-identical)

## Verification

1. **Tests first.** New test files and stubs written, run, and confirmed red for the right reason (assertions, not
   imports) before implementing.
2. **`make check`** green with the snippets applied (ruff, mypy, eslint, `next typegen` + tsc, pytest, Vitest,
   contract-check). Step 0 is checked on its own first: `make check` green before any frontend step, `make types` /
   `make fixtures` / `make contract-check` clean, and `git diff` of the fixtures showing only `calendar-months.json`
   (October 22 → 23). `grep -rn "no-img-element" apps/calendar/app` finds exactly one line (D4). At handoff it is red
   only on the gap tests (K1–K4) — the log lists exactly which. Snippets applied
   in a scratch copy and restored byte for byte (checksums), as in B3.
3. **Build with the API unreachable** (`API_BASE_URL=http://127.0.0.1:9 pnpm build`): succeeds; every data route,
   `/show/[id]` and `/_not-found` are `ƒ`. Bundle check unchanged from B3 (`grep -rl "Do not use built-in arithmetic
   operators with" .next/static` finds nothing): B4 adds no Client Component.
4. **HTTP matrix** against `next start` with the API up (snippets applied), expected values from the fixture:
   - **The parameter itself**, against `uvicorn`: `/shows?artist_id=1&upcoming=true` [200; 5 shows, last
     2026-10-29, `end` 2026-10-29]; `/shows?artist_id=1` [4 shows]; `/shows?upcoming=true` and
     `/shows?artist_id=1&upcoming=true&start=2026-10-01` [both 422].
   - `/venue/1` [200; 8 show blocks; "Earlier" → `?from=2026-08-31`, "Later" → `?from=2026-10-26`; one JSON-LD
     script holding 8 events]; `/venue/3` [200; 6 blocks; events carry Zhora Darling's address];
     `/venue/1?from=2026-10-26` [200; 1 show block (Charlie Parr, 2026-10-29, now that D2's row exists); "Earlier" →
     `?from=2026-09-28`, "Later" → `?from=2026-11-23`; a "Back to upcoming dates" link; JSON-LD with 1 event];
     `/venue/1?from=2026-11-23` [200; "No shows listed"; the back link; no JSON-LD];
     `/venue/1?from=garbage` and `/venue/1?from=9999-12-20` [200; the default window]; `/venue/9999`, `/venue/abc`
     [404].
   - `/artist/1` [200; Charlie Parr's **5** shows in date order, ending 2026-10-29 at The White Squirrel Bar; "Everything
     listed from Mon, Sep 28, 2026 on"; one untimed show (2026-10-08) with a "Details" link; an `<img>` for the photo];
     `/artist/1?from=2026-10-26` [the same page — the param is ignored]; `/artist/2` [200; Nooky Jones's shows, none
     beyond the window]; `/artist/9999` [404].
   - **Images (D4):** the served HTML of `/show/2` holds `<img src="https://example.com/posters/nooky.jpg">` with
     `loading="lazy"` and `referrerPolicy`/`referrerpolicy="no-referrer"` and a non-empty `alt`; `/venue/3` and `/artist/1`
     each hold their photo `<img>`; `/show/22` (no `image_url`) holds none; `/` holds none (blocks stay image-free).
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
     `/artist/1` and `/show/2` — except the 404 pages, which render twice (B2-CR1-5).
5. **JSON-LD validity** — Ari, locally: paste `/show/2`'s, `/venue/3`'s **and `/show/23`'s** JSON-LD into
   validator.schema.org (or the Rich Results Test's code tab). `/show/23` is at The White Squirrel Bar, which has no
   address in the sample data, so its `location` has no `address`: Google may treat the address as required for a physical
   location, and this is the only way to find out whether events at address-less venues lose rich results (CR1-8). The cloud sandbox can't reach either validator.
6. **API down at runtime:** `/venue/1`, `/artist/1`, `/show/2`, `/day/2026-10-07` give B2's bare 500, with no error
   text, URL or stack in the body; `/` keeps B3's 200 with the skeleton; `/health` 200. Recorded as measured.
7. **Layout** (headless Chromium, `/opt/pw-browsers`, snippets applied): page `scrollWidth === clientWidth` at 375 and
   1280px on `/venue/1`, `/artist/1`, `/day/2026-10-07?sort=artist` and `/show/2` (the venue page embeds B3's grid, whose
   scroll-container rule must still hold inside a new parent). The sample images 404, so this measures the
   broken-image case (alt text, the `max-h-80` cap); a real image is checked by pointing one sample `image_url` at a
   local file served for the test and reverting it.
8. **Browser check by Ari** (include phone width and an untimed show's block — PR1-6; expect `alt` text where
   the sample's `example.com` images 404, D4): each page; the day view's
   mode switch and Back; earlier/later on the venue page; a show
   block's time line → the show page; screen-reader name of that link; the tab titles.

## Not doing in B4

Edit forms and the write API; socials, genres, members, instrumentation (`api-contract.md` §6); an event page;
images inside show blocks, `next/image`, and our own copies of remote images (D4; R2 is the hosted phase's);
`upcoming` on the venue page (the API accepts `venue_id` with it, but the venue page is a calendar and pages, D1); a
cursor or cap on `upcoming` (one artist's bookings are bounded; the envelope has room); JSON-LD on the artist
page (`arch-initial.md` §4 says "detail pages", the build plan scopes it to show and venue pages; adding the artist's
events is a few lines later if Ari wants it); `url` in JSON-LD and `metadataBase` (no site URL until the hosted phase);
"The"-insensitive alphabetising of venues (the API's order stands; "The Midway Saloon" sorts under T); previous/next
day links on `/day/[date]`; a filter header on the venue page (the requirement sends that to the calendar); component
tests (B5); Playwright; caching.

## Follow-ups for other milestones

- **A1b:** the `/shows` query must keep "`start` without `end` = the default window from `start`" (the venue page
  pages that way), implement `upcoming` as `date >= <metro's local today>` with **both 422 guards** (they matter more
  against a real table than against a list), and order a day by night (B3's follow-up, still open). `sample_data.py`'s
  26th row and the generator's window filter go with `sample_data.py` when it is deleted — decide then whether the
  fixtures keep a sample source of their own (A1b already asks).
- **B5:** the day view's mode switch and `WindowNav` are links in Server Components, so they need no component test;
  `show-order.ts` and `calendar-window.ts` are already unit tested.
- **Hosted phase:** a site URL, then `url` in JSON-LD and `metadataBase`; image copies in R2 replace the remote `src`
  inside `RemoteImage` and nothing else (D4).

## Plan review

### Round 1 — Claude Sonnet 5.5, October 14, 2026

**Scope:** the whole plan (Context, D1–D8, Test approach, Steps 1–10, Verification), judged cold against `alpha-build-plan.md` B4, `requirements-initial.md` (Day view, Venue, Artist, Show, times after midnight), `arch-initial.md` §4 (Maps URL, JSON-LD), `api-contract.md`, Next's `json-ld.md`, and the code that exists today (`apps/api/app/routers/shows.py`, `sample_data.py`, `schemas.py`; `apps/calendar/lib/{api,params,dates,calendar,metro,show-format,api-url}.ts`, `app/{page,venue,artist,day}`, `app/_components/{show-block,calendar-grid}.tsx`, `lib/fixtures/*.json`). No experiments needed a worktree; scratch scripts ran outside the repo and left it untouched.

**Checked, and how:**
- The fixture-day expectations (venue order `[25, 8, 22, 23, 24]`, time order `[22, 24, 8, 23, 25]`, the 8 artist rows and their alphabetical order, Pert Near Sandstone at 23:15), venue 1 = 8 shows, venue 3 = 6, artist 1 = 4 shows (dates 09-28, 10-07, 10-08, 10-20), show 22 with no admission data, show 25 `free_admission: true`, show 2 at 21:00 with 18.00/22.00: all recomputed from `lib/fixtures/shows.json` and `show-detail.json`. CONFIRMED, all match.
- The paging arithmetic (28-day window, earlier `2026-08-31`, later `2026-10-26`; leap-year and year-end cases): worked by hand. CONFIRMED.
- The `start`-without-`end` path: `routers/shows.py` fills `end = start + DEFAULT_WINDOW`. CONFIRMED. `date(9999,12,20) + 27 days` raises `OverflowError` in Python (so the 500 claim holds). CONFIRMED.
- The JSON-LD date table, run with `@js-temporal/polyfill` 0.5.1 using the plan's exact expression: `2026-10-07 20:00` gives `...-05:00`; `2026-12-05 20:00` gives `-06:00`; `2026-10-31 01:30` gives `2026-11-01T01:30:00-05:00` (the earlier of the two 01:30s); `toString({ timeZoneName: "never" })` yields no bracketed zone. CONFIRMED. An invalid zone throws (the plan catches `RangeError`).
- React 19.2.0 in the repo blocks `javascript:` hrefs (the string "React has blocked a javascript: URL" is in `react-dom-client.production.js`). CONFIRMED (relevant to finding 3).
- `make check` was not run: no code exists to check. Test approach: tests come first, logic is in pure `lib/` functions, the async pages are not unit tested (style guide, Testing), and expected values are derived by hand. That all conforms.
- Gap placement against `AGENTS.md`: K2 (inclusive window length), K3 (`flatMap` shape change) and K4 (comparator priority) are real lessons with real tests, and D5's two [fill-in] to [written] re-markings are justified by the rule ("don't invent a gap"). Finding 2 concerns K1.

**Counts:** 0 blocker, 2 should-fix, 4 nit. **Verdict: proceed after fixes.** The design is sound and its numbers check out. The open items are specification holes in the JSON-LD builder's tests and one gap that is weaker than the others.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | The JSON-LD test spec (Test approach §4) leaves four reachable inputs undefined. (a) A lone **advance** price: the plan covers advance+door, lone day price, free, and none, but `formatAdmission` shows a lone advance as "$X adv", so the page and the JSON-LD can disagree. (b) A show with `end_time` but `start_time` null: `eventEndDateTime(date, start, end, tz)` is specified only for a non-null start ("earlier than the start" has no meaning without one). (c) `showJsonLd` with a `null` venue detail: Step 8 says the show page renders without an address when `getVenue` returns null, but `showJsonLd`'s signature takes `{ venue }` and only the address-present case is tested, so the `location.name` source (it should fall back to `show.venue.name`) is unspecified. (d) A wall-clock time inside the spring-forward gap (e.g. 2027-03-14 02:30 America/Chicago does not exist). | `lib/show-format.ts:32-41` (`formatAdmission` branch for `advance` alone); plan §4 and the JSON-LD table (no gap row); Step 8 ("A `null` venue ... renders the page without an address"). Offers and date rows checked against the plan text. CONFIRMED that the cases are unspecified; PLAUSIBLE for (d) (Temporal's default `compatible` shifts it forward by an hour, which is acceptable but unpinned). | The implementer decides these silently, and the tests that should pin "never an invented price/time" don't cover them. The likeliest bad outcome is (a) or (b) throwing or emitting `NaN`/`undefined` strings in a script tag on a real venue page. |  **Fixed.** Test approach §4 now specifies all four: (a) a lone advance price → one offer named "Advance", matching `formatAdmission`; (b) `eventEndDateTime` with a null start applies only the after-midnight rule; (c) `showJsonLd` with `venue: null` falls back to `show.venue.name` with no `address`; (d) the spring-forward case (listed 2027-03-13 02:30 → `2027-03-14T03:30:00-05:00`, checked with the polyfill) is pinned and accepted. |
| 2 | should-fix | K1 is the weakest of the four. The lesson (`Promise.all` against a waterfall) is already taught and in the code: `CalendarBody` in `app/page.tsx` runs five requests with `Promise.all` and its comment explains why. And the Check cannot fail: both `[api]` log lines print whichever way the awaits are written (the plan concedes "nothing fails"). A gap whose wrong answer is indistinguishable from the right one teaches nothing. | `app/page.tsx` `CalendarBody` (comment "run together rather than one after another"); K1's *Check* text. D8 already offers the better candidate. | Ari types a pattern he already wrote in B3 and gets no signal from the check. `AGENTS.md` asks for gaps "where the concept lives". |  **Fixed.** Agreed: the lesson repeats B3's and its Check can't fail. K1 is now `eventDateTime` in `lib/json-ld.ts`, with Lesson/Code/Check under TODO(Ari) gaps; the venue page's `Promise.all` is written complete (step 5). Moving a gap into a [written] item is a marking change, so D8 now recommends it and puts it to Ari. |
| 3 | nit | Scraped, soon-user-editable URLs go straight into `href`s and the JSON-LD with no scheme check: Poster (`image_url`), Photo, `original_url` "Source" link, website, plus `image` in JSON-LD (a search engine fetches it). React 19.2 blocks `javascript:` hrefs, so the severe case is covered, but nothing restricts the scheme in the JSON-LD `image` or rejects `data:`, `file:` and the like. | Step 5, Step 8, Step 9 (all render `*_url` fields); react-dom 19.2.0 block string (CONFIRMED); `requirements-initial.md` (image/original URL are extracted by a model). | Low risk today (read-only app, sample data), but "untrusted text from a model" is the plan's own stated threat model for `jsonLdScriptContent`. A one-line `httpUrlOrNull(url)` in `detail-format.ts` (tested: `https://x` ok, `javascript:alert(1)`, `data:...`, `""`, `"garbage"` -> null), used by the links and JSON-LD `image`, would close it consistently. |  **Fixed.** `httpUrlOrNull` added to `lib/detail-format.ts` with tests (§5). All data-driven external links and the JSON-LD `image` go through it (steps 1, 5, 8; §4). |
| 4 | nit | `WindowNav` copy hard-codes "Back to the next four weeks" and shows the range via `formatDayHeading`, which has no year ("Mon, Sep 28 - Sun, Oct 25"). The plan's principle is that the window length is the server's decision, and once paging crosses a year boundary (Dec to Jan) the heading is ambiguous. | Step 2 `WindowNav` description; `formatDayHeading` in `lib/dates.ts`; "Paging" section. PLAUSIBLE. | A server-side change of `DEFAULT_WINDOW` makes the link text lie; a January window reads like the previous January. |  **Fixed.** The range in `WindowNav` prints years, as `/day/[date]` already does; the reset link reads "Back to upcoming dates" (no length). Step 2 and Verification 4. |
| 5 | nit | `windowLinks` is unvalidated at the year bounds while `parseFromParam` rejects years above 9998 and below 1. From a window ending in year 9999, or starting in year 1, the "Later"/"Earlier" link silently lands on the default window. Practically unreachable, but the K2 and `parseFromParam` tests don't mention the interaction. | Plan "One edge, handled in the parser"; K2 *Code*. PLAUSIBLE. | A pager link that quietly resets to "now" instead of being absent. Cheap fix: say it is accepted and note it, or return `null` for that direction. |  **Fixed.** A written `windowNavLinks` wraps K2 and drops any link whose date `parseFromParam` would reject, so the parser is the single bound rule (tests in §2). K2's code is unchanged. |
| 6 | nit | D3 makes the show block's time line the link, including the "Time not listed" / "Start time not listed" variants, whose accessible name becomes "Time not listed, show details" and whose link text is a statement, not an action. The link is also a small touch target (one line of `text-sm`) on 25 blocks per page. | `show-block.tsx` current time line; D3 text. PLAUSIBLE. | Awkward link text for untimed shows; fiddly tap target on phones. The Verification 8 browser check should include untimed shows and a phone width. |  **Fixed.** Untimed blocks keep "Time not listed" as text and get a separate "Details" link; the time link gets `inline-block py-1`. Verification 8 now includes phone width and an untimed show. |

Rejected: none. Every finding was fixed in the plan body. **Round 2 isn't warranted in my view**: the fixes are additive, and the one structural change (PR1-2, the gap swap) is put to Ari as D8.

### Changes after Ari's decisions — October 14, 2026 (not reviewed)

Ari settled D1–D8 (D2 and D4 took the alternative); the plan body was adjusted by Claude Sonnet 5.5. **None of the
following has been seen by the reviewer**, and `AGENTS.md` says a substantial change after a round is Ari's call, so no
round 2 was started:
- **New step 0 and "`upcoming`" section** — a Python/API change in a frontend milestone: one query parameter with two
  422 guards, one appended sample show, a fixture-generator filter, Python tests (§0) and a contract-doc edit.
- **The artist page** loses paging and the `?from=` param and gains the `upcoming` request (step 6, K2 narrowed to the
  venue page).
- **`RemoteImage`** (step 9, D4) — the one lint exception — and the Verification rows that check it.
- Where to look hardest if a round 2 is run: the `upcoming` semantics (is `end` = last returned date the right echo? is
  422 right for `upcoming` + no filter, or should it be a bounded default?), the fixture-generator filter against B3's
  tests, and whether step 0 should be its own PR.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 14, 2026

**Approval:** the plan's Status was `Awaiting approval`; invoking `/build-milestone` counted as Ari's approval and I set it to `Approved` first. All six plan-review Resolution cells were filled.

**Scope.** Step 0 is already committed on its own: **`2231f5e`** ("B4 step 0: GET /shows?upcoming=true …", pushed). Review everything after it as `git diff 2231f5e` plus the untracked files (nothing else is committed): 14 tracked files changed and 14 untracked.
- *Step 0 (committed, `2231f5e`):* `apps/api/app/routers/shows.py`, `app/sample_data.py` (show id 26), `app/tests/test_routers.py` (+9 tests), `scripts/generate_fixtures.py`; generated `apps/calendar/lib/api-types.ts` and `lib/fixtures/calendar-months.json`; `docs/dev/api-contract.md`.
- *New lib:* `lib/{detail-format,json-ld,calendar-window,show-order,todo}.ts` and `.test.ts` for the first four. *Modified lib:* `lib/{api,params,dates}.ts`, `lib/{api,params,dates}.test.ts`.
- *New app:* `app/show/[id]/page.tsx`; `app/_components/{json-ld,remote-image,window-nav,detail-row}.tsx`. *Modified app:* `app/{venue/[id],artist/[id],day/[date]}/page.tsx`, `app/_components/show-block.tsx`.
- *Docs:* `docs/dev/{alpha-build-plan,notes}.md`, `apps/calendar/AGENTS.md`, this file.
- *Unchanged on purpose:* `apps/api/app/schemas.py`, every fixture except `calendar-months.json` (`shows.json` is byte-identical), `app/{venues,artists}/page.tsx`, `calendar-grid.tsx`.

**Departures from the plan.**
1. **K1 is narrower than the plan wrote it.** The plan's K1 was three lines (shift the date past midnight, attach the zone, print the offset). The unknown-zone fallback also needs the shifted date, so the after-midnight shift lives once in a written helper, `instantDay`, and K1 is the one line that attaches the zone and prints the offset (`withOffset`, `lib/json-ld.ts`). The lesson (a wall time is an instant only with a zone; the offset depends on the date) is unchanged; "dropping the date shift" is no longer a way to get the gap wrong, and its Check still fails on every offset row.
2. **`formatDayHeadingWithYear` added to `lib/dates.ts`** (not in the plan): four pages print "Mon, Oct 12, 2026". **Its test and implementation were written in the same step and I never watched the test fail first**; it's a one-liner, but it is a departure from tests-first.
3. **Unrelated json-ld tests run with no zone** (`noZone`), so offers, lineup, image and venue-null tests don't depend on K1 and stay green while it is open. The plan's §4 had them all use the Chicago context.
4. **New `DetailRow` component** (`app/_components/detail-row.tsx`) for the repeated `<dt>/<dd>` pairs; not in the plan. It also carries the overflow fix (below).
5. **Two bugs found by measurement, fixed, and recorded in `notes.md`** (the unit tests could not see either): `.sr-only` inside a scroll container widened `/` to 889px at 375px (fixed with `relative` on the show block's link), and a long URL widened `/venue/3` by 9px (`min-w-0 [overflow-wrap:anywhere]` on `DetailRow`'s `<dd>`).
6. **`windowNavLinks`'s bound test was wrong in my first draft** (I expected `9999-11-03` to survive; the parser rejects all of year 9999). The implementation matched the plan's "years 1..9998"; I rewrote the test to show each direction dropping independently.
7. **The router's range checks moved into an `else` branch** (`if upcoming: … else: <existing checks>`), so the open-ended request stays out of `MAX_RANGE`; the plan said only "unchanged otherwise". Behaviour without `upcoming` is unchanged (the existing router tests pass untouched).
8. **I committed step 0** although the skill says not to commit unless asked: the approved plan says step 0 "lands first and on its own", and a cloud session's work is lost unless pushed. Everything after it is uncommitted, as the skill says.
9. `lib/todo.ts` was recreated (B3's was deleted with its last gap); `byVenueName` is passed into the placeholders so it counts as used while K4 is open; the artist-mode row for an untimed act shows "Time not listed · Details".

**`TODO(Ari)` gaps (all four open; none filled by anyone).** Review the code as it stands; open gaps aren't findings.
- **K1** — `withOffset`, [lib/json-ld.ts:77](apps/calendar/lib/json-ld.ts#L77): a wall-clock time becomes an instant only with the metro's zone, and the offset depends on the date.
- **K2** — `windowLinks`, [lib/calendar-window.ts:24](apps/calendar/lib/calendar-window.ts#L24): paging links come from the range the server echoed, never a clock or a constant 28 (inclusive length, so `+ 1`).
- **K3** — `artistRows`, [lib/show-order.ts:74](apps/calendar/lib/show-order.ts#L74): artist mode is a different shape (one row per act), made with `flatMap`.
- **K4** — `venueOrder` and `timeOrder`, [lib/show-order.ts:46](apps/calendar/lib/show-order.ts#L46): the two venue modes are the same two keys in opposite priority, chained with `||`.
Tests: `pnpm --filter calendar test json-ld calendar-window show-order`. Suggested order K1, K2, K3, K4. While they are open the pages that call them render the error page (`/show/[id]` and `/venue/[id]` need A, `/venue/[id]` needs B, `/day/[date]?sort=artist|time|venue` needs C and D), so the browser check comes after all four.

**Verification.**
- **Tests first.** Python: 9 tests written and run first, 8 failed for the right reason (missing 2026-10-29 show, no 422, parameter absent from OpenAPI); `upcoming=false` passed because the parameter was still ignored (a regression guard). Frontend: stubs that throw, then tests, **88 failed**, all "not implemented" or a missing method (no import errors); then implemented. Exception: departure 2.
- **Baseline before any change:** `make check` green (566 Python, 187 Vitest, contract current).
- **Step 0 alone (`2231f5e`):** `make check` green: **575 Python passed** (566 + 9), 187 Vitest, contract current. `make types` emitted `upcoming?: boolean` on `GET /shows` exactly as the plan expected; `git diff` of fixtures: only `calendar-months.json`, October 22 → 23; `shows.json` unchanged.
- **`make check` at handoff (scaffold as committed-to-be):** ruff, mypy (29 files), eslint, `next typegen` + tsc, pytest (575) all clean; `make contract-check` current; **Vitest 250 passed, 31 failed** — exactly the open gaps: `json-ld.test.ts` 14 (K1), `calendar-window.test.ts` 6 (K2), `show-order.test.ts` 11 (K3 4, K4 7). (`make check` stops at Vitest, so tsc, eslint and contract-check were also run on their own, all clean.)
- **Snippets validated.** The four `Code:` snippets were applied exactly as written (a script first asserted every snippet line appears in its gap comment) in the working tree, everything run, and the scaffold restored from a copy: SHA-256 of `json-ld.ts`, `calendar-window.ts`, `show-order.ts` identical before and after. With them applied: **`make check` fully green — 575 Python, 281 Vitest**, tsc and eslint clean, contract current.
- **V3 (build, API unreachable, snippets applied):** `API_BASE_URL=http://127.0.0.1:9 pnpm build` succeeds; `/`, `/_not-found`, `/artist/[id]`, `/artists`, `/day/[date]`, `/health`, `/show/[id]`, `/venue/[id]`, `/venues` all `ƒ`. Bundle check: the polyfill's error text is in **no** `.next/static` file. `grep -rn no-img-element apps/calendar/app` finds **one** line (`remote-image.tsx`).
- **V4 (HTTP matrix, `next start` against uvicorn, snippets applied; 85 checks scripted, all pass).** `GET /shows`: `artist_id=1&upcoming=true` 200, 5 shows ending 2026-10-29, `end` 2026-10-29; `artist_id=1` 4 shows, `end` 2026-10-25; `upcoming=true` alone and with `start` both 422. Pages: `/venue/1` 8 blocks, Earlier `?from=2026-08-31`, Later `?from=2026-10-26`, one JSON-LD script with 8 events; `/venue/3` 6 blocks, events carry the address, photo `<img>`, tel/mailto links, "21+"/"Served" and no raw enum text; `/venue/1?from=2026-10-26` 1 block with Earlier `?from=2026-09-28` and Later `?from=2026-11-23`; `?from=2026-11-23` "No shows listed", back link, no JSON-LD; `?from=garbage|9999-12-20|20261026` the default window; `/artist/1` 5 shows ascending, "Everything listed from Mon, Sep 28, 2026 on" (React inserts `<!-- -->` between the pieces; my first check missed that), one untimed show with a "Details" link, no pager, `?from=` ignored; `/day/2026-10-07` block order `[25, 8, 22, 23, 24]`, `?sort=time` `[22, 24, 8, 23, 25]`, `?sort=bogus` the venue order, `?sort=artist` 8 rows alphabetical from Beasthead with "1:00 AM Thu" and "11:15 PM"; `/show/2` JSON-LD parses, `startDate` `2026-09-30T21:00:00-05:00`, offers 18.00/22.00 as strings, poster `<img>` with `loading="lazy"`, `referrerPolicy="no-referrer"` and alt text; `/show/25` `startDate` `2026-10-08T01:00:00-05:00`, one offer price "0"; `/show/22` no `offers`, no `<img>`; `/show/26` (2026-10-29) `-05:00`, one unlabelled "10.00" offer; `/` 25 blocks, each linking to its show, no `<img>`. 404s: `/venue/9999|abc`, `/artist/9999|abc`, `/day/2026-02-30|garbage|20261007`, `/show/9999|abc`, `/nope`. **De-duplication:** one `GET /venues/1`, `/artists/1`, `/shows/2` per page load (a 404 page renders twice, as in B2).
- **V6 (API stopped):** `/venue/1`, `/artist/1`, `/show/2`, `/day/2026-10-07` answer the bare **500** with no `ApiError`, URL or stack in the body; `/` **200**; `/health` 200; `/venue/abc` and `/nope` 404.
- **V7 (headless Chromium via the sandbox's Playwright, snippets applied, fully loaded):** page `scrollWidth === clientWidth` at **375, 768 and 1280px** on `/`, `/venue/1`, `/venue/3`, `/artist/1`, `/day/2026-10-07`, `/day/2026-10-07?sort=artist`, `/show/2`, `/show/22`, after the two fixes in departure 5 (before them: `/` 889px and `/venue/3` 384px at 375px). The sample's `example.com` images are unreachable here, so this measured the broken-image path (the alt text in a bordered box). Screenshots of the show, artist and day-by-artist pages at 375 and 1280 read as intended.
- **Not verified:** that Google and validator.schema.org accept the JSON-LD (no route from the sandbox; V5 is Ari's); a real image rendering (no reachable image), including the `max-h-80` cap on a tall poster; touch tap targets and the screen-reader name of the "show details" link; dark mode; a real phone; Vercel's build and Node 24 (the sandbox has Node 22); the `RemoteImage` markup beyond the served-HTML attributes (no component tests until B5); that A1b's SQL can reproduce `upcoming`.

**Where to look hardest.**
1. **Step 0, `routers/shows.py`.** The `upcoming` semantics are the least reviewed part of the plan (it changed after the plan review): `end` echoed as the last returned date, 422 for `upcoming` with no venue or artist, and the `if upcoming: … else:` restructure. Whether `datetime.date.max` as a temporary `end` is clear enough, and whether the new sample row (id 26) is a good way to make the parameter observable.
2. **`lib/json-ld.ts`.** The `eventEndDateTime` comparison uses `nightSortKey` of start and end; check the odd inputs (start 01:00 and end 00:30 gives a next-next-day end, a 23.5-hour show). `withOffset` being a one-line gap (departure 1). The JSON-LD on the venue page is a top-level array of events (valid JSON-LD, but unvalidated). No `url`, `availability` or `validFrom` on offers.
3. **`app/_components/show-block.tsx`.** The time line is the link and the `relative` fix for `sr-only`; the "Details" link for untimed shows; `inline-block py-1` as the tap target.
4. **`remote-image.tsx` and the three pages that use it.** The one lint exception and its accepted costs (D4); that `httpUrlOrNull` is applied to every URL that reaches an `href`, an `<img>` or JSON-LD (website, calendar URL, Source, photo, poster, image) — `tel:` and `mailto:` are built from scraped text with a fixed prefix and are not run through it.
5. **`lib/calendar-window.ts` and `window-nav.tsx`:** the pager at the year bounds; `rel="nofollow"`.
6. **Whether the four gaps are still the right lines** now that the scaffold exists (K1 in particular, narrowed to one line).

### Round 2 — Claude Sonnet 5.5, October 14, 2026 (the fixes for code review round 1)

**Scope.** Only the fixes, on top of the committed scaffold `6b1cb39`: `apps/calendar/lib/json-ld.ts` and `json-ld.test.ts` (CR1-1, CR1-3), `apps/calendar/app/venue/[id]/page.tsx` (CR1-7), `apps/api/app/tests/test_routers.py` (CR1-6), `apps/calendar/AGENTS.md`, `docs/dev/{alpha-build-plan,notes}.md` and this file (CR1-2, CR1-4, CR1-5, CR1-8). The log's round 1 said "nothing else is committed" and "everything after it is uncommitted": that was true when written; **the scaffold was committed as `6b1cb39` (and pushed) during the review**, at the repository stop hook's request, with the plan file left out because the reviewer was writing into it. Reviewers' scope was unaffected (`git diff 2231f5e` shows the same changes either way).

**Departures.**
10. **The day view's active mode is a `<span aria-current="page">`, not a `<Link>`** (plan D6 said three links with `aria-current` on the active one). A link to the page you are on is noise. (Missed in round 1's list; found by CR1-4.)
11. **`eventEndDateTime` returns `null` for a contradictory both-before-5:00 AM listing** (CR1-3). The plan specified only the cases in its test table; this is the rule for the one the review found.

**`TODO(Ari)` gaps (all four still open).** K1 [lib/json-ld.ts:77](apps/calendar/lib/json-ld.ts#L77), K2 [lib/calendar-window.ts:24](apps/calendar/lib/calendar-window.ts#L24), K4 [lib/show-order.ts:46](apps/calendar/lib/show-order.ts#L46), K3 [lib/show-order.ts:74](apps/calendar/lib/show-order.ts#L74) (line numbers re-checked after the edits). **D9 is open**: whether K1 should be widened back to the two ideas D8 approved.

**Verification.** See the end of code review round 1 for the suite results. Process notes: CR1-3's two tests were written and run against the committed code first (failing), then the fix; CR1-1's strengthened assertion and the comment fix were written together. The four snippets were re-applied (each asserted to appear in its gap comment) and the scaffold restored by SHA-256, because `json-ld.ts` changed.

**Where to look hardest.** The `null` rule in `eventEndDateTime` (is "omit" the right answer, or should the listing be flagged upstream in validation?) and D9.

### Round 3 — Claude Sonnet 5.5, October 15–16, 2026 (the closed gaps and the designation convention)

Not a fix round: Ari filled the four gaps, and `main` gained `docs/dev/conventions.md`, so the branch needed the cleanup pass `AGENTS.md` describes and a conversion to the new forms. No behaviour changed.

**Scope.** Ari's gap commits through `24cb88c` and the merge of `main` (`00d2203`) on top of it: the B4-authored files under `apps/calendar` and `apps/api`, `AGENTS.md` (step 4 of the [fill-in] section), `docs/dev/{alpha-build-plan,notes,api-contract,conventions}.md` and this file.

**What was done.**
1. **Gaps closed.** K1–K4 were filled by Ari (D9 is moot: K1 stayed the narrow `withOffset` line). The scaffold came out of the source: `TODO(Ari)` blocks became plain why-comments that keep the reasoning and cite the plan by K-form (`B4-K1`…), `lib/todo.ts` was deleted, and the "stay red until Ari fills" notes left the test docstrings.
2. **Designation convention.** Gap letters A–D became K1–K4; cross-plan references are scoped (`B2-D1`, `B3-K2`, `A2.1-D5`); review items are `B4-PR1-<n>` / `B4-CR1-<n>` in code and tests and bare `PR1-<n>` / `CR1-<n>` in this file (`#n` shorthand and "review #n" had been ambiguous between the two reviews).
3. **`AGENTS.md` step 4** now says the cleanup keeps the K-form references and drops only the scaffolding, so the next milestone's pass does this in one step.

**Departures.** Process: the scaffold and the step-0 commit were committed during the session rather than left uncommitted (the container is ephemeral); noted in round 1's review preamble.

**`TODO(Ari)` gaps.** All four filled by Ari; no `TODO(Ari)` remains in `apps/` (`grep -rn "TODO(Ari)" apps` finds nothing in B4's files).

**Verification.** Comment-only passes were checked as the Conventions require: the Python syntax trees (minus docstrings) and the TypeScript transpiles (comments removed) match the commit before each pass, for every file touched. `make check` after the pass: ruff, mypy, eslint, tsc clean; pytest **575 passed**, 14 skipped; Vitest **283 passed**; `make contract-check` current.

**Where to look hardest.** The `PR1`/`CR1` forms in the older rounds' prose ("round 1's list", "(#3)") were converted only where a reader could mistake the review; the round tables keep their own row numbers, which are the IDs.

## Code review

### Round 1 — Claude Opus 5.5, October 14, 2026

**Scope.** Step 0 (`2231f5e`) plus the scaffold. The log describes the scaffold as the uncommitted tree on top of `2231f5e`. While this review ran, it was committed as **`6b1cb39`** ("B4: detail pages scaffold with four open TODO(Ari) gaps", branch `claude/practical-davinci-ur4444`, 18:33 UTC), which left only this file modified. I checked that this changes nothing for the review: a scripted per-file comparison shows every tracked file's diff in `2231f5e..6b1cb39` is identical to the `git diff 2231f5e` I reviewed, and the new files I had already read have the same content at HEAD (the gap line numbers, and the text in finding 1). The reviewed range is therefore `2231f5e^..6b1cb39`.

**What I checked, and how.**
- **Read:** the whole plan (plan review round 1 and the Implementation log included); `nextjs-style-guide.md` (routing, metadata, `next/image`, Testing, Anti-patterns); the Anti-patterns table in `fastapi-style-guide.md`; `apps/calendar/AGENTS.md`. In scope I read every file: `routers/shows.py`, `sample_data.py`, `generate_fixtures.py`, the 9 new router tests, the `api-contract.md` edit, the generated `api-types.ts` hunk, every new or modified `lib/` module and test, the four new components, the four pages, `show-block.tsx`, and the doc edits.
- **`make check` on the scaffold as committed:** ruff, eslint, mypy (29 files), and `next typegen` + tsc are clean. pytest: **575 passed, 14 skipped**. Vitest: **250 passed, 31 failed**, and every one of the 31 throws `TODO(Ari)` from the four gaps (json-ld 14, calendar-window 6, show-order 11). `make contract-check` is current. CONFIRMED; this matches the log.
- **Gaps filled in a throwaway `git worktree`** (removed afterwards): at `2231f5e` plus the scaffold, I filled the four gaps verbatim from their own `Code:` comments. Vitest **281/281**; tsc and eslint clean, with `lib/todo.ts` left unreferenced. The snippets fit. CONFIRMED.
- **Build with the API unreachable:** in the same worktree, `API_BASE_URL=http://127.0.0.1:9 pnpm build` succeeds, and all nine routes are `ƒ`. CONFIRMED.
- **HTTP checks** against `next start` + uvicorn (worktree, gaps filled):
  - **API:** `/shows?artist_id=1&upcoming=true` returns start 2026-09-28, end 2026-10-29 and the five expected dates. `upcoming=true` alone, and with `start`, return 422 with readable details. `upcoming=` (empty) gets FastAPI's own 422.
  - **Status codes:** 200 for `/venue/1` (bare, `?from=2026-10-26`, `?from=0001-01-01`, `?from=9998-12-31`), `/venue/3`, `/artist/1|2`, `/day/2026-10-07` in all three modes, and `/show/2|22|23|25|26`. 404 for `/show/9999`, `/venue/9999` and `/show/abc`.
  - **JSON-LD, parsed from the served HTML:**
    - `/show/23`: `2026-10-07T22:00:00-05:00` to `2026-10-08T00:30:00-05:00`.
    - `/show/2`: offers "18.00"/"22.00" as strings, plus the address.
    - `/show/25`: `2026-10-08T01:00:00-05:00`, price "0".
    - `/show/22`: no `offers` key.
    - `/venue/1?from=2026-10-26`: one event.
  - **Titles:** "Nooky Jones, Beasthead at Zhora Darling, Wed, Sep 30, 2026 · …". The venue page's description includes the address.
  - **Pager at the year bound:** `/venue/1?from=9998-12-31` shows Earlier and "Back to upcoming dates" but no Later.
  - All CONFIRMED.
- **API stopped:** `/show/2`, `/venue/1`, `/artist/1` and `/day/2026-10-07?sort=artist` return 500, with no `ApiError` and no API URL in the body. `/show/abc` returns 404. CONFIRMED.
- **Layout:** headless Chromium (`/opt/pw-browsers`), measured after `networkidle`. `scrollWidth === clientWidth` at 375 and 1280 px on `/`, `/venue/1`, `/venue/3`, `/venue/1?from=9998-12-31`, `/artist/1`, `/day/2026-10-07` in all three modes, `/show/2` and `/show/23`. CONFIRMED.
- **`eventEndDateTime` on contradictory inputs:** run through Vitest from a scratch config outside the repo, with no zone, so no gap is involved. See finding 3. CONFIRMED.
- **Anti-patterns tables (Next.js and FastAPI):** no hits. No Client Component was added. `params` and `searchParams` are awaited. `notFound()` sits outside every `try`. There is no `images.domains` and no broad `except`.
- **The log's "Where to look hardest", answered:**
  1. Step 0 is sound. Setting `end` to the last returned date keeps `end >= start`. Both 422s are justified. The `else` restructure leaves the old path unchanged (the old tests pass untouched). The `datetime.date.max` sentinel is commented where it is set.
  2. `json-ld.ts`: see finding 3. A top-level array of events on the venue page is valid JSON-LD.
  3. Show block: the `relative` fix holds (no overflow measured).
  4. Every `href`, `src` and JSON-LD URL built from data goes through `httpUrlOrNull`. `tel:` and `mailto:` have fixed prefixes, so they can't become a script URL.
  5. Pager bounds: confirmed above.
  6. The gaps: K2, K3 and K4 are the right lines. For K1, see finding 2.

**Counts:** 0 blocker, 1 should-fix, 7 nit. **Verdict: proceed after fixes.** The code does what the plan says, the four snippets fit their gaps, and everything I measured matches the log. The findings are one wrong comment about the app's only XSS defence, one undecided edge case, and bookkeeping.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | The comment explaining why `dangerouslySetInnerHTML` is safe has lost its escape. `lib/json-ld.ts:240` reads "Replacing `<` with its JSON escape `<` is lossless", and `lib/json-ld.test.ts:220` reads "(< -> <)". The code itself (`json-ld.ts:245`) is right. The prose should name the six-character JSON escape (a backslash, then `u003c`), but as written it describes a no-op. | `grep -n "JSON escape" apps/calendar/lib/json-ld.ts`; `cat -A` shows a literal `<` where the escape should be. CONFIRMED. | In a project where the comments are the lesson, the explanation of the app's only XSS defence says nothing happens. A reader either doesn't learn why it's safe or "fixes" the code to match the comment. Probably whatever wrote the comment turned the escape sequence into the character, so verify the fix byte-wise (e.g. `grep -c u003c` on both files). |  **Fixed.** Both comments now spell the escape (`json-ld.ts` and `json-ld.test.ts`); verified byte-wise (`grep -c u003c`: 2 in each file). The cause was my own tooling converting the six characters to a literal `<` when I wrote the comments. The test also now asserts the output *contains* the escape, not only that `<` is absent, so the comment's claim is pinned. |
| 2 | nit | K1 is narrower than the gap Ari approved in D8. D8 and the plan's K1 put the after-midnight date shift inside the gap ("the after-midnight rule meeting a real instant"; likeliest mistake "dropping the `add`"). The scaffold pre-writes that shift as `instantDay` (`json-ld.ts:69-71`) and leaves a single line (`withOffset`, `:101-103`) that its own Code comment prints almost verbatim. The log records this (departure 1), and the remaining line is where the zone concept lives, so the gap is still legitimate. But the stated reason doesn't force the narrowing: if `instantDay` were left open, the fallback path that calls it would just stay red along with the rest of K1. | Plan D8 and "TODO(Ari) gaps", K1, against `json-ld.ts:63-103`. CONFIRMED (text). | Ari approved a gap with two ideas and gets one with one idea, without being asked. The half where the after-midnight rule meets a real instant is no longer typed. Fix: name it as a question for Ari in the handoff: keep it as is, or make `instantDay`'s body part of K1 (same block, one more line). |  **Fixed (put to Ari).** Raised as open decision **D9** in the plan's Decisions section with a recommendation (keep the narrow gap, since the date shift is the same line B3-K2 taught) and the cost of widening it. Code unchanged until Ari answers; the handoff repeats the question. |
| 3 | nit | `eventEndDateTime` produces an event about a day long when a start before 5:00 AM has an end that is earlier still. Listed 2026-10-07 at 01:00–00:30 (so the start is `2026-10-08T01:00`), the end comes out as `2026-10-09T00:30:00`, 23.5 hours later. 03:00–02:00 gives `2026-10-09T02:00:00`. Both rules fire: `endsNextMorning` moves the anchor a day (the night key of 00:30 is less than that of 01:00), then `instantDay` moves it again. The listing contradicts itself, so no answer is "right", but the current behaviour is pinned by no test (the log flags this case). | `json-ld.ts:148-150`. Output from a scratch Vitest run, no zone. CONFIRMED. | A model-extraction slip publishes an end time a day after the start in search results. Fix: decide and pin it with a test. For example, omit `endDate` when both times are after midnight and the end is earlier (the contract prefers "not stated" over a guess), or keep today's behaviour and pin it. |  **Fixed.** Test first: two cases (`01:00` to `00:30`, `03:00` to `02:00`) written and watched fail against the committed code, then `eventEndDateTime` returns `null` (no `endDate`) when start and end are both before 5:00 AM and the end is earlier — a contradictory listing publishes "not stated" rather than a ~23-hour show. The `01:00` to `06:00` row stays a real same-morning end. Comment at the rule and a `Proves:` comment on the test. |
| 4 | nit | D6 and step 7 specify three `<Link>`s, with `aria-current="page"` on the active one. The day view instead renders the active mode as a `<span aria-current="page">`. This departure isn't in the log. For accessibility it's fine (`aria-current` is a global attribute) and arguably clearer. But on `?sort=venue` (accepted, not canonical), nothing links back to the canonical bare URL. | `app/day/[date]/page.tsx:59-68`; served HTML of `/day/2026-10-07?sort=artist`. CONFIRMED. | An unrecorded departure from an Ari-approved decision, with a small canonical-URL gap. Fix: record it as a departure, or follow the plan. |  **Fixed (recorded); part rejected.** Recorded as departure 10 in Implementation log round 2: the active mode is a `<span aria-current="page">`, because a link to the page you are already on is noise and `aria-current` is global. **Rejected:** the canonical-URL concern. Nothing in the app writes `?sort=venue` (`dayHref` never emits it), so it is reachable only by hand-editing, and the plan already says it is accepted and treated as the default. |
| 5 | nit | Bookkeeping left over from step 10 and from the commit made during the review:<br>(a) `apps/calendar/AGENTS.md` still says "`getVenue`/`getArtist` return `null` on 404". It doesn't mention `getShow`, or that the three getters are now wrapped in `cache()` (step 10 asked for "`/show/[id]` and the cached getters").<br>(b) `alpha-build-plan.md` B4 ticks the "Added during B4" item `[x]` but says "the boxes below stay unticked until Ari fills them and signs off", and leaves the two finished, gap-free [written] items unticked.<br>(c) The log's scope ("nothing else is committed"; departure 8, "Everything after it is uncommitted") has been stale since `6b1cb39`.<br>(d) `git diff --check` flags a new blank line at the end of `docs/dev/notes.md`. | `apps/calendar/AGENTS.md:59-62`; the `alpha-build-plan.md` B4 block; `git diff --check 2231f5e 6b1cb39`. CONFIRMED. | The next agent reads the AGENTS.md line as the full list of getters. The tick marks contradict the sentence above them. The code reviewer's scope is wrong. Fix: one line per item. |  **Fixed.** (a) `apps/calendar/AGENTS.md` now lists `getShow` and says `getMetro`/`getVenue`/`getArtist`/`getShow` are `cache()`-wrapped and why. (b) `alpha-build-plan.md`: the sentence now says the three items with a gap stay unticked and the two gap-free items are ticked (artist page, `/venues` + `/artists`). (c) The log's scope note is corrected in round 2 (the scaffold is `6b1cb39`). (d) the trailing blank line in `notes.md` removed; `git diff --check` is clean. |
| 6 | nit | The `_dates` helper in `test_routers.py` (step 0) has no comment. Root AGENTS.md says to "explain each helper and fixture in plain terms". | `git show 2231f5e -- apps/api/app/tests/test_routers.py`. CONFIRMED. | A small convention miss. One line fixes it ("dates of the shows `GET /shows?<query>` returns, in response order"). |  **Fixed.** `_dates` in `test_routers.py` now has a comment saying what it returns and why. |
| 7 | nit | The venue page keys its phone and email spans by value (`key={phone}`, `key={email}`). Both lists are scraped, and a site that lists the same number twice gives React duplicate keys. | `app/venue/[id]/page.tsx:114,126`. PLAUSIBLE (no sample venue has a duplicate). | A duplicate-key warning, and possibly a wrong reconciliation, from ordinary dirty data. `key={i}` (the list is static) or de-duplicating fixes it. |  **Fixed.** The phone and email spans are keyed `${i}:${value}`, so a duplicated scraped value can't produce duplicate keys (the lists are static, so the index is stable). |
| 8 | nit | Shows at a venue with no address get JSON-LD with no `location.address`. Google's Event rich result treats the address as required for a physical location, but Verification 5 validates only `/show/2` and `/venue/3`, which both have addresses. Venue 1 (The White Squirrel Bar) has none in the sample: `/show/23`'s served JSON-LD has no `address`. | Served JSON-LD of `/show/23` (CONFIRMED). Google's requirement: PLAUSIBLE (the sandbox can't reach Google's docs or the validator). | Without that check, nobody learns whether a third of the venues' events lose rich results. Fix: add `/show/23` to Ari's V5 paste. Any real fix is data (the A track filling addresses), not an invented address. |  **Fixed.** `/show/23` added to Verification 5 (Ari's validator paste), with the reason: its venue has no address, so its `location` has none. No address is invented; filling addresses is the data's job (A track). |

Rejected: part of CR1-4 only (the canonical-link concern, reason above). Everything else was fixed in the code or the docs; CR1-2 is put to Ari as D9 rather than decided here.

**Test-suite result after the fixes.** Handoff state (scaffold with the four gaps open): ruff, mypy (29 files), eslint, `next typegen` + tsc and pytest (**575 passed**, 14 skipped) clean; `make contract-check` current; Vitest **252 passed, 31 failed** — exactly the open gaps (json-ld 14, calendar-window 6, show-order 11), the same 31 as before. With the four `Code:` snippets applied from their comments (scaffold restored by checksum afterwards): `make check` fully green, **575 Python and 283 Vitest**.

**Round 2 is not warranted.** The one behaviour change (CR1-3) is a small, test-pinned `null` case; the rest is comments, docs and a key. The open question for Ari is D9, which is a design choice, not a defect.
