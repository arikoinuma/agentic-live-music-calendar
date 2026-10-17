<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

---

<!--
Everything below is hand-written and sits OUTSIDE the managed block above.
`next dev` rewrites only the region between its BEGIN/END markers, so content
here survives. Don't move it above the END marker.
-->

# apps/calendar — the public Next.js app

**Read `docs/references/nextjs-style-guide.md` before non-trivial work here.** It's written
against Next.js 16.3 / React 19.2 / Tailwind 4, all of which changed recently enough that
training-data defaults are frequently wrong. Its Anti-patterns table is the review checklist.
The block above says the same thing about `node_modules/next/dist/docs/`, and means it.

## Commands

From the repo root: `make dev` (with the API) or `make web` (alone). Port 3000.

```
pnpm --filter calendar dev
pnpm lint            # eslint directly — `next lint` was REMOVED in 16, don't add it back
pnpm check-types     # next typegen && tsc --noEmit
```

Run `pnpm check-types` after adding or renaming a dynamic route segment — `next typegen`
regenerates the `PageProps`/`LayoutProps` helpers.

## The API contract

`lib/api-types.ts` is **generated** from FastAPI's OpenAPI schema. Never edit it. Run
`make types` from the repo root after the backend's models change; `make contract-check`
fails if it's stale.

Import from `lib/types.ts`, which aliases the generated shapes to readable names. Three
things about them:

- Dates and times are `string`. Parse with `Temporal.PlainDate`/`PlainTime`, never
  `new Date("2026-09-28")` — that parses as UTC midnight and renders as the 27th anywhere
  west of Greenwich.
- `Decimal` is `string` ("15.00"), not a number. Format it; don't `parseFloat` it.
- Fields with Python-side defaults generate as optional, so they're `T | null | undefined`.

`lib/fixtures/*.json` exists for tests that shouldn't need a running backend. Prefer real
HTTP against the API for anything else — the routes exist and serve the same data.

## Where data and URL state live

- `lib/api.ts` is the only code that talks to FastAPI. It is `server-only` (it reads
  `API_BASE_URL`, which must never reach a browser bundle), every request is `no-store`
  with a timeout, and `getVenue`/`getArtist`/`getShow` return `null` on 404 so the page can call
  `notFound()`. `getMetro`, `getVenue`, `getArtist` and `getShow` are wrapped in React `cache()` (their arguments are
  primitives, so it keys by value): a detail page's `generateMetadata` and its body share one API request per
  render. `getShows` takes an object, so it isn't wrapped. Tests use `createApiClient({ baseUrl, fetchImpl })` with a fake `fetch`.
- `lib/params.ts` is the other half: pure parsing of URL state. **Path params**
  (`parseIdParam`, `parseDateParam`) return `null` for anything non-canonical → the page
  calls `notFound()`. **Search params** (`parseCalendarFilters` → `toShowsQuery`, and
  `buildCalendarHref` back) never throw: bad entries are dropped, the result is
  canonical (de-duplicated, numerically sorted), so one filter set has one URL. Keys:
  `venue`, `artist` (repeatable ids) and `month=YYYY-MM` (the whole calendar month).
  Two more search params, each on one page and each parsed to a canonical value or ignored:
  **`?from=YYYY-MM-DD`** on `/venue/[id]` (`parseFromParam`) moves the venue calendar's window, and
  **`?sort=time|artist`** on `/day/[date]` (`parseDaySort`; the default view is the bare URL, so each view has one
  URL). The artist page takes **no** search params: it asks the API for `upcoming: true` (every show from the
  server's today on), so a stray `?from=` there is ignored.
- **The client never computes a date window.** The venue page sends only a `start`; the API fills `end` and echoes
  what it served, and `lib/calendar-window.ts` builds the Earlier/Later links from that echo. `upcoming` is exclusive
  with `start`/`end` and needs a `venue_id` or `artist_id` — the server answers 422 otherwise.
- `lib/calendar-href.ts` holds `CalendarFilters`, `buildCalendarHref`, `withIds` and `hasActiveFilters` — the
  **Temporal-free** half of URL state, re-exported from `params.ts`. A Client Component
  must import from here, never `params.ts` or `lib/dates.ts`: both pull the ~36 KB gzipped
  Temporal polyfill into the browser bundle. (Check: `grep -rl "Do not use built-in
  arithmetic operators with" .next/static` after a build must find nothing.)
- `lib/detail-format.ts` (`httpUrlOrNull`: **every URL rendered from scraped data goes through it** — website,
  source, images, the JSON-LD `image`; label maps for the enums; `mapsUrl`), `lib/json-ld.ts` (schema.org events:
  `startDate` carries the metro's UTC offset, an unstated price is *no* `offers`, and `jsonLdScriptContent` escapes
  `<` because names are scraped text printed inside a `<script>`), `lib/show-order.ts` (the day view's orderings)
  and `lib/calendar-window.ts` are B4's pure, tested modules.
- `lib/dates.ts` (Temporal formatting, `metroToday`, the 5:00 AM after-midnight rule),
  `lib/calendar.ts` (shows → date rows → venue columns) and `lib/show-format.ts` (prices and
  admission) are the calendar's pure, tested core. A show's own date and time are wall-clock
  strings with **no timezone** — the metro's zone is needed only to ask what "today" is.
- `app/_components/calendar-results.tsx` is the synchronous half of the home page: the calendar, or the
  "No matches found" / "No shows listed" message. It exists so that branch is testable (B5-D1); `CalendarBody`
  in `app/page.tsx` only fetches.
- The calendar's one Client Component is `app/_components/filter-header.tsx`. It holds no
  results: a selection calls `router.push` with the new URL and the server page re-renders.
- Every API call logs one line to the Next server's terminal from `send()` in `lib/api.ts`:
  `[api] GET /shows?venue_id=3 -> 200 in 41ms` (or `-> failed (timed out) in …ms`). It's how you
  see server-to-server requests the browser's Network tab can't. It
  writes path and query only, never the base URL, and it must never be able to throw — it runs
  inside the error path (`api.test.ts`, "request log"). Each 2xx body also gets a one-line
  **summary** (`[api] GET /shows?venue_id=3 body (2.0 KB): 6 shows (…); 0 without start_time; …`,
  built by the pure functions in `lib/api-log.ts`), and `LOG_API_BODIES=1` in `.env.local`
  adds the full JSON on one line. The flag is ignored when `NODE_ENV` is `production`: hosted
  logs get summaries only. Summary lines carry their own `GET <path>` because the page's five
  calls run in parallel and their lines interleave.
- Vitest aliases `server-only` to an empty stub (`test/server-only-stub.ts`); the real
  package throws outside Next's `react-server` condition.
- **Never wrap a `fetch` in a `catch` without `unstable_rethrow(err)` first.** During
  `next build` a `no-store` fetch throws a dynamic-usage error on purpose, and a bare
  `catch` turns it into a build failure (`docs/dev/notes.md`).
- Every route is dynamic (`ƒ`) in B2: the root layout fetches the metro with `no-store`
  (decision B2-D1). `next build` therefore doesn't need the API running.
- **Images:** the one place a remote image is rendered is `app/_components/remote-image.tsx` (a plain `<img>`,
  `no-referrer`, lazy, height-capped, http(s) only), and it carries the app's **only**
  `@next/next/no-img-element` exception (B4-D4; `grep -rn no-img-element app` should find one line). Show blocks
  render no images; the show page, venue page and artist page do.
- **`sr-only` inside the calendar's scrollers needs a positioned ancestor** (`relative` on its link), and values in a
  `grid-cols-[auto_1fr]` list need `min-w-0 [overflow-wrap:anywhere]` — both widen the *page* otherwise
  (`docs/dev/notes.md`).
- `/` streams (B3-D4): its API-dependent body sits inside a `<Suspense>` in the
  page, not a root `loading.tsx`, because streaming makes `notFound()` answer 200 (a soft
  404) and the detail routes need real 404s. With the API down `/` is a 200 with the shell
  and a skeleton; the detail routes are still B2's bare 500.

## Rules that bite most often here

- **Server Components by default.** `"use client"` goes on the smallest interactive leaf,
  never on a page or layout to make one widget work.
- **No `useEffect` + `fetch` for initial data.** Fetch in the Server Component and pass it
  down. That's the single most common stale-training-data pattern.
- **`params` and `searchParams` are Promises.** `const { slug } = await props.params`.
  No synchronous fallback exists in 16.
- **`fetch` is not cached by default** (since 15). Opt in: `{ cache: "force-cache",
  next: { revalidate, tags } }`. This repo is on the **default** caching model —
  `"use cache"` is a Cache Components feature and errors without the flag.
- **Filter and view state goes in URL search params**, not component state
  (`arch-initial.md` §4). It's what makes a filtered calendar shareable and
  server-renderable.
- **`proxy.ts`, not `middleware.ts`** — renamed in 16.
- **Generate shadcn components** with `pnpm dlx shadcn@latest add <name>`; don't hand-roll
  something that has to match the CVA setup `components.json` expects. Shared primitives go
  in `packages/ui` and import as `@repo/ui/components/<name>`.

## Known state and open cleanups

B1 stripped the `create-turbo` template (`docs/dev/alpha-build-plan.md`): Tailwind is the
only styling system and the root layout has real metadata and chrome. B2 added the six routes
(`/`, `/day/[date]`, `/venue/[id]`, `/venues`, `/artist/[id]`, `/artists`), `not-found.tsx`,
`error.tsx` and the API client. B3 built the calendar on `/` (grid, show block, filter header,
empty state) and gave `/day/[date]` the same show blocks. B4 finished the detail pages: the venue page (metadata,
Maps link, its calendar with paging, JSON-LD), the artist page (every upcoming show), the day view's three
orderings, and the new `/show/[id]` with Event JSON-LD; `/venues` and `/artists` stayed as B2 built them.
`/health` is the diagnostics page.

- Tests: `pnpm test` (Vitest). **The file extension picks the environment** (B5): `*.test.ts` runs
  in node (the pure `lib/` code), `*.test.tsx` runs in jsdom with Testing Library and jest-dom
  (`vitest.config.ts`, `test/setup-dom.ts`). Component tests sit beside the component.
  Conventions: query by role and accessible name (`getByRole`, `getByLabelText`), never a class or
  `data-slot`; use `userEvent`, not `fireEvent` (Base UI's combobox doesn't open for a bare
  `fireEvent.click`); mock only `useRouter` from `next/navigation` (with `vi.hoisted`) and assert the
  whole pushed URL with `toHaveBeenCalledExactlyOnceWith`; assert absence with `queryBy*`; no
  snapshot tests. **Don't unit-test async Server Components** (style guide, Testing): pull the
  synchronous part out instead, as B5 did with `CalendarResults`, and test that. A JSON-LD-style test
  that depends on how the SERVER's HTML is parsed must render with `react-dom/server` and parse the
  result with `DOMParser`, not use Testing Library's client `render` (`json-ld.test.tsx`).
- Shared-package imports go through `packages/ui/package.json` `exports`, not its
  tsconfig `paths` — a new folder of `.ts` files under `packages/ui/src` needs its own
  `exports` entry (`docs/dev/notes.md`).
- Tailwind doesn't scan `packages/ui`, so `app/globals.css` has
  `@source "../../../packages/ui/src";` (three `..`: the path is relative to the CSS file in
  `app/`; an earlier version of this note said two and was wrong — `docs/dev/notes.md`).
  The shadcn CLI must be run from `packages/ui`, and needs its output fixed afterwards
  (same file).
