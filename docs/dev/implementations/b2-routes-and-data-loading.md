# B2 — routes and data loading

**Status:** Done — signed off by Ari October 12, 2026 after a browser check. All five `TODO(Ari)` gaps filled by Ari; code review round 1 (7 findings) resolved. Committed as `e1eecd4`.
**Date:** October 8, 2026
**Author model:** Claude Sonnet 5.5
**Reviewer model:** Claude Opus 5.5 (plan review round 1; code review round 1) — findings and resolutions under [Plan review](#plan-review); code review under [Code review](#code-review)
**Spec:** `docs/dev/alpha-build-plan.md` §6 B2 (and gaps v0.1-G23, v0.1-G24), `docs/dev/api-contract.md`, `docs/arch/arch-initial.md` §4, `docs/arch/requirements-initial.md` "Main Views & URL Scheme", `docs/references/nextjs-style-guide.md`

## Context

B1 stripped the template and left `apps/calendar` with a shell, a `/` placeholder and `/health`.
B2 makes it a real app skeleton: the six routes from the requirements exist, each loads its
data from FastAPI in a Server Component, and the calendar's filters live in the URL. It is the
first milestone where the two tracks meet over real HTTP.

What B2 is *not*: the calendar layout, the filter header UI, responsive behavior, the show block
component (all B3), or richer detail pages and JSON-LD (B4). B2's pages render their data
**deliberately plainly** — semantic HTML, minimal Tailwind — because B3/B4 replace the
presentation. Anything B2 builds that those milestones would throw away should be as small as
possible.

### What B2 delivers

| Route | Data (B2) | Notes |
|---|---|---|
| `/` | `GET /shows` with filters from the URL, plus `GET /venues` | Plain list of shows. Filter state parsed from `?venue=…&artist=…&month=…`; no filter UI yet. `/venues` supplies the names for the demo filter links (step 7) |
| `/day/[date]` | `GET /shows?start=D&end=D` | `[date]` validated; bad date → 404. The three sort modes are B4 |
| `/venue/[id]` | `GET /venues/{id}` | Metadata only. The embedded calendar is B4 |
| `/venues` | `GET /venues` | Alphabetical list, links to `/venue/[id]` |
| `/artist/[id]` | `GET /artists/{id}` | Metadata only. Upcoming-shows list is B4 |
| `/artists` | `GET /artists` | Alphabetical list, links to `/artist/[id]` |
| layout | `GET /metro` | Replaces the hard-coded metro name (`TODO(v0.1-G24)`) in the footer and `description` |

Plus: header nav links to `/venues` and `/artists` (deferred from B1 because the routes 404'd),
`not-found.tsx`, `error.tsx`, and the `server-only` guard that `apps/calendar/AGENTS.md` said
to add "in B2 along with the API client".

### Decisions already made (earlier in this project)

- **Filters are URL search params**, not component state (`arch-initial.md` §4).
- **Types come from the generated `lib/api-types.ts`**; import via `lib/types.ts`.
- **Server Components fetch; no `useEffect`**, no client data library (style guide anti-patterns).
- **The server owns "now"** (`api-contract.md` §3): the client never computes the window; it
  renders the `start`/`end` the API echoes back.
- **The Oct 8 note:** [fill-in] items get dense guiding comments and a scaffold; Ari walks through
  them before the implementation is completed. Tests first, always.

### Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **B2's "reading from the JSON fixtures until Track A's endpoints exist" is stale.** Track 0
   shipped the routes: `app/routers/` serves `sample_data.py` over real HTTP, and
   `apps/calendar/AGENTS.md` says "prefer real HTTP … for anything else". The client calls the
   API; fixtures are used **only in tests**.
2. **The v0.1-G24 item I wrote ("cache the fetch with `force-cache` and a long `revalidate`") is wrong
   for this phase** — see Decision D1. Revise that wording.
3. B2's route list names six routes. `/show/[id]` is in the contract (`GET /shows/{id}`) and in the
   requirements' view list but is **not** in B2's list; see D3.

## Decisions (settled by Ari, October 9, 2026)

These changed what gets built. Ari accepted the recommendation on D1–D4 and chose the alternative
on D5.

- **D1 — Caching policy: no persistent caching in B2.** **Decided: approved.** Ari does want a caching
  layer eventually — as architectural discipline and a learning exercise as much as for measured
  need — but not in B2. It's recorded as a deferred decision in `arch-initial.md` §11
  ("Calendar data loading, caching, and where filter/search runs"), including Ari's idea of loading
  the whole future calendar into local storage for up to 24 hours and filtering client-side, and the
  tensions that idea has with the URL-as-state decision. B2's choices keep it open: filters are in
  the URL, the client calls the API by URL parameters, and nothing here assumes the data is fetched
  fresh per request beyond the `no-store` setting in one place (`lib/api.ts`). Every fetch uses `cache: "no-store"`.
  `getMetro()` is wrapped in React `cache()` so the layout and `generateMetadata` share one API
  request per render (Next's own `fetch` memoization is *not* available: it is switched off when
  a `signal` is passed — review #3). Reasoning: any route that does a
  `force-cache`/`revalidate` fetch gets prerendered **at build time**, which makes every Vercel
  build (and every local `next build`) depend on the API being reachable — the exact problem the
  old `/` page's comment (`force-dynamic`) was written to avoid. Because the root layout would
  fetch the metro, that includes `/_not-found`. Caching is a performance decision to make when
  there's something to measure ("don't build what has nothing to consume it"). **Consequence, accepted:** with
  no cached fetch in the root layout, *every* route is dynamic (`ƒ`), including `/` and
  `/_not-found`; each request pays one extra, cheap `/metro` call. Alternative: cache reference
  data (metro, venue and artist lists) with `revalidate` and accept the build-time dependency.
- **D2 — Include `month` in the URL scheme now, without its dropdown.** **Decided: approved,** including the whole-month semantics below. The dropdown is B3, but the
  parameter scheme is "the decision with the most downstream consequences"; defining
  `venue`, `artist` and `month` together means B3 doesn't reopen it. `month=YYYY-MM` means **the whole calendar
  month, literally**: first to last day inclusive, past days included, no clock consulted on the
  client (review #10). "Future-facing months only" is a property of which months the B3 dropdown
  *offers* — the server's `GET /calendar/months` — not of the range; a hand-edited past month
  shows what it says. The later "show past dates" toggle will interact with this and can add a
  clamp then. Alternative: venue and artist only; `month` joins in B3. (Not
  included either way: `getCalendarMonths()` — its only consumer is the B3 dropdown.)
- **D3 — `/show/[id]` stays out of B2.** **Decided: approved.** Nothing links to it until B3 makes show blocks
  clickable. It is a small addition then (`GET /shows/{id}` already exists).
- **D4 — `loading.tsx`: omit.** **Decided: approved.** Dynamic pages would show nothing during navigation until the
  fetch resolves; `loading.tsx` fixes that. But the pages are fast against sample data and B3
  decides skeleton design. Add it with B3 unless you want the primer coverage now. **Note for B3:** once
  `loading.tsx` exists, responses stream, and `notFound()` can then return HTTP 200 (Next docs,
  `not-found.md`) — the 404 rows in Verification 4 are only valid while there is no
  `loading.tsx`; re-check them when it lands (review #11). **Also (code review #2):** `loading.tsx`
  (or a `<Suspense>` around the page content) is what would let the shell and `error.tsx` render
  during an API outage; without it a failed fetch returns a bare 500 document — see Verification 6.
- **D5 — Steps 4 and 6 stay [fill-in]. Decided: keep the marking as it is.** The review (#2) noted
  these two steps have no unit-testable line and suggested re-marking them [written]. Ari rejected
  that: the testability requirement in `AGENTS.md` is overstated for them. The point of a [fill-in]
  is that Ari types the few lines that teach something, not that a test turns green. So both steps
  get `TODO(Ari)` gaps (D and E under [TODO(Ari) gaps](#todoari-gaps)) whose **Check** is a command
  or an HTTP response (`pnpm check-types`, `curl`) rather than a test. This is a deliberate
  departure from the "test that goes green" wording in `AGENTS.md`'s [fill-in] section, approved by
  Ari for these two gaps; `AGENTS.md` itself is unchanged.

## Test approach (written first, watched fail, then made green)

The testable logic is pure functions and the fetch wrapper. Async Server Components are **not**
unit-tested (style guide: "Don't try to unit-test an `async function Page()`"); Playwright is
deferred to after B5. So B2's rendered pages are verified by build output and HTTP checks (see
Verification), and the plan says so plainly rather than pretending the tests cover them.

All new frontend tests run under the Vitest setup from B1 (node environment).

### 1. Python: `GET /metro` (`apps/api/app/tests/test_routers.py`)
- `/metro` returns 200 with `id`, `name`, `timezone` equal to `sample_data.METRO`.
- A new OpenAPI test asserts `"/metro" in app.openapi()["paths"]` **and** that its 200 response
  references `MetroSummary`. It must *not* just add `"MetroSummary"` to the existing schema-name
  check: `MetroSummary` is already in `components.schemas`, nested in `VenueDetail`, so that
  assertion would pass before the route exists (review #5). The test guards against a dropped
  return annotation on the route.
- Red first: the route doesn't exist, so both fail (404 / path missing).

### 2. `lib/params.test.ts` — URL-state parsing (pure, no mocks)
`parseIdParam(raw)`:
- `"12"` → `12`; `"2147483647"` → valid; `"0"`, `"-1"`, `"1.5"`, `"abc"`, `"12abc"`, `""`,
  `" 12"`, `"1e3"` → `null`; `"2147483648"` and `"99999999999999999999"` → `null`. **Why the cap:**
  database ids are `int4` (`app/db/models/calendar.py`: `Mapped[int]`), so a larger id can only
  ever be a Postgres out-of-range error → 500 once the routers are DB-backed, where a 404 is right
  (review #9).

`parseDateParam(raw)` (→ `Temporal.PlainDate | null`):
- `"2026-10-08"` → that date. `"2024-02-29"` valid, `"2026-02-29"` and `"2026-02-30"` → `null`.
- `"0000-01-01"` → `null`: it passes the regex and Temporal, but the API rejects year 0 with a 422
  (verified with `TestClient`), which would surface as the error boundary instead of a 404
  (review #8). `"0001-01-01"` is accepted by the API and stays valid.
- Non-padded (`"2026-1-5"`), basic format (`"20261008"`), datetimes (`"2026-10-08T00:00"`),
  trailing junk, and `""` → `null`. **Why this list:** `Temporal.PlainDate.from` happily accepts
  basic format and date-time strings, which would make `/day/20261008` and `/day/2026-10-08T…` two
  more URLs for the same page. A strict `^\d{4}-\d{2}-\d{2}$` guard runs first, then Temporal (which already rejects
  impossible dates like `2026-02-30` for string input, whatever `overflow` says — review #14),
  then a year ≥ 1 check.

`parseCalendarFilters(searchParams)` (input is Next's
`{ [key: string]: string | string[] | undefined }`):
- empty → no filters.
- `venue=1` and `venue=1&venue=3` (a `string[]`) → `[1]`, `[1,3]`; same for `artist`.
- Invalid entries dropped individually: `venue=1&venue=abc&venue=-2` → `[1]`. Never throws —
  a stale or hand-edited bookmark must not 500.
- Duplicates collapsed; result sorted ascending (canonical form).
- `month=2026-10` → `"2026-10"`; `2026-13`, `2026-00`, `26-10`, `abc` → no month; repeated `month`
  → first valid value.
- Sorting is **numeric**: `venue=10&venue=9` → `[9, 10]` (the default `Array.prototype.sort` is
  lexicographic and would give `[10, 9]`).
- Unrelated keys ignored.

`toShowsQuery(filters)` → `{ start?, end?, venueIds, artistIds }`:
- month → inclusive first and last day (whole-month semantics, D2), including **leap February**
  (`2028-02` ends the 29th, `2026-02` the 28th) and 31-/30-day months; no month → no
  `start`/`end` (the server picks its default window). Both bounds are always sent together, so
  the API's default window and `MAX_RANGE` never apply to a month request.

`buildCalendarHref(filters)`:
- no filters → `"/"`; with filters → `"/?venue=1&venue=3&artist=7&month=2026-10"` in a fixed key order.
- **Round trip, clean input:** `parse(query(buildCalendarHref(f)))` equals `f`.
- **Canonicalization, messy input** (review #13): `build(parse(x))` for unsorted, duplicated and
  partly invalid input yields the one canonical href — e.g. `venue=3&venue=1&venue=3&venue=x` →
  `/?venue=1&venue=3`. Together the two directions are what proves filters are shareable and
  bookmarkable.
- The tests feed `parseCalendarFilters` Next-shaped records (`string | string[] | undefined`) built
  by a small test helper from a query string (repeated key → array). Whether that helper matches
  what Next really passes is checked by the HTTP matrix (`/?venue=1&venue=2` must show both
  venues' shows), not assumed.

### 3. `lib/api-url.test.ts` — base URL joining (pure)
`apiUrl(base, path, query?)`: trailing slashes stripped (`http://h/` and `http://h///` →
`http://h/shows`); repeated query keys preserved in order (`venue_id=1&venue_id=3`); `undefined`
values omitted; values URL-encoded. `lib/health.ts` is refactored to use `apiUrl`, and its
existing 11 tests must stay green unchanged.

### 4. `lib/api.test.ts` — the typed client (injected `fetch`, fixtures as response bodies)
The client takes `fetchImpl` and `baseUrl` as parameters (as `getApiHealth` does); the exported
convenience functions bind the real `fetch` and `process.env.API_BASE_URL`. Fixtures
(`lib/fixtures/*.json`) are served as `JSON.stringify`'d response bodies and the tests assert the
client returns them unchanged. **No claim that this type-checks the fixtures:** assigning imported
JSON to the generated types fails for `VenueDetail`, `ArtistDetail` and `ShowDetail` (JSON imports
widen enum fields to `string`; review #6). The guarantee that fixtures match the types is
`make contract-check` plus the fact that `generate_fixtures.py` dumps them from the Pydantic models.
- `getShows` calls `/shows` with `start`, `end`, and repeated `venue_id` / `artist_id`; omits
  absent filters; returns the parsed `ShowListResponse`.
- `getVenue` / `getArtist`: **404 → `null`** (the caller decides to `notFound()`); 200 → the record.
- Non-404 error status (500, 422) → throws `ApiError` carrying the status and path; not swallowed.
- Network failure and malformed JSON → throw `ApiError` (cause attached), with distinct messages.
- **Next's control-flow errors pass through untouched** (review #1): a `fetchImpl` that throws an
  error with `digest: "DYNAMIC_SERVER_USAGE"` makes the client reject with *that same error
  object*, not an `ApiError`. During `next build` a `no-store` fetch throws exactly this, on
  purpose, to mark the route dynamic; wrapping it fails the build whether or not the API is up, and
  no other test can see it because Vitest has no patched `fetch`. (Checked in plain Node:
  `unstable_rethrow` rethrows such an error and ignores an ordinary `TypeError`; confirming it
  also holds under Vitest is part of the stubs-first step.)
- Every request passes `cache: "no-store"` (D1) and a timeout signal — asserted with
  `objectContaining`, not `expect.anything()` (the lesson from B1's review).
- Missing base URL → throws an error naming `API_BASE_URL`.
- `getMetro`, `getVenues`, `getArtists` return their fixtures (one test each; `metro.json` is new, see below).

### 4b. `lib/metro.test.ts` — the layout's safety net (gap C below)
`getMetroOrNull(fetcher)`: success → the metro; `ApiError` → `null` (and it logs, it doesn't
swallow silently); an error with `digest: "DYNAMIC_SERVER_USAGE"` → rethrown unchanged. The third
case is what a bare `catch { return null }` gets wrong — and that mistake passes every other unit
test and then fails `next build` (review #1).

### 5. Fixtures
`apps/api/scripts/generate_fixtures.py` gains `metro.json` (a `MetroSummary`), its only consumer
being `api.test.ts`. Run `make fixtures`, then `make types` — `contract-check` must be clean.

### What is *not* covered, stated plainly
- Rendered output of the six pages and the layout (async Server Components). Covered by HTTP checks
  and a build, not by automated tests, until Playwright.
- Per-render de-duplication of `getMetro()` (React `cache()` only operates inside a server render).
  Covered by Verification 5 only.
- The build-time behaviour of Next's dynamic-usage signal. The unit tests pin that it is *rethrown*;
  that the build then passes is Verification 3 only.
- `error.tsx` / `not-found.tsx` behaviour: checked by hand.

### Tests-first caveat
`params.test.ts` and `api.test.ts` import modules that don't exist yet, so the first run is
collection errors, not assertion failures. As in A1, create empty exported-but-throwing stubs
first so the useful red state (assertions failing) is reached before implementing.

### Known gotcha to handle up front
`import "server-only"` **throws** when imported outside Next's `react-server` condition — which is
what Vitest is. `vitest.config.ts` needs an alias mapping `server-only` to an empty stub module,
or `api.test.ts` can't even load. Without the alias the failure looks like a test bug rather than a
config gap; with it, the `server-only` build-time guard in the app is unaffected.

## Implementation steps

Order matters: Python first (it unblocks the types), pure functions next, then the client, then
routes. **[written]** / **[fill-in]** follow the build plan; fill-in steps follow the protocol below.

### Working protocol for [fill-in] steps
This follows `AGENTS.md` "[fill-in] tasks — Ari types the lines that carry the lesson". For each
[fill-in] step: I write everything around the lesson (imports, types, signatures, wiring, markup,
and the tests, which stay red); the 1–3 lines that carry the lesson become `TODO(Ari)` blocks with
**Lesson / Code / Check** (listed under [TODO(Ari) gaps](#todoari-gaps)); each placeholder
`throw`s so the tests fail loudly; then I **stop and hand off** with a file:line list and the test
command. "Implement B2" does not mean fill the blocks — only a request that names a block or file
does. This corrects B1, where I implemented the fill-in items directly.

**Handoff happens on an uncommitted tree** (review #16). Red tests at handoff keep `make check`
red until Ari fills the gaps, so nothing is committed or pushed in that state and CI never sees it.
[written] steps are written complete.

### TODO(Ari) gaps
Five blocks (review #2, D5). **Fill order (code review #4): C first** — while K3 is open the root
layout throws and every route 500s, so D's and E's curl checks can't pass until C *and* E are filled
(D's own check is `pnpm check-types`). Each lesson was chosen for where the concept lives, not where the
typing is; `AGENTS.md`'s own example of a good gap is the `searchParams` → API-query mapping, which
is K1, K2. A–C sit in unit-tested code, so their Check is a test. D and E sit in pages, which
Vitest can't render, so their Check is a command or an HTTP response (D5).

- **K1 — `parseCalendarFilters` in `lib/params.ts`** (step 7).
  *Lesson:* Next hands search params over as `string | string[] | undefined` — one `venue=1` is a
  string, a repeated key is an array — and the API contract also uses repeated keys
  (`api-contract.md` §2). The URL is the state (`arch-initial.md` §4), so parsing must be total
  (bad entries dropped one by one, never a throw) and canonical (de-duplicated, numerically sorted)
  so one filter set has one URL.
  *Code:* `const asList = (v) => v === undefined ? [] : Array.isArray(v) ? v : [v];` then
  `[...new Set(asList(v).map(parseIdParam).filter((n): n is number => n !== null))].sort((a, b) => a - b)`.
  *Check:* `params.test.ts` repeated-key, drop-invalid and numeric-sort cases. Likeliest mistake:
  `.sort()` without a comparator (`[10, 9]`).
- **K2 — `toShowsQuery` month range in `lib/params.ts`** (step 7).
  *Lesson:* `month=2026-10` becomes the API's inclusive `start`/`end`; the client computes
  calendar arithmetic but consults no clock (D2, `api-contract.md` §3). Use Temporal, not `Date`.
  *Code:* `const ym = Temporal.PlainYearMonth.from(month); start = ym.toPlainDate({ day: 1 }).toString(); end = ym.toPlainDate({ day: ym.daysInMonth }).toString();`
  *Check:* leap-February, 28-, 30- and 31-day cases. Likeliest mistakes: end = first of the *next*
  month (exclusive — the API's `end` is inclusive), or a hard-coded 31.
- **K3 — `getMetroOrNull` in `lib/metro.ts`** (step 8, the v0.1-G24 item).
  *Lesson:* every page renders the root layout, so a failed metro call must not fail the shell —
  but a blanket `catch` also swallows Next's internal control-flow errors (the dynamic-usage signal
  `fetch` throws during prerender), which turns a working build into a failing one. `unstable_rethrow`
  first, then handle.
  *Code:* `try { return await fetcher(); } catch (err) { unstable_rethrow(err); console.error("[metro] unavailable:", err); return null; }`
  *Check:* `metro.test.ts` — the digest-error case. Likeliest mistake: `catch { return null }`,
  which passes the other two cases.

- **K4 — `await props.params` in `app/venue/[id]/page.tsx`** (step 4).
  *Lesson:* in Next 16 `params` and `searchParams` are Promises with no synchronous fallback
  (`nextjs-style-guide.md`, Routing conventions and the Anti-patterns table). The route's whole
  filesystem-routing story — folder `[id]` becomes a parameter — only becomes real when the value
  arrives in the component.
  *Code:* `const { id: rawId } = await props.params;` with
  `props: PageProps<"/venue/[id]">`, then render the heading with `rawId` echoed back.
  *Check:* `pnpm check-types` (it runs `next typegen` first): using `props.params` without `await` is
  a type error. Then `curl localhost:3000/venue/7` shows `7`. Likeliest mistake: destructuring
  without `await`.
- **K5 — the fetch-and-404 flow in the same page** (step 6).
  *Lesson:* the RSC idea. `await getVenue(id)` sits directly in the component and runs on the
  server before any HTML is sent — no `useEffect`, no loading state, no client data library. And a
  miss is signalled with `notFound()`, which *throws*, producing a real HTTP 404; returning
  "not found" markup instead gives a 200 (a soft 404).
  *Code:* `const id = parseIdParam(rawId); if (id === null) notFound(); const venue = await getVenue(id); if (venue === null) notFound();`
  *Check:* `curl -s -o /dev/null -w "%{http_code}" localhost:3000/venue/1` → 200, `/venue/9999` → 404,
  `/venue/abc` → 404. Likeliest mistakes: `return <p>Not found</p>` (200), or calling `notFound()`
  inside a `try`/`catch` that swallows it.

### 1. `GET /metro` (written, Python)
- Tests first (above). New `app/routers/metro.py`: `@router.get("")` → `MetroSummary` from
  `sample_data.METRO`, prefix `/metro`, same "TEMPORARY IMPLEMENTATION — A-track swaps the body"
  comment as the sibling routers. Register in `app/main.py`.
- `make types` (new path in `api-types.ts`), `make fixtures` (adds `metro.json`).
- `api-contract.md`: add the `/metro` row to the endpoint table (milestone: B2) and `metro.json`
  to the fixtures table. Leave the other rows alone (A1 already repointed them to "after A1b").

### 2. Pure helpers (written) — `lib/params.ts` (id/date part), `lib/api-url.ts`
- Implement `parseIdParam`, `parseDateParam` and `apiUrl` to the tests in §2 and §3. Dense comments
  on the non-obvious decisions: int4 cap, strict date regex before Temporal, year ≥ 1.
- `parseCalendarFilters`, `toShowsQuery` and `buildCalendarHref` are **not** written here: they
  belong to the filters task and are scaffolded in step 7 with K1, K2.
- Refactor `lib/health.ts` to call `apiUrl`; the 11 existing tests stay green and unmodified.
- Dependencies: none new (`@js-temporal/polyfill` is installed). Import
  `{ Temporal } from "@js-temporal/polyfill"` explicitly — Node 24 has no native Temporal.

### 3. The API client (written) — `lib/api.ts`
- `import "server-only"`; add the `server-only` package; add the Vitest alias (gotcha above).
- A small `ApiError` class; one private `request<T>()` doing URL, timeout, `no-store`, status
  mapping and JSON parse. **Every `catch` around the fetch starts with `unstable_rethrow(err)`**
  (from `next/navigation`) — it must not turn Next's dynamic-usage signal into an `ApiError`
  (review #1; pinned by the pass-through test in §4); exported `getMetro`, `getShows`, `getVenues`, `getVenue`, `getArtists`,
  `getArtist`. **Not built** (no consumer in B2): `getShow`, `getCalendarMonths`.
- `getMetro` is wrapped in React `cache()` (it takes no arguments, so `cache` keys correctly). The
  other getters are not: they take object arguments, which `cache()` would compare by identity
  and never hit, and each is called once per page anyway (review #3).
- Return types are the aliases from `lib/types.ts`. A why-comment on optional-vs-null fields from
  the generated types (`api-contract.md` §7) where a page first touches one.
- Base URL read **at call time**, not module load, so tests and `next build` don't depend on
  import order.
- After this step, remove the paragraph in `apps/calendar/AGENTS.md` ("Not done … `server-only`").

### 4. Route placeholders (fill-in) — the filesystem-routing lesson
Create the six routes as **static placeholders first** (heading + the param echoed back), per the
build plan: `app/day/[date]/page.tsx`, `app/venue/[id]/page.tsx`, `app/venues/page.tsx`,
`app/artist/[id]/page.tsx`, `app/artists/page.tsx` (and `/` already exists). Seeing the URLs
resolve before any render data makes the model concrete.
- Dynamic params are a **Promise** — **K4** (`TODO(Ari)` in `app/venue/[id]/page.tsx`); the other
  dynamic pages are written complete with the same `await`. Typed with the generated
  `PageProps<"/venue/[id]">` (run `pnpm check-types` — it runs `next typegen` — after adding each
  dynamic segment).
- Header nav gains **Venues** and **Artists** links (`<Link>`), now that the targets exist.
- Verify with `next build`'s route table and `curl` status codes before moving on.

### 5. `not-found.tsx` and `error.tsx` (written)
- `app/not-found.tsx`: reached via `notFound()` for bad ids/dates and by unknown URLs.
- `app/error.tsx`: a `"use client"` component (the one place that is required — error boundaries
  must be Client Components) with `reset`. Generic message; do not render `error.message`
  (server error text is not for visitors, the same reasoning as B1's `/health` fix).
- Why now: with real fetches, an API outage is a normal event the pages must survive.

### 6. Load data in Server Components (fill-in) — the RSC lesson
Replace each placeholder with real loading, one at a time, keeping pages **plain**:
- `/venues`, `/artists`: `await getVenues()` / `getArtists()`; render a `<ul>` of `<Link>`s.
- `/venue/[id]`, `/artist/[id]`: `parseIdParam` → `notFound()` if null — **K5** is this flow in
  `/venue/[id]` (the `/artist/[id]` page is written complete to match); `await getVenue(id)` →
  `notFound()` if the client returns `null`; render the metadata fields that exist in the contract
  (and nothing for the absent ones — `api-contract.md` §6).
- `/day/[date]`: `parseDateParam` → `notFound()` if null; `getShows({start: d, end: d})`.
- Notice and comment, once, on the first page: no `useEffect`, no loading state, no client
  library — and *why* that works (the component runs on the server before any HTML is sent).
- Money/dates are strings (`api-contract.md` §4): print `admission_*` as returned, do not
  `parseFloat`; no `new Date()` anywhere. Real date/time formatting with Temporal is B3.

### 7. Filters as URL search params (fill-in) — the downstream-consequences decision
- `lib/params.ts` gains `parseCalendarFilters`, `toShowsQuery`, `buildCalendarHref`, scaffolded
  with **K1** and **K2** as `TODO(Ari)` blocks (tests red until filled). `buildCalendarHref`
  (fixed key order, `/` when empty) is mechanical and written complete.
- `/` becomes `async function Home({ searchParams }: PageProps<"/">)`:
  `parseCalendarFilters(await searchParams)` → `toShowsQuery` → `getShows` (+ `getVenues` for
  names) → render a plain list grouped by the date the server echoed, with the `start`–`end` range
  shown on the page: the "server owns now" contract made visible. Until the real endpoint computes
  its window from the metro's local date, the sample API echoes 2026-09-28 – 2026-10-25 regardless
  of today (2026-10-08 when this was written); that is correct per the contract and not a bug to
  chase during the visual check (review #12).
- Because `searchParams` is a request-time API the page is dynamic by definition (Next docs,
  `page.md`); say so in a comment so nobody "fixes" it with `force-dynamic` they don't need.
- Until B3 provides the filter header, filters change by editing the URL or following plain
  `<Link href={buildCalendarHref(...)}>` links. One demo link per venue (names from `getVenues()`)
  proves the round trip and gives B3 a working target; they are scaffolding with no consumer
  beyond that and B3 deletes them (review #15). **No** filter component, no `"use client"`.
- Empty result → one plain "No shows match these filters" line plus a reset `<Link href="/">`
  (the real empty state is B3).

### 8. Metro in the layout (fill-in) — closes v0.1-G24
- New `lib/metro.ts` with `getMetroOrNull(fetcher = getMetro)`, scaffolded with **K3**.
- `layout.tsx`: `generateMetadata()` builds the `description` from the metro name (keeping
  `title.template`) and falls back to an exported generic-description constant when the metro is
  `null`; the footer's metro name becomes a small **async child inside `<Suspense>`** with a
  neutral fallback. The layout body itself stays free of `await`.
- **Why Suspense, stated correctly** (review #4): without `cacheComponents` it does *not* keep the
  shell prerenderable — a `no-store` fetch anywhere in the root layout makes every route dynamic.
  Its real benefit is streaming: the header and page content flush before the footer's metro call
  returns. Comment it that way.
- **The shell must never fail because of the metro call** — handled by `getMetroOrNull`, not by an
  ad hoc `try/catch` in the layout.
- Remove both `TODO(v0.1-G24)` comments.

### 9. Docs and plan bookkeeping (written)
- `alpha-build-plan.md`: tick the B2 boxes; fix the stale "reading from the JSON fixtures" line and
  the v0.1-G24 caching wording (departures 1–2).
- **Correct the B1 comments that become false** (review #4): `layout.tsx` ("lets Next.js prerender
  it once and reuse it") and `app/page.tsx` ("Next.js prerenders it to static HTML at build")
  both assume a static root layout. After B2 every route is dynamic, and the comments should say
  why that is the accepted cost of D1.
- `apps/calendar/AGENTS.md`: the `server-only` note, Tailwind `@source` note stays, add the
  search-params conventions and the `lib/params.ts` / `lib/api.ts` split.
- `docs/dev/notes.md`: only if a real surprise turns up (candidates: the `server-only`/Vitest
  alias, `PageProps` typegen naming).

## Critical files

- New (Python): `apps/api/app/routers/metro.py`
- New (frontend): `apps/calendar/lib/{params,api-url,api,metro}.ts` + `.test.ts` for each,
  `apps/calendar/lib/fixtures/metro.json` (generated), `app/{day/[date],venue/[id],venues,artist/[id],artists}/page.tsx`,
  `app/not-found.tsx`, `app/error.tsx`
- Modified: `apps/api/app/main.py`, `apps/api/app/tests/test_routers.py`,
  `apps/api/scripts/generate_fixtures.py`, `apps/calendar/lib/api-types.ts` (**generated** — via
  `make types`, never by hand), `apps/calendar/lib/health.ts`, `apps/calendar/app/{layout,page}.tsx`,
  `apps/calendar/vitest.config.ts`, `apps/calendar/package.json` (+`server-only`),
  `docs/dev/api-contract.md`, `docs/dev/alpha-build-plan.md`, `apps/calendar/AGENTS.md`
- Reused as-is: `lib/types.ts`, `app/health/page.tsx`, the shadcn button (unused by B2),
  `app/sample_data.py`

## Verification

1. **Tests first.** Python and Vitest tests written, stubs created, run, and confirmed failing for
   the right reason (assertions, not import errors) before any implementation.
2. `make check` green (ruff, mypy, eslint, tsc incl. `next typegen`, pytest, vitest,
   contract-check). `make contract-check` must be clean after `make types` / `make fixtures`.
3. **Build with the API unreachable.** Point `API_BASE_URL` at a closed port and run
   `pnpm build` in `apps/calendar`. It must succeed, **and** the route table must show every data
   route *and `/_not-found`* as `ƒ`, checked by name. A green build alone proves nothing: with the
   metro fetch accidentally at the default cache setting, the build also passes with the API down
   while baking the fallback into a static `/_not-found` (review #7). So also
   `grep -rl "<the generic-description constant's text>" .next/server/app --include='*.html'`
   must find nothing. This is the acceptance test for D1 — no build-time API dependency — and, with
   the pass-through test, for review #1.
4. **HTTP matrix** against `next start` with the API up (expected status in brackets):
   `/` [200], `/?venue=1&venue=2` [200, fewer shows], `/?venue=abc` [200, ignored], `/venues` [200],
   `/venue/1` [200], `/venue/9999` [404], `/venue/abc` [404], `/artists` [200], `/artist/1` [200],
   `/artist/9999` [404], `/day/2026-10-08` [200], `/day/2026-02-30` [404], `/day/20261008` [404],
   `/day/garbage` [404], `/health` [200].
5. **De-duplication.** One page load produces exactly one `GET /metro` line in the API's access
   log (layout footer + `generateMetadata` share it through React `cache()`; Next's `fetch`
   memoization does not apply because of the timeout `signal`). *Exception found in code review #5:*
   a page that calls `notFound()` makes two (Next renders the not-found tree as a second render, and
   `cache()` is per render).
6. **API down at runtime.** Stop FastAPI: data routes (and `/`) answer **HTTP 500 with Next's bare
   `__next_error__` document** — no header, footer or `error.tsx` markup in the server HTML, because
   no `<Suspense>` boundary sits above the page, so the failure is before the first flush;
   `error.tsx` takes over only after hydration (its "Try again" is `retry()`, code review #1).
   Neither the body nor the browser shows a stack trace, the URL or `error.message` (detail goes to
   the server log). `/health` (200) and unknown URLs (404) are unaffected; after restarting FastAPI,
   pages recover without restarting Next. *Revised after code review #2:* the original expectation
   ("shell and footer still render") isn't achievable without `loading.tsx`/`<Suspense>`, which
   would make `notFound()` a 200 (D4). Accepting the bare 500 for B2 is **Ari's decision to confirm**.
7. **Visual check by Ari** in the browser: nav, each route, the filter links on `/`, a 404, and the
   metro name in the footer and tab description. `/` will show 2026-09-28 – 2026-10-25, not today's
   window — expected until the real endpoint exists (step 7).

## Not doing in B2

The filter header UI, show block component, responsive layout, Temporal-based date/time
formatting and grouping (B3); venue and artist embedded calendars, JSON-LD, day-view sort modes
(B4); `/show/[id]` and `getShow` (D3); `getCalendarMonths` and the month dropdown (B3); persistent
caching (D1; recorded as a deferred decision in `arch-initial.md` §11); `loading.tsx` (D4); `images.remotePatterns` (no images are rendered yet); component
tests and Playwright (B5); CI running `next build` (Vercel builds it; the manual build check in
Verification step 3 stands in).

## Plan review

### Round 1 — Claude Opus 5.5, October 8, 2026

Reviewed against the docs the plan cites, the committed code (B1 `2455f2c`, A1 `283564e`), and
the bundled Next 16.3 docs and source. Next.js behaviour was tested in a throwaway `git worktree`
(since removed): `next build` with `API_BASE_URL` on a closed port, `next start` against a
request-counting stub API, and `tsc` / Vitest experiments. 2 blockers, 8 should-fix, 6 nits.
Verdict: **proceed after fixes.**

**Resolutions** (Claude Sonnet 5.5, October 8, 2026): all 16 findings fixed in the plan above, none
rejected. I re-checked #3 (the `signal` opt-out in `dedupe-fetch.js:88`), #5, #8 (`TestClient`: year
0 → 422), #9 (`Mapped[int]`), #16 (committed `api-contract.md` says "after A1b") and the
`unstable_rethrow` behaviour myself; the rest are accepted on the reviewer's measurements. The two
fixes that needed Ari's decision were settled on October 9, 2026: whole-month semantics for `month`
(#10, D2: approved) and whether steps 4 and 6 are re-marked [written] (#2, D5: no, they stay
[fill-in]).

| # | Sev | Status | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|---|
| 1 | blocker | CONFIRMED | Rethrowing fetch errors as `ApiError` also catches Next's internal `DynamicServerError`, so `next build` fails | §4 "Network failure … throw `ApiError` (cause attached)"; step 3 `request<T>()`. Build: `Error occurred prerendering page "/venues"` … `[cause]: Dynamic server usage … no-store fetch` | During prerender a `no-store` fetch throws on purpose, before any network call, to mark the route dynamic. The `catch` converts that, so the build fails whether or not the API is up. Vitest can't see it (no patched `fetch`). Fix: `unstable_rethrow(err)` first in every `catch` around a fetch, including the layout's metro `try/catch`; with it the build passed with the API down | **Fixed.** `request()` and `getMetroOrNull` both start their `catch` with `unstable_rethrow(err)`; new pass-through tests in `api.test.ts` and `metro.test.ts` (an error with `digest: "DYNAMIC_SERVER_USAGE"` must come out unchanged). I confirmed in plain Node that `unstable_rethrow` rethrows such an error and ignores an ordinary one; the Vitest equivalent is checked in the stubs-first step. This is also K3. Verification 3 is the build-level check |
| 2 | blocker | CONFIRMED | The plan doesn't name its `TODO(Ari)` gaps, and marks [written] the code `AGENTS.md` gives as the example of a good gap | `AGENTS.md` "[fill-in] tasks": plans "name each [fill-in] step's `TODO(Ari)` blocks and their lessons"; its example good gap is "the `searchParams` → API-query mapping". Step 2 marks `lib/params.ts` [written] | Nobody can check the gaps are the right ones. Step 7's lesson (`parseCalendarFilters` / `toShowsQuery`) gets written in full, leaving page wiring. Gaps placed in pages (steps 4, 6, 8) have no test to turn green, so the required "Check" can't be written. Move the gaps into `params.ts` and list each | **Fixed; D5 decided by Ari.** New [TODO(Ari) gaps](#todoari-gaps) section names five blocks with Lesson/Code/Check: A and B (`parseCalendarFilters`, `toShowsQuery` — the `AGENTS.md` example gap, moved out of step 2 into step 7) and C (`getMetroOrNull`), all in unit-tested code; and D and E (`await props.params`; the fetch-and-`notFound()` flow) in steps 4 and 6. I had proposed re-marking those two steps [written] because they have no unit-testable line; Ari rejected that (the testability requirement is overstated for them), so they stay [fill-in] with command/HTTP Checks. Working protocol rewritten to match `AGENTS.md` (handoff, don't fill unasked) |
| 3 | should-fix | CONFIRMED | The timeout `signal` turns off fetch memoization: `getMetro()` costs 2 requests per page, not 1 | `next/dist/server/lib/dedupe-fetch.js:88` ("If we're passed a signal … opts out of caching"). Measured per page load: 2× `/metro` with the signal, 1× without | D1's claim and Verification 5 fail as designed. Fix: wrap the getters in React `cache()`, which keys on arguments, so the signal doesn't matter | **Fixed.** `getMetro` wrapped in React `cache()` (no arguments, so it keys correctly); other getters aren't (object args never hit; one call per page). D1 text and Verification 5 corrected — Next's `fetch` memoization is off whenever a `signal` is passed. Checked `dedupe-fetch.js:88` myself |
| 4 | should-fix | CONFIRMED | "Keep the shell prerenderable" is not a real reason for the Suspense-wrapped footer without `cacheComponents` | Build with a `no-store` metro fetch in a Suspense child: every route `ƒ`, including `/` and `/_not-found`. Step 8; B1 `layout.tsx` "lets Next.js prerender it once"; `page.tsx` "prerenders it to static HTML" | One dynamic fetch in the root layout makes the whole site dynamic. Suspense's real benefit here is streaming the footer late. Teaching point in a learning repo: correct the B1 comments in step 9 | **Fixed.** D1 now states the accepted consequence (every route `ƒ`, including `/` and `/_not-found`). Step 8 gives Suspense's real benefit as streaming. Step 9 adds correcting the now-false B1 comments in `layout.tsx` and `page.tsx` |
| 5 | should-fix | CONFIRMED | The planned `/metro` OpenAPI test would pass before the route exists | `MetroSummary` is already in `components.schemas`, nested in `VenueDetail` (`api-types.ts:309`, `:438`). Plan lines 95–97: "only a route puts it in `components.schemas`" | Adding `"MetroSummary"` to the checked tuple gives no red state. Assert `"/metro" in app.openapi()["paths"]` and that its 200 response references `MetroSummary` | **Fixed.** The Python test asserts `"/metro"` is in `openapi()["paths"]` and its 200 response references `MetroSummary`, with a note on why the schema-name check would pass before the route exists. Confirmed `MetroSummary` is already nested in `VenueDetail` (`api-types.ts:309`, `:438`) |
| 6 | should-fix | CONFIRMED | "Fixtures imported as typed JSON make the compiler check the generated types" doesn't hold | Assigning each fixture to its type: `ShowListResponse` passes; `VenueDetail`, `ArtistDetail`, `ShowDetail` fail TS2322 (JSON imports widen enum fields to `string`) | Typed assignment turns `check-types` red; going through `JSON.stringify` checks nothing. `contract-check` is the real guarantee: drop the claim, or cast with a comment | **Fixed (claim dropped).** §4 no longer says the typed-JSON import checks the types. Tests serve fixtures as `JSON.stringify` bodies and assert they come back unchanged; the real guarantee is `make contract-check` plus `generate_fixtures.py` dumping from the models. Reason recorded in §4 |
| 7 | should-fix | CONFIRMED | Verification 3 ("build succeeds with the API unreachable") passes even if the metro fetch loses `no-store` | Metro fetch at the default cache setting, API down: build succeeds, `/_not-found` is `○`, "FALLBACK" baked into `_not-found.html` | A regression ships a permanent fallback with a green build. Require `/_not-found` to be `ƒ` by name, and grep `.next/server/app/*.html` for the fallback text | **Fixed.** Verification 3 now requires `/_not-found` and every data route to be `ƒ` by name, and a `grep` of `.next/server/app/*.html` for the generic-description constant to find nothing. `getMetroOrNull` falls back to an exported constant so the grep has something to look for |
| 8 | should-fix | CONFIRMED | `/day/0000-01-01` passes the regex and Temporal; the API returns 422, so the page shows the error boundary, not a 404 | `TestClient`: `start=0000-01-01` → 422 "year 0 is out of range". Plan: 422 → throws `ApiError` | A bad URL produces an error page. Require year ≥ 1 in `parseDateParam` and add the test case | **Fixed.** `parseDateParam` requires year ≥ 1; test case `"0000-01-01"` → `null`. Confirmed with `TestClient`: year 0 → 422, year 1 → 200 |
| 9 | should-fix | PLAUSIBLE | `parseIdParam` accepts ids up to 2⁵³, but database ids are `int4` | `app/db/models/calendar.py:69` (`Mapped[int]` → `Integer`) | After A1b, `/venue/3000000000` → asyncpg out-of-range → 500, not 404. Cap at 2147483647 | **Fixed.** `parseIdParam` capped at 2147483647 (`int4`); tests at 2147483647 and 2147483648. Confirmed `Mapped[int]` on the primary keys |
| 10 | should-fix | PLAUSIBLE | Mapping `month` to a range on the client puts a "now" policy in the client, against D2's aim of settling the scheme now | Requirements: months list "only future facing"; `api-contract.md` §3 "the server owns now"; `/shows` accepts any `start` | The current month shows past days; past months are accepted; the client can't clamp to today. Decide: server owns the clamp (pass `month` through, or clamp `start`), or document whole-month semantics. `MAX_RANGE` / default window aren't traps, since both `start` and `end` are always sent | **Fixed; approved by Ari (D2).** `month` means the whole calendar month literally, past days included, with no client clock; "future only" belongs to which months the B3 dropdown offers (the server's `GET /calendar/months`). The later past-dates toggle can add a clamp. `MAX_RANGE` and the default window never apply because both bounds are always sent. Recorded in D2 and K2. Alternative if Ari prefers: server-side clamp |
| 11 | nit | CONFIRMED | Adding `loading.tsx` later (D4) turns the 404s into soft 404s that return 200 | Next docs `not-found.md:13` ("200 … for streamed responses"). Measured now: `/venue/abc` and an unmatched URL return 404 with the Suspense footer | B3 adds `loading.tsx` and the HTTP matrix's 404 rows silently become 200. Note it under D4 | **Fixed.** Noted under D4 as a B3 follow-up: once `loading.tsx` exists the 404 rows in Verification 4 must be re-checked |
| 12 | nit | CONFIRMED | The sample-data clock: `/` shows 2026-09-28 – 2026-10-25 while today is 2026-10-08 | The API's default window echoes `2026-09-28`/`2026-10-25` | Correct per the contract, but Verification 7 could mistake it for a bug; say so. No planned test depends on today's date | **Fixed.** Step 7 and Verification 7 state that `/` shows 2026-09-28 – 2026-10-25 until the real endpoint exists, and that this is not a bug. No test depends on today's date |
| 13 | nit | CONFIRMED | The round-trip property only proves `parse(build(f)) == f` for already-clean filters | §2 | Messy URLs (unsorted, duplicate, invalid) → canonical href is untested, and the test needs a hand-written URLSearchParams → `searchParams` converter that may not match Next. Add `build(parse(url))` cases | **Fixed.** Added `build(parse(messy))` canonicalization cases (e.g. `venue=3&venue=1&venue=3&venue=x` → `/?venue=1&venue=3`). The test helper's match to Next's real `searchParams` shape is verified by the HTTP matrix (`/?venue=1&venue=2`), not assumed |
| 14 | nit | CONFIRMED | `overflow: "reject"` does nothing for string input | `Temporal.PlainDate.from("2026-02-30")` throws with the default setting too | Harmless, but the comment shouldn't credit `overflow` with rejecting bad dates | **Fixed.** Dropped the `overflow: "reject"` option and its credit from the plan; the comment says Temporal rejects impossible string dates regardless |
| 15 | nit | — | "One demo link per venue" on `/` needs venue names the route table doesn't fetch | Step 7; table lists only `GET /shows` for `/` | Add `getVenues()` to `/` or take venues from the shows, and say which. The demo links are a made-up consumer for `buildCalendarHref`; acceptable, but say so | **Fixed.** `/` also calls `getVenues()` (table row and step 7 updated); the demo links are called out as scaffolding that B3 deletes |
| 16 | nit | CONFIRMED | Stale wording, and no plan for red tests at handoff | Step 1: "Do not touch the 'A-track, after A1' cells — A1's plan repoints those"; committed `api-contract.md` already says "after A1b" | Remove the sentence. Red tests at a [fill-in] handoff keep `make check` / CI red until the gaps are filled: say whether handoff happens on an uncommitted tree | **Fixed.** Removed the stale sentence; the handoff policy is now explicit — [fill-in] handoff happens on an uncommitted tree, red tests keep `make check` red until Ari fills the gaps, and nothing is committed in that state |

**Claims checked.** D1 / `no-store`: verified with conditions (#1, #7; `force-cache` prerenders `/`
and `/_not-found` at build and bakes in the fallback, and a fetch with no cache option also runs at
build). Memoization: wrong as designed (#3). `searchParams` makes `/` dynamic: verified (`ƒ`).
`server-only` under Vitest needs an alias that doesn't weaken Next's guard: verified. Temporal:
verified; Node 24.19 has no global `Temporal` (#14). `PageProps<"/">` / `PageProps<"/venue/[id]">`:
verified with `next typegen` + `tsc`. `error.tsx` must be a Client Component, and `notFound()` /
unmatched URLs both 404: verified (Suspense rationale is #4). `/metro` needs only a route: partly
wrong (#5). `health.ts` refactor keeps its 11 tests: verified by reading. Route table vs docs:
mostly matches; the gaps are `/show` (D3) and `month` (#10).

**On D1–D4.** D1: agree, with `unstable_rethrow` (#1), `cache()` (#3), and `/_not-found` as `ƒ` as
the acceptance check (#7). D2: agree once #10 is decided. D3: agree. D4: agree, recording #11.

**Not checked:** `contract-check` after adding `/metro` (needs the implementation); the id overflow
against A1b's database-backed routers (not built); Vercel's build as opposed to a local
`next build`. `server-only` was tested using the copy bundled inside Next (same package, `0.0.1`),
because it wasn't in the offline pnpm store.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 9, 2026

**Scope.** Uncommitted working tree on top of `283564e` (A1). Review with `git status` / `git diff` plus the untracked files below. Nothing committed (Ari hasn't asked, and red gap tests would keep CI red).

- Python: `apps/api/app/routers/metro.py` (new), `app/main.py`, `app/tests/test_routers.py`, `scripts/generate_fixtures.py`.
- Generated: `apps/calendar/lib/api-types.ts`, `lib/fixtures/metro.json` (via `make types` / `make fixtures`).
- Frontend lib: `lib/{params,api-url,api,metro}.ts` + `.test.ts` for each (new); `lib/health.ts` (now uses `apiUrl`; its 11 tests untouched and green); `vitest.config.ts`; `test/server-only-stub.ts` (new); `package.json` + `pnpm-lock.yaml` (`server-only`).
- Frontend app: `app/{layout,page}.tsx` (modified); new `app/{venues,artists}/page.tsx`, `app/{venue,artist}/[id]/page.tsx`, `app/day/[date]/page.tsx`, `app/not-found.tsx`, `app/error.tsx`, `app/_components/plain-show-list.tsx`.
- Docs: `docs/dev/{api-contract,alpha-build-plan,notes}.md`, `apps/calendar/AGENTS.md` (the "Not done … `server-only`" paragraph removed, "Where data and URL state live" added).
- Not mine, present in the tree before I started: `AGENTS.md`, `docs/arch/arch-initial.md` (modified), `.claude/`, `a2-extraction-schema.md`.

**Departures from the plan.**
1. **`createApiClient` is the injectable seam; `getMetroOrNull(fetcher = getMetro)` imports `./api`**, so `metro.test.ts` loads `api.ts` (through the `server-only` alias). The plan said the same default; noting it because it makes `lib/metro.ts` transitively server-only.
2. **`CalendarFilters.month` is `string | null`** (plan said "no month"). Chosen so `toEqual` against `{…, month: null}` is explicit.
3. **`parseMonthParam` is exported and tested directly**, and `parseIdParam` also rejects leading zeros (`"012"`): both additions beyond the plan's list, for the same one-URL-per-state reason. `parseMonthParam` also requires year ≥ 1 (the API rejects year 0).
4. **`siteDescription(metro)` added to `lib/metro.ts`** (with a test) so the fallback/`FALLBACK_DESCRIPTION` logic is unit tested rather than living inline in `layout.tsx`.
5. **`PlainShowList` (`app/_components/`)** is a small shared throwaway used by `/` and `/day/[date]` rather than two copies; B3 deletes it.
6. **K4/E scaffold uses a `todo<T>()` helper** at the bottom of `app/venue/[id]/page.tsx` so the rest of the page (the markup) stays complete and type-checks; the TODO blocks say to delete it when filled.
7. `error.tsx` shows `error.digest` ("Reference: …") when present — a safe opaque id, not `error.message`.
8. Page `metadata` titles on detail pages are static ("Venue", "Artist", "Day"), not name-bearing; making them name-bearing needs a second fetch or sharing one, which is B4.

**`TODO(Ari)` gaps (all five open — none filled by anyone).** Review the code as it stands; open gaps aren't findings.
- K1 — `parseIdList` in `lib/params.ts`
- K2 — `monthRange` in `lib/params.ts`
- K3 — `getMetroOrNull` in `lib/metro.ts`
- K4 — `await props.params` in `app/venue/[id]/page.tsx`
- K5 — fetch-and-`notFound()` flow in `app/venue/[id]/page.tsx`

**Verification.**
- Tests first: Python `test_metro_returns_the_live_metro` and `test_openapi_exposes_the_metro_route` watched fail (404 / path missing) then pass. Frontend: stubs first, so the red state was assertion failures (83 failed / 11 passed), then implemented.
- `make lint` 0, `make typecheck` 0 (ruff, mypy, eslint, `next typegen` + tsc), `make contract-check` "current".
- Vitest with the five gaps open: **78 passed, 16 failed**; the 16 failures are exactly the gap tests (`metro.test.ts` ×3, `params.test.ts`: `parseCalendarFilters` ×5, `toShowsQuery` ×6, two `buildCalendarHref` cases that parse). Everything else, including the 11 `health.test.ts` tests, is green. Mutation check: removing `unstable_rethrow` from `api.ts`'s `send()` makes the "dynamic-usage signal" test fail (restored).
- **Gap snippets validated.** I temporarily applied the five `Code:` snippets exactly as written in the TODO blocks, ran everything, then restored the scaffold byte-for-byte (SHA-checked): Vitest 94/94, lint and tsc clean. So each snippet is correct, and the open-gap state is the only reason `make check` is red.
- With the snippets applied (not in the delivered tree): **V3** `API_BASE_URL=http://127.0.0.1:9 pnpm build` succeeded; route table: `/`, `/_not-found`, `/artist/[id]`, `/artists`, `/day/[date]`, `/health`, `/venue/[id]`, `/venues` all `ƒ`; grep of `.next/server/app/*.html` for the fallback text found nothing (only `_global-error.html` exists). **V4** the 16-row HTTP matrix against `next start`: all as planned, and `/?venue=1&venue=2` shows 11 shows = 6 (venue 1) + 5 (venue 2), `/?venue=abc` shows all 21 (so the test helper's `string | string[]` shape matches what Next passes). **V5** exactly one `GET /metro` per page load (`/venues` and `/`). **V6** with FastAPI stopped: data routes 500 with no `ApiError`, URL, or env-var text in the body (detail only in the server log), `/health` 200, `/nope` 404, the `<meta description>` fell back to the generic text; after restarting FastAPI, pages recovered with no Next restart.
- **Python full suite:** `REQUIRE_DB=1 uv run pytest` was **66 passed** earlier in the session. At the end of the session Docker's daemon stopped responding (`docker info` 500s/hangs), so the 18 DB tests error with "Postgres not reachable"; the 48 non-DB tests pass. No B2 change touches the DB. **`make check` was therefore not run to completion** (red on the open gaps by design, and the DB suite unavailable at the end).
- **Not verified:** V6's "shell and footer still render, error boundary visible" and V7 (visual check) need a browser; I have none. Observed instead: when the page's fetch fails, the **server response is Next's bare `__next_error__` document with HTTP 500** (title and description present, no header/footer in the HTML), because no `<Suspense>`/`loading.tsx` wraps the page; `error.tsx` can only take over after hydration. That's Next's behaviour for an error before the first flush, and it relates to D4 (a `loading.tsx` would stream the shell first). Ari should look at this in the browser.

**Where to look hardest.**
1. `lib/api.ts` `send()` / `readJson()`: that every `catch` around a fetch or body read starts with `unstable_rethrow`, and that `AbortSignal.timeout` also covers the body read.
2. `lib/params.ts` `parseDateParam` / `parseIdParam` / `parseMonthParam` edge cases (the three-layer date check; regex vs Temporal).
3. `app/layout.tsx`: `generateMetadata` + `<MetroName>` sharing one request via React `cache()` on `getMetro` (verified once per load), and that the comments about Suspense and D1 are now true.
4. The V6 behaviour above: is a bare 500 document, with `error.tsx` only after hydration, acceptable until B3's `loading.tsx`?
5. The scaffold: are K1–K5 the right lines, and do the TODO blocks' `Code:` snippets fit the surrounding code?

## Code review

### Round 1 — Claude Opus 5.5, October 9, 2026

**Scope.** Implementation log round 1: the uncommitted working tree on top of `283564e`. I reviewed the
files the log lists (Python router, test and fixture script; `lib/{params,api-url,api,metro}.ts` and
their tests; `test/server-only-stub.ts`; `vitest.config.ts`; the six routes, `layout.tsx`,
`not-found.tsx`, `error.tsx`, `_components/plain-show-list.tsx`; the doc edits). I left out
`AGENTS.md`, `arch-initial.md`, `.claude/` and `a2-extraction-schema.md`, which the log says aren't part of B2.
I checked the code against the plan, `nextjs-style-guide.md` (including its Anti-patterns table), `AGENTS.md`
conventions, and the bundled Next 16.3.0 docs and source in `node_modules/next`.

**What was run.**
- `make check` in the real tree stops at pytest: 48 passed and 18 errors, all "Postgres not reachable"
  (Docker was down, as the log says). `make lint` 0, `make typecheck` 0, `make contract-check`
  "current". Vitest: **16 failed / 78 passed**, and every failure is a gap test (A, B or C). Matches the log.
- I made a throwaway `git worktree` holding a copy of the working tree, installed with
  `pnpm install --offline`, and removed the worktree afterwards. There I applied the five `Code:` snippets
  exactly as written. Results: Vitest 94/94, `pnpm check-types` and `pnpm lint` clean, so the snippets fit
  the code around them. **V3:**
  `API_BASE_URL=http://127.0.0.1:9 pnpm build` succeeded, all 8 routes including `/_not-found` were `ƒ`,
  and the only HTML file was `_global-error.html`, so the grep for the fallback text found nothing. **V4:**
  `next start` against a live uvicorn returned the expected status on all 16 rows. I added `/venue/012`,
  `/day/0000-01-01` (both 404) and `/?month=2026-02` (200, "Showing 2026-02-01 to 2026-02-28"). The demo
  links keep `month` (`/?venue=1&month=2026-10`). **V5:** see #5. **V6:** see #2.
  Also checked in plain Node (CONFIRMED): `AbortSignal.timeout` covers the body read. A server that sends
  headers and then stalls makes `response.json()` reject with a `DOMException` named `TimeoutError`, which
  is the case `readJson` relies on (log "where to look" 1).
- With K3 reverted to its scaffold, `next build` fails (see #4).

**Answers to "where to look hardest".**
1. Every `catch` around a fetch or a body read starts with `unstable_rethrow`. The timeout covers the body read.
2. The edge cases in `params.ts` hold, and the tests cover them.
3. `cache()` sharing works on pages that render (one `/metro` per load), but not on 404 pages (#5). The Suspense and D1 comments are accurate.
4. The bare 500 document is real; see #2.
5. K1–K5 sit where the concept lives, and their snippets fit. The one gap problem is the ordering between gaps (#4).

**Counts:** 0 blocker, 3 should-fix, 4 nit. **Verdict: proceed after fixes.**

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | `error.tsx`'s "Try again" calls `reset()`, which in Next 16.3 re-renders the segment **without re-fetching**. Every error B2 can produce comes from a server fetch, so the button can never recover. The Next 16.3 prop for this is `retry`. The style guide's stale wording is probably the source | CONFIRMED (docs + source; button not clicked in a browser): `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md` §`reset`: "In most cases, you should use `retry()` instead … re-render … without re-fetching". Version history: "`v16.3.0` `retry` prop became stable". `next/dist/client/components/error-boundary.js:39-48`: `reset` is `setState({error:null})`, while `retry` is `context.refresh()` then `reset()`. `app/error.tsx:21,39`. `nextjs-style-guide.md:491` says "(a Client Component receiving `error`/`reset`)" | After the API comes back, clicking "Try again" renders the cached failed payload again and shows the same error. The user has to reload the page. This repo's whole point is teaching current Next, and the style guide would keep handing out the stale prop. Fix: take `retry` and call `retry()`, and update the comment. Also correct `nextjs-style-guide.md:491` to `error`/`retry` and note `reset`'s narrower meaning (a style-guide change, so tell Ari) | **Fixed.** Re-checked `error.md` (`retry` stable in 16.3.0) and `error-boundary.js`. `app/error.tsx` now takes `retry` and calls `retry()`; the comment explains why `reset()` can't recover from a failed server fetch. `nextjs-style-guide.md:491` corrected to `error`/`retry` — **a style-guide edit, flagged to Ari**. Not click-tested in a browser. Also recorded in `notes.md` |
| 2 | should-fix | Verification 6 isn't met as the plan wrote it. With the API down, `/`, `/venues` and `/venue/1` return HTTP 500 with Next's bare `<html id="__next_error__">` document: no header, nav, footer or `error.tsx` markup in the HTML. The log reports this. It needs a recorded decision, not just "Ari should look in the browser" | CONFIRMED (curl against `next start`, API stopped): `500 /`, `500 /venues`, `500 /venue/1`, `404 /venue/abc`, `200 /health`, `404 /nope`. The `/venues` body contains `__next_error__`, `<meta name="robots" content="noindex">` and the fallback description, and none of "Venues</a>", "Status</a>" or "Something went wrong". Plan V6 expected "data routes show the error boundary … `/` shell … still render". React's server renderer doesn't run error boundaries, and with no `<Suspense>` above the page the shell itself errors | Without JS, or until hydration, a visitor (or crawler) gets a blank page during an outage, and `/` is down as well (its `getVenues()` call exists only for the demo links). The obvious fix, `loading.tsx` or `<Suspense>` around `{children}`, turns `notFound()` into a soft 404 that returns 200 (review #11, D4). That trade-off is **Ari's call**. Recommendation: accept it for B2 and write it down where it lives: update V6's expected result, add a sentence to D4's B3 note that `loading.tsx` also fixes this, and add a `notes.md` entry, since it's exactly the kind of non-obvious behaviour that file is for | **Fixed (documented); decision is Ari's.** No code change: I applied the reviewer's recommendation to accept the bare 500 for B2. Verification 6 rewritten to the actual behaviour (bare `__next_error__` 500, `error.tsx` after hydration, no leaks, `/health` and 404s unaffected, recovery without restart); D4's B3 note now says `loading.tsx`/`<Suspense>` would also fix it, at the cost of soft 404s; new `notes.md` entry. **Ari should confirm accepting this (or choose `loading.tsx` now)** |
| 3 | should-fix | About 16 tests have no `Proves:` comment, against the `AGENTS.md` rule "Every test opens with a comment beginning `Proves:`" | CONFIRMED (read): `api.test.ts:57, 86, 117, 129`; `metro.test.ts:11, 46`; `params.test.ts:109, 122, 166, 209, 224`; `api-url.test.ts:7, 29, 42, 48`. Others (e.g. `params.test.ts:130`, `api.test.ts:138`) follow the rule, and the Python tests do too | A reader can't tell what some tests pin. One example: `api.test.ts:86` is what proves "the server owns now" for the no-filter case, and it doesn't say so. Add a one-line `Proves:` to each test. Comment-only, so snapshot the files and compare syntax trees as `AGENTS.md` asks | **Fixed.** Added `Proves:` comments to the 16 listed tests (`api.test.ts` ×4, `api-url.test.ts` ×4, `metro.test.ts` ×2, `params.test.ts` ×5, plus rewording `Proves (with…` to `Proves:` on the round-trip test). Comment-only: snapshotted the four files, compiled before/after with comments removed (TypeScript `transpileModule`, `removeComments`), output identical for all four. `health.test.ts` (B1) was out of scope and left alone |
| 4 | nit | The gaps depend on each other's order, and nothing says so. While K3 is open, every route returns 500 (including `/health` and `/nope`, because the root layout's `generateMetadata` throws), and `next build` fails. So K4's Check ("`curl localhost:3000/venue/1` shows the venue") and K5's curl checks can't pass until C *and* E are filled | CONFIRMED: build with K3 at its scaffold → `Error occurred prerendering page "/_not-found"` … `Error: TODO(Ari)` … `lib/metro.ts:62`. `app/venue/[id]/page.tsx:25-27` (K4's Check depends on E) | Ari fills D, runs its curl Check, gets a 500 for every URL, and looks for a bug in his own line. Fix: in the handoff and the K4/E Check text, say to fill C first, and that D's curl check needs E too. As a stand-alone check for D, `pnpm check-types` is enough | **Fixed.** The plan's gap section now says to fill **C first**, and that D's own check is `pnpm check-types` while its curl check needs C and E; the K4 and E `Check:` text in `app/venue/[id]/page.tsx` says the same (comment-only edit; the scaffold's code is unchanged). Repeated in the handoff |
| 5 | nit | `getMetro`'s `cache()` de-duplication holds for pages that render and for unmatched URLs, but a page that calls `notFound()` makes **two** `/metro` requests. The code comments and Verification 5 claim one per page load | CONFIRMED (uvicorn access-log deltas): `/`, `/venues`, `/venue/1`, `/nope` → 1 each; `/venue/abc`, `/venue/9999`, `/day/garbage` → 2 each. PLAUSIBLE cause: Next renders the not-found tree in a second render, and React `cache()` is scoped to one render. `layout.tsx:33-34` ("one API request per render") and `lib/api.ts:207-209` | Harmless, since the call is cheap. But it's the measured number this plan is about, and the next person to count requests will think `cache()` broke. Add a sentence to the `api.ts` comment and V5 rather than changing code | **Fixed (comments, no code).** Added the two-requests-on-`notFound()` caveat to the `getMetro` comment in `lib/api.ts`, the `generateMetadata` comment in `layout.tsx`, and Verification 5. I did not re-measure; the cause is the reviewer's PLAUSIBLE reading (second render), the counts are theirs |
| 6 | nit | The new `/metro` row in `api-contract.md` §2 gives its milestone as "B2". The route serves sample data until A1b, like every other row ("A-track, after A1b") | CONFIRMED (read): `api-contract.md:40`; `app/routers/metro.py` docstring ("TEMPORARY IMPLEMENTATION … A1b swaps the body"). The section's lead-in, "Not implemented yet", is stale for all rows | Someone reading the contract to plan A1b may skip `/metro` as already finished. Fix: "B2 (sample data); DB-backed in A1b". Optionally also correct the "Not implemented yet" lead-in | **Fixed.** `/metro` row now reads "B2 (serves sample data; DB-backed in A1b)"; the stale "Not implemented yet" lead-in is replaced with a sentence saying all routes exist over sample data and `A-track, after A1b` means the body becomes a query then |
| 7 | nit | Two comment slips | CONFIRMED (read): `app/page.tsx` header says "Before B1's placeholder this page was static; it is not any more", but it was B1's placeholder itself that was static. `app/_components/plain-show-list.tsx:23-24`: a reflow merged two sentences onto one overlong line ("…on /day/[date]), so it isn't repeated per row. `start_time` is …") | Small, but this is a learning repo and both comments explain *why*. Reword the first to "B1's placeholder was static; this page is not". Reflow the second | **Fixed.** `app/page.tsx` comment reworded ("B1's placeholder was static; this page is not"); the merged sentences in `plain-show-list.tsx` split onto separate paragraphs |

**Resolutions** (Claude Sonnet 5.5, October 9, 2026): all 7 findings fixed (#2 by documenting the behaviour, pending Ari's confirmation).

Rejected: none.

Test-suite result after the fixes: `make lint` 0 (ruff, eslint); `make typecheck` 0 (mypy, `next typegen` + tsc); `make contract-check` "current"; Vitest **78 passed, 16 failed**, the 16 being exactly the open-gap tests (A, B, C) as before; pytest 48 passed, 18 DB tests skipped/unavailable because Docker's daemon is down (the full suite was 66 passed earlier in the session, before Docker stopped). `make check` therefore remains red by design until Ari fills the gaps; it was not run end to end. Findings #1, #3 and #7 are not unit-testable (client component; comment-only), so no failing-test-first for them; #5 and #6 are comment/doc edits.

