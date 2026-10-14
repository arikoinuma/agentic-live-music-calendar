# Debugging the app: a guided trace

**Status:** written for B3 (October 12, 2026), after Ari asked how to trace through the
Next.js side with real breakpoints. The server-side half was checked by attaching a debugger to
`next dev --inspect` and hitting a breakpoint in `lib/api.ts`; the VS Code UI itself was not
(see [What was and wasn't verified](#what-was-and-wasnt-verified)).

Goal: follow one page load — `/?venue=3` — from the URL, through Next.js, to FastAPI and back, with
breakpoints, and understand why the browser's Network tab shows none of it.

---

## 1. The mental model: three processes

```
  Browser (Chrome)            Next.js server (Node, :3000)          FastAPI (Python, :8000)
  ──────────────────          ───────────────────────────           ───────────────────────
  shows HTML, runs the        runs app/page.tsx, layout.tsx,        runs app/routers/shows.py,
  "use client" code           lib/api.ts, lib/calendar.ts,          returns JSON
  (the filter header)         the Server Components
        │                              ▲   │
        │   GET /?venue=3              │   │  GET http://localhost:8000/shows?venue_id=3
        └──────────────────────────────┘   └───────────────────────────────────────────────►
```

**The browser never talks to FastAPI.** `lib/api.ts` is `import "server-only"` and reads
`API_BASE_URL`, which has no `NEXT_PUBLIC_` prefix, so it cannot exist in a browser bundle. A Server
Component such as `app/page.tsx` is just a function that runs **on the Next.js server**, `await`s
the API, and sends back finished HTML. That is the whole reason the inspector shows nothing: those
requests are server-to-server.

What the browser's Network tab **does** show (checked in a real browser against this app):

| When | Request | Meaning |
|---|---|---|
| Opening the page | `GET /` — type *Document* | The full HTML, already containing the shows |
| Picking a filter | `GET /?venue=3&_rsc=…` — type *Fetch*, request header `RSC: 1` | "Re-render this URL on the server and send me the result." The response is React's component payload, not JSON from your API |

One filter pick = one request to *Next*, never to FastAPI. The API calls happen inside that request,
on the server. To see them you debug the server.

Files and where they run:

| Runs in | Files |
|---|---|
| **Next.js server** | `app/page.tsx`, `app/layout.tsx`, `app/day/[date]/page.tsx`, `app/_components/calendar-grid.tsx`, `show-block.tsx`, everything in `lib/` except what the filter header imports |
| **Browser** (and also once on the server, for the first HTML) | `app/_components/filter-header.tsx` — the only `"use client"` file — and the `packages/ui` combobox/select it renders |
| **FastAPI** | `apps/api/app/routers/*.py`, `app/sample_data.py` |

---

## 2. Setup

The configs live in `.vscode/launch.json` (Run and Debug panel, `⇧⌘D`):

| Config | Debugs | Port |
|---|---|---|
| `API: FastAPI` | the Python API (debugpy, no `--reload`) | 8000 |
| `Calendar: Next.js server` | the Node process (`pnpm --filter calendar dev --inspect`) | 3000 |
| `Calendar: browser` | a fresh Chrome, for client code | — |
| `Full stack: API + Next.js server` | the first two together | |

1. **Stop `make dev`** (Ctrl-C). The debug configs use the same ports, so both can't run.
2. Run **`Full stack: API + Next.js server`**. Wait for `✓ Ready` in the Next terminal.
3. Set your breakpoints (§3). Breakpoints in `.ts`/`.tsx` bind to the *server* config;
   breakpoints in `filter-header.tsx` bind to the *browser* config.
4. Open <http://localhost:3000/?venue=3> in any browser for the server-side stops. For client-side
   stops, also start **`Calendar: browser`** and use the Chrome window it opens.

It must be `next dev` (what the config runs), not `next start`: only dev serves source maps, so a
breakpoint in `page.tsx` would otherwise never bind.

---

## 3. The trace

Load `/?venue=3`. Set these breakpoints first (click the gutter next to the line; or search for the
quoted text, since line numbers drift). Each stop says what to look at and what it teaches.

### Server side (config: `Calendar: Next.js server`)

| # | File — the line to search for | Look at | What it teaches |
|---|---|---|---|
| 1 | `app/page.tsx` — `const filters = parseCalendarFilters(await searchParams);` | Hover `searchParams` (a Promise — Next 16 hands it over unresolved). **Step Over** the line, then hover `filters` → `{ venueIds: [3], artistIds: [], month: null }`. To see how: run again and **Step Into** `parseCalendarFilters`, then `parseIdList` in `lib/params.ts` | The URL is the state. This function body runs on the server on every request |
| 2 | `app/page.tsx` — `await Promise.all([` in `CalendarBody` | **Step Over** it, then hover `shows`, `venues`, `months` | Five API calls start together and are awaited together. You get plain objects back; there is no `useEffect`, no loading state |
| 3 | `lib/api.ts` — `return await fetchImpl(apiUrl(` in `send()` — make it a **conditional breakpoint**: right-click the gutter → *Add Conditional Breakpoint* → `path === "/shows"` | `path` = `"/shows"`, `query` = `{ start: undefined, end: undefined, venue_id: [3], artist_id: [] }`, `baseUrl` = `"http://localhost:8000"` | **This is the request the Network tab can't show.** Every API call in the app goes through this line |
| 4 | `lib/api.ts` — `return (await response.json()) as T;` in `readJson()` | `response.url` → `http://localhost:8000/shows?venue_id=3`; `response.status` | The exact URL that was sent, and the answer |
| 5 | `lib/calendar.ts` — `return rows;` at the end of `groupCalendar` | `rows` → 28 dates, each with `venues: [{ venue, shows }]` | The flat list from the API becomes the calendar's shape |
| 6 | `app/_components/calendar-grid.tsx` — `{rows.map((row) => {` — conditional: `row.date === "2026-10-07"` | `row.venues` → four columns | A Server Component is a function returning markup, run once per request |
| 7 | `lib/dates.ts` — `export function formatShowTime(` | `time` = `"01:00:00"`, and the return value `"1:00 AM Thu"` | The after-midnight rule |

**Gotcha — stop 3 fires five times per page load** (`/metro`, `/shows`, `/venues`, `/artists`,
`/calendar/months`), more on a 404 page. That is why the condition matters. Without it you will
press Continue (`F5`) over and over.

### FastAPI (config: `API: FastAPI`)

| # | File — the line to search for | Look at | What it teaches |
|---|---|---|---|
| 8 | `apps/api/app/routers/shows.py` — `shows = [s for s in data.SHOWS if start <= s.date <= end]` | `start`, `end` (defaulted by the server: "the server owns now"), then step to `if venue_id:` → `venue_id == [3]` | The other end of stop 3: the query string became typed Python parameters |

Stops 3 → 8 → 4 are one request, seen from both sides: Node sends `?venue_id=3`, Python receives
`venue_id=[3]`, Node reads back JSON.

### Browser side (config: `Calendar: browser`)

| # | File — the line to search for | Look at | What it teaches |
|---|---|---|---|
| 9 | `app/_components/filter-header.tsx` — `router.push(buildCalendarHref(next), { scroll: false });` | `next` = the new filters; step over `buildCalendarHref` and see the URL `"/?venue=1&venue=3"` it produces | Picking a filter doesn't filter anything: it **changes the URL**. Press Continue and watch stops 1–7 fire again in the server config |
| 10 | same file — `export function FilterHeader({` | It stops **twice per page load**: once under the server config (server-rendering the first HTML) and once under the browser config (hydration, making it interactive) | A `"use client"` component still renders on the server first. "Client" means "also runs in the browser", not "only" |

The loop to remember: **client picks a filter → `router.push` changes the URL → Next re-runs the
server page with the new `searchParams` → the Server Components stream back new markup.**

---

## 4. Seeing requests without a debugger

| Where | What you see |
|---|---|
| The Next terminal | Two kinds of line. **Ours:** per API call, written by `lib/api.ts`, a status line — `[api] GET /shows?venue_id=3 -> 200 in 41ms`, or `-> failed (timed out) in 5003ms` — and then a one-line summary of the body (below). **Next's:** one per page request — `GET /?venue=3 200 in 546ms (next.js: 170ms, application-code: 376ms)`. The `[api]` lines for a request print just above its `GET` line, so a page load reads like a trace: `/metro`, `/shows?venue_id=3`, `/artists`, `/venues`, `/calendar/months`, then the page |
| What came back (the body) | The summary line after each status line: `[api] GET /shows?venue_id=3 body (2.0 KB): 6 shows (2026-09-28..2026-10-25); 0 without start_time; 0 with empty lineup; 0 with no admission info`. For `/shows` it counts the gaps that usually mean extraction missed something; for any other route it lists small values, `key[N]` for lists, and the **null fields** apart at the end. Set **`LOG_API_BODIES=1`** in `apps/calendar/.env.local` and restart `next dev` to also get the full JSON, on one line: `[api] GET /shows?venue_id=3 body JSON: {…}` (cut at 4000 characters with a marker). Ignored in production builds. For a browsable tree instead of a log line, use `curl 'localhost:8000/shows?venue_id=3' \| jq` or `http://localhost:8000/docs` |
| The uvicorn terminal | One access-log line per API call — the same calls from the receiving end: `GET /shows?venue_id=3 HTTP/1.1" 200`. If an `[api]` line says `-> 200` here, FastAPI answered; if it says `failed`, nothing arrives here at all |
| `console.log` in a Server Component or `lib/` | Prints in the **Next terminal**, not the browser console |
| `console.log` in `filter-header.tsx` | Prints in the browser console, and once in the terminal (the server render) |
| The browser's Network tab | Only the document and the `_rsc` fetches (§1) |
| The React DevTools extension (not installed here) | The component tree and props of what runs in the browser, e.g. what the filter header receives |

---

## 5. Gotchas

- **A paused server is a frozen server.** While you're stopped at a server breakpoint, every request
  waits: the browser tab just spins. That isn't a hang; press Continue. (Disconnecting the debugger
  also releases it.) Breakpoints stay armed after the first hit.
- **The API client gives up after 5 seconds** (`TIMEOUT_MS` in `lib/api.ts`), and the timer keeps
  running while you're paused. Linger on a stop between the request and the end of reading the body
  (stops 3 → 4, or inside FastAPI at stop 8) and the page ends in the error screen with "API
  request timed out". That's you, not a bug. While learning, raise `TIMEOUT_MS` locally and don't
  commit it. *(Deduced from the code, not exercised.)*
- **Prefer the `[api]` log to a breakpoint for "what did the page ask for?".** It costs nothing, doesn't freeze the server, and isn't subject to the 5-second timeout. Reach for a breakpoint when you need to see *values* (`filters`, `rows`) rather than requests.
- **Hot reload and breakpoints:** editing a file re-compiles it and the breakpoint usually
  re-binds. If a breakpoint goes grey and stays grey, restart the Next config. Python has no
  reload here, so restart `API: FastAPI` after editing Python.
- **Two debug messages are normal.** `next dev --inspect` logs `Starting inspector on 127.0.0.1:9229
  failed: address already in use`. That comes from a helper process (Turbopack's compile pool) and is
  harmless; the process that serves your pages owns the port.
- **Source maps cover your code.** In a stack trace you'll also see generated names like
  `__TURBOPACK__imported__module__…`; those are compiled import aliases, and the frame still maps to
  your `.ts` file. The Debug Console can read variables in scope (`path`, `query`), but calling a
  function you merely *imported* (`apiUrl(...)`) may fail, because the compiler renamed it.
- **Prefer `justMyCode`/`skipFiles` as configured:** stepping stays in this repo's code instead of
  diving into `node_modules/next` or FastAPI internals.

---

## What was and wasn't verified

Verified on October 12, 2026 against this repo (Next 16.3.0, Turbopack, Node 24):

- `pnpm --filter calendar dev --inspect` starts the server with a debugger on port 9229; the
  process that serves the pages holds it.
- Over the debugger protocol, a breakpoint set on the compiled `lib/api.ts` call **hit** on a real
  request, paused with the call stack `send ← get ← getMetro ← getMetroOrNull …` and the variables
  `path = "/metro"`, `baseUrl = "http://localhost:8000"` readable.
- Turbopack's source maps point back to the real files — server chunks to
  `apps/calendar/lib/api.ts` and client chunks to `apps/calendar/app/_components/filter-header.tsx`
  (absolute `file://` paths, so no path-mapping overrides are needed).
- The Network-tab table in §1, and the five API calls per page load (from the code: five getters
  behind one `Promise.all`, with the layout's metro call shared).

**Not verified: the VS Code UI itself** (the launch configs were checked to be valid JSONC and to
use commands I ran, not run from the Debug panel), the `Calendar: browser` config, the Python
debugger, the 5-second timeout behaviour, and stop 10's double hit (the server render is confirmed —
the chips are in the server-sent HTML — but I didn't watch it stop twice). If a breakpoint won't bind, the first things to check
are that the right config is running for that file (§2, step 3) and that it's `next dev`.
